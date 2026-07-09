from __future__ import annotations

import asyncio
import json
import os
import queue
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from fastmcp import Client as FastMCPClient
from sqlalchemy import create_engine
from starlette.websockets import WebSocketDisconnect

from src.control_plane.app import _build_verifier, create_control_plane_app
from src.control_plane.auth.context import (
    AuthorizationContext,
    clear_authorization_context,
    set_authorization_context,
)
from src.control_plane.auth.jwt_verifier import TokenPrincipal
from src.control_plane.auth.service import AuthorizationService
from src.control_plane.execution_targets import (
    LoopbackExecutionTarget,
    TargetToolRequest,
)
from src.control_plane.models import ControlPlaneBase
from src.control_plane.redis_keys import RedisKey, RedisTtl
from src.control_plane.relay.protocol import (
    RelayHeartbeat,
    RelayHeartbeatFrame,
    RelayInvocationResultFrame,
    RelayVersionMetadata,
    build_handshake_claims,
)
from src.hosted_mcp.execution_target_handlers import (
    build_execution_target_tool_handlers,
)
from src.hosted_mcp.server import build_server as real_build_server
from src.services.desktop_relay_client import DesktopRelayClient
from src.services.relay_key_service import RelayKeyService


class InMemoryKeyStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


KEY_SERVICE = RelayKeyService(InMemoryKeyStore())
KEYPAIR = KEY_SERVICE.generate_or_load_keypair()
PUBLIC_KEY = KEYPAIR.public_key_pem
OTHER_KEY_SERVICE = RelayKeyService(InMemoryKeyStore())
OTHER_KEYPAIR = OTHER_KEY_SERVICE.generate_or_load_keypair()
THIRD_KEY_SERVICE = RelayKeyService(InMemoryKeyStore())
THIRD_KEYPAIR = THIRD_KEY_SERVICE.generate_or_load_keypair()
PRIVATE_KEY = (
    "-----BEGIN ED25519 PRIVATE KEY-----\nsecret\n-----END ED25519 PRIVATE KEY-----\n"
)
INVALID_PUBLIC_KEY = "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----\n"
VERSION = RelayVersionMetadata(
    shipagent_core_version="1.0.0",
    registry_contract_version="registry-v1",
    ups_boundary_contract_version="ups-v1",
    capabilities=["rate_shipment"],
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, *keys: str):
        deleted = 0
        for key in keys:
            if key in self.values:
                deleted += 1
            self.values.pop(key, None)
            self.ttls.pop(key, None)
        return deleted

    async def expire(self, key: str, seconds: int):
        if key not in self.values:
            return False
        self.ttls[key] = seconds
        return True

    async def eval(self, script: str, numkeys: int, *keys_and_args: str):
        if numkeys == 1 and ("SA_RATE_LIMIT" in script or "SA_LOOP_GUARD" in script):
            key = keys_and_args[0]
            count = int(self.values.get(key, "0")) + 1
            self.values[key] = str(count)
            self.ttls[key] = int(keys_and_args[-1])
            return count
        if numkeys == 1:
            key = keys_and_args[0]
            self.ttls.pop(key, None)
            return self.values.pop(key, None)
        if numkeys == 4 and len(keys_and_args) == 5:
            (
                device_key,
                session_key,
                heartbeat_key,
                active_target_key,
                device_payload,
            ) = keys_and_args
            current_payload = self.values.get(device_key)
            if current_payload is None:
                return "missing"
            if isinstance(current_payload, bytes):
                current_payload = current_payload.decode("utf-8")
            current_device = json.loads(current_payload)
            if current_device.get("revoked") is True:
                await self._delete_current_liveness(
                    session_key, heartbeat_key, active_target_key
                )
                return "revoked"
            self.values[device_key] = device_payload
            await self._delete_current_liveness(
                session_key, heartbeat_key, active_target_key
            )
            return "ok"
        if numkeys == 4 and len(keys_and_args) == 4:
            device_key, session_key, heartbeat_key, active_target_key = keys_and_args
            current_payload = self.values.get(device_key)
            if current_payload is None:
                return "missing"
            if isinstance(current_payload, bytes):
                current_payload = current_payload.decode("utf-8")
            current_device = json.loads(current_payload)
            current_device["revoked"] = True
            revoked_payload = json.dumps(current_device)
            self.values[device_key] = revoked_payload
            await self._delete_current_liveness(
                session_key, heartbeat_key, active_target_key
            )
            return revoked_payload
        if numkeys == 3 and len(keys_and_args) == 7:
            (
                session_key,
                heartbeat_key,
                active_target_key,
                session_payload,
                heartbeat_payload,
                publish_active,
                ttl,
            ) = keys_and_args
            self.values[session_key] = session_payload
            self.values[heartbeat_key] = heartbeat_payload
            self.ttls[session_key] = int(ttl)
            self.ttls[heartbeat_key] = int(ttl)
            if publish_active == "1":
                self.values[active_target_key] = session_payload
                self.ttls[active_target_key] = int(ttl)
            return 1
        if numkeys == 3 and len(keys_and_args) == 5:
            (
                session_key,
                heartbeat_key,
                active_target_key,
                session_snapshot,
                device_id,
            ) = keys_and_args
            current_session = self.values.get(session_key)
            if session_snapshot == "":
                if current_session is not None:
                    return 0
                deleted = await self.delete(heartbeat_key)
                active_payload = self.values.get(active_target_key)
                if active_payload is not None:
                    if isinstance(active_payload, bytes):
                        active_payload = active_payload.decode("utf-8")
                    active = json.loads(active_payload)
                    if active.get("device_id") == device_id:
                        deleted += await self.delete(active_target_key)
                return deleted
            if current_session != session_snapshot:
                return 0
            deleted = await self.delete(session_key, heartbeat_key)
            active_payload = self.values.get(active_target_key)
            if active_payload is not None:
                if isinstance(active_payload, bytes):
                    active_payload = active_payload.decode("utf-8")
                active = json.loads(active_payload)
                session = json.loads(session_snapshot)
                if active.get("device_id") == session.get("device_id") and active.get(
                    "relay_session_id"
                ) == session.get("relay_session_id"):
                    deleted += await self.delete(active_target_key)
            return deleted
        if numkeys == 4:
            (
                device_key,
                session_key,
                heartbeat_key,
                active_target_key,
                expected_fingerprint,
                expected_public_key_pem,
                session_payload,
                heartbeat_payload,
                ttl,
            ) = keys_and_args
            device_payload = self.values.get(device_key)
            if device_payload is None:
                return "missing"
            if isinstance(device_payload, bytes):
                device_payload = device_payload.decode("utf-8")
            device = json.loads(device_payload)
            if device.get("revoked") is True:
                return "revoked"
            if (
                device.get("fingerprint") != expected_fingerprint
                or device.get("public_key_pem") != expected_public_key_pem
            ):
                return "stale"
            self.values[session_key] = session_payload
            self.values[heartbeat_key] = heartbeat_payload
            self.values[active_target_key] = session_payload
            self.ttls[session_key] = int(ttl)
            self.ttls[heartbeat_key] = int(ttl)
            self.ttls[active_target_key] = int(ttl)
            return "ok"
        if numkeys == 3 and len(keys_and_args) == 8:
            (
                session_key,
                heartbeat_key,
                active_target_key,
                expected_relay_session_id,
                heartbeat_payload,
                ttl,
                account_id,
                device_id,
            ) = keys_and_args
            payload = self.values.get(session_key)
            if payload is None or heartbeat_key not in self.values:
                return 0
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            session = json.loads(payload)
            if (
                session.get("relay_session_id") != expected_relay_session_id
                or session.get("account_id") != account_id
                or session.get("device_id") != device_id
            ):
                return 0
            self.values[heartbeat_key] = heartbeat_payload
            self.ttls[session_key] = int(ttl)
            self.ttls[heartbeat_key] = int(ttl)
            active_payload = self.values.get(active_target_key)
            if active_payload is not None:
                if isinstance(active_payload, bytes):
                    active_payload = active_payload.decode("utf-8")
                active = json.loads(active_payload)
                if (
                    active.get("device_id") == session.get("device_id")
                    and active.get("relay_session_id") == expected_relay_session_id
                ):
                    self.ttls[active_target_key] = int(ttl)
            return 1
        session_key, heartbeat_key, active_target_key, expected_relay_session_id = (
            keys_and_args
        )
        payload = self.values.get(session_key)
        if payload is None:
            return 0
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        try:
            session = json.loads(payload)
        except json.JSONDecodeError:
            return await self.delete(session_key, heartbeat_key)
        if session.get("relay_session_id") != expected_relay_session_id:
            return 0
        active_payload = self.values.get(active_target_key)
        if active_payload is not None:
            if isinstance(active_payload, bytes):
                active_payload = active_payload.decode("utf-8")
            active = json.loads(active_payload)
            if (
                active.get("device_id") == session.get("device_id")
                and active.get("relay_session_id") == expected_relay_session_id
            ):
                return await self.delete(session_key, heartbeat_key, active_target_key)
        return await self.delete(session_key, heartbeat_key)

    async def _delete_current_liveness(
        self,
        session_key: str,
        heartbeat_key: str,
        active_target_key: str,
    ):
        payload = self.values.get(session_key)
        if payload is None:
            return await self.delete(session_key, heartbeat_key)
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        session = json.loads(payload)
        active_payload = self.values.get(active_target_key)
        if active_payload is not None:
            if isinstance(active_payload, bytes):
                active_payload = active_payload.decode("utf-8")
            active = json.loads(active_payload)
            if active.get("device_id") == session.get("device_id") and active.get(
                "relay_session_id"
            ) == session.get("relay_session_id"):
                return await self.delete(session_key, heartbeat_key, active_target_key)
        return await self.delete(session_key, heartbeat_key)


class _TokenVerifier:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def verify(self, token: str) -> TokenPrincipal:
        scopes = {"jobs:read", "shipments:preview"}
        if token == "status-token":
            scopes.add("shipagent.status")
        if token == "relay-manage-token":
            scopes.add("relay:device:manage")
        if token == "relay-device-manage-no-auth-time-token":
            scopes.add("relay:device:manage")
        auth_time = datetime.now(UTC) if token == "relay-manage-token" else None
        if token == "stale-relay-device-manage-token":
            scopes.add("relay:device:manage")
            auth_time = datetime(2020, 1, 1, tzinfo=UTC)
        if token == "future-relay-device-manage-token":
            scopes.add("relay:device:manage")
            auth_time = datetime.now(UTC) + timedelta(minutes=10)
        if token == "near-future-relay-device-manage-token":
            scopes.add("relay:device:manage")
            auth_time = datetime.now(UTC) + timedelta(minutes=1)
        return TokenPrincipal(
            subject="auth0|owner-1",
            client_id="chatgpt-client",
            scopes=frozenset(scopes),
            auth_time=auth_time,
        )


class _AuthorizationService(AuthorizationService):
    async def resolve(
        self,
        *,
        subject: str,
        client_id: str,
        scopes: set[str],
        auth_time: datetime | None = None,
    ) -> AuthorizationContext:
        return AuthorizationContext(
            account_id="acct-1",
            provider_connection_id="pc-1",
            provider_surface="chatgpt",
            subject=subject,
            client_id=client_id,
            scopes=frozenset(scopes),
            auth_time=auth_time,
        )


class _RelayTestClientConnection:
    def __init__(self, websocket) -> None:
        self._websocket = websocket

    async def send_json(self, payload: dict[str, object]) -> None:
        await asyncio.to_thread(self._websocket.send_json, payload)

    async def receive_json(self) -> dict[str, object]:
        return await asyncio.to_thread(self._websocket.receive_json)


class _RelayTestClientConnectionContext:
    def __init__(self, client: TestClient, path: str) -> None:
        self._client = client
        self._path = path
        self._websocket_context = None

    async def __aenter__(self) -> _RelayTestClientConnection:
        self._websocket_context = self._client.websocket_connect(self._path)
        websocket = self._websocket_context.__enter__()
        return _RelayTestClientConnection(websocket)

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._websocket_context is not None:
            self._websocket_context.__exit__(exc_type, exc, tb)
            self._websocket_context = None


class _RelayTestClientTransport:
    def __init__(self, client: TestClient) -> None:
        self._client = client

    def connect(self, url: str) -> _RelayTestClientConnectionContext:
        return _RelayTestClientConnectionContext(self._client, url)


class SpyRelayInvocationBroker:
    def __init__(self) -> None:
        self.disconnect_calls: list[dict[str, object]] = []

    async def disconnect_device(
        self,
        *,
        account_id: str,
        device_id: str,
        code: int = 1008,
        reason: str = "relay device disconnected",
    ) -> None:
        self.disconnect_calls.append(
            {
                "account_id": account_id,
                "device_id": device_id,
                "code": code,
                "reason": reason,
            }
        )


def _build_app(monkeypatch, *, execution_target=None, relay_invocation_broker=None):
    redis = FakeRedis()
    fd, database_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database_url = f"sqlite+aiosqlite:///{database_path}"
    sync_engine = create_engine(database_url.replace("+aiosqlite", ""))
    try:
        ControlPlaneBase.metadata.create_all(sync_engine)
    finally:
        sync_engine.dispose()
    monkeypatch.setenv("SHIPAGENT_PUBLIC_BASE_URL", "https://dev-mcp.shipagent.app/")
    monkeypatch.setenv("SHIPAGENT_AUTH0_ISSUER", "https://tenant.us.auth0.com/")
    monkeypatch.setenv("SHIPAGENT_AUTH0_AUDIENCE", "https://dev-mcp.shipagent.app")
    monkeypatch.setenv("SHIPAGENT_DATABASE_URL", database_url)
    monkeypatch.setenv("SHIPAGENT_REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setattr("src.control_plane.app.Auth0TokenVerifier", _TokenVerifier)
    monkeypatch.setattr(
        "src.control_plane.app.AuthorizationService", _AuthorizationService
    )
    _build_verifier.cache_clear()
    return create_control_plane_app(
        redis_client=redis,
        execution_target=execution_target,
        relay_invocation_broker=relay_invocation_broker,
    ), redis


class RecordingTarget:
    def __init__(self, result: dict[str, object]) -> None:
        self._result = result
        self.requests: list[TargetToolRequest] = []

    async def invoke(self, request: TargetToolRequest) -> dict[str, object]:
        self.requests.append(request)
        return self._result


@pytest.mark.asyncio
async def test_status_handler_builds_full_target_tool_request() -> None:
    target = RecordingTarget(
        result={
            "status": "ready",
            "executionTarget": {
                "state": "ready",
                "target_id": "device-1",
                "capabilities": [],
            },
        }
    )
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset(),
    )

    result = await build_execution_target_tool_handlers(target)["get_shipagent_status"](
        context,
        {"correlation_id": "corr-1"},
    )

    assert target.requests == [
        TargetToolRequest(
            account_id="acct-1",
            provider_connection_id="pc-1",
            provider_surface="chatgpt",
            tool_name="get_shipagent_status",
            arguments={"correlation_id": "corr-1"},
            correlation_id="corr-1",
        )
    ]
    assert result["status"] == "ready"


async def _run_status_tool(server) -> dict[str, object]:
    tools = await server.get_tools()
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )
    token = set_authorization_context(context)
    try:
        result = await tools["get_shipagent_status"].run({"correlation_id": "corr-1"})
    finally:
        clear_authorization_context(token)
    return result.structured_content


async def _run_status_tool_over_http(
    base_url: str,
    *,
    correlation_id: str = "corr-1",
) -> dict[str, object]:
    async with FastMCPClient(
        f"{base_url}/mcp/",
        auth="status-token",
        timeout=2,
        init_timeout=2,
    ) as client:
        result = await client.call_tool(
            "get_shipagent_status",
            {"correlation_id": correlation_id},
        )
    structured = result.structured_content
    assert structured is not None
    return structured


async def _poll_status_tool_over_http(
    base_url: str,
    *,
    expected_state: str,
    relay_process: subprocess.Popen[str] | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_status: dict[str, object] | None = None
    last_error: Exception | None = None
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        if relay_process is not None and relay_process.poll() is not None:
            stderr = relay_process.stderr.read() if relay_process.stderr else ""
            raise AssertionError(
                f"relay process exited before {expected_state} status: {stderr}"
            )
        try:
            last_status = await _run_status_tool_over_http(
                base_url,
                correlation_id=f"poll-{expected_state}-{attempt}",
            )
            execution_target = last_status.get("executionTarget")
            if (
                isinstance(execution_target, dict)
                and execution_target.get("state") == expected_state
            ):
                return last_status
        except Exception as exc:  # pragma: no cover - surfaced in assertion below
            last_error = exc
        await asyncio.sleep(0.2)
    raise AssertionError(
        f"timed out waiting for {expected_state} status; "
        f"last_status={last_status!r} last_error={last_error!r}"
    )


def _start_uvicorn_server(app, *, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            lifespan="on",
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, name="relay-test-uvicorn", daemon=True)
    thread.start()
    return server, thread


def _wait_for_http_server(base_url: str, *, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(
                f"{base_url}/.well-known/oauth-protected-resource",
                timeout=0.2,
            )
            if response.status_code == 200:
                return
        except Exception as exc:  # pragma: no cover - surfaced in assertion below
            last_error = exc
        time.sleep(0.05)
    raise AssertionError(f"control-plane server did not start: {last_error!r}")


def _stop_uvicorn_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=5)
    assert not thread.is_alive()


def _start_desktop_relay_process(
    *,
    relay_url: str,
    account_id: str,
    device_id: str,
    private_key_pem: str,
) -> subprocess.Popen[str]:
    script = textwrap.dedent(
        """
        import asyncio
        import json
        import os
        import sys

        from src.services.desktop_relay_client import (
            DesktopRelayClient,
            WebSocketRelayTransport,
        )
        from src.services.relay_key_service import RelayKeyService


        class EnvStore:
            def get(self, key):
                return os.environ.get(key)

            def set(self, key, value):
                os.environ[key] = value

            def delete(self, key):
                os.environ.pop(key, None)


        async def main():
            config = json.loads(os.environ["SHIPAGENT_RELAY_PROCESS_CONFIG"])
            client = DesktopRelayClient(
                relay_url=config["relay_url"],
                account_id=config["account_id"],
                device_id=config["device_id"],
                key_service=RelayKeyService(EnvStore()),
                transport=WebSocketRelayTransport(allow_insecure_loopback=True),
                heartbeat_interval_seconds=0.2,
            )
            accepted = await client.start()
            print(accepted.model_dump_json(), flush=True)
            await asyncio.to_thread(sys.stdin.readline)
            await client.stop()


        asyncio.run(main())
        """
    )
    env = os.environ.copy()
    env["SHIPAGENT_RELAY_PROCESS_CONFIG"] = json.dumps(
        {
            "relay_url": relay_url,
            "account_id": account_id,
            "device_id": device_id,
        }
    )
    env["SHIPAGENT_RELAY_DEVICE_PRIVATE_KEY"] = private_key_pem
    return subprocess.Popen(
        [sys.executable, "-u", "-c", script],
        cwd=os.getcwd(),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _read_relay_process_json_line(
    relay_process: subprocess.Popen[str],
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, object]:
    assert relay_process.stdout is not None
    lines: queue.Queue[str] = queue.Queue(maxsize=1)

    def read_line() -> None:
        lines.put(relay_process.stdout.readline())

    threading.Thread(target=read_line, name="relay-process-stdout", daemon=True).start()
    try:
        line = lines.get(timeout=timeout_seconds)
    except queue.Empty as exc:
        stderr = relay_process.stderr.read() if relay_process.poll() is not None else ""
        raise AssertionError(
            f"relay process did not report readiness: {stderr}"
        ) from exc
    if not line:
        stderr = relay_process.stderr.read() if relay_process.stderr else ""
        raise AssertionError(f"relay process exited without readiness: {stderr}")
    payload = json.loads(line)
    assert isinstance(payload, dict)
    return payload


def test_register_device_returns_public_device_record(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_id"] == "acct-1"
    assert payload["device_id"].startswith("relay_device_")
    assert payload["fingerprint"].startswith("sha256:")
    assert payload["revoked"] is False
    assert "private_key" not in response.text
    assert "private_key_pem" not in response.text


def test_register_device_rejects_duplicate_fingerprint(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        first = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        )
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Warehouse Mac", "public_key_pem": PUBLIC_KEY},
        )

    assert first.status_code == 200
    assert response.status_code == 400
    assert response.json() == {"detail": "Relay request rejected"}
    assert "fingerprint" not in response.text


def test_list_devices_returns_public_device_records(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        first = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        second = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={
                "device_name": "Warehouse Mac",
                "public_key_pem": OTHER_KEYPAIR.public_key_pem,
            },
        ).json()
        response = client.get(
            "/relay/devices",
            headers={"Authorization": "Bearer relay-manage-token"},
        )

    assert response.status_code == 200
    assert response.json() == [first, second]
    assert "public_key" not in response.text
    assert "private_key" not in response.text
    assert "private_key_pem" not in response.text


def test_list_devices_rejects_provider_token_without_relay_manage_scope(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        response = client.get(
            "/relay/devices",
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 403


def test_set_active_device_selects_public_device_record(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        first = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        second = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={
                "device_name": "Warehouse Mac",
                "public_key_pem": OTHER_KEYPAIR.public_key_pem,
            },
        ).json()
        response = client.post(
            f"/relay/devices/{second['device_id']}/set-active",
            headers={"Authorization": "Bearer relay-manage-token"},
        )
        listed = client.get(
            "/relay/devices",
            headers={"Authorization": "Bearer relay-manage-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_id"] == "acct-1"
    assert payload["device_id"] == second["device_id"]
    assert payload["fingerprint"] == second["fingerprint"]
    assert payload["revoked"] is False
    assert payload["active"] is True
    assert [(device["device_id"], device["active"]) for device in listed.json()] == [
        (first["device_id"], False),
        (second["device_id"], True),
    ]
    assert "public_key" not in response.text
    assert "private_key" not in response.text
    assert "private_key_pem" not in response.text


def test_set_active_missing_device_returns_404(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/relay/devices/missing-device/set-active",
            headers={"Authorization": "Bearer relay-manage-token"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Relay device not found"}


def test_set_active_rejects_revoked_device(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        client.post(
            f"/relay/devices/{registered['device_id']}/revoke",
            headers={"Authorization": "Bearer relay-manage-token"},
        )
        response = client.post(
            f"/relay/devices/{registered['device_id']}/set-active",
            headers={"Authorization": "Bearer relay-manage-token"},
        )

    assert response.status_code == 410
    assert response.json() == {"detail": "Relay device revoked"}


def test_set_active_rejects_provider_token_without_relay_manage_scope(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        response = client.post(
            f"/relay/devices/{registered['device_id']}/set-active",
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 403


def test_set_active_rejects_stale_recent_auth(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        response = client.post(
            f"/relay/devices/{registered['device_id']}/set-active",
            headers={"Authorization": "Bearer stale-relay-device-manage-token"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "recent_auth_required"}


def test_device_management_routes_disconnect_replaced_live_sessions(
    monkeypatch,
) -> None:
    broker = SpyRelayInvocationBroker()
    app, _redis = _build_app(monkeypatch, relay_invocation_broker=broker)

    with TestClient(app) as client:
        first = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        second = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={
                "device_name": "Warehouse Mac",
                "public_key_pem": OTHER_KEYPAIR.public_key_pem,
            },
        ).json()

        broker.disconnect_calls.clear()
        set_active = client.post(
            f"/relay/devices/{second['device_id']}/set-active",
            headers={"Authorization": "Bearer relay-manage-token"},
        )
        assert set_active.status_code == 200
        assert broker.disconnect_calls == [
            {
                "account_id": "acct-1",
                "device_id": first["device_id"],
                "code": 1008,
                "reason": "relay device policy changed",
            }
        ]

        broker.disconnect_calls.clear()
        rotate = client.post(
            f"/relay/devices/{second['device_id']}/rotate-key",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"public_key_pem": THIRD_KEYPAIR.public_key_pem},
        )
        assert rotate.status_code == 200
        assert broker.disconnect_calls == [
            {
                "account_id": "acct-1",
                "device_id": second["device_id"],
                "code": 1008,
                "reason": "relay device policy changed",
            }
        ]

        broker.disconnect_calls.clear()
        revoke = client.post(
            f"/relay/devices/{second['device_id']}/revoke",
            headers={"Authorization": "Bearer relay-manage-token"},
        )
        assert revoke.status_code == 200
        assert broker.disconnect_calls == [
            {
                "account_id": "acct-1",
                "device_id": second["device_id"],
                "code": 1008,
                "reason": "relay device policy changed",
            }
        ]

        broker.disconnect_calls.clear()
        unlink = client.post(
            f"/relay/devices/{first['device_id']}/unlink",
            headers={"Authorization": "Bearer relay-manage-token"},
        )
        assert unlink.status_code == 200
        assert broker.disconnect_calls == [
            {
                "account_id": "acct-1",
                "device_id": first["device_id"],
                "code": 1008,
                "reason": "relay device policy changed",
            }
        ]


def test_control_plane_app_binds_only_status_mcp_tool(monkeypatch) -> None:
    captured = {}

    def capture_build_server(**kwargs):
        server = real_build_server(**kwargs)
        captured["server"] = server
        captured["handler_names"] = set((kwargs.get("tool_handlers") or {}).keys())
        captured["request_controls"] = kwargs.get("request_controls")
        return server

    monkeypatch.setattr("src.control_plane.app.build_server", capture_build_server)

    _app, _redis = _build_app(monkeypatch)
    tools = asyncio.run(captured["server"].get_tools())

    assert captured["handler_names"] == {"get_shipagent_status"}
    assert captured["request_controls"] is not None
    assert set(tools) == {"get_shipagent_status"}


def test_register_device_rejects_private_key_material_with_validation_error(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PRIVATE_KEY},
        )

    assert response.status_code == 422
    assert PRIVATE_KEY not in response.text
    assert "PRIVATE KEY" not in response.text
    assert "input" not in response.json()["detail"][0]


def test_register_device_rejects_invalid_public_key_with_validation_error(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": INVALID_PUBLIC_KEY},
        )

    assert response.status_code == 422
    assert INVALID_PUBLIC_KEY not in response.text
    assert "abc" not in response.text
    assert "input" not in response.json()["detail"][0]


def test_register_device_rejects_extra_private_key_field_without_echoing_key_name(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)
    malicious_key = "-----BEGIN PRIVATE KEY-----"

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={
                "device_name": "Dock Mac",
                "public_key_pem": PUBLIC_KEY,
                malicious_key: "attacker-controlled",
            },
        )

    assert response.status_code == 422
    assert malicious_key not in response.text
    assert "PRIVATE KEY" not in response.text
    assert "input" not in response.json()["detail"][0]
    assert "loc" not in response.json()["detail"][0]


def test_register_device_rejects_provider_token_without_relay_manage_scope(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        )

    assert response.status_code == 403


def test_register_device_checks_scope_before_public_key_validation(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer valid-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PRIVATE_KEY},
        )

    assert response.status_code == 403
    assert PRIVATE_KEY not in response.text


def test_register_device_rejects_stale_recent_auth(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer stale-relay-device-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "recent_auth_required"}


def test_register_device_checks_recent_auth_before_public_key_validation(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer stale-relay-device-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PRIVATE_KEY},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "recent_auth_required"}
    assert PRIVATE_KEY not in response.text


def test_register_device_rejects_missing_recent_auth_time(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-device-manage-no-auth-time-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "recent_auth_required"}


def test_register_device_rejects_future_recent_auth_time(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer future-relay-device-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "recent_auth_required"}


def test_register_device_rejects_near_future_recent_auth_time(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer near-future-relay-device-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "recent_auth_required"}


def test_rotate_key_returns_updated_fingerprint(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)
    rotated_key = OTHER_KEYPAIR.public_key_pem

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        response = client.post(
            f"/relay/devices/{registered['device_id']}/rotate-key",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"public_key_pem": rotated_key},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_id"] == "acct-1"
    assert payload["device_id"] == registered["device_id"]
    assert payload["fingerprint"] != registered["fingerprint"]
    assert payload["revoked"] is False
    assert "private_key" not in response.text
    assert "private_key_pem" not in response.text


def test_rotate_key_rejects_private_key_material_with_validation_error(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        response = client.post(
            f"/relay/devices/{registered['device_id']}/rotate-key",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"public_key_pem": PRIVATE_KEY},
        )

    assert response.status_code == 422
    assert PRIVATE_KEY not in response.text
    assert "PRIVATE KEY" not in response.text
    assert "input" not in response.json()["detail"][0]


def test_rotate_key_missing_device_returns_404(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/relay/devices/missing-device/rotate-key",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"public_key_pem": PUBLIC_KEY},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Relay device not found"}


def test_rotate_key_rejects_provider_token_without_relay_manage_scope(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        response = client.post(
            f"/relay/devices/{registered['device_id']}/rotate-key",
            headers={"Authorization": "Bearer valid-token"},
            json={"public_key_pem": OTHER_KEYPAIR.public_key_pem},
        )

    assert response.status_code == 403


def test_rotate_key_checks_scope_before_public_key_validation(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        response = client.post(
            f"/relay/devices/{registered['device_id']}/rotate-key",
            headers={"Authorization": "Bearer valid-token"},
            json={"public_key_pem": PRIVATE_KEY},
        )

    assert response.status_code == 403
    assert PRIVATE_KEY not in response.text


def test_rotate_key_rejects_stale_recent_auth(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        response = client.post(
            f"/relay/devices/{registered['device_id']}/rotate-key",
            headers={"Authorization": "Bearer stale-relay-device-manage-token"},
            json={"public_key_pem": OTHER_KEYPAIR.public_key_pem},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "recent_auth_required"}


def test_rotate_key_checks_recent_auth_before_public_key_validation(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        response = client.post(
            f"/relay/devices/{registered['device_id']}/rotate-key",
            headers={"Authorization": "Bearer stale-relay-device-manage-token"},
            json={"public_key_pem": PRIVATE_KEY},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "recent_auth_required"}
    assert PRIVATE_KEY not in response.text


def test_revoke_device_returns_revoked_record(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        response = client.post(
            f"/relay/devices/{registered['device_id']}/revoke",
            headers={"Authorization": "Bearer relay-manage-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_id"] == "acct-1"
    assert payload["device_id"] == registered["device_id"]
    assert payload["fingerprint"] == registered["fingerprint"]
    assert payload["revoked"] is True
    assert "private_key" not in response.text
    assert "private_key_pem" not in response.text


def test_unlink_device_returns_revoked_public_record(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        client.post(
            f"/relay/devices/{registered['device_id']}/set-active",
            headers={"Authorization": "Bearer relay-manage-token"},
        )
        response = client.post(
            f"/relay/devices/{registered['device_id']}/unlink",
            headers={"Authorization": "Bearer relay-manage-token"},
        )
        listed = client.get(
            "/relay/devices",
            headers={"Authorization": "Bearer relay-manage-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_id"] == "acct-1"
    assert payload["device_id"] == registered["device_id"]
    assert payload["fingerprint"] == registered["fingerprint"]
    assert payload["revoked"] is True
    assert payload["active"] is False
    assert listed.json() == [payload]
    assert "public_key" not in response.text
    assert "private_key" not in response.text
    assert "private_key_pem" not in response.text


def test_unlink_device_rejects_stale_recent_auth(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        response = client.post(
            f"/relay/devices/{registered['device_id']}/unlink",
            headers={"Authorization": "Bearer stale-relay-device-manage-token"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "recent_auth_required"}


def test_unlink_device_rejects_already_revoked_device(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        client.post(
            f"/relay/devices/{registered['device_id']}/revoke",
            headers={"Authorization": "Bearer relay-manage-token"},
        )
        response = client.post(
            f"/relay/devices/{registered['device_id']}/unlink",
            headers={"Authorization": "Bearer relay-manage-token"},
        )

    assert response.status_code == 410
    assert response.json() == {"detail": "Relay device revoked"}


def test_revoke_missing_device_returns_404(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/relay/devices/missing-device/revoke",
            headers={"Authorization": "Bearer relay-manage-token"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Relay device not found"}


def test_revoke_device_rejects_provider_token_without_relay_manage_scope(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        response = client.post(
            f"/relay/devices/{registered['device_id']}/revoke",
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 403


def test_revoke_device_rejects_stale_recent_auth(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        response = client.post(
            f"/relay/devices/{registered['device_id']}/revoke",
            headers={"Authorization": "Bearer stale-relay-device-manage-token"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "recent_auth_required"}


def test_register_device_requires_authorization(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/relay/devices/register",
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        )

    assert response.status_code == 401


def test_connect_websocket_challenges_then_accepts_claims(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            challenge = websocket.receive_json()
            claims = build_handshake_claims(
                device_id=registered["device_id"],
                account_id="acct-1",
                relay_session_id=challenge["relay_session_id"],
                nonce=challenge["nonce"],
                version=VERSION,
            )
            signed = KEY_SERVICE.sign_handshake_claims(claims)
            websocket.send_json(signed.model_dump(mode="json"))
            accepted = websocket.receive_json()

    assert accepted == {
        "type": "relay.authenticated",
        "relay_session_id": challenge["relay_session_id"],
        "execution_target_id": f"relay:{registered['device_id']}",
        "state": "ready",
    }


def test_desktop_relay_client_connection_makes_hosted_status_ready(
    monkeypatch,
) -> None:
    captured = {}

    def capture_build_server(**kwargs):
        server = real_build_server(**kwargs)
        captured["server"] = server
        return server

    monkeypatch.setattr("src.control_plane.app.build_server", capture_build_server)
    app, _redis = _build_app(monkeypatch)

    async def run_scenario(client: TestClient, device_id: str) -> None:
        relay_client = DesktopRelayClient(
            relay_url="/relay/connect",
            account_id="acct-1",
            device_id=device_id,
            key_service=KEY_SERVICE,
            transport=_RelayTestClientTransport(client),
        )

        await relay_client.start()
        try:
            ready_status = await _run_status_tool(captured["server"])
        finally:
            await relay_client.stop()
        offline_status = await _run_status_tool(captured["server"])

        assert ready_status == {
            "status": "ready",
            "executionTarget": {
                "state": "ready",
                "target_id": f"relay:{device_id}",
                "capabilities": ["rate_shipment", "get_shipagent_status"],
                "message": None,
            },
        }
        assert offline_status == {
            "status": "offline",
            "executionTarget": {
                "state": "offline",
                "target_id": None,
                "capabilities": [],
                "message": "No active execution target connected.",
            },
        }

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        asyncio.run(run_scenario(client, registered["device_id"]))


def test_hosted_status_returns_offline_when_only_stale_redis_liveness_remains(
    monkeypatch,
) -> None:
    captured = {}

    def capture_build_server(**kwargs):
        server = real_build_server(**kwargs)
        captured["server"] = server
        return server

    monkeypatch.setattr("src.control_plane.app.build_server", capture_build_server)
    app, redis = _build_app(monkeypatch)

    async def run_scenario(client: TestClient, device_id: str) -> None:
        relay_client = DesktopRelayClient(
            relay_url="/relay/connect",
            account_id="acct-1",
            device_id=device_id,
            key_service=KEY_SERVICE,
            transport=_RelayTestClientTransport(client),
        )

        await relay_client.start()
        session_key = RedisKey.relay_session(device_id)
        heartbeat_key = RedisKey.relay_heartbeat(device_id)
        active_target_key = RedisKey.relay_active_target("acct-1")
        stale_values = {
            session_key: redis.values[session_key],
            heartbeat_key: redis.values[heartbeat_key],
            active_target_key: redis.values[active_target_key],
        }
        await relay_client.stop()
        redis.values.update(stale_values)

        status = await _run_status_tool(captured["server"])

        assert status == {
            "status": "offline",
            "executionTarget": {
                "state": "offline",
                "target_id": None,
                "capabilities": [],
                "message": "No active execution target connected.",
            },
        }

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        asyncio.run(run_scenario(client, registered["device_id"]))


def test_desktop_relay_process_makes_hosted_http_status_ready_then_offline(
    monkeypatch,
    unused_tcp_port: int,
) -> None:
    app, _redis = _build_app(monkeypatch)
    base_url = f"http://127.0.0.1:{unused_tcp_port}"
    server, thread = _start_uvicorn_server(app, port=unused_tcp_port)
    relay_process: subprocess.Popen[str] | None = None
    try:
        _wait_for_http_server(base_url)
        registered = httpx.post(
            f"{base_url}/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
            timeout=2,
        )
        assert registered.status_code == 200
        device_id = registered.json()["device_id"]

        relay_process = _start_desktop_relay_process(
            relay_url=f"ws://127.0.0.1:{unused_tcp_port}/relay/connect",
            account_id="acct-1",
            device_id=device_id,
            private_key_pem=KEYPAIR.private_key_pem,
        )
        accepted = _read_relay_process_json_line(relay_process)
        assert accepted == {
            "type": "relay.authenticated",
            "relay_session_id": accepted["relay_session_id"],
            "execution_target_id": f"relay:{device_id}",
            "state": "ready",
        }
        ready_status = asyncio.run(
            _run_status_tool_over_http(base_url, correlation_id="ready-status")
        )

        assert ready_status == {
            "status": "ready",
            "executionTarget": {
                "state": "ready",
                "target_id": f"relay:{device_id}",
                "capabilities": ["rate_shipment", "get_shipagent_status"],
                "message": None,
            },
        }

        assert relay_process.stdin is not None
        relay_process.stdin.write("\n")
        relay_process.stdin.flush()
        relay_process.wait(timeout=5)
        assert relay_process.returncode == 0, relay_process.stderr.read()

        offline_status = asyncio.run(
            _poll_status_tool_over_http(base_url, expected_state="offline")
        )
        assert offline_status == {
            "status": "offline",
            "executionTarget": {
                "state": "offline",
                "target_id": None,
                "capabilities": [],
                "message": "No active execution target connected.",
            },
        }
    finally:
        if relay_process is not None and relay_process.poll() is None:
            relay_process.terminate()
            try:
                relay_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                relay_process.kill()
                relay_process.wait(timeout=5)
        _stop_uvicorn_server(server, thread)


def test_control_plane_app_injected_loopback_status_over_mcp_http(
    monkeypatch,
    unused_tcp_port: int,
) -> None:
    app, _redis = _build_app(
        monkeypatch,
        execution_target=LoopbackExecutionTarget(
            capabilities=["rate_shipment", "get_shipagent_status"],
            execution_target_id="loopback-target",
        ),
    )
    base_url = f"http://127.0.0.1:{unused_tcp_port}"
    server, thread = _start_uvicorn_server(app, port=unused_tcp_port)
    try:
        _wait_for_http_server(base_url)

        status = asyncio.run(
            _run_status_tool_over_http(base_url, correlation_id="loopback-status")
        )

        assert status == {
            "status": "ready",
            "executionTarget": {
                "state": "ready",
                "target_id": "loopback-target",
                "capabilities": ["rate_shipment", "get_shipagent_status"],
                "message": None,
            },
        }
    finally:
        _stop_uvicorn_server(server, thread)


def test_connect_websocket_disconnect_clears_ready_liveness(monkeypatch) -> None:
    app, redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            challenge = websocket.receive_json()
            claims = build_handshake_claims(
                device_id=registered["device_id"],
                account_id="acct-1",
                relay_session_id=challenge["relay_session_id"],
                nonce=challenge["nonce"],
                version=VERSION,
            )
            signed = KEY_SERVICE.sign_handshake_claims(claims)
            websocket.send_json(signed.model_dump(mode="json"))
            assert websocket.receive_json()["state"] == "ready"

    assert RedisKey.relay_session(registered["device_id"]) not in redis.values
    assert RedisKey.relay_heartbeat(registered["device_id"]) not in redis.values
    assert RedisKey.relay_active_target("acct-1") not in redis.values


def test_connect_websocket_heartbeat_refreshes_ready_liveness(monkeypatch) -> None:
    app, redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            challenge = websocket.receive_json()
            claims = build_handshake_claims(
                device_id=registered["device_id"],
                account_id="acct-1",
                relay_session_id=challenge["relay_session_id"],
                nonce=challenge["nonce"],
                version=VERSION,
            )
            signed = KEY_SERVICE.sign_handshake_claims(claims)
            websocket.send_json(signed.model_dump(mode="json"))
            assert websocket.receive_json()["state"] == "ready"
            session_key = RedisKey.relay_session(registered["device_id"])
            heartbeat_key = RedisKey.relay_heartbeat(registered["device_id"])
            active_target_key = RedisKey.relay_active_target("acct-1")
            redis.ttls[session_key] = 1
            redis.ttls[heartbeat_key] = 1
            redis.ttls[active_target_key] = 1
            refreshed_version = RelayVersionMetadata(
                shipagent_core_version="1.0.1",
                registry_contract_version="registry-v2",
                ups_boundary_contract_version="ups-v2",
                capabilities=["rate_shipment", "get_shipagent_status"],
            )

            websocket.send_json(
                RelayHeartbeatFrame(
                    relay_session_id=challenge["relay_session_id"],
                    device_id=registered["device_id"],
                    version=refreshed_version,
                    active_source_fingerprint=registered["fingerprint"],
                    sent_at=datetime.now(UTC),
                ).model_dump(mode="json")
            )
            time.sleep(0.01)

            assert redis.ttls[session_key] == RedisTtl.RELAY_SESSION_SECONDS
            assert redis.ttls[heartbeat_key] == RedisTtl.RELAY_SESSION_SECONDS
            assert redis.ttls[active_target_key] == RedisTtl.RELAY_SESSION_SECONDS
            refreshed_payload = redis.values[heartbeat_key]
            refreshed_heartbeat = RelayHeartbeat.model_validate_json(refreshed_payload)
            assert refreshed_heartbeat.version == refreshed_version
            assert (
                refreshed_heartbeat.active_source_fingerprint
                == registered["fingerprint"]
            )


def test_connect_websocket_arbitrary_text_does_not_refresh_liveness(
    monkeypatch,
) -> None:
    app, redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            challenge = websocket.receive_json()
            claims = build_handshake_claims(
                device_id=registered["device_id"],
                account_id="acct-1",
                relay_session_id=challenge["relay_session_id"],
                nonce=challenge["nonce"],
                version=VERSION,
            )
            signed = KEY_SERVICE.sign_handshake_claims(claims)
            websocket.send_json(signed.model_dump(mode="json"))
            assert websocket.receive_json()["state"] == "ready"
            session_key = RedisKey.relay_session(registered["device_id"])
            heartbeat_key = RedisKey.relay_heartbeat(registered["device_id"])
            redis.ttls[session_key] = 1
            redis.ttls[heartbeat_key] = 1

            websocket.send_text("not-a-heartbeat-frame")
            time.sleep(0.01)

            assert redis.ttls.get(session_key) in (None, 1)
            assert redis.ttls.get(heartbeat_key) in (None, 1)


def test_connect_websocket_wrong_session_heartbeat_does_not_refresh_liveness(
    monkeypatch,
) -> None:
    app, redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            challenge = websocket.receive_json()
            claims = build_handshake_claims(
                device_id=registered["device_id"],
                account_id="acct-1",
                relay_session_id=challenge["relay_session_id"],
                nonce=challenge["nonce"],
                version=VERSION,
            )
            signed = KEY_SERVICE.sign_handshake_claims(claims)
            websocket.send_json(signed.model_dump(mode="json"))
            assert websocket.receive_json()["state"] == "ready"
            session_key = RedisKey.relay_session(registered["device_id"])
            heartbeat_key = RedisKey.relay_heartbeat(registered["device_id"])
            redis.ttls[session_key] = 1
            redis.ttls[heartbeat_key] = 1

            websocket.send_json(
                RelayHeartbeatFrame(
                    relay_session_id="wrong-session",
                    device_id=registered["device_id"],
                    version=VERSION,
                    active_source_fingerprint=registered["fingerprint"],
                    sent_at=datetime.now(UTC),
                ).model_dump(mode="json")
            )
            time.sleep(0.01)

            assert redis.ttls.get(session_key) in (None, 1)
            assert redis.ttls.get(heartbeat_key) in (None, 1)


def test_connect_websocket_wrong_device_heartbeat_does_not_refresh_liveness(
    monkeypatch,
) -> None:
    app, redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            challenge = websocket.receive_json()
            claims = build_handshake_claims(
                device_id=registered["device_id"],
                account_id="acct-1",
                relay_session_id=challenge["relay_session_id"],
                nonce=challenge["nonce"],
                version=VERSION,
            )
            websocket.send_json(
                KEY_SERVICE.sign_handshake_claims(claims).model_dump(mode="json")
            )
            assert websocket.receive_json()["state"] == "ready"
            session_key = RedisKey.relay_session(registered["device_id"])
            heartbeat_key = RedisKey.relay_heartbeat(registered["device_id"])
            redis.ttls[session_key] = 1
            redis.ttls[heartbeat_key] = 1

            websocket.send_json(
                RelayHeartbeatFrame(
                    relay_session_id=challenge["relay_session_id"],
                    device_id="another-device",
                    version=VERSION,
                    active_source_fingerprint=registered["fingerprint"],
                    sent_at=datetime.now(UTC),
                ).model_dump(mode="json")
            )
            time.sleep(0.01)

            assert redis.ttls.get(session_key) in (None, 1)
            assert redis.ttls.get(heartbeat_key) in (None, 1)


def test_connect_websocket_wrong_session_invocation_result_closes_liveness(
    monkeypatch,
) -> None:
    app, redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            challenge = websocket.receive_json()
            claims = build_handshake_claims(
                device_id=registered["device_id"],
                account_id="acct-1",
                relay_session_id=challenge["relay_session_id"],
                nonce=challenge["nonce"],
                version=VERSION,
            )
            signed = KEY_SERVICE.sign_handshake_claims(claims)
            websocket.send_json(signed.model_dump(mode="json"))
            assert websocket.receive_json()["state"] == "ready"
            session_key = RedisKey.relay_session(registered["device_id"])
            heartbeat_key = RedisKey.relay_heartbeat(registered["device_id"])
            redis.ttls[session_key] = 1
            redis.ttls[heartbeat_key] = 1

            websocket.send_json(
                RelayInvocationResultFrame(
                    relay_session_id="wrong-session",
                    relay_invocation_id="invocation-1",
                    status="ok",
                    result={"status": "ok"},
                ).model_dump(mode="json")
            )
            time.sleep(0.01)

            assert redis.ttls.get(session_key) in (None, 1)
            assert redis.ttls.get(heartbeat_key) in (None, 1)


def test_connect_websocket_rejects_claims_for_different_outstanding_challenge(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        with client.websocket_connect("/relay/connect") as stale_websocket:
            stale_websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            stale_challenge = stale_websocket.receive_json()

        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            websocket.receive_json()
            claims = build_handshake_claims(
                device_id=registered["device_id"],
                account_id="acct-1",
                relay_session_id=stale_challenge["relay_session_id"],
                nonce=stale_challenge["nonce"],
                version=VERSION,
            )
            signed = KEY_SERVICE.sign_handshake_claims(claims)
            websocket.send_json(signed.model_dump(mode="json"))
            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1008


def test_connect_websocket_rejects_unsigned_claims(monkeypatch) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": registered["device_id"]}
            )
            challenge = websocket.receive_json()
            claims = build_handshake_claims(
                device_id=registered["device_id"],
                account_id="acct-1",
                relay_session_id=challenge["relay_session_id"],
                nonce=challenge["nonce"],
                version=VERSION,
            )
            websocket.send_json(claims.model_dump(mode="json"))
            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1008


def test_connect_websocket_rejects_claims_for_different_device_than_hello(
    monkeypatch,
) -> None:
    app, _redis = _build_app(monkeypatch)

    with TestClient(app) as client:
        challenged = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={"device_name": "Dock Mac", "public_key_pem": PUBLIC_KEY},
        ).json()
        other = client.post(
            "/relay/devices/register",
            headers={"Authorization": "Bearer relay-manage-token"},
            json={
                "device_name": "Warehouse Mac",
                "public_key_pem": OTHER_KEYPAIR.public_key_pem,
            },
        ).json()
        with client.websocket_connect("/relay/connect") as websocket:
            websocket.send_json(
                {"account_id": "acct-1", "device_id": challenged["device_id"]}
            )
            challenge = websocket.receive_json()
            claims = build_handshake_claims(
                device_id=other["device_id"],
                account_id="acct-1",
                relay_session_id=challenge["relay_session_id"],
                nonce=challenge["nonce"],
                version=VERSION,
            )
            signed = OTHER_KEY_SERVICE.sign_handshake_claims(claims)
            websocket.send_json(signed.model_dump(mode="json"))
            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1008
