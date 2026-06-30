from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.control_plane.app import create_control_plane_app
from src.control_plane.auth.context import (
    AuthorizationContext,
    clear_authorization_context,
    set_authorization_context,
)
from src.control_plane.auth.jwt_verifier import TokenPrincipal
from src.control_plane.auth.service import AuthorizationService
from src.control_plane.redis_keys import RedisKey, RedisTtl
from src.control_plane.relay.protocol import (
    RelayVersionMetadata,
    build_handshake_claims,
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
PRIVATE_KEY = "-----BEGIN ED25519 PRIVATE KEY-----\nsecret\n-----END ED25519 PRIVATE KEY-----\n"
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
        if numkeys == 1 and (
            "SA_RATE_LIMIT" in script or "SA_LOOP_GUARD" in script
        ):
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
            device_key, session_key, heartbeat_key, active_target_key, device_payload = (
                keys_and_args
            )
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
        if numkeys == 3 and len(keys_and_args) == 5:
            session_key, heartbeat_key, active_target_key, expected_relay_session_id, ttl = (
                keys_and_args
            )
            payload = self.values.get(session_key)
            if payload is None or heartbeat_key not in self.values:
                return 0
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            session = json.loads(payload)
            if session.get("relay_session_id") != expected_relay_session_id:
                return 0
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
            if (
                active.get("device_id") == session.get("device_id")
                and active.get("relay_session_id") == session.get("relay_session_id")
            ):
                return await self.delete(session_key, heartbeat_key, active_target_key)
        return await self.delete(session_key, heartbeat_key)


class _TokenVerifier:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def verify(self, token: str) -> TokenPrincipal:
        scopes = {"jobs:read", "shipments:preview"}
        if token == "relay-manage-token":
            scopes.add("relay:manage")
        return TokenPrincipal(
            subject="auth0|owner-1",
            client_id="chatgpt-client",
            scopes=frozenset(scopes),
        )


class _AuthorizationService(AuthorizationService):
    async def resolve(
        self, *, subject: str, client_id: str, scopes: set[str]
    ) -> AuthorizationContext:
        return AuthorizationContext(
            account_id="acct-1",
            provider_connection_id="pc-1",
            provider_surface="chatgpt",
            subject=subject,
            client_id=client_id,
            scopes=frozenset(scopes),
        )


class _RelayTestClientConnection:
    def __init__(self, websocket) -> None:
        self._websocket = websocket

    async def send_json(self, payload: dict[str, object]) -> None:
        self._websocket.send_json(payload)

    async def receive_json(self) -> dict[str, object]:
        return self._websocket.receive_json()


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


def _build_app(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setenv("SHIPAGENT_PUBLIC_BASE_URL", "https://dev-mcp.shipagent.app/")
    monkeypatch.setenv("SHIPAGENT_AUTH0_ISSUER", "https://tenant.us.auth0.com/")
    monkeypatch.setenv("SHIPAGENT_AUTH0_AUDIENCE", "https://dev-mcp.shipagent.app")
    monkeypatch.setenv("SHIPAGENT_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SHIPAGENT_REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setattr("src.control_plane.app.Auth0TokenVerifier", _TokenVerifier)
    monkeypatch.setattr(
        "src.control_plane.app.AuthorizationService", _AuthorizationService
    )
    monkeypatch.setattr("src.control_plane.app._build_redis_client", lambda _: redis)
    return create_control_plane_app(), redis


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
            "status": "ok",
            "execution_target": {
                "state": "ready",
                "execution_target_id": f"relay:{device_id}",
                "device_id": device_id,
                "capabilities": ["rate_shipment", "get_shipagent_status"],
                "message": None,
            },
        }
        assert offline_status == {
            "status": "unavailable",
            "execution_target": {
                "state": "offline",
                "execution_target_id": None,
                "device_id": None,
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

            websocket.send_json(
                {
                    "type": "heartbeat",
                    "relay_session_id": challenge["relay_session_id"],
                }
            )
            time.sleep(0.01)

            assert redis.ttls[session_key] == RedisTtl.RELAY_SESSION_SECONDS
            assert redis.ttls[heartbeat_key] == RedisTtl.RELAY_SESSION_SECONDS
            assert redis.ttls[active_target_key] == RedisTtl.RELAY_SESSION_SECONDS


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
                {
                    "type": "heartbeat",
                    "relay_session_id": "wrong-session",
                }
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
            json={"device_name": "Warehouse Mac", "public_key_pem": PUBLIC_KEY},
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
            signed = KEY_SERVICE.sign_handshake_claims(claims)
            websocket.send_json(signed.model_dump(mode="json"))
            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1008
