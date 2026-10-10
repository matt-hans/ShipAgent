"""Owned strict actions share durable behavior without blocking the event loop."""

import copy
import os
import sqlite3
import time

import pytest

from src.services.agent_runs.coordinator import CoordinatorLease
from src.services.agent_runs.store import AgentRunStore


@pytest.fixture
def owned(tmp_path):
    store = AgentRunStore(
        tmp_path / "runs.sqlite3", account_id="a", execution_target_id="t", create=True
    )
    lease = CoordinatorLease(store.path.with_suffix(".coordinator.lock"))
    store.upgrade(lease=lease)
    generation = store.begin_coordinator(lease=lease)
    scopes = []

    def allocate(*, monotonic=time.monotonic, acquire=True):
        borrow = lease.borrow()
        try:
            assert callable(getattr(store, "transaction", None)), (
                "missing owned Agent Run transaction"
            )
            tx = store.transaction(
                borrow=borrow, generation=generation, monotonic=monotonic
            )
        except BaseException:
            borrow.retire()
            raise
        scopes.append((tx, borrow))
        if acquire:
            tx.acquire(deadline=monotonic() + 2)
        return tx

    try:
        yield store, lease, generation, allocate
    finally:
        for tx, borrow in reversed(scopes):
            tx.retire()
            borrow.retire()
        lease.close()


def submit(tx, key="key", **overrides):
    args = {
        "connection_id": "c",
        "link_epoch": "epoch",
        "task": "Plan safely",
        "mode": "source_free",
        "request_key": key,
        "token_expires_at": time.time() + 90,
        "authority": lambda: True,
    }
    args.update(overrides)
    return tx.accept(**args)


def durable(allocate, action):
    tx = allocate()
    try:
        result = action(tx)
        tx.commit()
        return result
    finally:
        tx.retire()


def test_writer_contention_is_prompt_and_owner_remains_retireable(owned):
    store, _, _, allocate = owned
    with sqlite3.connect(store.path) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        tx = allocate(acquire=False)
        start = time.monotonic()
        with pytest.raises(RuntimeError, match="unavailable"):
            tx.acquire(deadline=start + 2)
        assert time.monotonic() - start < 0.25
        assert not tx.commit_attempted and not tx.commit_known
        tx.retire()


def test_commit_is_explicit_and_retirement_rolls_back(owned):
    store, _, _, allocate = owned
    tx = allocate()
    run = submit(tx)
    assert not tx.commit_attempted and not tx.commit_known
    tx.retire()
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 0
    tx2 = allocate()
    retry = submit(tx2)
    assert retry.run_reference != run.run_reference
    tx2.commit()
    assert tx2.commit_attempted and tx2.commit_known
    tx2.retire()
    assert (
        store.read(
            connection_id="c",
            run_reference=retry.run_reference,
            link_epoch="epoch",
            authority=lambda: True,
        )
        == retry
    )


def test_copy_cannot_use_or_retire_original(owned):
    _, _, _, allocate = owned
    tx = allocate()
    copied = copy.copy(tx)
    for action in (copied.retire, copied.commit, lambda: submit(copied)):
        with pytest.raises(RuntimeError, match="unavailable"):
            action()
    submit(tx)
    tx.commit()


def test_fork_cannot_retire_original(owned):
    _, _, _, allocate = owned
    tx = allocate()
    pid = os.fork()
    if pid == 0:
        try:
            tx.retire()
        except RuntimeError:
            os._exit(0)
        os._exit(3)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    submit(tx)
    tx.commit()


@pytest.mark.parametrize("bad", [None, True, float("nan"), float("inf"), "123", -1])
def test_strict_accept_requires_finite_current_token_expiry(owned, bad):
    _, _, _, allocate = owned
    tx = allocate()
    with pytest.raises((PermissionError, ValueError, RuntimeError)):
        submit(tx, token_expires_at=bad)
    assert not tx.commit_attempted


def test_original_fractional_turn_expiry_survives_retry_and_reopen(owned, monkeypatch):
    store, _, _, allocate = owned
    now = [1_800_000_000.25]
    monkeypatch.setattr("src.services.agent_runs.store.time.time", lambda: now[0])
    run = durable(allocate, lambda tx: submit(tx, token_expires_at=now[0] + 500))
    assert run.turn_authority_expires_at == now[0] + 120
    assert "turn_authority_expires_at" not in run.public_result()
    assert "turn_authority_expires_at" not in repr(run)
    now[0] += 130
    retry = durable(allocate, lambda tx: submit(tx, token_expires_at=now[0] + 500))
    assert retry == run
    reopened = AgentRunStore(store.path, account_id="a", execution_target_id="t")
    assert (
        reopened.read(
            connection_id="c",
            run_reference=run.run_reference,
            link_epoch="epoch",
            authority=lambda: True,
        )
        == run
    )
    assert durable(allocate, lambda tx: tx.claim()) is None
    assert (
        durable(
            allocate,
            lambda tx: tx.read(
                connection_id="c",
                run_reference=run.run_reference,
                link_epoch="epoch",
                authority=lambda: True,
            ),
        ).outcome
        == "interrupted"
    )


def test_continuation_retains_conversation_expiry_and_gets_own_turn(owned, monkeypatch):
    _, _, _, allocate = owned
    now = [1_800_000_000.25]
    monkeypatch.setattr("src.services.agent_runs.store.time.time", lambda: now[0])
    first = durable(allocate, lambda tx: submit(tx, token_expires_at=now[0] + 25.5))
    claimed = durable(allocate, lambda tx: tx.claim())
    durable(
        allocate,
        lambda tx: tx.finish(
            claimed,
            outcome="clarification_required",
            private_history=[{"role": "assistant", "content": "Which package?"}],
            clarification="package_scope",
            authority=lambda: True,
        ),
    )
    now[0] += 30
    second = durable(
        allocate,
        lambda tx: tx.continue_turn(
            connection_id="c",
            link_epoch="epoch",
            conversation_reference=first.conversation_reference,
            run_reference=first.run_reference,
            expected_revision=1,
            task="One package",
            request_key="next",
            token_expires_at=now[0] + 60,
            authority=lambda: True,
        ),
    )
    assert second.expires_at == first.expires_at
    assert second.turn_authority_expires_at == now[0] + 60
    claimed2 = durable(allocate, lambda tx: tx.claim())
    assert (
        durable(allocate, lambda tx: tx.history(claimed2, authority=lambda: True))
        == b'[{"role": "assistant", "content": "Which package?"}]'
    )


def test_strict_metadata_never_fetches_private_history(owned, monkeypatch):
    store, _, _, allocate = owned
    run = durable(allocate, submit)
    with sqlite3.connect(store.path) as db:
        db.execute(
            "UPDATE agent_runs SET private_history=?", ("PRIVATE_CANARY" * 100000,)
        )
    original = sqlite3.connect

    def guarded(*args, **kwargs):
        db = original(*args, **kwargs)
        db.set_authorizer(
            lambda op, table, column, *_: sqlite3.SQLITE_DENY
            if op == sqlite3.SQLITE_READ
            and table == "agent_runs"
            and column == "private_history"
            else sqlite3.SQLITE_OK
        )
        return db

    monkeypatch.setattr(sqlite3, "connect", guarded)
    assert durable(allocate, submit) == run
    assert (
        durable(
            allocate,
            lambda tx: tx.read(
                connection_id="c",
                run_reference=run.run_reference,
                link_epoch="epoch",
                authority=lambda: True,
            ),
        )
        == run
    )
    assert durable(allocate, lambda tx: tx.claim()).run_reference == run.run_reference


def test_oversized_history_denied_before_materialization(owned, monkeypatch):
    store, _, _, allocate = owned
    first = durable(allocate, submit)
    claimed = durable(allocate, lambda tx: tx.claim())
    durable(
        allocate,
        lambda tx: tx.finish(
            claimed,
            outcome="clarification_required",
            private_history=[],
            clarification="package_scope",
            authority=lambda: True,
        ),
    )
    second = durable(
        allocate,
        lambda tx: tx.continue_turn(
            connection_id="c",
            link_epoch="epoch",
            conversation_reference=first.conversation_reference,
            run_reference=first.run_reference,
            expected_revision=1,
            task="One package",
            request_key="next",
            token_expires_at=time.time() + 60,
            authority=lambda: True,
        ),
    )
    with sqlite3.connect(store.path) as db:
        db.execute(
            "UPDATE agent_runs SET private_history=? WHERE run_reference=?",
            ("X" * (1024 * 1024 + 1), first.run_reference),
        )
    tx = allocate()
    queries = []
    original = tx._execute

    def observe(sql, parameters=()):
        queries.append(sql)
        return original(sql, parameters)

    monkeypatch.setattr(tx, "_execute", observe)
    with pytest.raises(PermissionError, match="unavailable"):
        tx.history(second, authority=lambda: True)
    assert any("length(CAST(private_history AS BLOB))" in sql for sql in queries)
    assert not any(sql.startswith("SELECT private_history ") for sql in queries)


def test_strict_read_rejects_legacy_unbound_turn(owned):
    store, _, generation, allocate = owned
    run = store.accept(
        connection_id="c",
        link_epoch="epoch",
        task="Plan safely",
        mode="source_free",
        request_key="legacy",
        generation=generation,
        authority=lambda: True,
    )
    tx = allocate()
    with pytest.raises(PermissionError, match="unavailable"):
        tx.read(
            connection_id="c",
            link_epoch="epoch",
            run_reference=run.run_reference,
            authority=lambda: True,
        )


def test_deadline_crossing_during_sql_retains_cursor_for_cleanup(owned, monkeypatch):
    _, lease, _, allocate = owned
    now = [1.0]
    tx = allocate(monotonic=lambda: now[0])
    tx._db.set_trace_callback(lambda _: now.__setitem__(0, 4.0))
    with pytest.raises(RuntimeError, match="unavailable"):
        submit(tx)
    assert tx._cursor is not None
    tx.retire()
    assert tx._cursor is None
    assert lease.is_owned


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize(
    "stage", ["_commit_sql", "_rollback_sql", "_close_connection", "_close_cursor"]
)
def test_before_after_effect_faults_retain_truthful_cleanup(
    owned, monkeypatch, stage, after
):
    _, lease, _, allocate = owned
    tx = allocate()
    submit(tx)
    if stage == "_close_cursor":
        tx._cursor = tx._db.cursor()
    original = getattr(tx, stage)

    def fail():
        if after:
            original()
        raise OSError("PRIVATE_FAILURE_CANARY")

    monkeypatch.setattr(tx, stage, fail)
    with pytest.raises(RuntimeError, match="unavailable") as caught:
        tx.commit() if stage == "_commit_sql" else tx.retire()
    assert "CANARY" not in str(caught.value)
    assert lease.is_owned
    if stage == "_commit_sql":
        assert tx.commit_attempted and not tx.commit_known
    monkeypatch.setattr(tx, stage, original)
    tx.retire()
    assert tx.retirement_completed


def test_expired_claim_cannot_publish_success_but_can_record_interruption(
    owned, monkeypatch
):
    _, _, _, allocate = owned
    now = [1_800_000_000.25]
    monkeypatch.setattr("src.services.agent_runs.store.time.time", lambda: now[0])
    durable(allocate, lambda tx: submit(tx, token_expires_at=now[0] + 1))
    run = durable(allocate, lambda tx: tx.claim())
    now[0] += 2
    tx = allocate()
    with pytest.raises(PermissionError):
        tx.finish(
            run,
            outcome="planning_completed",
            private_history=[],
            authority=lambda: True,
        )
    tx.retire()
    durable(
        allocate, lambda tx: tx.finish(run, outcome="interrupted", private_history=[])
    )
    result = durable(
        allocate,
        lambda tx: tx.read(
            connection_id="c",
            run_reference=run.run_reference,
            link_epoch="epoch",
            authority=lambda: True,
        ),
    )
    assert result.state == "failed" and result.outcome == "interrupted"


def test_authority_callback_failure_has_closed_message(owned):
    _, _, _, allocate = owned

    def fail():
        raise ValueError("PRIVATE_AUTHORITY_CANARY")

    with pytest.raises(PermissionError, match="unavailable") as error:
        submit(allocate(), authority=fail)
    assert "CANARY" not in str(error.value)


def test_close_after_native_effect_retains_positive_retirement(owned, monkeypatch):
    _, _, _, allocate = owned
    tx = allocate()
    original = tx._close_connection

    def fail():
        tx._db.close()
        raise OSError("PRIVATE_CLOSE_CANARY")

    monkeypatch.setattr(tx, "_close_connection", fail)
    with pytest.raises(RuntimeError):
        tx.retire()
    monkeypatch.setattr(tx, "_close_connection", original)
    tx.retire()
    assert tx.retirement_completed


@pytest.mark.parametrize("point", ["before", "after"])
def test_commit_clock_boundary_preserves_attempted_and_known_facts(
    owned, monkeypatch, point
):
    store, _, _, allocate = owned
    now = [1.0]
    tx = allocate(monotonic=lambda: now[0])
    submit(tx)
    original = tx._commit_sql

    def commit():
        original()
        now[0] = 3.0

    if point == "before":
        now[0] = 3.0
    else:
        monkeypatch.setattr(tx, "_commit_sql", commit)
    with pytest.raises(RuntimeError):
        tx.commit()
    assert tx.commit_attempted == (point == "after")
    assert tx.commit_known == (point == "after")
    tx.retire()
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == int(
            point == "after"
        )


@pytest.mark.parametrize("after", [False, True])
def test_unknown_commit_is_never_reissued_and_survives_retirement(
    owned, monkeypatch, after
):
    store, _, _, allocate = owned
    tx = allocate()
    submit(tx)
    original = tx._commit_sql
    calls = []

    def commit():
        calls.append(1)
        if after:
            original()
        raise KeyboardInterrupt("lost commit response")

    monkeypatch.setattr(tx, "_commit_sql", commit)
    with pytest.raises(KeyboardInterrupt):
        tx.commit()
    with pytest.raises(RuntimeError):
        tx.commit()
    assert calls == [1]
    assert tx.commit_attempted and not tx.commit_known
    tx.retire()
    assert tx.commit_attempted and not tx.commit_known
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == int(after)


@pytest.mark.parametrize("point", ["file", "generation", "borrow", "deadline"])
def test_current_owner_is_rechecked_before_commit(owned, point, monkeypatch):
    store, _, generation, allocate = owned
    now = [1.0]
    tx = allocate(monotonic=lambda: now[0])
    submit(tx)
    if point == "file":
        monkeypatch.setattr(store, "_identity", (0, 0))
    elif point == "generation":
        tx._db.execute(
            "UPDATE target_owner SET coordinator_generation=?", (generation + 1,)
        ).close()
    elif point == "borrow":
        tx._borrow.retire()
    else:
        now[0] = 3.0
    with pytest.raises(RuntimeError):
        tx.commit()
    assert not tx.commit_attempted
    tx.retire()


def test_wrong_store_borrow_denies_before_connect(owned, tmp_path, monkeypatch):
    store, _, generation, _ = owned
    other = CoordinatorLease(tmp_path / "other.lock")
    borrow = other.borrow()
    tx = store.transaction(borrow=borrow, generation=generation)

    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected SQLite open")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    try:
        with pytest.raises(RuntimeError):
            tx.acquire(deadline=time.monotonic() + 2)
        tx.retire()
    finally:
        borrow.retire()
        other.close()


def test_conflict_and_stale_continuation_do_not_remint(owned):
    store, _, _, allocate = owned
    run = durable(allocate, submit)
    tx = allocate()
    with pytest.raises(ValueError, match="different task"):
        submit(tx, task="Different task")
    with pytest.raises(RuntimeError):
        tx.commit()
    tx.retire()
    claimed = durable(allocate, lambda tx: tx.claim())
    durable(
        allocate,
        lambda tx: tx.finish(
            claimed,
            outcome="clarification_required",
            clarification="package_scope",
            private_history=[],
            authority=lambda: True,
        ),
    )
    tx2 = allocate()
    with pytest.raises(ValueError):
        tx2.continue_turn(
            connection_id="c",
            conversation_reference=run.conversation_reference,
            run_reference=run.run_reference,
            expected_revision=2,
            task="One package",
            request_key="next",
            link_epoch="epoch",
            token_expires_at=time.time() + 60,
            authority=lambda: True,
        )
    tx2.retire()
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 1


def test_cancel_waiting_keeps_old_terminal_row(owned):
    _, _, _, allocate = owned
    run = durable(allocate, submit)
    claimed = durable(allocate, lambda tx: tx.claim())
    durable(
        allocate,
        lambda tx: tx.finish(
            claimed,
            outcome="clarification_required",
            clarification="package_scope",
            private_history=[],
            authority=lambda: True,
        ),
    )
    result = durable(
        allocate,
        lambda tx: tx.cancel(
            connection_id="c",
            run_reference=run.run_reference,
            link_epoch="epoch",
            authority=lambda: True,
        ),
    )
    assert result.state == "waiting_for_input"
    assert result.conversation_state == "cancelled"
    assert "clarification" not in result.public_result()


@pytest.mark.parametrize("kind", ["rollback", "cursor"])
def test_cleanup_after_effect_control_flow_is_retryable(owned, monkeypatch, kind):
    _, _, _, allocate = owned
    tx = allocate()
    submit(tx)
    method = "_rollback_sql" if kind == "rollback" else "_close_cursor"
    if kind == "cursor":
        tx._cursor = tx._db.cursor()
    original = getattr(tx, method)

    def interrupted():
        original()
        raise KeyboardInterrupt("retirement interrupted")

    monkeypatch.setattr(tx, method, interrupted)
    with pytest.raises(KeyboardInterrupt):
        tx.retire()
    monkeypatch.setattr(tx, method, original)
    tx.retire()
    assert tx.retirement_completed


def test_progress_callback_preserves_original_control_flow_and_cursor(owned):
    _, _, _, allocate = owned
    inside = [False]
    failure = KeyboardInterrupt("original progress interruption")

    def clock():
        if inside[0]:
            raise failure
        return 1.0

    tx = allocate(monotonic=clock)

    def callback():
        inside[0] = True
        try:
            return tx._progress()
        finally:
            inside[0] = False

    tx._db.set_progress_handler(callback, 1)
    with pytest.raises(KeyboardInterrupt) as captured:
        tx._execute(
            "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<1000) SELECT sum(x) FROM n"
        )
    assert captured.value is failure
    assert tx._cursor is not None
    tx.retire()


@pytest.mark.parametrize("method", ["read", "cancel"])
def test_strict_request_cannot_use_corrupt_null_link_binding(owned, method):
    store, _, _, allocate = owned
    run = durable(allocate, submit)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE agent_runs SET link_epoch=NULL")
    tx = allocate()
    with pytest.raises(PermissionError):
        getattr(tx, method)(
            connection_id="c",
            run_reference=run.run_reference,
            link_epoch=None,
            authority=lambda: True,
        )


def test_claim_expiry_projection_uses_one_cutoff(owned, monkeypatch):
    store, _, _, allocate = owned
    fixed = 1_800_000_000.0
    monkeypatch.setattr("src.services.agent_runs.store.time.time", lambda: fixed)
    durable(allocate, lambda tx: submit(tx, token_expires_at=fixed + 1))
    calls = [fixed + 0.5, fixed + 1, fixed + 1]
    monkeypatch.setattr(
        "src.services.agent_runs.store.time.time",
        lambda: calls.pop(0) if calls else fixed + 1,
    )
    tx = allocate()
    try:
        tx.claim()
        tx.commit()
    except PermissionError:
        pass
    finally:
        tx.retire()
    with sqlite3.connect(store.path) as db:
        state = db.execute("SELECT state FROM agent_runs").fetchone()[0]
        conversation = db.execute("SELECT state FROM agent_conversations").fetchone()[0]
        assert state != "failed" or conversation == "failed"
    assert durable(allocate, lambda tx: tx.claim()) is None
    with sqlite3.connect(store.path) as db:
        assert (
            db.execute("SELECT state FROM agent_conversations").fetchone()[0]
            == "failed"
        )


@pytest.mark.parametrize(
    "action", ["continue", "read", "cancel", "claim", "history", "finish"]
)
def test_original_reference_deadline_gates_commit_after_action(
    owned, monkeypatch, action
):
    store, _, _, allocate = owned
    now = [1_800_000_000.0]
    monkeypatch.setattr("src.services.agent_runs.store.time.time", lambda: now[0])
    run = durable(allocate, submit)
    if action in {"continue", "history", "finish"}:
        run = durable(allocate, lambda tx: tx.claim())
    if action == "continue":
        durable(
            allocate,
            lambda tx: tx.finish(
                run,
                outcome="clarification_required",
                clarification="package_scope",
                private_history=[],
                authority=lambda: True,
            ),
        )
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE agent_runs SET expires_at=?", (int(now[0] + 1),))
        db.execute("UPDATE agent_conversations SET expires_at=?", (int(now[0] + 1),))
    run = durable(
        allocate,
        lambda tx: tx.read(
            connection_id="c",
            run_reference=run.run_reference,
            link_epoch="epoch",
            authority=lambda: True,
        ),
    )
    tx = allocate()
    if action == "continue":
        tx.continue_turn(
            connection_id="c",
            conversation_reference=run.conversation_reference,
            run_reference=run.run_reference,
            expected_revision=1,
            task="One package",
            request_key="next",
            link_epoch="epoch",
            token_expires_at=now[0] + 60,
            authority=lambda: True,
        )
    elif action in {"read", "cancel"}:
        getattr(tx, action)(
            connection_id="c",
            run_reference=run.run_reference,
            link_epoch="epoch",
            authority=lambda: True,
        )
    elif action == "claim":
        assert tx.claim() is not None
    elif action == "history":
        assert tx.history(run, authority=lambda: True) == b"[]"
    else:
        tx.finish(
            run,
            outcome="planning_completed",
            private_history=[],
            authority=lambda: True,
        )
    now[0] += 2
    with pytest.raises(RuntimeError, match="unavailable"):
        tx.commit()
    assert not tx.commit_attempted
    tx.retire()


@pytest.mark.parametrize(
    "field,value",
    [
        ("expires_at", 2_000_000_000),
        ("revision", 7),
        ("conversation_reference", "forged"),
    ],
)
def test_finish_requires_durable_run_identity(owned, field, value):
    from dataclasses import replace

    _, _, _, allocate = owned
    durable(allocate, submit)
    run = durable(allocate, lambda tx: tx.claim())
    tx = allocate()
    with pytest.raises(PermissionError):
        tx.finish(
            replace(run, **{field: value}),
            outcome="planning_completed",
            private_history=[],
            authority=lambda: True,
        )


def test_interrupted_cleanup_survives_original_reference_expiry(owned, monkeypatch):
    store, _, _, allocate = owned
    now = [1_800_000_000.0]
    monkeypatch.setattr("src.services.agent_runs.store.time.time", lambda: now[0])
    durable(allocate, submit)
    run = durable(allocate, lambda tx: tx.claim())
    now[0] = run.expires_at + 1
    durable(
        allocate, lambda tx: tx.finish(run, outcome="interrupted", private_history=[])
    )
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT state,outcome FROM agent_runs").fetchone() == (
            "failed",
            "interrupted",
        )


def test_known_commit_after_reference_expiry_is_retained_but_not_acknowledged(
    owned, monkeypatch
):
    store, _, _, allocate = owned
    now = [1_800_000_000.0]
    monkeypatch.setattr("src.services.agent_runs.store.time.time", lambda: now[0])
    run = durable(allocate, submit)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE agent_runs SET expires_at=?", (int(now[0] + 1),))
        db.execute("UPDATE agent_conversations SET expires_at=?", (int(now[0] + 1),))
    tx = allocate()
    tx.cancel(
        connection_id="c",
        run_reference=run.run_reference,
        link_epoch="epoch",
        authority=lambda: True,
    )
    original = tx._commit_sql

    def commit():
        original()
        now[0] += 2

    monkeypatch.setattr(tx, "_commit_sql", commit)
    with pytest.raises(RuntimeError):
        tx.commit()
    assert tx.commit_attempted and tx.commit_known
    tx.retire()
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT state FROM agent_runs").fetchone()[0] == "cancelled"
