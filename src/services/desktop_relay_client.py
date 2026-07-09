from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, suppress
from datetime import UTC, datetime
from typing import Any, Protocol

from websockets.asyncio.client import connect as websocket_connect

from src.control_plane.relay.protocol import (
    ExecutionTargetStatus,
    RelayHandshakeChallenge,
    RelayInvocationEnvelope,
    RelayInvocationResultFrame,
    RelayProtocolModel,
    RelayTargetState,
    RelayVersionMetadata,
    ShipAgentStatus,
    build_handshake_claims,
    relay_invocation_input_hash,
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
        self._receive_task: asyncio.Task[None] | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._processed_relay_invocation_ids: set[str] = set()
        self._processed_idempotency_keys: set[str] = set()
        self._last_invocation_sequence = 0

    async def start(self) -> RelayAcceptedResponse:
        async with self._lifecycle_lock:
            if self._connection_context is not None:
                raise RuntimeError("relay client is already started")

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
                if accepted.state != RelayTargetState.READY:
                    raise ValueError("accepted relay state must be ready")
                if accepted.execution_target_id != f"relay:{self._device_id}":
                    raise ValueError("accepted execution target mismatch")
                self._accepted = accepted
                self._reset_invocation_replay_state()
                self._heartbeat_task = asyncio.create_task(
                    self._heartbeat_loop(accepted.relay_session_id)
                )
                self._receive_task = asyncio.create_task(
                    self._receive_loop(accepted.relay_session_id)
                )
                return accepted
            except BaseException:
                await self._stop_unlocked()
                raise

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            await self._stop_unlocked()

    async def _stop_unlocked(self) -> None:
        try:
            if self._receive_task is not None:
                self._receive_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await self._receive_task
                self._receive_task = None
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await self._heartbeat_task
                self._heartbeat_task = None
        finally:
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
            await self._send_json(
                {"type": "heartbeat", "relay_session_id": relay_session_id}
            )

    async def _receive_loop(self, relay_session_id: str) -> None:
        while True:
            if self._connection is None:
                return
            payload = await self._connection.receive_json()
            frame_type = payload.get("type")
            if frame_type != "invocation":
                continue
            invocation = RelayInvocationEnvelope.model_validate(payload)
            if invocation.relay_session_id != relay_session_id:
                await self._send_invocation_error(
                    invocation,
                    error_code="wrong_relay_session",
                    message="Invocation was not addressed to this relay session.",
                )
                return
            if invocation.relay_invocation_id in self._processed_relay_invocation_ids:
                await self._send_invocation_error(
                    invocation,
                    error_code="duplicate_invocation",
                    message="Relay invocation has already been processed.",
                )
                continue
            if invocation.idempotency_key in self._processed_idempotency_keys:
                await self._send_invocation_error(
                    invocation,
                    error_code="duplicate_idempotency_key",
                    message="Relay invocation idempotency key has already been processed.",
                )
                continue
            if invocation.sequence <= self._last_invocation_sequence:
                await self._send_invocation_error(
                    invocation,
                    error_code="non_increasing_sequence",
                    message="Relay invocation sequence must increase.",
                )
                continue
            deadline_at = invocation.deadline_at
            if deadline_at.tzinfo is None:
                deadline_at = deadline_at.replace(tzinfo=UTC)
            if deadline_at <= datetime.now(UTC):
                await self._send_invocation_error(
                    invocation,
                    error_code="expired_deadline",
                    message="Relay invocation deadline has expired.",
                )
                continue
            if invocation.input_hash != relay_invocation_input_hash(
                invocation.tool_name,
                invocation.arguments,
            ):
                await self._send_invocation_error(
                    invocation,
                    error_code="input_hash_mismatch",
                    message="Relay invocation input hash did not match.",
                )
                continue
            self._processed_relay_invocation_ids.add(invocation.relay_invocation_id)
            self._processed_idempotency_keys.add(invocation.idempotency_key)
            self._last_invocation_sequence = invocation.sequence
            await self._handle_invocation(invocation)

    def _reset_invocation_replay_state(self) -> None:
        self._processed_relay_invocation_ids.clear()
        self._processed_idempotency_keys.clear()
        self._last_invocation_sequence = 0

    async def _handle_invocation(self, invocation: RelayInvocationEnvelope) -> None:
        if invocation.tool_name != "get_shipagent_status":
            await self._send_invocation_error(
                invocation,
                error_code="unsupported_tool",
                message="Relay invocation tool is not supported.",
            )
            return
        accepted = self._accepted
        if accepted is None:
            await self._send_invocation_error(
                invocation,
                error_code="not_ready",
                message="Relay client is not ready.",
            )
            return
        status = ShipAgentStatus(
            status=RelayTargetState.READY,
            execution_target=ExecutionTargetStatus(
                state=RelayTargetState.READY,
                target_id=accepted.execution_target_id,
                capabilities=list(self._version.capabilities),
                message=None,
            ),
        )
        await self._send_json(
            RelayInvocationResultFrame(
                type="invocation_result",
                relay_session_id=invocation.relay_session_id,
                relay_invocation_id=invocation.relay_invocation_id,
                status="ok",
                result=status.model_dump(mode="json", by_alias=True),
            ).model_dump(mode="json")
        )

    async def _send_invocation_error(
        self,
        invocation: RelayInvocationEnvelope,
        *,
        error_code: str,
        message: str,
    ) -> None:
        await self._send_json(
            RelayInvocationResultFrame(
                type="invocation_result",
                relay_session_id=invocation.relay_session_id,
                relay_invocation_id=invocation.relay_invocation_id,
                status="error",
                error={"code": error_code, "message": message},
            ).model_dump(mode="json")
        )

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if self._connection is None:
            return
        async with self._send_lock:
            await self._connection.send_json(payload)
