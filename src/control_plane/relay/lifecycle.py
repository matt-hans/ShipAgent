"""Dormant accepted-job coordination; never injected into local or hosted apps."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from src.control_plane.execution_targets import DurableExecutionTarget
from src.control_plane.relay.lifecycle_store import (
    InvocationLifecycleStore,
    InvocationRecord,
    InvocationState,
    JobReferenceStore,
    LifecycleUnavailable,
)
from src.control_plane.relay.protocol import (
    InvocationIdentity,
    relay_invocation_input_hash,
)


class GrantCallbacks(Protocol):
    """Plan 7's fenced authority operations, not a second invocation lifecycle.

    The callback implementation is required and must reserve non-reusably before
    returning, bind the original reservation fence to this invocation, perform
    idempotent bounded I/O, and never revive missing/expired authorization.
    ``release`` here is privileged evidence-backed reconciliation; it is NOT an
    alias for an ordinary stale ``ExecutionGrantReservation.release``. Neither
    the coordinator nor Redis metadata authorizes a purchase by itself.
    """

    async def reserve(self, record: InvocationRecord) -> None: ...

    async def consume_on_accept(self, record: InvocationRecord) -> None: ...

    async def release(self, record: InvocationRecord) -> None: ...

    async def hold_for_reconciliation(self, record: InvocationRecord) -> None: ...


@dataclass(frozen=True)
class TimeoutLadder:
    cloud_send_seconds: float = 2.0
    target_accept_seconds: float = 5.0
    sync_hard_deadline_seconds: float = 25.0
    poll_after_ms: int = 2000

    def __post_init__(self):
        for value, maximum in (
            (self.cloud_send_seconds, 2),
            (self.target_accept_seconds, 5),
            (self.sync_hard_deadline_seconds, 25),
        ):
            if (
                not isinstance(value, (float, int))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or not 0 < value <= maximum
            ):
                raise ValueError("invalid lifecycle timeout ladder")
        if (
            self.cloud_send_seconds + self.target_accept_seconds
            >= self.sync_hard_deadline_seconds
        ):
            raise ValueError("send and accept must fit within the overall deadline")
        if (
            type(self.poll_after_ms) is not int
            or not 100 <= self.poll_after_ms <= 60_000
        ):
            raise ValueError("invalid polling delay")


_PENDING_OPERATIONS: set[asyncio.Task] = set()


def _observe_operation(task: asyncio.Task) -> None:
    _PENDING_OPERATIONS.discard(task)
    if not task.cancelled():
        task.exception()  # Retrieve eventual outcomes; never log dependency payloads.


class _Budget:
    """Bound local wait without waiting forever for cancellation cleanup.

    Dependencies must still fence and bound their own I/O. Cancellation cannot
    undo a remote write; retained tasks may finish later, never trigger dispatch.
    """

    def __init__(self, seconds: float):
        self.deadline = asyncio.get_running_loop().time() + seconds
        self.wall_deadline = datetime.now(UTC) + timedelta(seconds=seconds)

    async def call(self, operation: Coroutine[Any, Any, Any], *, cap=None):
        remaining = self.deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            operation.close()
            raise TimeoutError()
        task = asyncio.create_task(operation)
        _PENDING_OPERATIONS.add(task)
        task.add_done_callback(_observe_operation)
        try:
            done, _ = await asyncio.wait(
                {task}, timeout=min(remaining, cap) if cap else remaining
            )
        except asyncio.CancelledError:
            task.cancel()
            raise
        if not done:
            task.cancel()
            raise TimeoutError()
        if task.cancelled():
            raise LifecycleUnavailable()
        return task.result()


def build_processing_envelope(job_ref: str) -> dict[str, str | int]:
    return {"status": "processing", "job_ref": job_ref, "poll_after_ms": 2000}


def build_unknown_envelope(job_ref: str) -> dict[str, object]:
    return {
        "status": "processing_unknown",
        "reason": "processing_unknown",
        "terminal": False,
        "message": "Check the existing job before retrying; acceptance is still being reconciled.",
        "job_ref": job_ref,
        "poll_after_ms": 2000,
    }


def build_expired_envelope() -> dict[str, object]:
    return {
        "status": "blocked",
        "reason": "approval_expired",
        "terminal": True,
        "message": "This authorization expired. Check any existing job before requesting a new preview and approval.",
    }


class InvocationLifecycleCoordinator:
    def __init__(
        self,
        *,
        invocation_store: InvocationLifecycleStore,
        job_reference_store: JobReferenceStore,
        timeout_ladder: TimeoutLadder | None = None,
    ):
        self.invocations = invocation_store
        self.job_refs = job_reference_store
        self.timeouts = timeout_ladder or TimeoutLadder()

    async def invoke(
        self,
        *,
        target: DurableExecutionTarget,
        identity: InvocationIdentity,
        arguments: dict[str, object],
        grant_callbacks: GrantCallbacks,
    ) -> dict[str, object]:
        budget = _Budget(self.timeouts.sync_hard_deadline_seconds)
        record = None
        try:
            if (
                target.execution_target_id != identity.execution_target_id
                or relay_invocation_input_hash(identity.tool_name, arguments)
                != identity.arguments_hash
            ):
                raise LifecycleUnavailable()
            if datetime.now(UTC) >= identity.authorization_expires_at:
                try:
                    record = await budget.call(
                        self.invocations.get(
                            identity.relay_invocation_id,
                            account_id=identity.account_id,
                            provider_connection_id=identity.provider_connection_id,
                        )
                    )
                except Exception:
                    return build_expired_envelope()
                if record.identity != identity:
                    raise LifecycleUnavailable()
                return await self._reconcile(target, record, grant_callbacks, budget)
            record, created = await budget.call(self.invocations.create(identity))
            if not created:
                return await self._reconcile(target, record, grant_callbacks, budget)
            await budget.call(grant_callbacks.reserve(record))
            if datetime.now(UTC) >= identity.authorization_expires_at:
                await self._unknown(record, grant_callbacks, budget)
                return build_expired_envelope()
            sent = await budget.call(
                self.invocations.transition(record, InvocationState.SENT_TO_TARGET)
            )
            if sent is None:
                raise LifecycleUnavailable()
            record = sent
            await budget.call(
                target.dispatch_invocation(
                    identity=identity,
                    arguments=arguments,
                    deadline_at=min(
                        identity.authorization_expires_at, budget.wall_deadline
                    ),
                ),
                cap=self.timeouts.cloud_send_seconds,
            )
            return await self._reconcile(target, sent, grant_callbacks, budget)
        except Exception:
            if record is None:
                raise LifecycleUnavailable() from None
            await self._unknown(record, grant_callbacks, budget)
            return build_unknown_envelope(record.job_ref)

    async def reconcile(
        self,
        *,
        target: DurableExecutionTarget,
        job_ref: str,
        account_id: str,
        provider_connection_id: str,
        grant_callbacks: GrantCallbacks,
    ) -> dict[str, object]:
        budget = _Budget(self.timeouts.sync_hard_deadline_seconds)
        record = await budget.call(
            self.job_refs.resolve(
                job_ref,
                account_id=account_id,
                provider_connection_id=provider_connection_id,
            )
        )
        return await self._reconcile(target, record, grant_callbacks, budget)

    async def _unknown(self, record, callbacks, budget):
        try:
            state = (
                InvocationState.ABANDONED
                if record.state == InvocationState.QUEUED
                else InvocationState.TARGET_DISCONNECTED_MID_CALL
            )
            if record.state in {InvocationState.QUEUED, InvocationState.SENT_TO_TARGET}:
                changed = await budget.call(self.invocations.transition(record, state))
                record = changed or record
        except Exception:
            pass
        await self._hold(record, callbacks, budget)

    async def _hold(self, record, callbacks, budget):
        try:
            await budget.call(callbacks.hold_for_reconciliation(record))
        except Exception:
            pass

    async def _reconcile(self, target, record, callbacks, budget):
        if target.execution_target_id != record.identity.execution_target_id:
            raise LifecycleUnavailable()
        if record.evidence is not None:
            return await self._settle(record, callbacks, budget)
        try:
            proof = await budget.call(
                target.get_acceptance(record.identity),
                cap=self.timeouts.target_accept_seconds,
            )
            if proof.outcome == "unknown":
                await self._hold(record, callbacks, budget)
                return build_unknown_envelope(record.job_ref)
            accepted = await budget.call(
                self.invocations.record_evidence(record, proof)
            )
            if accepted is None:
                raise LifecycleUnavailable()
        except Exception:
            await self._unknown(record, callbacks, budget)
            return build_unknown_envelope(record.job_ref)
        return await self._settle(accepted, callbacks, budget)

    async def _settle(self, record, callbacks, budget):
        expired = datetime.now(UTC) >= record.identity.authorization_expires_at
        if record.evidence.outcome == "not_accepted":
            if expired:
                return build_expired_envelope()
            try:
                await budget.call(callbacks.release(record))
            except Exception:
                await self._hold(record, callbacks, budget)
                return build_unknown_envelope(record.job_ref)
            return {
                "status": "unavailable",
                "reason": "target_offline",
                "terminal": True,
                "message": "The target positively rejected this invocation. Reconnect before continuing.",
            }
        if expired:
            await self._hold(record, callbacks, budget)
        else:
            try:
                await budget.call(callbacks.consume_on_accept(record))
            except Exception:
                await self._hold(record, callbacks, budget)
        return build_processing_envelope(record.job_ref)
