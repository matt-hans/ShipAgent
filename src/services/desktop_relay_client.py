from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, suppress
from typing import Any, Protocol

from websockets.asyncio.client import connect as websocket_connect

from src.control_plane.relay.protocol import (
    RelayHandshakeChallenge,
    RelayProtocolModel,
    RelayTargetState,
    RelayVersionMetadata,
    build_handshake_claims,
)
from src.services.relay_key_service import RelayKeyService


class RelayClientConnection(Protocol):
    async def send_json(self, payload: dict[str, Any]) -> None: ...

    async def receive_json(self) -> dict[str, Any]: ...


class RelayClientTransport(Protocol):
    def connect(self, url: str) -> AbstractAsyncContextManager[RelayClientConnection]: ...


class RawWebSocketConnection(Protocol):
    async def send(self, message: str) -> None: ...

    async def recv(self) -> str | bytes: ...


class WebSocketConnectFactory(Protocol):
    def __call__(
        self,
        url: str,
    ) -> AbstractAsyncContextManager[RawWebSocketConnection]: ...


class RelayAcceptedResponse(RelayProtocolModel):
    relay_session_id: str
    execution_target_id: str
    state: RelayTargetState


class WebSocketRelayConnection:
    def __init__(self, websocket: RawWebSocketConnection) -> None:
        self._websocket = websocket

    async def send_json(self, payload: dict[str, Any]) -> None:
        await self._websocket.send(
            json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )

    async def receive_json(self) -> dict[str, Any]:
        frame = await self._websocket.recv()
        if isinstance(frame, bytes):
            frame = frame.decode("utf-8")
        payload = json.loads(frame)
        if not isinstance(payload, dict):
            raise ValueError("relay websocket frame must be a JSON object")
        return payload


class WebSocketRelayConnectionContext:
    def __init__(
        self,
        url: str,
        connect_factory: WebSocketConnectFactory,
    ) -> None:
        self._url = url
        self._connect_factory = connect_factory
        self._websocket_context: AbstractAsyncContextManager[
            RawWebSocketConnection
        ] | None = None

    async def __aenter__(self) -> WebSocketRelayConnection:
        self._websocket_context = self._connect_factory(self._url)
        websocket = await self._websocket_context.__aenter__()
        return WebSocketRelayConnection(websocket)

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._websocket_context is not None:
            await self._websocket_context.__aexit__(exc_type, exc, tb)
            self._websocket_context = None


class WebSocketRelayTransport:
    def __init__(
        self,
        connect_factory: WebSocketConnectFactory = websocket_connect,
    ) -> None:
        self._connect_factory = connect_factory

    def connect(self, url: str) -> WebSocketRelayConnectionContext:
        return WebSocketRelayConnectionContext(url, self._connect_factory)


def default_relay_version_metadata() -> RelayVersionMetadata:
    return RelayVersionMetadata(
        shipagent_core_version="0.1.0",
        registry_contract_version="registry-v1",
        ups_boundary_contract_version="ups-v1",
        capabilities=["rate_shipment", "get_shipagent_status"],
    )


class DesktopRelayClient:
    def __init__(
        self,
        *,
        relay_url: str,
        account_id: str,
        device_id: str,
        key_service: RelayKeyService,
        transport: RelayClientTransport | None = None,
        version: RelayVersionMetadata | None = None,
        heartbeat_interval_seconds: float = 30.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._relay_url = relay_url
        self._account_id = account_id
        self._device_id = device_id
        self._key_service = key_service
        self._version = version or default_relay_version_metadata()
        self._transport = transport or WebSocketRelayTransport()
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._sleep = sleep
        self._connection_context: AbstractAsyncContextManager[RelayClientConnection] | None = (
            None
        )
        self._connection: RelayClientConnection | None = None
        self._accepted: RelayAcceptedResponse | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def start(self) -> RelayAcceptedResponse:
        connection_context = self._transport.connect(self._relay_url)
        connection = await connection_context.__aenter__()
        self._connection_context = connection_context
        self._connection = connection

        try:
            await self._connection.send_json(
                {"account_id": self._account_id, "device_id": self._device_id}
            )
            challenge = RelayHandshakeChallenge.model_validate(
                await self._connection.receive_json()
            )
            claims = build_handshake_claims(
                device_id=self._device_id,
                account_id=self._account_id,
                relay_session_id=challenge.relay_session_id,
                nonce=challenge.nonce,
                version=self._version,
            )
            signed_claims = self._key_service.sign_handshake_claims(claims)
            await self._connection.send_json(signed_claims.model_dump(mode="json"))

            accepted = RelayAcceptedResponse.model_validate(
                await self._connection.receive_json()
            )
            if accepted.relay_session_id != challenge.relay_session_id:
                raise ValueError("accepted relay session mismatch")
            self._accepted = accepted
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(accepted.relay_session_id)
            )
            return accepted
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

        if self._connection_context is not None:
            await self._connection_context.__aexit__(None, None, None)
            self._connection_context = None
            self._connection = None
            self._accepted = None

    async def _heartbeat_loop(self, relay_session_id: str) -> None:
        while True:
            await self._sleep(self._heartbeat_interval_seconds)
            if self._connection is None:
                return
            await self._connection.send_json(
                {"type": "heartbeat", "relay_session_id": relay_session_id}
            )
