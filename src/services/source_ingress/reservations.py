"""Dormant metadata reservations under borrowed conversation/authority exclusion.

This module accepts no content and supplies no production authority adapter.
Authority implementations must retain real exclusion until explicit retirement,
must not re-enter either store, and must not perform network/provider work.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from src.services.agent_runs.coordinator import CoordinatorBorrow
from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.source_ownership import (
    ConversationFence,
    OwnedConversation,
)
from src.services.source_ingress.reservation_contracts import (
    MAX_SOURCE_LIFETIME,
    MAX_SQLITE_INTEGER,
    MAX_UPLOAD_LIFETIME,
    ReservationError,
    ReservationNamespace,
    ReservationReceipt,
    ReservationRequest,
    ResolvedSourceAuthority,
    SourceOperatorContext,
    require_private_text,
)
from src.services.source_ingress.reservation_store import (
    ReservationStore,
    ReservationTransaction,
)

_OPERATION_SECONDS = 2.0


class AuthorityFence(Protocol):
    def acquire(self, *, deadline: float) -> None: ...
    def resolve(self) -> ResolvedSourceAuthority: ...
    def require_current(self, *, now: float) -> None: ...
    def retire(self) -> None: ...


class SourceAuthority(Protocol):
    def fence(
        self,
        operator_context: SourceOperatorContext,
        *,
        provider_connection_id: str,
        monotonic: Callable[[], float],
        purpose: Literal["operator_source_setup"],
    ) -> AuthorityFence: ...


@dataclass(repr=False)
class _Operation:
    deadline: float = 0.0
    borrow: CoordinatorBorrow | None = None
    conversation: ConversationFence | None = None
    source: ReservationTransaction | None = None
    authority: AuthorityFence | None = None
    resolved: ResolvedSourceAuthority | None = None
    owned: OwnedConversation | None = None
    namespace: ReservationNamespace | None = None
    receipt: ReservationReceipt | None = None
    commit_attempted: bool = False
    commit_known: bool = False
    uncertain: bool = False

    @property
    def retired(self) -> bool:
        return all(
            scope is None
            for scope in (self.authority, self.source, self.conversation, self.borrow)
        )

    def retire(self) -> None:
        # Stop at the first uncertain retirement. Each scope retains its own
        # stages, so later explicit close retries that exact scope in order.
        for name in ("authority", "source", "conversation", "borrow"):
            scope = getattr(self, name)
            if scope is not None:
                try:
                    scope.retire()
                except BaseException:
                    if name == "borrow" and scope.retirement_completed:
                        # All earlier contexts already retired. Preserve the
                        # control-flow exception without inventing live work.
                        setattr(self, name, None)
                    raise
                setattr(self, name, None)


class SourceReservationCoordinator:
    def __init__(
        self,
        agent_runs: AgentRunService,
        store: ReservationStore,
        authority: SourceAuthority | None,
        *,
        expected_target_fingerprint: str,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        require_private_text(expected_target_fingerprint)
        if (store.account_id, store.execution_target_id) != (
            agent_runs.store.account_id,
            agent_runs.store.execution_target_id,
        ):
            raise ReservationError("reservation_unavailable")
        self._agent_runs = agent_runs
        self._store = store
        self._authority = authority
        self._fingerprint = expected_target_fingerprint
        self._clock = clock
        self._monotonic = monotonic
        self._pid = os.getpid()
        self._state_lock = threading.Lock()
        self._operation: _Operation | None = None
        self._running = False
        self._failed = False
        self._closed = False

    def _require_process(self) -> None:
        # A copied mutex may remain locked by a thread that does not exist in
        # the child. Reject before touching it or borrowing copied ownership.
        if os.getpid() != self._pid:
            raise ReservationError("reservation_unavailable")

    @staticmethod
    def _number(value: float) -> float:
        try:
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError
        except Exception:
            raise ReservationError("reservation_unavailable") from None
        return value

    def _read_clock(self, clock: Callable[[], float]) -> float:
        try:
            return self._number(clock())
        except Exception:
            raise ReservationError("reservation_unavailable") from None

    def _now(self) -> float:
        now = self._read_clock(self._clock)
        if not 0 <= now < MAX_SQLITE_INTEGER:
            raise ReservationError("reservation_unavailable")
        return now

    def _budget(self, operation: _Operation) -> None:
        if self._read_clock(self._monotonic) >= operation.deadline:
            raise ReservationError("reservation_unavailable")

    def _current(self, operation: _Operation) -> float:
        self._budget(operation)
        operation.borrow.require_source_usable()
        now = self._now()
        self._require_authority(operation, now)
        operation.conversation.require_current(now=now)
        self._budget(operation)
        return now

    @staticmethod
    def _require_authority(operation: _Operation, now: float) -> None:
        try:
            operation.authority.require_current(now=now)
            if now >= operation.resolved.authorization_expires_at:
                raise ReservationError("reservation_unavailable")
        except Exception:
            raise ReservationError("reservation_unavailable") from None

    def _response_time(self, operation: _Operation) -> None:
        now = self._now()
        self._budget(operation)
        if (
            now >= operation.resolved.authorization_expires_at
            or now >= operation.owned.expires_at
        ):
            raise ReservationError("reservation_unavailable")
        if operation.receipt is not None and now >= operation.receipt.upload_expires_at:
            raise ReservationError("reservation_expired")

    def _validate_commit(self, operation: _Operation) -> None:
        self._current(operation)
        operation.borrow.require_source_usable()
        # No further storage/authority operation follows these clock samples.
        self._response_time(operation)

    def _quarantine(self, operation: _Operation) -> None:
        self._failed = True
        operation.uncertain = True
        if operation.borrow is not None:
            operation.borrow.quarantine()

    def reserve(
        self,
        *,
        operator_context: SourceOperatorContext,
        provider_connection_id: str,
        conversation_reference: str,
        request: ReservationRequest,
    ) -> ReservationReceipt:
        if type(request) is not ReservationRequest:
            raise ReservationError("invalid_request")
        return self._run(
            operator_context,
            provider_connection_id,
            conversation_reference,
            request.request_key,
            request,
        )

    def recover(
        self,
        *,
        operator_context: SourceOperatorContext,
        provider_connection_id: str,
        conversation_reference: str,
        request_key: str,
    ) -> ReservationReceipt:
        return self._run(
            operator_context,
            provider_connection_id,
            conversation_reference,
            request_key,
            None,
        )

    def _run(
        self, context, connection_id, conversation_reference, request_key, request
    ):
        self._require_process()
        with self._state_lock:
            if self._closed or self._failed or self._operation is not None:
                raise ReservationError("reservation_unavailable")
            operation = _Operation()
            self._operation = operation
            self._running = True
        error = None
        try:
            operation.deadline = self._read_clock(self._monotonic) + _OPERATION_SECONDS
            self._number(operation.deadline)
            self._perform(
                operation,
                context,
                connection_id,
                conversation_reference,
                request_key,
                request,
            )
        except ReservationError as caught:
            error = caught
        except Exception:
            error = ReservationError("reservation_unavailable")
        finally:
            try:
                if operation.commit_attempted and not operation.commit_known:
                    self._quarantine(operation)
                if not operation.uncertain:
                    operation.retire()
            except BaseException as interrupted:
                if not operation.retired:
                    self._quarantine(operation)
                if not isinstance(interrupted, Exception):
                    raise
                error = ReservationError("reservation_unavailable")
            finally:
                with self._state_lock:
                    self._running = False
                    if not operation.uncertain:
                        self._operation = None
        # Metadata-dependent errors disclose an authorized observation too.
        # Capacity denial can have no receipt, but still has captured authority
        # and conversation lifetimes that must survive cleanup.
        if error is None or error.code in {
            "request_conflict",
            "source_limit_exceeded",
            "reservation_expired",
        }:
            self._response_time(operation)
        if error is not None:
            raise error from None
        return operation.receipt

    def _perform(
        self,
        operation,
        context,
        connection_id,
        conversation_reference,
        request_key,
        request,
    ):
        if self._authority is None or type(context) is not SourceOperatorContext:
            raise ReservationError("reservation_unavailable")
        try:
            require_private_text(connection_id)
            require_private_text(request_key, key=True)
        except ReservationError:
            raise ReservationError("reservation_unavailable") from None
        self._budget(operation)
        operation.borrow, generation = self._agent_runs.borrow_coordinator()
        operation.conversation = self._agent_runs.store.conversation_fence(
            borrow=operation.borrow, generation=generation, monotonic=self._monotonic
        )
        operation.conversation.acquire(deadline=operation.deadline)
        operation.source = self._store.transaction(monotonic=self._monotonic)
        operation.source.acquire(deadline=operation.deadline)
        try:
            operation.authority = self._authority.fence(
                context,
                provider_connection_id=connection_id,
                monotonic=self._monotonic,
                purpose="operator_source_setup",
            )
            operation.authority.acquire(deadline=operation.deadline)
            resolved = operation.authority.resolve()
        except Exception:
            raise ReservationError("reservation_unavailable") from None
        if type(resolved) is not ResolvedSourceAuthority or (
            resolved.account_id,
            resolved.provider_connection_id,
            resolved.execution_target_id,
            resolved.target_fingerprint,
            resolved.purpose,
        ) != (
            self._store.account_id,
            connection_id,
            self._store.execution_target_id,
            self._fingerprint,
            "operator_source_setup",
        ):
            raise ReservationError("reservation_unavailable")
        operation.resolved = resolved
        now = self._now()
        self._require_authority(operation, now)
        operation.owned = operation.conversation.resolve(
            conversation_reference=conversation_reference,
            connection_id=connection_id,
            link_epoch=resolved.link_epoch,
            now=now,
        )
        operation.namespace = ReservationNamespace(
            account_id=resolved.account_id,
            provider_connection_id=connection_id,
            link_epoch=resolved.link_epoch,
            conversation_reference=conversation_reference,
            execution_target_id=resolved.execution_target_id,
            target_fingerprint=resolved.target_fingerprint,
            request_key=request_key,
        )
        existing = operation.source.lookup(operation.namespace)
        now = self._current(operation)
        if existing is not None:
            operation.receipt = existing.to_receipt()
            self._response_time(operation)
            if request is not None and existing.request != request:
                raise ReservationError("request_conflict")
        elif request is None:
            raise ReservationError("reservation_unavailable")
        else:
            admitted_at = int(now)
            record = operation.source.insert(
                operation.namespace,
                request,
                admitted_revision=operation.owned.revision,
                admitted_at=admitted_at,
                upload_expires_at=min(
                    admitted_at + MAX_UPLOAD_LIFETIME, operation.owned.expires_at
                ),
                prospective_source_expires_at=min(
                    admitted_at + MAX_SOURCE_LIFETIME, operation.owned.expires_at
                ),
            )
            operation.receipt = record.to_receipt()
            self._current(operation)
            self._response_time(operation)
            try:
                operation.source.commit(
                    _validate=lambda: self._validate_commit(operation)
                )
            finally:
                operation.commit_attempted = operation.source.commit_attempted
                operation.commit_known = operation.source.committed
        self._current(operation)
        self._response_time(operation)

    def close(self) -> None:
        """Retry retained cleanup, never unlock the Agent Run owner's lease.

        Explicit cleanup must use the thread owning the captured SQLite scopes.
        Concurrent close stops new admission but cannot reclaim a running call.
        """
        self._require_process()
        with self._state_lock:
            self._closed = True
            if self._running:
                raise ReservationError("reservation_unavailable")
            operation = self._operation
            self._running = operation is not None
        try:
            if operation is not None:
                operation.retire()
                self._operation = None
        except BaseException as interrupted:
            if operation.retired:
                self._operation = None
            else:
                self._quarantine(operation)
            if not isinstance(interrupted, Exception):
                raise
            raise ReservationError("reservation_unavailable") from None
        finally:
            with self._state_lock:
                self._running = False
