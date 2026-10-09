"""Bounded target-private reservation metadata, without admission authority.

Only the source operation coordinator may interpret this internal store after
holding its conversation and authority fences. Logical metadata accounting
excludes SQLite page/index/WAL overhead; it is not a physical disk quota.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import threading
import time
import weakref
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from urllib.parse import quote

from src.services.agent_runs.private_storage import (
    require_private_directory,
    require_private_file,
    sync_directory,
)
from src.services.agent_runs.source_ownership import ConversationFence
from src.services.agent_runs.store import MAX_CONVERSATION_RUNS
from src.services.source_ingress.reservation_contracts import (
    ReservationError,
    ReservationNamespace,
    ReservationReceipt,
    ReservationRequest,
    require_private_text,
)
from src.services.source_ingress.snapshot_store import V2_TABLES, SnapshotTransaction
from src.services.source_ingress.sqlite_profile import SourceSqliteProfile

APPLICATION_ID = 0x53415352
SCHEMA_VERSION = 2
RESERVATION_PAYLOAD_VERSION = 1
_V1_TABLES = {
    "target_owner": """CREATE TABLE target_owner (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        account_id TEXT NOT NULL, target_id TEXT NOT NULL)""",
    "reservations": """CREATE TABLE reservations (
        reservation_id TEXT PRIMARY KEY,
        namespace_digest TEXT NOT NULL UNIQUE,
        input_digest TEXT NOT NULL,
        upload_expires_at INTEGER NOT NULL,
        payload TEXT NOT NULL,
        metadata_bytes INTEGER NOT NULL)""",
}
MAX_RETAINED_RECORDS = 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_RECORD_BYTES = 8 * 1024
MAX_LIVE_RESERVATIONS = 2
SQLITE_LENGTH_LIMIT = 32 * 1024
_PAYLOAD_KEYS = {
    "version",
    "namespace",
    "input",
    "admitted_revision",
    "admitted_at",
    "upload_expires_at",
    "prospective_source_expires_at",
}
_INPUT_KEYS = {"content_length", "content_sha256", "media_type", "parser_profile"}
_NAMESPACE_KEYS = {item.name for item in fields(ReservationNamespace)}


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _input(request: ReservationRequest) -> dict:
    return {
        key: value for key, value in asdict(request).items() if key != "request_key"
    }


def metadata_size(
    payload: str, reservation_id: str, namespace_digest: str, input_digest: str
) -> int:
    """Actual encoded text plus two fixed-width persisted integer upper bounds."""
    return (
        sum(
            len(value.encode("utf-8"))
            for value in (payload, reservation_id, namespace_digest, input_digest)
        )
        + 16
    )  # upload_expires_at and metadata_bytes, at most eight bytes each.


@dataclass(frozen=True, slots=True, repr=False)
class ReservationRecord:
    namespace: ReservationNamespace
    request: ReservationRequest
    admitted_revision: int
    receipt: ReservationReceipt

    def to_receipt(self) -> ReservationReceipt:
        return self.receipt


def _payload(record: ReservationRecord) -> str:
    receipt = record.receipt
    return canonical_json(
        {
            "version": RESERVATION_PAYLOAD_VERSION,
            "namespace": asdict(record.namespace),
            "input": _input(record.request),
            "admitted_revision": record.admitted_revision,
            "admitted_at": receipt.admitted_at,
            "upload_expires_at": receipt.upload_expires_at,
            "prospective_source_expires_at": receipt.prospective_source_expires_at,
        }
    )


def _decode(row: sqlite3.Row) -> ReservationRecord:
    """Called only after encoded lengths and SQLite scalar types were checked."""
    payload = row["payload"]
    data = json.loads(payload)
    if (
        type(data) is not dict
        or set(data) != _PAYLOAD_KEYS
        or type(data["version"]) is not int
        or data["version"] != RESERVATION_PAYLOAD_VERSION
        or type(data["namespace"]) is not dict
        or set(data["namespace"]) != _NAMESPACE_KEYS
        or type(data["input"]) is not dict
        or set(data["input"]) != _INPUT_KEYS
        or canonical_json(data) != payload
        or type(data["admitted_revision"]) is not int
        or not 1 <= data["admitted_revision"] <= MAX_CONVERSATION_RUNS
    ):
        raise ReservationError("reservation_unavailable")
    namespace = ReservationNamespace(**data["namespace"])
    request = ReservationRequest(request_key=namespace.request_key, **data["input"])
    receipt = ReservationReceipt(
        reservation_id=row["reservation_id"],
        status="reserved",
        admitted_at=data["admitted_at"],
        upload_expires_at=data["upload_expires_at"],
        prospective_source_expires_at=data["prospective_source_expires_at"],
    )
    if (
        _digest(asdict(namespace)) != row["namespace_digest"]
        or _digest(_input(request)) != row["input_digest"]
        or receipt.upload_expires_at != row["upload_expires_at"]
        or metadata_size(
            payload, row["reservation_id"], row["namespace_digest"], row["input_digest"]
        )
        != row["metadata_bytes"]
    ):
        raise ReservationError("reservation_unavailable")
    return ReservationRecord(namespace, request, data["admitted_revision"], receipt)


class ReservationStore:
    def __init__(
        self,
        path: Path,
        *,
        account_id: str,
        execution_target_id: str,
        coordinator_path: Path,
        create: bool = False,
    ) -> None:
        require_private_text(account_id)
        require_private_text(execution_target_id)
        self.path = Path(path).absolute()
        self.account_id = account_id
        self.execution_target_id = execution_target_id
        self.coordinator_path = Path(coordinator_path).absolute()
        # singleton (8), application_id (4), user_version (4), exact owner text.
        self._owner_bytes = (
            16 + len(account_id.encode()) + len(execution_target_id.encode())
        )
        self._create = create
        self._identity = None
        self._setup: ReservationTransaction | None = None
        self._open_attempted = False
        self._ready = False
        self._closed = False
        self._maintenance_self = weakref.ref(self)
        self._maintenance_pid = os.getpid()
        self._maintenance_lock = threading.Lock()
        self._maintenance_owner = None

    def _claim_maintenance_owner(self, owner) -> None:
        """One original owner for this object, before any setup or close rights."""
        if self._maintenance_pid != os.getpid() or self._maintenance_self() is not self:
            raise ReservationError("reservation_unavailable")
        with self._maintenance_lock:
            if (
                self._maintenance_owner is not None
                or self._open_attempted
                or self._closed
            ):
                raise ReservationError("reservation_unavailable")
            self._maintenance_owner = owner

    @property
    def initialization_committed(self) -> bool:
        """Positive setup COMMIT evidence; False never proves rollback."""
        return self._setup is not None and self._setup.committed

    def open(
        self,
        *,
        conversation: ConversationFence,
        deadline: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """One startup attempt, retaining setup ownership through cleanup faults."""
        if self._open_attempted or self._closed:
            raise ReservationError("reservation_unavailable")
        self._open_attempted = True
        setup = ReservationTransaction(
            self, conversation, monotonic, initialize=self._create
        )
        self._setup = setup
        setup._deadline = deadline
        try:
            setup._remaining()
            self._require_conversation(conversation)
            setup._claim_source_owner()
            require_private_directory(self.path.parent)
            if self._create:
                setup._create_file()
                setup._retire_created_file()
                sync_directory(self.path.parent)
            self._identity = require_private_file(self.path)
            try:
                setup.acquire(deadline=deadline)
                if self._create:
                    setup.commit()
            finally:
                setup.retire()
            if self._create:
                sync_directory(self.path.parent)
            setup._remaining()
            self._ready = True
        except Exception:
            raise ReservationError("reservation_unavailable") from None

    def close(self) -> None:
        """Retire setup only; handed-out transaction scopes retain their owner."""
        self._closed = True
        self._ready = False
        if self._setup is not None:
            self._setup.retire()

    def transaction(
        self,
        *,
        conversation: ConversationFence,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> ReservationTransaction:
        if not self._ready or self._closed:
            raise ReservationError("reservation_unavailable")
        return ReservationTransaction(self, conversation, monotonic)

    def _require_conversation(self, conversation: ConversationFence) -> None:
        if type(conversation) is not ConversationFence:
            raise ReservationError("reservation_unavailable")
        conversation.require_storage_owner(
            account_id=self.account_id,
            execution_target_id=self.execution_target_id,
            coordinator_path=self.coordinator_path,
        )

    def _require_files(self) -> None:
        if self._identity is None:
            raise ReservationError("reservation_unavailable")
        require_private_directory(self.path.parent)
        require_private_file(self.path, identity=self._identity)
        for suffix in ("-wal", "-shm", "-journal"):
            path = Path(str(self.path) + suffix)
            if path.exists() or path.is_symlink():
                require_private_file(path)


class ReservationTransaction:
    def __init__(
        self,
        store: ReservationStore,
        conversation: ConversationFence,
        monotonic: Callable[[], float],
        *,
        initialize: bool = False,
    ) -> None:
        self._owner_ref = weakref.ref(self)
        self._pid = os.getpid()
        self._binding_attempted = False
        self._store = store
        self._conversation = conversation
        self._monotonic = monotonic
        self._initialize = initialize
        self._db: sqlite3.Connection | None = None
        self._pending_cursor: sqlite3.Cursor | None = None
        self._deadline = 0.0
        self._attempted = False
        self._active = False
        self._retired = False
        self._rolled_back = False
        self._progress_cleared = False
        self._commit_attempted = False
        self._committed = False
        self._profile = SourceSqliteProfile()
        self._connected = False
        self._profile_configured = False
        self._checkpointed = False
        self._files_checked = False
        self._created_file = None

    def _require_identity(self) -> None:
        try:
            if self._pid != os.getpid() or self._owner_ref() is not self:
                raise ReservationError("reservation_unavailable")
        except Exception:
            raise ReservationError("reservation_unavailable") from None

    def _claim_source_owner(self) -> None:
        self._require_identity()
        self._store._require_conversation(self._conversation)
        self._binding_attempted = True
        self._conversation._claim_source_owner(self)

    def _create_file(self) -> None:
        self._created_file = open(
            self._store.path,
            "xb",
            buffering=0,
            opener=lambda path, flags: os.open(
                path, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
            ),
        )

    def _retire_created_file(self) -> None:
        if self._created_file is not None:
            if not self._created_file.closed:
                self._created_file.close()
            if not self._created_file.closed:
                raise ReservationError("reservation_unavailable")
            self._created_file = None

    @property
    def commit_attempted(self) -> bool:
        """Whether the underlying COMMIT call began, independent of its outcome."""
        return self._commit_attempted

    @property
    def committed(self) -> bool:
        """True only after COMMIT returned; False never proves rollback."""
        return self._committed

    def _remaining(self) -> float:
        now = self._monotonic()
        if (
            isinstance(now, bool)
            or not isinstance(now, (int, float))
            or not math.isfinite(now)
            or isinstance(self._deadline, bool)
            or not isinstance(self._deadline, (int, float))
            or not math.isfinite(self._deadline)
            or now >= self._deadline
        ):
            raise ReservationError("reservation_unavailable")
        return self._deadline - now

    def _interrupted(self) -> int:
        try:
            self._remaining()
            return 0
        except Exception:
            return 1

    def _execute(self, sql: str, parameters: tuple = ()) -> sqlite3.Cursor:
        self._require_identity()
        if self._db is None or self._retired or self._pending_cursor is not None:
            raise ReservationError("reservation_unavailable")
        milliseconds = min(int(self._remaining() * 1000), 2**31 - 1)
        self._db.execute(f"PRAGMA busy_timeout={milliseconds}")
        self._pending_cursor = self._db.execute(sql, parameters)
        self._remaining()
        cursor, self._pending_cursor = self._pending_cursor, None
        return cursor

    def _verify_format(self) -> int:
        version = self._execute("PRAGMA user_version").fetchone()[0]
        if self._execute("PRAGMA application_id").fetchone()[
            0
        ] != APPLICATION_ID or version not in (1, SCHEMA_VERSION):
            raise ReservationError("reservation_unavailable")
        return version

    def _verify_schema(self, version: int) -> None:
        tables = _V1_TABLES | (V2_TABLES if version == 2 else {})

        def normalized(sql):
            return re.sub(r"\s+", "", sql).casefold()

        expected = {
            name: ("table", name, normalized(sql)) for name, sql in tables.items()
        }
        for table, indexes in (
            ("reservations", 2),
            ("source_lifecycle", 1),
            ("snapshot_manifests", 2),
        ):
            if table in tables:
                for number in range(1, indexes + 1):
                    expected[f"sqlite_autoindex_{table}_{number}"] = (
                        "index",
                        table,
                        None,
                    )
        sizes = self._execute("""SELECT rowid, length(CAST(name AS BLOB)),
            length(CAST(type AS BLOB)), length(CAST(tbl_name AS BLOB)),
            length(CAST(sql AS BLOB)) FROM sqlite_schema LIMIT 10""").fetchall()
        if len(sizes) != len(expected):
            raise ReservationError("reservation_unavailable")
        actual = {}
        for row in sizes:
            if (
                not 0 < row[1] <= 128
                or not 0 < row[2] <= 16
                or not 0 < row[3] <= 128
                or (row[4] is not None and not 0 < row[4] <= 8192)
            ):
                raise ReservationError("reservation_unavailable")
            name, kind, table, sql = self._execute(
                "SELECT name, type, tbl_name, sql FROM sqlite_schema WHERE rowid=?",
                (row[0],),
            ).fetchone()
            actual[name] = (kind, table, normalized(sql) if sql is not None else None)
        if actual != expected:
            raise ReservationError("reservation_unavailable")

    def _verify_owner(self) -> None:
        self._verify_schema(self._verify_format())
        row = self._execute(
            "SELECT account_id, target_id FROM target_owner WHERE singleton=1"
        ).fetchone()
        if row is None or tuple(row) != (
            self._store.account_id,
            self._store.execution_target_id,
        ):
            raise ReservationError("reservation_unavailable")

    def acquire(self, *, deadline: float) -> None:
        self._require_identity()
        if self._attempted or self._retired:
            raise ReservationError("reservation_unavailable")
        self._attempted = True
        self._deadline = deadline
        try:
            self._remaining()
            self._claim_source_owner()
            self._store._require_files()
            self._profile.check_runtime()
            self._profile.inspect_files(self._store.path, initializing=self._initialize)
            self._remaining()
            self._db = sqlite3.connect(
                f"file:{quote(str(self._store.path))}?mode=rw&vfs=unix&psow=0",
                uri=True,
                timeout=self._remaining(),
                isolation_level=None,
            )
            self._connected = True
            self._db.row_factory = sqlite3.Row
            self._db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, SQLITE_LENGTH_LIMIT)
            self._db.set_progress_handler(self._interrupted, 1000)
            if not self._initialize:
                self._verify_format()
            self._profile.configure(
                self._db, initialize=self._initialize, execute=self._execute
            )
            self._profile_configured = True
            if not self._initialize:
                self._verify_owner()
            self._profile.before_mutation(
                self._db, execute=self._execute, path=self._store.path
            )
            self._execute("BEGIN IMMEDIATE")
            if self._initialize:
                for sql in (_V1_TABLES | V2_TABLES).values():
                    self._execute(sql)
                self._execute(
                    "INSERT INTO target_owner VALUES(1,?,?)",
                    (self._store.account_id, self._store.execution_target_id),
                )
                self._execute(f"PRAGMA application_id={APPLICATION_ID}")
                self._execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self._store._require_files()
            self._verify_owner()
            self._active = True
        except Exception:
            self._active = False
            raise ReservationError("reservation_unavailable") from None

    def upgrade_schema(self) -> bool:
        """Stage an explicit V1→V2 DDL change; caller owns COMMIT and recovery."""
        self._require_active()
        if self._verify_format() == SCHEMA_VERSION:
            return False
        for sql in V2_TABLES.values():
            self._execute(sql)
        self._execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self._verify_owner()
        return True

    def _require_active(self) -> None:
        self._require_identity()
        if (
            not self._active
            or self._retired
            or self._db is None
            or not self._db.in_transaction
        ):
            raise ReservationError("reservation_unavailable")
        self._remaining()
        self._store._require_conversation(self._conversation)
        self._store._require_files()
        self._verify_owner()

    def _records(
        self, *, _include_snapshots: bool = True
    ) -> tuple[list[ReservationRecord], int]:
        self._require_active()
        # The writer reservation prevents a row changing between length/type
        # validation and bounded materialization. No stored counter is trusted.
        sizes = self._execute(
            """SELECT rowid,
                typeof(reservation_id), length(CAST(reservation_id AS BLOB)),
                typeof(namespace_digest), length(CAST(namespace_digest AS BLOB)),
                typeof(input_digest), length(CAST(input_digest AS BLOB)),
                typeof(payload), length(CAST(payload AS BLOB)),
                typeof(upload_expires_at), typeof(metadata_bytes), metadata_bytes
                FROM reservations LIMIT ?""",
            (MAX_RETAINED_RECORDS + 1,),
        ).fetchall()
        if len(sizes) > MAX_RETAINED_RECORDS:
            raise ReservationError("reservation_unavailable")
        records = []
        used = self._store._owner_bytes
        for size in sizes:
            if (
                tuple(size[index] for index in (1, 3, 5, 7)) != ("text",) * 4
                or tuple(size[index] for index in (2, 4, 6)) != (32, 64, 64)
                or tuple(size[index] for index in (9, 10)) != ("integer", "integer")
                or not 0 < size[8] <= MAX_RECORD_BYTES
                or size[2] + size[4] + size[6] + size[8] + 16 != size[11]
                or not 0 < size[11] <= MAX_RECORD_BYTES
            ):
                raise ReservationError("reservation_unavailable")
            row = self._execute(
                "SELECT * FROM reservations WHERE rowid=?", (size[0],)
            ).fetchone()
            if any(
                re.fullmatch(r"[0-9a-f]{64}", row[key]) is None
                for key in ("namespace_digest", "input_digest")
            ):
                raise ReservationError("reservation_unavailable")
            record = _decode(row)
            if (
                record.namespace.account_id != self._store.account_id
                or record.namespace.execution_target_id
                != self._store.execution_target_id
            ):
                raise ReservationError("reservation_unavailable")
            used += metadata_size(
                row["payload"],
                row["reservation_id"],
                row["namespace_digest"],
                row["input_digest"],
            )
            records.append(record)
        if used > MAX_METADATA_BYTES:
            raise ReservationError("reservation_unavailable")
        if _include_snapshots and self._verify_format() == 2:
            used = (
                SnapshotTransaction(self)
                ._read_metadata(records, used, now=0)
                .metadata_bytes
            )
        self._remaining()
        return records, used

    def lookup(self, namespace: ReservationNamespace) -> ReservationRecord | None:
        try:
            records, _ = self._records()
            wanted = _digest(asdict(namespace))
            for record in records:
                if _digest(asdict(record.namespace)) == wanted:
                    if record.namespace != namespace:
                        raise ReservationError("reservation_unavailable")
                    return record
            return None
        except Exception:
            raise ReservationError("reservation_unavailable") from None

    def insert(
        self,
        namespace: ReservationNamespace,
        request: ReservationRequest,
        *,
        admitted_revision: int,
        admitted_at: int,
        upload_expires_at: int,
        prospective_source_expires_at: int,
    ) -> ReservationRecord:
        try:
            records, used = self._records()
            if (
                type(namespace) is not ReservationNamespace
                or type(request) is not ReservationRequest
                or namespace.request_key != request.request_key
                or namespace.account_id != self._store.account_id
                or namespace.execution_target_id != self._store.execution_target_id
                or type(admitted_revision) is not int
                or not 1 <= admitted_revision <= MAX_CONVERSATION_RUNS
            ):
                raise ReservationError("invalid_request")
            namespace_digest = _digest(asdict(namespace))
            for existing in records:
                if _digest(asdict(existing.namespace)) != namespace_digest:
                    continue
                if existing.namespace != namespace:
                    raise ReservationError("reservation_unavailable")
                if existing.request != request:
                    raise ReservationError("request_conflict")
                return existing
            receipt = ReservationReceipt(
                secrets.token_hex(16),
                "reserved",
                admitted_at,
                upload_expires_at,
                prospective_source_expires_at,
            )
            record = ReservationRecord(namespace, request, admitted_revision, receipt)
            payload = _payload(record)
            input_digest = _digest(_input(request))
            size = metadata_size(
                payload, receipt.reservation_id, namespace_digest, input_digest
            )
            if (
                size > MAX_RECORD_BYTES
                or len(records) >= MAX_RETAINED_RECORDS
                or used + size > MAX_METADATA_BYTES
                or (
                    SnapshotTransaction(self)
                    .inventory(now=admitted_at)
                    .incomplete_count
                    if self._verify_format() == 2
                    else sum(
                        item.receipt.upload_expires_at > admitted_at for item in records
                    )
                )
                >= MAX_LIVE_RESERVATIONS
            ):
                raise ReservationError("source_limit_exceeded")
            self._execute(
                "INSERT INTO reservations VALUES(?,?,?,?,?,?)",
                (
                    receipt.reservation_id,
                    namespace_digest,
                    input_digest,
                    upload_expires_at,
                    payload,
                    size,
                ),
            )
            return record
        except ReservationError:
            raise
        except Exception:
            raise ReservationError("reservation_unavailable") from None

    def commit(self, *, _validate: Callable[[], None] | None = None) -> None:
        """Commit under the operation coordinator's final held-scope validation.

        The private validator is trusted wiring, never supplied by request data.
        It may only recheck existing fences and sample their final expiry budget.
        """
        try:
            self._require_active()
            self._remaining()
            if _validate is not None:
                _validate()
            self._commit_attempted = True
            self._commit_database()
            self._committed = True
            self._active = False
            # The operation owner checks response-time deadline/expiry after
            # this known commit and after cleanup. Do not erase that evidence.
        except ReservationError:
            self._active = False
            raise
        except Exception:
            self._active = False
            raise ReservationError("reservation_unavailable") from None

    def _commit_database(self) -> None:
        self._db.commit()

    def _close_pending_cursor(self) -> None:
        if self._pending_cursor is not None:
            self._pending_cursor.close()
            self._pending_cursor = None

    def _rollback_database(self) -> None:
        self._db.rollback()

    def _close_database(self) -> None:
        self._db.close()

    def _cleanup_execute(self, sql: str) -> sqlite3.Cursor:
        """Only the fixed profile's cleanup PRAGMAs use this retained handle."""
        self._close_pending_cursor()
        self._pending_cursor = self._db.execute(sql)
        return self._pending_cursor

    def retire(self) -> None:
        self._require_identity()
        self._active = False
        if self._retired:
            return
        try:
            self._retire_created_file()
            if self._db is not None:
                # Cleanup is required even when the admission deadline passed.
                if not self._progress_cleared:
                    self._db.set_progress_handler(None, 0)
                    self._progress_cleared = True
                self._close_pending_cursor()
                if not self._rolled_back:
                    self._rollback_database()
                    self._rolled_back = True
                if self._profile_configured and not self._checkpointed:
                    # Admission may have expired. This is non-waiting cleanup
                    # of captured ownership, never a fresh authority decision.
                    self._db.execute("PRAGMA busy_timeout=0")
                    self._profile.before_mutation(
                        self._db, execute=self._cleanup_execute, path=self._store.path
                    )
                    self._checkpointed = True
                self._close_pending_cursor()
                self._close_database()
                self._db = None
            if self._connected and not self._files_checked:
                inventory = self._profile.inspect_files(
                    self._store.path, initializing=self._initialize
                )
                if inventory.files["wal"].length != 0:
                    raise ReservationError("reservation_unavailable")
                self._files_checked = True
            self._profile.close()
            if self._binding_attempted:
                self._conversation._release_source_owner(self)
            self._retired = True
        except Exception:
            raise ReservationError("reservation_unavailable") from None
