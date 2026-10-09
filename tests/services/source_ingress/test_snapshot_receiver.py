"""Private reception commits one immutable snapshot under real held fences."""

import hashlib
import importlib.util
import json
import sqlite3
from contextlib import closing

import pytest

from src.services.source_ingress.reservation_contracts import ReservationError
from tests.services.source_ingress.snapshot_fixtures import (
    receive_args,
    snapshot_manager,
    snapshot_target,
)


async def test_real_receive_finish_and_recovery_preserve_original_identity(tmp_path):
    assert (
        importlib.util.find_spec("src.services.source_ingress.snapshots") is not None
    ), "private chunk receiver is absent"
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        with closing(sqlite3.connect(target.agent.store.path)) as db:
            before = list(db.iterdump())
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw[:7]
        )
        manager.append_chunk(
            handle, **target.arguments, expected_offset=7, chunk=target.raw[7:]
        )
        first = manager.finish(handle, **target.arguments)
        second = manager.begin_receive(**receive_args(target))
        assert first == second
        assert first.snapshot_id != target.reservation.reservation_id
        assert (
            first.source_expires_at == target.reservation.prospective_source_expires_at
        )
        assert (first.row_count, first.column_count, first.format, first.version) == (
            1,
            2,
            "csv",
            1,
        )
        assert "00123" not in repr(first) and "line1" not in repr(first)
        assert len(target.providers) == len(target.providers[0].requests) == 1
        with closing(sqlite3.connect(target.agent.store.path)) as db:
            assert list(db.iterdump()) == before
        with closing(sqlite3.connect(target.metadata.path)) as db:
            assert db.execute("SELECT COUNT(*) FROM snapshot_manifests").fetchone() == (
                1,
            )
        assert len(list(target.root.iterdir())) == 2
        assert handle._borrow.retirement_completed
        assert not handle._attempt.cleanup_pending


@pytest.mark.parametrize(
    "case", ["offset", "empty", "text", "oversized", "overflow", "retransmit"]
)
async def test_invalid_chunks_close_attempt_without_replay_or_publication(
    tmp_path, case
):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        offset, chunk = 0, target.raw
        if case == "offset":
            offset = 1
        elif case == "empty":
            chunk = b""
        elif case == "text":
            chunk = "PRIVATE_TEXT_CANARY"
        elif case == "oversized":
            chunk = b"x" * 65537
        elif case == "overflow":
            chunk += b"extra"
        elif case == "retransmit":
            manager.append_chunk(
                handle, **target.arguments, expected_offset=0, chunk=target.raw[:3]
            )
            chunk = target.raw[:3]
        with pytest.raises(ReservationError) as caught:
            manager.append_chunk(
                handle, **target.arguments, expected_offset=offset, chunk=chunk
            )
        assert "PRIVATE_" not in str(caught.value)
        with pytest.raises(ReservationError):
            manager.append_chunk(
                handle, **target.arguments, expected_offset=0, chunk=target.raw
            )
        with pytest.raises(ReservationError):
            manager.begin_receive(**receive_args(target))
        assert handle._borrow.retirement_completed
        assert list(target.root.iterdir()) == []
        with closing(sqlite3.connect(target.metadata.path)) as db:
            payload = json.loads(
                db.execute("SELECT payload FROM source_lifecycle").fetchone()[0]
            )
            assert payload["state"] == "failed" and payload["cleanup_pending"] is False
            assert db.execute("SELECT COUNT(*) FROM snapshot_manifests").fetchone() == (
                0,
            )


@pytest.mark.parametrize(
    "change",
    [
        {"enabled": 0},
        {"account": "foreign"},
        {"epoch": "changed"},
        {"target": "foreign"},
        {"fingerprint": "changed"},
        {"purpose": "shipagent.status"},
    ],
)
async def test_fresh_authority_denies_before_chunk_write(tmp_path, monkeypatch, change):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        target.authority.mutate(**change)
        calls = []
        original = handle._files.append

        def observed(**kwargs):
            calls.append(True)
            return original(**kwargs)

        monkeypatch.setattr(handle._files, "append", observed)
        with pytest.raises(ReservationError):
            manager.append_chunk(
                handle, **target.arguments, expected_offset=0, chunk=target.raw
            )
        assert not calls and len(target.providers) == 1


async def test_completed_retry_does_not_accumulate_owned_receivers(tmp_path):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        completed = manager.finish(handle, **target.arguments)
        for _ in range(6):
            assert manager.begin_receive(**receive_args(target)) == completed
        assert not manager._owners


@pytest.mark.parametrize("case", ["short", "digest"])
async def test_invalid_eof_retires_files_and_slot_before_failure(tmp_path, case):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        raw = target.raw[:-1] if case == "short" else b"X" + target.raw[1:]
        manager.append_chunk(handle, **target.arguments, expected_offset=0, chunk=raw)
        with pytest.raises(ReservationError):
            manager.finish(handle, **target.arguments)
        assert handle._borrow.retirement_completed
        assert list(target.root.iterdir()) == []
        assert handle._attempt.state == "failed" and not handle._attempt.cleanup_pending


async def test_abort_proves_cleanup_and_does_not_recycle_request(tmp_path):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw[:5]
        )
        result = manager.abort(handle, **target.arguments)
        assert result.status == "aborted"
        assert list(target.root.iterdir()) == [] and handle._borrow.retirement_completed
        with pytest.raises(ReservationError):
            manager.begin_receive(**receive_args(target))
        assert handle._attempt.state == "failed" and not handle._attempt.cleanup_pending


async def test_busy_parser_leaves_sealed_retryable_without_renewing_time(tmp_path):
    from src.services.agent_runs.coordinator import SourceWorkKind

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        clocks = handle._whole_deadline, handle._idle_deadline, handle._grant_expiry
        blocker, _ = target.agent.borrow_coordinator(
            source_work=SourceWorkKind.PARSER,
            source_binding=target.agent.source_storage_binding(),
        )
        try:
            with pytest.raises(ReservationError):
                manager.finish(handle, **target.arguments)
            assert handle._attempt.state == "sealed"
            assert handle._parser._retired and handle._parser._child is None
            assert not handle._borrow.retirement_completed
            assert clocks == (
                handle._whole_deadline,
                handle._idle_deadline,
                handle._grant_expiry,
            )
        finally:
            blocker.retire()
        assert manager.finish(handle, **target.arguments).row_count == 1


async def test_denied_parsing_commit_never_spawns_and_retires_admitted_slot(
    tmp_path, monkeypatch
):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        original = manager._phase

        def denied(owner, arguments, expected, state):
            if state == "parsing":
                raise ReservationError("reservation_unavailable")
            return original(owner, arguments, expected, state)

        with monkeypatch.context() as patch:
            patch.setattr(manager, "_phase", denied)
            with pytest.raises(ReservationError):
                manager.finish(handle, **target.arguments)
        assert (
            handle._parser._child is None
            and handle._parser._borrow.retirement_completed
        )
        assert handle._borrow.retirement_completed and list(target.root.iterdir()) == []


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "fifo"])
async def test_unaccounted_content_refuses_claim_without_repair(tmp_path, kind):
    import os

    async with snapshot_target(tmp_path) as target:
        unknown = target.root / "unaccounted"
        if kind == "file":
            unknown.write_bytes(b"PRIVATE_UNACCOUNTED_CANARY")
        elif kind == "directory":
            unknown.mkdir()
        elif kind == "symlink":
            unknown.symlink_to(tmp_path / "absent")
        else:
            os.mkfifo(unknown, 0o600)
        manager = snapshot_manager(target)
        before = unknown.lstat()
        with pytest.raises(ReservationError):
            manager.begin_receive(**receive_args(target))
        assert unknown.lstat() == before
        with closing(sqlite3.connect(target.metadata.path)) as db:
            assert db.execute("SELECT COUNT(*) FROM source_lifecycle").fetchone() == (
                0,
            )


async def test_creation_before_recorded_identity_blocks_other_manager_without_adoption(
    tmp_path,
    monkeypatch,
):
    import concurrent.futures
    import threading
    from dataclasses import replace

    from src.services.source_ingress.snapshot_files import OwnedSnapshotFiles

    async with snapshot_target(tmp_path) as target:
        other_request = replace(target.request, request_key="source-b")
        other_reservation = target.coordinator.reserve(
            **target.arguments, request=other_request
        )
        manager = snapshot_manager(target)
        other = snapshot_manager(target)
        other_args = target.arguments | {
            "request_key": other_request.request_key,
            "reservation_id": other_reservation.reservation_id,
        }
        created, release = threading.Event(), threading.Event()
        original = OwnedSnapshotFiles.create

        def delayed(files):
            original(files)
            created.set()
            assert release.wait(2)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with monkeypatch.context() as patch:
                patch.setattr(OwnedSnapshotFiles, "create", delayed)
                future = pool.submit(manager.begin_receive, **receive_args(target))
                try:
                    assert created.wait(2)
                    original_bytes = {
                        p.name: p.read_bytes() for p in target.root.iterdir()
                    }
                    with pytest.raises(ReservationError):
                        other.begin_receive(**other_args)
                    assert {
                        p.name: p.read_bytes() for p in target.root.iterdir()
                    } == original_bytes
                finally:
                    release.set()
                first = future.result(timeout=3)
        second = other.begin_receive(**other_args)
        assert manager.abort(first, **target.arguments).status == "aborted"
        assert other.abort(second, **target.arguments).status == "aborted"


async def test_watchdog_exists_only_for_admitted_work_and_retires_idle_expiry(tmp_path):
    import asyncio
    import time

    async with snapshot_target(tmp_path) as target:
        mono = [time.monotonic()]
        manager = snapshot_manager(target, monotonic=lambda: mono[0])
        assert manager._watchdog is None
        handle = manager.begin_receive(**receive_args(target))
        assert manager._watchdog.is_alive()
        mono[0] += 11
        async with asyncio.timeout(2):
            while not handle._resources_retired or manager._watchdog.is_alive():
                await asyncio.sleep(0.01)
        assert handle._cancelled and handle._borrow.retirement_completed
        assert list(target.root.iterdir()) == []
        with closing(sqlite3.connect(target.metadata.path)) as db:
            assert db.execute("SELECT COUNT(*) FROM snapshot_manifests").fetchone() == (
                0,
            )


async def test_timeout_and_close_do_not_reclaim_a_blocked_append(tmp_path, monkeypatch):
    import concurrent.futures
    import threading
    import time

    async with snapshot_target(tmp_path) as target:
        mono = [time.monotonic()]
        manager = snapshot_manager(target, monotonic=lambda: mono[0])
        handle = manager.begin_receive(**receive_args(target))
        entered, release = threading.Event(), threading.Event()
        original = handle._files._write_raw

        def blocked(chunk):
            entered.set()
            assert release.wait(3)
            return original(chunk)

        monkeypatch.setattr(handle._files, "_write_raw", blocked)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                manager.append_chunk,
                handle,
                **target.arguments,
                expected_offset=0,
                chunk=target.raw,
            )
            try:
                assert entered.wait(2)
                mono[0] += 11
                until = time.monotonic() + 1
                while not handle._cancelled and time.monotonic() < until:
                    time.sleep(0.01)
                assert handle._cancelled
                assert (
                    not handle._resources_retired
                    and not handle._borrow.retirement_completed
                )
                start = time.monotonic()
                with pytest.raises(ReservationError):
                    manager.close()
                assert time.monotonic() - start < 0.5
                assert not handle._borrow.retirement_completed
            finally:
                release.set()
            with pytest.raises(ReservationError):
                future.result(timeout=3)
        assert handle._borrow.retirement_completed and list(target.root.iterdir()) == []
        manager.close()


async def test_late_begin_and_post_io_utc_expiry_keep_original_upload_lifetime(
    tmp_path, monkeypatch
):
    import time

    async with snapshot_target(tmp_path) as target:
        # Isolate the upload boundary from the independently minted grant clock.
        target.authority.mutate(expires=target.reservation.upload_expires_at + 30)
        now = [target.reservation.upload_expires_at - 4]
        mono = [time.monotonic()]
        manager = snapshot_manager(
            target, clock=lambda: now[0], monotonic=lambda: mono[0]
        )
        handle = manager.begin_receive(**receive_args(target))
        assert handle._grant_expiry == target.reservation.upload_expires_at
        assert handle._whole_deadline - mono[0] == 4
        original = handle._files._write_raw

        def delayed(chunk):
            result = original(chunk)
            now[0] = target.reservation.upload_expires_at
            return result

        monkeypatch.setattr(handle._files, "_write_raw", delayed)
        with pytest.raises(ReservationError):
            manager.append_chunk(
                handle, **target.arguments, expected_offset=0, chunk=target.raw
            )
        assert handle._borrow.retirement_completed
        assert list(target.root.iterdir()) == []


async def test_a_late_write_cannot_renew_an_already_expired_idle_budget(
    tmp_path, monkeypatch
):
    import time

    async with snapshot_target(tmp_path) as target:
        mono = [time.monotonic()]
        manager = snapshot_manager(target, monotonic=lambda: mono[0])
        handle = manager.begin_receive(**receive_args(target))
        original = handle._files._write_raw

        def late(chunk):
            written = original(chunk)
            mono[0] += 11
            return written

        monkeypatch.setattr(handle._files, "_write_raw", late)
        with pytest.raises(ReservationError):
            manager.append_chunk(
                handle, **target.arguments, expected_offset=0, chunk=target.raw
            )
        assert handle._borrow.retirement_completed and list(target.root.iterdir()) == []


async def test_duplicate_denials_do_not_accumulate_empty_owners(tmp_path):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        for _ in range(5):
            with pytest.raises(ReservationError):
                manager.begin_receive(**receive_args(target))
        assert manager._owners == {handle}
        manager.abort(handle, **target.arguments)


@pytest.mark.parametrize("kind", ["copied", "forged", "object"])
async def test_bad_handle_denial_never_changes_the_real_receiver(tmp_path, kind):
    import copy

    from src.services.source_ingress.snapshots import ReceiverHandle

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        bad = (
            copy.copy(handle)
            if kind == "copied"
            else object()
            if kind == "object"
            else ReceiverHandle(
                manager,
                connection="connection-a",
                conversation=target.accepted["conversation_reference"],
                key=target.request.request_key,
                reservation_id=target.reservation.reservation_id,
            )
        )
        for call in (
            lambda: manager.append_chunk(
                bad, **target.arguments, expected_offset=0, chunk=target.raw
            ),
            lambda: manager.finish(bad, **target.arguments),
            lambda: manager.abort(bad, **target.arguments),
        ):
            with pytest.raises(ReservationError):
                call()
        assert not handle._cancelled and not handle._borrow.retirement_completed
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw
        )
        assert manager.finish(handle, **target.arguments).row_count == 1


async def test_idle_abort_uses_a_fresh_current_call_grant(tmp_path):
    import time

    now = [int(time.time())]
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target, clock=lambda: now[0])
        handle = manager.begin_receive(**receive_args(target))
        target.authority.mutate(expires=now[0] + 2)
        manager.append_chunk(
            handle, **target.arguments, expected_offset=0, chunk=target.raw[:3]
        )
        now[0] += 3
        target.authority.mutate(expires=now[0] + 30)
        assert manager.abort(handle, **target.arguments).status == "aborted"
        assert handle._borrow.retirement_completed


async def test_two_receiver_slots_are_shared_across_replacement_managers(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    async with snapshot_target(tmp_path) as target:
        first, second, third = [snapshot_manager(target) for _ in range(3)]
        one = first.begin_receive(**receive_args(target))
        request = replace(target.request, request_key="source-b")
        reservation = target.coordinator.reserve(**target.arguments, request=request)
        two = second.begin_receive(
            **target.arguments,
            request_key=request.request_key,
            reservation_id=reservation.reservation_id,
        )

        def no_more_fences():
            raise AssertionError(
                "Third receiver must be denied before storage or authority"
            )

        monkeypatch.setattr(third, "_executor", no_more_fences)
        with pytest.raises(ReservationError):
            third.begin_receive(**receive_args(target))
        assert not third._owners and third._watchdog is None
        first.abort(one, **target.arguments)
        assert not two._borrow.retirement_completed
        second.append_chunk(
            two, **target.arguments, expected_offset=0, chunk=target.raw
        )
        assert second.finish(two, **target.arguments).row_count == 1
        assert not first._owners and not second._owners


async def test_completed_retention_reaches_128_without_reusing_lifetime_or_bytes(
    tmp_path,
):
    from dataclasses import replace

    from src.services.source_ingress.snapshot_contracts import MAX_COMPLETED_SNAPSHOTS

    async with snapshot_target(tmp_path, raw=b"Zip\n00123\n") as target:
        manager = snapshot_manager(target)
        ids = set()
        before = None
        for index in range(MAX_COMPLETED_SNAPSHOTS):
            request = (
                replace(target.request, request_key=f"source-{index}")
                if index
                else target.request
            )
            reservation = target.coordinator.reserve(
                **target.arguments, request=request
            )
            handle = manager.begin_receive(
                **target.arguments,
                request_key=request.request_key,
                reservation_id=reservation.reservation_id,
            )
            manager.append_chunk(
                handle, **target.arguments, expected_offset=0, chunk=target.raw
            )
            result = manager.finish(handle, **target.arguments)
            assert result.source_expires_at == reservation.prospective_source_expires_at
            assert result.snapshot_id not in ids
            ids.add(result.snapshot_id)
            assert not handle._attempt.cleanup_pending and not manager._owners
            if index == 0:
                before = {p.name: p.read_bytes() for p in target.root.iterdir()}
        assert len(ids) == 128 and len(list(target.root.iterdir())) == 256
        request = replace(target.request, request_key="over-completed-cap")
        reservation = target.coordinator.reserve(**target.arguments, request=request)
        with pytest.raises(ReservationError):
            manager.begin_receive(
                **target.arguments,
                request_key=request.request_key,
                reservation_id=reservation.reservation_id,
            )
        assert len(list(target.root.iterdir())) == 256
        assert all(
            (target.root / name).read_bytes() == data for name, data in before.items()
        )
        assert len(target.providers) == 1
        with closing(sqlite3.connect(target.metadata.path)) as db:
            assert db.execute("SELECT COUNT(*) FROM snapshot_manifests").fetchone() == (
                128,
            )
            rows = [
                json.loads(row[0])
                for row in db.execute("SELECT payload FROM source_lifecycle")
            ]
            assert len(rows) == 128 and all(not row["cleanup_pending"] for row in rows)

    from tests.services.source_ingress.test_snapshot_recovery import (
        qualify_reopened_capacity,
    )

    await qualify_reopened_capacity(tmp_path)


async def test_replacement_process_cannot_claim_while_receiver_lifetime_is_owned(
    tmp_path,
):
    import subprocess
    import sys

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        path = target.agent.store.path.with_suffix(".coordinator.lock")
        command = """import sys
from pathlib import Path
from src.services.agent_runs.coordinator import CoordinatorLease
try:
    lease = CoordinatorLease(Path(sys.argv[1]))
except RuntimeError:
    print('denied')
else:
    lease.close()
    raise SystemExit('replacement unexpectedly acquired live ownership')
"""
        child = subprocess.run(
            [sys.executable, "-c", command, str(path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert child.returncode == 0, child.stderr
        assert child.stdout.strip() == "denied"
        assert not handle._borrow.retirement_completed
        assert manager.abort(handle, **target.arguments).status == "aborted"


@pytest.mark.parametrize("control", [False, True])
@pytest.mark.parametrize("phase", ["file_close", "token_after"])
async def test_manager_close_preserves_receiver_interruption_and_retirement_proof(
    tmp_path, monkeypatch, control, phase
):
    from src.services.agent_runs.coordinator import CoordinatorBorrow, SourceWorkKind
    from src.services.source_ingress.snapshot_files import OwnedSnapshotFiles

    class Stop(BaseException):
        pass

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        token = handle._borrow

        def fail():
            raise Stop() if control else OSError("PRIVATE_RECEIVER_CLOSE_CANARY")

        with monkeypatch.context() as patch:
            if phase == "file_close":

                def close(files, **kwargs):
                    fail()

                patch.setattr(OwnedSnapshotFiles, "retire", close)
            else:
                original = CoordinatorBorrow.retire

                def retire(borrow):
                    original(borrow)
                    if borrow._source_work is SourceWorkKind.RECEIVER:
                        fail()

                patch.setattr(CoordinatorBorrow, "retire", retire)
            with pytest.raises(Stop if control else ReservationError) as caught:
                manager.close()
            assert "PRIVATE_RECEIVER_CLOSE_CANARY" not in str(caught.value)
        after = phase == "token_after"
        assert token.retirement_completed is after
        assert handle._resources_retired is after
        assert target.agent._lease._source_quarantined is (not after)
        manager.close()
        assert handle._resources_retired and not target.agent._lease._borrows


@pytest.mark.parametrize("field", ["record", "lifecycle", "manifest"])
async def test_closed_action_value_cannot_wrap_live_scopes(tmp_path, field):
    from src.services.source_ingress.snapshot_contracts import _SnapshotActionValue

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = manager.begin_receive(**receive_args(target))
        values = {
            "record": handle._record,
            "lifecycle": handle._attempt,
            "manifest": None,
        }
        for invalid in (
            handle,
            handle._borrow,
            manager,
            target.metadata,
            target.authority,
            {"value": handle},
        ):
            with pytest.raises(ReservationError):
                _SnapshotActionValue(**(values | {field: invalid}))
        assert manager.abort(handle, **target.arguments).status == "aborted"


async def test_content_cap_reserves_peak_before_files_and_retains_completed_bytes(
    tmp_path,
):
    from dataclasses import replace

    from src.services.source_ingress.csv_snapshot import parse_csv_snapshot
    from src.services.source_ingress.snapshot_codec import encode_snapshot
    from src.services.source_ingress.snapshot_contracts import (
        MAX_CONTENT_BYTES,
        RESERVED_CONTENT_BYTES,
    )
    from tests.services.source_ingress.test_parser_owner import boundary_raw

    raw = boundary_raw("raw_cap")
    parsed = parse_csv_snapshot(
        raw,
        content_length=len(raw),
        content_sha256=hashlib.sha256(raw).hexdigest(),
        media_type="text/csv",
    )
    per_complete = len(raw) + len(encode_snapshot(parsed))
    count = (MAX_CONTENT_BYTES - RESERVED_CONTENT_BYTES) // per_complete + 1
    async with snapshot_target(tmp_path, raw=raw) as target:
        manager = snapshot_manager(target)
        completed = []
        for index in range(count):
            request = (
                replace(target.request, request_key=f"large-{index}")
                if index
                else target.request
            )
            reservation = target.coordinator.reserve(
                **target.arguments, request=request
            )
            handle = manager.begin_receive(
                **target.arguments,
                request_key=request.request_key,
                reservation_id=reservation.reservation_id,
            )
            for offset in range(0, len(raw), 65536):
                manager.append_chunk(
                    handle,
                    **target.arguments,
                    expected_offset=offset,
                    chunk=raw[offset : offset + 65536],
                )
            completed.append(manager.finish(handle, **target.arguments))
        assert count * per_complete <= MAX_CONTENT_BYTES
        assert count * per_complete + RESERVED_CONTENT_BYTES > MAX_CONTENT_BYTES
        before = {
            p.name: (p.stat().st_ino, p.stat().st_size) for p in target.root.iterdir()
        }
        request = replace(target.request, request_key="over-content-cap")
        reservation = target.coordinator.reserve(**target.arguments, request=request)
        with pytest.raises(ReservationError):
            manager.begin_receive(
                **target.arguments,
                request_key=request.request_key,
                reservation_id=reservation.reservation_id,
            )
        assert {
            p.name: (p.stat().st_ino, p.stat().st_size) for p in target.root.iterdir()
        } == before
        assert manager.begin_receive(**receive_args(target)) == completed[0]
        assert len(target.providers) == 1

    from tests.services.source_ingress.test_snapshot_recovery import (
        qualify_reopened_capacity,
    )

    await qualify_reopened_capacity(tmp_path)


@pytest.mark.parametrize("method", ["begin", "finish", "abort", "completed"])
@pytest.mark.parametrize(
    "change",
    [
        {"account": "foreign"},
        {"connection": "foreign"},
        {"epoch": "changed"},
        {"fingerprint": "changed"},
        {"enabled": 0},
    ],
)
async def test_every_receiver_boundary_requires_current_authority(
    tmp_path, method, change
):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        handle = None
        if method != "begin":
            handle = manager.begin_receive(**receive_args(target))
            manager.append_chunk(
                handle, **target.arguments, expected_offset=0, chunk=target.raw
            )
        if method == "completed":
            manager.finish(handle, **target.arguments)
        before = {p.name: p.read_bytes() for p in target.root.iterdir()}
        target.authority.mutate(**change)
        with pytest.raises(ReservationError):
            if method in ("begin", "completed"):
                manager.begin_receive(**receive_args(target))
            elif method == "finish":
                manager.finish(handle, **target.arguments)
            else:
                manager.abort(handle, **target.arguments)
        assert {p.name: p.read_bytes() for p in target.root.iterdir()} == before
        assert handle is None or handle._parser is None or handle._published
        assert len(target.providers) == 1
