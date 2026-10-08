"""Authority races/restarts with Redis retained and separate durable target."""

import asyncio
import json
import sys
from dataclasses import asdict

from src.control_plane.redis_keys import RedisKey
from tests.control_plane.persistence.test_grant_authority import (
    setup_authority,
)
from tests.control_plane.persistence.test_lifecycle_process_recovery import (
    effects,
    finish_client,
    reap,
    target_process,
    wait_file,
)


async def start_authority(
    redis, database, endpoint, context, purchase, approval, **options
):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tests.control_plane.persistence.grant_process",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    request = {
        "redis_port": redis.connection_pool.connection_kwargs["port"],
        "postgres_url": database["postgres_url"],
        "target_port": endpoint["port"],
        "session_id": endpoint["session_id"],
        "context": {**asdict(context), "scopes": list(context.scopes)},
        "purchase": purchase.model_dump(mode="json"),
        "approval_request_id": approval,
        **options,
    }
    process.stdin.write(json.dumps(request).encode())
    await process.stdin.drain()
    process.stdin.close()
    return process


async def test_independent_real_authorities_race_one_grant_and_restart_denies_replay(
    real_redis, postgres_db, disposable_control_stores, tmp_path
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    # Build the immutable target identity without reserving on behalf of racers.
    state = await authority.state.read(
        "execution_grant", approval, account_id=context.account_id
    )
    from src.control_plane.redis_grant_authority import RedisGrantReservation

    identity = RedisGrantReservation(authority, context, state).identity
    async with target_process(tmp_path, identity) as (endpoint, journal):
        clients = await asyncio.gather(
            *(
                start_authority(
                    real_redis,
                    disposable_control_stores,
                    endpoint,
                    context,
                    preview.value,
                    approval,
                )
                for _ in range(4)
            )
        )
        results = await asyncio.gather(*(finish_client(p) for p in clients))
        successful = [r["result"] for r in results if "result" in r]
        assert len(successful) == 1
        assert successful[0]["status"] == "processing"
        assert all(
            r["denial"] in {"grant_in_use", "grant_consumed", "reconciliation_pending"}
            for r in results
            if "denial" in r
        )
        assert len(effects(journal)) == 1
        restarted = await finish_client(
            await start_authority(
                real_redis,
                disposable_control_stores,
                endpoint,
                context,
                preview.value,
                approval,
            )
        )
        assert restarted == {"denial": "grant_consumed"}
        assert len(effects(journal)) == 1


async def test_real_authority_lost_accept_reply_recovers_original_job_after_process_restart(
    real_redis, postgres_db, disposable_control_stores, tmp_path
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    state = await authority.state.read(
        "execution_grant", approval, account_id=context.account_id
    )
    from src.control_plane.redis_grant_authority import RedisGrantReservation

    identity = RedisGrantReservation(authority, context, state).identity
    expiry = await real_redis.pexpiretime(RedisKey.execution_grant(approval))
    async with target_process(tmp_path, identity) as (endpoint, journal):
        first = await finish_client(
            await start_authority(
                real_redis,
                disposable_control_stores,
                endpoint,
                context,
                preview.value,
                approval,
                drop_reply=True,
            )
        )
        assert first["result"]["status"] == "processing_unknown"
        original = effects(journal)
        assert len(original) == 1
    async with target_process(
        tmp_path, identity, session="relay_session_restarted"
    ) as (endpoint, journal):
        second = await finish_client(
            await start_authority(
                real_redis,
                disposable_control_stores,
                endpoint,
                context,
                preview.value,
                approval,
                job_ref=first["result"]["job_ref"],
            )
        )
        assert second["result"]["status"] == "processing"
        assert second["result"]["job_ref"] == first["result"]["job_ref"]
        assert effects(journal) == original
        assert (
            await real_redis.pexpiretime(RedisKey.execution_grant(approval)) == expiry
        )


async def test_abrupt_authority_crash_after_lifecycle_acceptance_recovers_without_another_effect(
    real_redis, postgres_db, disposable_control_stores, tmp_path
):
    authority, context, preview, approval = await setup_authority(
        real_redis, postgres_db
    )
    state = await authority.state.read(
        "execution_grant", approval, account_id=context.account_id
    )
    from src.control_plane.redis_grant_authority import RedisGrantReservation

    identity = RedisGrantReservation(authority, context, state).identity
    marker = tmp_path / "accepted.marker"
    async with target_process(tmp_path, identity) as (endpoint, journal):
        process = await start_authority(
            real_redis,
            disposable_control_stores,
            endpoint,
            context,
            preview.value,
            approval,
            consume_marker=str(marker),
        )
        try:
            await wait_file(marker, process)
            process.kill()
            await asyncio.wait_for(process.wait(), 3)
        finally:
            await reap(process)
        accepted = await authority.lifecycle.get(
            identity.relay_invocation_id,
            account_id=context.account_id,
            provider_connection_id=context.provider_connection_id,
        )
        assert accepted.evidence.outcome == "accepted"
        original = effects(journal)
        recovered = await finish_client(
            await start_authority(
                real_redis,
                disposable_control_stores,
                endpoint,
                context,
                preview.value,
                approval,
                job_ref=accepted.job_ref,
            )
        )
        assert recovered["result"]["job_ref"] == accepted.job_ref
        assert recovered["result"]["status"] == "processing"
        assert effects(journal) == original and len(original) == 1
