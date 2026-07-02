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


class RelayInvocationError(RuntimeError):
    pass


class NoLiveRelaySession(RelayInvocationError):
    pass


class RelayInvocationTimeout(RelayInvocationError):
    pass


class RelayInvocationBroker:
    def __init__(self) -> None:
        self._connections: dict[str, RelayInvocationConnection] = {}
        self._pending: dict[str, asyncio.Future[RelayInvocationResultFrame]] = {}
        self._pending_sessions: dict[str, str] = {}
        self._session_sequences: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        relay_session_id: str,
        connection: RelayInvocationConnection,
    ) -> None:
        async with self._lock:
            self._connections[relay_session_id] = connection

    async def unregister(self, relay_session_id: str) -> None:
        async with self._lock:
            self._connections.pop(relay_session_id, None)
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
                    future.set_exception(
                        NoLiveRelaySession("relay session disconnected")
                    )

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
            sequence = self._session_sequences.get(relay_session_id, 0) + 1
            self._session_sequences[relay_session_id] = sequence
            self._pending[relay_invocation_id] = future
            self._pending_sessions[relay_invocation_id] = relay_session_id
        frame = RelayInvocationEnvelope(
            type="invocation",
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
            await connection.send_json(frame.model_dump(mode="json"))
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
