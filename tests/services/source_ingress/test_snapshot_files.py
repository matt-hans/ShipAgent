"""Pinned private byte owners; these tests grant no source/public authority."""

import hashlib
import importlib
import importlib.util
import os
from dataclasses import replace

import pytest

from src.services.source_ingress.csv_snapshot import PARSER_PROFILE, parse_csv_snapshot
from src.services.source_ingress.reservation_contracts import ReservationError
from src.services.source_ingress.snapshot_codec import encode_snapshot
from src.services.source_ingress.snapshot_contracts import (
    RESERVED_CONTENT_BYTES,
    SnapshotLifecycle,
    SnapshotManifest,
)

RAW = b"Zip,Formula\n00123,=2+2\n"


def implementation():
    name = "src.services.source_ingress.snapshot_files"
    assert importlib.util.find_spec(name) is not None, (
        "private file ownership is absent"
    )
    return importlib.import_module(name)


def attempt():
    return SnapshotLifecycle(
        reservation_id="1" * 32,
        attempt_id="2" * 32,
        generation=1,
        state="receiving",
        authorization_expires_at=2000,
        reserved_content_bytes=RESERVED_CONTENT_BYTES,
        raw_basename="2" * 32 + ".raw",
        normalized_basename="2" * 32 + ".normalized",
    )


def content():
    snapshot = parse_csv_snapshot(
        RAW,
        content_length=len(RAW),
        content_sha256=hashlib.sha256(RAW).hexdigest(),
        media_type="text/csv",
    )
    return snapshot, encode_snapshot(snapshot)


def manifest(owner):
    snapshot, canonical = content()
    raw_identity, normalized_identity = owner.identities()
    return SnapshotManifest(
        snapshot_id="3" * 32,
        reservation_id="1" * 32,
        attempt_id="2" * 32,
        generation=1,
        raw_content_sha256=hashlib.sha256(RAW).hexdigest(),
        normalized_sha256=hashlib.sha256(canonical).hexdigest(),
        raw_length=len(RAW),
        normalized_length=len(canonical),
        row_count=1,
        column_count=2,
        parser_profile=PARSER_PROFILE,
        raw_identity=raw_identity,
        normalized_identity=normalized_identity,
        source_expires_at=2000,
    )


def opened(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    files = implementation().SnapshotFiles(root)
    files.open_root()
    return files, root


def populate(owner):
    owner.append(expected_offset=0, chunk=RAW)
    owner.seal_raw(
        content_length=len(RAW), content_sha256=hashlib.sha256(RAW).hexdigest()
    )
    os.write(owner.normalized_fd, content()[1])
    value = manifest(owner)
    owner.verify_and_sync(value)
    return value


def test_exclusive_fixed_files_never_overwrite_and_require_identity_for_cleanup(
    tmp_path,
):
    files, root = opened(tmp_path)
    first = files.allocate(attempt())
    first.create()
    assert len(list(root.iterdir())) == 2
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in root.iterdir())
    assert not os.get_inheritable(first.raw_fd)
    assert not os.get_inheritable(first.normalized_fd)
    second = files.allocate(attempt())
    with pytest.raises(ReservationError):
        second.create()
    second.retire(remove_incomplete=True)
    assert len(list(root.iterdir())) == 2
    populate(first)
    first.retire(remove_incomplete=True)
    assert list(root.iterdir()) == []
    files.close()


def test_completed_bytes_are_protected_and_reopen_only_exact_manifest(tmp_path):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    value = populate(owner)
    owner.protect_publication()
    with pytest.raises(ReservationError):
        owner.retire(remove_incomplete=True)
    owner.retire(remove_incomplete=False)
    reopened = files.allocate_complete(value)
    reopened.open_complete()
    reopened.verify_and_sync(value)
    assert os.pread(reopened.raw_fd, len(RAW), 0) == RAW
    with pytest.raises(ReservationError):
        reopened.retire(remove_incomplete=True)
    reopened.retire(remove_incomplete=False)
    files.close()
    assert len(list(root.iterdir())) == 2


@pytest.mark.parametrize("method", ["_open_descriptor", "_adopt_file"])
@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("index", [0, 1])
def test_creation_fault_keeps_owner_and_every_captured_descriptor(
    tmp_path, monkeypatch, method, after, index
):
    files, root = opened(tmp_path)
    before = len(os.listdir("/proc/self/fd"))
    owner = files.allocate(attempt())
    original = getattr(owner, method)
    calls = 0

    def fail(item, create):
        nonlocal calls
        current = calls
        calls += 1
        if current != index:
            return original(item, create)
        if after:
            original(item, create)
        raise OSError("PRIVATE_OPEN_ERROR")

    monkeypatch.setattr(owner, method, fail)
    with pytest.raises(ReservationError) as error:
        owner.create()
    assert "PRIVATE_" not in str(error.value)
    assert owner in files._owners
    with pytest.raises(ReservationError):
        files.close()
    monkeypatch.undo()
    owner.retire(remove_incomplete=True)
    assert list(root.iterdir()) == []
    assert len(os.listdir("/proc/self/fd")) == before
    files.close()


@pytest.mark.parametrize("method", ["_open_root_fd", "_close_root_fd"])
@pytest.mark.parametrize("after", [False, True])
def test_root_effects_are_captured_before_exceptions(
    tmp_path, monkeypatch, method, after
):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    before = len(os.listdir("/proc/self/fd"))
    files = implementation().SnapshotFiles(root)
    if method == "_close_root_fd":
        files.open_root()
    original = getattr(files, method)

    def fail():
        if after:
            original()
        raise OSError("PRIVATE_ROOT_ERROR")

    monkeypatch.setattr(files, method, fail)
    with pytest.raises(ReservationError):
        files.open_root() if method == "_open_root_fd" else files.close()
    monkeypatch.undo()
    files.close()
    assert len(os.listdir("/proc/self/fd")) == before
    with pytest.raises(ReservationError):
        files.open_root()


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("after", [False, True])
def test_close_fault_retry_never_closes_reused_unrelated_descriptor(
    tmp_path, monkeypatch, index, after
):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    original = owner._close_file
    calls = 0
    unrelated = []

    def fail(item):
        nonlocal calls
        current = calls
        calls += 1
        if current != index:
            return original(item)
        if after:
            released = item.file.fileno()
            original(item)
            descriptor = os.open(root / "unrelated", os.O_CREAT | os.O_RDWR, 0o600)
            assert descriptor == released
            unrelated.append(descriptor)
        raise OSError("PRIVATE_CLOSE_ERROR")

    monkeypatch.setattr(owner, "_close_file", fail)
    with pytest.raises(ReservationError):
        owner.retire(remove_incomplete=False)
    assert owner in files._owners
    monkeypatch.undo()
    owner.retire(remove_incomplete=False)
    for descriptor in unrelated:
        os.fstat(descriptor)
        os.close(descriptor)
    files.close()


@pytest.mark.parametrize("after", [False, True])
def test_fsync_fault_closes_publication_and_retains_cleanable_files(
    tmp_path, monkeypatch, after
):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    owner.append(expected_offset=0, chunk=RAW)
    owner.seal_raw(
        content_length=len(RAW), content_sha256=hashlib.sha256(RAW).hexdigest()
    )
    os.write(owner.normalized_fd, content()[1])
    value = manifest(owner)
    original = owner._fsync_file

    def fail(item):
        if after:
            original(item)
        raise OSError("PRIVATE_SYNC_ERROR")

    monkeypatch.setattr(owner, "_fsync_file", fail)
    with pytest.raises(ReservationError):
        owner.verify_and_sync(value)
    with pytest.raises(ReservationError):
        owner.protect_publication()
    monkeypatch.undo()
    owner.retire(remove_incomplete=True)
    assert not list(root.iterdir())
    files.close()


@pytest.mark.parametrize("effect", ["partial", "before", "after"])
def test_write_failure_never_allows_resume_or_seal(tmp_path, monkeypatch, effect):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    original = owner._write_raw

    def fail(chunk):
        if effect == "partial":
            return original(chunk[:3])
        if effect == "after":
            original(chunk)
        raise OSError(28, "PRIVATE_DISK_FULL")

    monkeypatch.setattr(owner, "_write_raw", fail)
    with pytest.raises(ReservationError):
        owner.append(expected_offset=0, chunk=RAW)
    monkeypatch.undo()
    with pytest.raises(ReservationError):
        owner.append(expected_offset=0, chunk=RAW)
    with pytest.raises(ReservationError):
        owner.seal_raw(
            content_length=len(RAW), content_sha256=hashlib.sha256(RAW).hexdigest()
        )
    owner.retire(remove_incomplete=True)
    assert not list(root.iterdir())
    files.close()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode", "identity"])
def test_completed_open_rejects_replaced_or_nonprivate_bytes(tmp_path, kind):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    value = populate(owner)
    owner.protect_publication()
    owner.retire(remove_incomplete=False)
    raw = root / attempt().raw_basename
    backup = root / "original"
    if kind == "hardlink":
        os.link(raw, backup)
    elif kind == "mode":
        raw.chmod(0o644)
    else:
        raw.rename(backup)
        if kind == "symlink":
            raw.symlink_to(backup)
        else:
            raw.write_bytes(RAW)
            raw.chmod(0o600)
    reopened = files.allocate_complete(value)
    with pytest.raises(ReservationError):
        reopened.open_complete()
    reopened.retire(remove_incomplete=False)
    files.close()
    assert raw.exists()


def test_replacement_denies_writes_and_cleanup_never_deletes_replacement(tmp_path):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    raw = root / attempt().raw_basename
    original = root / "original"
    raw.rename(original)
    raw.write_bytes(b"UNRELATED_PRIVATE_CANARY")
    raw.chmod(0o600)
    with pytest.raises(ReservationError):
        owner.append(expected_offset=0, chunk=RAW)
    with pytest.raises(ReservationError):
        owner.retire(remove_incomplete=True)
    assert raw.read_bytes() == b"UNRELATED_PRIVATE_CANARY"
    owner.retire(remove_incomplete=False)
    files.close()


@pytest.mark.parametrize("bad", ["mode", "symlink", "file"])
def test_root_is_private_real_directory_without_repairs(tmp_path, bad):
    root = tmp_path / "root"
    if bad == "file":
        root.write_bytes(b"unrelated")
    elif bad == "symlink":
        destination = tmp_path / "destination"
        destination.mkdir(mode=0o700)
        root.symlink_to(destination, target_is_directory=True)
    else:
        root.mkdir(mode=0o755)
        root.chmod(0o755)
        assert root.stat().st_mode & 0o777 == 0o755
    files = implementation().SnapshotFiles(root)
    with pytest.raises(ReservationError):
        files.open_root()
    files.close()
    assert root.exists()


@pytest.mark.parametrize("target", ["manager", "owner"])
def test_copied_owner_cannot_use_or_close_original(tmp_path, target):
    import copy

    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    if target == "manager":
        clone = copy.copy(files)
        with pytest.raises(ReservationError):
            clone.close()
        with pytest.raises(ReservationError):
            clone.allocate(attempt())
    else:
        clone = copy.copy(owner)
        with pytest.raises(ReservationError):
            clone.append(expected_offset=0, chunk=RAW)
        with pytest.raises(ReservationError):
            clone.retire(remove_incomplete=True)
    populate(owner)
    owner.retire(remove_incomplete=True)
    files.close()


@pytest.mark.parametrize("operation", ["append", "retire"])
def test_inflight_io_denies_concurrent_actions_without_blocking_root_close(
    tmp_path, monkeypatch, operation
):
    import concurrent.futures
    import threading

    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    entered, release = threading.Event(), threading.Event()
    method = "_write_raw" if operation == "append" else "_close_file"
    original = getattr(owner, method)

    def blocked(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)

    monkeypatch.setattr(owner, method, blocked)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        running = (
            pool.submit(owner.append, expected_offset=0, chunk=RAW)
            if operation == "append"
            else pool.submit(owner.retire, remove_incomplete=True)
        )
        try:
            assert entered.wait(1)
            closing = pool.submit(files.close)
            with pytest.raises(ReservationError):
                closing.result(timeout=0.5)
            for call in (
                lambda: owner.raw_fd,
                owner.protect_publication,
                lambda: owner.retire(remove_incomplete=True),
            ):
                with pytest.raises(ReservationError):
                    call()
        finally:
            release.set()
        running.result(timeout=2)
    monkeypatch.undo()
    owner.retire(remove_incomplete=False)
    files.close()


def test_protection_wins_before_commit_and_cannot_be_cleared_for_cleanup(tmp_path):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    populate(owner)
    owner.protect_publication()
    # A later pre-SQL denial grants no permission to clear the denying marker.
    with pytest.raises(ReservationError):
        owner.retire(remove_incomplete=True)
    owner.retire(remove_incomplete=False)
    files.close()
    assert len(list(root.iterdir())) == 2


@pytest.mark.parametrize("after", [False, True])
def test_final_registration_release_fault_preserves_positive_retirement(
    tmp_path, after
):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()

    class FaultingSet(set):
        def remove(self, value):
            if after:
                super().remove(value)
            raise KeyboardInterrupt("synthetic release interruption")

    files._owners = FaultingSet(files._owners)
    with pytest.raises(KeyboardInterrupt):
        owner.retire(remove_incomplete=True)
    assert list(root.iterdir()) == []
    if not after:
        with pytest.raises(ReservationError):
            files.close()
    files._owners = set(files._owners)
    owner.retire(remove_incomplete=True)
    files.close()


@pytest.mark.parametrize("after", [False, True])
def test_deletion_directory_sync_failure_retains_owner_until_real_sync(
    tmp_path, monkeypatch, after
):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    original = os.fsync
    seen = []

    def fail(fd):
        if fd == files._fd:
            seen.append(fd)
            if after:
                original(fd)
            raise OSError("PRIVATE_DIR_SYNC_ERROR")
        return original(fd)

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(ReservationError):
        owner.retire(remove_incomplete=True)
    assert seen
    assert owner in files._owners
    with pytest.raises(ReservationError):
        files.close()
    monkeypatch.undo()
    owner.retire(remove_incomplete=True)
    files.close()


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("after", [False, True])
def test_completed_open_faults_retain_only_owned_descriptors(
    tmp_path, monkeypatch, index, after
):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    value = populate(owner)
    owner.protect_publication()
    owner.retire(remove_incomplete=False)
    before = len(os.listdir("/proc/self/fd"))
    reopened = files.allocate_complete(value)
    original = reopened._open_descriptor
    calls = 0

    def fail(item, create):
        nonlocal calls
        current = calls
        calls += 1
        if current != index:
            return original(item, create)
        if after:
            original(item, create)
        raise OSError("PRIVATE_REOPEN_ERROR")

    monkeypatch.setattr(reopened, "_open_descriptor", fail)
    with pytest.raises(ReservationError):
        reopened.open_complete()
    monkeypatch.undo()
    reopened.retire(remove_incomplete=False)
    assert len(os.listdir("/proc/self/fd")) == before
    assert len(list(root.iterdir())) == 2
    files.close()


@pytest.mark.parametrize(
    "offset,chunk",
    [(1, RAW), (True, RAW), (0, b""), (0, bytearray(RAW)), (0, b"x" * (65536 + 1))],
)
def test_append_requires_exact_offset_and_bounded_nonempty_bytes(
    tmp_path, offset, chunk
):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    with pytest.raises(ReservationError):
        owner.append(expected_offset=offset, chunk=chunk)
    assert (root / attempt().raw_basename).stat().st_size == 0
    owner.retire(remove_incomplete=True)
    files.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_content_sha256", "0" * 64),
        ("normalized_sha256", "0" * 64),
        ("raw_length", 2),
        ("normalized_length", 2),
        ("row_count", 0),
        ("column_count", 1),
        ("generation", 2),
        ("attempt_id", "a" * 32),
    ],
)
def test_manifest_verification_rejects_wrong_bytes_shape_or_attempt(
    tmp_path, field, value
):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    original = populate(owner)
    with pytest.raises(ReservationError):
        owner.verify_and_sync(replace(original, **{field: value}))
    owner.retire(remove_incomplete=True)
    files.close()


def test_observed_allocated_overage_is_rejected_without_claiming_hard_fs_quota(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    fd = owner.raw_fd
    original = os.fstat

    def oversized(descriptor):
        info = original(descriptor)
        if descriptor != fd:
            return info
        values = {
            name: getattr(info, name) for name in dir(info) if name.startswith("st_")
        }
        values["st_blocks"] = (1024 * 1024) // 512 + 1
        return SimpleNamespace(**values)

    monkeypatch.setattr(os, "fstat", oversized)
    with pytest.raises(ReservationError):
        owner.identities()
    monkeypatch.undo()
    owner.retire(remove_incomplete=True)
    files.close()


def test_fork_inherited_owners_reject_before_inherited_mutex(tmp_path):
    import select
    import signal

    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    read_fd, write_fd = os.pipe()
    files._lock.acquire()
    owner._lock.acquire()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(read_fd)
            denied = 0
            for call in (files.close, lambda: owner.retire(remove_incomplete=True)):
                try:
                    call()
                except ReservationError:
                    denied += 1
            os.write(write_fd, str(denied).encode())
        finally:
            os._exit(0)
    os.close(write_fd)
    try:
        ready, _, _ = select.select([read_fd], [], [], 2)
        if not ready:
            os.kill(pid, signal.SIGKILL)
        assert ready and os.read(read_fd, 2) == b"2"
    finally:
        os.waitpid(pid, 0)
        os.close(read_fd)
        owner._lock.release()
        files._lock.release()
        owner.retire(remove_incomplete=True)
        files.close()


@pytest.mark.parametrize("failure", ["adoption", "raw_close"])
def test_uncertain_fd_handoff_never_retries_a_reused_integer(tmp_path, failure):
    import subprocess
    import sys

    script = r"""
import os, sys
from pathlib import Path
from unittest.mock import patch
from src.services.source_ingress import snapshot_files as module
from src.services.source_ingress.snapshot_contracts import SnapshotLifecycle, RESERVED_CONTENT_BYTES
from src.services.source_ingress.reservation_contracts import ReservationError
root = Path(sys.argv[1]); root.mkdir(mode=0o700)
files = module.SnapshotFiles(root); files.open_root()
value = SnapshotLifecycle("1"*32,"2"*32,1,"receiving",2000,RESERVED_CONTENT_BYTES,"2"*32+".raw","2"*32+".normalized")
owner = files.allocate(value)
unrelated = []
if sys.argv[2] == "adoption":
    real = module.io.FileIO
    def broken(*args, **kwargs):
        wrapper = real(*args, **kwargs)
        released = wrapper.fileno(); wrapper.close()
        descriptor = os.open(root / "unrelated", os.O_CREAT | os.O_RDWR, 0o600)
        assert descriptor == released
        unrelated.append(descriptor)
        raise OSError("synthetic post-handoff error")
    with patch.object(module.io, "FileIO", broken):
        try: owner.create()
        except ReservationError: pass
        else: raise AssertionError("admission unexpectedly succeeded")
else:
    real_open = owner._open_descriptor
    def broken_open(item, create):
        real_open(item, create)
        raise OSError("synthetic pre-handoff error")
    with patch.object(owner, "_open_descriptor", broken_open):
        try: owner.create()
        except ReservationError: pass
        else: raise AssertionError("admission unexpectedly succeeded")
    target = owner._raw.raw_fd
    real_close = os.close
    def broken_close(fd):
        assert fd == target
        real_close(fd)
        descriptor = os.open(root / "unrelated", os.O_CREAT | os.O_RDWR, 0o600)
        assert descriptor == fd
        unrelated.append(descriptor)
        raise OSError("synthetic uncertain close")
    with patch.object(os, "close", broken_close):
        try: owner.retire(remove_incomplete=False)
        except ReservationError: pass
        else: raise AssertionError("unknown close reported retired")
for _ in range(2):
    try: owner.retire(remove_incomplete=False)
    except ReservationError: pass
    else: raise AssertionError("uncertain owner retired")
    os.fstat(unrelated[0])
try: files.close()
except ReservationError: pass
else: raise AssertionError("uncertain owner released root")
os.close(unrelated[0])
print("retained safely until disposable process exit")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "child"), failure],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "retained safely until disposable process exit"


def test_creation_before_identity_never_deletes_by_name(tmp_path, monkeypatch):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    original = os.fstat

    def fail(fd):
        if fd == owner._raw.raw_fd:
            raise OSError("synthetic identity failure")
        return original(fd)

    monkeypatch.setattr(os, "fstat", fail)
    with pytest.raises(ReservationError):
        owner.create()
    monkeypatch.undo()
    with pytest.raises(ReservationError):
        owner.retire(remove_incomplete=True)
    owner.retire(remove_incomplete=False)
    files.close()
    assert (root / attempt().raw_basename).exists()


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("index", [0, 1])
def test_unlink_effects_are_retained_until_directory_sync_and_close(
    tmp_path, monkeypatch, after, index
):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    original = owner._unlink_file
    calls = 0

    def fail(item):
        nonlocal calls
        current = calls
        calls += 1
        if current != index:
            return original(item)
        if after:
            original(item)
        raise OSError("PRIVATE_UNLINK_ERROR")

    monkeypatch.setattr(owner, "_unlink_file", fail)
    with pytest.raises(ReservationError):
        owner.retire(remove_incomplete=True)
    with pytest.raises(ReservationError):
        owner.protect_publication()
    assert owner in files._owners
    monkeypatch.undo()
    owner.retire(remove_incomplete=True)
    assert not list(root.iterdir())
    files.close()


def test_raw_byte_cap_is_enforced_before_an_extra_write(tmp_path):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    chunk = b"x" * 65536
    for offset in range(0, 1024 * 1024, len(chunk)):
        owner.append(expected_offset=offset, chunk=chunk)
    with pytest.raises(ReservationError):
        owner.append(expected_offset=1024 * 1024, chunk=b"x")
    assert (root / attempt().raw_basename).stat().st_size == 1024 * 1024
    owner.retire(remove_incomplete=True)
    files.close()


@pytest.mark.parametrize("protected", [False, True])
def test_retained_descriptor_retirement_never_acknowledges_later_deletion(
    tmp_path, protected
):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    populate(owner)
    if protected:
        owner.protect_publication()
    owner.retire(remove_incomplete=False)
    owner.retire(remove_incomplete=False)
    with pytest.raises(ReservationError):
        owner.retire(remove_incomplete=True)
    assert len(list(root.iterdir())) == 2
    files.close()


def test_actual_synchronized_deletion_is_idempotent_after_retirement(tmp_path):
    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    owner.retire(remove_incomplete=True)
    owner.retire(remove_incomplete=True)
    assert not list(root.iterdir())
    files.close()


def test_completed_fifo_replacement_is_rejected_without_waiting_for_writer(tmp_path):
    import concurrent.futures

    files, root = opened(tmp_path)
    owner = files.allocate(attempt())
    owner.create()
    value = populate(owner)
    owner.protect_publication()
    owner.retire(remove_incomplete=False)
    raw = root / attempt().raw_basename
    raw.unlink()
    os.mkfifo(raw, 0o600)
    reopened = files.allocate_complete(value)
    blocked = False
    releaser = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        call = pool.submit(reopened.open_complete)
        try:
            with pytest.raises(ReservationError):
                call.result(timeout=0.5)
        except concurrent.futures.TimeoutError:
            blocked = True
            releaser = os.open(raw, os.O_RDWR | os.O_NONBLOCK)
            with pytest.raises(ReservationError):
                call.result(timeout=2)
        finally:
            if releaser is not None:
                os.close(releaser)
    reopened.retire(remove_incomplete=False)
    files.close()
    assert not blocked, (
        "non-regular open waited for a FIFO writer before type validation"
    )
