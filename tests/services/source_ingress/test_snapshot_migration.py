"""Source metadata migration is explicit, fenced, atomic and payload preserving."""

import hashlib
import json
import sqlite3
from contextlib import asynccontextmanager, closing

import pytest

from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.source_ingress.reservation_contracts import ReservationError
from src.services.source_ingress.reservation_store import (
    ReservationStore,
    ReservationTransaction,
)
from src.services.source_ingress.source_store_owner import SourceStoreOwner


def v1_file(path):
    path.touch(mode=0o600)
    namespace = {
        "account_id": "account-a",
        "provider_connection_id": "connection-a",
        "link_epoch": "epoch-a",
        "conversation_reference": "sa_conversation_" + "a" * 32,
        "execution_target_id": "target-a",
        "target_fingerprint": "fingerprint-a",
        "request_key": "original",
        "operation": "upload",
    }
    content = {
        "content_length": 12,
        "content_sha256": "b" * 64,
        "media_type": "text/csv",
        "parser_profile": "synthetic_csv_v1",
    }

    def canonical(value):
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    payload = canonical(
        {
            "version": 1,
            "namespace": namespace,
            "input": content,
            "admitted_revision": 1,
            "admitted_at": 100,
            "upload_expires_at": 400,
            "prospective_source_expires_at": 86500,
        }
    )
    identity = "c" * 32
    namespace_hash = hashlib.sha256(canonical(namespace).encode()).hexdigest()
    input_hash = hashlib.sha256(canonical(content).encode()).hexdigest()
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        db.execute("PRAGMA page_size=4096")
        db.execute("PRAGMA auto_vacuum=NONE")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "CREATE TABLE target_owner(singleton INTEGER PRIMARY KEY CHECK(singleton=1), account_id TEXT NOT NULL, target_id TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE reservations(reservation_id TEXT PRIMARY KEY, namespace_digest TEXT NOT NULL UNIQUE, input_digest TEXT NOT NULL, upload_expires_at INTEGER NOT NULL, payload TEXT NOT NULL, metadata_bytes INTEGER NOT NULL)"
        )
        db.execute("INSERT INTO target_owner VALUES(1, 'account-a', 'target-a')")
        db.execute(
            "INSERT INTO reservations VALUES(?,?,?,?,?,?)",
            (
                identity,
                namespace_hash,
                input_hash,
                400,
                payload,
                32 + 64 + 64 + len(payload.encode()) + 16,
            ),
        )
        db.execute("PRAGMA application_id=1396790098")
        db.execute("PRAGMA user_version=1")
        db.commit()
    return payload


def persisted(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute("PRAGMA user_version").fetchone()[0], db.execute(
            "SELECT * FROM reservations"
        ).fetchall()


@asynccontextmanager
async def maintenance(tmp_path):
    runs = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=not (tmp_path / "runs.sqlite3").exists(),
    )
    agent = AgentRunService(
        store=runs, provider_factory=lambda _: pytest.fail("migration called model")
    )
    await agent.start()
    store = ReservationStore(
        tmp_path / "sources.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        coordinator_path=runs.path.with_suffix(".coordinator.lock"),
    )
    owner = SourceStoreOwner(agent, store)
    try:
        yield agent, store, owner
    finally:
        owner.close()
        await agent.close()


async def test_open_preserves_v1_and_explicit_upgrade_preserves_exact_records(tmp_path):
    payload = v1_file(tmp_path / "sources.sqlite3")
    before = persisted(tmp_path / "sources.sqlite3")
    async with maintenance(tmp_path) as (_, store, owner):
        owner.open()
        assert persisted(store.path) == before
        assert callable(getattr(owner, "upgrade_to_v2", None)), (
            "explicit V2 migration is absent"
        )
        owner.upgrade_to_v2()
        version, rows = persisted(store.path)
        assert version == 2 and rows == before[1]
        assert rows[0][4] == payload and json.loads(payload)["version"] == 1
        owner.upgrade_to_v2()
        assert persisted(store.path) == (version, rows)


@pytest.mark.parametrize("after_effect", [False, True])
async def test_migration_commit_fault_preserves_actual_durable_outcome(
    tmp_path, monkeypatch, after_effect
):
    v1_file(tmp_path / "sources.sqlite3")
    before = persisted(tmp_path / "sources.sqlite3")
    async with maintenance(tmp_path) as (agent, store, owner):
        owner.open()
        assert callable(getattr(owner, "upgrade_to_v2", None)), (
            "explicit V2 migration is absent"
        )
        original = ReservationTransaction._commit_database

        def commit(tx):
            if after_effect:
                original(tx)
            raise OSError("PRIVATE-MIGRATION-COMMIT")

        with monkeypatch.context() as patch:
            patch.setattr(ReservationTransaction, "_commit_database", commit)
            with pytest.raises(ReservationError):
                owner.upgrade_to_v2()
            with pytest.raises(ReservationError):
                owner.upgrade_to_v2()
            with pytest.raises(RuntimeError):
                agent.borrow_coordinator()
        owner.close()
        version, rows = persisted(store.path)
        assert version == (2 if after_effect else 1)
        assert rows == before[1]


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
async def test_real_process_death_migration_has_only_old_or_complete_new_schema(
    tmp_path, phase
):
    import os
    import subprocess
    import sys

    v1_file(tmp_path / "sources.sqlite3")
    before = persisted(tmp_path / "sources.sqlite3")
    script = """
import asyncio, os, sys
from pathlib import Path
from tests.services.source_ingress.test_snapshot_migration import maintenance
from src.services.source_ingress.reservation_store import ReservationTransaction
async def main():
    async with maintenance(Path(sys.argv[1])) as (_, store, owner):
        owner.open()
        original = ReservationTransaction._commit_database
        def commit(tx):
            if sys.argv[2] == "after_commit":
                original(tx)
            os._exit(42)
        ReservationTransaction._commit_database = commit
        owner.upgrade_to_v2()
asyncio.run(main())
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), phase],
        capture_output=True,
        text=True,
        timeout=15,
        env=os.environ.copy(),
    )
    assert child.returncode == 42, child.stderr
    async with maintenance(tmp_path) as (_, store, owner):
        owner.open()
        version, rows = persisted(store.path)
        assert version == (1 if phase == "before_commit" else 2)
        assert rows == before[1]
        with closing(sqlite3.connect(store.path)) as db:
            names = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                )
            }
        assert names == (
            {"target_owner", "reservations"}
            if version == 1
            else {
                "target_owner",
                "reservations",
                "source_lifecycle",
                "snapshot_manifests",
            }
        )
        owner.upgrade_to_v2()
        assert persisted(store.path) == (2, before[1])


def test_cached_v1_requires_live_writer_even_when_v2_commit_is_only_in_wal(
    tmp_path, monkeypatch
):
    import time

    from tests.services.agent_runs.test_source_ownership import owned_conversation

    v1_file(tmp_path / "sources.sqlite3")
    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        store = ReservationStore(
            tmp_path / "sources.sqlite3",
            account_id="account-a",
            execution_target_id="target-a",
            coordinator_path=runs.path.with_suffix(".coordinator.lock"),
        )
        store.open(conversation=scope, deadline=time.monotonic() + 2)
        tx = store.transaction(conversation=scope)
        invalid = None
        try:
            tx.acquire(deadline=time.monotonic() + 2)
            assert tx.upgrade_schema()
            tx.commit()
            assert tx._db.execute("PRAGMA user_version").fetchone()[0] == 2
            # Read only the existing inode via a separate process: opening and
            # closing a descriptor here would disturb SQLite's POSIX locks.
            import subprocess
            import sys

            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    'import sys; p=open(sys.argv[1],"rb"); p.seek(60); print(int.from_bytes(p.read(4),"big"))',
                    str(store.path),
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            assert result.returncode == 0 and result.stdout.strip() == "1"
            real = sqlite3.connect
            calls = []

            def connect(path, *args, **kwargs):
                if str(store.path) in str(path):
                    calls.append(str(path))
                    pytest.fail("cached V1 bypassed held ownership before WAL recovery")
                return real(path, *args, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(sqlite3, "connect", connect)
                invalid = store.transaction(conversation=None)
                with pytest.raises(ReservationError):
                    invalid.acquire(deadline=time.monotonic() + 2)
                assert calls == []
        finally:
            if invalid is not None:
                invalid.retire()
            tx.retire()
            store.close()
