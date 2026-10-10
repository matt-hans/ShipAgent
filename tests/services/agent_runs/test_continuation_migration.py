"""Legacy storage upgrades atomically under an exclusive coordinator lease."""

import hashlib
import json
import sqlite3
import time

from src.registry.identifiers import ShipAgentIdFamily, mint_shipagent_id
from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore


def legacy_store(tmp_path):
    path = tmp_path / "runs.sqlite3"
    run = mint_shipagent_id(ShipAgentIdFamily.AGENT_RUN)
    conversation = mint_shipagent_id(ShipAgentIdFamily.CONVERSATION)
    now = int(time.time())
    digest = hashlib.sha256(b'{"mode":"source_free","task":"Legacy plan"}').hexdigest()
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE target_owner (singleton INTEGER PRIMARY KEY, account_id TEXT NOT NULL, target_id TEXT NOT NULL, coordinator_generation INTEGER NOT NULL DEFAULT 0);
            INSERT INTO target_owner VALUES (1, 'account-a', 'target-a', 4);
            CREATE TABLE agent_runs (
                run_reference TEXT PRIMARY KEY, conversation_reference TEXT NOT NULL UNIQUE,
                connection_id TEXT NOT NULL, request_key TEXT NOT NULL, input_hash TEXT NOT NULL,
                task TEXT NOT NULL, state TEXT NOT NULL, outcome TEXT NOT NULL,
                accepted_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                private_history TEXT NOT NULL DEFAULT '[]', claim_generation INTEGER NOT NULL DEFAULT 0,
                UNIQUE (connection_id, request_key)
            );
            PRAGMA application_id=1396785746;
            PRAGMA user_version=1;
        """)
        db.execute(
            "INSERT INTO agent_runs VALUES (?, ?, 'connection-a', 'legacy-key', ?, 'Legacy plan', 'completed', 'planning_completed', ?, ?, ?, 4)",
            (
                run,
                conversation,
                digest,
                now - 30,
                now + 500,
                json.dumps(
                    [{"role": "assistant", "content": "PRIVATE_LEGACY_HISTORY"}]
                ),
            ),
        )
    path.chmod(0o600)
    return path, run


async def test_open_and_read_do_not_upgrade_but_owned_start_preserves_legacy_records(
    tmp_path,
):
    path, run = legacy_store(tmp_path)
    with sqlite3.connect(path) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(agent_runs)")]
        before = db.execute("SELECT * FROM agent_runs").fetchone()
    store = AgentRunStore(path, account_id="account-a", execution_target_id="target-a")
    original = store.read(
        connection_id="connection-a", run_reference=run
    ).public_result()
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
    service = AgentRunService(
        store=store,
        provider_factory=lambda _: (_ for _ in ()).throw(
            AssertionError("Legacy history must not replay")
        ),
    )
    await service.start()
    try:
        assert service.read(connection_id="connection-a", run_reference=run) == original
        assert (
            service.submit(
                connection_id="connection-a",
                arguments={
                    "task": "Legacy plan",
                    "mode": "source_free",
                    "request_key": "legacy-key",
                },
            )
            == original
        )
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 3
            assert (
                db.execute(
                    "SELECT " + ",".join(columns) + " FROM agent_runs"
                ).fetchone()
                == before
            )
            assert db.execute("SELECT link_epoch FROM agent_runs").fetchone()[0] is None
    finally:
        await service.close()


def test_upgrade_rejects_unowned_lease_without_changing_v1(tmp_path):
    import pytest

    from src.services.agent_runs.coordinator import CoordinatorLease

    path, run = legacy_store(tmp_path)
    store = AgentRunStore(path, account_id="account-a", execution_target_id="target-a")
    lease = CoordinatorLease(path.with_suffix(".coordinator.lock"))
    lease.close()
    with pytest.raises(RuntimeError):
        store.upgrade(lease=lease)
    assert (
        store.read(connection_id="connection-a", run_reference=run).state == "completed"
    )
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_failed_migration_rolls_back_every_schema_and_data_change(
    tmp_path, monkeypatch
):
    import pytest

    from src.services.agent_runs.coordinator import CoordinatorLease

    path, run = legacy_store(tmp_path)
    store = AgentRunStore(path, account_id="account-a", execution_target_id="target-a")
    original_connect = sqlite3.connect

    def deny_drop(*args, **kwargs):
        db = original_connect(*args, **kwargs)
        db.set_authorizer(
            lambda action, name, *args: sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_DROP_TABLE and name == "agent_runs_v1"
            else sqlite3.SQLITE_OK
        )
        return db

    lease = CoordinatorLease(path.with_suffix(".coordinator.lock"))
    try:
        monkeypatch.setattr(sqlite3, "connect", deny_drop)
        with pytest.raises(sqlite3.DatabaseError):
            store.upgrade(lease=lease)
        monkeypatch.setattr(sqlite3, "connect", original_connect)
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 1
            assert {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            } == {"target_owner", "agent_runs"}
        assert (
            store.read(connection_id="connection-a", run_reference=run).state
            == "completed"
        )
        store.upgrade(lease=lease)
        assert (
            store.read(connection_id="connection-a", run_reference=run).state
            == "completed"
        )
    finally:
        lease.close()


def test_process_death_mid_migration_leaves_original_schema_and_history(tmp_path):
    import subprocess
    import sys

    path, run = legacy_store(tmp_path)
    with sqlite3.connect(path) as db:
        original = db.execute("SELECT * FROM agent_runs").fetchone()
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            r"""
import os, sqlite3, sys
from pathlib import Path
from src.services.agent_runs.store import AgentRunStore
from src.services.agent_runs.coordinator import CoordinatorLease
path = Path(sys.argv[1])
store = AgentRunStore(path, account_id="account-a", execution_target_id="target-a")
lease = CoordinatorLease(path.with_suffix(".coordinator.lock"))
original = sqlite3.connect
def traced(*args, **kwargs):
    db = original(*args, **kwargs)
    db.set_trace_callback(lambda sql: os._exit(42) if sql == "DROP TABLE agent_runs_v1" else None)
    return db
sqlite3.connect = traced
store.upgrade(lease=lease)
""",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert child.returncode == 42, child.stderr
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT * FROM agent_runs").fetchone() == original
    store = AgentRunStore(path, account_id="account-a", execution_target_id="target-a")
    assert (
        store.read(connection_id="connection-a", run_reference=run).link_epoch is None
    )
