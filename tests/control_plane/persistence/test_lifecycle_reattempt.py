"""Explicit attempt fencing against real Redis and target-owned durable proof."""

import pytest

from src.control_plane.redis_keys import RedisKey
from src.control_plane.relay.lifecycle_store import (
    InvocationLifecycleStore,
    InvocationState,
    JobReferenceStore,
)
from src.control_plane.relay.protocol import TargetAcceptanceEvidence
from tests.control_plane.persistence.test_invocation_lifecycle import bound_identity


async def rejected_record(redis, *, identity=None):
    store = InvocationLifecycleStore(redis)
    record, _ = await store.create(identity or bound_identity())
    sent = await store.transition(record, InvocationState.SENT_TO_TARGET)
    rejected = await store.record_evidence(
        sent,
        TargetAcceptanceEvidence(
            identity=sent.identity,
            outcome="not_accepted",
            proof_id="sha256:" + "d" * 64,
            rejection_fenced=True,
        ),
    )
    return store, rejected


async def test_reattempt_keeps_purchase_job_and_original_expiries(real_redis):
    store, rejected = await rejected_record(real_redis)
    original_expiries = [
        await real_redis.pexpiretime(key)
        for key in (
            RedisKey.invocation(rejected.relay_invocation_id),
            RedisKey.job_reference(rejected.job_ref),
        )
    ]

    next_attempt = await store.begin_reattempt(rejected)

    assert next_attempt.identity.attempt_generation == 1
    assert (
        next_attempt.identity.model_copy(update={"attempt_generation": 0})
        == rejected.identity
    )
    assert next_attempt.job_ref == rejected.job_ref
    assert next_attempt.relay_invocation_id == rejected.relay_invocation_id
    assert next_attempt.created_at_ms == rejected.created_at_ms
    assert next_attempt.expires_at_ms == rejected.expires_at_ms
    assert next_attempt.dispatch_deadline_at == rejected.dispatch_deadline_at
    assert next_attempt.state == InvocationState.QUEUED
    assert next_attempt.evidence is None
    assert next_attempt.revision == rejected.revision + 1
    assert (
        await JobReferenceStore(real_redis).resolve(
            rejected.job_ref,
            account_id=rejected.identity.account_id,
            provider_connection_id=rejected.identity.provider_connection_id,
        )
        == next_attempt
    )
    assert [
        await real_redis.pexpiretime(key)
        for key in (
            RedisKey.invocation(rejected.relay_invocation_id),
            RedisKey.job_reference(rejected.job_ref),
        )
    ] == original_expiries
    assert await real_redis.dbsize() == 2


async def test_explicit_reattempt_dispatches_next_generation_under_original_deadline(
    real_redis,
):
    from tests.control_plane.persistence.test_invocation_lifecycle import (
        DurableTarget,
        GrantRecorder,
        coordinator,
    )

    bound = bound_identity()
    grants = GrantRecorder()

    class RejectFirstAttempt(DurableTarget):
        async def dispatch_invocation(self, **kwargs):
            await super().dispatch_invocation(**kwargs)
            if kwargs["identity"].attempt_generation == 0:
                self.proof = TargetAcceptanceEvidence(
                    identity=kwargs["identity"],
                    outcome="not_accepted",
                    proof_id="sha256:" + "d" * 64,
                    rejection_fenced=True,
                )

    target = RejectFirstAttempt(bound, grants)
    lifecycle = coordinator(real_redis)
    initial = await lifecycle.invoke(
        target=target, identity=bound, arguments={}, grant_callbacks=grants
    )
    assert initial["reason"] == "target_offline"
    store = InvocationLifecycleStore(real_redis)
    rejected = await store.get(
        bound.relay_invocation_id,
        account_id=bound.account_id,
        provider_connection_id=bound.provider_connection_id,
    )
    result = await lifecycle.reattempt(
        target=target,
        rejected_record=rejected,
        arguments={},
        grant_callbacks=grants,
    )
    assert result["status"] == "processing"
    assert result["job_ref"] == rejected.job_ref
    assert [dispatch[0].attempt_generation for dispatch in target.dispatches] == [0, 1]
    assert (
        target.dispatches[0][2]
        == target.dispatches[1][2]
        == rejected.dispatch_deadline_at
    )
    assert target.dispatches[1][0].idempotency_key == bound.idempotency_key


def test_scope_hashes_are_joint_immutable_evidence():
    from pydantic import ValidationError

    fields = {
        "purchase_scope_hash": "sha256:" + "a" * 64,
        "preview_hash": "sha256:" + "b" * 64,
    }
    scoped = bound_identity(**fields)
    assert scoped.purchase_scope_hash == fields["purchase_scope_hash"]
    assert scoped.preview_hash == fields["preview_hash"]
    for field in fields:
        with pytest.raises(ValidationError):
            bound_identity(**{field: fields[field]})
    with pytest.raises(ValidationError):
        bound_identity(**{**fields, "preview_hash": "RAW_PRIVATE_CANARY"})


async def test_target_restart_preserves_old_attempt_fence_after_reattempt(
    real_redis, tmp_path
):
    import asyncio

    from tests.control_plane.persistence.lifecycle_process import ProtocolTarget
    from tests.control_plane.persistence.test_invocation_lifecycle import (
        GrantRecorder,
        coordinator,
    )
    from tests.control_plane.persistence.test_lifecycle_process_recovery import (
        effects,
        target_process,
    )

    bound = bound_identity()
    grants = GrantRecorder()
    lifecycle = coordinator(real_redis)
    async with target_process(tmp_path, bound) as (endpoint, journal):
        target = ProtocolTarget(
            port=endpoint["port"],
            session_id=endpoint["session_id"],
            execution_target_id=bound.execution_target_id,
        )
        original_proof = await target.fence(bound)
        await lifecycle.invoke(
            target=target, identity=bound, arguments={}, grant_callbacks=grants
        )
        rejected = await InvocationLifecycleStore(real_redis).get(
            bound.relay_invocation_id,
            account_id=bound.account_id,
            provider_connection_id=bound.provider_connection_id,
        )
        result = await lifecycle.reattempt(
            target=target,
            rejected_record=rejected,
            arguments={},
            grant_callbacks=grants,
        )
        assert result["status"] == "processing"
        assert result["job_ref"] == rejected.job_ref
        original_effects = effects(journal)
        assert len(original_effects) == 1
        assert original_effects[0][1] == bound.idempotency_key

    async with target_process(tmp_path, bound, session="relay_session_restarted") as (
        endpoint,
        journal,
    ):
        target = ProtocolTarget(
            port=endpoint["port"],
            session_id=endpoint["session_id"],
            execution_target_id=bound.execution_target_id,
        )
        deliver_delayed_send = asyncio.Event()

        async def delayed_old_send():
            await deliver_delayed_send.wait()
            await target.dispatch_invocation(
                identity=bound, arguments={}, deadline_at=rejected.dispatch_deadline_at
            )

        delayed = asyncio.create_task(delayed_old_send())
        recovered = await lifecycle.reconcile(
            target=target,
            job_ref=result["job_ref"],
            account_id=bound.account_id,
            provider_connection_id=bound.provider_connection_id,
            grant_callbacks=grants,
        )
        deliver_delayed_send.set()
        await delayed
        assert recovered == result
        assert await target.get_acceptance(bound) == original_proof
        assert effects(journal) == original_effects
        assert await real_redis.dbsize() == 2
