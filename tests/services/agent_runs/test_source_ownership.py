"""Source setup borrows existing conversation ownership without changing it."""

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict

import pytest

from src.services.agent_runs.coordinator import CoordinatorLease
from src.services.agent_runs.store import AgentRunStore


@contextmanager
def owned_conversation(tmp_path, *, state="waiting_for_input", epoch="epoch-a"):
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    lease = CoordinatorLease(store.path.with_suffix(".coordinator.lock"))
    token = lease.borrow()
    generation = store.begin_coordinator(lease=lease)
    scope = None
    try:
        run = store.accept(
            connection_id="connection-a",
            link_epoch=epoch,
            authority=lambda: True,
            task="PRIVATE_TASK_CANARY",
            mode="source_free",
            request_key="first",
            generation=generation,
        )
        if state != "active":
            claimed = store.claim_next(generation=generation)
            store.finish(
                claimed,
                outcome=(
                    "clarification_required"
                    if state in {"waiting_for_input", "cancelled"}
                    else "completed"
                    if state == "completed"
                    else "interrupted"
                ),
                clarification=(
                    "shipping_goal"
                    if state in {"waiting_for_input", "cancelled"}
                    else None
                ),
                private_history=[{"role": "user", "content": "PRIVATE_HISTORY_CANARY"}],
                authority=lambda: True,
            )
        if state == "cancelled":
            store.cancel(
                connection_id="connection-a",
                run_reference=run.run_reference,
                generation=generation,
                link_epoch=epoch,
                authority=lambda: True,
            )
        scope = store.conversation_fence(borrow=token, generation=generation)
        yield store, token, generation, run, scope
    finally:
        if scope is not None:
            scope.retire()
        token.retire()
        lease.close()


def resolve(scope, run, **overrides):
    arguments = {
        "conversation_reference": run.conversation_reference,
        "connection_id": "connection-a",
        "link_epoch": "epoch-a",
        "now": time.time(),
    }
    arguments.update(overrides)
    return scope.resolve(**arguments)


def test_borrowed_conversation_is_private_materialized_and_read_only(tmp_path):
    with owned_conversation(tmp_path) as (store, _, generation, run, scope):
        with sqlite3.connect(store.path) as db:
            before = list(db.iterdump())
        scope.acquire(deadline=time.monotonic() + 2)
        owned = resolve(scope, run)
        assert asdict(owned) == {
            "conversation_reference": run.conversation_reference,
            "revision": 1,
            "expires_at": run.expires_at,
            "state": "waiting_for_input",
        }
        assert "PRIVATE_" not in repr(owned)
        with pytest.raises((AttributeError, TypeError)):
            owned.revision = 2
        scope.require_current(now=time.time())
        scope.retire()
        scope.retire()
        with pytest.raises(RuntimeError, match="unavailable"):
            resolve(scope, run)
        with pytest.raises(RuntimeError, match="unavailable"):
            scope.acquire(deadline=time.monotonic() + 2)
        assert store.is_current_generation(generation)
        with sqlite3.connect(store.path) as db:
            assert list(db.iterdump()) == before


@pytest.mark.parametrize(
    "overrides",
    [
        {"conversation_reference": "sa_conversation_" + "a" * 32},
        {"conversation_reference": "PRIVATE_PATH_CANARY"},
        {"connection_id": "foreign-connection"},
        {"link_epoch": "foreign-epoch"},
        {"link_epoch": None},
        {"link_epoch": ""},
    ],
)
def test_unknown_or_foreign_binding_is_unavailable(tmp_path, overrides):
    with owned_conversation(tmp_path) as (_, _, _, run, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        with pytest.raises(RuntimeError, match="^Source conversation is unavailable.$"):
            resolve(scope, run, **overrides)


@pytest.mark.parametrize("state", ["active", "completed", "failed", "cancelled"])
def test_ineligible_conversation_cannot_be_borrowed_for_source(tmp_path, state):
    with owned_conversation(tmp_path, state=state) as (_, _, _, run, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        with pytest.raises(RuntimeError, match="unavailable"):
            resolve(scope, run)


def test_expiry_is_rechecked_for_each_owned_result(tmp_path):
    with owned_conversation(tmp_path) as (_, _, _, run, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        resolve(scope, run, now=run.expires_at - 0.1)
        with pytest.raises(RuntimeError, match="unavailable"):
            scope.require_current(now=run.expires_at)


def test_factory_has_no_io_and_wrong_store_borrow_fails_before_open(
    tmp_path, monkeypatch
):
    with owned_conversation(tmp_path) as (store, token, generation, _, _):
        assert token.coordinator_path == store.path.with_suffix(".coordinator.lock")
        other = CoordinatorLease(tmp_path / "different.lock")
        other_token = other.borrow()
        scope = None

        def forbidden_open(*args, **kwargs):
            raise AssertionError("wrong-store borrowing must not open SQLite")

        try:
            with monkeypatch.context() as guard:
                guard.setattr(sqlite3, "connect", forbidden_open)
                scope = store.conversation_fence(
                    borrow=other_token, generation=generation
                )
                with pytest.raises(RuntimeError, match="unavailable"):
                    scope.acquire(deadline=time.monotonic() + 2)
        finally:
            if scope is not None:
                scope.retire()
            other_token.retire()
            other.close()


@pytest.mark.parametrize("generation_delta", [-1, 1])
def test_stale_generation_is_rejected_without_advancing_owner(
    tmp_path, generation_delta
):
    with owned_conversation(tmp_path) as (store, token, generation, _, _):
        scope = store.conversation_fence(
            borrow=token, generation=generation + generation_delta
        )
        try:
            with pytest.raises(RuntimeError, match="unavailable"):
                scope.acquire(deadline=time.monotonic() + 2)
        finally:
            scope.retire()
        assert store.is_current_generation(generation)


def test_retired_or_quarantined_borrow_cannot_acquire_or_continue(tmp_path):
    with owned_conversation(tmp_path) as (_, token, _, run, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        resolve(scope, run)
        token.quarantine()
        with pytest.raises(RuntimeError, match="unavailable"):
            scope.require_current(now=time.time())
        scope.retire()
        token.retire()
        with pytest.raises(RuntimeError, match="unavailable"):
            resolve(scope, run)


def test_null_epoch_record_is_ineligible_even_when_locally_waiting(tmp_path):
    with owned_conversation(tmp_path) as (store, _, _, run, scope):
        # Exercise fail-closed handling of a legacy/corrupt record; this setup
        # does not authorize promoting a real unbound conversation.
        with sqlite3.connect(store.path) as db:
            db.execute("UPDATE agent_conversations SET link_epoch = NULL")
        scope.acquire(deadline=time.monotonic() + 2)
        with pytest.raises(RuntimeError, match="unavailable"):
            resolve(scope, run)


@pytest.mark.parametrize(
    "revision, expiry",
    [(0, None), (9, None), (1.5, None), (1, float("inf"))],
)
def test_invalid_stored_revision_or_expiry_cannot_become_owned_snapshot(
    tmp_path, revision, expiry
):
    with owned_conversation(tmp_path) as (store, _, _, run, scope):
        with sqlite3.connect(store.path) as db:
            db.execute(
                "UPDATE agent_conversations SET revision = ?, expires_at = ?",
                (revision, run.expires_at if expiry is None else expiry),
            )
        scope.acquire(deadline=time.monotonic() + 2)
        with pytest.raises(RuntimeError, match="unavailable"):
            resolve(scope, run)


def test_replaced_lease_file_invalidates_already_acquired_scope(tmp_path):
    with owned_conversation(tmp_path) as (_, token, _, run, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        resolve(scope, run)
        token.coordinator_path.rename(tmp_path / "retired.lock")
        with pytest.raises(RuntimeError, match="unavailable"):
            scope.require_current(now=time.time())


@pytest.mark.parametrize("schema_lock", [False, True])
def test_writer_and_schema_waits_use_short_common_deadline(tmp_path, schema_lock):
    with owned_conversation(tmp_path) as (store, _, _, _, scope):
        blocker = sqlite3.connect(store.path, isolation_level=None)
        try:
            if schema_lock:
                blocker.execute("PRAGMA journal_mode=DELETE")
            blocker.execute("BEGIN EXCLUSIVE" if schema_lock else "BEGIN IMMEDIATE")
            started = time.monotonic()
            with pytest.raises(RuntimeError, match="unavailable"):
                scope.acquire(deadline=started + 0.08)
            assert time.monotonic() - started < 0.75
            scope.retire()
        finally:
            blocker.rollback()
            blocker.close()


def test_foreign_format_is_rejected_before_journal_change_and_handle_retires(
    tmp_path, monkeypatch
):
    with owned_conversation(tmp_path) as (store, _, _, _, scope):
        with sqlite3.connect(store.path) as db:
            db.execute("PRAGMA application_id=1")
            db.execute("PRAGMA journal_mode=DELETE")
        real_connect = sqlite3.connect
        opened = []

        def capture_connection(*args, **kwargs):
            db = real_connect(*args, **kwargs)
            opened.append(db)
            return db

        with monkeypatch.context() as guard:
            guard.setattr(sqlite3, "connect", capture_connection)
            with pytest.raises(RuntimeError, match="unavailable"):
                scope.acquire(deadline=time.monotonic() + 2)
        assert len(opened) == 1
        scope.retire()
        with pytest.raises(sqlite3.ProgrammingError):
            opened[0].execute("SELECT 1")
        with real_connect(store.path) as db:
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
            assert db.execute("PRAGMA application_id").fetchone()[0] == 1


def test_cancel_waits_for_writer_fence_then_fresh_resolution_denies(
    tmp_path, monkeypatch
):
    with owned_conversation(tmp_path) as (store, token, generation, run, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        resolve(scope, run)
        entered_write = threading.Event()
        real_connect = sqlite3.connect

        def capture_connection(*args, **kwargs):
            db = real_connect(*args, **kwargs)
            db.set_trace_callback(
                lambda sql: entered_write.set() if sql == "BEGIN IMMEDIATE" else None
            )
            return db

        def cancel():
            return store.cancel(
                connection_id="connection-a",
                run_reference=run.run_reference,
                generation=generation,
                link_epoch="epoch-a",
                authority=lambda: True,
            )

        with monkeypatch.context() as guard, ThreadPoolExecutor(max_workers=1) as pool:
            guard.setattr(sqlite3, "connect", capture_connection)
            future = pool.submit(cancel)
            try:
                assert entered_write.wait(1)
                assert not future.done()
                assert resolve(scope, run).state == "waiting_for_input"
            finally:
                scope.retire()
            assert future.result(timeout=2).conversation_state == "cancelled"
        fresh = store.conversation_fence(borrow=token, generation=generation)
        try:
            fresh.acquire(deadline=time.monotonic() + 2)
            with pytest.raises(RuntimeError, match="unavailable"):
                resolve(fresh, run)
        finally:
            fresh.retire()


@pytest.mark.parametrize("bad_time", [True, float("nan"), float("inf"), -float("inf")])
def test_invalid_deadline_and_response_clock_fail_closed(tmp_path, bad_time):
    with owned_conversation(tmp_path) as (store, token, generation, run, scope):
        with pytest.raises(RuntimeError, match="unavailable"):
            scope.acquire(deadline=bad_time)
        scope.retire()
        fresh = store.conversation_fence(borrow=token, generation=generation)
        try:
            fresh.acquire(deadline=time.monotonic() + 2)
            with pytest.raises(RuntimeError, match="unavailable"):
                resolve(fresh, run, now=bad_time)
        finally:
            fresh.retire()


def test_deadline_after_acquisition_denies_without_preventing_retirement(tmp_path):
    with owned_conversation(tmp_path) as (store, token, generation, run, _):
        clock = [100.0]
        scope = store.conversation_fence(
            borrow=token, generation=generation, monotonic=lambda: clock[0]
        )
        try:
            scope.acquire(deadline=102)
            resolve(scope, run)
            clock[0] = 102
            with pytest.raises(RuntimeError, match="unavailable"):
                scope.require_current(now=time.time())
        finally:
            scope.retire()
        # Deadline expiry does not release the borrowed lease or strand a DB
        # writer reservation once explicit retirement succeeds.
        token.require_owned()
        with sqlite3.connect(store.path, timeout=0) as db:
            db.execute("BEGIN IMMEDIATE")
            db.rollback()


def test_schema_work_consumes_the_same_budget_as_later_writer_wait(
    tmp_path, monkeypatch
):
    with owned_conversation(tmp_path) as (store, token, generation, _, _):
        offset = [0.0]
        timeouts = []
        real_connect = sqlite3.connect
        blocker = real_connect(store.path, isolation_level=None)
        blocker.execute("BEGIN IMMEDIATE")

        def trace(sql):
            if sql == "PRAGMA application_id" and offset[0] == 0:
                offset[0] = 0.06
            if sql.startswith("PRAGMA busy_timeout="):
                timeouts.append(int(sql.split("=")[1]))

        def capture_connection(*args, **kwargs):
            db = real_connect(*args, **kwargs)
            db.set_trace_callback(trace)
            return db

        scope = store.conversation_fence(
            borrow=token,
            generation=generation,
            monotonic=lambda: time.monotonic() + offset[0],
        )
        try:
            with monkeypatch.context() as guard:
                guard.setattr(sqlite3, "connect", capture_connection)
                started = time.monotonic()
                with pytest.raises(RuntimeError, match="unavailable"):
                    scope.acquire(deadline=started + 0.1)
                assert time.monotonic() - started < 0.75
            assert len(timeouts) >= 2
            assert 0 <= timeouts[-1] <= 40
            assert timeouts[0] - timeouts[-1] >= 50
        finally:
            scope.retire()
            blocker.rollback()
            blocker.close()
