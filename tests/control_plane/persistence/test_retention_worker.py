"""Opt-in workers have fixed cadence, recover safely, and do not start locally."""

import asyncio

import pytest


async def test_disabled_worker_never_connects_or_starts_tasks():
    from src.control_plane.retention.tasks import ControlPlaneRetentionWorker

    worker = ControlPlaneRetentionWorker(redis_client=None, session_factory=None)
    assert worker.redis_sweep_interval_seconds == 300
    assert worker.sql_purge_interval_seconds == 86400
    await worker.start()
    assert worker.running_task_count == 0
    await worker.stop()


async def test_worker_sweeps_real_redis_and_commits_real_postgresql(
    postgres_db, real_redis
):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.control_plane.retention.tasks import ControlPlaneRetentionWorker

    await real_redis.set("sa:approval:request:broken", "bad")
    worker = ControlPlaneRetentionWorker(
        redis_client=real_redis,
        session_factory=async_sessionmaker(postgres_db.bind, expire_on_commit=False),
        enabled=True,
    )
    result = await worker.run_once()
    assert result.redis.deleted == 1
    assert result.sql.authorization_ledger_events_deleted == 0
    await worker.start()
    await asyncio.sleep(0.02)
    assert worker.running_task_count == 2
    await worker.stop()
    assert worker.running_task_count == 0


async def test_worker_retries_failures_without_logging_raw_exception(caplog):
    from src.control_plane.retention.tasks import ControlPlaneRetentionWorker

    worker = ControlPlaneRetentionWorker(
        redis_client=None, session_factory=None, enabled=True
    )
    calls = 0
    stop = asyncio.Event()

    async def broken_then_success():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("SECRET_TOKEN_CANARY")
        stop.set()

    task = asyncio.create_task(worker._loop(broken_then_success, 0.001))
    try:
        await asyncio.wait_for(stop.wait(), 1)
        assert calls >= 2
        assert "SECRET_TOKEN_CANARY" not in caplog.text
        assert "retention_pass_failed" in caplog.text
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_new_persistence_is_not_imported_by_local_runtime(tmp_path):
    import os
    import subprocess
    import sys

    code = """
import importlib.abc, os, sys
for name in list(os.environ):
 if name.startswith("SHIPAGENT_"): del os.environ[name]
class DormantControlPlane(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname in {"src.control_plane.authorization_state", "src.control_plane.audit.authorization_ledger", "src.control_plane.retention.tasks"} or fullname == "asyncpg":
   raise AssertionError("local runtime activated optional control-plane persistence")
sys.meta_path.insert(0,DormantControlPlane())
import src.api.main, src.cli.main, src.services.batch_engine
from src.control_plane.startup import validate_startup_security
from src.control_plane.config import ControlPlaneSettings
from typer.testing import CliRunner
validate_startup_security(ControlPlaneSettings())
result = CliRunner().invoke(src.cli.main.app, ["--help"])
assert result.exit_code == 0
assert src.api.main.app is not None
assert src.services.batch_engine.BatchEngine is not None
print("local runtime remains independent")
"""
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path / 'local.db'}"}
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr
