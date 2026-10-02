from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.control_plane.relay.protocol import (
    RelayHandshakeChallenge,
    RelayHandshakeToken,
    RelayHeartbeatFrame,
    RelayInvocationEnvelope,
    RelayInvocationResultFrame,
    RelayVersionMetadata,
    relay_invocation_input_hash,
    verify_handshake_jwt,
)
from src.services.desktop_relay_client import (
    DesktopRelayClient,
    WebSocketRelayTransport,
)
from src.services.relay_key_service import RelayKeyService


class InMemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


class FakeConnection:
    def __init__(self, incoming: list[dict[str, Any]]) -> None:
        self.incoming = list(incoming)
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    async def receive_json(self) -> dict[str, Any]:
        return self.incoming.pop(0)


class BlockingReceiveConnection(FakeConnection):
    def __init__(self) -> None:
        super().__init__([])
        self.receive_started = asyncio.Event()
        self.release_receive = asyncio.Event()

    async def receive_json(self) -> dict[str, Any]:
        self.receive_started.set()
        await self.release_receive.wait()
        return {}


class BlockingAfterHandshakeConnection(FakeConnection):
    def __init__(self, incoming: list[dict[str, Any]]) -> None:
        super().__init__(incoming)
        self.receive_blocked = asyncio.Event()
        self.release_receive = asyncio.Event()

    async def receive_json(self) -> dict[str, Any]:
        if self.incoming:
            return await super().receive_json()
        self.receive_blocked.set()
        await self.release_receive.wait()
        return {}


class FailingHeartbeatConnection(FakeConnection):
    def __init__(self, incoming: list[dict[str, Any]]) -> None:
        super().__init__(incoming)
        self.heartbeat_send_attempted = asyncio.Event()

    async def send_json(self, payload: dict[str, Any]) -> None:
        if payload.get("type") == "relay.heartbeat":
            self.heartbeat_send_attempted.set()
            raise RuntimeError("heartbeat send failed")
        await super().send_json(payload)


class FakeConnectionContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.exit_count = 0

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exit_count += 1
        return None


class SlowEnterConnectionContext(FakeConnectionContext):
    def __init__(self, connection: FakeConnection) -> None:
        super().__init__(connection)
        self.enter_started = asyncio.Event()
        self.release_enter = asyncio.Event()

    async def __aenter__(self) -> FakeConnection:
        self.enter_started.set()
        await self.release_enter.wait()
        return self.connection


class FakeTransport:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.urls: list[str] = []
        self.connection_context: FakeConnectionContext | None = None

    def connect(self, url: str) -> FakeConnectionContext:
        self.urls.append(url)
        self.connection_context = FakeConnectionContext(self.connection)
        return self.connection_context


class QueueTransport:
    def __init__(self, connections: list[FakeConnection]) -> None:
        self.connections = list(connections)
        self.connection_contexts: list[FakeConnectionContext] = []

    def connect(self, url: str) -> FakeConnectionContext:
        connection_context = FakeConnectionContext(self.connections.pop(0))
        self.connection_contexts.append(connection_context)
        return connection_context


class SlowEnterTransport:
    def __init__(self, connections: list[FakeConnection]) -> None:
        self.connections = list(connections)
        self.connection_contexts: list[SlowEnterConnectionContext] = []

    def connect(self, url: str) -> SlowEnterConnectionContext:
        connection_context = SlowEnterConnectionContext(self.connections.pop(0))
        self.connection_contexts.append(connection_context)
        return connection_context


class ControlledSleep:
    def __init__(self) -> None:
        self.intervals: list[float] = []
        self.waiters: list[asyncio.Event] = []

    async def __call__(self, interval: float) -> None:
        self.intervals.append(interval)
        waiter = asyncio.Event()
        self.waiters.append(waiter)
        await waiter.wait()

    async def release_next(self) -> None:
        for _ in range(20):
            if self.waiters:
                self.waiters.pop(0).set()
                await asyncio.sleep(0)
                return
            await asyncio.sleep(0)
        raise AssertionError("heartbeat sleep was not reached")


class FakeRawWebSocket:
    def __init__(self, incoming: list[str]) -> None:
        self.incoming = list(incoming)
        self.sent_text: list[str] = []

    async def send(self, payload: str) -> None:
        self.sent_text.append(payload)

    async def recv(self) -> str:
        return self.incoming.pop(0)


class FakeRawWebSocketContext:
    def __init__(self, websocket: FakeRawWebSocket) -> None:
        self.websocket = websocket
        self.exit_count = 0

    async def __aenter__(self) -> FakeRawWebSocket:
        return self.websocket

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exit_count += 1


VERSION = RelayVersionMetadata(
    shipagent_core_version="1.0.0",
    registry_contract_version="registry-v1",
    ups_boundary_contract_version="ups-v1",
    capabilities=["rate_shipment", "get_shipagent_status"],
)


def relay_invocation_envelope(
    *,
    relay_session_id: str,
    sequence: int = 1,
    relay_invocation_id: str = "invocation-1",
    tool_name: str = "get_shipagent_status",
    arguments: dict[str, object] | None = None,
    deadline_at: datetime | None = None,
    idempotency_key: str = "idempotency-1",
    audit_correlation_id: str = "corr-1",
) -> RelayInvocationEnvelope:
    invocation_arguments = arguments or {}
    return RelayInvocationEnvelope(
        type="relay.invoke",
        relay_session_id=relay_session_id,
        sequence=sequence,
        relay_invocation_id=relay_invocation_id,
        tool_name=tool_name,
        arguments=invocation_arguments,
        input_hash=relay_invocation_input_hash(tool_name, invocation_arguments),
        deadline_at=deadline_at or datetime.now(UTC) + timedelta(seconds=30),
        idempotency_key=idempotency_key,
        audit_correlation_id=audit_correlation_id,
    )


@pytest.mark.asyncio
async def test_start_sends_hello_and_jwt_handshake_for_challenge() -> None:
    key_service = RelayKeyService(InMemoryStore())
    keypair = key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
        ]
    )
    transport = FakeTransport(connection)
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=transport,
    )

    accepted = await client.start()

    assert transport.urls == ["ws://relay.test/relay/connect"]
    assert connection.sent[0] == {"account_id": "acct-1", "device_id": "device-1"}
    handshake = RelayHandshakeToken.model_validate(connection.sent[1])
    claims = verify_handshake_jwt(handshake, keypair.public_key_pem)
    assert claims.account_id == "acct-1"
    assert claims.device_id == "device-1"
    assert claims.relay_session_id == challenge.relay_session_id
    assert claims.nonce == challenge.nonce
    assert claims.version == VERSION
    assert accepted.model_dump(mode="json") == {
        "type": "relay.authenticated",
        "relay_session_id": challenge.relay_session_id,
        "execution_target_id": "relay:device-1",
        "state": "ready",
    }
    await client.stop()


@pytest.mark.asyncio
async def test_start_closes_connection_when_cancelled_during_receive() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    connection = BlockingReceiveConnection()
    transport = FakeTransport(connection)
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=transport,
    )

    start_task = asyncio.create_task(client.start())
    await asyncio.wait_for(connection.receive_started.wait(), timeout=1)
    start_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await start_task

    assert transport.connection_context is not None
    assert transport.connection_context.exit_count == 1


@pytest.mark.asyncio
async def test_start_sends_session_bound_heartbeat_frames() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
        ]
    )
    sleep = ControlledSleep()
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=FakeTransport(connection),
        heartbeat_interval_seconds=30,
        sleep=sleep,
    )

    await client.start()
    await sleep.release_next()

    heartbeat = RelayHeartbeatFrame.model_validate(connection.sent[-1])
    assert heartbeat.relay_session_id == challenge.relay_session_id
    assert heartbeat.device_id == "device-1"
    assert heartbeat.version == VERSION
    assert heartbeat.active_source_fingerprint is None
    assert heartbeat.sent_at.tzinfo is not None
    assert sleep.intervals[0] == 30
    await client.stop()


@pytest.mark.asyncio
async def test_heartbeat_uses_typed_frame_and_no_signing_key_as_source_identity() -> (
    None
):
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
        ]
    )
    sleep = ControlledSleep()
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=FakeTransport(connection),
        heartbeat_interval_seconds=30,
        sleep=sleep,
    )

    await client.start()
    await sleep.release_next()

    heartbeat = RelayHeartbeatFrame.model_validate(connection.sent[-1])
    assert heartbeat.device_id == "device-1"
    assert heartbeat.relay_session_id == challenge.relay_session_id
    assert heartbeat.active_source_fingerprint is None
    assert heartbeat.sent_at.tzinfo is not None
    await client.stop()


@pytest.mark.asyncio
async def test_receive_loop_dispatches_get_shipagent_status_invocation() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    invocation = relay_invocation_envelope(
        relay_session_id=challenge.relay_session_id,
        arguments={"correlation_id": "corr-1"},
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
            invocation.model_dump(mode="json"),
        ]
    )
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=FakeTransport(connection),
        sleep=ControlledSleep(),
    )

    await client.start()
    for _ in range(20):
        result_payloads = [
            payload
            for payload in connection.sent
            if payload.get("type") == "relay.invocation_result"
        ]
        if result_payloads:
            break
        await asyncio.sleep(0)
    await client.stop()

    result = RelayInvocationResultFrame.model_validate(result_payloads[0])
    assert result.status == "ok"
    assert result.relay_session_id == challenge.relay_session_id
    assert result.relay_invocation_id == "invocation-1"
    assert result.error is None
    assert result.result == {
        "status": "ready",
        "executionTarget": {
            "state": "ready",
            "target_id": "relay:device-1",
            "capabilities": ["rate_shipment", "get_shipagent_status"],
            "message": None,
        },
    }


@pytest.mark.asyncio
async def test_receive_loop_rejects_unsupported_tool_with_sanitized_result() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    invocation = relay_invocation_envelope(
        relay_session_id=challenge.relay_session_id,
        tool_name="read_secret_credentials",
        arguments={"token": "secret"},
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
            invocation.model_dump(mode="json"),
        ]
    )
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=FakeTransport(connection),
        sleep=ControlledSleep(),
    )

    await client.start()
    for _ in range(20):
        result_payloads = [
            payload
            for payload in connection.sent
            if payload.get("type") == "relay.invocation_result"
        ]
        if result_payloads:
            break
        await asyncio.sleep(0)
    await client.stop()

    result = RelayInvocationResultFrame.model_validate(result_payloads[0])
    assert result.status == "error"
    assert result.result is None
    assert result.error == {
        "code": "unsupported_tool",
        "message": "Relay invocation tool is not supported.",
    }
    assert "read_secret_credentials" not in json.dumps(result.model_dump(mode="json"))
    assert "secret" not in json.dumps(result.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_receive_loop_rejects_expired_invocation_without_execution() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    invocation = relay_invocation_envelope(
        relay_session_id=challenge.relay_session_id,
        deadline_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
            invocation.model_dump(mode="json"),
        ]
    )
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=FakeTransport(connection),
        sleep=ControlledSleep(),
    )

    await client.start()
    for _ in range(20):
        result_payloads = [
            payload
            for payload in connection.sent
            if payload.get("type") == "relay.invocation_result"
        ]
        if result_payloads:
            break
        await asyncio.sleep(0)
    await client.stop()

    result = RelayInvocationResultFrame.model_validate(result_payloads[0])
    assert result.status == "error"
    assert result.result is None
    assert result.error == {
        "code": "expired_deadline",
        "message": "Relay invocation deadline has expired.",
    }


@pytest.mark.asyncio
async def test_receive_loop_rejects_input_hash_mismatch_without_execution() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    invocation = relay_invocation_envelope(
        relay_session_id=challenge.relay_session_id,
    ).model_copy(update={"input_hash": "sha256:wrong"})
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
            invocation.model_dump(mode="json"),
        ]
    )
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=FakeTransport(connection),
        sleep=ControlledSleep(),
    )

    await client.start()
    for _ in range(20):
        result_payloads = [
            payload
            for payload in connection.sent
            if payload.get("type") == "relay.invocation_result"
        ]
        if result_payloads:
            break
        await asyncio.sleep(0)
    await client.stop()

    result = RelayInvocationResultFrame.model_validate(result_payloads[0])
    assert result.status == "error"
    assert result.result is None
    assert result.error == {
        "code": "input_hash_mismatch",
        "message": "Relay invocation input hash did not match.",
    }


@pytest.mark.asyncio
async def test_receive_loop_rejects_replayed_invocation_id_without_execution() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    first_invocation = relay_invocation_envelope(
        relay_session_id=challenge.relay_session_id,
        sequence=1,
        relay_invocation_id="invocation-1",
        idempotency_key="idempotency-1",
    )
    replayed_invocation = relay_invocation_envelope(
        relay_session_id=challenge.relay_session_id,
        sequence=2,
        relay_invocation_id="invocation-1",
        idempotency_key="idempotency-2",
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
            first_invocation.model_dump(mode="json"),
            replayed_invocation.model_dump(mode="json"),
        ]
    )
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=FakeTransport(connection),
        sleep=ControlledSleep(),
    )

    await client.start()
    for _ in range(20):
        result_payloads = [
            payload
            for payload in connection.sent
            if payload.get("type") == "relay.invocation_result"
        ]
        if len(result_payloads) == 2:
            break
        await asyncio.sleep(0)
    await client.stop()

    results = [
        RelayInvocationResultFrame.model_validate(payload)
        for payload in result_payloads
    ]
    assert results[0].status == "ok"
    assert results[1].status == "error"
    assert results[1].result is None
    assert results[1].error == {
        "code": "duplicate_invocation",
        "message": "Relay invocation has already been processed.",
    }


@pytest.mark.asyncio
async def test_receive_loop_rejects_replayed_idempotency_key_without_execution() -> (
    None
):
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    first_invocation = relay_invocation_envelope(
        relay_session_id=challenge.relay_session_id,
        sequence=1,
        relay_invocation_id="invocation-1",
        idempotency_key="idempotency-1",
    )
    replayed_invocation = relay_invocation_envelope(
        relay_session_id=challenge.relay_session_id,
        sequence=2,
        relay_invocation_id="invocation-2",
        idempotency_key="idempotency-1",
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
            first_invocation.model_dump(mode="json"),
            replayed_invocation.model_dump(mode="json"),
        ]
    )
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=FakeTransport(connection),
        sleep=ControlledSleep(),
    )

    await client.start()
    for _ in range(20):
        result_payloads = [
            payload
            for payload in connection.sent
            if payload.get("type") == "relay.invocation_result"
        ]
        if len(result_payloads) == 2:
            break
        await asyncio.sleep(0)
    await client.stop()

    results = [
        RelayInvocationResultFrame.model_validate(payload)
        for payload in result_payloads
    ]
    assert results[0].status == "ok"
    assert results[1].status == "error"
    assert results[1].result is None
    assert results[1].error == {
        "code": "duplicate_idempotency_key",
        "message": "Relay invocation idempotency key has already been processed.",
    }


@pytest.mark.asyncio
async def test_receive_loop_rejects_non_increasing_sequence_without_execution() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    first_invocation = relay_invocation_envelope(
        relay_session_id=challenge.relay_session_id,
        sequence=1,
        relay_invocation_id="invocation-1",
        idempotency_key="idempotency-1",
    )
    replayed_sequence_invocation = relay_invocation_envelope(
        relay_session_id=challenge.relay_session_id,
        sequence=1,
        relay_invocation_id="invocation-2",
        idempotency_key="idempotency-2",
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
            first_invocation.model_dump(mode="json"),
            replayed_sequence_invocation.model_dump(mode="json"),
        ]
    )
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=FakeTransport(connection),
        sleep=ControlledSleep(),
    )

    await client.start()
    for _ in range(20):
        result_payloads = [
            payload
            for payload in connection.sent
            if payload.get("type") == "relay.invocation_result"
        ]
        if len(result_payloads) == 2:
            break
        await asyncio.sleep(0)
    await client.stop()

    results = [
        RelayInvocationResultFrame.model_validate(payload)
        for payload in result_payloads
    ]
    assert results[0].status == "ok"
    assert results[1].status == "error"
    assert results[1].result is None
    assert results[1].error == {
        "code": "non_increasing_sequence",
        "message": "Relay invocation sequence must increase.",
    }


@pytest.mark.asyncio
async def test_receive_loop_rejects_wrong_session_invocation_and_stops() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    invocation = relay_invocation_envelope(
        relay_session_id="wrong-session",
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
            invocation.model_dump(mode="json"),
        ]
    )
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=FakeTransport(connection),
        sleep=ControlledSleep(),
    )

    await client.start()
    for _ in range(20):
        result_payloads = [
            payload
            for payload in connection.sent
            if payload.get("type") == "relay.invocation_result"
        ]
        if result_payloads:
            break
        await asyncio.sleep(0)
    await client.stop()

    result = RelayInvocationResultFrame.model_validate(result_payloads[0])
    assert result.status == "error"
    assert result.relay_session_id == "wrong-session"
    assert result.error == {
        "code": "wrong_relay_session",
        "message": "Invocation was not addressed to this relay session.",
    }


@pytest.mark.asyncio
async def test_receive_loop_resets_replay_state_for_new_relay_session() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    first_challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    second_challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-2",
        nonce="nonce-2",
    )
    first_connection = FakeConnection(
        [
            first_challenge.model_dump(mode="json"),
            {
                "relay_session_id": first_challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
            relay_invocation_envelope(
                relay_session_id=first_challenge.relay_session_id,
                sequence=1,
                relay_invocation_id="invocation-1",
                idempotency_key="idempotency-1",
            ).model_dump(mode="json"),
        ]
    )
    second_connection = FakeConnection(
        [
            second_challenge.model_dump(mode="json"),
            {
                "relay_session_id": second_challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
            relay_invocation_envelope(
                relay_session_id=second_challenge.relay_session_id,
                sequence=1,
                relay_invocation_id="invocation-1",
                idempotency_key="idempotency-1",
            ).model_dump(mode="json"),
        ]
    )
    transport = QueueTransport([first_connection, second_connection])
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=transport,
        sleep=ControlledSleep(),
    )

    await client.start()
    for _ in range(20):
        first_results = [
            payload
            for payload in first_connection.sent
            if payload.get("type") == "relay.invocation_result"
        ]
        if first_results:
            break
        await asyncio.sleep(0)
    await client.stop()

    await client.start()
    for _ in range(20):
        second_results = [
            payload
            for payload in second_connection.sent
            if payload.get("type") == "relay.invocation_result"
        ]
        if second_results:
            break
        await asyncio.sleep(0)
    await client.stop()

    first_result = RelayInvocationResultFrame.model_validate(first_results[0])
    second_result = RelayInvocationResultFrame.model_validate(second_results[0])
    assert first_result.status == "ok"
    assert second_result.status == "ok"


@pytest.mark.asyncio
async def test_stop_cancels_receive_loop() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    connection = BlockingAfterHandshakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
        ]
    )
    transport = FakeTransport(connection)
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=transport,
        sleep=ControlledSleep(),
    )

    await client.start()
    await asyncio.wait_for(connection.receive_blocked.wait(), timeout=1)
    await client.stop()

    assert transport.connection_context is not None
    assert transport.connection_context.exit_count == 1


@pytest.mark.asyncio
async def test_stop_closes_connection_after_heartbeat_send_failure() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    connection = FailingHeartbeatConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
        ]
    )
    transport = FakeTransport(connection)
    sleep = ControlledSleep()
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=transport,
        heartbeat_interval_seconds=30,
        sleep=sleep,
    )

    await client.start()
    await sleep.release_next()
    await asyncio.wait_for(connection.heartbeat_send_attempted.wait(), timeout=1)
    await client.stop()

    assert transport.connection_context is not None
    assert transport.connection_context.exit_count == 1


@pytest.mark.asyncio
async def test_stop_closes_relay_connection_context_once() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
        ]
    )
    transport = FakeTransport(connection)
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=transport,
        sleep=ControlledSleep(),
    )

    await client.start()
    await client.stop()
    await client.stop()

    assert transport.connection_context is not None
    assert transport.connection_context.exit_count == 1


@pytest.mark.asyncio
async def test_start_rejects_when_client_is_already_started() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    first_connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
        ]
    )
    second_connection = FakeConnection([])
    transport = QueueTransport([first_connection, second_connection])
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=transport,
        sleep=ControlledSleep(),
    )

    await client.start()
    with pytest.raises(RuntimeError, match="already started"):
        await client.start()
    await client.stop()

    assert len(transport.connection_contexts) == 1
    assert transport.connection_contexts[0].exit_count == 1
    assert second_connection.sent == []


@pytest.mark.asyncio
async def test_concurrent_start_opens_only_one_connection_and_rejects_other() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    first_connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
        ]
    )
    second_connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
        ]
    )
    transport = SlowEnterTransport([first_connection, second_connection])
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=transport,
        sleep=ControlledSleep(),
    )

    start_tasks = [asyncio.create_task(client.start()) for _ in range(2)]
    for _ in range(20):
        if transport.connection_contexts:
            break
        await asyncio.sleep(0)
    assert transport.connection_contexts
    await asyncio.wait_for(transport.connection_contexts[0].enter_started.wait(), 1)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    for connection_context in list(transport.connection_contexts):
        connection_context.release_enter.set()

    results = await asyncio.gather(*start_tasks, return_exceptions=True)
    opened_context_count = len(transport.connection_contexts)
    runtime_error_count = sum(isinstance(result, RuntimeError) for result in results)
    successful_start_count = sum(
        not isinstance(result, BaseException) for result in results
    )
    try:
        await client.stop()
        exit_counts = [context.exit_count for context in transport.connection_contexts]
    finally:
        for connection_context in transport.connection_contexts:
            if connection_context.exit_count == 0:
                await connection_context.__aexit__(None, None, None)

    assert opened_context_count == 1
    assert successful_start_count == 1
    assert runtime_error_count == 1
    assert exit_counts == [1]


@pytest.mark.asyncio
async def test_stop_waits_for_in_progress_start_and_closes_connection() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
        ]
    )
    transport = SlowEnterTransport([connection])
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=transport,
        sleep=ControlledSleep(),
    )

    start_task = asyncio.create_task(client.start())
    for _ in range(20):
        if transport.connection_contexts:
            break
        await asyncio.sleep(0)
    assert transport.connection_contexts
    connection_context = transport.connection_contexts[0]
    await asyncio.wait_for(connection_context.enter_started.wait(), 1)
    stop_task = asyncio.create_task(client.stop())
    await asyncio.sleep(0)

    connection_context.release_enter.set()
    started = await start_task
    await stop_task

    assert started.execution_target_id == "relay:device-1"
    assert connection_context.exit_count == 1


@pytest.mark.asyncio
async def test_start_rejects_accepted_session_mismatch_before_heartbeat() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": "different-relay-session",
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
        ]
    )
    transport = FakeTransport(connection)
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=transport,
        sleep=ControlledSleep(),
    )

    with pytest.raises(ValueError, match="relay session"):
        await client.start()

    assert [payload.get("type") for payload in connection.sent] == [
        None,
        "relay.authenticate",
    ]
    assert transport.connection_context is not None
    assert transport.connection_context.exit_count == 1


@pytest.mark.asyncio
async def test_start_rejects_non_ready_accepted_state_before_heartbeat() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "offline",
            },
        ]
    )
    transport = FakeTransport(connection)
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=transport,
        sleep=ControlledSleep(),
    )

    with pytest.raises(ValueError, match="state"):
        await client.start()

    assert [payload.get("type") for payload in connection.sent] == [
        None,
        "relay.authenticate",
    ]
    assert transport.connection_context is not None
    assert transport.connection_context.exit_count == 1


@pytest.mark.asyncio
async def test_start_rejects_execution_target_mismatch_before_heartbeat() -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:different-device",
                "state": "ready",
            },
        ]
    )
    transport = FakeTransport(connection)
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
        transport=transport,
        sleep=ControlledSleep(),
    )

    with pytest.raises(ValueError, match="execution target"):
        await client.start()

    assert [payload.get("type") for payload in connection.sent] == [
        None,
        "relay.authenticate",
    ]
    assert transport.connection_context is not None
    assert transport.connection_context.exit_count == 1


@pytest.mark.asyncio
async def test_start_uses_websocket_transport_when_transport_is_not_injected(
    monkeypatch,
) -> None:
    key_service = RelayKeyService(InMemoryStore())
    key_service.generate_or_load_keypair()
    challenge = RelayHandshakeChallenge(
        relay_session_id="relay-session-1",
        nonce="nonce-1",
    )
    connection = FakeConnection(
        [
            challenge.model_dump(mode="json"),
            {
                "relay_session_id": challenge.relay_session_id,
                "execution_target_id": "relay:device-1",
                "state": "ready",
            },
        ]
    )
    created_transports: list[FakeTransport] = []

    class DefaultTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__(connection)
            created_transports.append(self)

    monkeypatch.setattr(
        "src.services.desktop_relay_client.WebSocketRelayTransport",
        DefaultTransport,
    )
    client = DesktopRelayClient(
        relay_url="ws://relay.test/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=key_service,
        version=VERSION,
    )

    accepted = await client.start()
    await client.stop()

    assert created_transports[0].urls == ["ws://relay.test/relay/connect"]
    assert accepted.execution_target_id == "relay:device-1"


@pytest.mark.asyncio
async def test_websocket_relay_transport_exchanges_json_frames() -> None:
    raw_websocket = FakeRawWebSocket(['{"accepted": true}'])
    raw_context = FakeRawWebSocketContext(raw_websocket)
    connected_urls: list[str] = []

    def connect_factory(url: str) -> FakeRawWebSocketContext:
        connected_urls.append(url)
        return raw_context

    transport = WebSocketRelayTransport(connect_factory=connect_factory)

    async with transport.connect("wss://relay.test/relay/connect") as connection:
        await connection.send_json({"hello": "relay"})
        received = await connection.receive_json()

    assert connected_urls == ["wss://relay.test/relay/connect"]
    assert json.loads(raw_websocket.sent_text[0]) == {"hello": "relay"}
    assert received == {"accepted": True}
    assert raw_context.exit_count == 1


def test_websocket_transport_rejects_public_plaintext_url() -> None:
    with pytest.raises(ValueError, match="wss"):
        WebSocketRelayTransport().connect("ws://relay.example/relay/connect")


def test_websocket_transport_allows_explicit_loopback_development_url() -> None:
    transport = WebSocketRelayTransport(allow_insecure_loopback=True)

    assert transport.connect("ws://127.0.0.1:8080/relay/connect")
