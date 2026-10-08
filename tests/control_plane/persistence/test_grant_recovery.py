"""One authority owner shared with the existing durable lifecycle, on real stores."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from src.control_plane.execution_grants import ExecutionGrantError
from src.control_plane.redis_keys import RedisKey
from src.control_plane.relay.protocol import TargetAcceptanceEvidence
from tests.control_plane.persistence.test_grant_authority import (
    reserve,
    setup_authority,
)
from tests.control_plane.persistence.test_invocation_lifecycle import coordinator


class SyntheticTarget:
    def __init__(self, identity, *, lost_reply=False, reject=False):
        self.execution_target_id = identity.execution_target_id
        self.lost_reply = lost_reply
        self.reject = reject
        self.proofs = {}
        self.effects = []

    async def dispatch_invocation(self, *, identity, arguments, deadline_at):
        if identity.attempt_generation in self.proofs:
            return
        if self.reject:
            self.proofs[identity.attempt_generation] = TargetAcceptanceEvidence(
                identity=identity,
                outcome="not_accepted",
                rejection_fenced=True,
                proof_id="sha256:" + "d" * 64,
            )
        else:
            assert not self.effects
            self.effects.append(identity.idempotency_key)
            self.proofs[identity.attempt_generation] = TargetAcceptanceEvidence(
                identity=identity,
                outcome="accepted",
                local_job_id="synthetic_original",
                proof_id="sha256:" + "e" * 64,
                accepted_at=datetime.now(UTC),
            )
        if self.lost_reply:
            raise ConnectionError("SYNTHETIC_LOST_REPLY")

    async def get_acceptance(self, identity):
        return self.proofs.get(identity.attempt_generation) or TargetAcceptanceEvidence(
            identity=identity, outcome="unknown"
        )


async def invoke(redis, reservation, target):
    return await coordinator(redis).invoke(
        target=target,
        identity=reservation.identity,
        arguments={},
        grant_callbacks=reservation.callbacks(),
    )


async def test_real_callbacks_consume_only_persisted_acceptance_and_replay_original_job(
    real_redis, postgres_db
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    reservation = await reserve(authority, context, preview, approval)
    target = SyntheticTarget(reservation.identity)
    result = await invoke(real_redis, reservation, target)
    assert result["status"] == "processing"
    record = await authority.state.read(
        "execution_grant", approval, account_id=context.account_id
    )
    assert record.grant.status == "consumed"
    with pytest.raises(ExecutionGrantError) as error:
        await reserve(authority, context, preview, approval)
    assert error.value.denial == "grant_consumed"
    replay = await invoke(real_redis, reservation, target)
    assert replay == result
    assert len(target.effects) == 1


async def test_accepted_recovery_after_lease_and_original_expiry_is_audit_only(
    real_redis, postgres_db
):
    from src.control_plane.audit.models import ControlPlaneAuthorizationLedgerEvent

    authority, context, preview, approval = await setup_authority(
        real_redis,
        postgres_db,
        authorization_seconds=0.15,
        lease_seconds=0.05,
    )
    reservation = await reserve(authority, context, preview, approval)
    target = SyntheticTarget(reservation.identity, lost_reply=True)
    first = await invoke(real_redis, reservation, target)
    assert first["status"] == "processing_unknown"
    await asyncio.sleep(0.16)
    callbacks = await authority.recovery_callbacks(
        context=context, job_ref=first["job_ref"]
    )
    recovered = await coordinator(real_redis).reconcile(
        target=target,
        job_ref=first["job_ref"],
        account_id=context.account_id,
        provider_connection_id=context.provider_connection_id,
        grant_callbacks=callbacks,
    )
    assert recovered["status"] == "processing"
    assert recovered["job_ref"] == first["job_ref"]
    assert len(target.effects) == 1
    assert not await real_redis.exists(RedisKey.execution_grant(approval))
    rows = (
        await postgres_db.scalars(select(ControlPlaneAuthorizationLedgerEvent))
    ).all()
    assert any(row.grant_transition == "consumed" for row in rows)
    with pytest.raises(ExecutionGrantError):
        await reserve(authority, context, preview, approval)
    with pytest.raises(ExecutionGrantError):
        await callbacks.reserve(
            await authority.lifecycle.get(
                reservation.identity.relay_invocation_id,
                account_id=context.account_id,
                provider_connection_id=context.provider_connection_id,
            )
        )


async def test_positive_proof_releases_held_owner_after_lease_without_renewing_authorization(
    real_redis, postgres_db
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db, lease_seconds=0.04
    )
    first = await reserve(authority, context, preview, approval)
    target = SyntheticTarget(first.identity, lost_reply=True, reject=True)
    result = await invoke(real_redis, first, target)
    await asyncio.sleep(0.05)
    recovered = await coordinator(real_redis).reconcile(
        target=target,
        job_ref=result["job_ref"],
        account_id=context.account_id,
        provider_connection_id=context.provider_connection_id,
        grant_callbacks=first.callbacks(),
    )
    assert recovered["reason"] == "target_offline"
    second = await reserve(authority, context, preview, approval)
    assert second.identity.attempt_generation == first.identity.attempt_generation + 1
    assert second.binding.expires_at == first.binding.expires_at
    assert second.binding.idempotency_key == first.binding.idempotency_key
    # Old callbacks cannot release or hold this newly reserved attempt.
    await first.release()
    await first.hold_for_reconciliation()
    current = await authority.state.read(
        "execution_grant", approval, account_id=context.account_id
    )
    assert current.grant.owner_token == second.binding.reservation_token
    assert current.grant.status == "reserved"


async def test_gate_passes_original_owner_to_lifecycle_and_hides_private_token(
    real_redis, postgres_db
):
    from dataclasses import replace

    from src.control_plane.auth.context import (
        clear_authorization_context,
        set_authorization_context,
    )
    from src.registry.catalog import public_tools
    from tests.hosted.test_execution_grant_gate import bound_execute

    authority, context, preview, unused = await setup_authority(real_redis, postgres_db)
    # This is a disposable explicitly injected gate; shipped exports stay off.
    preview.value = preview.value.model_copy(
        update={"policy": "provider_and_shipagent"}
    )
    approval = await authority.issue_approved(
        context=context,
        purchase=preview.value,
        approving_subject_hash=__import__("hashlib")
        .sha256(context.subject.encode())
        .hexdigest(),
    )
    context = replace(
        context,
        scopes=frozenset(
            scope for tool in public_tools() for scope in tool.auth_scopes
        ),
    )
    owners = []
    targets = []

    async def handler(ctx, arguments, binding):
        owners.append(binding.reservation_token)
        callbacks = await authority.callbacks_for_binding(
            context=ctx,
            approval_request_id=approval,
            binding=binding,
        )
        target = SyntheticTarget(callbacks.reservation.identity)
        targets.append(target)
        result = await authority.invoke_bound(
            context=ctx,
            approval_request_id=approval,
            binding=binding,
            target=target,
            arguments={},
            coordinator=coordinator(real_redis),
        )
        # Test-only projection into the currently registered legacy result shape.
        return {"job_id": result["job_ref"], "status": "running"}

    tool = await bound_execute(handler, authority)
    token = set_authorization_context(context)
    try:
        result = await tool.run(
            {"preview_id": preview.value.preview_id, "approval_request_id": approval}
        )
    finally:
        clear_authorization_context(token)
    assert len(owners) == 1 and len(targets[0].effects) == 1
    assert owners[0] not in str(result)
    current = await authority.state.read(
        "execution_grant", approval, account_id=context.account_id
    )
    assert current.grant.status == "consumed"
    assert current.grant.fence == 1  # Gate and lifecycle did not reserve twice.


async def test_ordinary_release_cannot_reopen_owner_after_lifecycle_dispatch_claim(
    real_redis, postgres_db
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    reservation = await reserve(authority, context, preview, approval)
    record, created = await authority.lifecycle.create(reservation.identity)
    assert created
    await reservation.callbacks().reserve(record)
    await reservation.release()
    with pytest.raises(ExecutionGrantError) as error:
        await reserve(authority, context, preview, approval)
    assert error.value.denial == "grant_in_use"


async def test_repeated_accepted_recovery_records_one_consumed_ledger_event(
    real_redis, postgres_db
):
    from src.control_plane.audit.models import ControlPlaneAuthorizationLedgerEvent

    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    reservation = await reserve(authority, context, preview, approval)
    target = SyntheticTarget(reservation.identity, lost_reply=True)
    first = await invoke(real_redis, reservation, target)
    for _ in range(2):
        callbacks = await authority.recovery_callbacks(
            context=context, job_ref=first["job_ref"]
        )
        result = await coordinator(real_redis).reconcile(
            target=target,
            job_ref=first["job_ref"],
            account_id=context.account_id,
            provider_connection_id=context.provider_connection_id,
            grant_callbacks=callbacks,
        )
        assert result["status"] == "processing"
    consumed = (
        await postgres_db.scalars(
            select(ControlPlaneAuthorizationLedgerEvent).where(
                ControlPlaneAuthorizationLedgerEvent.approval_request_id == approval,
                ControlPlaneAuthorizationLedgerEvent.grant_transition == "consumed",
            )
        )
    ).all()
    assert len(consumed) == 1


async def test_held_rejection_settlement_is_idempotent_without_touching_new_owner(
    real_redis, postgres_db
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    first = await reserve(authority, context, preview, approval)
    target = SyntheticTarget(first.identity, reject=True)
    result = await invoke(real_redis, first, target)
    assert result["reason"] == "target_offline"
    rejected = await authority.lifecycle.get(
        first.identity.relay_invocation_id,
        account_id=context.account_id,
        provider_connection_id=context.provider_connection_id,
    )
    await first.callbacks().release(rejected)
    second = await reserve(authority, context, preview, approval)
    with pytest.raises(ExecutionGrantError):
        await first.callbacks().release(rejected)
    assert (
        await authority.state.read(
            "execution_grant", approval, account_id=context.account_id
        )
    ).grant.owner_token == second.binding.reservation_token


async def test_bound_bridge_explicit_retry_preserves_purchase_and_original_job(
    real_redis, postgres_db
):
    from src.control_plane.execution_grants import PreAcceptFailure

    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    first = await reserve(authority, context, preview, approval)
    target = SyntheticTarget(first.identity, reject=True)
    with pytest.raises(PreAcceptFailure):
        await authority.invoke_bound(
            context=context,
            approval_request_id=approval,
            binding=first.binding,
            target=target,
            arguments={},
            coordinator=coordinator(real_redis),
        )
    rejected = await authority.lifecycle.get(
        first.identity.relay_invocation_id,
        account_id=context.account_id,
        provider_connection_id=context.provider_connection_id,
    )
    second = await reserve(authority, context, preview, approval)
    target.reject = False
    result = await authority.invoke_bound(
        context=context,
        approval_request_id=approval,
        binding=second.binding,
        target=target,
        arguments={},
        coordinator=coordinator(real_redis),
    )
    assert result["job_ref"] == rejected.job_ref
    assert target.effects == [first.binding.idempotency_key]
    accepted = await authority.lifecycle.get(
        first.identity.relay_invocation_id,
        account_id=context.account_id,
        provider_connection_id=context.provider_connection_id,
    )
    assert accepted.identity.attempt_generation == 1
    assert accepted.dispatch_deadline_at == rejected.dispatch_deadline_at
    assert accepted.expires_at_ms == rejected.expires_at_ms


async def test_bound_bridge_unknown_result_never_returns_as_accepted(
    real_redis, postgres_db
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    reservation = await reserve(authority, context, preview, approval)
    target = SyntheticTarget(reservation.identity, lost_reply=True)
    with pytest.raises(ExecutionGrantError) as error:
        await authority.invoke_bound(
            context=context,
            approval_request_id=approval,
            binding=reservation.binding,
            target=target,
            arguments={},
            coordinator=coordinator(real_redis),
        )
    assert error.value.denial == "reconciliation_pending"
    assert len(target.effects) == 1
    current = await authority.state.read(
        "execution_grant", approval, account_id=context.account_id
    )
    assert current.grant.status == "held"
