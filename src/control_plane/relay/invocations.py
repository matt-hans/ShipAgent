from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
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


@dataclass
class _SessionOperationLock:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    owner: asyncio.Task[Any] | None = None
    depth: int = 0


class RelayDeviceSessionOperationGuard:
    """Serializes authenticated work for one relay device within this process."""

    def __init__(self) -> None:
        self._locks: dict[tuple[str, str], _SessionOperationLock] = {}

    @asynccontextmanager
    async def hold(
        self,
        account_id: str,
        device_id: str,
    ) -> AsyncIterator[None]:
        key = (account_id, device_id)
        operation_lock = self._locks.setdefault(key, _SessionOperationLock())
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("relay session guard requires an asyncio task")
        if operation_lock.owner is task:
            operation_lock.depth += 1
            try:
                yield
            finally:
                operation_lock.depth -= 1
            return

        await operation_lock.lock.acquire()
        operation_lock.owner = task
        operation_lock.depth = 1
        try:
            yield
        finally:
            operation_lock.depth -= 1
            if operation_lock.depth == 0:
                operation_lock.owner = None
                operation_lock.lock.release()

    @asynccontextmanager
    async def hold_many(
        self,
        account_id: str,
        device_ids: set[str],
    ) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            for device_id in sorted(device_ids):
                await stack.enter_async_context(self.hold(account_id, device_id))
            yield


class RelayInvocationBroker:
    def __init__(
        self,
        session_operation_guard: RelayDeviceSessionOperationGuard | None = None,
    ) -> None:
        self._connections: dict[str, RelayInvocationConnection] = {}
        self._session_devices: dict[str, tuple[str, str]] = {}
        self._pending: dict[str, asyncio.Future[RelayInvocationResultFrame]] = {}
        self._pending_sessions: dict[str, str] = {}
        self._session_sequences: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._session_operation_guard = (
            session_operation_guard or RelayDeviceSessionOperationGuard()
        )

    @property
    def session_operation_guard(self) -> RelayDeviceSessionOperationGuard:
        return self._session_operation_guard

    async def register(
        self,
        relay_session_id: str,
        connection: RelayInvocationConnection,
        *,
        account_id: str | None = None,
        device_id: str | None = None,
    ) -> None:
        if account_id is None or device_id is None:
            async with self._lock:
                self._connections[relay_session_id] = connection
            return

        async with self._session_operation_guard.hold(account_id, device_id):
            await self._replace_device_session(
                relay_session_id,
                connection,
                account_id=account_id,
                device_id=device_id,
            )

    async def _replace_device_session(
        self,
        relay_session_id: str,
        connection: RelayInvocationConnection,
        *,
        account_id: str,
        device_id: str,
    ) -> None:
        async with self._lock:
            prior_connections = [
                (prior_session_id, prior_connection)
                for prior_session_id, prior_connection in self._connections.items()
                if self._session_devices.get(prior_session_id)
                == (account_id, device_id)
                and (
                    prior_session_id != relay_session_id
                    or prior_connection is not connection
                )
            ]
            for prior_session_id, prior_connection in prior_connections:
                self._unregister_locked(
                    prior_session_id,
                    connection=prior_connection,
                )
        for _prior_session_id, prior_connection in prior_connections:
            try:
                await prior_connection.close(code=1008, reason="relay session replaced")
            except Exception:
                continue
        async with self._lock:
            self._connections[relay_session_id] = connection
            self._session_devices[relay_session_id] = (account_id, device_id)

    async def unregister(
        self,
        relay_session_id: str,
        *,
        connection: RelayInvocationConnection | None = None,
    ) -> None:
        session_device = await self._get_session_device(relay_session_id)
        if session_device is not None:
            async with self._session_operation_guard.hold(*session_device):
                async with self._lock:
                    self._unregister_locked(relay_session_id, connection=connection)
            return
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
        async with self._session_operation_guard.hold(account_id, device_id):
            await self._disconnect_device_sessions(
                account_id=account_id,
                device_id=device_id,
                code=code,
                reason=reason,
            )

    async def _disconnect_device_sessions(
        self,
        *,
        account_id: str,
        device_id: str,
        code: int,
        reason: str,
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

    async def _get_session_device(
        self,
        relay_session_id: str,
    ) -> tuple[str, str] | None:
        async with self._lock:
            return self._session_devices.get(relay_session_id)

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
        try:
            session_device = await self._get_session_device(relay_session_id)
            if session_device is None:
                await self._admit_and_send(
                    relay_session_id=relay_session_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    audit_correlation_id=audit_correlation_id,
                    timeout_seconds=timeout_seconds,
                    relay_invocation_id=relay_invocation_id,
                    idempotency_key=idempotency_key,
                    future=future,
                )
            else:
                async with self._session_operation_guard.hold(*session_device):
                    await self._admit_and_send(
                        relay_session_id=relay_session_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        audit_correlation_id=audit_correlation_id,
                        timeout_seconds=timeout_seconds,
                        relay_invocation_id=relay_invocation_id,
                        idempotency_key=idempotency_key,
                        future=future,
                    )
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except TimeoutError as exc:
            raise RelayInvocationTimeout("relay invocation timed out") from exc
        finally:
            async with self._lock:
                self._pending.pop(relay_invocation_id, None)
                self._pending_sessions.pop(relay_invocation_id, None)

    async def _admit_and_send(
        self,
        *,
        relay_session_id: str,
        tool_name: str,
        arguments: dict[str, object],
        audit_correlation_id: str,
        timeout_seconds: float,
        relay_invocation_id: str,
        idempotency_key: str,
        future: asyncio.Future[RelayInvocationResultFrame],
    ) -> None:
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
            await connection.send_json(frame.model_dump(mode="json"))
        except Exception as exc:
            await self.unregister(relay_session_id, connection=connection)
            raise NoLiveRelaySession("relay session send failed") from exc

    async def accept_result(self, frame: RelayInvocationResultFrame) -> None:
        async with self._lock:
            future = self._pending.get(frame.relay_invocation_id)
            relay_session_id = self._pending_sessions.get(frame.relay_invocation_id)
            if future is None or relay_session_id != frame.relay_session_id:
                return
            if not future.done():
                future.set_result(frame)
