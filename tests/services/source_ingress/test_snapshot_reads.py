"""Private values require a fresh two-fence observation and retired ownership."""

import pytest

from src.services.source_ingress.reservation_contracts import ReservationError
from tests.services.source_ingress.snapshot_fixtures import (
    receive_args,
    snapshot_manager,
    snapshot_target,
)


def complete(target, manager):
    handle = manager.begin_receive(**receive_args(target))
    manager.append_chunk(
        handle, **target.arguments, expected_offset=0, chunk=target.raw
    )
    return manager.finish(handle, **target.arguments)


def read_args(target, receipt):
    return target.arguments | {
        "request_key": target.request.request_key,
        "private_snapshot_id": receipt.snapshot_id,
    }


async def test_private_read_materializes_exact_inert_values_and_retires_every_scope(
    tmp_path,
):
    async with snapshot_target(tmp_path, raw=b"Zip,Formula\n00123,=2+2\n") as target:
        manager = snapshot_manager(target)
        receipt = complete(target, manager)
        assert callable(getattr(manager, "read_private_snapshot", None)), (
            "private read is absent"
        )
        snapshot = manager.read_private_snapshot(**read_args(target, receipt))
        assert snapshot.headers == ("Zip", "Formula")
        assert snapshot.rows == (("00123", "=2+2"),)
        assert manager.describe_snapshot(**read_args(target, receipt)) == receipt
        assert not target.agent._lease._borrows and not manager._root._owners
        assert len(target.providers) == 1


@pytest.mark.parametrize(
    "corruption", ["same_length", "truncated", "missing", "replaced"]
)
async def test_completed_same_key_receipt_recovery_rejects_corrupt_private_bytes(
    tmp_path, corruption
):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        receipt = complete(target, manager)
        path = next(target.root.glob("*.raw"))
        original = path.read_bytes()
        if corruption == "same_length":
            path.write_bytes(b"!" + original[1:])
        elif corruption == "truncated":
            path.write_bytes(original[:-1])
        elif corruption == "missing":
            path.unlink()
        else:
            path.rename(target.root / "unrelated-original")
            path.write_bytes(original)
            path.chmod(0o600)
        with pytest.raises(ReservationError):
            manager.begin_receive(**receive_args(target))
        assert receipt.snapshot_id
        assert not target.agent._lease._borrows


@pytest.mark.parametrize("change", ["revoke", "relink", "cancel", "expiry", "deadline"])
async def test_second_read_fence_denies_changes_during_private_materialization(
    tmp_path, monkeypatch, change
):
    import time

    from src.services.source_ingress.snapshot_files import OwnedSnapshotFiles

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        receipt = complete(target, manager)
        original = OwnedSnapshotFiles.read_complete
        observed = []

        def materialize(files):
            value = original(files)
            observed.append(value)
            if change == "revoke":
                target.authority.mutate(enabled=0)
            elif change == "relink":
                target.authority.mutate(epoch="replacement-epoch")
            elif change == "cancel":
                target.agent.cancel(
                    connection_id="connection-a",
                    run_reference=target.accepted["run_reference"],
                )
            elif change == "expiry":
                manager._clock = lambda: float(receipt.source_expires_at)
            else:
                manager._monotonic = lambda: time.monotonic() + 3
            return value

        monkeypatch.setattr(OwnedSnapshotFiles, "read_complete", materialize)
        with pytest.raises(ReservationError):
            manager.read_private_snapshot(**read_args(target, receipt))
        assert observed and observed[0].rows
        assert not manager._reads and not target.agent._lease._borrows
        assert len(target.providers) == 1


@pytest.mark.parametrize("clock", ["utc", "mono"])
@pytest.mark.parametrize("interrupt", [False, True])
async def test_final_read_clock_errors_are_closed_after_positive_token_retirement(
    tmp_path, monkeypatch, clock, interrupt
):
    from src.services.agent_runs.coordinator import CoordinatorBorrow, SourceWorkKind

    class Stop(BaseException):
        pass

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        receipt = complete(target, manager)
        original = CoordinatorBorrow.retire

        def fail():
            raise Stop() if interrupt else RuntimeError("PRIVATE_CLOCK_CANARY")

        def retire(token):
            original(token)
            if token._source_work is SourceWorkKind.PRIVATE_READ:
                assert token.retirement_completed
                setattr(manager, "_clock" if clock == "utc" else "_monotonic", fail)

        monkeypatch.setattr(CoordinatorBorrow, "retire", retire)
        with pytest.raises(Stop if interrupt else ReservationError) as caught:
            manager.read_private_snapshot(**read_args(target, receipt))
        assert "PRIVATE_CLOCK_CANARY" not in str(caught.value)
        assert not manager._reads and not target.agent._lease._borrows


async def test_shared_read_cap_retains_one_original_lifetime_through_materialization(
    tmp_path, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from src.services.source_ingress.snapshot_files import OwnedSnapshotFiles

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        receipt = complete(target, manager)
        replacement = snapshot_manager(target)
        entered, release = threading.Event(), threading.Event()
        original = OwnedSnapshotFiles.read_complete

        def materialize(files):
            result = original(files)
            entered.set()
            assert release.wait(2)
            return result

        monkeypatch.setattr(OwnedSnapshotFiles, "read_complete", materialize)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                manager.read_private_snapshot, **read_args(target, receipt)
            )
            try:
                assert entered.wait(2)
                with pytest.raises(ReservationError):
                    replacement.read_private_snapshot(**read_args(target, receipt))
                assert len(target.agent._lease._borrows) == 1
                assert not target.agent._lease._source_quarantined
            finally:
                release.set()
            assert future.result(timeout=3).rows
        assert not manager._reads and not replacement._reads


async def test_known_busy_read_retirement_defers_without_quarantining_shared_lease(
    tmp_path, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from src.services.source_ingress.snapshot_files import OwnedSnapshotFiles
    from src.services.source_ingress.snapshots import _PrivateRead

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        receipt = complete(target, manager)
        before, allow_reader = threading.Event(), threading.Event()
        closing, allow_close = threading.Event(), threading.Event()
        reader_ident = []
        original_retire = _PrivateRead._retire
        original_files = OwnedSnapshotFiles.retire

        def retire(owner):
            if threading.get_ident() == reader_ident[0]:
                before.set()
                assert allow_reader.wait(2)
            return original_retire(owner)

        def files_close(files, **kwargs):
            closing.set()
            assert allow_close.wait(2)
            return original_files(files, **kwargs)

        def read():
            reader_ident.append(threading.get_ident())
            return manager.read_private_snapshot(**read_args(target, receipt))

        monkeypatch.setattr(_PrivateRead, "_retire", retire)
        monkeypatch.setattr(OwnedSnapshotFiles, "retire", files_close)
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(read)
            closer = None
            try:
                assert before.wait(2)
                closer = pool.submit(manager.close)
                assert closing.wait(2)
                allow_reader.set()
                with pytest.raises(ReservationError):
                    future.result(timeout=2)
                assert not target.agent._lease._source_quarantined
                assert target.agent._lease._borrows
            finally:
                allow_reader.set()
                allow_close.set()
                if closer is not None:
                    closer.result(timeout=3)
        assert not manager._reads and not target.agent._lease._borrows


@pytest.mark.parametrize("method", ["read_private_snapshot", "describe_snapshot"])
async def test_private_reads_recheck_bounded_inventory_without_adopting_unknown_files(
    tmp_path, method
):
    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        receipt = complete(target, manager)
        unknown = target.root / "UNOWNED"
        unknown.write_bytes(b"PRIVATE_UNKNOWN_CANARY")
        unknown.chmod(0o600)
        with pytest.raises(ReservationError):
            getattr(manager, method)(**read_args(target, receipt))
        assert unknown.read_bytes() == b"PRIVATE_UNKNOWN_CANARY"
        assert not target.agent._lease._borrows


@pytest.mark.parametrize("after", [False, True])
async def test_read_retains_original_failed_scan_until_explicit_cleanup(
    tmp_path, monkeypatch, after
):
    import os

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        receipt = complete(target, manager)
        original = os.scandir
        failing = [True]

        class CapturedScan:
            def __init__(self, fd):
                self.scan = original(fd)

            def __iter__(self):
                return iter(self.scan)

            def close(self):
                if failing[0]:
                    if after:
                        self.scan.close()
                    raise RuntimeError("PRIVATE_SCAN_CANARY")
                self.scan.close()

        with monkeypatch.context() as patch:
            patch.setattr(os, "scandir", CapturedScan)
            with pytest.raises(ReservationError):
                manager.read_private_snapshot(**read_args(target, receipt))
        assert manager._root._scan is not None and len(manager._reads) == 1
        read = next(iter(manager._reads))
        assert not read._borrow.retirement_completed
        assert target.agent._lease._source_quarantined
        failing[0] = False
        manager.close()
        assert not manager._reads and not target.agent._lease._borrows
        assert manager._root._scan is None and len(list(target.root.iterdir())) == 2


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("control", [False, True])
async def test_read_final_token_interruption_retains_or_proves_its_exact_retirement(
    tmp_path, monkeypatch, after, control
):
    from src.services.agent_runs.coordinator import CoordinatorBorrow, SourceWorkKind

    class Stop(BaseException):
        pass

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        receipt = complete(target, manager)
        original = CoordinatorBorrow.retire
        observed = []

        def retire(token):
            if token._source_work is not SourceWorkKind.PRIVATE_READ:
                return original(token)
            observed.append(token)
            if after:
                original(token)
            raise Stop() if control else RuntimeError("PRIVATE_RETIRE_CANARY")

        with monkeypatch.context() as patch:
            patch.setattr(CoordinatorBorrow, "retire", retire)
            with pytest.raises(Stop if control else ReservationError):
                manager.read_private_snapshot(**read_args(target, receipt))
        assert observed and observed[0].retirement_completed is after
        assert target.agent._lease._source_quarantined is (not after)
        manager.close()
        assert not manager._reads and not target.agent._lease._borrows


async def test_fresh_grant_cannot_extend_the_original_in_progress_read(
    tmp_path, monkeypatch
):
    import time

    from src.services.source_ingress.snapshot_files import OwnedSnapshotFiles

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        receipt = complete(target, manager)
        original_expiry = int(time.time()) + 10
        target.authority.mutate(expires=original_expiry)
        original = OwnedSnapshotFiles.read_complete

        def materialize(files):
            value = original(files)
            target.authority.mutate(expires=original_expiry + 500)
            manager._clock = lambda: float(original_expiry + 1)
            return value

        monkeypatch.setattr(OwnedSnapshotFiles, "read_complete", materialize)
        with pytest.raises(ReservationError):
            manager.read_private_snapshot(**read_args(target, receipt))
        assert not manager._reads and not target.agent._lease._borrows


@pytest.mark.parametrize("replacement", ["root", "store"])
async def test_read_denies_identity_replacement_between_its_two_fences(
    tmp_path, monkeypatch, replacement
):
    from src.services.source_ingress.snapshot_files import OwnedSnapshotFiles

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        receipt = complete(target, manager)
        original = OwnedSnapshotFiles.read_complete
        path = target.root if replacement == "root" else target.metadata.path
        moved = path.with_name(path.name + ".original")
        switched = False

        def materialize(files):
            nonlocal switched
            value = original(files)
            path.rename(moved)
            switched = True
            if replacement == "root":
                path.mkdir(mode=0o700)
            else:
                path.write_bytes(moved.read_bytes())
                path.chmod(0o600)
            return value

        monkeypatch.setattr(OwnedSnapshotFiles, "read_complete", materialize)
        try:
            with pytest.raises(ReservationError):
                manager.read_private_snapshot(**read_args(target, receipt))
            assert len(target.providers) == 1
        finally:
            if switched:
                path.rmdir() if replacement == "root" else path.unlink()
                moved.rename(path)
            manager.close()


def test_read_unknown_scan_acquisition_retains_lifetime_until_process_exit(tmp_path):
    import subprocess
    import sys

    script = r"""
import asyncio, os, sys
from pathlib import Path
from tests.services.source_ingress.snapshot_fixtures import snapshot_target, snapshot_manager
from tests.services.source_ingress.test_snapshot_reads import complete, read_args
from src.services.source_ingress.reservation_contracts import ReservationError
async def main():
    context=snapshot_target(Path(sys.argv[1]))
    target=await context.__aenter__()
    manager=snapshot_manager(target)
    receipt=complete(target,manager)
    original=os.scandir
    hidden=[]
    def acquire(fd):
        hidden.append(original(fd))
        raise RuntimeError("PRIVATE_SCAN_ACQUISITION_CANARY")
    os.scandir=acquire
    try:
        manager.read_private_snapshot(**read_args(target,receipt))
        raise AssertionError("unknown acquisition returned values")
    except ReservationError as error:
        assert "PRIVATE_SCAN" not in str(error)
    finally:
        os.scandir=original
    assert manager._root._uncertain and manager._root._scan is None
    assert len(manager._reads)==1
    read=next(iter(manager._reads))
    assert read._borrow is not None and not read._borrow.retirement_completed
    assert target.agent._lease._source_quarantined
    try:
        manager.close()
        raise AssertionError("uncertain ownership reported retired")
    except ReservationError:
        pass
    assert not read._borrow.retirement_completed
    os._exit(0)
asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=6,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("control", [False, True])
@pytest.mark.parametrize("phase", ["file_close", "token_after"])
async def test_manager_close_retains_uncertain_read_or_positive_final_retirement(
    tmp_path, monkeypatch, control, phase
):
    from src.services.agent_runs.coordinator import CoordinatorBorrow, SourceWorkKind
    from src.services.source_ingress.snapshot_files import OwnedSnapshotFiles
    from src.services.source_ingress.snapshots import _PrivateRead, _WorkPending

    class Stop(BaseException):
        pass

    async with snapshot_target(tmp_path) as target:
        manager = snapshot_manager(target)
        receipt = complete(target, manager)
        with monkeypatch.context() as patch:

            def busy(owner):
                raise _WorkPending()

            patch.setattr(_PrivateRead, "_retire", busy)
            with pytest.raises(ReservationError):
                manager.read_private_snapshot(**read_args(target, receipt))
        read = next(iter(manager._reads))
        token = read._borrow
        assert not token.retirement_completed
        assert not target.agent._lease._source_quarantined

        def fail():
            raise Stop() if control else OSError("PRIVATE_CLOSE_CANARY")

        with monkeypatch.context() as patch:
            if phase == "file_close":

                def close(files, **kwargs):
                    fail()

                patch.setattr(OwnedSnapshotFiles, "retire", close)
            else:
                original = CoordinatorBorrow.retire

                def retire(borrow):
                    original(borrow)
                    if borrow._source_work is SourceWorkKind.PRIVATE_READ:
                        fail()

                patch.setattr(CoordinatorBorrow, "retire", retire)
            with pytest.raises(Stop if control else ReservationError) as caught:
                manager.close()
            assert "PRIVATE_CLOSE_CANARY" not in str(caught.value)
        after = phase == "token_after"
        assert token.retirement_completed is after
        assert target.agent._lease._source_quarantined is (not after)
        assert bool(manager._reads) is (not after)
        manager.close()
        assert not manager._reads and not target.agent._lease._borrows
