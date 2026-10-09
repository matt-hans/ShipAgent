"""Fresh ownership resolves durable visibility before incomplete-file cleanup."""

import os
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest

from src.services.source_ingress.reservation_contracts import ReservationError
from src.services.source_ingress.snapshot_files import SnapshotFiles
from tests.services.source_ingress.test_snapshot_files import attempt, opened


@pytest.mark.parametrize("absent", ["none", "raw", "both"])
def test_recovery_opens_only_recorded_incomplete_files_and_syncs_absence(
    tmp_path, absent
):
    root_owner, root = opened(tmp_path)
    original = root_owner.allocate(attempt())
    original.create()
    raw_identity, normalized_identity = original.identities()
    saved = replace(
        attempt(), raw_identity=raw_identity, normalized_identity=normalized_identity
    )
    original.retire(remove_incomplete=False)
    if absent in {"raw", "both"}:
        (root / saved.raw_basename).unlink()
    if absent == "both":
        (root / saved.normalized_basename).unlink()
    recovery = None
    try:
        assert callable(getattr(root_owner, "allocate_recovery", None)), (
            "owned recovery opener is absent"
        )
        recovery = root_owner.allocate_recovery(saved)
        recovery.open_recovery()
        recovery.retire(remove_incomplete=True)
        assert recovery._deletion_completed
        assert list(root.iterdir()) == []
        recovery.retire(remove_incomplete=True)
    finally:
        if recovery is not None:
            recovery.retire(remove_incomplete=False)
        root_owner.close()


@pytest.mark.parametrize("fault", ["missing_identity", "replacement", "fifo"])
def test_recovery_never_deletes_unproven_or_replaced_fixed_name(tmp_path, fault):
    root_owner, root = opened(tmp_path)
    original = root_owner.allocate(attempt())
    original.create()
    raw_identity, normalized_identity = original.identities()
    saved = replace(
        attempt(), raw_identity=raw_identity, normalized_identity=normalized_identity
    )
    original.retire(remove_incomplete=False)
    raw_path = root / saved.raw_basename
    if fault == "missing_identity":
        saved = replace(saved, raw_identity=None, normalized_identity=None)
    else:
        raw_path.rename(root / "held-original")
        if fault == "fifo":
            os.mkfifo(raw_path, 0o600)
        else:
            raw_path.write_bytes(b"UNRELATED_PRIVATE_CANARY")
            raw_path.chmod(0o600)
    recovery = None
    try:
        assert callable(getattr(root_owner, "allocate_recovery", None)), (
            "owned recovery opener is absent"
        )
        recovery = root_owner.allocate_recovery(saved)
        with pytest.raises(ReservationError) as caught:
            recovery.open_recovery()
        assert caught.value.code == "reservation_unavailable"
        with pytest.raises(ReservationError):
            recovery.retire(remove_incomplete=True)
        assert raw_path.exists()
        assert (root / saved.normalized_basename).exists()
    finally:
        if recovery is not None:
            recovery.retire(remove_incomplete=False)
        root_owner.close()


async def test_actual_empty_startup_issues_exact_binding_after_maintenance_retirement(
    tmp_path,
):
    from src.services.agent_runs.service import AgentRunService
    from src.services.agent_runs.store import AgentRunStore
    from src.services.source_ingress.reservation_store import ReservationStore
    from src.services.source_ingress.source_store_owner import SourceStoreOwner

    runs = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    agent = AgentRunService(
        store=runs, provider_factory=lambda _: pytest.fail("startup called provider")
    )
    store = ReservationStore(
        tmp_path / "sources.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        coordinator_path=runs.path.with_suffix(".coordinator.lock"),
        create=True,
    )
    owner = SourceStoreOwner(agent, store)
    root = tmp_path / "content"
    root.mkdir(mode=0o700)
    files = SnapshotFiles(root)
    await agent.start()
    try:
        owner.open()
        owner.upgrade_to_v2()
        with pytest.raises(RuntimeError):
            agent.source_storage_binding()
        assert callable(getattr(owner, "reconcile_snapshots", None)), (
            "real startup reconciliation is absent"
        )
        owner.reconcile_snapshots(files)
        binding = agent.source_storage_binding()
        assert binding.store_identity == store._identity
        assert binding.root_identity == (root.stat().st_dev, root.stat().st_ino)
        assert binding.generation == agent._generation
        assert owner._operation is None and not agent._lease._borrows
        assert files._fd is None and not files._owners
        with pytest.raises(ReservationError):
            owner.reconcile_snapshots(SnapshotFiles(root))
    finally:
        owner.close()
        files.close()
        await agent.close()


def seed_crashed_target(path, phase):
    """A real process ends without Python cleanup at the named durable boundary."""
    import json
    import subprocess
    import sys

    script = r"""
import asyncio, json, os, sys
from pathlib import Path
from tests.services.source_ingress.snapshot_fixtures import snapshot_target, snapshot_manager, receive_args
from src.services.source_ingress.snapshot_files import OwnedSnapshotFiles
from src.services.source_ingress.parser_owner import OwnedParser
from src.services.source_ingress.reservation_store import ReservationTransaction

async def main():
    async with snapshot_target(Path(sys.argv[1])) as target:
        manager=snapshot_manager(target)
        phase=sys.argv[2]
        def stop():
            os.write(1,json.dumps({"generation":target.agent._generation,"conversation_reference":target.accepted["conversation_reference"],"reservation_id":target.reservation.reservation_id}).encode()+b"\n")
            os._exit(0)
        if phase in {"claim", "creation"}:
            original=OwnedSnapshotFiles.create
            def create(files):
                if phase=="creation": original(files)
                stop()
            OwnedSnapshotFiles.create=create
        if phase=="raw_creation":
            original_open=OwnedSnapshotFiles._open_descriptor
            def open_descriptor(files,item,create):
                original_open(files,item,create)
                if create: stop()
            OwnedSnapshotFiles._open_descriptor=open_descriptor
        handle=manager.begin_receive(**receive_args(target))
        if phase=="receiving": stop()
        if phase=="append":
            manager.append_chunk(handle,**target.arguments,expected_offset=0,chunk=target.raw[:4])
            stop()
        manager.append_chunk(handle,**target.arguments,expected_offset=0,chunk=target.raw)
        if phase in {"sealed", "staged"}:
            original_phase=manager._phase
            def phase_change(owner,args,expected,state):
                result=original_phase(owner,args,expected,state)
                if state==phase: stop()
                return result
            manager._phase=phase_change
        if phase=="parser_exited":
            original_run=OwnedParser.run
            def run(parser,*args,**kwargs):
                result=original_run(parser,*args,**kwargs)
                stop()
            OwnedParser.run=run
        if phase in {"raw_fsync", "normalized_fsync"}:
            original_sync=OwnedSnapshotFiles._fsync_file
            def sync(files,item):
                original_sync(files,item)
                if item.name.endswith(".raw" if phase=="raw_fsync" else ".normalized"): stop()
            OwnedSnapshotFiles._fsync_file=sync
        if phase=="directory_fsync":
            original_verify=OwnedSnapshotFiles.verify_and_sync
            def verify(files,manifest):
                original_verify(files,manifest)
                stop()
            OwnedSnapshotFiles.verify_and_sync=verify
        if phase=="before_complete_commit":
            original_gate=manager._publish_gate
            def gate(owner):
                original_gate(owner)
                stop()
            manager._publish_gate=gate
        if phase=="complete_sql_before_return":
            original_sql=ReservationTransaction._commit_database
            def commit_sql(tx):
                terminal=tx._db.execute("SELECT COUNT(*) FROM snapshot_manifests").fetchone()[0]
                original_sql(tx)
                if terminal: stop()
            ReservationTransaction._commit_database=commit_sql
        if phase=="complete_before_response":
            original_ack=manager._acknowledge
            def ack(*args,**kwargs):
                original_ack(*args,**kwargs)
                stop()
            manager._acknowledge=ack
        if phase=="complete_pending":
            original=manager._commit
            def commit(*args,**kwargs):
                result=original(*args,**kwargs)
                if kwargs.get("terminal"): stop()
                return result
            manager._commit=commit
        manager.finish(handle,**target.arguments)
        stop()
asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), phase],
        capture_output=True,
        text=True,
        timeout=8,
        check=True,
    )
    return json.loads(result.stdout)


@asynccontextmanager
async def reopened_target(path):
    from src.services.agent_runs.service import AgentRunService
    from src.services.agent_runs.store import AgentRunStore
    from src.services.source_ingress.reservation_store import ReservationStore
    from src.services.source_ingress.source_store_owner import SourceStoreOwner

    runs = AgentRunStore(
        path / "runs.sqlite3", account_id="account-a", execution_target_id="target-a"
    )
    agent = AgentRunService(
        store=runs,
        provider_factory=lambda _: pytest.fail("recovery replayed model work"),
        connection_epoch=lambda _: "epoch-a",
    )
    store = ReservationStore(
        path / "sources.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        coordinator_path=runs.path.with_suffix(".coordinator.lock"),
    )
    owner = SourceStoreOwner(agent, store)
    files = SnapshotFiles(path / "content")
    await agent.start()
    try:
        owner.open()
        yield agent, store, owner, files
    finally:
        owner.close()
        files.close()
        await agent.close()


def durable_rows(path):
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(path / "sources.sqlite3")) as db:
        return tuple(db.execute("SELECT payload FROM source_lifecycle")), tuple(
            db.execute("SELECT payload FROM snapshot_manifests")
        )


@pytest.mark.parametrize(
    "phase",
    [
        "claim",
        "receiving",
        "append",
        "sealed",
        "parser_exited",
        "raw_fsync",
        "normalized_fsync",
        "directory_fsync",
        "staged",
        "before_complete_commit",
        "complete",
        "complete_pending",
        "complete_sql_before_return",
        "complete_before_response",
    ],
)
async def test_fresh_process_startup_resolves_durable_visibility_before_settlement(
    tmp_path, phase
):
    import json

    original = seed_crashed_target(tmp_path, phase)
    before_bytes = {p.name: p.read_bytes() for p in (tmp_path / "content").iterdir()}
    async with reopened_target(tmp_path) as (agent, store, owner, files):
        before_lifecycles, before_manifests = durable_rows(tmp_path)
        assert agent._generation > original["generation"]
        owner.reconcile_snapshots(files)
        assert agent.source_storage_binding().generation == agent._generation
        lifecycles, manifests = durable_rows(tmp_path)
        row = json.loads(lifecycles[0][0])
        assert row["generation"] == original["generation"]
        assert row["cleanup_pending"] is False
        if phase.startswith("complete"):
            assert row["state"] == "complete"
            assert manifests == before_manifests
            assert {
                p.name: p.read_bytes() for p in (tmp_path / "content").iterdir()
            } == before_bytes
        else:
            assert row["state"] == "failed" and not manifests
            assert list((tmp_path / "content").iterdir()) == []
        assert not agent._lease._borrows and owner._operation is None


@pytest.mark.parametrize("phase", ["raw_creation", "creation"])
async def test_crash_before_identity_commit_keeps_unknown_files_and_denies_startup(
    tmp_path,
    phase,
):
    seed_crashed_target(tmp_path, phase)
    before_bytes = {p.name: p.read_bytes() for p in (tmp_path / "content").iterdir()}
    async with reopened_target(tmp_path) as (agent, store, owner, files):
        before_rows = durable_rows(tmp_path)
        with pytest.raises(ReservationError):
            owner.reconcile_snapshots(files)
        with pytest.raises(RuntimeError):
            agent.source_storage_binding()
        assert {
            p.name: p.read_bytes() for p in (tmp_path / "content").iterdir()
        } == before_bytes
        # Owner still holds SQL, so use its captured connection for observation.
        assert (
            tuple(
                tuple(row)
                for row in owner._operation.transaction._db.execute(
                    "SELECT payload FROM source_lifecycle"
                )
            )
            == before_rows[0]
        )


async def test_manager_requires_real_startup_before_opening_or_admitting_work(tmp_path):
    from src.services.source_ingress.snapshots import SourceSnapshotManager
    from tests.services.source_ingress.snapshot_fixtures import snapshot_target

    async with snapshot_target(tmp_path, startup=False) as target:
        manager = SourceSnapshotManager(
            target.agent,
            target.metadata,
            target.authority,
            target.root,
            expected_target_fingerprint="fingerprint-a",
        )
        target.managers.append(manager)
        with pytest.raises(ReservationError):
            manager.open()
        assert manager._root._fd is None
        assert not target.agent._lease._source_tagged_ever


async def test_ready_manager_and_owned_parser_use_the_same_storage_binding(tmp_path):
    from tests.services.source_ingress.snapshot_fixtures import (
        receive_args,
        snapshot_manager,
        snapshot_target,
    )

    async with snapshot_target(tmp_path) as target:
        binding = target.agent.source_storage_binding()
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        result = manager.finish(handle, **target.arguments)
        assert result.row_count == 1 and result.column_count == 2
        assert target.agent.source_storage_binding() is binding
        assert handle._resources_retired


@pytest.mark.parametrize("after", [False, True])
async def test_unknown_recovery_commit_preserves_complete_bytes_for_a_new_owner(
    tmp_path, monkeypatch, after
):
    from src.services.source_ingress.reservation_store import ReservationTransaction

    seed_crashed_target(tmp_path, "complete_pending")
    before_files = {p.name: p.read_bytes() for p in (tmp_path / "content").iterdir()}
    original = ReservationTransaction._commit_database

    def commit(tx):
        if after:
            original(tx)
        raise OSError("PRIVATE_COMMIT_CANARY")

    async with reopened_target(tmp_path) as (agent, store, owner, files):
        before_life, before_manifests = durable_rows(tmp_path)
        with monkeypatch.context() as patch:
            patch.setattr(ReservationTransaction, "_commit_database", commit)
            with pytest.raises(ReservationError):
                owner.reconcile_snapshots(files)
        assert owner._operation.commit_attempted and not owner._operation.commit_known
        assert not owner._operation.original_token.retirement_completed
        with pytest.raises(RuntimeError):
            agent.source_storage_binding()
        assert {
            p.name: p.read_bytes() for p in (tmp_path / "content").iterdir()
        } == before_files
    assert durable_rows(tmp_path)[1] == before_manifests
    async with reopened_target(tmp_path) as (agent, store, owner, files):
        owner.reconcile_snapshots(files)
        assert agent.source_storage_binding()
    assert durable_rows(tmp_path)[1] == before_manifests
    assert {
        p.name: p.read_bytes() for p in (tmp_path / "content").iterdir()
    } == before_files


@pytest.mark.parametrize("phase", ["root_retirement", "ready_transition"])
async def test_startup_never_renews_its_deadline_across_final_retirement(
    tmp_path, monkeypatch, phase
):
    import time

    seed_crashed_target(tmp_path, "complete")
    async with reopened_target(tmp_path) as (agent, store, owner, files):
        before = durable_rows(tmp_path)
        offset = [0]
        owner._monotonic = lambda: time.monotonic() + offset[0]
        if phase == "root_retirement":
            original = files.close

            def close():
                original()
                offset[0] = 3

            monkeypatch.setattr(files, "close", close)
        else:
            original = owner._publish_startup

            def publish(operation):
                original(operation)
                offset[0] = 3

            monkeypatch.setattr(owner, "_publish_startup", publish)
        with pytest.raises(ReservationError):
            owner.reconcile_snapshots(files)
        assert owner._operation.original_token.retirement_completed
        with pytest.raises(RuntimeError):
            agent.source_storage_binding()
        assert durable_rows(tmp_path) == before


async def test_current_generation_lifecycle_denies_before_any_owned_file_deletion(
    tmp_path,
):
    import json
    import sqlite3
    from contextlib import closing

    original = seed_crashed_target(tmp_path, "receiving")
    with closing(sqlite3.connect(tmp_path / "sources.sqlite3")) as db:
        row = json.loads(
            db.execute("SELECT payload FROM source_lifecycle").fetchone()[0]
        )
        row["generation"] = original["generation"] + 1
        payload = json.dumps(
            row, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        db.execute(
            "UPDATE source_lifecycle SET payload=?,metadata_bytes=?",
            (payload, len(payload.encode()) + 40),
        )
        db.commit()
    before = {p.name: p.read_bytes() for p in (tmp_path / "content").iterdir()}
    async with reopened_target(tmp_path) as (agent, store, owner, files):
        with pytest.raises(ReservationError):
            owner.reconcile_snapshots(files)
        assert not owner._operation.files
        assert {
            p.name: p.read_bytes() for p in (tmp_path / "content").iterdir()
        } == before


async def test_completed_reopen_reads_original_values_after_upload_expiry(tmp_path):
    import json

    from src.services.source_ingress.reservation_contracts import SourceOperatorContext
    from src.services.source_ingress.snapshots import SourceSnapshotManager
    from tests.services.source_ingress.reservation_fixtures import SQLiteSourceAuthority

    seed = seed_crashed_target(tmp_path, "complete")
    async with reopened_target(tmp_path) as (agent, store, owner, files):
        life, manifests = durable_rows(tmp_path)
        attempt = json.loads(life[0][0])
        manifest = json.loads(manifests[0][0])
        now = attempt["authorization_expires_at"] + 1
        owner.reconcile_snapshots(files)
        authority = SQLiteSourceAuthority(tmp_path / "authority.sqlite3", create=False)
        authority.mutate(expires=now + 300)
        manager = SourceSnapshotManager(
            agent,
            store,
            authority,
            tmp_path / "content",
            expected_target_fingerprint="fingerprint-a",
            clock=lambda: now,
        )
        try:
            manager.open()
            arguments = {
                "operator_context": SourceOperatorContext("operator-a"),
                "provider_connection_id": "connection-a",
                "conversation_reference": seed["conversation_reference"],
                "request_key": "source-a",
                "private_snapshot_id": manifest["snapshot_id"],
            }
            value = manager.read_private_snapshot(**arguments)
            assert value.rows == (("00123", "line1\nline2"),)
            receipt = manager.describe_snapshot(**arguments)
            assert receipt.source_expires_at == manifest["source_expires_at"]
            manager._clock = lambda: float(manifest["source_expires_at"])
            authority.mutate(expires=manifest["source_expires_at"] + 300)
            with pytest.raises(ReservationError):
                manager.read_private_snapshot(**arguments)
        finally:
            manager.close()


async def test_losing_startup_owner_cannot_quarantine_ready_winner_on_reject_or_close(
    tmp_path,
):
    from src.services.source_ingress.reservation_store import ReservationStore
    from src.services.source_ingress.source_store_owner import SourceStoreOwner
    from tests.services.source_ingress.snapshot_fixtures import (
        receive_args,
        snapshot_manager,
        snapshot_target,
    )

    async with snapshot_target(tmp_path) as target:
        binding = target.agent.source_storage_binding()
        other_store = ReservationStore(
            target.metadata.path,
            account_id="account-a",
            execution_target_id="target-a",
            coordinator_path=target.metadata.coordinator_path,
        )
        loser = SourceStoreOwner(target.agent, other_store)
        loser_files = SnapshotFiles(target.root)
        try:
            loser.open()
            with pytest.raises(ReservationError):
                loser.reconcile_snapshots(loser_files)
            assert loser_files._fd is None and not loser_files._attempted
            assert target.agent.source_storage_binding() is binding
        finally:
            loser.close()
            loser_files.close()
        assert target.agent.source_storage_binding() is binding
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        assert manager.abort(handle, **target.arguments).status == "aborted"


@pytest.mark.parametrize("after", [False, True])
async def test_known_complete_manifest_survives_failed_startup_checkpoint_retirement(
    tmp_path, monkeypatch, after
):
    from src.services.source_ingress.reservation_store import ReservationTransaction

    seed_crashed_target(tmp_path, "complete_pending")
    before_files = {p.name: p.read_bytes() for p in (tmp_path / "content").iterdir()}
    original = ReservationTransaction._close_database

    def close(tx):
        if after:
            original(tx)
        raise OSError("PRIVATE_RETIRE_CANARY")

    async with reopened_target(tmp_path) as (agent, store, owner, files):
        before_manifests = durable_rows(tmp_path)[1]
        with monkeypatch.context() as patch:
            patch.setattr(ReservationTransaction, "_close_database", close)
            with pytest.raises(ReservationError):
                owner.reconcile_snapshots(files)
        assert owner._operation.commit_known
        assert not owner._operation.original_token.retirement_completed
        with pytest.raises(RuntimeError):
            agent.source_storage_binding()
        assert {
            p.name: p.read_bytes() for p in (tmp_path / "content").iterdir()
        } == before_files
    assert durable_rows(tmp_path)[1] == before_manifests
    async with reopened_target(tmp_path) as (agent, store, owner, files):
        owner.reconcile_snapshots(files)
        assert agent.source_storage_binding()
    assert durable_rows(tmp_path)[1] == before_manifests


async def test_startup_settlement_proof_denies_copies_wrong_transaction_and_wrong_row(
    tmp_path, monkeypatch
):
    from copy import copy

    from src.services.source_ingress.snapshot_store import SnapshotTransaction

    seed_crashed_target(tmp_path, "receiving")
    original = SnapshotTransaction.reconcile_retirement
    attempts = []

    def settle(snapshot, attempt, *, proof):
        attempts.append(attempt)
        with pytest.raises(ReservationError):
            original(snapshot, attempt, proof=copy(proof))
        with pytest.raises(ReservationError):
            original(snapshot, replace(attempt, reservation_id="f" * 32), proof=proof)
        with pytest.raises(ReservationError):
            original(SnapshotTransaction(copy(snapshot._tx)), attempt, proof=proof)
        file_owner = proof._files
        proof._files = copy(file_owner)
        try:
            with pytest.raises(ReservationError):
                original(snapshot, attempt, proof=proof)
        finally:
            proof._files = file_owner
        return original(snapshot, attempt, proof=proof)

    async with reopened_target(tmp_path) as (agent, store, owner, files):
        monkeypatch.setattr(SnapshotTransaction, "reconcile_retirement", settle)
        owner.reconcile_snapshots(files)
        assert attempts and agent.source_storage_binding()


async def test_same_store_object_cannot_gain_a_second_maintenance_owner(tmp_path):
    from src.services.source_ingress.source_store_owner import SourceStoreOwner
    from tests.services.source_ingress.snapshot_fixtures import (
        receive_args,
        snapshot_manager,
        snapshot_target,
    )

    async with snapshot_target(tmp_path) as target:
        binding = target.agent.source_storage_binding()
        with pytest.raises(ReservationError):
            SourceStoreOwner(target.agent, target.metadata)
        assert target.agent.source_storage_binding() is binding
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        assert manager.abort(handle, **target.arguments).status == "aborted"


async def test_copied_store_is_rejected_before_its_maintenance_mutex(tmp_path):
    from copy import copy

    from src.services.source_ingress.reservation_store import ReservationStore
    from src.services.source_ingress.source_store_owner import SourceStoreOwner
    from tests.services.source_ingress.snapshot_fixtures import snapshot_target

    async with snapshot_target(tmp_path) as target:
        unused = ReservationStore(
            tmp_path / "unused.sqlite3",
            account_id="account-a",
            execution_target_id="target-a",
            coordinator_path=target.metadata.coordinator_path,
        )

        class ForbiddenMutex:
            def __enter__(self):
                pytest.fail("copied store reached inherited mutex")

            def __exit__(self, *args):
                pass

        unused._maintenance_lock = ForbiddenMutex()
        with pytest.raises(ReservationError):
            SourceStoreOwner(target.agent, copy(unused))
        assert not unused.path.exists()


async def qualify_reopened_capacity(path):
    import time

    before_rows = durable_rows(path)
    before_files = {
        p.name: (p.stat().st_ino, p.read_bytes()) for p in (path / "content").iterdir()
    }
    async with reopened_target(path) as (agent, store, owner, files):
        start = time.monotonic()
        owner.reconcile_snapshots(files)
        assert time.monotonic() - start < 2
        assert agent.source_storage_binding()
    assert durable_rows(path) == before_rows
    assert {
        p.name: (p.stat().st_ino, p.read_bytes()) for p in (path / "content").iterdir()
    } == before_files


@pytest.mark.parametrize(
    ("phase", "completed"),
    [
        ("first_unlink", False),
        ("before_commit", False),
        ("after_commit", False),
        ("before_commit", True),
        ("after_commit", True),
    ],
)
async def test_recovery_process_death_preserves_visibility_and_retries_only_cleanup(
    tmp_path, phase, completed
):
    import json
    import subprocess
    import sys

    original = seed_crashed_target(
        tmp_path, "complete_pending" if completed else "append"
    )
    before_files = {p.name: p.read_bytes() for p in (tmp_path / "content").iterdir()}
    script = r"""
import asyncio, os, sys
from pathlib import Path
from tests.services.source_ingress.test_snapshot_recovery import reopened_target, durable_rows
from src.services.source_ingress.reservation_store import ReservationTransaction
from src.services.source_ingress.snapshot_files import OwnedSnapshotFiles
async def main():
    async with reopened_target(Path(sys.argv[1])) as (_,_,owner,files):
        # The real maintenance owner has already performed the first SQLite open.
        print(repr(durable_rows(Path(sys.argv[1]))[1]), flush=True)
        if sys.argv[2] == "first_unlink":
            original=OwnedSnapshotFiles._unlink_file
            def unlink(self,item):
                original(self,item)
                os._exit(0)
            OwnedSnapshotFiles._unlink_file=unlink
        else:
            original=ReservationTransaction._commit_database
            def commit(self):
                if sys.argv[2] == "after_commit":
                    original(self)
                os._exit(0)
            ReservationTransaction._commit_database=commit
        owner.reconcile_snapshots(files)
        raise AssertionError("recovery death barrier was not reached")
asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), phase],
        capture_output=True,
        text=True,
        timeout=6,
        check=True,
    )
    import ast

    original_manifests = ast.literal_eval(result.stdout)
    async with reopened_target(tmp_path) as (agent, store, owner, files):
        assert agent._generation > original["generation"] + 1
        owner.reconcile_snapshots(files)
        assert agent.source_storage_binding()
        rows, manifests = durable_rows(tmp_path)
        lifecycle = json.loads(rows[0][0])
        assert lifecycle["generation"] == original["generation"]
        assert not lifecycle["cleanup_pending"]
        assert manifests == original_manifests
        if completed:
            assert lifecycle["state"] == "complete"
            assert {
                p.name: p.read_bytes() for p in (tmp_path / "content").iterdir()
            } == before_files
        else:
            assert lifecycle["state"] == "failed"
            assert not list((tmp_path / "content").iterdir())


async def test_forked_store_rejects_before_inherited_locked_maintenance_mutex(tmp_path):
    import select
    import signal

    from src.services.source_ingress.reservation_store import ReservationStore
    from src.services.source_ingress.source_store_owner import SourceStoreOwner
    from tests.services.source_ingress.snapshot_fixtures import snapshot_target

    async with snapshot_target(tmp_path) as target:
        unused = ReservationStore(
            tmp_path / "unused.sqlite3",
            account_id="account-a",
            execution_target_id="target-a",
            coordinator_path=target.metadata.coordinator_path,
        )
        read_fd, write_fd = os.pipe()
        with unused._maintenance_lock:
            pid = os.fork()
            if pid == 0:
                os.close(read_fd)
                try:
                    SourceStoreOwner(target.agent, unused)
                except ReservationError:
                    os.write(write_fd, b"denied")
                    os._exit(0)
                os._exit(2)
            os.close(write_fd)
            waited = False
            try:
                assert select.select([read_fd], [], [], 2)[0]
                assert os.read(read_fd, 64) == b"denied"
                _, status = os.waitpid(pid, 0)
                waited = True
                assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
                assert not unused.path.exists()
            finally:
                if not waited:
                    os.kill(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)
                os.close(read_fd)


@pytest.mark.skipif(
    not hasattr(os, "pidfd_open"), reason="qualified Linux process identity"
)
async def test_actual_surviving_parser_excludes_startup_after_parent_death(tmp_path):
    import json
    import select
    import signal
    import subprocess
    import sys

    from src.services.agent_runs.coordinator import CoordinatorLease

    script = r"""
import asyncio, json, os, signal, sys
from pathlib import Path
from tests.services.source_ingress.snapshot_fixtures import snapshot_target, snapshot_manager, receive_args
from src.services.source_ingress.parser_owner import OwnedParser
async def main():
    async with snapshot_target(Path(sys.argv[1])) as target:
        manager=snapshot_manager(target)
        handle=manager.begin_receive(**receive_args(target))
        manager.append_chunk(handle, **target.arguments, expected_offset=0, chunk=target.raw)
        original=OwnedParser._spawn
        def spawn(parser, files, request):
            original(parser,files,request)
            os.kill(parser._child.pid, signal.SIGSTOP)
            pid,status=os.waitpid(parser._child.pid,os.WUNTRACED)
            assert pid==parser._child.pid and os.WIFSTOPPED(status)
            print(json.dumps({"child":pid}),flush=True)
            assert sys.stdin.readline().strip()=="never"
        OwnedParser._spawn=spawn
        manager.finish(handle, **target.arguments)
asyncio.run(main())
"""
    parent = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child_fd = None
    provider = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ready, _, _ = select.select([parent.stdout], [], [], 6)
        assert ready, "owned parent did not reach the fixed-child barrier"
        line = parent.stdout.readline()
        assert line, parent.stderr.read()
        child_fd = os.pidfd_open(json.loads(line)["child"])
        parent.kill()
        parent.wait(timeout=2)
        assert not select.select([child_fd], [], [], 0)[0]
        with pytest.raises(RuntimeError):
            CoordinatorLease(tmp_path / "runs.coordinator.lock")
        assert provider.poll() is None
        assert len(list((tmp_path / "content").iterdir())) == 2
        signal.pidfd_send_signal(child_fd, signal.SIGCONT)
        assert select.select([child_fd], [], [], 6)[0], (
            "fixed child did not actually exit"
        )
        async with reopened_target(tmp_path) as (agent, store, owner, files):
            owner.reconcile_snapshots(files)
            assert agent.source_storage_binding()
            assert list((tmp_path / "content").iterdir()) == []
        assert provider.poll() is None
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=2)
        for stream in (parent.stdin, parent.stdout, parent.stderr):
            stream.close()
        if child_fd is not None:
            if not select.select([child_fd], [], [], 0)[0]:
                signal.pidfd_send_signal(child_fd, signal.SIGKILL)
                assert select.select([child_fd], [], [], 2)[0]
            os.close(child_fd)
        provider.terminate()
        provider.wait(timeout=2)
