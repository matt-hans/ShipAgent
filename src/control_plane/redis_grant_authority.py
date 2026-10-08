"""Dormant fenced Redis authority. Explicit construction only; no app wiring.

SQL is evidence, never a grant source. All executable transitions are existing-
key CAS against the original TTL and owner; uncertainty never releases ownership.
"""

from __future__ import annotations

import hashlib
import math
import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from src.control_plane.audit.authorization_ledger import AuthorizationMetadata
from src.control_plane.authorization_state import (
    AuthorizationState,
    AuthorizationStateStore,
)
from src.control_plane.execution_grants import (
    ExecutionGrantBinding,
    ExecutionGrantError,
    PreAcceptFailure,
)
from src.control_plane.execution_grants import (
    ExecutionGrantDenial as Denial,
)
from src.control_plane.grant_models import ApprovedPurchase, GrantRecord
from src.control_plane.relay.lifecycle import _Budget, build_processing_envelope
from src.control_plane.relay.lifecycle_store import (
    InvocationLifecycleStore,
    JobReferenceStore,
)
from src.control_plane.relay.protocol import InvocationIdentity


class LiveApprovedPreview(Protocol):
    """Trusted exact-target fetch/verification. Full preview detail is transit-only."""

    async def resolve(
        self, *, context, tool_name, prepare_tool, preview_id
    ) -> ApprovedPurchase: ...


class RedisExecutionGrantAuthority:
    def __init__(
        self,
        *,
        redis_client,
        ledger,
        live_preview: LiveApprovedPreview,
        io_timeout: float = 2.0,
        lease_seconds: float = 30.0,
        authorization_seconds: float = 900.0,
    ):
        for value, maximum in (
            (io_timeout, 5),
            (lease_seconds, 900),
            (authorization_seconds, 900),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 < value <= maximum
            ):
                raise ValueError("invalid grant deadline")
        self.state = AuthorizationStateStore(redis_client)
        self.lifecycle = InvocationLifecycleStore(redis_client)
        self.job_refs = JobReferenceStore(redis_client)
        self.ledger = ledger
        self.live_preview = live_preview
        self.io_timeout = io_timeout
        self.lease_seconds = lease_seconds
        self.authorization_seconds = authorization_seconds

    async def _bounded(self, operation):
        try:
            return await _Budget(self.io_timeout).call(operation)
        except ExecutionGrantError:
            raise
        except Exception:
            raise ExecutionGrantError(Denial.GRANT_UNAVAILABLE) from None

    async def issue_approved(self, *, context, purchase, approving_subject_hash):
        """Internal post-gesture API; never accepts a previously issued request/key.

        No public approval surface calls this dormant method. Its caller must
        establish the explicit gesture; live server data is checked again here.
        """
        return await self._bounded(
            self._issue(context, purchase, approving_subject_hash)
        )

    async def _live(self, context, purchase):
        live = await self.live_preview.resolve(
            context=context,
            tool_name=purchase.tool_name,
            prepare_tool=purchase.prepare_tool,
            preview_id=purchase.preview_id,
        )
        if type(live) is not ApprovedPurchase:
            raise ExecutionGrantError(Denial.PREVIEW_CHANGED)
        try:
            live = ApprovedPurchase.model_validate_json(live.model_dump_json())
        except ValueError:
            raise ExecutionGrantError(Denial.PREVIEW_CHANGED) from None
        if live != purchase:
            raise ExecutionGrantError(Denial.PREVIEW_CHANGED)

    async def _issue(self, context, purchase, subject_hash):
        if type(purchase) is not ApprovedPurchase:
            raise ExecutionGrantError(Denial.GRANT_INVALID)
        purchase = ApprovedPurchase.model_validate_json(purchase.model_dump_json())
        if (
            purchase.account_id != context.account_id
            or purchase.provider_connection_id != context.provider_connection_id
            or subject_hash != hashlib.sha256(context.subject.encode()).hexdigest()
        ):
            raise ExecutionGrantError(Denial.GRANT_INVALID)
        await self._live(context, purchase)
        approval_id = "sa_approval_request_" + secrets.token_hex(16)
        grant = GrantRecord(
            purchase=purchase,
            idempotency_key=secrets.token_urlsafe(32),
            status="pending",
        )
        metadata = AuthorizationMetadata(
            account_id=context.account_id,
            provider_connection_id=context.provider_connection_id,
            approval_request_id=approval_id,
            preview_hash=purchase.preview_hash,
            purchase_scope_hash=purchase.scope_hash,
            authorized_amount_minor=int(Decimal(purchase.amount) * 100),
            currency=purchase.currency_code,
            approving_subject_hash=subject_hash,
            execution_target_fingerprint_hash=purchase.execution_target_fingerprint_hash,
            idempotency_key_hash=hashlib.sha256(
                grant.idempotency_key.encode()
            ).hexdigest(),
        )
        now = datetime.now(UTC)
        pending = AuthorizationState(
            metadata=metadata,
            created_at=now,
            expires_at=now + timedelta(seconds=self.authorization_seconds),
            grant=grant,
        )
        # Even a delayed CREATE after account cleanup is inert and TTL-bound.
        await self.ledger.record(metadata, "requested", context=context)
        if not await self.state.create(
            "approval_request", replace(pending, grant=None)
        ):
            raise ExecutionGrantError(Denial.GRANT_UNAVAILABLE)
        if not await self.state.create("execution_grant", pending):
            raise ExecutionGrantError(Denial.GRANT_UNAVAILABLE)
        approved = replace(
            pending, revision=1, grant=grant.model_copy(update={"status": "approved"})
        )
        changed = await self.ledger.enable(
            context=context,
            metadata=metadata,
            transition="approved",
            operation=lambda: self.state.replace_existing(
                "execution_grant", original=pending, updated=approved
            ),
        )
        if not changed:
            raise ExecutionGrantError(Denial.GRANT_UNAVAILABLE)
        return approval_id

    async def _read(self, approval_id, context):
        record = await self.state.read(
            "execution_grant", approval_id, account_id=context.account_id
        )
        if (
            record.grant is None
            or record.metadata.provider_connection_id != context.provider_connection_id
        ):
            raise ExecutionGrantError(Denial.GRANT_UNAVAILABLE)
        # Verify the permitted ledger hashes still describe this exact purchase.
        grant = record.grant
        if (
            record.metadata.idempotency_key_hash
            != hashlib.sha256(grant.idempotency_key.encode()).hexdigest()
            or record.metadata.authorized_amount_minor
            != int(Decimal(grant.purchase.amount) * 100)
            or record.metadata.currency != grant.purchase.currency_code
            or record.metadata.execution_target_fingerprint_hash
            != grant.purchase.execution_target_fingerprint_hash
        ):
            raise ExecutionGrantError(Denial.GRANT_INVALID)
        return record

    @staticmethod
    def _denial(record):
        return {
            "pending": Denial.APPROVAL_PENDING,
            "reserved": Denial.GRANT_IN_USE,
            "held": Denial.RECONCILIATION_PENDING,
            "consumed": Denial.GRANT_CONSUMED,
            "revoked": Denial.APPROVAL_REJECTED,
        }.get(record.grant.status, Denial.GRANT_UNAVAILABLE)

    async def reserve(
        self, *, context, tool_name, prepare_tool, approval_request_id, preview_id
    ):
        return await self._bounded(
            self._reserve(
                context, tool_name, prepare_tool, approval_request_id, preview_id
            )
        )

    async def _reserve(self, context, tool, prepare, approval, preview):
        original = await self._read(approval, context)
        grant = original.grant
        if grant.status != "approved":
            raise ExecutionGrantError(self._denial(original))
        if (tool, prepare, preview) != (
            grant.purchase.tool_name,
            grant.purchase.prepare_tool,
            grant.purchase.preview_id,
        ):
            raise ExecutionGrantError(Denial.PREVIEW_CHANGED)
        await self._live(context, grant.purchase)
        now = datetime.now(UTC)
        if now >= original.expires_at:
            raise ExecutionGrantError(Denial.APPROVAL_EXPIRED)
        reserved = replace(
            original,
            revision=original.revision + 1,
            grant=grant.model_copy(
                update={
                    "status": "reserved",
                    "fence": grant.fence + 1,
                    "owner_token": secrets.token_hex(32),
                    "dispatch_claimed": False,
                    "lease_expires_at": min(
                        original.expires_at, now + timedelta(seconds=self.lease_seconds)
                    ),
                }
            ),
        )
        changed = await self.ledger.enable(
            context=context,
            metadata=original.metadata,
            transition="reserved",
            operation=lambda: self.state.replace_existing(
                "execution_grant",
                original=original,
                updated=reserved,
                not_after=reserved.grant.lease_expires_at,
            ),
        )
        if not changed:
            raise ExecutionGrantError(self._denial(await self._read(approval, context)))
        return RedisGrantReservation(self, context, reserved)

    async def callbacks_for_binding(self, *, context, approval_request_id, binding):
        """Recover only the exact gate-owned token; never adopt the latest owner."""
        return await self._bounded(
            self._callbacks(context, approval_request_id, binding)
        )

    async def _callbacks(self, context, approval, binding):
        if (
            type(binding) is not ExecutionGrantBinding
            or binding.reservation_token is None
        ):
            raise ExecutionGrantError(Denial.GRANT_INVALID)
        record = await self._read(approval, context)
        if record.grant.binding(
            record.expires_at
        ) != binding or record.grant.status not in {"reserved", "held", "consumed"}:
            raise ExecutionGrantError(Denial.GRANT_UNAVAILABLE)
        return RedisGrantCallbacks(RedisGrantReservation(self, context, record))

    async def invoke_bound(
        self, *, context, approval_request_id, binding, target, arguments, coordinator
    ):
        """Dormant handler bridge. Only verified acceptance returns to the gate.

        The caller owns provider-safe result projection. This helper neither
        registers a handler nor changes current public job_id/job_ref schemas.
        """
        callbacks = await self.callbacks_for_binding(
            context=context,
            approval_request_id=approval_request_id,
            binding=binding,
        )
        expected = callbacks.reservation.identity
        previous = None
        if expected.attempt_generation:
            previous = await self._bounded(
                self.lifecycle.get(
                    expected.relay_invocation_id,
                    account_id=context.account_id,
                    provider_connection_id=context.provider_connection_id,
                )
            )
        if previous is not None and previous.identity != expected:
            # This explicit execute request already holds the next approved
            # generation. Ordinary invoke remains replay/recovery-only.
            if previous.next_attempt().identity != expected:
                raise ExecutionGrantError(Denial.RECONCILIATION_PENDING)
            result = await coordinator.reattempt(
                target=target,
                rejected_record=previous,
                arguments=arguments,
                grant_callbacks=callbacks,
            )
        else:
            result = await coordinator.invoke(
                target=target,
                identity=expected,
                arguments=arguments,
                grant_callbacks=callbacks,
            )
        record = await self._bounded(
            self.lifecycle.get(
                callbacks.reservation.identity.relay_invocation_id,
                account_id=context.account_id,
                provider_connection_id=context.provider_connection_id,
            )
        )
        if record.identity != callbacks.reservation.identity or record.evidence is None:
            raise ExecutionGrantError(Denial.RECONCILIATION_PENDING)
        if record.evidence.outcome == "not_accepted":
            raise PreAcceptFailure()
        if (
            record.evidence.outcome != "accepted"
            or result.get("job_ref") != record.job_ref
        ):
            raise ExecutionGrantError(Denial.RECONCILIATION_PENDING)
        return build_processing_envelope(
            record.job_ref, coordinator.timeouts.poll_after_ms
        )

    async def recovery_callbacks(self, *, context, job_ref):
        """Read-only recovery capability; it can never authorize a dispatch."""
        return await self._bounded(self._recovery(context, job_ref))

    async def _recovery(self, context, job_ref):
        record = await self.job_refs.resolve(
            job_ref,
            account_id=context.account_id,
            provider_connection_id=context.provider_connection_id,
        )
        metadata = await self.ledger.recovery_metadata(record.identity, context=context)
        reservation = None
        try:
            current = await self._read(record.identity.approval_request_id, context)
        except Exception:
            pass  # Missing authorization permits audit-only accepted recovery.
        else:
            candidate = RedisGrantReservation(self, context, current)
            if candidate.identity == record.identity and current.grant.status in {
                "reserved",
                "held",
                "consumed",
            }:
                reservation = candidate
        return RedisRecoveryCallbacks(
            self, context, record.identity, metadata, reservation
        )

    async def revoke(self, *, context, approval_request_id):
        return await self._bounded(self._revoke(context, approval_request_id))

    async def _revoke(self, context, approval):
        original = await self._read(approval, context)
        if original.grant.status in {"revoked", "consumed"}:
            return
        await self.ledger.record(original.metadata, "revoked", context=context)
        updated = replace(
            original,
            revision=original.revision + 1,
            grant=original.grant.model_copy(update={"status": "revoked"}),
        )
        if not await self.state.replace_existing(
            "execution_grant", original=original, updated=updated
        ):
            raise ExecutionGrantError(Denial.GRANT_UNAVAILABLE)


class RedisGrantReservation:
    """Immutable capability for one owner; callbacks never look up a newer owner."""

    def __init__(self, authority, context, original):
        self.authority = authority
        self.context = context
        self.original = original
        self.binding = original.grant.binding(original.expires_at)

    @property
    def identity(self):
        grant = self.original.grant
        return InvocationIdentity(
            account_id=self.binding.account_id,
            provider_connection_id=self.binding.provider_connection_id,
            execution_target_id=self.binding.execution_target_id,
            approval_request_id=self.original.metadata.approval_request_id,
            tool_name=grant.purchase.tool_name,
            arguments_hash=grant.purchase.arguments_hash,
            idempotency_key=self.binding.idempotency_key,
            authorization_expires_at=self.binding.expires_at,
            attempt_generation=grant.attempt_generation,
            purchase_scope_hash="sha256:" + self.original.metadata.purchase_scope_hash,
            preview_hash="sha256:" + self.original.metadata.preview_hash,
            execution_target_fingerprint_hash="sha256:"
            + grant.purchase.execution_target_fingerprint_hash,
        )

    def callbacks(self):
        return RedisGrantCallbacks(self)

    async def _current(self):
        current = await self.authority._read(
            self.original.metadata.approval_request_id, self.context
        )
        if (
            current.grant.owner_token != self.original.grant.owner_token
            or current.grant.fence != self.original.grant.fence
            or current.grant.attempt_generation
            != self.original.grant.attempt_generation
            or current.grant.purchase != self.original.grant.purchase
            or current.grant.idempotency_key != self.original.grant.idempotency_key
        ):
            raise ExecutionGrantError(Denial.GRANT_UNAVAILABLE)
        return current

    async def release(self):
        await self.authority._bounded(self._ordinary_settle("approved", "released"))

    async def hold_for_reconciliation(self):
        await self.authority._bounded(
            self._ordinary_settle("held", "reconciliation_pending")
        )

    async def _ordinary_settle(self, status, transition):
        # A stale callback is a no-op, not permission to use current ownership.
        try:
            original = await self._current()
        except Exception:
            return
        if original.grant.status != "reserved":
            return
        now = datetime.now(UTC)
        if status == "approved" and (
            original.grant.dispatch_claimed or now >= original.grant.lease_expires_at
        ):
            return
        updates = {"status": status}
        if status == "approved":
            updates.update(owner_token=None, lease_expires_at=None)
        updated = replace(
            original,
            revision=original.revision + 1,
            grant=original.grant.model_copy(update=updates),
        )

        def operation():
            return self.authority.state.replace_existing(
                "execution_grant",
                original=original,
                updated=updated,
                not_after=original.grant.lease_expires_at
                if status == "approved"
                else None,
            )

        if status == "approved":
            await self.authority.ledger.enable(
                context=self.context,
                metadata=original.metadata,
                transition=transition,
                operation=operation,
            )
        else:
            await self.authority.ledger.record(original.metadata, transition)
            await operation()

    async def consume(self):
        await self.authority._bounded(self._consume())

    async def _consume(self):
        record = await self.authority.lifecycle.get(
            self.identity.relay_invocation_id,
            account_id=self.context.account_id,
            provider_connection_id=self.context.provider_connection_id,
        )
        await self._evidence_settle(record, accepted=True, ordinary=True)

    async def _evidence_settle(self, record, *, accepted, ordinary=False):
        if (
            record.identity != self.identity
            or record.evidence is None
            or record.evidence.outcome != ("accepted" if accepted else "not_accepted")
        ):
            raise ExecutionGrantError(Denial.RECONCILIATION_PENDING)
        persisted = await self.authority.lifecycle.get(
            record.relay_invocation_id,
            account_id=self.context.account_id,
            provider_connection_id=self.context.provider_connection_id,
        )
        if persisted != record:
            raise ExecutionGrantError(Denial.RECONCILIATION_PENDING)
        if not accepted:
            released = await self.authority._read(
                self.original.metadata.approval_request_id, self.context
            )
            if (
                released.grant.status == "approved"
                and released.grant.fence == self.original.grant.fence
                and released.grant.attempt_generation
                == self.original.grant.attempt_generation + 1
                and released.grant.purchase == self.original.grant.purchase
                and released.grant.idempotency_key
                == self.original.grant.idempotency_key
                and released.expires_at == self.original.expires_at
            ):
                return  # Same proof-backed release already committed; no new lease.
        original = await self._current()
        if accepted and original.grant.status == "consumed":
            return
        if original.grant.status not in {"reserved", "held"}:
            raise ExecutionGrantError(Denial.RECONCILIATION_PENDING)
        settlement_deadline = (
            original.grant.lease_expires_at if ordinary else original.expires_at
        )
        if datetime.now(UTC) >= settlement_deadline:
            raise ExecutionGrantError(Denial.RECONCILIATION_PENDING)
        updates = {"status": "consumed" if accepted else "approved"}
        if not accepted:
            updates.update(
                owner_token=None,
                lease_expires_at=None,
                attempt_generation=original.grant.attempt_generation + 1,
                dispatch_claimed=False,
            )
        updated = replace(
            original,
            revision=original.revision + 1,
            grant=original.grant.model_copy(update=updates),
        )

        def operation():
            return self.authority.state.replace_existing(
                "execution_grant",
                original=original,
                updated=updated,
                not_after=settlement_deadline,
            )

        if accepted:
            await self.authority.ledger.record(original.metadata, "consumed")
            changed = await operation()
        else:
            changed = await self.authority.ledger.enable(
                context=self.context,
                metadata=original.metadata,
                transition="released",
                operation=operation,
            )
        if not changed:
            raise ExecutionGrantError(Denial.RECONCILIATION_PENDING)


class RedisGrantCallbacks:
    """Plan 2 adapter retaining the same exact gate reservation, never re-reserving."""

    def __init__(self, reservation):
        self.reservation = reservation

    async def reserve(self, record):
        async def check():
            reservation = self.reservation
            if record.identity != reservation.identity:
                raise ExecutionGrantError(Denial.GRANT_INVALID)
            async with reservation.authority.ledger.active_owner(reservation.context):
                current = await reservation._current()
                if (
                    current.grant.status != "reserved"
                    or datetime.now(UTC) >= current.grant.lease_expires_at
                ):
                    raise ExecutionGrantError(Denial.RECONCILIATION_PENDING)
                if not current.grant.dispatch_claimed:
                    claimed = replace(
                        current,
                        revision=current.revision + 1,
                        grant=current.grant.model_copy(
                            update={"dispatch_claimed": True}
                        ),
                    )
                    if not await reservation.authority.state.replace_existing(
                        "execution_grant",
                        original=current,
                        updated=claimed,
                        not_after=current.grant.lease_expires_at,
                    ):
                        raise ExecutionGrantError(Denial.RECONCILIATION_PENDING)

        await self.reservation.authority._bounded(check())

    async def consume_on_accept(self, record):
        await self.reservation.authority._bounded(
            self.reservation._evidence_settle(record, accepted=True)
        )

    async def release(self, record):
        await self.reservation.authority._bounded(
            self.reservation._evidence_settle(record, accepted=False)
        )

    async def hold_for_reconciliation(self, record):
        if record.identity != self.reservation.identity:
            raise ExecutionGrantError(Denial.GRANT_INVALID)
        if record.evidence is not None and record.evidence.outcome == "accepted":
            if datetime.now(UTC) >= self.reservation.binding.expires_at:
                recovery = await self.reservation.authority.recovery_callbacks(
                    context=self.reservation.context,
                    job_ref=record.job_ref,
                )
                await recovery.consume_on_accept(record)
                return
        await self.reservation.hold_for_reconciliation()


class RedisRecoveryCallbacks:
    """A pinned original lifecycle identity; SQL evidence can never enable use."""

    def __init__(self, authority, context, identity, metadata, reservation):
        self.authority = authority
        self.context = context
        self.identity = identity
        self.metadata = metadata
        self.reservation = reservation

    async def reserve(self, record):
        raise ExecutionGrantError(Denial.RECONCILIATION_PENDING)

    async def _validate(self, record):
        if record.identity != self.identity:
            raise ExecutionGrantError(Denial.RECONCILIATION_PENDING)
        current = await self.authority.lifecycle.get(
            record.relay_invocation_id,
            account_id=self.context.account_id,
            provider_connection_id=self.context.provider_connection_id,
        )
        if current != record:
            raise ExecutionGrantError(Denial.RECONCILIATION_PENDING)

    async def consume_on_accept(self, record):
        async def settle():
            await self._validate(record)
            if record.evidence is None or record.evidence.outcome != "accepted":
                raise ExecutionGrantError(Denial.RECONCILIATION_PENDING)
            # Original durable truth is recorded even after Redis grant expiry.
            # This metadata has no purchase key or executable credential.
            await self.authority.ledger.record(self.metadata, "consumed")
            if (
                self.reservation is not None
                and datetime.now(UTC) < self.identity.authorization_expires_at
            ):
                await self.reservation._evidence_settle(record, accepted=True)

        await self.authority._bounded(settle())

    async def release(self, record):
        async def settle():
            await self._validate(record)
            if self.reservation is None:
                raise ExecutionGrantError(Denial.RECONCILIATION_PENDING)
            await self.reservation._evidence_settle(record, accepted=False)

        await self.authority._bounded(settle())

    async def hold_for_reconciliation(self, record):
        if record.evidence is not None and record.evidence.outcome == "accepted":
            await self.consume_on_accept(record)
            return
        await self.authority._bounded(self._validate(record))
        if self.reservation is not None:
            await self.reservation.hold_for_reconciliation()
