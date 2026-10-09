"""Fixed, internal SQLite file-length profile; no admission authority.

The limits cover managed file lengths. Allocated blocks are observations and
can deny further work, not a hard filesystem/CoW/journal peak quota. Callers
must hold the real source-storage writer fence throughout inspection and use.
This module does not provision files or repair unsupported recovery artifacts.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import struct
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO

from src.services.agent_runs.private_storage import (
    require_private_directory,
    require_private_file,
)
from src.services.source_ingress.reservation_contracts import ReservationError

PAGE_BYTES = 4096
MAX_DB_PAGES = 4096
MAX_DB_BYTES = PAGE_BYTES * MAX_DB_PAGES
MAX_WAL_FRAMES = 4112
WAL_FRAME_BYTES = PAGE_BYTES + 24
MAX_WAL_BYTES = 32 + MAX_WAL_FRAMES * WAL_FRAME_BYTES
MAX_SHM_BYTES = 65536
MAX_METADATA_FILE_BYTES = 34 * 1024 * 1024
SQLITE_SOURCE_ID = (
    "2026-05-05 10:34:17 "
    "c88b22011a54b4f6fbd149e9f8e4de77658ce58143a1af0e3785e4e6475127e9"
)
_COMPILE_OPTIONS_SHA256 = (
    "054a2945f636bf3b8f648d6abe8ed75a02c74ce6d54dbad67d7ad1777b58d606"
)
_FILES = {
    "db": ("", MAX_DB_BYTES),
    "wal": ("-wal", MAX_WAL_BYTES),
    "shm": ("-shm", MAX_SHM_BYTES),
    "journal": ("-journal", 0),
}
_SETTINGS = {
    "page_size": PAGE_BYTES,
    "max_page_count": MAX_DB_PAGES,
    "auto_vacuum": 0,
    "journal_mode": "wal",
    "synchronous": 2,
    "cache_spill": 0,
    "cache_size": -16384,
    "temp_store": 2,
    "wal_autocheckpoint": 0,
    "journal_size_limit": 0,
    "automatic_index": 0,
    "mmap_size": 0,
    "trusted_schema": 0,
}
_Execute = Callable[[str], sqlite3.Cursor]


def _unavailable() -> ReservationError:
    return ReservationError("reservation_unavailable")


def _check_runtime(execute: _Execute) -> None:
    source = execute("SELECT sqlite_source_id()").fetchone()[0]
    options = sorted(row[0] for row in execute("PRAGMA compile_options"))
    if (
        sys.platform != "linux"
        or source != SQLITE_SOURCE_ID
        or hashlib.sha256("\n".join(options).encode()).hexdigest()
        != _COMPILE_OPTIONS_SHA256
    ):
        raise _unavailable()


def _verify_settings(execute: _Execute) -> None:
    for key, value in _SETTINGS.items():
        if execute("PRAGMA " + key).fetchone()[0] != value:
            raise _unavailable()
    if not 0 <= execute("PRAGMA page_count").fetchone()[0] <= MAX_DB_PAGES:
        raise _unavailable()


@dataclass(frozen=True, slots=True, repr=False)
class ManagedFile:
    length: int
    allocated_bytes: int
    identity: tuple[int, int] | None


@dataclass(frozen=True, slots=True, repr=False)
class ManagedFileInventory:
    files: Mapping[str, ManagedFile]
    managed_bytes: int
    allocated_bytes: int


class _InspectionFile:
    """Captured before open; only this exact file object may be retired."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: BinaryIO | None = None
        self.observed: ManagedFile | None = None

    def acquire(self, limit: int, *, required: bool) -> None:
        try:
            identity = require_private_file(self.path)
        except FileNotFoundError:
            if required:
                raise
            self.observed = ManagedFile(0, 0, None)
            return
        self.handle = open(
            self.path,
            "rb",
            buffering=0,
            opener=lambda path, flags: os.open(
                path, flags | os.O_NOFOLLOW | os.O_CLOEXEC
            ),
        )
        info = os.fstat(self.handle.fileno())
        if (info.st_dev, info.st_ino) != identity or info.st_size > limit:
            raise _unavailable()
        require_private_file(self.path, identity=identity)
        self.observed = ManagedFile(info.st_size, info.st_blocks * 512, identity)

    def read(self, offset: int, count: int) -> bytes:
        assert self.handle is not None
        self.handle.seek(offset)
        data = self.handle.read(count)
        if len(data) != count:
            raise _unavailable()
        return data

    def require_unchanged(self) -> None:
        assert self.observed is not None
        if self.observed.identity is None:
            if self.path.exists() or self.path.is_symlink():
                raise _unavailable()
            return
        assert self.handle is not None
        info = os.fstat(self.handle.fileno())
        require_private_file(self.path, identity=self.observed.identity)
        if (info.st_size, info.st_blocks * 512) != (
            self.observed.length,
            self.observed.allocated_bytes,
        ):
            raise _unavailable()

    def retire(self) -> None:
        if self.handle is not None:
            if not self.handle.closed:
                self.handle.close()
            if not self.handle.closed:
                raise _unavailable()
            self.handle = None


class _Inspection:
    def __init__(self) -> None:
        self.files: dict[str, _InspectionFile] = {}

    def acquire(self, path: Path, *, initializing: bool) -> ManagedFileInventory:
        require_private_directory(path.parent)
        for name, (suffix, limit) in _FILES.items():
            owned = _InspectionFile(Path(str(path) + suffix))
            self.files[name] = owned
            owned.acquire(limit, required=name == "db")
        db = self.files["db"]
        assert db.observed is not None
        if db.observed.length == 0:
            if not initializing or any(
                item.observed and item.observed.length
                for name, item in self.files.items()
                if name != "db"
            ):
                raise _unavailable()
        else:
            if db.observed.length % PAGE_BYTES:
                raise _unavailable()
            header = db.read(0, 100)
            if (
                header[:16] != b"SQLite format 3\0"
                or int.from_bytes(header[16:18], "big") != PAGE_BYTES
                or int.from_bytes(header[28:32], "big") > MAX_DB_PAGES
            ):
                raise _unavailable()
        wal = self.files["wal"]
        assert wal.observed is not None
        if wal.observed.length:
            if wal.observed.length < 32 or (wal.observed.length - 32) % WAL_FRAME_BYTES:
                raise _unavailable()
            magic, version, page_size = struct.unpack(">3I", wal.read(0, 12))
            if (
                magic not in (0x377F0682, 0x377F0683)
                or version != 3007000
                or page_size != PAGE_BYTES
            ):
                raise _unavailable()
            for offset in range(32, wal.observed.length, WAL_FRAME_BYTES):
                page, commit_pages = struct.unpack(">2I", wal.read(offset, 8))
                if not 1 <= page <= MAX_DB_PAGES or commit_pages > MAX_DB_PAGES:
                    raise _unavailable()
        observed = {}
        for name, owned in self.files.items():
            owned.require_unchanged()
            assert owned.observed is not None
            observed[name] = owned.observed
        managed = sum(item.length for item in observed.values())
        allocated = sum(item.allocated_bytes for item in observed.values())
        if max(managed, allocated) > MAX_METADATA_FILE_BYTES:
            raise _unavailable()
        return ManagedFileInventory(MappingProxyType(observed), managed, allocated)

    def retire(self) -> None:
        for item in reversed(tuple(self.files.values())):
            item.retire()


class SourceSqliteProfile:
    """Serial inspection owner. A failed retirement requires explicit close."""

    def __init__(self) -> None:
        self._inspection: _Inspection | None = None
        self._runtime: sqlite3.Connection | None = None
        self._closed = False
        self._pid = os.getpid()
        self._thread = threading.get_ident()
        self._connection: sqlite3.Connection | None = None
        self._path: Path | None = None
        self._identities: dict[str, tuple[int, int] | None] = {}

    def _require_owner(self) -> None:
        if self._pid != os.getpid() or self._thread != threading.get_ident():
            raise _unavailable()

    def _require_available(self) -> None:
        self._require_owner()
        if self._closed or self._inspection is not None or self._runtime is not None:
            raise _unavailable()

    def _require_disk_retired(self) -> None:
        # Only this exact real connection, on its original process/thread, may
        # establish the supported CPython closed-handle proof. False is LIVE.
        self._require_owner()
        if self._connection is not None:
            try:
                _ = self._connection.in_transaction
            except sqlite3.ProgrammingError:
                self._connection = None
            else:
                raise _unavailable()

    def check_runtime(self) -> None:
        self._require_available()
        try:
            if sys.platform != "linux":
                raise _unavailable()
            self._runtime = sqlite3.connect(":memory:")
            _check_runtime(self._runtime.execute)
        except BaseException as error:
            try:
                self._retire_runtime()
            except BaseException as cleanup_error:
                if not isinstance(error, Exception):
                    raise error from None
                if not isinstance(cleanup_error, Exception):
                    raise
                raise _unavailable() from None
            if isinstance(error, Exception):
                raise _unavailable() from None
            raise
        self._retire_runtime()

    def _retire_runtime(self) -> None:
        if self._runtime is not None:
            try:
                self._runtime.close()
            except Exception:
                raise _unavailable() from None
            self._runtime = None

    def configure(
        self, db: sqlite3.Connection, *, initialize: bool, execute: _Execute
    ) -> None:
        """Configure a caller-owned unix/psow=0 connection under its deadline.

        A nonempty database must already have the supported persistent format.
        This never VACUUMs or changes an existing journal/auto-vacuum format.
        """
        self._require_available()
        self._require_disk_retired()
        try:
            if type(db) is not sqlite3.Connection or self._path is None:
                raise _unavailable()
            # Validate real initialized/live handle before retaining it. A
            # ProgrammingError from an uninitialized object is not retirement.
            _ = db.in_transaction
            self._connection = db
            databases = execute("PRAGMA database_list").fetchall()
            if (
                len(databases) != 1
                or databases[0][1] != "main"
                or Path(databases[0][2]) != self._path
            ):
                raise _unavailable()
            if db.in_transaction:
                raise _unavailable()
            _check_runtime(execute)
            pages = execute("PRAGMA page_count").fetchone()[0]
            if initialize:
                if pages != 0:
                    raise _unavailable()
                execute("PRAGMA page_size=4096")
                execute("PRAGMA auto_vacuum=NONE")
                if execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                    raise _unavailable()
            elif not 1 <= pages <= MAX_DB_PAGES or any(
                execute("PRAGMA " + key).fetchone()[0] != _SETTINGS[key]
                for key in ("page_size", "auto_vacuum", "journal_mode")
            ):
                raise _unavailable()
            for key, value in _SETTINGS.items():
                if key not in {"page_size", "auto_vacuum", "journal_mode"}:
                    execute(f"PRAGMA {key}={value}")
            _verify_settings(execute)
        except Exception:
            raise _unavailable() from None

    def before_mutation(
        self, db: sqlite3.Connection, *, execute: _Execute, path: Path
    ) -> None:
        """Require a complete checkpoint before another dirty-page set.

        The caller holds the writer fence and owns this connection's lifetime;
        a return grants neither storage nor operator authority.
        """
        self._require_available()
        try:
            if db is not self._connection or db.in_transaction:
                raise _unavailable()
            _verify_settings(execute)
            self.observe_active_files(path)
            result = execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if result is None or tuple(result) != (0, 0, 0):
                raise _unavailable()
            inventory = self.observe_active_files(path)
            if inventory.files["wal"].length != 0:
                raise _unavailable()
        except Exception:
            raise _unavailable() from None

    def observe_active_files(self, path: Path) -> ManagedFileInventory:
        """Stat-only observations while SQLite owns its POSIX record locks.

        Opening then closing any additional DB/SHM descriptor would release
        same-process SQLite locks. No descriptor is opened by this path.
        """
        self._require_available()
        try:
            if self._connection is None or Path(path) != self._path:
                raise _unavailable()
            _ = self._connection.in_transaction  # Closed is an error in this phase.
            require_private_directory(path.parent)
            observed = {}
            for name, (suffix, limit) in _FILES.items():
                target = Path(str(path) + suffix)
                expected = self._identities.get(name)
                try:
                    identity = require_private_file(target, identity=expected)
                except FileNotFoundError:
                    if name == "db" or expected is not None:
                        raise _unavailable() from None
                    observed[name] = ManagedFile(0, 0, None)
                    continue
                info = target.stat(follow_symlinks=False)
                if (info.st_dev, info.st_ino) != identity or info.st_size > limit:
                    raise _unavailable()
                self._identities[name] = identity
                observed[name] = ManagedFile(
                    info.st_size, info.st_blocks * 512, identity
                )
            managed = sum(item.length for item in observed.values())
            allocated = sum(item.allocated_bytes for item in observed.values())
            if max(managed, allocated) > MAX_METADATA_FILE_BYTES:
                raise _unavailable()
            return ManagedFileInventory(MappingProxyType(observed), managed, allocated)
        except Exception:
            raise _unavailable() from None

    def inspect_files(self, path: Path, *, initializing: bool) -> ManagedFileInventory:
        self._require_available()
        self._require_disk_retired()
        self._inspection = _Inspection()
        try:
            inventory = self._inspection.acquire(path, initializing=initializing)
        except BaseException as error:
            try:
                self._inspection.retire()
            except BaseException as cleanup_error:
                if not isinstance(error, Exception):
                    raise error from None
                if not isinstance(cleanup_error, Exception):
                    raise
                raise _unavailable() from None
            self._inspection = None
            if isinstance(error, Exception):
                raise _unavailable() from None
            raise
        try:
            self._inspection.retire()
        except Exception:
            raise _unavailable() from None
        self._inspection = None
        self._path = Path(path)
        self._identities = {
            name: item.identity for name, item in inventory.files.items()
        }
        return inventory

    def close(self) -> None:
        self._require_owner()
        self._closed = True
        self._require_disk_retired()
        try:
            if self._inspection is not None:
                self._inspection.retire()
                self._inspection = None
            self._retire_runtime()
        except Exception:
            raise _unavailable() from None
