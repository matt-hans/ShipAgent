"""Acceptance/recovery across real Redis and independently restarted processes."""

import asyncio
import json
import sqlite3
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from src.control_plane.redis_keys import RedisKey
from tests.control_plane.persistence.lifecycle_process import ProtocolTarget
from tests.control_plane.persistence.test_invocation_lifecycle import bound_identity

MODULE = "tests.control_plane.persistence.lifecycle_process"


async def wait_file(path, process):
    for _ in range(500):
        if path.exists() and path.stat().st_size:
            return path.read_text()
        if process.returncode is not None:
            _, error = await process.communicate()
            raise AssertionError(f"synthetic process exited: {error.decode()}")
        await asyncio.sleep(0.01)
    raise AssertionError("synthetic process readiness timed out")


async def reap(process):
    if process.returncode is None:
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), 3)
    except TimeoutError:
        process.kill()
        await asyncio.wait_for(process.wait(), 3)


@asynccontextmanager
async def target_process(tmp_path, identity, *, session="relay_session_first"):
    ready = tmp_path / f"{session}.json"
    journal = tmp_path / "target-journal.db"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        MODULE,
        "target",
        "--journal",
        str(journal),
        "--ready",
        str(ready),
        "--target-id",
        identity.execution_target_id,
        "--session-id",
        session,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        endpoint = json.loads(await wait_file(ready, process))
        yield endpoint, journal
    finally:
        await reap(process)


async def start_client(
    redis, endpoint, identity, *, job_ref=None, drop_reply=False, marker=None
):
    args = [
        sys.executable,
        "-m",
        MODULE,
        "lifecycle",
        "--redis-port",
        str(redis.connection_pool.connection_kwargs["port"]),
        "--target-port",
        str(endpoint["port"]),
        "--session-id",
        endpoint["session_id"],
    ]
    if drop_reply:
        args.append("--drop-reply")
    if marker is not None:
        args += ["--consume-marker", str(marker)]
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    request = {"identity": identity.model_dump(mode="json"), "job_ref": job_ref}
    process.stdin.write(json.dumps(request).encode())
    await process.stdin.drain()
    process.stdin.close()
    return process


async def finish_client(process):
    try:
        out, error = await asyncio.wait_for(process.communicate(), 8)
        assert process.returncode == 0, error.decode()
        return json.loads(out)
    finally:
        await reap(process)


def effects(journal):
    with sqlite3.connect(journal) as db:
        return db.execute("SELECT job, key FROM effects").fetchall()


async def test_lost_accept_response_recovers_after_target_and_application_restart(
    real_redis, tmp_path
):
    identity = bound_identity()
    async with target_process(tmp_path, identity) as (endpoint, journal):
        first = await finish_client(
            await start_client(real_redis, endpoint, identity, drop_reply=True)
        )
        assert first["result"]["status"] == "processing_unknown"
        assert first["callbacks"] == ["reserve", "hold"]
        original_effect = effects(journal)
        assert len(original_effect) == 1
        original_expiry = await real_redis.pexpiretime(
            RedisKey.invocation(identity.relay_invocation_id)
        )
    async with target_process(
        tmp_path, identity, session="relay_session_reconnected"
    ) as (endpoint, journal):
        second = await finish_client(
            await start_client(
                real_redis, endpoint, identity, job_ref=first["result"]["job_ref"]
            )
        )
        assert second["result"]["status"] == "processing"
        assert second["result"]["job_ref"] == first["result"]["job_ref"]
        assert second["callbacks"] == ["consume"]
        assert effects(journal) == original_effect
        from src.control_plane.relay.lifecycle_store import JobReferenceStore

        record = await JobReferenceStore(real_redis).resolve(
            second["result"]["job_ref"],
            account_id=identity.account_id,
            provider_connection_id=identity.provider_connection_id,
        )
        assert record.local_job_id == original_effect[0][0]
        assert record.identity.idempotency_key == original_effect[0][1]
        assert (
            await real_redis.pexpiretime(
                RedisKey.invocation(identity.relay_invocation_id)
            )
            == original_expiry
        )


async def test_crash_after_durable_evidence_before_consume_retries_settlement_only(
    real_redis, tmp_path
):
    identity = bound_identity()
    marker = tmp_path / "consume-entered.txt"
    async with target_process(tmp_path, identity) as (endpoint, journal):
        process = await start_client(real_redis, endpoint, identity, marker=marker)
        try:
            job_ref = await wait_file(marker, process)
            process.kill()  # Abrupt lifecycle death, not graceful cancellation.
            await asyncio.wait_for(process.wait(), 3)
        finally:
            await reap(process)
        original_effect = effects(journal)
        assert len(original_effect) == 1
        recovered = await finish_client(
            await start_client(real_redis, endpoint, identity, job_ref=job_ref)
        )
        assert recovered["result"]["job_ref"] == job_ref
        assert recovered["callbacks"] == ["consume"]
        assert effects(journal) == original_effect


async def test_separate_lifecycle_process_race_has_one_committed_effect(
    real_redis, tmp_path
):
    identity = bound_identity()
    async with target_process(tmp_path, identity) as (endpoint, journal):
        processes = await asyncio.gather(
            *(start_client(real_redis, endpoint, identity) for _ in range(3))
        )
        outcomes = await asyncio.gather(
            *(finish_client(process) for process in processes)
        )
        assert sum("reserve" in outcome["callbacks"] for outcome in outcomes) == 1
        assert len({outcome["result"]["job_ref"] for outcome in outcomes}) == 1
        assert len(effects(journal)) == 1
        assert len(await real_redis.keys("sa:invocation:*")) == 1
        assert len(await real_redis.keys("sa:jobref:*")) == 1


async def test_target_rejection_fence_excludes_delayed_original_send(
    real_redis, tmp_path
):
    identity = bound_identity()
    async with target_process(tmp_path, identity) as (endpoint, journal):
        target = ProtocolTarget(
            port=endpoint["port"],
            session_id=endpoint["session_id"],
            execution_target_id=identity.execution_target_id,
        )
        proof = await target.fence(identity)
        assert proof.rejection_fenced
        await target.dispatch_invocation(
            identity=identity,
            arguments={},
            deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        )
        assert await target.get_acceptance(identity) == proof
        assert effects(journal) == []


@pytest.mark.parametrize("invalid", ["session", "hash", "deadline"])
async def test_protocol_target_rejects_invalid_existing_envelope_fields(
    tmp_path, invalid
):
    identity = bound_identity()
    async with target_process(tmp_path, identity) as (endpoint, journal):
        target = ProtocolTarget(
            port=endpoint["port"],
            session_id=endpoint["session_id"],
            execution_target_id=identity.execution_target_id,
        )
        arguments = {}
        deadline = datetime.now(UTC) + timedelta(seconds=5)
        if invalid == "session":
            target.session_id = "wrong-session"
        elif invalid == "hash":
            arguments = {"row": "TRANSIT_ONLY_CANARY"}
        else:
            deadline = datetime.now(UTC) - timedelta(seconds=1)
        with pytest.raises(RuntimeError, match="synthetic_protocol_rejected"):
            await target.dispatch_invocation(
                identity=identity, arguments=arguments, deadline_at=deadline
            )
        assert (await target.get_acceptance(identity)).outcome == "unknown"
        assert effects(journal) == []


async def test_protocol_target_rejects_nonincreasing_session_sequence(tmp_path):
    first = bound_identity()
    second = bound_identity(idempotency_key="different_server_key_" + "a" * 32)
    async with target_process(tmp_path, first) as (endpoint, journal):
        target = ProtocolTarget(
            port=endpoint["port"],
            session_id=endpoint["session_id"],
            execution_target_id=first.execution_target_id,
        )
        await target.dispatch_invocation(
            identity=first,
            arguments={},
            deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        )
        restarted_transport = ProtocolTarget(
            port=endpoint["port"],
            session_id=endpoint["session_id"],
            execution_target_id=second.execution_target_id,
        )
        with pytest.raises(RuntimeError, match="synthetic_protocol_rejected"):
            await restarted_transport.dispatch_invocation(
                identity=second,
                arguments={},
                deadline_at=datetime.now(UTC) + timedelta(seconds=5),
            )
        assert len(effects(journal)) == 1
        assert (await target.get_acceptance(second)).outcome == "unknown"
