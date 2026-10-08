"""Private SQLite acceptance and outcomes for one exact account-owned target."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from src.registry.identifiers import ShipAgentIdFamily, mint_shipagent_id
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

    def public_result(self) -> dict[str, object]:
        return {
            "run_reference": self.run_reference,
            "conversation_reference": self.conversation_reference,
            "revision": 1,
            "state": self.state,
            "outcome": self.outcome,
            "expires_at": datetime.fromtimestamp(self.expires_at, UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "poll_after_seconds": 2 if self.state in {"queued", "running"} else 0,
        }


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
        with self._connection() as db:
            if create:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS target_owner (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    account_id TEXT NOT NULL, target_id TEXT NOT NULL,
                    coordinator_generation INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_reference TEXT PRIMARY KEY,
                    conversation_reference TEXT NOT NULL UNIQUE,
                    connection_id TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    task TEXT NOT NULL,
                    state TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    accepted_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    private_history TEXT NOT NULL DEFAULT '[]',
                    claim_generation INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (connection_id, request_key)
                );
            """)
                db.execute(
                    "INSERT INTO target_owner (singleton, account_id, target_id) VALUES (1, ?, ?)",
                    (account_id, execution_target_id),
                )
                db.execute("PRAGMA application_id=1396785746")
                db.execute("PRAGMA user_version=1")
            if (
                db.execute("PRAGMA application_id").fetchone()[0] != 1396785746
                or db.execute("PRAGMA user_version").fetchone()[0] != 1
            ):
                raise PermissionError("Target store format is unavailable.")
            owner = db.execute(
                "SELECT account_id, target_id FROM target_owner WHERE singleton = 1"
            ).fetchone()
            if owner is None or tuple(owner) != (account_id, execution_target_id):
                raise PermissionError("Target store ownership does not match.")
        if create:
            sync_directory(self.path.parent)

    @contextmanager
    def _connection(self):
        require_private_directory(self.path.parent)
        require_private_file(self.path, identity=self._identity)
        self._require_private_sidecars()
        connection = sqlite3.connect(
            f"file:{quote(str(self.path))}?mode=rw", uri=True, timeout=3
        )
        connection.row_factory = sqlite3.Row
        try:
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
        return AgentRun(**{key: row[key] for key in AgentRun.__dataclass_fields__})

    def accept(
        self,
        *,
        connection_id: str,
        task: str,
        mode: str,
        request_key: str,
        generation: int,
    ) -> AgentRun:
        if (
            mode != "source_free"
            or not isinstance(task, str)
            or not 1 <= len(task) <= 8192
        ):
            raise ValueError("Invalid source-free task.")
        run_reference = mint_shipagent_id(ShipAgentIdFamily.AGENT_RUN)
        conversation_reference = mint_shipagent_id(ShipAgentIdFamily.CONVERSATION)
        canonical = json.dumps(
            {"task": task, "mode": mode}, sort_keys=True, separators=(",", ":")
        )
        input_hash = hashlib.sha256(canonical.encode()).hexdigest()
        accepted_at = int(time.time())
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "SELECT coordinator_generation FROM target_owner WHERE singleton = 1"
                ).fetchone()[0]
                != generation
            ):
                raise RuntimeError("Agent run coordinator is unavailable.")
            existing = db.execute(
                "SELECT * FROM agent_runs WHERE connection_id = ? AND request_key = ?",
                (connection_id, request_key),
            ).fetchone()
            if existing is not None:
                if existing["input_hash"] != input_hash:
                    raise ValueError(
                        "Request key was already used for a different task."
                    )
                if existing["expires_at"] <= accepted_at:
                    raise PermissionError("Agent Run Reference is unavailable.")
                return self._record(existing)
            counts = db.execute(
                """SELECT COUNT(*) AS retained,
                SUM(state IN ('queued','running') AND expires_at > ?) AS pending,
                SUM(state IN ('queued','running') AND expires_at > ? AND connection_id = ?) AS connection_pending,
                SUM(accepted_at > ?) AS recent,
                SUM(accepted_at > ? AND connection_id = ?) AS connection_recent
                FROM agent_runs""",
                (
                    accepted_at,
                    accepted_at,
                    connection_id,
                    accepted_at - 3600,
                    accepted_at - 3600,
                    connection_id,
                ),
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
            db.execute(
                "INSERT INTO agent_runs (run_reference, conversation_reference, connection_id, request_key, input_hash, task, state, outcome, accepted_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', 'pending', ?, ?)",
                (
                    run_reference,
                    conversation_reference,
                    connection_id,
                    request_key,
                    input_hash,
                    task,
                    accepted_at,
                    accepted_at + 86400,
                ),
            )
        return self.read(connection_id=connection_id, run_reference=run_reference)

    def read(self, *, connection_id: str, run_reference: str) -> AgentRun:
        with self._connection() as db:
            row = db.execute(
                "SELECT * FROM agent_runs WHERE connection_id = ? AND run_reference = ? AND expires_at > ?",
                (connection_id, run_reference, int(time.time())),
            ).fetchone()
        if row is None:
            raise PermissionError("Agent Run Reference is unavailable.")
        return self._record(row)

    def begin_coordinator(self, *, lease: CoordinatorLease) -> int:
        if lease.path != self.path.with_suffix(".coordinator.lock"):
            raise RuntimeError("Agent run coordinator is unavailable.")
        lease.require_owned()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
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
                "UPDATE agent_runs SET state = 'failed', outcome = 'interrupted' WHERE state = 'running'"
            )
        return generation

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
        self, run: AgentRun, *, outcome: str, private_history: list[dict]
    ) -> None:
        state = "completed" if outcome == "planning_completed" else "failed"
        with self._connection() as db:
            db.execute(
                "UPDATE agent_runs SET state = ?, outcome = ?, private_history = ? WHERE run_reference = ? AND state = 'running' AND claim_generation = ? AND (SELECT coordinator_generation FROM target_owner WHERE singleton = 1) = ?",
                (
                    state,
                    outcome,
                    json.dumps(private_history),
                    run.run_reference,
                    run.claim_generation,
                    run.claim_generation,
                ),
            )
