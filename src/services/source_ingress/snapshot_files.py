"""Private fixed-name files with captured, retryable descriptor ownership.

These helpers grant no upload, publication or read authority. Callers must own
all users of exported descriptors (including an actually retired parser child)
before cleanup. The private directory admits only coordinated trusted writers;
it is not a filesystem sandbox against arbitrary same-UID processes.
"""

from __future__ import annotations

import hashlib
import io
import os
import stat
import threading
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from src.services.source_ingress.csv_snapshot import MAX_NORMALIZED_BYTES, MAX_RAW_BYTES
from src.services.source_ingress.reservation_contracts import ReservationError
from src.services.source_ingress.snapshot_codec import decode_snapshot
from src.services.source_ingress.snapshot_contracts import (
    MAX_COMPLETED_SNAPSHOTS,
    MAX_CONTENT_BYTES,
    SnapshotLifecycle,
    SnapshotManifest,
)

MAX_CHUNK_BYTES = 64 * 1024


def _unavailable() -> ReservationError:
    return ReservationError("reservation_unavailable")


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _private(info: os.stat_result, *, directory: bool = False) -> None:
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not kind(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
        or (not directory and info.st_nlink != 1)
    ):
        raise _unavailable()


class SnapshotFiles:
    """Captured root owner. Construction is inert; close never steals file owners."""

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise _unavailable()
        self._root = root
        self._pid = os.getpid()
        self._self = weakref.ref(self)
        self._lock = threading.Lock()
        self._fd: int | None = None
        self._root_identity = None
        self._attempted = False
        self._running = False
        self._ready = False
        self._closing = False
        self._uncertain = False
        self._owners: set[OwnedSnapshotFiles] = set()
        self._scan = None

    def _require_identity(self) -> None:
        if self._pid != os.getpid() or self._self() is not self:
            raise _unavailable()

    def _open_root_fd(self) -> None:
        self._fd = os.open(
            self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )

    def _check_root(self) -> None:
        self._require_identity()
        if self._fd is None or self._uncertain:
            raise _unavailable()
        descriptor = os.fstat(self._fd)
        path = os.stat(self._root, follow_symlinks=False)
        _private(descriptor, directory=True)
        _private(path, directory=True)
        if _identity(descriptor) != _identity(path) or (
            self._root_identity is not None
            and _identity(descriptor) != self._root_identity
        ):
            raise _unavailable()

    def open_root(self) -> None:
        self._require_identity()
        with self._lock:
            if self._attempted or self._closing or self._running:
                raise _unavailable()
            self._attempted = self._running = True
        try:
            self._open_root_fd()
            self._check_root()
            self._root_identity = _identity(os.fstat(self._fd))
            self._ready = True
        except Exception:
            raise _unavailable() from None
        finally:
            with self._lock:
                self._running = False

    def _allocate(self, value, *, recovery=False) -> OwnedSnapshotFiles:
        self._require_identity()
        with self._lock:
            if not self._ready or self._closing or self._running or self._uncertain:
                raise _unavailable()
            owner = OwnedSnapshotFiles(self, value, recovery=recovery)
            self._owners.add(owner)
            return owner

    def allocate(self, attempt: SnapshotLifecycle) -> OwnedSnapshotFiles:
        if (
            type(attempt) is not SnapshotLifecycle
            or attempt.state != "receiving"
            or attempt.raw_identity is not None
            or attempt.normalized_identity is not None
        ):
            raise _unavailable()
        attempt.__post_init__()
        return self._allocate(attempt)

    def allocate_complete(self, manifest: SnapshotManifest) -> OwnedSnapshotFiles:
        if type(manifest) is not SnapshotManifest:
            raise _unavailable()
        manifest.__post_init__()
        return self._allocate(manifest)

    def allocate_recovery(self, attempt: SnapshotLifecycle) -> OwnedSnapshotFiles:
        """Capture incomplete cleanup only; the startup owner proves eligibility."""
        if (
            type(attempt) is not SnapshotLifecycle
            or attempt.state == "complete"
            or not attempt.cleanup_pending
        ):
            raise _unavailable()
        attempt.__post_init__()
        return self._allocate(attempt, recovery=True)

    def audit(self, expected: dict) -> None:
        """Observe bounded fixed names; never adopt, repair or open their contents."""
        self._require_identity()
        with self._lock:
            if (
                not self._ready
                or self._closing
                or self._running
                or self._uncertain
                or self._scan is not None
            ):
                raise _unavailable()
            self._running = True
        try:
            self._check_root()
            if type(expected) is not dict or len(expected) > 2 * (
                MAX_COMPLETED_SNAPSHOTS + 2
            ):
                raise _unavailable()
            try:
                self._scan = os.scandir(self._fd)
            except BaseException:
                self._uncertain = True
                raise
            seen, length, allocated = set(), 0, 0
            for entry in self._scan:
                if entry.name not in expected or len(seen) >= len(expected):
                    raise _unavailable()
                identity, minimum, maximum, required = expected[entry.name]
                info = os.stat(entry.name, dir_fd=self._fd, follow_symlinks=False)
                _private(info)
                if (
                    identity is None
                    or _identity(info) != identity
                    or not minimum <= info.st_size <= maximum
                ):
                    raise _unavailable()
                seen.add(entry.name)
                length += info.st_size
                allocated += info.st_blocks * 512
                if length > MAX_CONTENT_BYTES or allocated > MAX_CONTENT_BYTES:
                    raise _unavailable()
            if any(
                required and name not in seen
                for name, (_, _, _, required) in expected.items()
            ):
                raise _unavailable()
            self._check_root()
        except Exception:
            raise _unavailable() from None
        finally:
            try:
                if self._scan is not None:
                    self._scan.close()
                    self._scan = None
            finally:
                with self._lock:
                    self._running = False

    def retire_audit(self) -> bool:
        """Retry the captured scan, or defer while a known root action runs."""
        self._require_identity()
        with self._lock:
            if self._running:
                return False
            self._running = True
        try:
            if self._scan is not None:
                self._scan.close()
                self._scan = None
            return True
        except Exception:
            raise _unavailable() from None
        finally:
            with self._lock:
                self._running = False

    def _close_root_fd(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except BaseException:
                self._uncertain = True
                raise
            self._fd = None

    def close(self) -> None:
        self._require_identity()
        with self._lock:
            self._closing = True
            if self._running or self._owners or self._uncertain:
                raise _unavailable()
            self._running = True
        try:
            if self._scan is not None:
                self._scan.close()
                self._scan = None
            self._close_root_fd()
            self._ready = False
        except Exception:
            raise _unavailable() from None
        finally:
            with self._lock:
                self._running = False


@dataclass(repr=False)
class _OwnedFile:
    name: str
    cap: int
    expected_identity: tuple[int, int] | None = None
    identity: tuple[int, int] | None = None
    file: io.FileIO | None = None
    raw_fd: int | None = None
    handed: bool = False
    uncertain: bool = False
    created: bool = False
    removed: bool = False


class OwnedSnapshotFiles:
    """One retained action at a time; failures never lose acquired handles."""

    def __init__(self, manager: SnapshotFiles, value, *, recovery=False) -> None:
        self._manager = manager
        self._value = value
        self._pid = os.getpid()
        self._self = weakref.ref(self)
        self._lock = threading.Lock()
        self._running = False
        self._attempted = False
        self._active = False
        self._failed = False
        self._retirement_started = False
        self._retired = False
        self._cleanup_finished = False
        self._deletion_completed = False
        self._recovery = recovery
        self._recovery_acquired = False
        self._verified_manifest = None
        self._directory_dirty = False
        self._protected = type(value) is SnapshotManifest
        self._sealed = self._protected
        self._offset = 0
        self._raw = _OwnedFile(
            value.attempt_id + ".raw", MAX_RAW_BYTES, value.raw_identity
        )
        self._normalized = _OwnedFile(
            value.attempt_id + ".normalized",
            MAX_NORMALIZED_BYTES,
            value.normalized_identity,
        )

    def _require_identity(self) -> None:
        if self._pid != os.getpid() or self._self() is not self:
            raise _unavailable()
        self._manager._require_identity()
        if not self._retired and self not in self._manager._owners:
            if not self._cleanup_finished:
                raise _unavailable()
            # Only this exact original owner recorded all prior retirement.
            # An interrupted after-effect registry release is now reconcilable.
            self._retired = True

    @contextmanager
    def _action(self, *, acquire: bool = False):
        self._require_identity()
        with self._lock:
            if (
                self._running
                or self._retirement_started
                or self._retired
                or self._failed
            ):
                raise _unavailable()
            if acquire:
                if self._attempted:
                    raise _unavailable()
                self._attempted = True
            elif not self._active:
                raise _unavailable()
            self._running = True
        try:
            self._manager._check_root()
            yield
        except BaseException as error:
            self._failed = True
            if isinstance(error, Exception):
                raise _unavailable() from None
            raise
        finally:
            with self._lock:
                self._running = False

    def _open_descriptor(self, item: _OwnedFile, create: bool) -> None:
        flags = (
            os.O_NOFOLLOW
            | os.O_CLOEXEC
            | (
                os.O_RDWR | os.O_CREAT | os.O_EXCL
                if create
                else os.O_RDONLY | os.O_NONBLOCK
            )
        )
        item.raw_fd = os.open(item.name, flags, 0o600, dir_fd=self._manager._fd)
        item.created = create
        opened = os.fstat(item.raw_fd)
        item.identity = _identity(opened)
        _private(opened)

    def _adopt_file(self, item: _OwnedFile, create: bool) -> None:
        def opener(_name, _flags):
            self._open_descriptor(item, create)
            item.handed = True
            return item.raw_fd

        try:
            item.file = io.FileIO(item.name, "r+b" if create else "rb", opener=opener)
            item.raw_fd = None
        except BaseException:
            if item.handed and item.file is None:
                item.uncertain = True
            raise

    def _check_file(self, item: _OwnedFile, *, cleanup: bool = False) -> os.stat_result:
        if item.uncertain or item.removed:
            raise _unavailable()
        if item.file is not None and not item.file.closed:
            fd = item.file.fileno()
        elif cleanup and not item.handed and item.raw_fd is not None:
            fd = item.raw_fd
        else:
            raise _unavailable()
        info = os.fstat(fd)
        path = os.stat(item.name, dir_fd=self._manager._fd, follow_symlinks=False)
        _private(info)
        _private(path)
        if (
            _identity(info) != item.identity
            or _identity(path) != item.identity
            or (
                item.expected_identity is not None
                and item.identity != item.expected_identity
            )
            or max(info.st_size, info.st_blocks * 512) > item.cap
            or os.get_inheritable(fd)
        ):
            raise _unavailable()
        return info

    def create(self) -> None:
        with self._action(acquire=True):
            if type(self._value) is not SnapshotLifecycle or self._recovery:
                raise _unavailable()
            for item in (self._raw, self._normalized):
                self._adopt_file(item, True)
                self._check_file(item)
            self._active = True

    def open_recovery(self) -> None:
        """Adopt recorded incomplete identities, never infer them from names."""
        with self._action(acquire=True):
            if not self._recovery:
                raise _unavailable()
            for item in (self._raw, self._normalized):
                try:
                    info = os.stat(
                        item.name, dir_fd=self._manager._fd, follow_symlinks=False
                    )
                except FileNotFoundError:
                    item.removed = True
                    continue
                _private(info)
                if (
                    item.expected_identity is None
                    or _identity(info) != item.expected_identity
                ):
                    raise _unavailable()
                self._adopt_file(item, False)
                self._check_file(item)
                # A startup-verified original file has the same deletion right
                # as this process's exclusively created incomplete file.
                item.created = True
            self._directory_dirty = True  # Persist even already-absent names.
            self._recovery_acquired = self._active = True

    def open_complete(self) -> None:
        with self._action(acquire=True):
            if type(self._value) is not SnapshotManifest:
                raise _unavailable()
            for item in (self._raw, self._normalized):
                self._adopt_file(item, False)
                self._check_file(item)
            self._verify(self._value)
            self._active = True

    def identities(self) -> tuple[tuple[int, int], tuple[int, int]]:
        with self._action():
            self._check_file(self._raw)
            self._check_file(self._normalized)
            return self._raw.identity, self._normalized.identity

    @property
    def raw_fd(self) -> int:
        """Trusted parser/read owner only; exported FD has no child-exit proof."""
        with self._action():
            self._check_file(self._raw)
            return self._raw.file.fileno()

    @property
    def normalized_fd(self) -> int:
        with self._action():
            self._check_file(self._normalized)
            return self._normalized.file.fileno()

    def _write_raw(self, chunk: bytes) -> int:
        return os.pwrite(self._raw.file.fileno(), chunk, self._offset)

    def append(self, *, expected_offset: int, chunk: bytes) -> None:
        with self._action():
            if (
                self._sealed
                or type(expected_offset) is not int
                or expected_offset != self._offset
                or type(chunk) is not bytes
                or not 0 < len(chunk) <= MAX_CHUNK_BYTES
                or self._offset + len(chunk) > MAX_RAW_BYTES
            ):
                raise _unavailable()
            if self._check_file(self._raw).st_size != self._offset:
                raise _unavailable()
            if self._write_raw(chunk) != len(chunk):
                raise _unavailable()
            self._offset += len(chunk)
            if self._check_file(self._raw).st_size != self._offset:
                raise _unavailable()

    def _read(self, item: _OwnedFile) -> bytes:
        size = self._check_file(item).st_size
        result = bytearray()
        while len(result) < size:
            block = os.pread(
                item.file.fileno(),
                min(MAX_CHUNK_BYTES, size - len(result)),
                len(result),
            )
            if not block:
                raise _unavailable()
            result.extend(block)
        if self._check_file(item).st_size != size:
            raise _unavailable()
        return bytes(result)

    def seal_raw(self, *, content_length: int, content_sha256: str) -> None:
        with self._action():
            if (
                self._sealed
                or type(content_length) is not int
                or content_length != self._offset
                or not 0 < content_length <= MAX_RAW_BYTES
                or type(content_sha256) is not str
                or len(content_sha256) != 64
            ):
                raise _unavailable()
            if hashlib.sha256(self._read(self._raw)).hexdigest() != content_sha256:
                raise _unavailable()
            self._sealed = True

    def _verify(self, manifest: SnapshotManifest) -> None:
        if type(manifest) is not SnapshotManifest or not self._sealed:
            raise _unavailable()
        manifest.__post_init__()
        if (
            any(
                getattr(manifest, name) != getattr(self._value, name)
                for name in ("reservation_id", "attempt_id", "generation")
            )
            or manifest.raw_identity != self._raw.identity
            or manifest.normalized_identity != self._normalized.identity
            or (type(self._value) is SnapshotManifest and manifest != self._value)
        ):
            raise _unavailable()
        raw = self._read(self._raw)
        normalized = self._read(self._normalized)
        if (
            len(raw) != manifest.raw_length
            or len(normalized) != manifest.normalized_length
            or hashlib.sha256(raw).hexdigest() != manifest.raw_content_sha256
        ):
            raise _unavailable()
        snapshot = decode_snapshot(
            normalized,
            raw_content_sha256=manifest.raw_content_sha256,
            expected_identity=manifest.normalized_sha256,
            row_count=manifest.row_count,
            column_count=manifest.column_count,
        )
        self._verified_manifest = manifest
        return snapshot

    def read_complete(self):
        """Materialize exact private values; caller still owns read authorization."""
        with self._action():
            if type(self._value) is not SnapshotManifest or not self._protected:
                raise _unavailable()
            return self._verify(self._value)

    def _fsync_file(self, item: _OwnedFile) -> None:
        os.fsync(item.file.fileno())

    def verify_and_sync(self, manifest: SnapshotManifest) -> None:
        with self._action():
            self._verify(manifest)
            self._fsync_file(self._raw)
            self._fsync_file(self._normalized)
            os.fsync(self._manager._fd)
            self._check_file(self._raw)
            self._check_file(self._normalized)
            self._manager._check_root()

    def protect_publication(self) -> None:
        """Irreversibly deny deletion, without publishing bytes or doing I/O."""
        self._require_identity()
        with self._lock:
            if (
                self._running
                or self._retirement_started
                or self._retired
                or self._failed
                or not self._active
            ):
                raise _unavailable()
            self._protected = True

    def _unlink_file(self, item: _OwnedFile) -> None:
        self._check_file(item, cleanup=True)
        self._directory_dirty = True
        os.unlink(item.name, dir_fd=self._manager._fd)
        item.removed = True

    def _close_file(self, item: _OwnedFile) -> None:
        if item.uncertain:
            raise _unavailable()
        if item.file is not None:
            if not item.file.closed:
                item.file.close()
            if not item.file.closed:
                raise _unavailable()
            item.file = None
            item.raw_fd = None
        elif item.raw_fd is not None:
            try:
                os.close(item.raw_fd)
            except BaseException:
                item.uncertain = True
                raise
            item.raw_fd = None

    def retire(self, *, remove_incomplete: bool) -> None:
        """Retry captured cleanup only; caller must first retire every FD user."""
        self._require_identity()
        if type(remove_incomplete) is not bool:
            raise _unavailable()
        with self._lock:
            if remove_incomplete and self._protected:
                raise _unavailable()
            if remove_incomplete and self._recovery and not self._recovery_acquired:
                raise _unavailable()
            if self._retired:
                if remove_incomplete and not self._deletion_completed:
                    raise _unavailable()
                return
            if self._running:
                raise _unavailable()
            self._retirement_started = self._running = True
            self._active = False
        try:
            for item in (self._normalized, self._raw):
                if remove_incomplete and item.created and not item.removed:
                    self._manager._check_root()
                    self._unlink_file(item)
                self._close_file(item)
            if self._directory_dirty:
                self._manager._check_root()
                os.fsync(self._manager._fd)
                self._manager._check_root()
                self._directory_dirty = False
            if remove_incomplete:
                self._deletion_completed = all(
                    not item.created or item.removed
                    for item in (self._raw, self._normalized)
                )
            self._cleanup_finished = True
            with self._manager._lock:
                self._manager._owners.remove(self)
                self._retired = True
        except Exception:
            raise _unavailable() from None
        finally:
            with self._lock:
                self._running = False
