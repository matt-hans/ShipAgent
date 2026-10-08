"""Shared lifecycle proof against disposable Redis, never an in-memory store."""

from datetime import UTC, datetime, timedelta

import pytest

from src.control_plane.redis_keys import RedisKey


def identity(**updates):
    from src.control_plane.relay.protocol import InvocationIdentity

    return InvocationIdentity(
        **{
            "account_id": "11111111-1111-4111-8111-111111111111",
            "provider_connection_id": "22222222-2222-4222-8222-222222222222",
            "execution_target_id": "relay:relay_device_" + "3" * 32,
            "approval_request_id": "sa_approval_request_" + "4" * 32,
            "tool_name": "execute_shipments",
            "arguments_hash": "sha256:" + "a" * 64,
            "idempotency_key": "server_key_" + "5" * 32,
            "authorization_expires_at": datetime.now(UTC) + timedelta(minutes=10),
            **updates,
        }
    )


async def test_one_atomic_invocation_job_pair_has_original_24h_ttl(real_redis):
    from src.control_plane.relay.lifecycle_store import (
        InvocationLifecycleStore,
        JobReferenceStore,
    )
    from src.registry.identifiers import ShipAgentIdFamily, parse_shipagent_id

    store = InvocationLifecycleStore(real_redis)
    bound = identity()
    record, created = await store.create(bound)
    assert created
    parse_shipagent_id(record.job_ref, expected_family=ShipAgentIdFamily.JOB)
    original_expiry = await real_redis.pexpiretime(
        RedisKey.invocation(record.relay_invocation_id)
    )
    assert (
        86_398_000
        < await real_redis.pttl(RedisKey.invocation(record.relay_invocation_id))
        <= 86_400_000
    )
    same, created = await store.create(bound)
    assert not created
    assert same == record
    assert await real_redis.dbsize() == 2
    assert (
        await real_redis.pexpiretime(RedisKey.job_reference(record.job_ref))
        == original_expiry
    )
    resolved = await JobReferenceStore(real_redis).resolve(
        record.job_ref,
        account_id=bound.account_id,
        provider_connection_id=bound.provider_connection_id,
    )
    assert resolved == record
    assert (
        await real_redis.pexpiretime(RedisKey.invocation(record.relay_invocation_id))
        == original_expiry
    )


async def test_independent_clients_racing_same_server_key_keep_one_pair(real_redis):
    import asyncio

    from redis.asyncio import Redis

    from src.control_plane.relay.lifecycle_store import InvocationLifecycleStore

    bound = identity()
    client = Redis(**real_redis.connection_pool.connection_kwargs)
    try:
        stores = [
            InvocationLifecycleStore(real_redis),
            InvocationLifecycleStore(client),
        ]
        outcomes = await asyncio.gather(
            *(stores[i % 2].create(bound) for i in range(16))
        )
        assert sum(created for _, created in outcomes) == 1
        assert len({record.job_ref for record, _ in outcomes}) == 1
        assert await real_redis.dbsize() == 2
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_id", "99999999-9999-4999-8999-999999999999"),
        ("provider_connection_id", "99999999-9999-4999-8999-999999999999"),
        ("execution_target_id", "sa_device_" + "9" * 32),
        ("arguments_hash", "sha256:" + "b" * 64),
        ("approval_request_id", "sa_approval_request_" + "9" * 32),
        ("tool_name", "execute_other"),
    ],
)
async def test_same_server_key_cannot_change_immutable_binding(
    real_redis, field, value
):
    from src.control_plane.relay.lifecycle_store import (
        InvocationLifecycleStore,
        LifecycleUnavailable,
    )

    store = InvocationLifecycleStore(real_redis)
    bound = identity()
    record, _ = await store.create(bound)
    with pytest.raises(LifecycleUnavailable):
        await store.create(bound.model_copy(update={field: value}))
    assert await real_redis.dbsize() == 2
    assert (
        await store.get(
            record.relay_invocation_id,
            account_id=bound.account_id,
            provider_connection_id=bound.provider_connection_id,
        )
        == record
    )


async def test_acceptance_atomically_binds_original_job_and_rejects_stale_unknown(
    real_redis,
):
    from src.control_plane.relay.lifecycle_store import (
        InvocationLifecycleStore,
        InvocationState,
        JobReferenceStore,
    )
    from src.control_plane.relay.protocol import TargetAcceptanceEvidence

    store = InvocationLifecycleStore(real_redis)
    record, _ = await store.create(identity())
    sent = await store.transition(record, InvocationState.SENT_TO_TARGET)
    expiry = await real_redis.pexpiretime(
        RedisKey.invocation(record.relay_invocation_id)
    )
    proof = TargetAcceptanceEvidence(
        identity=record.identity,
        outcome="accepted",
        local_job_id="local-job-1",
        proof_id="sha256:" + "c" * 64,
        accepted_at=datetime.now(UTC),
    )
    accepted = await store.record_evidence(sent, proof)
    assert accepted.state == InvocationState.ACCEPTED
    assert accepted.local_job_id == "local-job-1"
    # A delayed timeout writer loses its exact-version CAS and cannot downgrade.
    assert await store.transition(sent, InvocationState.DEADLINE_EXCEEDED) is None
    resolved = await JobReferenceStore(real_redis).resolve(
        record.job_ref,
        account_id=record.identity.account_id,
        provider_connection_id=record.identity.provider_connection_id,
    )
    assert resolved == accepted
    assert (
        await real_redis.pexpiretime(RedisKey.invocation(record.relay_invocation_id))
        == expiry
    )
    assert (
        await real_redis.pexpiretime(RedisKey.job_reference(record.job_ref)) == expiry
    )


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "pointer_missing",
        "ttl_less",
        "pointer_ttl_less",
        "extended",
        "pointer_extended",
        "malformed",
        "accepted_without_evidence",
    ],
)
async def test_missing_corrupt_or_extended_records_deny_without_resurrection(
    real_redis, corruption
):
    import json

    from src.control_plane.relay.lifecycle_store import (
        InvocationLifecycleStore,
        InvocationState,
        LifecycleUnavailable,
    )

    store = InvocationLifecycleStore(real_redis)
    record, _ = await store.create(identity())
    key = RedisKey.invocation(record.relay_invocation_id)
    pointer = RedisKey.job_reference(record.job_ref)
    if corruption == "missing":
        await real_redis.delete(key)
    elif corruption == "pointer_missing":
        await real_redis.delete(pointer)
    elif corruption == "ttl_less":
        await real_redis.persist(key)
    elif corruption == "pointer_ttl_less":
        await real_redis.persist(pointer)
    elif corruption == "extended":
        await real_redis.pexpire(key, 90_000_000)
    elif corruption == "pointer_extended":
        await real_redis.pexpire(pointer, 90_000_000)
    elif corruption == "malformed":
        await real_redis.set(key, '{"raw":"SECRET_CANARY"}', keepttl=True)
    else:
        value = json.loads(await real_redis.get(key))
        value["state"] = "accepted"
        await real_redis.set(key, json.dumps(value), keepttl=True)
    with pytest.raises(LifecycleUnavailable) as caught:
        await store.get(
            record.relay_invocation_id,
            account_id=record.identity.account_id,
            provider_connection_id=record.identity.provider_connection_id,
        )
    assert "SECRET_CANARY" not in str(caught.value)
    assert await store.transition(record, InvocationState.SENT_TO_TARGET) is None


async def test_job_reference_is_scoped_and_local_job_cannot_be_rebound(real_redis):
    from src.control_plane.relay.lifecycle_store import (
        InvocationLifecycleStore,
        InvocationState,
        JobReferenceStore,
        LifecycleUnavailable,
    )
    from src.control_plane.relay.protocol import TargetAcceptanceEvidence

    store = InvocationLifecycleStore(real_redis)
    record, _ = await store.create(identity())
    sent = await store.transition(record, InvocationState.SENT_TO_TARGET)
    proof = TargetAcceptanceEvidence(
        identity=record.identity,
        outcome="accepted",
        local_job_id="original-job",
        proof_id="sha256:" + "c" * 64,
        accepted_at=datetime.now(UTC),
    )
    accepted = await store.record_evidence(sent, proof)
    with pytest.raises(LifecycleUnavailable):
        await store.record_evidence(
            accepted, proof.model_copy(update={"local_job_id": "other-job"})
        )
    for account, connection in [
        ("other-account", record.identity.provider_connection_id),
        (record.identity.account_id, "other-connection"),
    ]:
        with pytest.raises(LifecycleUnavailable):
            await JobReferenceStore(real_redis).resolve(
                record.job_ref, account_id=account, provider_connection_id=connection
            )


def test_negative_evidence_requires_positive_durable_rejection_fence():
    from pydantic import ValidationError

    from src.control_plane.relay.protocol import TargetAcceptanceEvidence

    with pytest.raises(ValidationError, match="durable rejection fence"):
        TargetAcceptanceEvidence(identity=identity(), outcome="not_accepted")
    unknown = TargetAcceptanceEvidence(identity=identity(), outcome="unknown")
    assert unknown.proof_id is None


def test_target_identity_preserves_registry_shape_and_acceptance_excludes_expiry():
    from pydantic import ValidationError

    from src.control_plane.relay.protocol import TargetAcceptanceEvidence

    bound = identity()
    assert bound.execution_target_id == "relay:relay_device_" + "3" * 32
    with pytest.raises(ValidationError, match="invalid acceptance evidence"):
        TargetAcceptanceEvidence(
            identity=bound,
            outcome="accepted",
            local_job_id="job-1",
            proof_id="sha256:" + "c" * 64,
            accepted_at=bound.authorization_expires_at,
        )


async def test_repeated_identical_recovered_evidence_is_idempotent(real_redis):
    from src.control_plane.relay.lifecycle_store import (
        InvocationLifecycleStore,
        InvocationState,
    )
    from src.control_plane.relay.protocol import TargetAcceptanceEvidence

    store = InvocationLifecycleStore(real_redis)
    record, _ = await store.create(identity())
    sent = await store.transition(record, InvocationState.SENT_TO_TARGET)
    unknown = await store.transition(sent, InvocationState.DEADLINE_EXCEEDED)
    proof = TargetAcceptanceEvidence(
        identity=record.identity,
        outcome="accepted",
        local_job_id="original-job",
        proof_id="sha256:" + "c" * 64,
        accepted_at=datetime.now(UTC),
    )
    recovered = await store.record_evidence(unknown, proof)
    assert recovered.state == InvocationState.RECOVERED_BY_POLL
    assert await store.record_evidence(recovered, proof) == recovered
    assert await store.record_evidence(unknown, proof) == recovered


async def test_partial_pair_loss_cannot_mint_a_replacement_job_reference(real_redis):
    from src.control_plane.relay.lifecycle_store import (
        InvocationLifecycleStore,
        LifecycleUnavailable,
    )

    store = InvocationLifecycleStore(real_redis)
    bound = identity()
    original, _ = await store.create(bound)
    await real_redis.delete(RedisKey.invocation(bound.relay_invocation_id))
    with pytest.raises(LifecycleUnavailable):
        await store.create(bound)
    assert await real_redis.dbsize() == 1
    assert await real_redis.exists(RedisKey.job_reference(original.job_ref))
