"""Acceptance is bounded, idempotent, private and never silently resurrected."""

import pytest

from src.services.agent_runs.coordinator import CoordinatorLease
from src.services.agent_runs.store import AgentRunStore


def accept(store, generation, key, *, connection="connection-a"):
    return store.accept(
        connection_id=connection,
        task="Plan safely",
        mode="source_free",
        request_key=key,
        generation=generation,
    )


def test_expired_retry_and_read_do_not_refresh_or_relaunch(tmp_path, monkeypatch):
    now = [1_800_000_000]
    monkeypatch.setattr("src.services.agent_runs.store.time.time", lambda: now[0])
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    lease = CoordinatorLease(store.path.with_suffix(".coordinator.lock"))
    try:
        generation = store.begin_coordinator(lease=lease)
        original = accept(store, generation, "original-key")
        now[0] += 10
        assert accept(store, generation, "original-key") == original
        now[0] = original.expires_at
        with pytest.raises(PermissionError, match="unavailable"):
            accept(store, generation, "original-key")
        with pytest.raises(PermissionError, match="unavailable"):
            store.read(
                connection_id="connection-a", run_reference=original.run_reference
            )
        assert store.claim_next(generation=generation) is None
    finally:
        lease.close()


def test_per_connection_pending_limit_does_not_block_identical_retry(tmp_path):
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    lease = CoordinatorLease(store.path.with_suffix(".coordinator.lock"))
    try:
        generation = store.begin_coordinator(lease=lease)
        original = accept(store, generation, "original-key")
        for index in range(3):
            accept(store, generation, f"request-{index}")
        with pytest.raises(ValueError, match="capacity"):
            accept(store, generation, "overflow-key")
        assert accept(store, generation, "original-key") == original
        assert (
            accept(store, generation, "another-key", connection="connection-b").state
            == "queued"
        )
    finally:
        lease.close()


def test_account_pending_limit_cannot_be_evaded_with_connection_churn(tmp_path):
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    lease = CoordinatorLease(store.path.with_suffix(".coordinator.lock"))
    try:
        generation = store.begin_coordinator(lease=lease)
        for index in range(16):
            accept(
                store, generation, f"request-{index}", connection=f"connection-{index}"
            )
        with pytest.raises(ValueError, match="capacity"):
            accept(store, generation, "overflow-key", connection="new-connection")
    finally:
        lease.close()


def test_completed_runs_still_count_against_acceptance_budget(tmp_path):
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    lease = CoordinatorLease(store.path.with_suffix(".coordinator.lock"))
    try:
        generation = store.begin_coordinator(lease=lease)
        for index in range(20):
            accept(store, generation, f"request-{index}")
            run = store.claim_next(generation=generation)
            store.finish(run, outcome="planning_completed", private_history=[])
        with pytest.raises(ValueError, match="capacity"):
            accept(store, generation, "overflow-key")
        assert accept(store, generation, "request-0").state == "completed"
    finally:
        lease.close()


def test_reopen_never_creates_a_missing_store(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises((FileNotFoundError, PermissionError)):
        AgentRunStore(path, account_id="account-a", execution_target_id="target-a")
    assert not path.exists()


def test_private_store_permissions_and_original_file_identity(tmp_path):
    import os
    import stat

    path = tmp_path / "runs.sqlite3"
    store = AgentRunStore(
        path, account_id="account-a", execution_target_id="target-a", create=True
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    path.rename(tmp_path / "original.sqlite3")
    # An accidental unlink or replacement must never make this owner create a
    # fresh database that accepts previously used idempotency keys again.
    with pytest.raises((FileNotFoundError, PermissionError, RuntimeError)):
        store.read(connection_id="connection-a", run_reference="missing")
    assert not path.exists()
    os.link(tmp_path / "original.sqlite3", path)
    with pytest.raises(PermissionError):
        AgentRunStore(path, account_id="account-a", execution_target_id="target-a")


def test_symlinked_store_and_coordinator_are_rejected(tmp_path):
    original = tmp_path / "original.sqlite3"
    AgentRunStore(
        original, account_id="account-a", execution_target_id="target-a", create=True
    )
    linked = tmp_path / "linked.sqlite3"
    linked.symlink_to(original)
    with pytest.raises(PermissionError):
        AgentRunStore(linked, account_id="account-a", execution_target_id="target-a")


def test_broadly_readable_coordinator_file_is_rejected(tmp_path):
    path = tmp_path / "coordinator.lock"
    path.write_text("")
    path.chmod(0o644)
    with pytest.raises(PermissionError):
        lease = CoordinatorLease(path)
        lease.close()


def test_failed_coordinator_directory_sync_releases_its_acquired_lease(
    tmp_path, monkeypatch
):
    from src.services.agent_runs import coordinator

    path = tmp_path / "coordinator.lock"
    original_sync = coordinator.sync_directory

    def fail_sync(_):
        raise OSError("SYNTHETIC_SYNC_FAILURE")

    monkeypatch.setattr(coordinator, "sync_directory", fail_sync)
    with pytest.raises(OSError):
        CoordinatorLease(path)
    monkeypatch.setattr(coordinator, "sync_directory", original_sync)
    lease = CoordinatorLease(path)
    lease.close()


def test_account_hourly_budget_counts_completed_connection_churn(tmp_path):
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    lease = CoordinatorLease(store.path.with_suffix(".coordinator.lock"))
    try:
        generation = store.begin_coordinator(lease=lease)
        for index in range(60):
            accept(
                store, generation, f"request-{index}", connection=f"connection-{index}"
            )
            store.finish(
                store.claim_next(generation=generation),
                outcome="planning_completed",
                private_history=[],
            )
        with pytest.raises(ValueError, match="capacity"):
            accept(store, generation, "overflow-key", connection="new-connection")
    finally:
        lease.close()


def test_retention_bound_does_not_drop_idempotency_records(tmp_path, monkeypatch):
    from src.services.agent_runs import store as store_module

    now = [1_800_000_000]
    monkeypatch.setattr(store_module, "MAX_RETAINED_RUNS", 2)
    monkeypatch.setattr(store_module.time, "time", lambda: now[0])
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    lease = CoordinatorLease(store.path.with_suffix(".coordinator.lock"))
    try:
        generation = store.begin_coordinator(lease=lease)
        first = accept(store, generation, "first-request")
        accept(store, generation, "second-request")
        now[0] = first.expires_at
        with pytest.raises(ValueError, match="capacity"):
            accept(store, generation, "third-request")
        with pytest.raises(PermissionError, match="unavailable"):
            accept(store, generation, "first-request")
    finally:
        lease.close()


def test_broad_directory_or_sidecar_permissions_fail_closed(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "runs.sqlite3"
    store = AgentRunStore(
        path, account_id="account-a", execution_target_id="target-a", create=True
    )
    private.chmod(0o755)
    with pytest.raises(PermissionError):
        store.read(connection_id="connection-a", run_reference="missing")
    assert private.stat().st_mode & 0o777 == 0o755
    private.chmod(0o700)
    sidecar = private / "runs.sqlite3-wal"
    sidecar.symlink_to(path)
    with pytest.raises(PermissionError):
        AgentRunStore(path, account_id="account-a", execution_target_id="target-a")
    assert sidecar.is_symlink()


def test_reopen_rejects_foreign_sqlite_without_modifying_it(tmp_path):
    import hashlib
    import sqlite3

    path = tmp_path / "unrelated.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE unrelated (value TEXT)")
        db.execute("INSERT INTO unrelated VALUES ('PRIVATE_FOREIGN_CANARY')")
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    path.chmod(0o600)
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(PermissionError, match="format"):
        AgentRunStore(path, account_id="account-a", execution_target_id="target-a")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert (
            db.execute("SELECT value FROM unrelated").fetchone()[0]
            == "PRIVATE_FOREIGN_CANARY"
        )
