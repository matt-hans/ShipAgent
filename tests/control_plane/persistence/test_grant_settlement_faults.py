"""Real writes with delayed/lost acknowledgements never defeat owner fencing."""

import asyncio
from datetime import UTC, datetime

import pytest

from src.control_plane.execution_grants import ExecutionGrantError
from src.control_plane.relay.lifecycle_store import InvocationState
from src.control_plane.relay.protocol import TargetAcceptanceEvidence
from tests.control_plane.persistence.test_grant_authority import (
    reserve,
    setup_authority,
)


async def accepted_record(authority, reservation):
    record, _ = await authority.lifecycle.create(reservation.identity)
    record = await authority.lifecycle.transition(
        record, InvocationState.SENT_TO_TARGET
    )
    return await authority.lifecycle.record_evidence(
        record,
        TargetAcceptanceEvidence(
            identity=reservation.identity,
            outcome="accepted",
            local_job_id="synthetic_settled_job",
            proof_id="sha256:" + "e" * 64,
            accepted_at=datetime.now(UTC),
        ),
    )


@pytest.mark.parametrize(
    "operation,expected",
    [
        ("consume", "consumed"),
        ("release", "approved"),
        ("hold_for_reconciliation", "held"),
    ],
)
async def test_real_settlement_write_with_lost_response_remains_fenced(
    real_redis, postgres_db, monkeypatch, operation, expected
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    reservation = await reserve(authority, context, preview, approval)
    if operation == "consume":
        await accepted_record(authority, reservation)
    original = authority.state.replace_existing

    async def lost(*args, **kwargs):
        assert await original(*args, **kwargs)
        raise ConnectionError("PRIVATE_REPLY_CANARY")

    monkeypatch.setattr(authority.state, "replace_existing", lost)
    with pytest.raises(ExecutionGrantError):
        await getattr(reservation, operation)()
    monkeypatch.setattr(authority.state, "replace_existing", original)
    state = await authority.state.read(
        "execution_grant", approval, account_id=context.account_id
    )
    assert state.grant.status == expected
    if expected == "approved":
        next_owner = await reserve(authority, context, preview, approval)
        await reservation.hold_for_reconciliation()
        assert (
            await authority.state.read(
                "execution_grant", approval, account_id=context.account_id
            )
        ).grant.owner_token == next_owner.binding.reservation_token
    else:
        await reservation.release()
        with pytest.raises(ExecutionGrantError):
            await reserve(authority, context, preview, approval)


@pytest.mark.parametrize("operation", ["release", "hold_for_reconciliation", "consume"])
async def test_delayed_cancelled_settlement_cannot_downgrade_later_state(
    real_redis, postgres_db, monkeypatch, operation
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    reservation = await reserve(authority, context, preview, approval)
    if operation == "consume":
        await accepted_record(authority, reservation)
    authority.io_timeout = 0.04
    original = authority.state.replace_existing
    finish = asyncio.Event()
    writes = []
    status = {
        "release": "approved",
        "hold_for_reconciliation": "held",
        "consume": "consumed",
    }[operation]

    async def delayed(*args, **kwargs):
        if kwargs["updated"].grant.status != status:
            return await original(*args, **kwargs)

        async def remote():
            await finish.wait()
            return await original(*args, **kwargs)

        task = asyncio.create_task(remote())
        writes.append(task)
        return await asyncio.shield(task)

    monkeypatch.setattr(authority.state, "replace_existing", delayed)
    start = asyncio.get_running_loop().time()
    with pytest.raises(ExecutionGrantError):
        await getattr(reservation, operation)()
    assert asyncio.get_running_loop().time() - start < 0.3
    monkeypatch.setattr(authority.state, "replace_existing", original)
    authority.io_timeout = 2
    if operation == "release":
        await reservation.hold_for_reconciliation()
        expected = "held"
    elif operation == "hold_for_reconciliation":
        await reservation.release()
        await reserve(authority, context, preview, approval)
        expected = "reserved"
    else:
        await authority.revoke(context=context, approval_request_id=approval)
        expected = "revoked"
    finish.set()
    assert await asyncio.wait_for(asyncio.gather(*writes), 1) == [False]
    state = await authority.state.read(
        "execution_grant", approval, account_id=context.account_id
    )
    assert state.grant.status == expected


async def test_ordinary_consume_after_lease_requires_positive_evidence_reconciliation(
    real_redis, postgres_db
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db, lease_seconds=0.08
    )
    reservation = await reserve(authority, context, preview, approval)
    evidence = await accepted_record(authority, reservation)
    await asyncio.sleep(0.09)
    with pytest.raises(ExecutionGrantError):
        await reservation.consume()
    await reservation.hold_for_reconciliation()
    await reservation.callbacks().consume_on_accept(evidence)
    state = await authority.state.read(
        "execution_grant", approval, account_id=context.account_id
    )
    assert state.grant.status == "consumed"
    assert state.grant.lease_expires_at == reservation.original.grant.lease_expires_at
    assert state.expires_at == reservation.binding.expires_at
