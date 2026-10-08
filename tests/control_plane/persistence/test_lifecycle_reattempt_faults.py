"""Fail-closed retry boundaries with real Redis writes and synthetic callbacks.

Real-authority ownership, revocation and ledger behavior are independently tested
by test_grant_recovery; callbacks here isolate lifecycle interruption boundaries.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from src.control_plane.redis_keys import RedisKey
from src.control_plane.relay.lifecycle import InvocationLifecycleCoordinator
from src.control_plane.relay.lifecycle_store import (
    InvocationLifecycleStore,
    InvocationState,
    JobReferenceStore,
    LifecycleUnavailable,
)
from src.control_plane.relay.protocol import TargetAcceptanceEvidence
from tests.control_plane.persistence.test_invocation_lifecycle import (
    DurableTarget,
    GrantRecorder,
    bound_identity,
    coordinator,
)
from tests.control_plane.persistence.test_lifecycle_reattempt import rejected_record


async def get_record(redis, identity):
    return await InvocationLifecycleStore(redis).get(
        identity.relay_invocation_id,
        account_id=identity.account_id,
        provider_connection_id=identity.provider_connection_id,
    )


async def test_acceptance_cannot_cross_original_dispatch_deadline(real_redis):
    store = InvocationLifecycleStore(real_redis)
    record, _ = await store.create(
        bound_identity(), dispatch_deadline_at=datetime.now(UTC) + timedelta(seconds=1)
    )
    sent = await store.transition(record, InvocationState.SENT_TO_TARGET)
    proof = TargetAcceptanceEvidence(
        identity=sent.identity,
        outcome="accepted",
        local_job_id="too-late-job",
        proof_id="sha256:" + "c" * 64,
        accepted_at=sent.dispatch_deadline_at,
    )
    with pytest.raises(LifecycleUnavailable):
        await store.record_evidence(sent, proof)
    assert await get_record(real_redis, sent.identity) == sent


async def test_racing_retry_cas_has_one_winner_and_old_evidence_stays_stale(real_redis):
    store, rejected = await rejected_record(real_redis)
    results = await asyncio.gather(
        *(store.begin_reattempt(rejected) for _ in range(12))
    )
    assert sum(result is not None for result in results) == 1
    winner = next(result for result in results if result is not None)
    assert await store.record_evidence(rejected, rejected.evidence) is None
    with pytest.raises(LifecycleUnavailable):
        await store.record_evidence(winner, rejected.evidence)
    assert await get_record(real_redis, rejected.identity) == winner


@pytest.mark.parametrize(
    "stage", ["queued", "sent", "unknown", "abandoned", "accepted"]
)
async def test_only_positive_fenced_rejection_is_reattemptable(real_redis, stage):
    store = InvocationLifecycleStore(real_redis)
    record, _ = await store.create(bound_identity())
    if stage == "abandoned":
        record = await store.transition(record, InvocationState.ABANDONED)
    elif stage != "queued":
        record = await store.transition(record, InvocationState.SENT_TO_TARGET)
        if stage == "unknown":
            record = await store.transition(record, InvocationState.DEADLINE_EXCEEDED)
        elif stage == "accepted":
            record = await store.record_evidence(
                record,
                TargetAcceptanceEvidence(
                    identity=record.identity,
                    outcome="accepted",
                    local_job_id="original-job",
                    proof_id="sha256:" + "a" * 64,
                    accepted_at=datetime.now(UTC),
                ),
            )
    with pytest.raises(LifecycleUnavailable):
        await store.begin_reattempt(record)
    assert await get_record(real_redis, record.identity) == record


@pytest.mark.parametrize("missing", ["invocation", "pointer", "both"])
async def test_missing_pair_cannot_be_reset_or_created_as_new_attempt(
    real_redis, missing
):
    store, rejected = await rejected_record(real_redis)
    keys = {
        "invocation": RedisKey.invocation(rejected.relay_invocation_id),
        "pointer": RedisKey.job_reference(rejected.job_ref),
    }
    await real_redis.delete(*(keys.values() if missing == "both" else [keys[missing]]))
    remaining = await real_redis.dbsize()
    assert await store.begin_reattempt(rejected) is None
    with pytest.raises(LifecycleUnavailable):
        await store.create(rejected.next_attempt().identity)
    assert await real_redis.dbsize() == remaining


@pytest.mark.parametrize("cutoff", ["authorization", "dispatch"])
async def test_expired_original_deadline_cannot_advance_attempt(real_redis, cutoff):
    end = datetime.now(UTC) + timedelta(milliseconds=100)
    bound = bound_identity(
        **({"authorization_expires_at": end} if cutoff == "authorization" else {})
    )
    store = InvocationLifecycleStore(real_redis)
    record, _ = await store.create(bound, dispatch_deadline_at=end)
    sent = await store.transition(record, InvocationState.SENT_TO_TARGET)
    rejected = await store.record_evidence(
        sent,
        TargetAcceptanceEvidence(
            identity=bound,
            outcome="not_accepted",
            proof_id="sha256:" + "d" * 64,
            rejection_fenced=True,
        ),
    )
    expiry = await real_redis.pexpiretime(
        RedisKey.invocation(bound.relay_invocation_id)
    )
    await asyncio.sleep(0.15)
    assert await store.begin_reattempt(rejected) is None
    assert await get_record(real_redis, bound) == rejected
    assert (
        await real_redis.pexpiretime(RedisKey.invocation(bound.relay_invocation_id))
        == expiry
    )


@pytest.mark.parametrize("deny_at", [1, 2])
async def test_current_owner_is_required_before_reset_and_again_before_send(
    real_redis, deny_at
):
    _, rejected = await rejected_record(real_redis)

    class DeniedOwner(GrantRecorder):
        async def reserve(self, record):
            await super().reserve(record)
            if sum(name == "reserve" for name, _ in self.calls) == deny_at:
                raise RuntimeError("revoked_or_held_owner")

    grants = DeniedOwner()
    target = DurableTarget(rejected.identity, grants)
    result = await coordinator(real_redis).reattempt(
        target=target, rejected_record=rejected, arguments={}, grant_callbacks=grants
    )
    assert result["status"] == "processing_unknown"
    assert target.dispatches == []
    current = await get_record(real_redis, rejected.identity)
    if deny_at == 1:
        assert current == rejected
    else:
        assert current.identity.attempt_generation == 1
        assert current.state == InvocationState.TARGET_DISCONNECTED_MID_CALL
    assert grants.calls[-1][0] == "hold"
    assert grants.calls[-1][1].identity.attempt_generation == 1


async def test_lost_retry_cas_reply_does_not_send_or_implicitly_restart(real_redis):
    _, rejected = await rejected_record(real_redis)

    class LostReply(InvocationLifecycleStore):
        async def begin_reattempt(self, original):
            await super().begin_reattempt(original)
            raise ConnectionError("lost_after_real_write")

    grants = GrantRecorder()
    target = DurableTarget(rejected.identity, grants)
    lifecycle = InvocationLifecycleCoordinator(
        invocation_store=LostReply(real_redis),
        job_reference_store=JobReferenceStore(real_redis),
    )
    result = await lifecycle.reattempt(
        target=target, rejected_record=rejected, arguments={}, grant_callbacks=grants
    )
    current = await get_record(real_redis, rejected.identity)
    assert current.identity.attempt_generation == 1
    assert current.state == InvocationState.ABANDONED
    assert target.dispatches == []
    assert result["status"] == "processing_unknown"
    replay = await lifecycle.invoke(
        target=target, identity=current.identity, arguments={}, grant_callbacks=grants
    )
    assert replay["job_ref"] == rejected.job_ref
    assert replay["status"] == "processing_unknown"
    assert target.dispatches == []
    assert (
        await lifecycle.reattempt(
            target=target,
            rejected_record=rejected,
            arguments={},
            grant_callbacks=grants,
        )
    )["status"] == "unavailable"


async def test_cancellation_after_real_retry_cas_never_dispatches(real_redis):
    _, rejected = await rejected_record(real_redis)
    committed = asyncio.Event()

    class PausedReply(InvocationLifecycleStore):
        async def begin_reattempt(self, original):
            await super().begin_reattempt(original)
            committed.set()
            await asyncio.Event().wait()

    grants = GrantRecorder()
    target = DurableTarget(rejected.identity, grants)
    lifecycle = InvocationLifecycleCoordinator(
        invocation_store=PausedReply(real_redis),
        job_reference_store=JobReferenceStore(real_redis),
    )
    task = asyncio.create_task(
        lifecycle.reattempt(
            target=target,
            rejected_record=rejected,
            arguments={},
            grant_callbacks=grants,
        )
    )
    await asyncio.wait_for(committed.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    current = await get_record(real_redis, rejected.identity)
    assert current.identity.attempt_generation == 1
    assert current.state == InvocationState.ABANDONED
    assert target.dispatches == []
    assert grants.calls[-1][0] == "hold"


async def test_deadline_crossed_during_retry_reset_cannot_reach_target(real_redis):
    store = InvocationLifecycleStore(real_redis)
    record, _ = await store.create(
        bound_identity(),
        dispatch_deadline_at=datetime.now(UTC) + timedelta(milliseconds=100),
    )
    sent = await store.transition(record, InvocationState.SENT_TO_TARGET)
    rejected = await store.record_evidence(
        sent,
        TargetAcceptanceEvidence(
            identity=record.identity,
            outcome="not_accepted",
            rejection_fenced=True,
            proof_id="sha256:" + "d" * 64,
        ),
    )

    class SlowTransition(InvocationLifecycleStore):
        async def transition(self, original, state):
            result = await super().transition(original, state)
            if state == InvocationState.SENT_TO_TARGET:
                await asyncio.sleep(0.15)
            return result

    grants = GrantRecorder()
    target = DurableTarget(rejected.identity, grants)
    lifecycle = InvocationLifecycleCoordinator(
        invocation_store=SlowTransition(real_redis),
        job_reference_store=JobReferenceStore(real_redis),
    )
    result = await lifecycle.reattempt(
        target=target, rejected_record=rejected, arguments={}, grant_callbacks=grants
    )
    assert target.dispatches == []
    assert result["status"] == "processing_unknown"
