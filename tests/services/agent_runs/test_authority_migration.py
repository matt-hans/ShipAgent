"""V3 adds private turn authority only through explicit owned migration."""

import sqlite3
import subprocess
import sys

import pytest

from src.services.agent_runs.coordinator import CoordinatorLease
from src.services.agent_runs.store import AgentRunStore
from tests.services.agent_runs.test_continuation_migration import legacy_store


@pytest.mark.parametrize("version", [1, 2])
def test_owned_upgrade_preserves_all_legacy_values_unbound(tmp_path, version):
    path, run = legacy_store(tmp_path)
    store = AgentRunStore(path, account_id="account-a", execution_target_id="target-a")
    lease = CoordinatorLease(path.with_suffix(".coordinator.lock"))
    try:
        if version == 2:
            store.upgrade(lease=lease)
            with sqlite3.connect(path) as db:
                columns = [r[1] for r in db.execute("PRAGMA table_info(agent_runs)")]
                if "turn_authority_expires_at" in columns:
                    db.execute(
                        "ALTER TABLE agent_runs DROP COLUMN turn_authority_expires_at"
                    )
                db.execute("PRAGMA user_version=2")
        with sqlite3.connect(path) as db:
            columns = [r[1] for r in db.execute("PRAGMA table_info(agent_runs)")]
            before = db.execute("SELECT * FROM agent_runs").fetchone()
        reopened = AgentRunStore(
            path, account_id="account-a", execution_target_id="target-a"
        )
        reopened.read(connection_id="connection-a", run_reference=run)
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == version
        store.upgrade(lease=lease)
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 3
            assert (
                db.execute(
                    "SELECT " + ",".join(columns) + " FROM agent_runs"
                ).fetchone()
                == before
            )
            assert (
                db.execute(
                    "SELECT turn_authority_expires_at FROM agent_runs"
                ).fetchone()[0]
                is None
            )
    finally:
        lease.close()


@pytest.mark.parametrize("death", [False, True])
@pytest.mark.parametrize("version", [1, 2])
def test_v3_upgrade_failure_is_atomic(tmp_path, death, monkeypatch, version):
    path, _ = legacy_store(tmp_path)
    if version == 2:
        prepared = AgentRunStore(
            path, account_id="account-a", execution_target_id="target-a"
        )
        preparation_lease = CoordinatorLease(path.with_suffix(".coordinator.lock"))
        try:
            prepared.upgrade(lease=preparation_lease)
        finally:
            preparation_lease.close()
        with sqlite3.connect(path) as db:
            db.execute("ALTER TABLE agent_runs DROP COLUMN turn_authority_expires_at")
            db.execute("PRAGMA user_version=2")
    if death:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import os, sqlite3, sys
from pathlib import Path
from src.services.agent_runs.store import AgentRunStore
from src.services.agent_runs.coordinator import CoordinatorLease
p=Path(sys.argv[1]); s=AgentRunStore(p,account_id="account-a",execution_target_id="target-a"); l=CoordinatorLease(p.with_suffix(".coordinator.lock"))
original=sqlite3.connect
def connect(*a,**k):
 d=original(*a,**k); d.set_trace_callback(lambda q: os._exit(42) if "turn_authority_expires_at" in q else None); return d
sqlite3.connect=connect
s.upgrade(lease=l)
""",
                str(path),
            ],
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 42, result.stderr
    else:
        store = AgentRunStore(
            path, account_id="account-a", execution_target_id="target-a"
        )
        lease = CoordinatorLease(path.with_suffix(".coordinator.lock"))
        original = sqlite3.connect

        def connect(*a, **k):
            db = original(*a, **k)
            db.set_authorizer(
                lambda op, *args: sqlite3.SQLITE_DENY
                if op == sqlite3.SQLITE_PRAGMA
                and args[0] == "user_version"
                and args[1] == "3"
                else sqlite3.SQLITE_OK
            )
            return db

        monkeypatch.setattr(sqlite3, "connect", connect)
        try:
            with pytest.raises(sqlite3.DatabaseError):
                store.upgrade(lease=lease)
        finally:
            lease.close()
            monkeypatch.setattr(sqlite3, "connect", original)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == version
        assert "turn_authority_expires_at" not in [
            r[1] for r in db.execute("PRAGMA table_info(agent_runs)")
        ]
        assert (
            db.execute("SELECT private_history FROM agent_runs")
            .fetchone()[0]
            .find("PRIVATE_LEGACY_HISTORY")
            >= 0
        )


@pytest.mark.parametrize("after", [False, True])
def test_failed_migration_retirement_keeps_exact_owner_and_lease(
    tmp_path, monkeypatch, after
):
    from src.services.agent_runs.transaction import AgentRunTransaction

    path, _ = legacy_store(tmp_path)
    store = AgentRunStore(path, account_id="account-a", execution_target_id="target-a")
    lease = CoordinatorLease(path.with_suffix(".coordinator.lock"))
    original = AgentRunTransaction._close_connection

    def fail(owner):
        if after:
            original(owner)
        raise OSError("PRIVATE_MIGRATION_CANARY")

    try:
        monkeypatch.setattr(AgentRunTransaction, "_close_connection", fail)
        with pytest.raises(RuntimeError, match="unavailable"):
            store.upgrade(lease=lease)
        assert store._upgrade_owner.commit_known
        with pytest.raises(RuntimeError):
            lease.close()
        assert lease.is_owned
        monkeypatch.setattr(AgentRunTransaction, "_close_connection", original)
        store.retire_upgrade()
        lease.close()
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        monkeypatch.setattr(AgentRunTransaction, "_close_connection", original)
        if hasattr(store, "retire_upgrade"):
            store.retire_upgrade()
        lease.close()


async def test_start_preserves_control_flow_failure_above_retained_migration(
    tmp_path, monkeypatch
):
    from src.services.agent_runs.service import AgentRunService
    from src.services.agent_runs.transaction import AgentRunTransaction

    path, _ = legacy_store(tmp_path)
    store = AgentRunStore(path, account_id="account-a", execution_target_id="target-a")
    service = AgentRunService(store=store, provider_factory=lambda _: None)
    original_rollback = AgentRunTransaction._rollback_sql

    def interrupted(_):
        raise KeyboardInterrupt("original interruption")

    def failed_rollback(_):
        raise OSError("PRIVATE_ROLLBACK_CANARY")

    monkeypatch.setattr(store, "_upgrade_on", interrupted)
    monkeypatch.setattr(AgentRunTransaction, "_rollback_sql", failed_rollback)
    try:
        with pytest.raises(KeyboardInterrupt, match="original interruption"):
            await service.start()
        assert service._lease is not None and service._lease.is_owned
        replacement = AgentRunStore(
            path, account_id="account-a", execution_target_id="target-a"
        )
        with pytest.raises(RuntimeError):
            replacement.upgrade(lease=service._lease)
    finally:
        monkeypatch.setattr(AgentRunTransaction, "_rollback_sql", original_rollback)
        await service.close()


def test_copied_store_cannot_release_original_migration_owner(tmp_path, monkeypatch):
    import copy

    from src.services.agent_runs.transaction import AgentRunTransaction

    path, _ = legacy_store(tmp_path)
    store = AgentRunStore(path, account_id="account-a", execution_target_id="target-a")
    lease = CoordinatorLease(path.with_suffix(".coordinator.lock"))
    original = AgentRunTransaction._close_connection

    def fail(_):
        raise OSError("retained connection")

    try:
        monkeypatch.setattr(AgentRunTransaction, "_close_connection", fail)
        with pytest.raises(RuntimeError):
            store.upgrade(lease=lease)
        monkeypatch.setattr(AgentRunTransaction, "_close_connection", original)
        with pytest.raises(RuntimeError):
            copy.copy(store).retire_upgrade()
        assert not store._upgrade_owner.retirement_completed
        store.retire_upgrade()
    finally:
        monkeypatch.setattr(AgentRunTransaction, "_close_connection", original)
        store.retire_upgrade()
        lease.close()
