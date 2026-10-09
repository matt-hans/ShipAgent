"""Private actions reuse the same owned exclusion and retirement boundary."""

import importlib
import importlib.util

import pytest

from src.services.agent_runs.coordinator import CoordinatorBorrow
from src.services.agent_runs.source_ownership import ConversationFence
from src.services.source_ingress.reservation_contracts import ReservationError
from src.services.source_ingress.reservation_store import ReservationTransaction
from tests.services.source_ingress.reservation_fixtures import SQLiteAuthorityFence
from tests.services.source_ingress.test_reservations import (
    arguments,
    coordinator,
    request,
    waiting_target,
)


def implementation():
    name = "src.services.source_ingress.source_fences"
    assert importlib.util.find_spec(name) is not None, (
        "shared source fence executor is absent"
    )
    return importlib.import_module(name)


def executor(agent, metadata, authority, **kwargs):
    return implementation().SourceFenceExecutor(
        agent,
        metadata,
        authority,
        expected_target_fingerprint="fingerprint-a",
        **kwargs,
    )


def read_candidate(held):
    record = held.source.lookup(held.namespace)
    assert record is not None
    candidate = record.to_receipt()
    held.set_result(candidate)
    held.set_response_expiry(candidate.upload_expires_at)
    return candidate


async def test_private_action_has_real_ordered_fences_and_cannot_escape_live_scope(
    tmp_path, monkeypatch
):
    implementation()
    async with waiting_target(tmp_path) as (
        agent,
        metadata,
        authority,
        accepted,
        providers,
    ):
        original = coordinator(agent, metadata, authority)
        expected = original.reserve(**arguments(accepted), request=request())
        original.close()
        owner = executor(agent, metadata, authority)
        events, captured = [], []
        for cls, method, label in (
            (ConversationFence, "acquire", "conversation+"),
            (ReservationTransaction, "acquire", "source+"),
            (SQLiteAuthorityFence, "acquire", "authority+"),
            (ConversationFence, "resolve", "conversation-read"),
            (SQLiteAuthorityFence, "retire", "authority-"),
            (ReservationTransaction, "retire", "source-"),
            (ConversationFence, "retire", "conversation-"),
            (CoordinatorBorrow, "retire", "borrow-"),
        ):
            original_method = getattr(cls, method)

            def tracked(scope, *args, _method=original_method, _label=label, **kwargs):
                events.append(_label)
                return _method(scope, *args, **kwargs)

            monkeypatch.setattr(cls, method, tracked)

        def action(held):
            events.append("action")
            captured.append(held)
            assert held.source._db.in_transaction
            assert held.resolved.provider_connection_id == "connection-a"
            assert (
                held.owned.conversation_reference == accepted["conversation_reference"]
            )
            held.require_current()
            return read_candidate(held)

        try:
            assert (
                owner._run_action(
                    **arguments(accepted),
                    request_key=request().request_key,
                    action=action,
                )
                == expected
            )
            assert events == [
                "conversation+",
                "source+",
                "authority+",
                "conversation-read",
                "action",
                "authority-",
                "source-",
                "conversation-",
                "borrow-",
            ]
            assert len(providers) == 1
            for use in (
                lambda: captured[0].source,
                captured[0].commit,
                captured[0].require_current,
            ):
                with pytest.raises(ReservationError):
                    use()
        finally:
            owner.close()


@pytest.mark.parametrize(
    "escape", ["held", "source", "commit", "different_result", "no_candidate"]
)
async def test_private_action_rejects_live_or_uncaptured_result(tmp_path, escape):
    implementation()
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        original = coordinator(agent, metadata, authority)
        original.reserve(**arguments(accepted), request=request())
        original.close()
        owner = executor(agent, metadata, authority)

        def action(held):
            if escape == "no_candidate":
                return held.source.lookup(held.namespace).to_receipt()
            candidate = read_candidate(held)
            if escape == "different_result":
                from dataclasses import replace

                return replace(candidate)
            return {"held": held, "source": held.source, "commit": held.commit}[escape]

        try:
            with pytest.raises(ReservationError) as error:
                owner._run_action(
                    **arguments(accepted),
                    request_key=request().request_key,
                    action=action,
                )
            assert error.value.code == "reservation_unavailable"
            assert owner._operation is None
            assert (
                owner._run_action(
                    **arguments(accepted),
                    request_key=request().request_key,
                    action=read_candidate,
                ).status
                == "reserved"
            )
        finally:
            owner.close()


async def test_private_source_lifetime_action_does_not_extend_reservation_recovery(
    tmp_path,
):
    import time

    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        clock = [time.time()]
        authority.mutate(expires=int(clock[0]) + 3600)
        reservations = coordinator(agent, metadata, authority, clock=lambda: clock[0])
        receipt = reservations.reserve(**arguments(accepted), request=request())
        clock[0] = receipt.upload_expires_at + 1
        with pytest.raises(ReservationError) as error:
            reservations.recover(
                **arguments(accepted), request_key=request().request_key
            )
        assert error.value.code == "reservation_expired"
        owner = executor(agent, metadata, authority, clock=lambda: clock[0])

        def source_lifetime_action(held):
            record = held.source.lookup(held.namespace)
            candidate = record.to_receipt()
            held.set_result(candidate)
            # This is only a synthetic executor lifetime probe. It creates no
            # completed snapshot or usable Source Reference.
            held.set_response_expiry(candidate.prospective_source_expires_at)
            return candidate

        try:
            recovered = owner._run_action(
                **arguments(accepted),
                request_key=request().request_key,
                action=source_lifetime_action,
            )
            assert recovered == receipt
            assert (
                recovered.prospective_source_expires_at
                == receipt.prospective_source_expires_at
            )
            with pytest.raises(ReservationError):
                reservations.recover(
                    **arguments(accepted), request_key=request().request_key
                )
        finally:
            owner.close()
            reservations.close()


async def test_commit_hook_must_return_none_and_cannot_replace_candidate(tmp_path):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        owner = executor(agent, metadata, authority)
        candidate = []

        def action(held):
            now = int(held.require_current())
            record = held.source.insert(
                held.namespace,
                request(),
                admitted_revision=held.owned.revision,
                admitted_at=now,
                upload_expires_at=now + 30,
                prospective_source_expires_at=now + 60,
            )
            receipt = record.to_receipt()
            candidate.append(receipt)
            held.set_result(receipt)
            held.set_response_expiry(receipt.upload_expires_at)

            def invalid_hook():
                assert owner._operation.receipt is receipt
                assert not owner._operation.commit_known
                return held.source

            held.commit(before_commit=invalid_hook)
            return receipt

        try:
            with pytest.raises(ReservationError) as error:
                owner._run_action(
                    **arguments(accepted),
                    request_key=request().request_key,
                    action=action,
                )
            assert error.value.code == "reservation_unavailable"
            assert not owner._failed and owner._operation is None
            # A pre-SQL hook rejection must roll back the candidate entirely.
            reserves = coordinator(agent, metadata, authority)
            try:
                fresh = reserves.reserve(**arguments(accepted), request=request())
                assert fresh.reservation_id != candidate[0].reservation_id
            finally:
                reserves.close()
        finally:
            owner.close()


@pytest.mark.parametrize("limit,expected", [(101, 101), (999, 102)])
async def test_action_deadline_can_shorten_but_never_extend_all_scopes(
    tmp_path, monkeypatch, limit, expected
):
    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        reservations = coordinator(agent, metadata, authority)
        reservations.reserve(**arguments(accepted), request=request())
        reservations.close()
        owner = executor(agent, metadata, authority, monotonic=lambda: 100)
        deadlines = []
        for cls in (ConversationFence, ReservationTransaction, SQLiteAuthorityFence):
            original = cls.acquire

            def acquire(scope, *, deadline, _original=original):
                deadlines.append(deadline)
                return _original(scope, deadline=deadline)

            monkeypatch.setattr(cls, "acquire", acquire)
        try:
            owner._run_action(
                **arguments(accepted),
                request_key=request().request_key,
                action=read_candidate,
                deadline=limit,
            )
            assert deadlines == [expected] * 3
        finally:
            owner.close()


@pytest.mark.parametrize("field", ["authority", "conversation", "source"])
async def test_materialized_result_is_rechecked_after_scope_retirement(
    tmp_path, monkeypatch, field
):
    import time

    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        clock = [time.time()]
        reservations = coordinator(agent, metadata, authority, clock=lambda: clock[0])
        receipt = reservations.reserve(**arguments(accepted), request=request())
        reservations.close()
        authority.mutate(expires=receipt.prospective_source_expires_at + 100)
        owner = executor(agent, metadata, authority, clock=lambda: clock[0])
        cls = {
            "authority": SQLiteAuthorityFence,
            "conversation": ConversationFence,
            "source": ReservationTransaction,
        }[field]
        original = cls.retire

        def retire(scope):
            original(scope)
            clock[0] = receipt.upload_expires_at

        try:
            with monkeypatch.context() as patch:
                patch.setattr(cls, "retire", retire)
                with pytest.raises(ReservationError) as error:
                    owner._run_action(
                        **arguments(accepted),
                        request_key=request().request_key,
                        action=read_candidate,
                    )
            assert error.value.code == "reservation_expired"
            assert owner._operation is None and not owner._failed
        finally:
            owner.close()


async def test_copied_held_action_cannot_use_original_owner(tmp_path):
    from copy import copy

    async with waiting_target(tmp_path) as (agent, metadata, authority, accepted, _):
        reservations = coordinator(agent, metadata, authority)
        reservations.reserve(**arguments(accepted), request=request())
        reservations.close()
        owner = executor(agent, metadata, authority)

        def action(held):
            copied = copy(held)
            for use in (lambda: copied.source, copied.require_current, copied.commit):
                with pytest.raises(ReservationError):
                    use()
            return read_candidate(held)

        try:
            assert (
                owner._run_action(
                    **arguments(accepted),
                    request_key=request().request_key,
                    action=action,
                ).status
                == "reserved"
            )
        finally:
            owner.close()
