from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from src.control_plane.relay.protocol import (
    RelayInvocationEnvelope,
    RelayInvocationResultFrame,
    relay_invocation_input_hash,
)


class RelayInvocationConnection(Protocol):
    async def send_json(self, payload: dict[str, Any]) -> None: ...

    async def close(self, code: int = 1000, reason: str | None = None) -> None: ...


class RelayInvocationError(RuntimeError):
    pass


class NoLiveRelaySession(RelayInvocationError):
    pass


class RelayInvocationTimeout(RelayInvocationError):
    pass


class RelayInvocationBusy(RelayInvocationError):
    pass


class RelayInvocationBroker:
    def __init__(self) -> None:
        self._connections: dict[str, RelayInvocationConnection] = {}
        self._session_devices: dict[str, tuple[str, str]] = {}
        self._pending: dict[str, asyncio.Future[RelayInvocationResultFrame]] = {}
        self._pending_sessions: dict[str, str] = {}
        self._session_sequences: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        relay_session_id: str,
        connection: RelayInvocationConnection,
        *,
        account_id: str | None = None,
        device_id: str | None = None,
    ) -> None:
        async with self._lock:
            self._connections[relay_session_id] = connection
            if account_id is not None and device_id is not None:
                self._session_devices[relay_session_id] = (account_id, device_id)

    async def unregister(
        self,
        relay_session_id: str,
        *,
        connection: RelayInvocationConnection | None = None,
    ) -> None:
        async with self._lock:
            self._unregister_locked(relay_session_id, connection=connection)

    def _unregister_locked(
        self,
        relay_session_id: str,
        *,
        connection: RelayInvocationConnection | None = None,
    ) -> None:
        if (
            connection is not None
            and self._connections.get(relay_session_id) is not connection
        ):
            return
        self._connections.pop(relay_session_id, None)
        self._session_devices.pop(relay_session_id, None)
        self._session_sequences.pop(relay_session_id, None)
        invocation_ids = [
            invocation_id
            for invocation_id, pending_session_id in self._pending_sessions.items()
            if pending_session_id == relay_session_id
        ]
        for invocation_id in invocation_ids:
            future = self._pending.pop(invocation_id, None)
            self._pending_sessions.pop(invocation_id, None)
            if future is not None and not future.done():
                future.set_exception(NoLiveRelaySession("relay session disconnected"))

    async def disconnect_device(
        self,
        *,
        account_id: str,
        device_id: str,
        code: int = 1008,
        reason: str = "relay device disconnected",
    ) -> None:
        async with self._lock:
            matches = [
                (relay_session_id, self._connections[relay_session_id])
                for relay_session_id, session_device in self._session_devices.items()
                if session_device == (account_id, device_id)
                and relay_session_id in self._connections
            ]
            for relay_session_id, connection in matches:
                self._unregister_locked(relay_session_id, connection=connection)
        for _relay_session_id, connection in matches:
            try:
                await connection.close(code=code, reason=reason)
            except Exception:
                continue

    async def invoke(
        self,
        *,
        relay_session_id: str,
        tool_name: str,
        arguments: dict[str, object],
        audit_correlation_id: str,
        timeout_seconds: float,
    ) -> RelayInvocationResultFrame:
        relay_invocation_id = f"relay_invocation_{uuid.uuid4().hex}"
        idempotency_key = f"relay_idempotency_{uuid.uuid4().hex}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[RelayInvocationResultFrame] = loop.create_future()
        async with self._lock:
            connection = self._connections.get(relay_session_id)
            if connection is None:
                raise NoLiveRelaySession("no live relay session")
            if relay_session_id in self._pending_sessions.values():
                raise RelayInvocationBusy(
                    "relay session already has an in-flight invocation"
                )
            sequence = self._session_sequences.get(relay_session_id, 0) + 1
            self._session_sequences[relay_session_id] = sequence
            self._pending[relay_invocation_id] = future
            self._pending_sessions[relay_invocation_id] = relay_session_id
        frame = RelayInvocationEnvelope(
            type="relay.invoke",
            relay_session_id=relay_session_id,
            sequence=sequence,
            relay_invocation_id=relay_invocation_id,
            tool_name=tool_name,
            arguments=arguments,
            input_hash=relay_invocation_input_hash(tool_name, arguments),
            deadline_at=datetime.now(UTC) + timedelta(seconds=timeout_seconds),
            idempotency_key=idempotency_key,
            audit_correlation_id=audit_correlation_id,
        )
        try:
            try:
                await connection.send_json(frame.model_dump(mode="json"))
            except Exception as exc:
                await self.unregister(relay_session_id)
                raise NoLiveRelaySession("relay session send failed") from exc
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except TimeoutError as exc:
            raise RelayInvocationTimeout("relay invocation timed out") from exc
        finally:
            async with self._lock:
                self._pending.pop(relay_invocation_id, None)
                self._pending_sessions.pop(relay_invocation_id, None)

    async def accept_result(self, frame: RelayInvocationResultFrame) -> None:
        async with self._lock:
            future = self._pending.get(frame.relay_invocation_id)
            relay_session_id = self._pending_sessions.get(frame.relay_invocation_id)
            if future is None or relay_session_id != frame.relay_session_id:
                return
            if not future.done():
                future.set_result(frame)
