"""Failure qualification for metadata ownership, without source content."""

import asyncio
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict
from datetime import datetime

import pytest

from src.services.agent_runs.coordinator import CoordinatorBorrow
from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.source_ownership import ConversationFence
from src.services.agent_runs.store import AgentRunStore
from src.services.source_ingress.reservation_contracts import ReservationError
from src.services.source_ingress.reservation_store import (
    ReservationStore,
    ReservationTransaction,
)
from tests.services.source_ingress.reservation_fixtures import (
    SQLiteAuthorityFence,
    SQLiteSourceAuthority,
)
from tests.services.source_ingress.test_reservations import (
    arguments,
    coordinator,
    request,
    waiting_target,
)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX copied-process rejection")
@pytest.mark.parametrize("operation", ["reserve", "recover", "close"])
async def test_copied_coordinator_rejects_before_inherited_state_mutex(
    tmp_path, operation
):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        owner = coordinator(agent, metadata, authority)
        owner.reserve(**arguments(accepted), request=request())
        with owner._state_lock:
            pid = os.fork()
            if pid == 0:
                try:
                    if operation == "reserve":
                        owner.reserve(**arguments(accepted), request=request())
                    elif operation == "recover":
                        owner.recover(
                            **arguments(accepted), request_key="reservation-a"
                        )
                    else:
                        owner.close()
                except ReservationError:
                    os._exit(0)
                except BaseException:
                    os._exit(2)
                os._exit(3)
        status = None
        try:
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                finished, observed = os.waitpid(pid, os.WNOHANG)
                if finished:
                    status = observed
                    break
                await asyncio.sleep(0.01)
        finally:
            if status is None:
                os.kill(pid, signal.SIGKILL)
                _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        assert (
            owner.recover(**arguments(accepted), request_key="reservation-a").status
            == "reserved"
        )
        owner.close()


@pytest.mark.parametrize("effect", ["before", "after"])
async def test_final_borrow_retirement_interruption_has_deliberate_outcome(
    tmp_path, monkeypatch, effect
):
    class InterruptedRetirement(BaseException):
        pass

    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        owner = coordinator(agent, metadata, authority)
        retired = CoordinatorBorrow.retire

        def interrupted(token):
            if effect == "after":
                retired(token)
            raise InterruptedRetirement

        with monkeypatch.context() as fault:
            fault.setattr(CoordinatorBorrow, "retire", interrupted)
            with pytest.raises(InterruptedRetirement):
                owner.reserve(**arguments(accepted), request=request())
        # No context remains live after the final token actually retires.
        # A later explicit close must reconcile without any fabricated borrow.
        owner.close()
        replacement = coordinator(agent, metadata, authority)
        if effect == "before":
            with pytest.raises(ReservationError):
                replacement.recover(**arguments(accepted), request_key="reservation-a")
            replacement.close()
            await agent.close()
            await agent.start()
            replacement = coordinator(agent, metadata, authority)
        assert (
            replacement.recover(
                **arguments(accepted), request_key="reservation-a"
            ).status
            == "reserved"
        )
        replacement.close()


async def restart_owner(agent, metadata, authority):
    await agent.close()
    await agent.start()
    reopened = ReservationStore(
        metadata.path,
        account_id="account-a",
        execution_target_id="target-a",
        coordinator_path=agent.store.path.with_suffix(".coordinator.lock"),
    )
    from src.services.source_ingress.source_store_owner import SourceStoreOwner

    maintenance = SourceStoreOwner(agent, reopened)
    maintenance.open()
    return coordinator(agent, reopened, authority), reopened


@pytest.mark.parametrize("effect", ["before", "after"])
async def test_unknown_commit_retains_identity_and_requires_explicit_owner_recovery(
    tmp_path, monkeypatch, effect
):
    async with waiting_target(tmp_path) as (
        agent,
        metadata,
        authority,
        accepted,
        providers,
    ):
        owner = coordinator(agent, metadata, authority)
        original_commit = ReservationTransaction._commit_database

        def commit(tx):
            if effect == "after":
                original_commit(tx)
            raise sqlite3.OperationalError("PRIVATE_COMMIT_CANARY")

        try:
            with monkeypatch.context() as fault:
                fault.setattr(ReservationTransaction, "_commit_database", commit)
                with pytest.raises(ReservationError) as caught:
                    owner.reserve(**arguments(accepted), request=request())
            assert caught.value.code == "reservation_unavailable"
            assert "PRIVATE_" not in str(caught.value) + repr(caught.value)
            retained = owner._operation
            assert (
                retained is not None
                and retained.commit_attempted
                and not retained.commit_known
            )
            candidate = retained.receipt
            retained.borrow.require_owned()
            replacement = coordinator(agent, metadata, authority)
            with pytest.raises(ReservationError):
                replacement.reserve(**arguments(accepted), request=request())
            replacement.close()
        finally:
            owner.close()
        with pytest.raises(RuntimeError):
            agent.borrow_coordinator()
        fresh, reopened = await restart_owner(agent, metadata, authority)
        try:
            if effect == "before":
                with pytest.raises(ReservationError):
                    fresh.recover(**arguments(accepted), request_key="reservation-a")
                retried = fresh.reserve(**arguments(accepted), request=request())
                assert retried.reservation_id != candidate.reservation_id
            else:
                assert (
                    fresh.recover(**arguments(accepted), request_key="reservation-a")
                    == candidate
                )
            assert len(providers) == len(providers[0].requests) == 1
            with closing(sqlite3.connect(metadata.path)) as db:
                assert (
                    db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 1
                )
        finally:
            fresh.close()
            reopened.close()


@pytest.mark.parametrize("effect", ["before", "after"])
async def test_precommit_rollback_failure_retains_original_scope_until_recovery(
    tmp_path, monkeypatch, effect
):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        owner = coordinator(agent, metadata, authority)
        captured = []
        blocked = [True]
        original_rollback = ReservationTransaction._rollback_database

        def rollback(tx):
            if tx._db not in captured:
                captured.append(tx._db)
                tx._rollback_database = lambda: rollback(tx)
            if blocked[0]:
                if effect == "after":
                    original_rollback(tx)
                raise OSError("PRIVATE_ROLLBACK_CANARY")
            return original_rollback(tx)

        def denied_commit(transaction, **kwargs):
            raise ReservationError("reservation_unavailable")

        try:
            with monkeypatch.context() as fault:
                fault.setattr(ReservationTransaction, "_rollback_database", rollback)
                fault.setattr(ReservationTransaction, "commit", denied_commit)
                with pytest.raises(ReservationError) as caught:
                    owner.reserve(**arguments(accepted), request=request())
            assert "PRIVATE_" not in str(caught.value) + repr(caught.value)
            retained = owner._operation
            assert retained is not None
            assert not retained.commit_attempted and not retained.commit_known
            assert retained.source._db is captured[0]
            assert captured[0].in_transaction is (effect == "before")
            retained.borrow.require_owned()
            candidate = retained.receipt
            with pytest.raises(ReservationError):
                owner.close()
            assert owner._operation is retained
            replacement = coordinator(agent, metadata, authority)
            with pytest.raises(ReservationError):
                replacement.reserve(**arguments(accepted), request=request())
            replacement.close()
        finally:
            blocked[0] = False
            owner.close()
        with pytest.raises(RuntimeError):
            agent.borrow_coordinator()
        fresh, reopened = await restart_owner(agent, metadata, authority)
        try:
            with pytest.raises(ReservationError):
                fresh.recover(**arguments(accepted), request_key="reservation-a")
            with closing(sqlite3.connect(metadata.path)) as db:
                assert (
                    db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0
                )
            receipt = fresh.reserve(**arguments(accepted), request=request())
            assert receipt.reservation_id != candidate.reservation_id
        finally:
            fresh.close()
            reopened.close()


@pytest.mark.parametrize(
    "scope_type", [SQLiteAuthorityFence, ReservationTransaction, ConversationFence]
)
@pytest.mark.parametrize("effect", ["before", "after"])
async def test_uncertain_scope_retirement_retains_borrow_and_known_commit(
    tmp_path, monkeypatch, scope_type, effect
):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        owner = coordinator(agent, metadata, authority)
        retire = scope_type.retire

        def retiring(scope):
            if effect == "after":
                retire(scope)
            raise OSError("PRIVATE_RETIREMENT_CANARY")

        try:
            with monkeypatch.context() as fault:
                fault.setattr(scope_type, "retire", retiring)
                with pytest.raises(ReservationError) as caught:
                    owner.reserve(**arguments(accepted), request=request())
                assert caught.value.code == "reservation_unavailable"
                assert "PRIVATE_" not in str(caught.value)
                retained = owner._operation
                assert retained is not None and retained.commit_known
                saved = retained.receipt
                retained.borrow.require_owned()
                with pytest.raises(ReservationError):
                    owner.close()
                assert owner._operation is retained
                other = coordinator(agent, metadata, authority)
                with pytest.raises(ReservationError):
                    other.recover(**arguments(accepted), request_key="reservation-a")
                other.close()
        finally:
            owner.close()
        with pytest.raises(RuntimeError):
            agent.borrow_coordinator()
        fresh, reopened = await restart_owner(agent, metadata, authority)
        try:
            assert (
                fresh.recover(**arguments(accepted), request_key="reservation-a")
                == saved
            )
        finally:
            fresh.close()
            reopened.close()


CRASHING_RESERVATION = r"""
import asyncio, json, os, sys
from dataclasses import asdict
from pathlib import Path
from src.services.source_ingress.reservation_store import ReservationTransaction
from tests.services.source_ingress.test_reservations import arguments, coordinator, request, waiting_target
root, phase = Path(sys.argv[1]), sys.argv[2]
def save(name, value):
    with (root / name).open("w") as handle:
        json.dump(value, handle)
        handle.flush()
        os.fsync(handle.fileno())
async def main():
    async with waiting_target(root) as (agent, metadata, authority, accepted, providers):
        owner = coordinator(agent, metadata, authority)
        save("conversation.json", accepted)
        save("provider-count.json", len(providers))
        commit = ReservationTransaction.commit
        def crash_commit(scope, **kwargs):
            save("candidate.json", asdict(owner._operation.receipt))
            if phase == "before":
                os._exit(42)
            commit(scope, **kwargs)
            if phase == "after":
                os._exit(42)
        ReservationTransaction.commit = crash_commit
        receipt = owner.reserve(**arguments(accepted), request=request())
        save("acknowledged.json", asdict(receipt))
        os._exit(42)
asyncio.run(main())
"""


@pytest.mark.parametrize("phase", ["before", "after", "acknowledged"])
async def test_fresh_process_death_recovers_only_durable_metadata_identity(
    tmp_path, phase
):
    child = subprocess.run(
        [sys.executable, "-c", CRASHING_RESERVATION, str(tmp_path), phase],
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )
    assert child.returncode == 42, child.stderr
    accepted = json.loads((tmp_path / "conversation.json").read_text())
    candidate = json.loads((tmp_path / "candidate.json").read_text())
    assert (tmp_path / "acknowledged.json").exists() == (phase == "acknowledged")
    assert json.loads((tmp_path / "provider-count.json").read_text()) == 1
    providers = []

    def forbidden_provider(_):
        providers.append(True)
        raise AssertionError("Metadata recovery must not dispatch another model turn")

    runs = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
    )
    agent = AgentRunService(
        store=runs,
        provider_factory=forbidden_provider,
        connection_epoch=lambda _: "epoch-a",
    )
    await agent.start()
    metadata = ReservationStore(
        tmp_path / "sources.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        coordinator_path=runs.path.with_suffix(".coordinator.lock"),
    )
    from src.services.source_ingress.source_store_owner import SourceStoreOwner

    maintenance = SourceStoreOwner(agent, metadata)
    maintenance.open()
    authority = SQLiteSourceAuthority(tmp_path / "authority.sqlite3", create=False)
    owner = coordinator(agent, metadata, authority)
    try:
        if phase == "before":
            with pytest.raises(ReservationError):
                owner.recover(**arguments(accepted), request_key="reservation-a")
            result = owner.reserve(**arguments(accepted), request=request())
            assert result.reservation_id != candidate["reservation_id"]
        else:
            result = owner.recover(**arguments(accepted), request_key="reservation-a")
            assert asdict(result) == candidate
            if phase == "acknowledged":
                assert (
                    json.loads((tmp_path / "acknowledged.json").read_text())
                    == candidate
                )
        assert owner.reserve(**arguments(accepted), request=request()) == result
        assert (
            agent.read(
                connection_id="connection-a", run_reference=accepted["run_reference"]
            )["state"]
            == "waiting_for_input"
        )
        assert providers == []
        with closing(sqlite3.connect(metadata.path)) as db:
            assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 1
    finally:
        owner.close()
        metadata.close()
        await agent.close()


@pytest.mark.parametrize("boundary", ["deadline", "authority", "conversation"])
@pytest.mark.parametrize("stage", ["conversation", "source", "authority", "commit"])
async def test_expiry_after_each_acquisition_or_commit_never_acknowledges_stale_data(
    tmp_path, monkeypatch, boundary, stage
):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        clock, monotonic = [time.time()], [100.0]
        conversation_expiry = datetime.fromisoformat(accepted["expires_at"]).timestamp()
        authority_expiry = int(clock[0]) + 900
        if boundary == "conversation":
            authority_expiry = int(conversation_expiry) + 300
        authority.mutate(expires=authority_expiry)
        owner = coordinator(
            agent,
            metadata,
            authority,
            clock=lambda: clock[0],
            monotonic=lambda: monotonic[0],
        )
        cls = {
            "conversation": ConversationFence,
            "source": ReservationTransaction,
            "authority": SQLiteAuthorityFence,
            "commit": ReservationTransaction,
        }[stage]
        method = "commit" if stage == "commit" else "acquire"
        original = getattr(cls, method)

        def after_wait(scope, **kwargs):
            result = original(scope, **kwargs)
            if boundary == "deadline":
                monotonic[0] = 102.0
            else:
                clock[0] = (
                    authority_expiry if boundary == "authority" else conversation_expiry
                )
            return result

        with monkeypatch.context() as wait:
            wait.setattr(cls, method, after_wait)
            with pytest.raises(ReservationError) as caught:
                owner.reserve(**arguments(accepted), request=request())
        assert caught.value.code == "reservation_unavailable"
        with closing(sqlite3.connect(metadata.path)) as db:
            assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == (
                1 if stage == "commit" else 0
            )
        assert owner._operation is None
        owner.close()


async def test_upload_expiry_crossing_commit_remains_stored_and_never_renews(
    tmp_path, monkeypatch
):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        clock = [time.time()]
        authority.mutate(expires=int(clock[0]) + 900)
        owner = coordinator(agent, metadata, authority, clock=lambda: clock[0])
        commit = ReservationTransaction.commit
        captured = []

        def committed(scope, **kwargs):
            commit(scope, **kwargs)
            captured.append(owner._operation.receipt)
            clock[0] = captured[0].upload_expires_at

        with monkeypatch.context() as wait:
            wait.setattr(ReservationTransaction, "commit", committed)
            with pytest.raises(ReservationError) as caught:
                owner.reserve(**arguments(accepted), request=request())
        assert caught.value.code == "reservation_expired"
        for action in (
            lambda: owner.recover(**arguments(accepted), request_key="reservation-a"),
            lambda: owner.reserve(**arguments(accepted), request=request()),
        ):
            with pytest.raises(ReservationError) as caught:
                action()
            assert caught.value.code == "reservation_expired"
        with closing(sqlite3.connect(metadata.path)) as db:
            assert db.execute(
                "SELECT reservation_id,upload_expires_at FROM reservations"
            ).fetchall() == [
                (captured[0].reservation_id, captured[0].upload_expires_at)
            ]
        owner.close()


async def test_owner_shutdown_keeps_admitted_commit_pinned_until_actual_retirement(
    tmp_path, monkeypatch
):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        owner = coordinator(agent, metadata, authority)
        committing, release = threading.Event(), threading.Event()
        commit = ReservationTransaction.commit

        def held_commit(scope, **kwargs):
            committing.set()
            assert release.wait(1)
            return commit(scope, **kwargs)

        with monkeypatch.context() as wait:
            wait.setattr(ReservationTransaction, "commit", held_commit)
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(
                    owner.reserve, **arguments(accepted), request=request()
                )
                try:
                    assert await asyncio.to_thread(committing.wait, 1)
                    with pytest.raises(RuntimeError):
                        await agent.close()
                    with pytest.raises(RuntimeError):
                        agent.borrow_coordinator()
                    assert agent._lease.is_owned()
                    assert not pending.done()
                finally:
                    release.set()
                result = await asyncio.wrap_future(pending)
        assert result.status == "reserved"
        assert agent._lease.is_owned()
        owner.close()
        await agent.close()
        assert agent._lease is None
