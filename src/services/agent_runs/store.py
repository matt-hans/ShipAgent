"""Private SQLite acceptance and outcomes for one exact account-owned target."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from src.registry.identifiers import ShipAgentIdFamily, mint_shipagent_id
from src.services.agent_runs.clarification import public_clarification
from src.services.agent_runs.coordinator import CoordinatorLease
from src.services.agent_runs.private_storage import (
    require_private_directory,
    require_private_file,
    sync_directory,
)

# Conservative synthetic admission bounds, not a production spending policy.
MAX_PENDING_PER_CONNECTION = 4
MAX_PENDING_PER_ACCOUNT = 16
MAX_ACCEPTED_PER_CONNECTION_HOUR = 20
MAX_ACCEPTED_PER_ACCOUNT_HOUR = 60
MAX_RETAINED_RUNS = 10000
MAX_CONVERSATION_RUNS = 8


@dataclass(frozen=True)
class AgentRun:
    run_reference: str
    conversation_reference: str
    connection_id: str
    task: str = field(repr=False)
    state: str = "queued"
    outcome: str = "pending"
    expires_at: int = 0
    claim_generation: int = 0
    link_epoch: str | None = field(default=None, repr=False)
    revision: int = 1
    clarification_code: str | None = None
    conversation_revision: int = 1
    conversation_state: str = "active"

    def public_result(self) -> dict[str, object]:
        result = {
            "run_reference": self.run_reference,
            "conversation_reference": self.conversation_reference,
            "revision": self.revision,
            "state": self.state,
            "outcome": self.outcome,
            "expires_at": datetime.fromtimestamp(self.expires_at, UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "poll_after_seconds": 2 if self.state in {"queued", "running"} else 0,
        }

        if self.link_epoch is not None:
            result.update(
                conversation_revision=self.conversation_revision,
                conversation_state=self.conversation_state,
            )
            if (
                self.clarification_code is not None
                and self.conversation_state == "waiting_for_input"
                and self.conversation_revision == self.revision
            ):
                result["clarification"] = public_clarification(self.clarification_code)
        return result


class AgentRunStore:
    def __init__(
        self,
        path: Path,
        *,
        account_id: str,
        execution_target_id: str,
        create: bool = False,
    ) -> None:
        self.path = Path(path).absolute()
        require_private_directory(self.path.parent)
        if create:
            fd = os.open(
                self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            os.close(fd)
            sync_directory(self.path.parent)
        self._identity = require_private_file(self.path)
        self.account_id = account_id
        self.execution_target_id = execution_target_id
        with self._connection(initialize=create) as db:
            if create:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS target_owner (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    account_id TEXT NOT NULL, target_id TEXT NOT NULL,
                    coordinator_generation INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS agent_conversations (
                    conversation_reference TEXT PRIMARY KEY,
                    connection_id TEXT NOT NULL,
                    link_epoch TEXT,
                    revision INTEGER NOT NULL,
                    current_run TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_reference TEXT PRIMARY KEY,
                    conversation_reference TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    link_epoch TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    clarification_code TEXT,
                    request_key TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    task TEXT NOT NULL,
                    state TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    accepted_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    private_history TEXT NOT NULL DEFAULT '[]',
                    claim_generation INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (connection_id, request_key),
                    UNIQUE (conversation_reference, revision)
                );
            """)
                db.execute(
                    "INSERT INTO target_owner (singleton, account_id, target_id) VALUES (1, ?, ?)",
                    (account_id, execution_target_id),
                )
                db.execute("PRAGMA application_id=1396785746")
                db.execute("PRAGMA user_version=2")
            self._require_store_identity(db)
        if create:
            sync_directory(self.path.parent)

    def _require_store_identity(self, db: sqlite3.Connection) -> None:
        if db.execute("PRAGMA application_id").fetchone()[
            0
        ] != 1396785746 or db.execute("PRAGMA user_version").fetchone()[0] not in {
            1,
            2,
        }:
            raise PermissionError("Target store format is unavailable.")
        owner = db.execute(
            "SELECT account_id, target_id FROM target_owner WHERE singleton = 1"
        ).fetchone()
        if owner is None or tuple(owner) != (self.account_id, self.execution_target_id):
            raise PermissionError("Target store ownership does not match.")

    @contextmanager
    def _connection(self, *, initialize: bool = False):
        require_private_directory(self.path.parent)
        require_private_file(self.path, identity=self._identity)
        self._require_private_sidecars()
        connection = sqlite3.connect(
            f"file:{quote(str(self.path))}?mode=rw", uri=True, timeout=3
        )
        connection.row_factory = sqlite3.Row
        try:
            if not initialize:
                self._require_store_identity(connection)
            if connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                raise RuntimeError("Target storage durability mode is unavailable.")
            connection.execute("PRAGMA synchronous=FULL")
            if connection.execute("PRAGMA synchronous").fetchone()[0] != 2:
                raise RuntimeError("Target storage durability mode is unavailable.")
            require_private_file(self.path, identity=self._identity)
            self._require_private_sidecars()
            with connection:
                yield connection
        finally:
            connection.close()

    def _require_private_sidecars(self) -> None:
        for suffix in ("-wal", "-shm", "-journal"):
            path = Path(str(self.path) + suffix)
            if path.exists() or path.is_symlink():
                require_private_file(path)

    @staticmethod
    def _record(row: sqlite3.Row) -> AgentRun:
        return AgentRun(
            **{
                key: row[key]
                for key in AgentRun.__dataclass_fields__
                if key in row.keys()
            }
        )

    @staticmethod
    def _authority(
        link_epoch: str | None, authority: Callable[[], bool] | None
    ) -> None:
        if link_epoch is not None and (
            not isinstance(link_epoch, str)
            or not 1 <= len(link_epoch) <= 128
            or authority is None
            or authority() is not True
        ):
            raise PermissionError("Provider Connection is unavailable.")

    @staticmethod
    def _binding(row: sqlite3.Row, link_epoch: str | None) -> None:
        if (row["link_epoch"] if "link_epoch" in row.keys() else None) != link_epoch:
            raise PermissionError("Agent Run Reference is unavailable.")

    @staticmethod
    def _snapshot(db: sqlite3.Connection, run_reference: str) -> sqlite3.Row:
        if db.execute("PRAGMA user_version").fetchone()[0] == 1:
            return db.execute(
                "SELECT * FROM agent_runs WHERE run_reference = ?", (run_reference,)
            ).fetchone()
        return db.execute(
            """SELECT r.*, c.revision AS conversation_revision, c.state AS conversation_state
            FROM agent_runs r JOIN agent_conversations c USING (conversation_reference)
            WHERE r.run_reference = ?""",
            (run_reference,),
        ).fetchone()

    def accept(
        self,
        *,
        connection_id: str,
        task: str,
        mode: str,
        request_key: str,
        generation: int,
        link_epoch: str | None = None,
        authority: Callable[[], bool] | None = None,
    ) -> AgentRun:
        return self._accept(
            connection_id=connection_id,
            task=task,
            mode=mode,
            request_key=request_key,
            generation=generation,
            link_epoch=link_epoch,
            authority=authority,
        )

    def continue_turn(
        self,
        *,
        connection_id: str,
        conversation_reference: str,
        run_reference: str,
        expected_revision: int,
        task: str,
        request_key: str,
        generation: int,
        link_epoch: str,
        authority: Callable[[], bool],
    ) -> AgentRun:
        if (
            link_epoch is None
            or type(expected_revision) is not int
            or not 1 <= expected_revision < 2147483647
        ):
            raise ValueError("Conversation continuation is unavailable.")
        return self._accept(
            connection_id=connection_id,
            task=task,
            mode="source_free",
            request_key=request_key,
            generation=generation,
            link_epoch=link_epoch,
            authority=authority,
            continuation=(conversation_reference, run_reference, expected_revision),
        )

    @staticmethod
    def _generation(db: sqlite3.Connection, generation: int) -> None:
        if (
            db.execute(
                "SELECT coordinator_generation FROM target_owner WHERE singleton = 1"
            ).fetchone()[0]
            != generation
        ):
            raise RuntimeError("Agent run coordinator is unavailable.")

    @staticmethod
    def _capacity(db: sqlite3.Connection, connection_id: str, now: int) -> None:
        counts = db.execute(
            """SELECT COUNT(*) AS retained,
            SUM(state IN ('queued','running') AND expires_at > ?) AS pending,
            SUM(state IN ('queued','running') AND expires_at > ? AND connection_id = ?) AS connection_pending,
            SUM(accepted_at > ?) AS recent,
            SUM(accepted_at > ? AND connection_id = ?) AS connection_recent
            FROM agent_runs""",
            (now, now, connection_id, now - 3600, now - 3600, connection_id),
        ).fetchone()
        bounds = (
            ("retained", MAX_RETAINED_RUNS),
            ("pending", MAX_PENDING_PER_ACCOUNT),
            ("connection_pending", MAX_PENDING_PER_CONNECTION),
            ("recent", MAX_ACCEPTED_PER_ACCOUNT_HOUR),
            ("connection_recent", MAX_ACCEPTED_PER_CONNECTION_HOUR),
        )
        if any((counts[name] or 0) >= limit for name, limit in bounds):
            raise ValueError("Agent run capacity is unavailable.")

    def _accept(
        self,
        *,
        connection_id: str,
        task: str,
        mode: str,
        request_key: str,
        generation: int,
        link_epoch: str | None,
        authority: Callable[[], bool] | None,
        continuation: tuple[str, str, int] | None = None,
    ) -> AgentRun:
        if (
            mode != "source_free"
            or not isinstance(task, str)
            or not 1 <= len(task) <= 8192
        ):
            raise ValueError("Invalid source-free task.")
        canonical_input = {"task": task, "mode": mode}
        if continuation is not None:
            canonical_input["continuation"] = continuation
        input_hash = hashlib.sha256(
            json.dumps(canonical_input, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._authority(link_epoch, authority)
            self._generation(db, generation)
            now = int(time.time())
            existing = db.execute(
                "SELECT * FROM agent_runs WHERE connection_id = ? AND request_key = ?",
                (connection_id, request_key),
            ).fetchone()
            if existing is not None:
                self._binding(existing, link_epoch)
                if existing["expires_at"] <= now:
                    raise PermissionError("Agent Run Reference is unavailable.")
                if existing["input_hash"] != input_hash:
                    raise ValueError(
                        "Request key was already used for a different task."
                    )
                result = self._record(self._snapshot(db, existing["run_reference"]))
                self._authority(link_epoch, authority)
                if existing["expires_at"] <= int(time.time()):
                    raise PermissionError("Agent Run Reference is unavailable.")
                return result
            self._capacity(db, connection_id, now)
            new_run = mint_shipagent_id(ShipAgentIdFamily.AGENT_RUN)
            if continuation is None:
                conversation = mint_shipagent_id(ShipAgentIdFamily.CONVERSATION)
                revision, expires_at = 1, now + 86400
                db.execute(
                    "INSERT INTO agent_conversations VALUES (?, ?, ?, ?, ?, ?, 'active')",
                    (
                        conversation,
                        connection_id,
                        link_epoch,
                        revision,
                        new_run,
                        expires_at,
                    ),
                )
            else:
                conversation, previous_run, expected_revision = continuation
                row = db.execute(
                    "SELECT * FROM agent_conversations WHERE conversation_reference = ? AND connection_id = ? AND expires_at > ?",
                    (conversation, connection_id, now),
                ).fetchone()
                if row is None:
                    raise PermissionError("Conversation Reference is unavailable.")
                self._binding(row, link_epoch)
                if (
                    row["current_run"] != previous_run
                    or row["revision"] != expected_revision
                    or row["state"] != "waiting_for_input"
                ):
                    raise ValueError(
                        "Conversation revision or follow-up is unavailable."
                    )
                if expected_revision >= MAX_CONVERSATION_RUNS:
                    raise ValueError("Conversation turn limit reached.")
                revision, expires_at = expected_revision + 1, row["expires_at"]
                db.execute(
                    "UPDATE agent_conversations SET revision = ?, current_run = ?, state = 'active' WHERE conversation_reference = ?",
                    (revision, new_run, conversation),
                )
            db.execute(
                """INSERT INTO agent_runs
                (run_reference, conversation_reference, connection_id, link_epoch, revision, request_key, input_hash, task, state, outcome, accepted_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', 'pending', ?, ?)""",
                (
                    new_run,
                    conversation,
                    connection_id,
                    link_epoch,
                    revision,
                    request_key,
                    input_hash,
                    task,
                    now,
                    expires_at,
                ),
            )
            result = self._record(self._snapshot(db, new_run))
            self._authority(link_epoch, authority)
            if expires_at <= int(time.time()):
                raise PermissionError("Conversation Reference is unavailable.")
        return result

    def read(
        self,
        *,
        connection_id: str,
        run_reference: str,
        link_epoch: str | None = None,
        authority: Callable[[], bool] | None = None,
    ) -> AgentRun:
        with self._connection() as db:
            row = self._snapshot(db, run_reference)
            if (
                row is None
                or row["connection_id"] != connection_id
                or row["expires_at"] <= int(time.time())
            ):
                raise PermissionError("Agent Run Reference is unavailable.")
            self._binding(row, link_epoch)
            self._authority(link_epoch, authority)
            if row["expires_at"] <= int(time.time()):
                raise PermissionError("Agent Run Reference is unavailable.")
            return self._record(row)

    def prior_history(
        self, run: AgentRun, *, authority: Callable[[], bool]
    ) -> list[dict]:
        """Only an accepted next turn can load its predecessor's committed text."""
        if run.revision == 1:
            return []
        with self._connection() as db:
            row = db.execute(
                "SELECT private_history FROM agent_runs WHERE conversation_reference = ? AND revision = ? AND state = 'waiting_for_input'",
                (run.conversation_reference, run.revision - 1),
            ).fetchone()
            self._authority(run.link_epoch, authority)
            if row is None:
                raise PermissionError("Conversation history is unavailable.")
            return json.loads(row["private_history"])

    def upgrade(self, *, lease: CoordinatorLease) -> None:
        """Explicit V1 upgrade; opening or reading a store never migrates it.

        Every legacy row keeps its exact identity, input hash, private history,
        and lifetime. NULL epoch is unbound history, never inferred authority.
        DDL uses execute, not executescript, to retain one atomic transaction.
        """
        if lease.path != self.path.with_suffix(".coordinator.lock"):
            raise RuntimeError("Agent run coordinator is unavailable.")
        lease.require_owned()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            lease.require_owned()
            if db.execute("PRAGMA user_version").fetchone()[0] == 2:
                return
            db.execute("ALTER TABLE agent_runs RENAME TO agent_runs_v1")
            db.execute("""CREATE TABLE agent_runs (
                run_reference TEXT PRIMARY KEY,
                conversation_reference TEXT NOT NULL,
                connection_id TEXT NOT NULL, link_epoch TEXT,
                revision INTEGER NOT NULL DEFAULT 1, clarification_code TEXT,
                request_key TEXT NOT NULL, input_hash TEXT NOT NULL, task TEXT NOT NULL,
                state TEXT NOT NULL, outcome TEXT NOT NULL,
                accepted_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                private_history TEXT NOT NULL DEFAULT '[]',
                claim_generation INTEGER NOT NULL DEFAULT 0,
                UNIQUE(connection_id, request_key), UNIQUE(conversation_reference, revision)
            )""")
            db.execute("""INSERT INTO agent_runs
                (run_reference, conversation_reference, connection_id, request_key,
                 input_hash, task, state, outcome, accepted_at, expires_at,
                 private_history, claim_generation)
                SELECT run_reference, conversation_reference, connection_id, request_key,
                 input_hash, task, state, outcome, accepted_at, expires_at,
                 private_history, claim_generation FROM agent_runs_v1""")
            db.execute("""CREATE TABLE agent_conversations (
                conversation_reference TEXT PRIMARY KEY, connection_id TEXT NOT NULL,
                link_epoch TEXT, revision INTEGER NOT NULL, current_run TEXT NOT NULL,
                expires_at INTEGER NOT NULL, state TEXT NOT NULL
            )""")
            db.execute("""INSERT INTO agent_conversations
                SELECT conversation_reference, connection_id, NULL, 1, run_reference,
                expires_at, CASE WHEN state IN ('queued','running') THEN 'active' ELSE state END
                FROM agent_runs_v1""")
            db.execute("DROP TABLE agent_runs_v1")
            db.execute("PRAGMA user_version=2")
            lease.require_owned()

    def begin_coordinator(self, *, lease: CoordinatorLease) -> int:
        if lease.path != self.path.with_suffix(".coordinator.lock"):
            raise RuntimeError("Agent run coordinator is unavailable.")
        lease.require_owned()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("PRAGMA user_version").fetchone()[0] != 2:
                raise RuntimeError("Target store requires an owned upgrade.")
            generation = (
                db.execute(
                    "SELECT coordinator_generation FROM target_owner WHERE singleton = 1"
                ).fetchone()[0]
                + 1
            )
            if generation > 2147483647:
                raise RuntimeError("Agent run coordinator is unavailable.")
            db.execute(
                "UPDATE target_owner SET coordinator_generation = ? WHERE singleton = 1",
                (generation,),
            )
            db.execute(
                "UPDATE agent_conversations SET state = 'failed' WHERE state = 'active' AND current_run IN (SELECT run_reference FROM agent_runs WHERE state = 'running')"
            )
            db.execute(
                "UPDATE agent_runs SET state = 'failed', outcome = 'interrupted' WHERE state = 'running'"
            )
        return generation

    def cancel(
        self,
        *,
        connection_id: str,
        run_reference: str,
        generation: int,
        link_epoch: str | None = None,
        authority: Callable[[], bool] | None = None,
    ) -> AgentRun:
        """Fence exact-current follow-up without rewriting quiescent history."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._authority(link_epoch, authority)
            self._generation(db, generation)
            row = self._snapshot(db, run_reference)
            if (
                row is None
                or row["connection_id"] != connection_id
                or row["expires_at"] <= int(time.time())
            ):
                raise PermissionError("Agent Run Reference is unavailable.")
            self._binding(row, link_epoch)
            if row["state"] in {"queued", "running"}:
                db.execute(
                    "UPDATE agent_runs SET state = 'cancelled', outcome = 'cancelled' WHERE run_reference = ? AND state IN ('queued', 'running')",
                    (run_reference,),
                )
            if row["state"] in {"queued", "running", "waiting_for_input"}:
                db.execute(
                    """UPDATE agent_conversations SET state = 'cancelled'
                    WHERE current_run = ? AND revision = ? AND state IN ('active', 'waiting_for_input')""",
                    (run_reference, row["revision"]),
                )
            result = self._record(self._snapshot(db, run_reference))
            self._authority(link_epoch, authority)
            if row["expires_at"] <= int(time.time()):
                raise PermissionError("Agent Run Reference is unavailable.")
        return result

    def is_current_generation(self, generation: int) -> bool:
        with self._connection() as db:
            return (
                db.execute(
                    "SELECT coordinator_generation FROM target_owner WHERE singleton = 1"
                ).fetchone()[0]
                == generation
            )

    def is_active(self, run: AgentRun) -> bool:
        with self._connection() as db:
            return (
                db.execute(
                    "SELECT 1 FROM agent_runs WHERE run_reference = ? AND state = 'running' AND claim_generation = ? AND expires_at > ? AND (SELECT coordinator_generation FROM target_owner WHERE singleton = 1) = ?",
                    (
                        run.run_reference,
                        run.claim_generation,
                        int(time.time()),
                        run.claim_generation,
                    ),
                ).fetchone()
                is not None
            )

    def claim_next(self, *, generation: int) -> AgentRun | None:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "SELECT coordinator_generation FROM target_owner WHERE singleton = 1"
                ).fetchone()[0]
                != generation
            ):
                raise RuntimeError("Agent run coordinator is unavailable.")
            row = db.execute(
                "SELECT * FROM agent_runs WHERE state = 'queued' AND expires_at > ? ORDER BY accepted_at, run_reference LIMIT 1",
                (int(time.time()),),
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE agent_runs SET state = 'running', claim_generation = ? WHERE run_reference = ? AND state = 'queued'",
                (generation, row["run_reference"]),
            )
            row = db.execute(
                "SELECT * FROM agent_runs WHERE run_reference = ?",
                (row["run_reference"],),
            ).fetchone()
        return self._record(row)

    def finish(
        self,
        run: AgentRun,
        *,
        outcome: str,
        private_history: list[dict],
        clarification: str | None = None,
        authority: Callable[[], bool] | None = None,
    ) -> None:
        state = "completed" if outcome == "planning_completed" else "failed"
        if outcome == "clarification_required":
            if run.link_epoch is None:
                raise PermissionError("Clarification authority is unavailable.")
            state = "waiting_for_input"
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if run.expires_at <= int(time.time()):
                state, outcome, clarification = "failed", "interrupted", None
            if state in {"completed", "waiting_for_input"}:
                self._authority(run.link_epoch, authority)
            updated = db.execute(
                "UPDATE agent_runs SET state = ?, outcome = ?, private_history = ?, clarification_code = ? WHERE run_reference = ? AND state = 'running' AND claim_generation = ? AND (SELECT coordinator_generation FROM target_owner WHERE singleton = 1) = ?",
                (
                    state,
                    outcome,
                    json.dumps(private_history),
                    clarification,
                    run.run_reference,
                    run.claim_generation,
                    run.claim_generation,
                ),
            )

            if updated.rowcount:
                db.execute(
                    "UPDATE agent_conversations SET state = ? WHERE current_run = ? AND revision = ?",
                    (state, run.run_reference, run.revision),
                )
            if state in {"completed", "waiting_for_input"}:
                self._authority(run.link_epoch, authority)
                if run.expires_at <= int(time.time()):
                    raise PermissionError("Agent Run Reference is unavailable.")
