"""Coordinator behavior with real Redis and deterministic target evidence."""

from datetime import UTC, datetime

import pytest

from tests.control_plane.persistence.test_lifecycle_store import identity


class GrantRecorder:
    def __init__(self):
        self.calls = []

    async def reserve(self, record):
        self.calls.append(("reserve", record))

    async def consume_on_accept(self, record):
        self.calls.append(("consume", record))

    async def release(self, record):
        self.calls.append(("release", record))

    async def hold_for_reconciliation(self, record):
        self.calls.append(("hold", record))


class DurableTarget:
    def __init__(self, bound, grants):
        self.execution_target_id = bound.execution_target_id
        self.grants = grants
        self.dispatches = []
        self.queries = []
        self.proof = None

    async def dispatch_invocation(self, *, identity, arguments, deadline_at):
        from src.control_plane.relay.protocol import TargetAcceptanceEvidence

        assert self.grants.calls[0][0] == "reserve"
        self.dispatches.append((identity, arguments, deadline_at))
        self.proof = TargetAcceptanceEvidence(
            identity=identity,
            outcome="accepted",
            local_job_id="original-job",
            proof_id="sha256:" + "c" * 64,
            accepted_at=datetime.now(UTC),
        )

    async def get_acceptance(self, identity):
        from src.control_plane.relay.protocol import TargetAcceptanceEvidence

        self.queries.append(identity)
        return self.proof or TargetAcceptanceEvidence(
            identity=identity, outcome="unknown"
        )


def coordinator(redis, **kwargs):
    from src.control_plane.relay.lifecycle import InvocationLifecycleCoordinator
    from src.control_plane.relay.lifecycle_store import (
        InvocationLifecycleStore,
        JobReferenceStore,
    )

    return InvocationLifecycleCoordinator(
        invocation_store=InvocationLifecycleStore(redis),
        job_reference_store=JobReferenceStore(redis),
        **kwargs,
    )


def bound_identity(arguments=None, **updates):
    from src.control_plane.relay.protocol import relay_invocation_input_hash

    return identity(
        arguments_hash=relay_invocation_input_hash(
            "execute_shipments", arguments or {}
        ),
        **updates,
    )


async def test_reserve_before_dispatch_and_consume_only_target_owned_acceptance(
    real_redis,
):
    from src.control_plane.relay.lifecycle_store import (
        InvocationState,
        JobReferenceStore,
    )

    bound = bound_identity()
    grants = GrantRecorder()
    target = DurableTarget(bound, grants)
    result = await coordinator(real_redis).invoke(
        target=target, identity=bound, arguments={}, grant_callbacks=grants
    )
    assert result == {
        "status": "processing",
        "job_ref": result["job_ref"],
        "poll_after_ms": 2000,
    }
    assert [name for name, _ in grants.calls] == ["reserve", "consume"]
    assert len(target.dispatches) == 1
    assert target.dispatches[0][2] <= bound.authorization_expires_at
    record = await JobReferenceStore(real_redis).resolve(
        result["job_ref"],
        account_id=bound.account_id,
        provider_connection_id=bound.provider_connection_id,
    )
    assert record.state == InvocationState.ACCEPTED
    assert record.local_job_id == "original-job"
    # Replay returns the original reference, with no second purchase or key.
    replay = await coordinator(real_redis).invoke(
        target=target, identity=bound, arguments={}, grant_callbacks=grants
    )
    assert replay == result
    assert len(target.dispatches) == 1


async def test_lost_send_response_stays_unknown_until_exact_target_recovers_original_job(
    real_redis,
):
    from src.control_plane.relay.lifecycle_store import (
        InvocationState,
        JobReferenceStore,
    )

    bound = bound_identity()
    grants = GrantRecorder()

    class LostReplyTarget(DurableTarget):
        async def dispatch_invocation(self, **kwargs):
            await super().dispatch_invocation(**kwargs)
            raise ConnectionError("PRIVATE_TARGET_CANARY")

    target = LostReplyTarget(bound, grants)
    first = await coordinator(real_redis).invoke(
        target=target, identity=bound, arguments={}, grant_callbacks=grants
    )
    assert first["status"] == "processing_unknown"
    assert first["terminal"] is False
    assert "PRIVATE_TARGET_CANARY" not in str(first)
    assert [name for name, _ in grants.calls] == ["reserve", "hold"]
    recovered = await coordinator(real_redis).reconcile(
        target=target,
        job_ref=first["job_ref"],
        account_id=bound.account_id,
        provider_connection_id=bound.provider_connection_id,
        grant_callbacks=grants,
    )
    assert recovered == {
        "status": "processing",
        "job_ref": first["job_ref"],
        "poll_after_ms": 2000,
    }
    assert [name for name, _ in grants.calls] == ["reserve", "hold", "consume"]
    assert target.queries == [bound]
    assert len(target.dispatches) == 1
    record = await JobReferenceStore(real_redis).resolve(
        first["job_ref"],
        account_id=bound.account_id,
        provider_connection_id=bound.provider_connection_id,
    )
    assert record.state == InvocationState.RECOVERED_BY_POLL
    assert record.local_job_id == "original-job"


async def test_missing_target_lookup_does_not_release_or_redispatch(real_redis):
    bound = bound_identity()
    grants = GrantRecorder()

    class UnreachableTarget(DurableTarget):
        async def dispatch_invocation(self, **kwargs):
            self.dispatches.append(kwargs)
            raise ConnectionError("unreachable")

    target = UnreachableTarget(bound, grants)
    first = await coordinator(real_redis).invoke(
        target=target, identity=bound, arguments={}, grant_callbacks=grants
    )
    replay = await coordinator(real_redis).invoke(
        target=target, identity=bound, arguments={}, grant_callbacks=grants
    )
    assert replay["status"] == "processing_unknown"
    assert replay["job_ref"] == first["job_ref"]
    assert len(target.dispatches) == 1
    assert "release" not in [name for name, _ in grants.calls]
    assert "consume" not in [name for name, _ in grants.calls]


@pytest.mark.parametrize("phase", ["send", "accept", "reserve", "consume", "hold"])
async def test_all_waits_have_one_budget_even_if_dependency_ignores_cancellation(
    real_redis, phase
):
    import asyncio
    import time

    from src.control_plane.relay.lifecycle import TimeoutLadder

    release = asyncio.Event()
    entered = asyncio.Event()

    async def stubborn():
        entered.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue

    bound = bound_identity()
    grants = GrantRecorder()
    target = DurableTarget(bound, grants)
    if phase in {"reserve", "consume", "hold"}:
        original = getattr(
            grants,
            {
                "reserve": "reserve",
                "consume": "consume_on_accept",
                "hold": "hold_for_reconciliation",
            }[phase],
        )

        async def slow_callback(record):
            await original(record)
            await stubborn()

        setattr(
            grants,
            {
                "reserve": "reserve",
                "consume": "consume_on_accept",
                "hold": "hold_for_reconciliation",
            }[phase],
            slow_callback,
        )
    if phase == "send":
        original_send = target.dispatch_invocation

        async def slow_send(**kwargs):
            await original_send(**kwargs)
            await stubborn()

        target.dispatch_invocation = slow_send
    elif phase == "accept":

        async def slow_accept(identity):
            await stubborn()
            return target.proof

        target.get_acceptance = slow_accept
    elif phase == "hold":

        async def failed_send(**kwargs):
            raise ConnectionError("lost transport")

        target.dispatch_invocation = failed_send
    start = time.monotonic()
    task = asyncio.create_task(
        coordinator(
            real_redis,
            timeout_ladder=TimeoutLadder(
                cloud_send_seconds=0.02,
                target_accept_seconds=0.03,
                sync_hard_deadline_seconds=0.1,
            ),
        ).invoke(target=target, identity=bound, arguments={}, grant_callbacks=grants)
    )
    try:
        await asyncio.wait_for(entered.wait(), 0.3)
        await asyncio.sleep(0.15)
        assert task.done(), "coordinator waited for uncooperative cancellation cleanup"
        result = task.result()
        assert result["status"] == (
            "processing" if phase == "consume" else "processing_unknown"
        )
        assert time.monotonic() - start < 0.3
        assert "release" not in [name for name, _ in grants.calls]
    finally:
        release.set()
        await asyncio.wait_for(task, 0.3)
        await asyncio.sleep(0.01)


async def test_fenced_nonacceptance_releases_only_unexpired_authorization(real_redis):
    from src.control_plane.relay.protocol import TargetAcceptanceEvidence

    bound = bound_identity()
    grants = GrantRecorder()

    class RejectingTarget(DurableTarget):
        async def dispatch_invocation(self, *, identity, **kwargs):
            self.dispatches.append(identity)
            self.proof = TargetAcceptanceEvidence(
                identity=identity,
                outcome="not_accepted",
                proof_id="sha256:" + "d" * 64,
                rejection_fenced=True,
            )

    target = RejectingTarget(bound, grants)
    result = await coordinator(real_redis).invoke(
        target=target, identity=bound, arguments={}, grant_callbacks=grants
    )
    assert result["status"] == "unavailable"
    assert result["reason"] == "target_offline"
    assert result["terminal"] is True
    assert [name for name, _ in grants.calls] == ["reserve", "release"]
    replay = await coordinator(real_redis).invoke(
        target=target, identity=bound, arguments={}, grant_callbacks=grants
    )
    assert replay == result
    assert len(target.dispatches) == 1


@pytest.mark.parametrize("when", ["before", "during_reserve"])
async def test_expired_authorization_never_dispatches_or_releases(real_redis, when):
    import asyncio
    from datetime import timedelta

    bound = bound_identity(
        authorization_expires_at=datetime.now(UTC)
        + timedelta(seconds=-1 if when == "before" else 0.02)
    )
    grants = GrantRecorder()
    if when == "during_reserve":

        async def reserve(record):
            grants.calls.append(("reserve", record))
            await asyncio.sleep(0.04)

        grants.reserve = reserve
    target = DurableTarget(bound, grants)
    result = await coordinator(real_redis).invoke(
        target=target, identity=bound, arguments={}, grant_callbacks=grants
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "approval_expired"
    assert not target.dispatches
    assert "release" not in [name for name, _ in grants.calls]


async def test_acceptance_before_expiry_is_recovered_after_expiry_without_renewal(
    real_redis,
):
    import asyncio
    from datetime import timedelta

    from src.control_plane.redis_keys import RedisKey

    bound = bound_identity(
        authorization_expires_at=datetime.now(UTC) + timedelta(seconds=0.03)
    )
    grants = GrantRecorder()

    class SlowReplyTarget(DurableTarget):
        async def dispatch_invocation(self, **kwargs):
            await super().dispatch_invocation(**kwargs)
            await asyncio.sleep(0.05)

    target = SlowReplyTarget(bound, grants)
    first = await coordinator(real_redis).invoke(
        target=target, identity=bound, arguments={}, grant_callbacks=grants
    )
    assert first["status"] == "processing"
    assert [name for name, _ in grants.calls] == ["reserve", "hold"]
    expiry = await real_redis.pexpiretime(
        RedisKey.invocation(bound.relay_invocation_id)
    )
    replay = await coordinator(real_redis).invoke(
        target=target, identity=bound, arguments={}, grant_callbacks=grants
    )
    assert replay == first
    assert len(target.dispatches) == 1
    assert (
        await real_redis.pexpiretime(RedisKey.invocation(bound.relay_invocation_id))
        == expiry
    )
