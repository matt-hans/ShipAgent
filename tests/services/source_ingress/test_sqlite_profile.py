"""Managed SQLite bytes are bounded before opening a disk connection."""

import importlib
import importlib.util
import os
import sqlite3
import struct
from contextlib import closing
from pathlib import Path

import pytest

from src.services.source_ingress.reservation_contracts import ReservationError


def implementation():
    name = "src.services.source_ingress.sqlite_profile"
    assert importlib.util.find_spec(name) is not None, "source SQLite profile is absent"
    return importlib.import_module(name)


def database(tmp_path):
    path = tmp_path / "metadata.sqlite3"
    path.touch(mode=0o600)
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        db.execute("PRAGMA page_size=4096")
        db.execute("PRAGMA auto_vacuum=NONE")
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        db.execute("CREATE TABLE synthetic(value TEXT)")
    return path


def wal_header(*, magic=0x377F0682, version=3007000, page_size=4096):
    return struct.pack(">8I", magic, version, page_size, 0, 1, 2, 3, 4)


def frame(*, page=1, commit_pages=0):
    return struct.pack(">6I", page, commit_pages, 1, 2, 3, 4) + bytes(4096)


def private_sidecar(path, suffix, content):
    target = Path(str(path) + suffix)
    target.touch(mode=0o600)
    target.write_bytes(content)
    return target


def assert_no_disk_connect(monkeypatch):
    connections = []
    original = sqlite3.connect

    def connect(path, *args, **kwargs):
        assert str(path) == ":memory:", "profile inspection opened a disk connection"
        connections.append(str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    return connections


def test_supported_runtime_and_private_geometry_are_observations_only(
    tmp_path, monkeypatch
):
    path = database(tmp_path)
    private_sidecar(path, "-wal", wal_header() + frame(commit_pages=2))
    private_sidecar(path, "-shm", bytes(32768))
    connections = assert_no_disk_connect(monkeypatch)
    profile = implementation().SourceSqliteProfile()
    try:
        profile.check_runtime()
        observed = profile.inspect_files(path, initializing=False)
        assert observed.managed_bytes == 8192 + 32 + 4120 + 32768
        assert observed.allocated_bytes >= observed.managed_bytes
        assert observed.files["db"].length == 8192
        assert observed.files["wal"].length == 4152
        assert observed.files["shm"].length == 32768
        assert connections and set(connections) == {":memory:"}
        assert "synthetic" not in repr(observed)
    finally:
        profile.close()


@pytest.mark.parametrize(
    "kind",
    [
        "db_length",
        "db_page_count",
        "wal_length",
        "shm_length",
        "journal",
        "wal_page_size",
        "wal_version",
        "wal_magic",
        "torn_header",
        "torn_frame",
        "first_page_number",
        "late_page_number",
        "first_commit_size",
        "late_commit_size",
    ],
)
def test_unsupported_geometry_is_refused_before_sqlite_open(
    tmp_path, monkeypatch, kind
):
    path = database(tmp_path)
    if kind == "db_length":
        with path.open("r+b") as target:
            target.truncate(16 * 1024 * 1024 + 4096)
    elif kind == "db_page_count":
        with path.open("r+b") as target:
            target.seek(28)
            target.write((4097).to_bytes(4, "big"))
    elif kind == "wal_length":
        target = private_sidecar(path, "-wal", wal_header())
        with target.open("r+b") as target_file:
            target_file.truncate(32 + 4113 * 4120)
    elif kind == "shm_length":
        private_sidecar(path, "-shm", bytes(65537))
    elif kind == "journal":
        private_sidecar(path, "-journal", b"unresolved journal")
    else:
        content = {
            "wal_page_size": wal_header(page_size=8192),
            "wal_version": wal_header(version=3007001),
            "wal_magic": wal_header(magic=0),
            "torn_header": wal_header()[:16],
            "torn_frame": wal_header() + frame()[:-1],
            "first_page_number": wal_header() + frame(page=4097),
            "late_page_number": wal_header() + frame() + frame() + frame(page=4097),
            "first_commit_size": wal_header() + frame(commit_pages=4097),
            "late_commit_size": wal_header()
            + frame()
            + frame()
            + frame(commit_pages=4097),
        }[kind]
        private_sidecar(path, "-wal", content)
    before = {
        item.name: (item.stat().st_size, item.stat().st_mtime_ns)
        for item in tmp_path.iterdir()
    }
    connections = assert_no_disk_connect(monkeypatch)
    profile = implementation().SourceSqliteProfile()
    try:
        with pytest.raises(ReservationError, match="unavailable"):
            profile.inspect_files(path, initializing=False)
        assert connections == []
        assert {
            item.name: (item.stat().st_size, item.stat().st_mtime_ns)
            for item in tmp_path.iterdir()
        } == before
    finally:
        profile.close()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode"])
def test_private_file_identity_is_required_before_scan(tmp_path, monkeypatch, kind):
    path = database(tmp_path)
    if kind == "symlink":
        original = tmp_path / "original.sqlite3"
        path.rename(original)
        path.symlink_to(original)
    elif kind == "hardlink":
        os.link(path, tmp_path / "second.sqlite3")
    else:
        path.chmod(0o644)
    assert_no_disk_connect(monkeypatch)
    profile = implementation().SourceSqliteProfile()
    try:
        with pytest.raises(ReservationError, match="unavailable"):
            profile.inspect_files(path, initializing=False)
    finally:
        profile.close()


def test_existing_empty_file_is_not_silently_treated_as_initialization(
    tmp_path, monkeypatch
):
    path = tmp_path / "empty.sqlite3"
    path.touch(mode=0o600)
    assert_no_disk_connect(monkeypatch)
    profile = implementation().SourceSqliteProfile()
    try:
        with pytest.raises(ReservationError):
            profile.inspect_files(path, initializing=False)
        assert profile.inspect_files(path, initializing=True).managed_bytes == 0
    finally:
        profile.close()


def connect_profile(path):
    return sqlite3.connect(
        f"file:{path}?mode=rw&vfs=unix&psow=0",
        uri=True,
        isolation_level=None,
        timeout=0.01,
    )


def test_configure_verifies_every_fixed_setting_and_uses_supplied_executor(tmp_path):
    path = tmp_path / "new.sqlite3"
    path.touch(mode=0o600)
    profile = implementation().SourceSqliteProfile()
    statements = []
    profile.inspect_files(path, initializing=True)
    with closing(connect_profile(path)) as db:

        def execute(sql):
            statements.append(sql)
            return db.execute(sql)

        profile.configure(db, initialize=True, execute=execute)
        expected = {
            "page_size": 4096,
            "max_page_count": 4096,
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
        assert {
            key: db.execute("PRAGMA " + key).fetchone()[0] for key in expected
        } == expected
        assert all("PRAGMA " + key in statements for key in expected)
        profile.before_mutation(db, execute=execute, path=path)
        db.execute("CREATE TABLE synthetic(value)")
        assert path.stat().st_size <= 16 * 1024 * 1024
    profile.close()


@pytest.mark.parametrize(
    "kind", ["page_size", "auto_vacuum", "journal_mode", "nonempty_initialize"]
)
def test_incompatible_existing_store_is_not_rewritten(tmp_path, kind):
    path = tmp_path / "incompatible.sqlite3"
    path.touch(mode=0o600)
    with closing(connect_profile(path)) as db:
        db.execute("PRAGMA page_size=" + ("8192" if kind == "page_size" else "4096"))
        db.execute(
            "PRAGMA auto_vacuum=" + ("FULL" if kind == "auto_vacuum" else "NONE")
        )
        if kind != "journal_mode":
            db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE synthetic(value)")
    before = path.read_bytes()
    profile = implementation().SourceSqliteProfile()
    try:
        try:
            profile.inspect_files(path, initializing=False)
        except ReservationError:
            assert kind == "page_size"
            assert path.read_bytes() == before
            return
        with closing(connect_profile(path)) as db:
            with pytest.raises(ReservationError, match="unavailable"):
                profile.configure(
                    db, initialize=kind == "nonempty_initialize", execute=db.execute
                )
        assert path.read_bytes() == before
    finally:
        profile.close()


def test_pinned_reader_denies_next_mutation_until_successful_truncate(tmp_path):
    path = database(tmp_path)
    profile = implementation().SourceSqliteProfile()
    try:
        profile.inspect_files(path, initializing=False)
        with (
            closing(connect_profile(path)) as db,
            closing(connect_profile(path)) as reader,
        ):
            profile.configure(db, initialize=False, execute=db.execute)
            profile.before_mutation(db, execute=db.execute, path=path)
            db.execute("INSERT INTO synthetic VALUES('before')")
            profile.before_mutation(db, execute=db.execute, path=path)
            reader.execute("BEGIN")
            assert (
                reader.execute("SELECT value FROM synthetic").fetchone()[0] == "before"
            )
            db.execute("UPDATE synthetic SET value='after'")
            changes = db.total_changes
            with pytest.raises(ReservationError):
                profile.before_mutation(db, execute=db.execute, path=path)
            assert db.total_changes == changes
            assert (
                reader.execute("SELECT value FROM synthetic").fetchone()[0] == "before"
            )
            assert Path(str(path) + "-wal").stat().st_size > 0
            reader.rollback()
            profile.before_mutation(db, execute=db.execute, path=path)
            assert Path(str(path) + "-wal").stat().st_size == 0
            assert db.execute("SELECT value FROM synthetic").fetchone()[0] == "after"
    finally:
        profile.close()


def test_changed_connection_profile_or_active_transaction_denies_next_write(tmp_path):
    path = database(tmp_path)
    profile = implementation().SourceSqliteProfile()
    try:
        profile.inspect_files(path, initializing=False)
        with closing(connect_profile(path)) as db:
            profile.configure(db, initialize=False, execute=db.execute)
            db.execute("PRAGMA cache_spill=ON")
            with pytest.raises(ReservationError):
                profile.before_mutation(db, execute=db.execute, path=path)
            db.execute("PRAGMA cache_spill=OFF")
            db.execute("BEGIN IMMEDIATE")
            with pytest.raises(ReservationError):
                profile.before_mutation(db, execute=db.execute, path=path)
            db.rollback()
    finally:
        profile.close()


@pytest.mark.parametrize("after_effect", [False, True])
def test_runtime_close_failure_is_private_and_retained_for_retry(
    tmp_path, monkeypatch, after_effect
):
    module = implementation()
    connect = sqlite3.connect
    owners = []

    class Connection:
        def __init__(self):
            self.db = connect(":memory:")
            self.fail = True

        def execute(self, sql):
            return self.db.execute(sql)

        def close(self):
            if self.fail:
                self.fail = False
                if after_effect:
                    self.db.close()
                raise OSError("PRIVATE-RUNTIME-CANARY")
            self.db.close()

    def open_memory(*args, **kwargs):
        owner = Connection()
        owners.append(owner)
        return owner

    monkeypatch.setattr(sqlite3, "connect", open_memory)
    profile = module.SourceSqliteProfile()
    try:
        with pytest.raises(ReservationError, match="unavailable") as error:
            profile.check_runtime()
        assert "PRIVATE-RUNTIME-CANARY" not in str(error.value)
        with pytest.raises(ReservationError):
            profile.check_runtime()
        assert len(owners) == 1
    finally:
        profile.close()
    with pytest.raises(sqlite3.ProgrammingError):
        owners[0].db.execute("SELECT 1")


@pytest.mark.parametrize("after_effect", [False, True])
def test_failed_inspection_retains_owner_and_only_retries_its_descriptors(
    tmp_path, monkeypatch, after_effect
):
    module = implementation()
    path = database(tmp_path)
    original = module._InspectionFile.retire
    captured = []
    fail = True

    def retire(owned):
        nonlocal fail
        if owned.handle is not None and fail:
            fail = False
            captured.append(owned.handle)
            if after_effect:
                original(owned)
            raise OSError("PRIVATE-CLOSE-CANARY")
        original(owned)

    monkeypatch.setattr(module._InspectionFile, "retire", retire)
    profile = module.SourceSqliteProfile()
    with pytest.raises(ReservationError):
        profile.inspect_files(path, initializing=False)
    with pytest.raises(ReservationError):
        profile.inspect_files(path, initializing=False)
    profile.close()
    assert captured and all(handle.closed for handle in captured)
    with pytest.raises(ReservationError):
        profile.inspect_files(path, initializing=False)


@pytest.mark.parametrize("mismatch", ["source", "compile_options"])
def test_runtime_mismatch_never_opens_disk_or_exposes_details(monkeypatch, mismatch):
    module = implementation()
    connect = sqlite3.connect
    opened = []

    class Rows:
        def fetchone(self):
            return ("UNSUPPORTED-PRIVATE-BUILD",)

        def __iter__(self):
            return iter([("UNSUPPORTED-PRIVATE-BUILD",)])

    class Connection(sqlite3.Connection):
        def execute(self, sql, *args):
            if (mismatch == "source" and sql == "SELECT sqlite_source_id()") or (
                mismatch == "compile_options" and sql == "PRAGMA compile_options"
            ):
                return Rows()
            return super().execute(sql, *args)

    def open_memory(path):
        assert path == ":memory:"
        opened.append(path)
        return connect(path, factory=Connection)

    monkeypatch.setattr(sqlite3, "connect", open_memory)
    profile = module.SourceSqliteProfile()
    try:
        with pytest.raises(ReservationError, match="unavailable") as error:
            profile.check_runtime()
        assert "PRIVATE" not in str(error.value)
        assert opened == [":memory:"]
    finally:
        profile.close()


def test_observed_allocated_overage_denies_without_claiming_peak_enforcement(
    tmp_path, monkeypatch
):
    module = implementation()
    path = database(tmp_path)
    fstat = module.os.fstat

    def excess(fd):
        from types import SimpleNamespace

        info = fstat(fd)
        return SimpleNamespace(
            st_dev=info.st_dev,
            st_ino=info.st_ino,
            st_size=info.st_size,
            st_blocks=(34 * 1024 * 1024 // 512) + 1,
        )

    monkeypatch.setattr(module.os, "fstat", excess)
    profile = module.SourceSqliteProfile()
    try:
        with pytest.raises(ReservationError):
            profile.inspect_files(path, initializing=False)
        assert path.stat().st_size == 8192
    finally:
        profile.close()


def test_file_replacement_during_scan_denies_and_retires_original(
    tmp_path, monkeypatch
):
    module = implementation()
    path = database(tmp_path)
    original = module._InspectionFile.read
    seen = []

    def read(owned, offset, count):
        data = original(owned, offset, count)
        if owned.path == path and not seen:
            seen.append(owned.handle)
            replacement = tmp_path / "replacement"
            replacement.touch(mode=0o600)
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)
        return data

    monkeypatch.setattr(module._InspectionFile, "read", read)
    profile = module.SourceSqliteProfile()
    try:
        with pytest.raises(ReservationError):
            profile.inspect_files(path, initializing=False)
        assert seen and seen[0].closed
        assert profile.inspect_files(path, initializing=False).managed_bytes == 8192
    finally:
        profile.close()


def test_inventory_is_immutable_and_only_contains_geometry(tmp_path):
    from dataclasses import FrozenInstanceError

    profile = implementation().SourceSqliteProfile()
    try:
        observed = profile.inspect_files(database(tmp_path), initializing=False)
        with pytest.raises(TypeError):
            observed.files["db"] = None
        with pytest.raises(FrozenInstanceError):
            observed.files["db"].length = 0
        assert set(observed.files) == {"db", "wal", "shm", "journal"}
    finally:
        profile.close()


def test_sqlite_full_rolls_back_without_second_dirty_set(tmp_path):
    path = database(tmp_path)
    profile = implementation().SourceSqliteProfile()
    try:
        profile.inspect_files(path, initializing=False)
        with closing(connect_profile(path)) as db:
            profile.configure(db, initialize=False, execute=db.execute)
            profile.before_mutation(db, execute=db.execute, path=path)
            db.execute("BEGIN IMMEDIATE")
            with pytest.raises(sqlite3.OperationalError, match="full"):
                db.executemany(
                    "INSERT INTO synthetic VALUES(?)",
                    ((bytes(3800),) for _ in range(5000)),
                )
            db.rollback()
            assert db.execute("SELECT count(*) FROM synthetic").fetchone()[0] == 0
            assert Path(str(path) + "-wal").stat().st_size == 0
            profile.before_mutation(db, execute=db.execute, path=path)
            db.execute("INSERT INTO synthetic VALUES('recover')")
            assert db.execute("SELECT value FROM synthetic").fetchone()[0] == "recover"
            inventory = profile.observe_active_files(path)
            assert inventory.managed_bytes <= 34 * 1024 * 1024
    finally:
        profile.close()


def test_near_page_ceiling_commit_stays_in_file_envelope(tmp_path):
    path = database(tmp_path)
    profile = implementation().SourceSqliteProfile()
    try:
        profile.inspect_files(path, initializing=False)
        with closing(connect_profile(path)) as db:
            profile.configure(db, initialize=False, execute=db.execute)
            profile.before_mutation(db, execute=db.execute, path=path)
            db.execute("BEGIN IMMEDIATE")
            db.executemany(
                "INSERT INTO synthetic VALUES(?)", ((b"A" * 3800,) for _ in range(4021))
            )
            db.commit()
            assert 4000 <= db.execute("PRAGMA page_count").fetchone()[0] <= 4096
            profile.before_mutation(db, execute=db.execute, path=path)
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE synthetic SET value=?", (b"B" * 3800,))
            assert Path(str(path) + "-wal").stat().st_size == 0
            db.commit()
            inventory = profile.observe_active_files(path)
            assert 16_000_000 <= inventory.files["wal"].length <= 16_941_472
            assert inventory.files["db"].length <= 16_777_216
            assert inventory.files["shm"].length <= 65536
            assert inventory.managed_bytes <= 34 * 1024 * 1024
            assert inventory.allocated_bytes <= 34 * 1024 * 1024
            import json

            print(
                "PROFILE_MEASUREMENT "
                + json.dumps(
                    {
                        "purpose": "generic pager evidence, not the future V2 schema",
                        "sqlite_version": sqlite3.sqlite_version,
                        "source_id": db.execute("SELECT sqlite_source_id()").fetchone()[
                            0
                        ],
                        "selected_vfs": "unix",
                        "psow": 0,
                        "database_pages": db.execute("PRAGMA page_count").fetchone()[0],
                        "files": {
                            key: {
                                "length": value.length,
                                "allocated_bytes": value.allocated_bytes,
                            }
                            for key, value in inventory.files.items()
                        },
                        "managed_bytes": inventory.managed_bytes,
                        "allocated_bytes": inventory.allocated_bytes,
                        "allocation_is_not_a_hard_peak_quota": True,
                    },
                    sort_keys=True,
                )
            )
            profile.before_mutation(db, execute=db.execute, path=path)
            assert Path(str(path) + "-wal").stat().st_size == 0
    finally:
        profile.close()


@pytest.mark.parametrize("phase", ["before", "after", "after_corrupt_shm"])
def test_crash_before_after_commit_recovery_is_bounded(tmp_path, phase):
    import subprocess
    import sys

    path = database(tmp_path)
    script = """
import os, sqlite3, sys
from pathlib import Path
from src.services.source_ingress.sqlite_profile import SourceSqliteProfile
path = Path(sys.argv[1])
p = SourceSqliteProfile()
p.inspect_files(path, initializing=False)
db = sqlite3.connect(f"file:{path}?mode=rw&vfs=unix&psow=0", uri=True, isolation_level=None)
p.configure(db, initialize=False, execute=db.execute)
p.before_mutation(db, execute=db.execute, path=path)
db.execute("BEGIN IMMEDIATE")
db.execute("INSERT INTO synthetic VALUES('crash-value')")
db.execute("PRAGMA user_version=77")
if sys.argv[2] != 'before':
    db.commit()
os._exit(42)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), phase], capture_output=True, timeout=5
    )
    assert result.returncode == 42, result.stderr.decode()
    if phase == "after_corrupt_shm":
        # A dead first owner leaves a bounded but unusable cached mapping. The
        # pinned unix VFS must reset it on the first new opener, not trust it.
        private_sidecar(path, "-shm", b"\xff" * 32768)
    profile = implementation().SourceSqliteProfile()
    try:
        before = profile.inspect_files(path, initializing=False)
        assert before.managed_bytes <= 34 * 1024 * 1024
        assert int.from_bytes(path.read_bytes()[60:64], "big") == 0
        with closing(connect_profile(path)) as db:
            profile.configure(db, initialize=False, execute=db.execute)
            assert db.execute("SELECT count(*) FROM synthetic").fetchone()[0] == (
                phase != "before"
            )
            assert db.execute("PRAGMA user_version").fetchone()[0] == (
                0 if phase == "before" else 77
            )
            profile.before_mutation(db, execute=db.execute, path=path)
            assert Path(str(path) + "-wal").stat().st_size == 0
            assert profile.observe_active_files(path).managed_bytes <= 34 * 1024 * 1024
    finally:
        profile.close()


def test_active_checks_never_open_descriptors_and_keep_dms_lock(tmp_path, monkeypatch):
    import subprocess
    import sys

    module = implementation()
    path = database(tmp_path)
    profile = module.SourceSqliteProfile()
    profile.inspect_files(path, initializing=False)
    witness = """
import errno, fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR)
try:
    try:
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 128, os.SEEK_SET)
    except OSError as error:
        assert error.errno in (errno.EAGAIN, errno.EACCES)
        print('held')
    else:
        print('released')
finally:
    os.close(fd)
"""

    def dms():
        result = subprocess.run(
            [sys.executable, "-c", witness, str(path) + "-shm"],
            capture_output=True,
            timeout=5,
        )
        assert result.returncode == 0, result.stderr.decode()
        return result.stdout.strip()

    try:
        with closing(connect_profile(path)) as db:
            profile.configure(db, initialize=False, execute=db.execute)
            db.execute("SELECT * FROM synthetic").fetchall()
            assert dms() == b"held"
            profile.before_mutation(db, execute=db.execute, path=path)
            assert dms() == b"held"

            def forbidden(*args, **kwargs):
                pytest.fail("active profile opened a managed descriptor")

            with monkeypatch.context() as patch:
                patch.setattr(module.os, "open", forbidden)
                profile.before_mutation(db, execute=db.execute, path=path)
                assert profile.observe_active_files(path).managed_bytes > 0
    finally:
        profile.close()


def test_descriptor_inspection_waits_for_positive_disk_connection_retirement(tmp_path):
    profile = implementation().SourceSqliteProfile()
    path = database(tmp_path)
    profile.inspect_files(path, initializing=False)
    db = connect_profile(path)
    try:
        profile.configure(db, initialize=False, execute=db.execute)
        with pytest.raises(ReservationError):
            profile.inspect_files(path, initializing=False)
        db.close()
        assert profile.inspect_files(path, initializing=False).managed_bytes == 8192
    finally:
        db.close()
        profile.close()


def test_runtime_interruption_survives_cleanup_failure_and_keeps_owner(monkeypatch):
    module = implementation()
    connect = sqlite3.connect
    owned = []

    class Connection:
        def __init__(self):
            self.db = connect(":memory:")
            self.fail = True

        def execute(self, sql):
            raise KeyboardInterrupt("control-flow")

        def close(self):
            if self.fail:
                self.fail = False
                raise OSError("PRIVATE-RUNTIME-CLEANUP")
            self.db.close()

    def open_memory(*args, **kwargs):
        connection = Connection()
        owned.append(connection)
        return connection

    monkeypatch.setattr(module.sqlite3, "connect", open_memory)
    profile = module.SourceSqliteProfile()
    try:
        with pytest.raises(KeyboardInterrupt):
            profile.check_runtime()
        with pytest.raises(ReservationError):
            profile.check_runtime()
        assert len(owned) == 1
    finally:
        profile.close()
    with pytest.raises(sqlite3.ProgrammingError):
        owned[0].db.execute("SELECT 1")


def test_live_connection_close_denial_preserves_identity_until_actual_retirement(
    tmp_path,
):
    module = implementation()
    path = database(tmp_path)
    profile = module.SourceSqliteProfile()
    profile.inspect_files(path, initializing=False)
    with closing(connect_profile(path)) as db:
        profile.configure(db, initialize=False, execute=db.execute)
        with pytest.raises(ReservationError):
            profile.close()
        assert db.execute("SELECT count(*) FROM synthetic").fetchone()[0] == 0
        with pytest.raises(ReservationError):
            profile.observe_active_files(path)
    profile.close()


def test_active_identity_replacement_denies_without_touching_unrelated_handle(tmp_path):
    module = implementation()
    path = database(tmp_path)
    profile = module.SourceSqliteProfile()
    profile.inspect_files(path, initializing=False)
    try:
        with closing(connect_profile(path)) as db:
            profile.configure(db, initialize=False, execute=db.execute)
            profile.observe_active_files(path)
            replacement = tmp_path / "unrelated"
            replacement.touch(mode=0o600)
            replacement.replace(Path(str(path) + "-shm"))
            with pytest.raises(ReservationError):
                profile.observe_active_files(path)
    finally:
        profile.close()


def test_profile_does_not_treat_other_thread_failure_as_connection_retirement(tmp_path):
    import concurrent.futures

    module = implementation()
    path = database(tmp_path)
    profile = module.SourceSqliteProfile()
    profile.inspect_files(path, initializing=False)
    try:
        with closing(connect_profile(path)) as db:
            profile.configure(db, initialize=False, execute=db.execute)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                with pytest.raises(ReservationError):
                    pool.submit(profile.inspect_files, path, initializing=False).result(
                        timeout=3
                    )
            assert db.execute("SELECT count(*) FROM synthetic").fetchone()[0] == 0
            with pytest.raises(ReservationError):
                profile.inspect_files(path, initializing=False)
    finally:
        profile.close()


def test_inspection_cleanup_interruption_is_propagated_and_owner_retained(
    tmp_path, monkeypatch
):
    module = implementation()
    path = database(tmp_path)
    original = module._InspectionFile.retire
    handles = []
    interrupted = False

    def fail_read(owned, offset, count):
        raise OSError("PRIVATE-READ-FAILURE")

    def interrupt_retire(owned):
        nonlocal interrupted
        if owned.handle is not None and not interrupted:
            interrupted = True
            handles.append(owned.handle)
            raise KeyboardInterrupt("cleanup-control-flow")
        original(owned)

    monkeypatch.setattr(module._InspectionFile, "read", fail_read)
    monkeypatch.setattr(module._InspectionFile, "retire", interrupt_retire)
    profile = module.SourceSqliteProfile()
    try:
        with pytest.raises(KeyboardInterrupt):
            profile.inspect_files(path, initializing=False)
        with pytest.raises(ReservationError):
            profile.inspect_files(path, initializing=False)
    finally:
        profile.close()
    assert handles and all(handle.closed for handle in handles)
