"""Cancellation and durable visibility have one explicit winner."""

import concurrent.futures
import json
import sqlite3
import threading
from contextlib import closing

import pytest

from src.services.source_ingress.reservation_contracts import ReservationError
from src.services.source_ingress.reservation_store import ReservationTransaction
from tests.services.source_ingress.snapshot_fixtures import (
    receive_args,
    snapshot_manager,
    snapshot_target,
)


async def test_authorized_abort_wins_during_prepublication_file_work(
    tmp_path, monkeypatch
):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        entered, release = threading.Event(), threading.Event()
        original = handle._files.verify_and_sync

        def blocked(manifest):
            original(manifest)
            entered.set()
            assert release.wait(3)

        monkeypatch.setattr(handle._files, "verify_and_sync", blocked)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(manager.finish, handle, **target.arguments)
            try:
                assert entered.wait(2)
                with pytest.raises(ReservationError):
                    manager.abort(handle, **target.arguments)
                assert handle._cancelled
                assert not handle._borrow.retirement_completed
                assert len(list(target.root.iterdir())) == 2
            finally:
                release.set()
            with pytest.raises(ReservationError):
                future.result(timeout=3)
        assert handle._borrow.retirement_completed and list(target.root.iterdir()) == []
        with closing(sqlite3.connect(target.metadata.path)) as db:
            assert db.execute("SELECT COUNT(*) FROM snapshot_manifests").fetchone() == (
                0,
            )


async def test_commit_admission_wins_and_late_abort_cannot_delete(
    tmp_path, monkeypatch
):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        entered, release = threading.Event(), threading.Event()
        original = manager._publish_gate

        def blocked(owner):
            original(owner)
            entered.set()
            assert release.wait(3)

        monkeypatch.setattr(manager, "_publish_gate", blocked)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(manager.finish, handle, **target.arguments)
            try:
                assert entered.wait(2)
                with pytest.raises(ReservationError):
                    manager.abort(handle, **target.arguments)
                assert handle._protected and not handle._borrow.retirement_completed
            finally:
                release.set()
            result = future.result(timeout=3)
        before = {p.name: p.read_bytes() for p in target.root.iterdir()}
        with pytest.raises(ReservationError):
            manager.abort(handle, **target.arguments)
        assert manager.begin_receive(**receive_args(target)) == result
        assert {p.name: p.read_bytes() for p in target.root.iterdir()} == before


@pytest.mark.parametrize("after", [False, True])
async def test_unknown_terminal_commit_retains_candidate_and_capacity(
    tmp_path, monkeypatch, after
):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        original = ReservationTransaction._commit_database

        def interrupted(transaction):
            if handle._commit_admitted and not handle._published:
                if after:
                    original(transaction)
                raise RuntimeError("PRIVATE_COMMIT_CANARY")
            return original(transaction)

        with monkeypatch.context() as patch:
            patch.setattr(ReservationTransaction, "_commit_database", interrupted)
            with pytest.raises(ReservationError) as caught:
                manager.finish(handle, **target.arguments)
        assert "PRIVATE_" not in str(caught.value)
        assert handle._last_commit == (True, False)
        assert handle._protected and handle._uncertain
        assert len(list(target.root.iterdir())) == 2
        with pytest.raises(ReservationError):
            manager.begin_receive(**receive_args(target))
        with closing(sqlite3.connect(target.metadata.path)) as db:
            assert db.execute("SELECT COUNT(*) FROM snapshot_manifests").fetchone() == (
                int(after),
            )
            state = json.loads(
                db.execute("SELECT payload FROM source_lifecycle").fetchone()[0]
            )
            assert state["cleanup_pending"] is True
        assert len(target.providers) == 1


async def test_completed_recovery_checks_current_grant_after_owner_retirement(
    tmp_path, monkeypatch
):
    import time

    from src.services.source_ingress.snapshots import ReceiverHandle

    now = [int(time.time())]
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target, clock=lambda: now[0])
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        expected = manager.finish(handle, **target.arguments)
        target.authority.mutate(expires=now[0] + 3)
        original = ReceiverHandle._cleanup

        def expires_after_cleanup(owner):
            original(owner)
            if owner._manifest is not None and owner._files is None:
                now[0] += 4

        with monkeypatch.context() as patch:
            patch.setattr(ReceiverHandle, "_cleanup", expires_after_cleanup)
            with pytest.raises(ReservationError):
                manager.begin_receive(**receive_args(target))
        target.authority.mutate(expires=now[0] + 30)
        assert manager.begin_receive(**receive_args(target)) == expected


async def test_retired_claim_proof_cannot_be_copied_to_clear_capacity(
    tmp_path, monkeypatch
):
    import copy

    from src.services.source_ingress.snapshot_store import SnapshotTransaction

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        original = SnapshotTransaction.acknowledge_retirement

        def copied(scope, attempt, *, generation, retirement_proof):
            return original(
                scope,
                attempt,
                generation=generation,
                retirement_proof=copy.copy(retirement_proof),
            )

        with monkeypatch.context() as patch:
            patch.setattr(SnapshotTransaction, "acknowledge_retirement", copied)
            with pytest.raises(ReservationError):
                manager.finish(handle, **target.arguments)
        assert (
            handle._published
            and handle._resources_retired
            and handle._attempt.cleanup_pending
        )
        before = {p.name: p.read_bytes() for p in target.root.iterdir()}
        manager._acknowledge(handle, target.arguments)
        assert not handle._attempt.cleanup_pending
        assert {p.name: p.read_bytes() for p in target.root.iterdir()} == before


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("control", [False, True])
async def test_final_receiver_token_interruption_preserves_known_completion(
    tmp_path,
    monkeypatch,
    after,
    control,
):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        original = handle._borrow.retire

        def interrupted():
            if after:
                original()
            if control:
                raise KeyboardInterrupt("PRIVATE_RETIRE_CANARY")
            raise RuntimeError("PRIVATE_RETIRE_CANARY")

        with monkeypatch.context() as patch:
            patch.setattr(handle._borrow, "retire", interrupted)
            with pytest.raises(KeyboardInterrupt if control else ReservationError):
                manager.finish(handle, **target.arguments)
        assert handle._published and handle._attempt.cleanup_pending
        assert handle._borrow.retirement_completed is after
        assert handle._resources_retired is after
        before = {p.name: p.read_bytes() for p in target.root.iterdir()}
        if after:
            assert (
                manager.begin_receive(**receive_args(target)).snapshot_id
                == handle._manifest.snapshot_id
            )
        else:
            with pytest.raises(ReservationError):
                manager.begin_receive(**receive_args(target))
        manager.close()
        assert {p.name: p.read_bytes() for p in target.root.iterdir()} == before


@pytest.mark.parametrize("after", [False, True])
async def test_unknown_retirement_ack_commit_keeps_known_manifest(
    tmp_path, monkeypatch, after
):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        original = ReservationTransaction._commit_database

        def interrupted(transaction):
            if handle._published and handle._resources_retired:
                if after:
                    original(transaction)
                raise RuntimeError("PRIVATE_ACK_CANARY")
            return original(transaction)

        with monkeypatch.context() as patch:
            patch.setattr(ReservationTransaction, "_commit_database", interrupted)
            with pytest.raises(ReservationError):
                manager.finish(handle, **target.arguments)
        assert handle._published and handle._resources_retired
        before = {p.name: p.read_bytes() for p in target.root.iterdir()}
        manager.close()
        with closing(sqlite3.connect(target.metadata.path)) as db:
            assert db.execute("SELECT COUNT(*) FROM snapshot_manifests").fetchone() == (
                1,
            )
            row = json.loads(
                db.execute("SELECT payload FROM source_lifecycle").fetchone()[0]
            )
            assert row["state"] == "complete"
            assert row["cleanup_pending"] is (not after)
        assert {p.name: p.read_bytes() for p in target.root.iterdir()} == before


async def test_truncated_completed_file_is_not_acknowledged_as_available(tmp_path):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        manager.finish(handle, **target.arguments)
        path = target.root / handle._attempt.normalized_basename
        original = path.read_bytes()
        path.write_bytes(original[:-1])
        with pytest.raises(ReservationError):
            manager.begin_receive(**receive_args(target))
        assert path.read_bytes() == original[:-1]  # Audit performs no repair.


@pytest.mark.parametrize(
    "field,value",
    [("_aborting", True), ("_retiring", True), ("_abort_fence", object())],
)
async def test_cleanup_proof_denies_pending_abort_or_retirement(
    tmp_path, monkeypatch, field, value
):
    from src.services.source_ingress.snapshot_store import SnapshotTransaction

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        original = SnapshotTransaction.acknowledge_retirement

        def pending(scope, attempt, *, generation, retirement_proof):
            old = getattr(handle, field)
            setattr(handle, field, value)
            try:
                return original(
                    scope,
                    attempt,
                    generation=generation,
                    retirement_proof=retirement_proof,
                )
            finally:
                setattr(handle, field, old)

        with monkeypatch.context() as patch:
            patch.setattr(SnapshotTransaction, "acknowledge_retirement", pending)
            with pytest.raises(ReservationError):
                manager.finish(handle, **target.arguments)
        assert handle._published and handle._attempt.cleanup_pending
        manager._acknowledge(handle, target.arguments)
        assert not handle._attempt.cleanup_pending


async def test_failed_call_cleanup_cannot_retire_a_successor_inflight_action(
    tmp_path, monkeypatch
):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        cleanup_entered, cleanup_release = threading.Event(), threading.Event()
        write_entered, write_release = threading.Event(), threading.Event()
        original_cleanup, original_append = (
            manager._failed_cleanup,
            handle._files.append,
        )
        first = [True]

        def delayed_cleanup(owner, arguments):
            if first[0]:
                first[0] = False
                cleanup_entered.set()
                assert cleanup_release.wait(3)
            return original_cleanup(owner, arguments)

        def delayed_append(**kwargs):
            original_append(**kwargs)
            write_entered.set()
            assert write_release.wait(3)

        monkeypatch.setattr(manager, "_failed_cleanup", delayed_cleanup)
        monkeypatch.setattr(handle._files, "append", delayed_append)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            failed = pool.submit(
                manager.append_chunk,
                handle,
                **target.arguments,
                expected_offset=1,
                chunk=b"x",
            )
            try:
                assert cleanup_entered.wait(2)
                writing = pool.submit(
                    manager.append_chunk,
                    handle,
                    **target.arguments,
                    expected_offset=0,
                    chunk=target.raw,
                )
                assert write_entered.wait(2)
                cleanup_release.set()
                with pytest.raises(ReservationError):
                    failed.result(timeout=2)
                assert not handle._retirement_failed
                assert not handle._borrow.retirement_completed
                handle._borrow.require_source_usable()
                assert len(list(target.root.iterdir())) == 2
            finally:
                cleanup_release.set()
                write_release.set()
            with pytest.raises(ReservationError):
                writing.result(timeout=3)
        assert handle._borrow.retirement_completed
        assert list(target.root.iterdir()) == []


@pytest.mark.parametrize("after", [False, True])
async def test_retained_audit_scan_can_retire_before_receiver_token(
    tmp_path, monkeypatch, after
):
    import os

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        original = os.scandir
        fail = [True]

        class CapturedScan:
            def __init__(self, fd):
                self.scan = original(fd)

            def __iter__(self):
                return iter(self.scan)

            def close(self):
                if fail[0]:
                    if after:
                        self.scan.close()
                    raise RuntimeError("PRIVATE_SCAN_CLOSE_CANARY")
                self.scan.close()

        with monkeypatch.context() as patch:
            patch.setattr(os, "scandir", CapturedScan)
            with pytest.raises(ReservationError):
                manager.append_chunk(
                    handle, **target.arguments, expected_offset=0, chunk=target.raw
                )
        assert manager._root._scan is not None
        assert not handle._borrow.retirement_completed
        fail[0] = False
        manager.close()
        assert manager._root._scan is None
        assert handle._borrow.retirement_completed
        assert list(target.root.iterdir()) == []


@pytest.mark.parametrize("boundary", ["commit", "files", "token"])
async def test_expiry_after_publication_preserves_completion_without_live_response(
    tmp_path, monkeypatch, boundary
):
    import time

    now = [int(time.time())]
    async with snapshot_target(tmp_path) as target:
        target.authority.mutate(expires=now[0] + 3)
        manager = snapshot_manager(target, clock=lambda: now[0])
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        if boundary == "commit":
            original = ReservationTransaction._commit_database

            def late(transaction):
                original(transaction)
                if handle._commit_admitted:
                    now[0] += 4

            monkeypatch.setattr(ReservationTransaction, "_commit_database", late)
        elif boundary == "files":
            original = handle._files.retire

            def late(**kwargs):
                original(**kwargs)
                now[0] += 4

            monkeypatch.setattr(handle._files, "retire", late)
        else:
            original = handle._borrow.retire

            def late():
                original()
                now[0] += 4

            monkeypatch.setattr(handle._borrow, "retire", late)
        with pytest.raises(ReservationError):
            manager.finish(handle, **target.arguments)
        assert handle._published and handle._resources_retired
        assert handle._attempt.cleanup_pending
        before = {p.name: p.read_bytes() for p in target.root.iterdir()}
        target.authority.mutate(expires=now[0] + 30)
        assert (
            manager.begin_receive(**receive_args(target)).snapshot_id
            == handle._manifest.snapshot_id
        )
        assert {p.name: p.read_bytes() for p in target.root.iterdir()} == before


@pytest.mark.parametrize("deny", ["closing", "quarantine", "revocation"])
async def test_lost_admission_before_cleanup_ack_never_downgrades_known_manifest(
    tmp_path, monkeypatch, deny
):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        original = manager._acknowledge

        def lost(owner, arguments):
            assert owner._borrow.retirement_completed
            if deny == "closing":
                target.agent._lease.begin_close()
            elif deny == "quarantine":
                borrow, _ = target.agent.borrow_coordinator()
                borrow.quarantine()
                borrow.retire()
            else:
                target.authority.mutate(enabled=0)
            return original(owner, arguments)

        monkeypatch.setattr(manager, "_acknowledge", lost)
        with pytest.raises(ReservationError):
            manager.finish(handle, **target.arguments)
        assert handle._published and handle._resources_retired
        before = {p.name: p.read_bytes() for p in target.root.iterdir()}
        manager.close()
        with closing(sqlite3.connect(target.metadata.path)) as db:
            row = json.loads(
                db.execute("SELECT payload FROM source_lifecycle").fetchone()[0]
            )
            assert row["state"] == "complete" and row["cleanup_pending"]
            assert db.execute("SELECT COUNT(*) FROM snapshot_manifests").fetchone() == (
                1,
            )
        assert {p.name: p.read_bytes() for p in target.root.iterdir()} == before


async def test_sibling_audit_defers_cleanup_without_quarantining_shared_lease(
    tmp_path, monkeypatch
):
    import os
    from dataclasses import replace

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        first = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            first, **target.arguments, expected_offset=0, chunk=target.raw
        )
        request = replace(target.request, request_key="sibling")
        reservation = target.coordinator.reserve(**target.arguments, request=request)
        second = manager.begin_receive(
            **target.arguments,
            request_key=request.request_key,
            reservation_id=reservation.reservation_id,
        )
        files_done, cleanup_go = threading.Event(), threading.Event()
        audit_active, audit_go = threading.Event(), threading.Event()
        original_retire = first._files.retire
        original_scan = os.scandir

        def delayed_retire(**kwargs):
            original_retire(**kwargs)
            files_done.set()
            assert cleanup_go.wait(3)

        class HeldScan:
            def __init__(self, fd):
                self.scan = original_scan(fd)

            def __iter__(self):
                audit_active.set()
                assert audit_go.wait(3)
                return iter(self.scan)

            def close(self):
                self.scan.close()

        monkeypatch.setattr(first._files, "retire", delayed_retire)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            completing = pool.submit(manager.finish, first, **target.arguments)
            try:
                assert files_done.wait(2)
                with monkeypatch.context() as patch:
                    patch.setattr(os, "scandir", HeldScan)
                    appending = pool.submit(
                        manager.append_chunk,
                        second,
                        **target.arguments,
                        expected_offset=0,
                        chunk=target.raw,
                    )
                    assert audit_active.wait(2)
                    cleanup_go.set()
                    with pytest.raises(ReservationError):
                        completing.result(timeout=2)
                    assert first._published and not first._resources_retired
                    assert not first._retirement_failed
                    second._borrow.require_source_usable()
                    audit_go.set()
                    appending.result(timeout=2)
            finally:
                cleanup_go.set()
                audit_go.set()
        assert manager.finish(second, **target.arguments).row_count == 1
        before = {p.name: p.read_bytes() for p in target.root.iterdir()}
        manager.close()
        assert first._borrow.retirement_completed
        assert {p.name: p.read_bytes() for p in target.root.iterdir()} == before


@pytest.mark.parametrize("operation", ["finish", "abort"])
@pytest.mark.parametrize("clock", ["_clock", "_monotonic"])
@pytest.mark.parametrize("control", [False, True])
async def test_final_response_clock_failure_is_closed_without_erasing_durable_outcome(
    tmp_path,
    monkeypatch,
    operation,
    clock,
    control,
):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        original = manager._acknowledge

        def failed_clock():
            if control:
                raise KeyboardInterrupt("PRIVATE_FINAL_CLOCK_CANARY")
            raise RuntimeError("PRIVATE_FINAL_CLOCK_CANARY")

        def acknowledged(owner, arguments):
            original(owner, arguments)
            assert owner._resources_retired and not owner._attempt.cleanup_pending
            monkeypatch.setattr(manager, clock, failed_clock)

        monkeypatch.setattr(manager, "_acknowledge", acknowledged)
        with pytest.raises(
            KeyboardInterrupt if control else ReservationError
        ) as caught:
            getattr(manager, operation)(handle, **target.arguments)
        if not control:
            assert "PRIVATE_" not in str(caught.value)
        assert handle._resources_retired and not handle._attempt.cleanup_pending
        with closing(sqlite3.connect(target.metadata.path)) as db:
            row = json.loads(
                db.execute("SELECT payload FROM source_lifecycle").fetchone()[0]
            )
            assert row["state"] == ("complete" if operation == "finish" else "failed")
            assert row["cleanup_pending"] is False
            assert db.execute("SELECT COUNT(*) FROM snapshot_manifests").fetchone() == (
                int(operation == "finish"),
            )
        assert len(list(target.root.iterdir())) == (2 if operation == "finish" else 0)
