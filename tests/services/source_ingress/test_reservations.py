"""Metadata-only reservation through the real shared conversation owner."""

import asyncio
import importlib
import importlib.util
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, closing
from datetime import datetime

import pytest

from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.source_ingress.reservation_contracts import (
    ReservationError,
    ReservationRequest,
    SourceOperatorContext,
)
from src.services.source_ingress.reservation_store import (
    ReservationStore,
    ReservationTransaction,
)
from tests.services.agent_runs.test_continuation import terminal
from tests.services.conversation_acceptance import text_turn
from tests.services.source_ingress.reservation_fixtures import (
    SQLiteAuthorityFence,
    SQLiteSourceAuthority,
)


def implementation():
    name = "src.services.source_ingress.reservations"
    assert importlib.util.find_spec(name) is not None, (
        "reservation coordinator is absent"
    )
    return importlib.import_module(name)


@asynccontextmanager
async def waiting_target(tmp_path, *, following_turn=None):
    providers = []

    def provider_factory(_):
        turn = text_turn('{"clarification_code":"shipping_goal"}')
        if providers and following_turn is not None:
            turn = following_turn
        provider = FakeProviderClient(script=[turn])
        providers.append(provider)
        return provider

    runs = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    agent = AgentRunService(
        store=runs,
        provider_factory=provider_factory,
        connection_epoch=lambda _: "epoch-a",
    )
    await agent.start()
    metadata = ReservationStore(
        tmp_path / "sources.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    metadata.open(deadline=time.monotonic() + 2)
    authority = SQLiteSourceAuthority(tmp_path / "authority.sqlite3")
    try:
        accepted = agent.submit(
            connection_id="connection-a",
            arguments={
                "task": "PRIVATE_TASK_CANARY",
                "mode": "source_free",
                "request_key": "initial",
            },
        )
        result = await terminal(agent, accepted["run_reference"])
        assert result["state"] == "waiting_for_input"
        # Terminal publication precedes provider cleanup. The contention tests
        # need the promised quiescent fixture, with its worker already idle.
        async with asyncio.timeout(3):
            while agent._active_run is not None:
                await asyncio.sleep(0.001)
        yield agent, metadata, authority, accepted, providers
    finally:
        metadata.close()
        await agent.close()


def request(key="reservation-a", **changes):
    values = {"request_key": key, "content_length": 12, "content_sha256": "a" * 64}
    values.update(changes)
    return ReservationRequest(**values)


def arguments(accepted):
    return {
        "operator_context": SourceOperatorContext("operator-a"),
        "provider_connection_id": "connection-a",
        "conversation_reference": accepted["conversation_reference"],
    }


def coordinator(agent, metadata, authority, **changes):
    return implementation().SourceReservationCoordinator(
        agent,
        metadata,
        authority,
        expected_target_fingerprint="fingerprint-a",
        **changes,
    )


async def test_reserve_recover_is_stable_read_only_and_never_calls_provider(
    tmp_path, monkeypatch
):
    from src.services.source_ingress import csv_snapshot

    async with waiting_target(tmp_path) as (
        agent,
        metadata,
        authority,
        accepted,
        providers,
    ):
        owner = coordinator(agent, metadata, authority)
        parsed = []

        def forbidden_parser(*args, **kwargs):
            parsed.append(True)
            raise AssertionError("Metadata reservation must not parse source bytes")

        monkeypatch.setattr(csv_snapshot, "parse_csv_snapshot", forbidden_parser)
        with closing(sqlite3.connect(agent.store.path)) as db:
            before = list(db.iterdump())
        first = owner.reserve(**arguments(accepted), request=request())
        assert owner.reserve(**arguments(accepted), request=request()) == first
        assert (
            owner.recover(**arguments(accepted), request_key="reservation-a") == first
        )
        assert first.status == "reserved"
        expiry = datetime.fromisoformat(accepted["expires_at"]).timestamp()
        assert first.upload_expires_at <= expiry
        assert first.prospective_source_expires_at <= expiry
        assert "PRIVATE_" not in repr(first)
        assert len(providers) == len(providers[0].requests) == 1
        assert parsed == []
        with closing(sqlite3.connect(agent.store.path)) as db:
            assert list(db.iterdump()) == before
        with closing(sqlite3.connect(metadata.path)) as db:
            assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 1
        assert authority.events[-1] == "retired"
        owner.close()


@pytest.mark.parametrize(
    "change",
    [
        {"enabled": 0},
        {"account": "other-account"},
        {"connection": "other-connection"},
        {"epoch": "other-epoch"},
        {"epoch": None},
        {"epoch": ""},
        {"target": "other-target"},
        {"fingerprint": "other-key"},
        {"purpose": "shipagent.preview"},
        {"purpose": "shipagent.status"},
        {"expires": 1},
    ],
)
async def test_current_authority_denials_precede_reservation_disclosure(
    tmp_path, monkeypatch, change
):
    async with waiting_target(tmp_path) as (
        agent,
        metadata,
        authority,
        accepted,
        providers,
    ):
        owner = coordinator(agent, metadata, authority)
        first = owner.reserve(**arguments(accepted), request=request())
        authority.mutate(**change)
        looked_up = []

        def premature_lookup(*args):
            looked_up.append(True)
            raise AssertionError("Identity read preceded current authority")

        monkeypatch.setattr(ReservationTransaction, "lookup", premature_lookup)
        for operation in (
            lambda: owner.reserve(
                **arguments(accepted), request=request(content_length=13)
            ),
            lambda: owner.recover(**arguments(accepted), request_key="reservation-a"),
        ):
            with pytest.raises(ReservationError) as caught:
                operation()
            assert caught.value.code == "reservation_unavailable"
            assert "PRIVATE_" not in str(caught.value) + repr(caught.value)
        assert looked_up == []
        assert len(providers) == len(providers[0].requests) == 1
        with closing(sqlite3.connect(metadata.path)) as db:
            assert db.execute("SELECT reservation_id FROM reservations").fetchall() == [
                (first.reservation_id,)
            ]
        owner.close()


@pytest.mark.parametrize(
    "changed",
    [
        {"operator_context": SourceOperatorContext("foreign-principal")},
        {"provider_connection_id": "foreign-connection"},
        {"conversation_reference": "sa_conversation_" + "b" * 32},
        {"conversation_reference": "PRIVATE_PATH_CANARY"},
    ],
)
async def test_unknown_selectors_have_one_closed_error(tmp_path, changed):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        owner = coordinator(agent, metadata, authority)
        supplied = arguments(accepted) | changed
        with pytest.raises(ReservationError) as caught:
            owner.recover(**supplied, request_key="unknown")
        assert caught.value.code == "reservation_unavailable"
        assert "PRIVATE_" not in str(caught.value)
        owner.close()


@pytest.mark.parametrize("missing", [True, False])
async def test_missing_or_failed_adapter_is_unavailable(tmp_path, missing):
    class Outage:
        def fence(self, *args, **kwargs):
            raise OSError("PRIVATE_AUTHORITY_CANARY")

    async with waiting_target(tmp_path) as (agent, metadata, _, accepted, providers):
        owner = coordinator(agent, metadata, None if missing else Outage())
        with pytest.raises(ReservationError) as caught:
            owner.reserve(**arguments(accepted), request=request())
        assert caught.value.code == "reservation_unavailable"
        assert "PRIVATE_" not in str(caught.value)
        assert len(providers) == 1
        owner.close()


async def test_changed_input_conflicts_only_after_current_authority(tmp_path):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        owner = coordinator(agent, metadata, authority)
        first = owner.reserve(**arguments(accepted), request=request())
        with pytest.raises(ReservationError) as caught:
            owner.reserve(**arguments(accepted), request=request(content_length=13))
        assert caught.value.code == "request_conflict"
        assert (
            owner.recover(**arguments(accepted), request_key="reservation-a") == first
        )
        owner.close()


@pytest.mark.parametrize("clock_name", ["clock", "monotonic"])
@pytest.mark.parametrize("value", [True, float("nan"), float("inf")])
async def test_nonfinite_or_bool_clock_never_admits(tmp_path, clock_name, value):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        owner = coordinator(agent, metadata, authority, **{clock_name: lambda: value})
        with pytest.raises(ReservationError) as caught:
            owner.reserve(**arguments(accepted), request=request())
        assert caught.value.code == "reservation_unavailable"
        with closing(sqlite3.connect(metadata.path)) as db:
            assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0
        owner.close()


async def test_cancellation_and_continuation_do_not_rebind_existing_reservation(
    tmp_path,
):
    async with waiting_target(tmp_path) as (
        agent,
        metadata,
        authority,
        accepted,
        providers,
    ):
        owner = coordinator(agent, metadata, authority)
        first = owner.reserve(**arguments(accepted), request=request())
        with closing(sqlite3.connect(metadata.path)) as db:
            before = list(db.iterdump())
        next_run = agent.continue_turn(
            connection_id="connection-a",
            arguments={
                "conversation_reference": accepted["conversation_reference"],
                "run_reference": accepted["run_reference"],
                "expected_revision": 1,
                "task": "One package",
                "request_key": "next-turn",
            },
        )
        with pytest.raises(ReservationError) as caught:
            owner.recover(**arguments(accepted), request_key="reservation-a")
        assert caught.value.code == "reservation_unavailable"
        await terminal(agent, next_run["run_reference"])
        assert (
            owner.recover(**arguments(accepted), request_key="reservation-a") == first
        )
        with closing(sqlite3.connect(metadata.path)) as db:
            assert list(db.iterdump()) == before
        agent.cancel(
            connection_id="connection-a", run_reference=next_run["run_reference"]
        )
        with pytest.raises(ReservationError) as caught:
            owner.recover(**arguments(accepted), request_key="reservation-a")
        assert caught.value.code == "reservation_unavailable"
        assert len(providers) == 2
        owner.close()


async def test_same_key_in_two_conversations_has_independent_private_identity(tmp_path):
    async with waiting_target(tmp_path) as (
        agent,
        metadata,
        authority,
        accepted,
        providers,
    ):
        owner = coordinator(agent, metadata, authority)
        first = owner.reserve(**arguments(accepted), request=request())
        second_conversation = agent.submit(
            connection_id="connection-a",
            arguments={
                "task": "Independent plan",
                "mode": "source_free",
                "request_key": "second-conversation",
            },
        )
        await terminal(agent, second_conversation["run_reference"])
        second = owner.reserve(**arguments(second_conversation), request=request())
        assert second.reservation_id != first.reservation_id
        assert (
            owner.recover(**arguments(accepted), request_key="reservation-a") == first
        )
        assert (
            owner.recover(**arguments(second_conversation), request_key="reservation-a")
            == second
        )
        assert len(providers) == 2
        owner.close()


@pytest.mark.parametrize(
    "state,turn", [("completed", text_turn("Plan complete")), ("failed", [])]
)
async def test_terminal_conversation_cannot_recover_metadata(tmp_path, state, turn):
    async with waiting_target(tmp_path, following_turn=turn) as (
        agent,
        metadata,
        authority,
        accepted,
        _,
    ):
        owner = coordinator(agent, metadata, authority)
        owner.reserve(**arguments(accepted), request=request())
        next_run = agent.continue_turn(
            connection_id="connection-a",
            arguments={
                "conversation_reference": accepted["conversation_reference"],
                "run_reference": accepted["run_reference"],
                "expected_revision": 1,
                "task": "One package",
                "request_key": "next-turn",
            },
        )
        assert (await terminal(agent, next_run["run_reference"]))["state"] == state
        with pytest.raises(ReservationError) as caught:
            owner.recover(**arguments(accepted), request_key="reservation-a")
        assert caught.value.code == "reservation_unavailable"
        owner.close()


async def test_legacy_null_epoch_is_unavailable(tmp_path):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        with closing(sqlite3.connect(agent.store.path)) as db:
            db.execute("UPDATE agent_conversations SET link_epoch=NULL")
            db.commit()
        owner = coordinator(agent, metadata, authority)
        with pytest.raises(ReservationError) as caught:
            owner.reserve(**arguments(accepted), request=request())
        assert caught.value.code == "reservation_unavailable"
        owner.close()


async def test_invalidation_commits_first_and_denies_waiting_reservation(
    tmp_path, monkeypatch
):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        owner = coordinator(agent, metadata, authority)
        attempted = threading.Event()
        acquire = SQLiteAuthorityFence.acquire

        def acquiring(scope, *, deadline):
            attempted.set()
            return acquire(scope, deadline=deadline)

        monkeypatch.setattr(SQLiteAuthorityFence, "acquire", acquiring)
        with closing(
            sqlite3.connect(authority.path, isolation_level=None)
        ) as invalidation:
            invalidation.execute("BEGIN IMMEDIATE")
            invalidation.execute("UPDATE principals SET enabled=0")
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(
                    owner.reserve, **arguments(accepted), request=request()
                )
                try:
                    assert await asyncio.to_thread(attempted.wait, 1)
                    assert not pending.done()
                finally:
                    invalidation.commit()
                with pytest.raises(ReservationError) as caught:
                    await asyncio.wrap_future(pending)
                assert caught.value.code == "reservation_unavailable"
        with closing(sqlite3.connect(metadata.path)) as db:
            assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0
        owner.close()


async def test_source_commit_keeps_authority_excluded_then_revocation_denies_retry(
    tmp_path, monkeypatch
):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        owner = coordinator(agent, metadata, authority)
        committing, release, mutating, mutated = (threading.Event() for _ in range(4))
        commit = ReservationTransaction.commit

        def held_commit(scope, **kwargs):
            committing.set()
            assert release.wait(1)
            return commit(scope, **kwargs)

        def revoke():
            mutating.set()
            authority.mutate(enabled=0)
            mutated.set()

        monkeypatch.setattr(ReservationTransaction, "commit", held_commit)
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = executor.submit(
                owner.reserve, **arguments(accepted), request=request()
            )
            invalidation = None
            try:
                assert await asyncio.to_thread(committing.wait, 1)
                invalidation = executor.submit(revoke)
                assert await asyncio.to_thread(mutating.wait, 1)
                assert not await asyncio.to_thread(mutated.wait, 0.05)
                # One coordinator cannot give concurrent callers the same scopes.
                with pytest.raises(ReservationError):
                    owner.recover(**arguments(accepted), request_key="reservation-a")
            finally:
                release.set()
            first = await asyncio.wrap_future(pending)
            if invalidation is not None:
                await asyncio.wrap_future(invalidation)
        assert mutated.is_set()
        with pytest.raises(ReservationError) as caught:
            owner.recover(**arguments(accepted), request_key="reservation-a")
        assert caught.value.code == "reservation_unavailable"
        with closing(sqlite3.connect(metadata.path)) as db:
            assert (
                db.execute("SELECT reservation_id FROM reservations").fetchone()[0]
                == first.reservation_id
            )
        owner.close()


async def test_authority_wait_consumes_common_budget_and_retires_partial_scope(
    tmp_path, monkeypatch
):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        monkeypatch.setattr(implementation(), "_OPERATION_SECONDS", 0.08)
        owner = coordinator(agent, metadata, authority)
        with closing(sqlite3.connect(authority.path, isolation_level=None)) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            started = time.monotonic()
            with pytest.raises(ReservationError) as caught:
                owner.reserve(**arguments(accepted), request=request())
            assert caught.value.code == "reservation_unavailable"
            assert time.monotonic() - started < 0.75
            blocker.rollback()
        assert authority.events[-1] == "retired"
        # The ordinary timeout retired cleanly and did not poison ownership.
        assert (
            owner.reserve(**arguments(accepted), request=request()).status == "reserved"
        )
        owner.close()


async def test_scope_order_and_exact_common_deadline(tmp_path, monkeypatch):
    from src.services.agent_runs.coordinator import CoordinatorBorrow
    from src.services.agent_runs.source_ownership import ConversationFence

    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        owner = coordinator(agent, metadata, authority)
        events, deadlines = [], []

        def track(cls, name, label):
            original = getattr(cls, name)

            def observed(scope, *args, **kwargs):
                events.append(label)
                if name == "acquire":
                    deadlines.append(kwargs["deadline"])
                return original(scope, *args, **kwargs)

            monkeypatch.setattr(cls, name, observed)

        for cls, name, label in (
            (ConversationFence, "acquire", "conversation+"),
            (ReservationTransaction, "acquire", "source+"),
            (SQLiteAuthorityFence, "acquire", "authority+"),
            (ConversationFence, "resolve", "conversation-read"),
            (ReservationTransaction, "lookup", "reservation-read"),
            (ReservationTransaction, "commit", "commit"),
            (SQLiteAuthorityFence, "retire", "authority-"),
            (ReservationTransaction, "retire", "source-"),
            (ConversationFence, "retire", "conversation-"),
            (CoordinatorBorrow, "retire", "borrow-"),
        ):
            track(cls, name, label)
        owner.reserve(**arguments(accepted), request=request())
        assert events == [
            "conversation+",
            "source+",
            "authority+",
            "conversation-read",
            "reservation-read",
            "commit",
            "authority-",
            "source-",
            "conversation-",
            "borrow-",
        ]
        assert len(deadlines) == 3 and len(set(deadlines)) == 1
        owner.close()


async def test_expiry_during_commit_owner_check_prevents_sql_commit(
    tmp_path, monkeypatch
):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        clock = [time.time()]
        authority.mutate(expires=int(clock[0]) + 10)
        owner = coordinator(agent, metadata, authority, clock=lambda: clock[0])
        committing = False
        original_commit = ReservationTransaction.commit
        original_check = ReservationTransaction._require_active

        def checking(scope):
            original_check(scope)
            if committing:
                clock[0] += 11

        def commit(scope, **kwargs):
            nonlocal committing
            committing = True
            try:
                return original_commit(scope, **kwargs)
            finally:
                committing = False

        monkeypatch.setattr(ReservationTransaction, "_require_active", checking)
        monkeypatch.setattr(ReservationTransaction, "commit", commit)
        with pytest.raises(ReservationError) as caught:
            owner.reserve(**arguments(accepted), request=request())
        assert caught.value.code == "reservation_unavailable"
        with closing(sqlite3.connect(metadata.path)) as db:
            assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0
        # A denial before actual COMMIT with clean rollback does not quarantine.
        authority.mutate(expires=int(clock[0]) + 300)
        assert (
            owner.reserve(**arguments(accepted), request=request()).status == "reserved"
        )
        owner.close()


@pytest.mark.parametrize("name", ["clock", "monotonic"])
async def test_failed_clock_after_retirement_has_a_closed_error(
    tmp_path, monkeypatch, name
):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        retired = False
        real_clock = time.time if name == "clock" else time.monotonic

        def clock():
            if retired:
                raise OSError("PRIVATE_CLOCK_CANARY")
            return real_clock()

        original_retire = SQLiteAuthorityFence.retire

        def retiring(scope):
            nonlocal retired
            original_retire(scope)
            retired = True

        monkeypatch.setattr(SQLiteAuthorityFence, "retire", retiring)
        owner = coordinator(agent, metadata, authority, **{name: clock})
        with pytest.raises(ReservationError) as caught:
            owner.reserve(**arguments(accepted), request=request())
        assert caught.value.code == "reservation_unavailable"
        assert "PRIVATE_" not in str(caught.value) + repr(caught.value)
        with closing(sqlite3.connect(metadata.path)) as db:
            assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 1
        owner.close()


async def test_delayed_retirement_checks_response_deadline_and_preserves_known_commit(
    tmp_path, monkeypatch
):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        clock = [100.0]
        owner = coordinator(agent, metadata, authority, monotonic=lambda: clock[0])
        original_retire = SQLiteAuthorityFence.retire

        def delayed_retire(scope):
            original_retire(scope)
            clock[0] = 102.0

        with monkeypatch.context() as delay:
            delay.setattr(SQLiteAuthorityFence, "retire", delayed_retire)
            with pytest.raises(ReservationError) as caught:
                owner.reserve(**arguments(accepted), request=request())
        assert caught.value.code == "reservation_unavailable"
        with closing(sqlite3.connect(metadata.path)) as db:
            row = db.execute(
                "SELECT reservation_id,upload_expires_at FROM reservations"
            ).fetchone()
        recovered = owner.recover(**arguments(accepted), request_key="reservation-a")
        assert (recovered.reservation_id, recovered.upload_expires_at) == row
        owner.close()


async def test_control_flow_interruption_retains_scopes_and_shared_quarantine(
    tmp_path, monkeypatch
):
    class InterruptedCleanup(BaseException):
        pass

    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        owner = coordinator(agent, metadata, authority)
        captured = []

        def interrupted_retire(scope):
            captured.append(owner._operation)
            raise InterruptedCleanup

        try:
            with monkeypatch.context() as fault:
                fault.setattr(SQLiteAuthorityFence, "retire", interrupted_retire)
                with pytest.raises(InterruptedCleanup):
                    owner.reserve(**arguments(accepted), request=request())
            assert captured and owner._operation is captured[0]
            with pytest.raises(RuntimeError):
                agent.borrow_coordinator()
            replacement = coordinator(agent, metadata, authority)
            with pytest.raises(ReservationError):
                replacement.recover(**arguments(accepted), request_key="reservation-a")
            replacement.close()
            owner.close()
            assert owner._operation is None
            with pytest.raises(RuntimeError):
                agent.borrow_coordinator()
        finally:
            # Also retire the captured owner on RED, without leaking its writer
            # just because the product lost that reference before the repair.
            for operation in captured:
                operation.retire()


@pytest.mark.parametrize("outcome", ["conflict", "capacity", "expired"])
@pytest.mark.parametrize("boundary", ["deadline", "authority", "conversation"])
async def test_metadata_error_after_cleanup_rechecks_captured_lifetimes(
    tmp_path, monkeypatch, outcome, boundary
):
    async with waiting_target(tmp_path) as (
        agent,
        metadata,
        authority,
        accepted,
        providers,
    ):
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
        saved = owner.reserve(**arguments(accepted), request=request())
        if outcome == "capacity":
            owner.reserve(**arguments(accepted), request=request("second-key"))
        elif outcome == "expired":
            clock[0] = saved.upload_expires_at + 1
        original_retire = SQLiteAuthorityFence.retire

        def delayed_retire(scope):
            original_retire(scope)
            if boundary == "deadline":
                monotonic[0] = 102.0
            else:
                clock[0] = (
                    authority_expiry if boundary == "authority" else conversation_expiry
                )

        with monkeypatch.context() as delay:
            delay.setattr(SQLiteAuthorityFence, "retire", delayed_retire)
            with pytest.raises(ReservationError) as caught:
                if outcome == "conflict":
                    owner.reserve(
                        **arguments(accepted), request=request(content_length=13)
                    )
                elif outcome == "capacity":
                    owner.reserve(**arguments(accepted), request=request("third-key"))
                else:
                    owner.recover(**arguments(accepted), request_key="reservation-a")
        assert caught.value.code == "reservation_unavailable"
        with closing(sqlite3.connect(metadata.path)) as db:
            assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == (
                2 if outcome == "capacity" else 1
            )
        assert len(providers) == len(providers[0].requests) == 1
        owner.close()
