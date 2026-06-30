from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from src.control_plane.relay.protocol import (
    RelayHandshakeChallenge,
    RelaySignedHandshakeClaims,
    RelayVersionMetadata,
    verify_handshake_signature,
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


class FakeConnectionContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.exit_count = 0

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exit_count += 1
        return None


class FakeTransport:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.urls: list[str] = []
        self.connection_context: FakeConnectionContext | None = None

    def connect(self, url: str) -> FakeConnectionContext:
        self.urls.append(url)
        self.connection_context = FakeConnectionContext(self.connection)
        return self.connection_context


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


@pytest.mark.asyncio
async def test_start_sends_hello_and_signed_handshake_for_challenge() -> None:
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
    signed = RelaySignedHandshakeClaims.model_validate(connection.sent[1])
    assert signed.claims.account_id == "acct-1"
    assert signed.claims.device_id == "device-1"
    assert signed.claims.relay_session_id == challenge.relay_session_id
    assert signed.claims.nonce == challenge.nonce
    assert signed.claims.version == VERSION
    verify_handshake_signature(signed, keypair.public_key_pem)
    assert accepted.model_dump(mode="json") == {
        "relay_session_id": challenge.relay_session_id,
        "execution_target_id": "relay:device-1",
        "state": "ready",
    }


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

    assert connection.sent[-1] == {
        "type": "heartbeat",
        "relay_session_id": challenge.relay_session_id,
    }
    assert sleep.intervals[0] == 30
    await client.stop()


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

    assert [payload.get("type") for payload in connection.sent] == [None, None]
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

    async with transport.connect("ws://relay.test/relay/connect") as connection:
        await connection.send_json({"hello": "relay"})
        received = await connection.receive_json()

    assert connected_urls == ["ws://relay.test/relay/connect"]
    assert json.loads(raw_websocket.sent_text[0]) == {"hello": "relay"}
    assert received == {"accepted": True}
    assert raw_context.exit_count == 1
