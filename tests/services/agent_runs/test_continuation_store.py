"""Real SQLite continuation admission is atomic and lifetime/authority bound."""

from contextlib import contextmanager

import pytest

from src.services.agent_runs.coordinator import CoordinatorLease
from src.services.agent_runs.store import AgentRunStore


@contextmanager
def owned_store(tmp_path):
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    lease = CoordinatorLease(store.path.with_suffix(".coordinator.lock"))
    try:
        yield store, store.begin_coordinator(lease=lease)
    finally:
        lease.close()


def waiting(store, generation):
    store.accept(
        connection_id="connection-a",
        link_epoch="link-a",
        authority=lambda: True,
        task="Plan",
        mode="source_free",
        request_key="first-key",
        generation=generation,
    )
    run = store.claim_next(generation=generation)
    store.finish(
        run,
        outcome="clarification_required",
        clarification="shipping_goal",
        private_history=[{"role": "user", "content": "Plan"}],
        authority=lambda: True,
    )
    return run


def continuation(store, current_generation, run, **overrides):
    kwargs = {
        "connection_id": "connection-a",
        "link_epoch": "link-a",
        "authority": lambda: True,
        "conversation_reference": run.conversation_reference,
        "run_reference": run.run_reference,
        "expected_revision": run.revision,
        "task": "One package",
        "request_key": "reply-key",
        "generation": current_generation,
    }
    kwargs.update(overrides)
    return store.continue_turn(**kwargs)


def test_conversation_turn_budget_cannot_be_evaded_with_fresh_keys(tmp_path):
    with owned_store(tmp_path) as (store, generation):
        run = waiting(store, generation)
        for number in range(2, 9):
            new = continuation(
                store, generation, run, request_key=f"reply-key-{number}"
            )
            run = store.claim_next(generation=generation)
            assert new.revision == run.revision == number
            store.finish(
                run,
                outcome="clarification_required",
                clarification="shipping_goal",
                private_history=[],
                authority=lambda: True,
            )
        with pytest.raises(ValueError, match="turn limit"):
            continuation(store, generation, run, request_key="overflow-key")


@pytest.mark.parametrize("same_key", [True, False])
def test_simultaneous_continuations_accept_one_writer(tmp_path, same_key):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    with owned_store(tmp_path) as (store, generation):
        run = waiting(store, generation)
        barrier = Barrier(2)

        def reply(number):
            barrier.wait()
            try:
                return continuation(
                    store,
                    generation,
                    run,
                    request_key="same-key" if same_key else f"reply-key-{number}",
                )
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reply, [1, 2]))
        accepted = [result for result in results if result is not None]
        assert len(accepted) == (2 if same_key else 1)
        assert len({result.run_reference for result in accepted}) == 1
        assert {result.revision for result in accepted} == {2}
        claimed = store.claim_next(generation=generation)
        assert claimed.run_reference == accepted[0].run_reference
        assert store.claim_next(generation=generation) is None


@pytest.mark.parametrize(
    "overrides, error",
    [
        ({"expected_revision": True}, ValueError),
        ({"expected_revision": 0}, ValueError),
        ({"expected_revision": 2}, ValueError),
        ({"run_reference": "different-run"}, ValueError),
        ({"conversation_reference": "different-conversation"}, PermissionError),
        ({"connection_id": "connection-b"}, PermissionError),
        ({"link_epoch": "link-b"}, PermissionError),
        ({"authority": lambda: False}, PermissionError),
        ({"generation": 0}, RuntimeError),
    ],
)
def test_stale_or_foreign_continuation_cannot_consume_followup(
    tmp_path, overrides, error
):
    with owned_store(tmp_path) as (store, generation):
        run = waiting(store, generation)
        with pytest.raises(error):
            continuation(store, generation, run, **overrides)
        accepted = continuation(store, generation, run)
        assert accepted.revision == 2


def test_changed_input_conflicts_but_retry_recovers_before_stale_revision_check(
    tmp_path,
):
    with owned_store(tmp_path) as (store, generation):
        run = waiting(store, generation)
        accepted = continuation(store, generation, run)
        assert continuation(store, generation, run) == accepted
        for overrides in (
            {"task": "Different answer"},
            {"expected_revision": 2},
            {"run_reference": accepted.run_reference},
        ):
            with pytest.raises(ValueError, match="Request key"):
                continuation(store, generation, run, **overrides)
        with pytest.raises(ValueError, match="revision"):
            continuation(store, generation, run, request_key="different-key")
        with pytest.raises(PermissionError):
            continuation(store, generation, run, authority=lambda: False)


def test_old_waiting_cancel_never_cancels_an_accepted_successor(tmp_path):
    with owned_store(tmp_path) as (store, generation):
        run = waiting(store, generation)
        accepted = continuation(store, generation, run)
        result = store.cancel(
            connection_id="connection-a",
            link_epoch="link-a",
            authority=lambda: True,
            run_reference=run.run_reference,
            generation=generation,
        )
        assert result.state == "waiting_for_input"
        assert (
            result.conversation_revision == 2 and result.conversation_state == "active"
        )
        assert "clarification" not in result.public_result()
        assert (
            store.claim_next(generation=generation).run_reference
            == accepted.run_reference
        )


def test_cancel_and_continue_race_has_one_ordered_outcome(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    with owned_store(tmp_path) as (store, generation):
        run = waiting(store, generation)
        barrier = Barrier(2)

        def cancel():
            barrier.wait()
            return store.cancel(
                connection_id="connection-a",
                link_epoch="link-a",
                authority=lambda: True,
                run_reference=run.run_reference,
                generation=generation,
            )

        def reply():
            barrier.wait()
            try:
                return continuation(store, generation, run)
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            cancel_future = pool.submit(cancel)
            reply_future = pool.submit(reply)
            cancelled, accepted = cancel_future.result(), reply_future.result()
        if accepted is None:
            assert cancelled.conversation_state == "cancelled"
            assert store.claim_next(generation=generation) is None
        else:
            assert cancelled.conversation_state == "active"
            assert (
                store.claim_next(generation=generation).run_reference
                == accepted.run_reference
            )


def test_original_expiry_is_not_renewed_by_continue_or_retry(tmp_path, monkeypatch):
    now = [1_800_000_000]
    monkeypatch.setattr("src.services.agent_runs.store.time.time", lambda: now[0])
    with owned_store(tmp_path) as (store, generation):
        run = waiting(store, generation)
        now[0] += 100
        child = continuation(store, generation, run)
        assert child.expires_at == run.expires_at
        now[0] = run.expires_at
        for kwargs in ({}, {"request_key": "fresh-key"}):
            with pytest.raises(PermissionError):
                continuation(store, generation, run, **kwargs)
        assert store.claim_next(generation=generation) is None


def test_authority_is_rechecked_after_waiting_for_database_writer(
    tmp_path, monkeypatch
):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    with owned_store(tmp_path) as (store, generation):
        run = waiting(store, generation)
        active = [True]
        entering = Event()
        original_connect = sqlite3.connect
        blocker = original_connect(store.path)
        blocker.execute("BEGIN IMMEDIATE")

        def traced_connect(*args, **kwargs):
            db = original_connect(*args, **kwargs)
            db.set_trace_callback(
                lambda sql: entering.set() if sql == "BEGIN IMMEDIATE" else None
            )
            return db

        monkeypatch.setattr(sqlite3, "connect", traced_connect)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                continuation, store, generation, run, authority=lambda: active[0]
            )
            try:
                assert entering.wait(1)
                active[0] = False
            finally:
                blocker.rollback()
                blocker.close()
            with pytest.raises(PermissionError):
                pending.result(timeout=2)
        active[0] = True
        assert continuation(store, generation, run).revision == 2


def test_revocation_at_commit_rolls_back_acceptance_and_key_consumption(tmp_path):
    with owned_store(tmp_path) as (store, generation):
        run = waiting(store, generation)
        checks = iter([True, False])
        with pytest.raises(PermissionError):
            continuation(store, generation, run, authority=lambda: next(checks))
        assert continuation(store, generation, run).revision == 2


def test_stale_finish_cannot_rewrite_old_turn_or_successor(tmp_path):
    with owned_store(tmp_path) as (store, generation):
        run = waiting(store, generation)
        accepted = continuation(store, generation, run)
        store.finish(
            run,
            outcome="planning_completed",
            private_history=[{"role": "assistant", "content": "STALE_CANARY"}],
            authority=lambda: True,
        )
        old = store.read(
            connection_id="connection-a",
            link_epoch="link-a",
            authority=lambda: True,
            run_reference=run.run_reference,
        )
        assert old.state == "waiting_for_input"
        assert old.conversation_revision == 2 and old.conversation_state == "active"
        assert (
            store.claim_next(generation=generation).run_reference
            == accepted.run_reference
        )


def test_expired_terminal_publication_does_not_create_followup(tmp_path, monkeypatch):
    now = [1_800_000_000]
    monkeypatch.setattr("src.services.agent_runs.store.time.time", lambda: now[0])
    with owned_store(tmp_path) as (store, generation):
        store.accept(
            connection_id="connection-a",
            link_epoch="link-a",
            authority=lambda: True,
            task="Plan",
            mode="source_free",
            request_key="first-key",
            generation=generation,
        )
        run = store.claim_next(generation=generation)
        now[0] = run.expires_at
        store.finish(
            run,
            outcome="clarification_required",
            clarification="shipping_goal",
            private_history=[],
            authority=lambda: True,
        )
        now[0] -= 1  # Inspect retained data without extending the actual deadline.
        result = store.read(
            connection_id="connection-a",
            link_epoch="link-a",
            authority=lambda: True,
            run_reference=run.run_reference,
        )
        assert result.state != "waiting_for_input"
        assert result.conversation_state != "waiting_for_input"


def test_legacy_unbound_run_cannot_gain_clarification_authority(tmp_path):
    with owned_store(tmp_path) as (store, generation):
        accepted = store.accept(
            connection_id="connection-a",
            task="Plan",
            mode="source_free",
            request_key="legacy-key",
            generation=generation,
        )
        run = store.claim_next(generation=generation)
        with pytest.raises(PermissionError, match="Clarification"):
            store.finish(
                run,
                outcome="clarification_required",
                clarification="shipping_goal",
                private_history=[],
            )
        assert (
            store.read(
                connection_id="connection-a", run_reference=accepted.run_reference
            ).state
            == "running"
        )


@pytest.mark.parametrize("operation", ["read", "retry"])
def test_expiry_during_final_authority_check_cannot_publish_reference(
    tmp_path, monkeypatch, operation
):
    now = [1_800_000_000]
    monkeypatch.setattr("src.services.agent_runs.store.time.time", lambda: now[0])
    with owned_store(tmp_path) as (store, generation):
        run = waiting(store, generation)
        accepted = continuation(store, generation, run)
        checks = 0

        def active():
            nonlocal checks
            checks += 1
            if checks == (1 if operation == "read" else 2):
                now[0] = run.expires_at
            return True

        with pytest.raises(PermissionError):
            if operation == "read":
                store.read(
                    connection_id="connection-a",
                    run_reference=accepted.run_reference,
                    link_epoch="link-a",
                    authority=active,
                )
            else:
                continuation(store, generation, run, authority=active)
