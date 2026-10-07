"""Real Redis proof of original TTLs, atomic writes and fail-closed reads."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.control_plane.redis_keys import RedisKey
from tests.control_plane.persistence.test_contract import metadata


def api(real_redis):
    from src.control_plane.authorization_state import (
        AuthorizationState,
        AuthorizationStateStore,
    )

    return AuthorizationStateStore(real_redis), AuthorizationState.new(
        metadata=metadata(), now=datetime.now(UTC)
    )


@pytest.mark.parametrize("kind", ["approval_request", "execution_grant"])
async def test_original_900s_ttl_duplicate_create_and_read_never_refresh(
    real_redis, kind
):
    store, record = api(real_redis)
    key = getattr(RedisKey, kind)(record.metadata.approval_request_id)
    assert await store.create(kind, record)
    ttl = await real_redis.pttl(key)
    assert 898000 < ttl <= 900000
    await asyncio.sleep(0.02)
    assert not await store.create(kind, record)
    loaded = await store.read(
        kind, record.metadata.approval_request_id, account_id=record.metadata.account_id
    )
    assert loaded == record
    assert await real_redis.pttl(key) < ttl


async def test_cas_preserves_original_expiry_and_only_one_writer_wins(real_redis):
    store, record = api(real_redis)
    assert await store.create("execution_grant", record)
    key = RedisKey.execution_grant(record.metadata.approval_request_id)
    expiry = await real_redis.pexpiretime(key)
    updated = replace(record, revision=1)
    outcomes = await asyncio.gather(
        *(
            store.replace_existing("execution_grant", original=record, updated=updated)
            for _ in range(12)
        )
    )
    assert outcomes.count(True) == 1
    assert await real_redis.pexpiretime(key) == expiry
    assert (
        await store.read(
            "execution_grant",
            record.metadata.approval_request_id,
            account_id=record.metadata.account_id,
        )
        == updated
    )


async def test_missing_expired_corrupt_and_ttlless_keys_deny_without_sql_fallback(
    real_redis,
):
    from src.control_plane.authorization_state import AuthorizationStateError

    store, record = api(real_redis)
    key = RedisKey.approval_request(record.metadata.approval_request_id)

    async def read():
        return await store.read(
            "approval_request",
            record.metadata.approval_request_id,
            account_id=record.metadata.account_id,
        )

    with pytest.raises(AuthorizationStateError):
        await read()
    await store.create("approval_request", record)
    await real_redis.persist(key)
    with pytest.raises(AuthorizationStateError):
        await read()
    await real_redis.set(key, '{"raw":"SECRET_CANARY"}', px=1000)
    with pytest.raises(AuthorizationStateError) as error:
        await read()
    assert "SECRET_CANARY" not in str(error.value)
    await real_redis.delete(key)
    await store.create("approval_request", record)
    await real_redis.pexpire(key, 5)
    await asyncio.sleep(0.025)
    with pytest.raises(AuthorizationStateError):
        await read()
    assert not await store.replace_existing(
        "approval_request", original=record, updated=replace(record, revision=1)
    )
    assert not await real_redis.exists(key)


async def test_cas_cannot_change_original_deadline_or_owner(real_redis):
    store, record = api(real_redis)
    await store.create("approval_request", record)
    for updated in [
        replace(
            record,
            created_at=record.created_at + timedelta(seconds=1),
            expires_at=record.expires_at + timedelta(seconds=1),
            revision=1,
        ),
        replace(record, metadata=metadata(), revision=1),
    ]:
        with pytest.raises(ValueError):
            await store.replace_existing(
                "approval_request", original=record, updated=updated
            )


async def test_wrong_account_and_expired_create_are_denied(real_redis):
    from src.control_plane.authorization_state import AuthorizationStateError

    store, record = api(real_redis)
    await store.create("approval_request", record)
    with pytest.raises(AuthorizationStateError):
        await store.read(
            "approval_request",
            record.metadata.approval_request_id,
            account_id=metadata().account_id,
        )
    stale = replace(
        record,
        created_at=record.created_at - timedelta(seconds=901),
        expires_at=record.expires_at - timedelta(seconds=901),
    )
    await real_redis.delete(
        RedisKey.approval_request(record.metadata.approval_request_id)
    )
    assert not await store.create("approval_request", stale)


async def test_atomic_sweeper_only_removes_owned_ttlless_keys(real_redis):
    from src.control_plane.retention.redis_sweeper import sweep_ephemeral_redis_keys

    await real_redis.set("sa:approval:request:broken", "unsafe")
    await real_redis.set("sa:jobref:broken", "unsafe")
    await real_redis.set("sa:approval:grant:active", "safe", ex=900)
    await real_redis.set("other:permanent", "untouched")
    result = await sweep_ephemeral_redis_keys(real_redis)
    assert result.deleted == 2
    assert await real_redis.exists("sa:approval:grant:active", "other:permanent") == 2


async def test_account_cleanup_only_removes_matching_metadata(real_redis):
    store, first = api(real_redis)
    second = replace(
        first, metadata=metadata(approval_request_id="sa_approval_request_" + "b" * 32)
    )
    await store.create("approval_request", first)
    await store.create("execution_grant", first)
    await store.create("approval_request", second)
    assert await store.cleanup_for_account(first.metadata.account_id) == 2
    assert (
        await store.read(
            "approval_request",
            second.metadata.approval_request_id,
            account_id=second.metadata.account_id,
        )
        == second
    )
