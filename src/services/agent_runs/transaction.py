"""Captured nonwaiting SQLite actions for the strict authenticated profile.

This private owner is not authorization. Its caller holds current external
account/link authority and owns the original coordinator borrow until retirement.
Every SQL result is detached before returning to a shared store helper. No public
method returns a connection, cursor, borrow or commit callback.
"""

from __future__ import annotations

import math
import os
import sqlite3
import threading
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote

from src.services.agent_runs.coordinator import CoordinatorBorrow
from src.services.agent_runs.private_storage import (
    require_private_directory,
    require_private_file,
)
from src.services.agent_runs.store import AgentRun

if TYPE_CHECKING:
    from src.services.agent_runs.store import AgentRunStore

_UNAVAILABLE = "Agent run transaction is unavailable."
MAX_HISTORY_BYTES = 1024 * 1024


@dataclass(frozen=True)
class _Result:
    row: sqlite3.Row | None
    rowcount: int

    def fetchone(self):
        return self.row


class _SQL:
    """Private shared-helper adapter; it cannot escape an action."""

    def __init__(self, owner):
        self._owner = owner

    def execute(self, sql, parameters=()):
        return self._owner._execute(sql, parameters)


class AgentRunTransaction:
    def __init__(
        self,
        store: AgentRunStore,
        borrow: CoordinatorBorrow,
        generation: int,
        monotonic: Callable[[], float],
    ):
        self._self = weakref.ref(self)
        self._pid = os.getpid()
        self._thread = threading.get_ident()
        self._store = store
        self._borrow = borrow
        self._generation = generation
        self._maintenance_mode = False
        self._monotonic = monotonic
        self._deadline = 0.0
        self._db: sqlite3.Connection | None = None
        self._cursor: sqlite3.Cursor | None = None
        self._progress_failure: BaseException | None = None
        self._attempted = False
        self._connect_unknown = False
        self._active = False
        self._failed = False
        self._retired = False
        self._rolled_back = False
        self._commit_attempted = False
        self._commit_known = False
        self._live_turn: float | None = None
        self._reference_expiry: int | None = None
        self._sql = _SQL(self)

    @classmethod
    def _maintenance(cls, store, borrow):
        owner = cls(store, borrow, 0, time.monotonic)
        owner._maintenance_mode = True
        return owner

    def _identity(self):
        if (
            self._self() is not self
            or self._pid != os.getpid()
            or self._thread != threading.get_ident()
        ):
            raise RuntimeError(_UNAVAILABLE)

    @property
    def commit_attempted(self) -> bool:
        self._identity()
        return self._commit_attempted

    @property
    def commit_known(self) -> bool:
        self._identity()
        return self._commit_known

    @property
    def retirement_completed(self) -> bool:
        self._identity()
        return self._retired

    @property
    def reference_expires_at(self) -> int | None:
        """Descriptive minimum learned from bound rows, even on action denial."""
        self._identity()
        return self._reference_expiry

    def _remaining(self):
        now = self._monotonic()
        if (
            type(now) not in (int, float)
            or not math.isfinite(now)
            or type(self._deadline) not in (int, float)
            or not math.isfinite(self._deadline)
            or now >= self._deadline
        ):
            raise RuntimeError(_UNAVAILABLE)
        return self._deadline - now

    def _files(self):
        self._borrow.require_owned()
        if self._borrow.coordinator_path != self._store.path.with_suffix(
            ".coordinator.lock"
        ):
            raise RuntimeError(_UNAVAILABLE)
        require_private_directory(self._store.path.parent)
        require_private_file(self._store.path, identity=self._store._identity)
        self._store._require_private_sidecars()

    def _progress(self):
        try:
            self._remaining()
            return 0
        except BaseException as exc:
            if self._progress_failure is None:
                self._progress_failure = exc
            return 1

    def _close_cursor(self):
        if self._cursor is not None:
            self._cursor.close()
            self._cursor = None

    def _execute(self, sql, parameters=()):
        self._identity()
        if self._db is None or self._cursor is not None or self._retired:
            raise RuntimeError(_UNAVAILABLE)
        self._remaining()
        # Capture before executing and before any post-SQL clock callback.
        self._cursor = self._db.cursor()
        try:
            self._cursor.execute(sql, parameters)
            self._remaining()
            row = self._cursor.fetchone()
            count = self._cursor.rowcount
            self._remaining()
        except BaseException:
            self._failed = True
            if self._progress_failure is not None:
                raise self._progress_failure from None
            raise
        self._close_cursor()
        return _Result(row, count)

    def acquire(self, *, deadline: float):
        self._identity()
        if self._attempted or self._retired:
            raise RuntimeError(_UNAVAILABLE)
        self._attempted = True
        self._deadline = deadline
        try:
            self._remaining()
            self._files()
            self._connect_unknown = True
            self._db = sqlite3.connect(
                f"file:{quote(str(self._store.path))}?mode=rw",
                uri=True,
                timeout=0,
                isolation_level=None,
            )
            self._connect_unknown = False
            if type(self._db) is not sqlite3.Connection:
                raise RuntimeError(_UNAVAILABLE)
            self._db.row_factory = sqlite3.Row
            self._db.set_progress_handler(self._progress, 1000)
            self._execute("PRAGMA busy_timeout=0")
            self._execute("PRAGMA temp_store=MEMORY")
            self._execute("PRAGMA trusted_schema=OFF")
            self._execute("PRAGMA automatic_index=OFF")
            self._store._require_store_identity(self._db, execute=self._execute)
            if (
                not self._maintenance_mode
                and self._execute("PRAGMA user_version").fetchone()[0] != 3
            ):
                raise RuntimeError(_UNAVAILABLE)
            if self._execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                raise RuntimeError(_UNAVAILABLE)
            self._execute("PRAGMA synchronous=FULL")
            if self._execute("PRAGMA synchronous").fetchone()[0] != 2:
                raise RuntimeError(_UNAVAILABLE)
            self._execute("BEGIN IMMEDIATE")
            self._active = True
            self._current()
        except BaseException as exc:
            self._failed = True
            if isinstance(exc, Exception):
                raise RuntimeError(_UNAVAILABLE) from None
            raise

    def _current(self):
        self._identity()
        if (
            not self._active
            or self._failed
            or self._retired
            or self._commit_attempted
            or self._db is None
            or not self._db.in_transaction
        ):
            raise RuntimeError(_UNAVAILABLE)
        self._remaining()
        self._files()
        self._store._require_store_identity(self._db, execute=self._execute)
        if not self._maintenance_mode:
            if type(self._generation) is not int or self._generation <= 0:
                raise RuntimeError(_UNAVAILABLE)
            self._store._generation(self._sql, self._generation)
        self._remaining()

    def _call(self, action):
        self._identity()
        try:
            self._current()
            if self._maintenance_mode:
                raise RuntimeError(_UNAVAILABLE)
            result = action()
            if type(result) is AgentRun:
                self._capture_run(result)
            self._current()
            return result
        except BaseException as exc:
            self._failed = True
            if isinstance(exc, (PermissionError, ValueError)):
                raise
            if isinstance(exc, Exception):
                raise RuntimeError(_UNAVAILABLE) from None
            raise

    def _capture_run(self, run: AgentRun, *, live_turn: bool = False) -> None:
        # Values have been matched to the held durable row by the fixed action.
        self._capture_reference(run.expires_at)
        if live_turn:
            expiry = run.turn_authority_expires_at
            if type(expiry) not in (int, float) or not math.isfinite(expiry):
                raise PermissionError("Agent Run Reference is unavailable.")
            self._live_turn = (
                min(self._live_turn, expiry) if self._live_turn is not None else expiry
            )

    def _capture_reference(self, expiry: int) -> None:
        if type(expiry) is not int or not 0 < expiry < 253402300800:
            raise PermissionError("Agent Run Reference is unavailable.")
        self._reference_expiry = (
            min(self._reference_expiry, expiry)
            if self._reference_expiry is not None
            else expiry
        )

    @staticmethod
    def _authority(callback):
        def checked():
            try:
                return callback() is True
            except Exception:
                raise PermissionError("Provider Connection is unavailable.") from None

        return checked

    def accept(
        self,
        *,
        connection_id: str,
        task: str,
        mode: str,
        request_key: str,
        link_epoch: str,
        token_expires_at: float,
        authority: Callable[[], bool],
    ) -> AgentRun:
        return self._accept(
            connection_id=connection_id,
            task=task,
            mode=mode,
            request_key=request_key,
            link_epoch=link_epoch,
            token_expires_at=token_expires_at,
            authority=authority,
        )

    def _accept(self, **arguments):
        arguments["authority"] = self._authority(arguments["authority"])

        def action():
            result, created = self._store._accept_on(
                self._sql,
                generation=self._generation,
                strict=True,
                _observe_reference=self._capture_reference,
                **arguments,
            )
            if created:
                self._capture_run(result, live_turn=True)
            return result

        return self._call(action)

    def continue_turn(
        self,
        *,
        connection_id: str,
        conversation_reference: str,
        run_reference: str,
        expected_revision: int,
        task: str,
        request_key: str,
        link_epoch: str,
        token_expires_at: float,
        authority: Callable[[], bool],
    ) -> AgentRun:
        if (
            type(expected_revision) is not int
            or not 1 <= expected_revision < 2147483647
        ):
            raise ValueError("Conversation continuation is unavailable.")
        return self._accept(
            connection_id=connection_id,
            task=task,
            mode="source_free",
            request_key=request_key,
            link_epoch=link_epoch,
            token_expires_at=token_expires_at,
            authority=authority,
            continuation=(conversation_reference, run_reference, expected_revision),
        )

    def read(
        self,
        *,
        connection_id: str,
        run_reference: str,
        link_epoch: str,
        authority: Callable[[], bool],
    ) -> AgentRun:
        return self._call(
            lambda: self._store._read_on(
                self._sql,
                connection_id=connection_id,
                run_reference=run_reference,
                link_epoch=link_epoch,
                authority=self._authority(authority),
                strict=True,
            )
        )

    def cancel(
        self,
        *,
        connection_id: str,
        run_reference: str,
        link_epoch: str,
        authority: Callable[[], bool],
    ) -> AgentRun:
        return self._call(
            lambda: self._store._cancel_on(
                self._sql,
                connection_id=connection_id,
                run_reference=run_reference,
                generation=self._generation,
                link_epoch=link_epoch,
                authority=self._authority(authority),
                strict=True,
            )
        )

    def claim(self) -> AgentRun | None:
        """Local candidate ownership only; this never grants model dispatch."""

        def action():
            result = self._store._claim_next_on(
                self._sql, generation=self._generation, strict=True
            )
            if result is not None:
                self._capture_run(result, live_turn=True)
            return result

        return self._call(action)

    def history(self, run: AgentRun, *, authority: Callable[[], bool]) -> bytes:
        def action():
            if type(run) is not AgentRun:
                raise PermissionError("Conversation history is unavailable.")
            result = self._store._history_on(
                self._sql, run, authority=self._authority(authority), strict=True
            )
            self._capture_run(run, live_turn=True)
            return result

        return self._call(action)

    def finish(
        self,
        run: AgentRun,
        *,
        outcome: str,
        private_history: list[dict],
        clarification: str | None = None,
        authority: Callable[[], bool] | None = None,
    ) -> None:
        def action():
            if type(run) is not AgentRun:
                raise PermissionError("Agent Run Reference is unavailable.")
            self._store._finish_on(
                self._sql,
                run,
                outcome=outcome,
                private_history=private_history,
                clarification=clarification,
                authority=self._authority(authority),
                strict=True,
            )
            if outcome in {"planning_completed", "clarification_required"}:
                self._capture_run(run, live_turn=True)

        return self._call(action)

    def _commit_sql(self):
        self._db.commit()

    def _check_clocks(self):
        self._remaining()
        now = time.time()
        if (
            type(now) not in (int, float)
            or not math.isfinite(now)
            or (self._live_turn is not None and now >= self._live_turn)
            or (self._reference_expiry is not None and now >= self._reference_expiry)
        ):
            raise RuntimeError(_UNAVAILABLE)

    def commit(self):
        self._identity()
        try:
            self._current()
            self._check_clocks()
            self._commit_attempted = True
            self._commit_sql()
            self._commit_known = True
            self._active = False
            self._check_clocks()
        except BaseException as exc:
            self._failed = True
            if isinstance(exc, Exception):
                raise RuntimeError(_UNAVAILABLE) from None
            raise

    def _rollback_sql(self):
        self._db.rollback()
        self._rolled_back = True

    def _close_connection(self):
        self._db.close()
        self._db = None

    def retire(self):
        """Retire captured cursors before connection; never release caller's pin.

        Cleanup uses exact ownership and may run after admission expiry. An
        uncertain connect/close retains the owner for later explicit recovery.
        """
        self._identity()
        if self._retired:
            return
        self._active = False
        try:
            if self._connect_unknown:
                raise RuntimeError(_UNAVAILABLE)
            if self._db is not None and type(self._db) is not sqlite3.Connection:
                raise RuntimeError(_UNAVAILABLE)
            self._close_cursor()
            if self._db is not None:
                # Exact native handle and all owned cursors are retired first.
                # In this supported CPython profile, in_transaction on a closed
                # native connection raises ProgrammingError (no SQL is run).
                try:
                    _ = self._db.in_transaction
                except sqlite3.ProgrammingError:
                    if type(self._db) is not sqlite3.Connection:
                        raise RuntimeError(_UNAVAILABLE) from None
                    self._db = None
            if self._db is not None:
                self._db.set_progress_handler(None, 0)
                if not self._rolled_back:
                    self._rollback_sql()
                self._close_connection()
            self._retired = True
        except Exception:
            raise RuntimeError(_UNAVAILABLE) from None
