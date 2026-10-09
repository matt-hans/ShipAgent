"""Durable cancellation never revives a task or rewrites its terminal history."""

from src.services.agent_runs.coordinator import CoordinatorLease
from src.services.agent_runs.store import AgentRunStore


def test_cancel_queued_run_survives_reopen_and_cannot_be_claimed(tmp_path):
    path = tmp_path / "runs.sqlite3"
    store = AgentRunStore(
        path, account_id="account-a", execution_target_id="target-a", create=True
    )
    lease = CoordinatorLease(path.with_suffix(".coordinator.lock"))
    arguments = {
        "connection_id": "connection-a",
        "task": "Plan safely",
        "mode": "source_free",
        "request_key": "original-key",
    }
    try:
        generation = store.begin_coordinator(lease=lease)
        accepted = store.accept(**arguments, generation=generation)
        cancelled = store.cancel(
            connection_id="connection-a",
            run_reference=accepted.run_reference,
            generation=generation,
        )
        assert cancelled.state == "cancelled"
        assert cancelled.outcome == "cancelled"
        assert cancelled.expires_at == accepted.expires_at
        assert cancelled.conversation_reference == accepted.conversation_reference
        assert store.claim_next(generation=generation) is None
    finally:
        lease.close()

    reopened = AgentRunStore(
        path, account_id="account-a", execution_target_id="target-a"
    )
    lease = CoordinatorLease(path.with_suffix(".coordinator.lock"))
    try:
        generation = reopened.begin_coordinator(lease=lease)
        assert reopened.accept(**arguments, generation=generation) == cancelled
        assert reopened.claim_next(generation=generation) is None
        assert (
            reopened.cancel(
                connection_id="connection-a",
                run_reference=accepted.run_reference,
                generation=generation,
            )
            == cancelled
        )
    finally:
        lease.close()


def test_cancel_running_run_fences_stale_completion_and_preserves_terminal_bytes(
    tmp_path,
):
    import sqlite3

    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    lease = CoordinatorLease(store.path.with_suffix(".coordinator.lock"))
    try:
        generation = store.begin_coordinator(lease=lease)
        for index, outcome in enumerate(
            (None, "planning_completed", "provider_failed")
        ):
            accepted = store.accept(
                connection_id="connection-a",
                task="Plan safely",
                mode="source_free",
                request_key=f"terminal-{index}",
                generation=generation,
            )
            running = store.claim_next(generation=generation)
            assert store.is_active(running)
            if outcome is not None:
                store.finish(
                    running,
                    outcome=outcome,
                    private_history=[
                        {"role": "assistant", "content": "PRIVATE_HISTORY"}
                    ],
                )
            original = store.read(
                connection_id="connection-a", run_reference=accepted.run_reference
            )
            with sqlite3.connect(store.path) as db:
                original_row = db.execute(
                    "SELECT * FROM agent_runs WHERE run_reference = ?",
                    (accepted.run_reference,),
                ).fetchone()
            cancelled = store.cancel(
                connection_id="connection-a",
                run_reference=accepted.run_reference,
                generation=generation,
            )
            if outcome is not None:
                assert cancelled == original
            else:
                assert cancelled.state == "cancelled"
            # Deliberately inspect complete persisted rows: the public projection
            # cannot reveal private history, acceptance hashes or original keys.
            with sqlite3.connect(store.path) as db:
                before = db.execute(
                    "SELECT * FROM agent_runs WHERE run_reference = ?",
                    (accepted.run_reference,),
                ).fetchone()
            if outcome is not None:
                assert before == original_row
            assert not store.is_active(running)
            store.finish(
                running,
                outcome="planning_completed",
                private_history=[{"content": "STALE_OVERWRITE"}],
            )
            assert (
                store.cancel(
                    connection_id="connection-a",
                    run_reference=accepted.run_reference,
                    generation=generation,
                )
                == cancelled
            )
            with sqlite3.connect(store.path) as db:
                after = db.execute(
                    "SELECT * FROM agent_runs WHERE run_reference = ?",
                    (accepted.run_reference,),
                ).fetchone()
            assert after == before
    finally:
        lease.close()


def test_cancel_requires_current_generation_connection_and_original_expiry(
    tmp_path, monkeypatch
):
    import pytest

    now = [1_800_000_000]
    monkeypatch.setattr("src.services.agent_runs.store.time.time", lambda: now[0])
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    lease = CoordinatorLease(store.path.with_suffix(".coordinator.lock"))
    try:
        generation = store.begin_coordinator(lease=lease)
        accepted = store.accept(
            connection_id="connection-a",
            task="Plan safely",
            mode="source_free",
            request_key="original-key",
            generation=generation,
        )
        for connection, reference in (
            ("connection-b", accepted.run_reference),
            ("connection-a", "unknown-reference"),
        ):
            with pytest.raises(PermissionError, match="unavailable"):
                store.cancel(
                    connection_id=connection,
                    run_reference=reference,
                    generation=generation,
                )
        assert (
            store.read(
                connection_id="connection-a", run_reference=accepted.run_reference
            )
            == accepted
        )
        newer_generation = store.begin_coordinator(lease=lease)
        with pytest.raises(RuntimeError, match="unavailable"):
            store.cancel(
                connection_id="connection-a",
                run_reference=accepted.run_reference,
                generation=generation,
            )
        now[0] = accepted.expires_at
        with pytest.raises(PermissionError, match="unavailable"):
            store.cancel(
                connection_id="connection-a",
                run_reference=accepted.run_reference,
                generation=newer_generation,
            )
        assert store.claim_next(generation=newer_generation) is None
    finally:
        lease.close()


def test_cancel_racing_completion_has_one_immutable_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    lease = CoordinatorLease(store.path.with_suffix(".coordinator.lock"))
    try:
        generation = store.begin_coordinator(lease=lease)
        accepted = store.accept(
            connection_id="connection-a",
            task="Plan safely",
            mode="source_free",
            request_key="racing-key",
            generation=generation,
        )
        running = store.claim_next(generation=generation)
        barrier = Barrier(2)

        def finish():
            barrier.wait(timeout=2)
            store.finish(running, outcome="planning_completed", private_history=[])

        def cancel():
            barrier.wait(timeout=2)
            return store.cancel(
                connection_id="connection-a",
                run_reference=accepted.run_reference,
                generation=generation,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            completed = pool.submit(finish)
            cancelled = pool.submit(cancel)
            completed.result(timeout=3)
            result = cancelled.result(timeout=3)
        assert result.state in {"completed", "cancelled"}
        assert (
            store.read(
                connection_id="connection-a", run_reference=accepted.run_reference
            )
            == result
        )
        assert (
            store.cancel(
                connection_id="connection-a",
                run_reference=accepted.run_reference,
                generation=generation,
            )
            == result
        )
    finally:
        lease.close()
