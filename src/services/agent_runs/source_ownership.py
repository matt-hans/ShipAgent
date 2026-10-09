"""A borrowed, bounded writer reservation for private conversation ownership.

Only the future source operation owner may use this internal scope. Authority
must be acquired before resolve; a returned snapshot is descriptive data, never
permission for another operation. This scope never commits or changes history.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import quote

from src.registry.identifiers import ShipAgentIdFamily, parse_shipagent_id
from src.services.agent_runs.coordinator import CoordinatorBorrow
from src.services.agent_runs.private_storage import (
    require_private_directory,
    require_private_file,
)
from src.services.agent_runs.store import MAX_CONVERSATION_RUNS

if TYPE_CHECKING:
    from src.services.agent_runs.store import AgentRunStore

_UNAVAILABLE = "Source conversation is unavailable."


@dataclass(frozen=True, slots=True)
class OwnedConversation:
    conversation_reference: str = field(repr=False)
    revision: int
    expires_at: int
    state: str


class ConversationFence:
    def __init__(
        self,
        store: AgentRunStore,
        borrow: CoordinatorBorrow,
        generation: int,
        monotonic: Callable[[], float],
    ) -> None:
        self._store = store
        self._borrow = borrow
        self._generation = generation
        self._monotonic = monotonic
        self._deadline = 0.0
        self._db: sqlite3.Connection | None = None
        self._attempted = False
        self._active = False
        self._retired = False
        self._rolled_back = False
        self._resolved: OwnedConversation | None = None

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
            raise RuntimeError(_UNAVAILABLE)
        return self._deadline - now

    def _execute(self, sql: str, parameters: tuple = ()) -> sqlite3.Cursor:
        if self._db is None or self._retired:
            raise RuntimeError(_UNAVAILABLE)
        milliseconds = min(int(self._remaining() * 1000), 2**31 - 1)
        self._db.execute(f"PRAGMA busy_timeout={milliseconds}")
        result = self._db.execute(sql, parameters)
        self._remaining()
        return result

    def _require_files(self) -> None:
        self._borrow.require_source_usable()
        if self._borrow.coordinator_path != self._store.path.with_suffix(
            ".coordinator.lock"
        ):
            raise RuntimeError(_UNAVAILABLE)
        require_private_directory(self._store.path.parent)
        require_private_file(self._store.path, identity=self._store._identity)
        self._store._require_private_sidecars()

    def _require_generation(self) -> None:
        if type(self._generation) is not int or self._generation <= 0:
            raise RuntimeError(_UNAVAILABLE)
        if self._execute("PRAGMA user_version").fetchone()[0] != 2:
            raise RuntimeError(_UNAVAILABLE)
        row = self._execute(
            "SELECT coordinator_generation FROM target_owner WHERE singleton = 1"
        ).fetchone()
        if row is None or row[0] != self._generation:
            raise RuntimeError(_UNAVAILABLE)

    def acquire(self, *, deadline: float) -> None:
        """Capture the connection before validation; retain it on any failure."""
        if self._attempted or self._retired:
            raise RuntimeError(_UNAVAILABLE)
        self._attempted = True
        self._deadline = deadline
        try:
            self._remaining()
            self._require_files()
            self._db = sqlite3.connect(
                f"file:{quote(str(self._store.path))}?mode=rw",
                uri=True,
                timeout=self._remaining(),
                isolation_level=None,
            )
            self._db.row_factory = sqlite3.Row
            # Reject foreign identity before any journal-mode change.
            self._store._require_store_identity(self._db, execute=self._execute)
            if self._execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                raise RuntimeError(_UNAVAILABLE)
            self._execute("PRAGMA synchronous=FULL")
            if self._execute("PRAGMA synchronous").fetchone()[0] != 2:
                raise RuntimeError(_UNAVAILABLE)
            self._execute("BEGIN IMMEDIATE")
            self._require_files()
            self._store._require_store_identity(self._db, execute=self._execute)
            self._require_generation()
            self._remaining()
            self._active = True
        except Exception:
            raise RuntimeError(_UNAVAILABLE) from None

    def _require_active(self) -> None:
        if (
            not self._active
            or self._retired
            or self._db is None
            or not self._db.in_transaction
        ):
            raise RuntimeError(_UNAVAILABLE)
        self._remaining()
        self._require_files()
        self._store._require_store_identity(self._db, execute=self._execute)
        self._require_generation()

    @staticmethod
    def _require_live(expires_at: int, now: float) -> None:
        if (
            isinstance(now, bool)
            or not isinstance(now, (int, float))
            or not math.isfinite(now)
            or now >= expires_at
        ):
            raise RuntimeError(_UNAVAILABLE)

    def resolve(
        self,
        *,
        conversation_reference: str,
        connection_id: str,
        link_epoch: str,
        now: float,
    ) -> OwnedConversation:
        """Resolve only after the operation owner holds current authority."""
        try:
            self._require_active()
            parse_shipagent_id(
                conversation_reference, expected_family=ShipAgentIdFamily.CONVERSATION
            )
            if not isinstance(link_epoch, str) or not 1 <= len(link_epoch) <= 128:
                raise RuntimeError(_UNAVAILABLE)
            row = self._execute(
                """SELECT conversation_reference, revision, expires_at, state
                   FROM agent_conversations
                   WHERE conversation_reference = ? AND connection_id = ?
                   AND link_epoch = ? AND state = 'waiting_for_input'
                   AND typeof(revision) = 'integer' AND revision BETWEEN 1 AND ?
                   AND typeof(expires_at) = 'integer' AND expires_at > 0""",
                (
                    conversation_reference,
                    connection_id,
                    link_epoch,
                    MAX_CONVERSATION_RUNS,
                ),
            ).fetchone()
            if row is None or row["state"] != "waiting_for_input":
                raise RuntimeError(_UNAVAILABLE)
            self._require_live(row["expires_at"], now)
            self._resolved = OwnedConversation(**dict(row))
            self._remaining()
            return self._resolved
        except Exception:
            raise RuntimeError(_UNAVAILABLE) from None

    def require_current(self, *, now: float) -> None:
        """Revalidate the held owner/generation and original expiry after waits."""
        try:
            self._require_active()
            if self._resolved is None:
                raise RuntimeError(_UNAVAILABLE)
            self._require_live(self._resolved.expires_at, now)
            self._remaining()
        except Exception:
            raise RuntimeError(_UNAVAILABLE) from None

    def retire(self) -> None:
        """Rollback and close explicitly; never retire the caller's borrow.

        A failed retirement retains the captured connection and completed stage
        so its operation owner can quarantine and retry actual cleanup later.
        """
        self._active = False
        if self._retired:
            return
        try:
            if self._db is not None:
                if not self._rolled_back:
                    self._db.rollback()
                    self._rolled_back = True
                self._db.close()
                self._db = None
            self._retired = True
        except Exception:
            raise RuntimeError(_UNAVAILABLE) from None
