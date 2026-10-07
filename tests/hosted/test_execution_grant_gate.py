"""BoundRegistryTool.run fails closed for confirming tools (ADR 0003/0008)."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastmcp.exceptions import ToolError

from src.control_plane.auth.context import (
    AuthorizationContext,
    clear_authorization_context,
    set_authorization_context,
)
from src.control_plane.execution_grants import (
    ExecutionGrantBinding,
    ExecutionGrantDenial,
    ExecutionGrantError,
    PreAcceptFailure,
)
from src.hosted_mcp import server as hosted_server
from src.hosted_mcp.server import (
    PROVIDER_RESULT_ERROR,
    ToolAuthorizationError,
    build_server,
)
from src.registry.catalog import public_tools
from src.registry.models import ProviderExport, SideEffectClass
from src.registry.tools.public import RATE_CURRENCY_CODES
from tests.control_plane.execution_grant_fakes import (
    FakeExecutionGrantAuthority,
    FakeReservation,
    GrantState,
    make_binding,
)

HEX = "0123456789abcdef0123456789abcdef"
PREVIEW_ID = f"sa_preview_{HEX}"
OTHER_PREVIEW_ID = f"sa_preview_{'f' * 32}"
APPROVAL_ID = f"sa_approval_request_{HEX}"
OTHER_APPROVAL_ID = f"sa_approval_request_{'e' * 32}"
JOB_ID = f"sa_job_{HEX}"
EXECUTE_ARGS = {"preview_id": PREVIEW_ID, "approval_request_id": APPROVAL_ID}


@pytest.fixture
def context():
    """Authorize every public scope for a single account/connection."""
    ctx = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="claude",
        subject="auth0|owner-1",
        client_id="claude-client",
        scopes=frozenset(s for t in public_tools() for s in t.auth_scopes),
    )
    token = set_authorization_context(ctx)
    yield ctx
    clear_authorization_context(token)


def execute_contract():
    """Return execute_shipments exported on generic MCP for gate tests."""
    base = next(t for t in public_tools() if t.name == "execute_shipments")
    return base.model_copy(
        update={
            "implementation_status": "implemented",
            "hosted_readiness": "ready",
            "provider_export_enabled": True,
            "provider_exports": [ProviderExport.generic_mcp],
        }
    )


class RecordingHandler:
    """Confirmed handler that records the binding it was handed."""

    def __init__(self, fail: Exception | None = None, gate=None) -> None:
        """Optionally raise ``fail`` or wait on ``gate`` before returning."""
        self.calls: list[tuple[dict, object]] = []
        self.fail = fail
        self.gate = gate

    async def __call__(self, _context, arguments, binding):
        """Record the call, then fail, wait or return a fixed result."""
        self.calls.append((arguments, binding))
        if self.gate is not None:
            await self.gate.wait()
        if self.fail is not None:
            raise self.fail
        return {"job_id": JOB_ID, "status": "running"}


async def bound_execute(handler, authority):
    """Build a server with execute_shipments bound and return its tool."""
    server = build_server(
        tools=[execute_contract()],
        confirmed_tool_handlers={"execute_shipments": handler},
        execution_grants=authority,
    )
    return (await server.get_tools())["execute_shipments"]


def approved(context, **overrides):
    """Return an authority with one approved request for ``context``."""
    return FakeExecutionGrantAuthority(
        approved={APPROVAL_ID: make_binding(context, PREVIEW_ID, **overrides)}
    )


async def test_default_build_server_fails_closed_for_execute(context):
    """Mutation guard: no authority wired means no handler call, ever."""
    handler = RecordingHandler()
    server = build_server(
        tools=[execute_contract()],
        confirmed_tool_handlers={"execute_shipments": handler},
    )
    tool = (await server.get_tools())["execute_shipments"]

    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)

    assert exc.value.code == ExecutionGrantDenial.GRANT_UNAVAILABLE
    assert handler.calls == []


async def test_unapproved_request_never_reaches_handler(context):
    handler = RecordingHandler()
    authority = FakeExecutionGrantAuthority()
    tool = await bound_execute(handler, authority)

    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)

    assert exc.value.code == ExecutionGrantDenial.APPROVAL_PENDING
    assert handler.calls == []
    assert authority.calls == [
        {
            "tool_name": "execute_shipments",
            "prepare_tool": "prepare_shipments",
            "approval_request_id": APPROVAL_ID,
            "preview_id": PREVIEW_ID,
        }
    ]


@pytest.mark.parametrize("denial", list(ExecutionGrantDenial))
async def test_every_denial_code_is_surfaced_and_blocks_handler(context, denial):
    handler = RecordingHandler()
    authority = FakeExecutionGrantAuthority(fail_with=ExecutionGrantError(denial))
    tool = await bound_execute(handler, authority)

    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)

    assert exc.value.code == denial.value
    assert handler.calls == []


@pytest.mark.parametrize(
    "denial",
    [
        ExecutionGrantDenial.GRANT_IN_USE,
        ExecutionGrantDenial.GRANT_CONSUMED,
        ExecutionGrantDenial.RECONCILIATION_PENDING,
        ExecutionGrantDenial.GRANT_UNAVAILABLE,
    ],
)
async def test_unsettled_or_used_grant_does_not_recommend_another_approval(
    context, denial
):
    handler = RecordingHandler()
    authority = FakeExecutionGrantAuthority(fail_with=ExecutionGrantError(denial))
    tool = await bound_execute(handler, authority)

    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)

    assert "approve again" not in str(exc.value)
    assert "check" in str(exc.value)
    assert handler.calls == []


async def test_authority_crash_fails_closed_without_leaking_detail(context):
    handler = RecordingHandler()
    authority = FakeExecutionGrantAuthority(
        fail_with=RuntimeError("redis password=hunter2 down")
    )
    tool = await bound_execute(handler, authority)

    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)

    assert exc.value.code == ExecutionGrantDenial.GRANT_UNAVAILABLE
    assert "hunter2" not in str(exc.value)
    assert handler.calls == []


async def test_approved_request_hands_server_owned_binding_to_handler(context):
    handler = RecordingHandler()
    authority = approved(context)
    tool = await bound_execute(handler, authority)

    result = await tool.run(EXECUTE_ARGS)

    assert result.structured_content == {"job_id": JOB_ID, "status": "running"}
    [(arguments, binding)] = handler.calls
    assert arguments == EXECUTE_ARGS
    assert binding is authority.approved[APPROVAL_ID]
    assert authority.events == ["reserve", "consume"]
    assert authority.state[APPROVAL_ID] == GrantState.CONSUMED


async def test_provable_pre_accept_failure_releases_and_allows_one_retry(context):
    authority = approved(context)
    failing = RecordingHandler(fail=PreAcceptFailure("target offline"))
    tool = await bound_execute(failing, authority)

    with pytest.raises(ToolError, match=PROVIDER_RESULT_ERROR):
        await tool.run(EXECUTE_ARGS)

    assert authority.events == ["reserve", "release"]
    assert APPROVAL_ID not in authority.state

    working = RecordingHandler()
    tool = await bound_execute(working, authority)
    await tool.run(EXECUTE_ARGS)

    assert len(working.calls) == 1
    assert authority.state[APPROVAL_ID] == GrantState.CONSUMED


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("timeout after send"), TimeoutError(), ValueError("unknown")],
)
async def test_ambiguous_failure_holds_reservation_and_blocks_replay(context, failure):
    authority = approved(context)
    handler = RecordingHandler(fail=failure)
    tool = await bound_execute(handler, authority)

    with pytest.raises(ToolError, match=PROVIDER_RESULT_ERROR):
        await tool.run(EXECUTE_ARGS)

    assert authority.events == ["reserve", "hold"]
    assert authority.state[APPROVAL_ID] == GrantState.HELD

    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)

    assert exc.value.code == ExecutionGrantDenial.RECONCILIATION_PENDING
    assert len(handler.calls) == 1


async def test_cancellation_holds_reservation_and_propagates(context):
    authority = approved(context)
    handler = RecordingHandler(gate=asyncio.Event())
    tool = await bound_execute(handler, authority)

    task = asyncio.ensure_future(tool.run(EXECUTE_ARGS))
    while not handler.calls:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert authority.events == ["reserve", "hold"]
    assert authority.state[APPROVAL_ID] == GrantState.HELD

    retry = RecordingHandler()
    tool = await bound_execute(retry, authority)
    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)
    assert exc.value.code == ExecutionGrantDenial.RECONCILIATION_PENDING
    assert retry.calls == []


async def test_hold_failure_is_logged_and_original_failure_still_raised(
    context, caplog
):
    authority = approved(context)
    tool = await bound_execute(RecordingHandler(fail=RuntimeError("boom")), authority)
    original = authority.reserve

    async def reserve(**kwargs):
        reservation = await original(**kwargs)

        async def broken_hold():
            raise RuntimeError("store down password=hunter2")

        reservation.hold_for_reconciliation = broken_hold
        return reservation

    authority.reserve = reserve

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ToolError, match=PROVIDER_RESULT_ERROR):
            await tool.run(EXECUTE_ARGS)

    assert "hold failed" in caplog.text
    assert "hunter2" not in caplog.text
    assert "RuntimeError" in caplog.text


class _NoBinding:
    """Reservation stub with no binding at all."""

    def __init__(self) -> None:
        """Track release calls."""
        self.released = 0

    async def release(self) -> None:
        """Record release."""
        self.released += 1


@pytest.mark.parametrize(
    "override",
    [
        {"account_id": "acct-other"},
        {"provider_connection_id": "pc-other"},
        {"preview_id": OTHER_PREVIEW_ID},
        {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        {"expires_at": datetime.now() + timedelta(minutes=5)},  # noqa: DTZ005 naive
        {"expires_at": "2099-01-01T00:00:00Z"},
        {"expires_at": None},
        {"execution_target_id": ""},
        {"execution_target_id": 7},
        {"amount": ""},
        {"amount": "-5.00"},
        {"amount": "0.00"},
        {"amount": "12.3"},
        {"amount": "twelve"},
        {"amount": 12.34},
        {"currency_code": ""},
        {"currency_code": "XXX"},
        {"currency_code": "usd"},
        {"policy": ""},
        {"policy": "garbage"},
        {"policy": "provider_only"},
        {"idempotency_key": ""},
        {"idempotency_key": None},
    ],
)
async def test_mismatched_or_malformed_binding_is_denied_and_released(
    context, override
):
    handler = RecordingHandler()
    authority = approved(context, **override)
    tool = await bound_execute(handler, authority)

    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)

    assert exc.value.code == ExecutionGrantDenial.GRANT_INVALID
    assert handler.calls == []
    assert authority.events == ["reserve", "release"]


@pytest.mark.parametrize("binding", [None, "not-a-binding", object()])
async def test_reservation_without_valid_binding_is_denied_and_cleaned_up(
    context, binding
):
    handler = RecordingHandler()
    stub = _NoBinding()
    stub.binding = binding
    authority = FakeExecutionGrantAuthority()

    async def reserve(**_kwargs):
        return stub

    authority.reserve = reserve
    tool = await bound_execute(handler, authority)

    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)

    assert exc.value.code == ExecutionGrantDenial.GRANT_INVALID
    assert handler.calls == []
    assert stub.released == 1


async def test_reservation_missing_binding_attribute_is_denied(context):
    handler = RecordingHandler()
    stub = _NoBinding()
    authority = FakeExecutionGrantAuthority()

    async def reserve(**_kwargs):
        return stub

    authority.reserve = reserve
    tool = await bound_execute(handler, authority)

    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)

    assert exc.value.code == ExecutionGrantDenial.GRANT_INVALID
    assert stub.released == 1
    assert handler.calls == []


async def test_validation_accepts_only_canonical_currency_codes(context):
    for code in RATE_CURRENCY_CODES:
        handler = RecordingHandler()
        authority = approved(context, currency_code=code)
        tool = await bound_execute(handler, authority)
        await tool.run(EXECUTE_ARGS)
        assert len(handler.calls) == 1


async def test_authority_cannot_be_satisfied_by_model_supplied_flags(context):
    handler = RecordingHandler()
    authority = approved(context)
    tool = await bound_execute(handler, authority)

    for extra in ("confirmed", "approved", "execution_grant", "confirmation_token"):
        with pytest.raises(ToolError, match=PROVIDER_RESULT_ERROR):
            await tool.run({**EXECUTE_ARGS, extra: True})

    assert handler.calls == []
    assert authority.calls == []


async def test_grant_for_another_approval_request_is_not_accepted(context):
    handler = RecordingHandler()
    authority = FakeExecutionGrantAuthority(
        approved={OTHER_APPROVAL_ID: make_binding(context, PREVIEW_ID)}
    )
    tool = await bound_execute(handler, authority)

    with pytest.raises(ToolAuthorizationError):
        await tool.run(EXECUTE_ARGS)

    assert handler.calls == []


async def test_replay_after_consume_is_denied_with_exactly_one_effect(context):
    handler = RecordingHandler()
    authority = approved(context)
    tool = await bound_execute(handler, authority)

    await tool.run(EXECUTE_ARGS)
    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)

    assert exc.value.code == ExecutionGrantDenial.GRANT_CONSUMED
    assert len(handler.calls) == 1
    assert authority.events == ["reserve", "consume"]


async def test_concurrent_calls_produce_exactly_one_effect(context):
    gate = asyncio.Event()
    handler = RecordingHandler(gate=gate)
    authority = approved(context)
    tool = await bound_execute(handler, authority)

    tasks = [asyncio.ensure_future(tool.run(EXECUTE_ARGS)) for _ in range(3)]
    try:
        async with asyncio.timeout(2):
            while sum(task.done() for task in tasks) < 2:
                await asyncio.sleep(0)
        gate.set()
        done, pending = await asyncio.wait(tasks, timeout=2)
        assert not pending, "concurrent grant calls did not settle"
        outcomes = [task.exception() or task.result() for task in done]

        denied = [o for o in outcomes if isinstance(o, ToolAuthorizationError)]
        assert len(denied) == 2
        assert {d.code for d in denied} == {ExecutionGrantDenial.GRANT_IN_USE}
        assert len(handler.calls) == 1
        assert authority.events == ["reserve", "consume"]
    finally:
        gate.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        done, pending = await asyncio.wait(tasks, timeout=2)
        for task in done:
            if not task.cancelled():
                task.exception()
        assert not pending, "concurrent grant test left unfinished tasks"


async def test_consume_failure_after_acceptance_holds_and_still_reports(
    context, caplog
):
    handler = RecordingHandler()
    authority = approved(context)
    original = authority.reserve

    async def reserve(**kwargs):
        reservation = await original(**kwargs)

        async def broken_consume():
            raise RuntimeError("store unavailable")

        reservation.consume = broken_consume
        return reservation

    authority.reserve = reserve
    tool = await bound_execute(handler, authority)

    with caplog.at_level(logging.ERROR):
        result = await tool.run(EXECUTE_ARGS)

    assert result.structured_content == {"job_id": JOB_ID, "status": "running"}
    assert "grant consume failed" in caplog.text
    assert "store unavailable" not in caplog.text
    assert authority.events == ["reserve", "hold"]
    assert authority.state[APPROVAL_ID] == GrantState.HELD

    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)
    assert exc.value.code == ExecutionGrantDenial.RECONCILIATION_PENDING
    assert len(handler.calls) == 1


async def test_grant_audit_logs_carry_codes_not_identifiers(context, caplog):
    authority = approved(context, amount="-5.00")
    tool = await bound_execute(RecordingHandler(), authority)

    with caplog.at_level(logging.INFO):
        with pytest.raises(ToolAuthorizationError):
            await tool.run(EXECUTE_ARGS)

    assert ExecutionGrantDenial.GRANT_INVALID.value in caplog.text
    assert "execute_shipments" in caplog.text
    assert APPROVAL_ID not in caplog.text
    assert "-5.00" not in caplog.text


def test_registration_rejects_confirming_tool_in_plain_handlers():
    async def plain(_context, _arguments):
        return {}

    with pytest.raises(ValueError, match="confirmed_tool_handlers"):
        build_server(
            tools=[execute_contract()],
            tool_handlers={"execute_shipments": plain},
        )


def test_registration_rejects_confirmed_handler_for_non_confirming_tool():
    contract = next(t for t in public_tools() if t.name == "get_shipagent_status")
    contract = contract.model_copy(
        update={
            "implementation_status": "implemented",
            "hosted_readiness": "ready",
            "provider_export_enabled": True,
            "provider_exports": [ProviderExport.generic_mcp],
        }
    )

    with pytest.raises(ValueError, match="does not require confirmation"):
        build_server(
            tools=[contract],
            confirmed_tool_handlers={"get_shipagent_status": RecordingHandler()},
        )


def test_registration_rejects_mutating_tool_that_skipped_confirmation():
    unsafe = execute_contract().model_copy(
        update={"requires_confirmation": False, "prepare_tool": None}
    )
    assert unsafe.side_effect == SideEffectClass.purchase

    async def plain(_context, _arguments):
        return {}

    with pytest.raises(ValueError, match="requires confirmation"):
        build_server(tools=[unsafe], tool_handlers={"execute_shipments": plain})


async def test_non_confirming_tools_do_not_touch_grant_authority(context):
    authority = FakeExecutionGrantAuthority()

    async def handler(_context, _arguments):
        return {
            "status": "ready",
            "executionTarget": {"state": "ready", "capabilities": []},
        }

    contract = next(t for t in public_tools() if t.name == "get_shipagent_status")
    server = build_server(
        tools=[contract],
        tool_handlers={"get_shipagent_status": handler},
        execution_grants=authority,
    )
    tool = (await server.get_tools())["get_shipagent_status"]

    await tool.run({"correlation_id": f"sa_correlation_{HEX}"})

    assert authority.calls == []


class _FlippingReservation:
    """Reservation whose binding changes after the first read (hostile authority)."""

    def __init__(self, real: FakeReservation, later: ExecutionGrantBinding) -> None:
        """Wrap ``real``; ``later`` is served for every read after the first."""
        self.real = real
        self.later = later
        self.reads = 0

    @property
    def binding(self) -> ExecutionGrantBinding:
        """Return the valid binding once, then the swapped one."""
        self.reads += 1
        return self.real.binding if self.reads == 1 else self.later

    async def consume(self) -> None:
        """Delegate to the real reservation."""
        await self.real.consume()

    async def release(self) -> None:
        """Delegate to the real reservation."""
        await self.real.release()

    async def hold_for_reconciliation(self) -> None:
        """Delegate to the real reservation."""
        await self.real.hold_for_reconciliation()


async def test_handler_receives_the_one_validated_binding_not_a_reread(context):
    authority = approved(context)
    handler = RecordingHandler()
    tool = await bound_execute(handler, authority)
    original = authority.reserve
    swapped = make_binding(context, PREVIEW_ID, amount="9999.00")

    async def reserve(**kwargs):
        return _FlippingReservation(await original(**kwargs), swapped)

    authority.reserve = reserve

    await tool.run(EXECUTE_ARGS)

    (_, delivered) = handler.calls[0]
    assert delivered.amount == "12.34"
    assert authority.events == ["reserve", "consume"]


class _LaxBinding(ExecutionGrantBinding):
    """Subclass whose validate approves anything (bypass attempt)."""

    def validate(self, *, policy):
        """Skip every check."""


@pytest.mark.parametrize("amount", ["-1.00", "12.34"])
async def test_binding_subclass_is_rejected_even_if_fields_are_valid(context, amount):
    base = make_binding(context, PREVIEW_ID, amount=amount)
    lax = _LaxBinding(**{f: getattr(base, f) for f in base.__dataclass_fields__})
    authority = FakeExecutionGrantAuthority(approved={APPROVAL_ID: lax})
    handler = RecordingHandler()
    tool = await bound_execute(handler, authority)

    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)

    assert exc.value.code == ExecutionGrantDenial.GRANT_INVALID
    assert handler.calls == []
    assert authority.events == ["reserve", "release"]


def gate_reservation_step(authority, step):
    """Make a reservation ``step`` wait on an event; return (started, proceed)."""
    started, proceed = asyncio.Event(), asyncio.Event()
    original = authority.reserve

    async def reserve(**kwargs):
        reservation = await original(**kwargs)
        real = getattr(reservation, step)

        async def gated():
            started.set()
            await proceed.wait()
            await real()

        setattr(reservation, step, gated)
        return reservation

    authority.reserve = reserve
    return started, proceed


async def _cancel_during_step(tool, started, proceed):
    """Cancel the run while a settlement step is waiting, then let it finish."""
    task = asyncio.ensure_future(tool.run(EXECUTE_ARGS))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_cancellation_during_consume_does_not_undo_acceptance(context):
    authority = approved(context)
    started, proceed = gate_reservation_step(authority, "consume")
    tool = await bound_execute(RecordingHandler(), authority)

    await _cancel_during_step(tool, started, proceed)

    assert authority.events == ["reserve", "consume"]
    assert authority.state[APPROVAL_ID] == GrantState.CONSUMED


async def test_consume_deadline_preserves_accepted_result_and_denies_replay(
    context, monkeypatch
):
    """Fake-backed gate liveness; this does not prove persistent store safety."""
    monkeypatch.setattr(
        hosted_server, "GRANT_SETTLEMENT_TIMEOUT_SECONDS", 0.05, raising=False
    )
    authority = approved(context)
    started, proceed = gate_reservation_step(authority, "consume")
    handler = RecordingHandler()
    tool = await bound_execute(handler, authority)
    task = asyncio.create_task(tool.run(EXECUTE_ARGS))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        done, _ = await asyncio.wait([task], timeout=1)
        assert task in done, "accepted call exceeded its settlement deadline"
        assert task.result().structured_content == {
            "job_id": JOB_ID,
            "status": "running",
        }
        assert authority.state[APPROVAL_ID] == GrantState.RESERVED
        with pytest.raises(ToolAuthorizationError) as exc:
            await tool.run(EXECUTE_ARGS)
        assert exc.value.code == ExecutionGrantDenial.GRANT_IN_USE
        assert len(handler.calls) == 1
        assert "release" not in authority.events
    finally:
        proceed.set()
        done, pending = await asyncio.wait([task], timeout=2)
        for finished in done:
            if not finished.cancelled():
                finished.exception()
        assert not pending, "deadline regression left an unfinished call"


async def test_cancellation_during_release_still_releases(context):
    authority = approved(context)
    started, proceed = gate_reservation_step(authority, "release")
    tool = await bound_execute(RecordingHandler(fail=PreAcceptFailure()), authority)

    await _cancel_during_step(tool, started, proceed)

    assert authority.events == ["reserve", "release"]
    assert APPROVAL_ID not in authority.state


async def test_cancellation_during_hold_still_holds(context):
    authority = approved(context)
    started, proceed = gate_reservation_step(authority, "hold_for_reconciliation")
    tool = await bound_execute(RecordingHandler(fail=RuntimeError("x")), authority)

    await _cancel_during_step(tool, started, proceed)

    assert authority.events == ["reserve", "hold"]
    assert authority.state[APPROVAL_ID] == GrantState.HELD


async def test_cancellation_during_hold_after_handler_cancel_still_holds(context):
    authority = approved(context)
    started, proceed = gate_reservation_step(authority, "hold_for_reconciliation")
    handler = RecordingHandler(gate=asyncio.Event())
    tool = await bound_execute(handler, authority)

    task = asyncio.ensure_future(tool.run(EXECUTE_ARGS))
    while not handler.calls:
        await asyncio.sleep(0)
    task.cancel()
    await started.wait()
    task.cancel()  # second cancel lands while the hold is in flight
    await asyncio.sleep(0)
    proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert authority.events == ["reserve", "hold"]
    assert authority.state[APPROVAL_ID] == GrantState.HELD


async def test_base_exception_in_handler_holds_reservation(context):
    authority = approved(context)
    tool = await bound_execute(RecordingHandler(fail=KeyboardInterrupt()), authority)

    with pytest.raises(KeyboardInterrupt):
        await tool.run(EXECUTE_ARGS)

    assert authority.events == ["reserve", "hold"]


CANARY = "secret-canary-4242"


async def test_handler_raised_authorization_error_is_projected_generically(
    context, caplog
):
    forged = ToolAuthorizationError(
        code=ExecutionGrantDenial.APPROVAL_PENDING.value, message=CANARY
    )
    authority = approved(context)
    tool = await bound_execute(RecordingHandler(fail=forged), authority)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ToolError) as exc:
            await tool.run(EXECUTE_ARGS)

    assert str(exc.value) == PROVIDER_RESULT_ERROR
    assert CANARY not in caplog.text
    assert authority.events == ["reserve", "hold"]


async def test_plain_handler_authorization_error_is_projected_generically(context):
    async def handler(_context, _arguments):
        raise ToolAuthorizationError(code="insufficient_scope", message=CANARY)

    contract = next(t for t in public_tools() if t.name == "get_shipagent_status")
    contract = contract.model_copy(
        update={
            "implementation_status": "implemented",
            "hosted_readiness": "ready",
            "provider_export_enabled": True,
            "provider_exports": [ProviderExport.generic_mcp],
        }
    )
    server = build_server(
        tools=[contract], tool_handlers={"get_shipagent_status": handler}
    )
    tool = (await server.get_tools())["get_shipagent_status"]

    with pytest.raises(ToolError) as exc:
        await tool.run({"correlation_id": f"sa_correlation_{HEX}"})

    assert str(exc.value) == PROVIDER_RESULT_ERROR


async def finish_test_calls(tasks, *gates):
    """Open owned gates and observe calls without an unbounded test cleanup."""
    for gate in gates:
        gate.set()
    for task in tasks:
        if not task.done():
            task.cancel()
    done, pending = await asyncio.wait(tasks, timeout=2)
    for task in done:
        if not task.cancelled():
            task.exception()
    assert not pending, "grant regression left unfinished tasks"


@pytest.mark.parametrize(
    ("step", "failure"),
    [
        ("consume", None),
        ("release", PreAcceptFailure()),
        ("hold_for_reconciliation", RuntimeError("ambiguous")),
    ],
)
async def test_repeated_cancellation_cannot_extend_settlement_deadline(
    context, monkeypatch, step, failure
):
    monkeypatch.setattr(hosted_server, "GRANT_SETTLEMENT_TIMEOUT_SECONDS", 0.05)
    authority = approved(context)
    started, proceed = gate_reservation_step(authority, step)
    tool = await bound_execute(RecordingHandler(fail=failure), authority)
    task = asyncio.create_task(tool.run(EXECUTE_ARGS))

    async def cancel_repeatedly():
        while not task.done():
            task.cancel()
            await asyncio.sleep(0.01)

    canceller = None
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        canceller = asyncio.create_task(cancel_repeatedly())
        done, _ = await asyncio.wait([task], timeout=0.5)
        assert task in done, "repeated cancellation extended the settlement budget"
        with pytest.raises(asyncio.CancelledError):
            task.result()
        assert authority.state[APPROVAL_ID] == GrantState.RESERVED
        assert authority.events == ["reserve"]
    finally:
        await finish_test_calls([task, *([canceller] if canceller else [])], proceed)


async def test_consume_self_cancellation_preserves_acceptance_and_holds(context):
    authority = approved(context)
    original = authority.reserve

    async def reserve(**kwargs):
        reservation = await original(**kwargs)

        async def self_cancel():
            raise asyncio.CancelledError

        reservation.consume = self_cancel
        return reservation

    authority.reserve = reserve
    handler = RecordingHandler()
    tool = await bound_execute(handler, authority)
    result = await tool.run(EXECUTE_ARGS)

    assert result.structured_content == {"job_id": JOB_ID, "status": "running"}
    assert authority.events == ["reserve", "hold"]
    assert authority.state[APPROVAL_ID] == GrantState.HELD
    assert len(handler.calls) == 1


@pytest.mark.parametrize("self_cancel", [False, True])
async def test_caller_cancel_racing_consume_completion_still_propagates(
    context, self_cancel
):
    authority = approved(context)
    original = authority.reserve
    caller = None

    async def reserve(**kwargs):
        reservation = await original(**kwargs)
        consume = reservation.consume

        async def complete_and_cancel():
            caller.cancel()
            if self_cancel:
                raise asyncio.CancelledError
            await consume()

        reservation.consume = complete_and_cancel
        return reservation

    authority.reserve = reserve
    tool = await bound_execute(RecordingHandler(), authority)
    caller = asyncio.create_task(tool.run(EXECUTE_ARGS))
    try:
        done, _ = await asyncio.wait([caller], timeout=1)
        assert caller in done
        with pytest.raises(asyncio.CancelledError):
            caller.result()
        expected = GrantState.HELD if self_cancel else GrantState.CONSUMED
        assert authority.state[APPROVAL_ID] == expected
        assert "release" not in authority.events
    finally:
        await finish_test_calls([caller])


@pytest.mark.parametrize("late_failure", [False, True])
async def test_late_consume_outcome_is_observed_without_new_hold_or_release(
    context, monkeypatch, caplog, late_failure
):
    monkeypatch.setattr(hosted_server, "GRANT_SETTLEMENT_TIMEOUT_SECONDS", 0.03)
    authority = approved(context)
    original = authority.reserve
    started, proceed, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    operation = None

    async def reserve(**kwargs):
        reservation = await original(**kwargs)
        consume = reservation.consume

        async def delayed():
            nonlocal operation
            operation = asyncio.current_task()
            started.set()
            try:
                await proceed.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await proceed.wait()
            if late_failure:
                raise RuntimeError(CANARY)
            await consume()

        reservation.consume = delayed
        return reservation

    authority.reserve = reserve
    handler = RecordingHandler()
    tool = await bound_execute(handler, authority)
    call = asyncio.create_task(tool.run(EXECUTE_ARGS))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        done, _ = await asyncio.wait([call], timeout=1)
        assert call in done
        assert call.result().structured_content["job_id"] == JOB_ID
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        with pytest.raises(ToolAuthorizationError) as exc:
            await tool.run(EXECUTE_ARGS)
        assert exc.value.code == ExecutionGrantDenial.GRANT_IN_USE
        with caplog.at_level(logging.ERROR):
            proceed.set()
            done, _ = await asyncio.wait([operation], timeout=1)
            assert operation in done
            await asyncio.sleep(0)  # allow the registered outcome observer to run
        assert len(handler.calls) == 1
        assert "release" not in authority.events
        assert "hold" not in authority.events
        assert CANARY not in caplog.text
        if late_failure:
            assert "consume failed" in caplog.text
            assert authority.state[APPROVAL_ID] == GrantState.RESERVED
        else:
            assert authority.state[APPROVAL_ID] == GrantState.CONSUMED
    finally:
        await finish_test_calls([call, *([operation] if operation else [])], proceed)


@pytest.mark.parametrize(
    ("step", "failure"),
    [
        ("release", PreAcceptFailure()),
        ("hold_for_reconciliation", RuntimeError("ambiguous")),
    ],
)
async def test_failed_release_or_hold_keeps_replay_denied(context, step, failure):
    authority = approved(context)
    original = authority.reserve

    async def reserve(**kwargs):
        reservation = await original(**kwargs)

        async def fail():
            raise RuntimeError(CANARY)

        setattr(reservation, step, fail)
        return reservation

    authority.reserve = reserve
    handler = RecordingHandler(fail=failure)
    tool = await bound_execute(handler, authority)
    with pytest.raises(ToolError, match=PROVIDER_RESULT_ERROR):
        await tool.run(EXECUTE_ARGS)
    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)
    assert exc.value.code == ExecutionGrantDenial.GRANT_IN_USE
    assert authority.state[APPROVAL_ID] == GrantState.RESERVED
    assert len(handler.calls) == 1


async def test_failed_consume_and_hold_still_reports_original_acceptance(context):
    authority = approved(context)
    original = authority.reserve

    async def reserve(**kwargs):
        reservation = await original(**kwargs)

        async def fail():
            raise RuntimeError(CANARY)

        reservation.consume = fail
        reservation.hold_for_reconciliation = fail
        return reservation

    authority.reserve = reserve
    handler = RecordingHandler()
    tool = await bound_execute(handler, authority)
    result = await tool.run(EXECUTE_ARGS)
    assert result.structured_content == {"job_id": JOB_ID, "status": "running"}
    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)
    assert exc.value.code == ExecutionGrantDenial.GRANT_IN_USE
    assert authority.state[APPROVAL_ID] == GrantState.RESERVED
    assert len(handler.calls) == 1


@pytest.mark.parametrize("remaining_budget", [0.01, -0.01])
async def test_consume_failure_cannot_restart_the_hold_deadline(
    context, monkeypatch, remaining_budget
):
    """Advance the gate's clock at consume failure, without wall-clock sleeps."""
    from types import SimpleNamespace

    loop = asyncio.get_running_loop()
    elapsed = 0.0
    clock = SimpleNamespace(time=lambda: loop.time() + elapsed)
    gate_asyncio = SimpleNamespace(**vars(asyncio))
    gate_asyncio.get_running_loop = lambda: clock
    monkeypatch.setattr(hosted_server, "asyncio", gate_asyncio)
    authority = approved(context)
    original = authority.reserve
    hold_started, proceed = asyncio.Event(), asyncio.Event()

    async def reserve(**kwargs):
        reservation = await original(**kwargs)

        async def fail_consume():
            nonlocal elapsed
            elapsed = hosted_server.GRANT_SETTLEMENT_TIMEOUT_SECONDS - remaining_budget
            raise RuntimeError(CANARY)

        async def delayed_hold():
            hold_started.set()
            await proceed.wait()

        reservation.consume = fail_consume
        reservation.hold_for_reconciliation = delayed_hold
        return reservation

    authority.reserve = reserve
    tool = await bound_execute(RecordingHandler(), authority)
    task = asyncio.create_task(tool.run(EXECUTE_ARGS))
    try:
        done, _ = await asyncio.wait([task], timeout=0.5)
        assert task in done, "consume failure restarted the settlement budget"
        assert task.result().structured_content["job_id"] == JOB_ID
        assert hold_started.is_set() is (remaining_budget > 0)
        assert authority.events == ["reserve"]
    finally:
        await finish_test_calls([task], proceed)


@pytest.mark.parametrize("commit_before_cancel", [False, True])
async def test_reserve_cancellation_never_dispatches_or_implies_rollback(
    context, commit_before_cancel
):
    authority = approved(context)
    original = authority.reserve
    paused, proceed = asyncio.Event(), asyncio.Event()

    async def interrupted_reserve(**kwargs):
        if commit_before_cancel:
            await original(**kwargs)
        paused.set()
        await proceed.wait()
        return await original(**kwargs)

    authority.reserve = interrupted_reserve
    handler = RecordingHandler()
    tool = await bound_execute(handler, authority)
    task = asyncio.create_task(tool.run(EXECUTE_ARGS))
    try:
        await asyncio.wait_for(paused.wait(), timeout=1)
        task.cancel()
        done, _ = await asyncio.wait([task], timeout=1)
        assert task in done
        with pytest.raises(asyncio.CancelledError):
            task.result()
        assert handler.calls == []
        authority.reserve = original
        if commit_before_cancel:
            with pytest.raises(ToolAuthorizationError) as exc:
                await tool.run(EXECUTE_ARGS)
            assert exc.value.code == ExecutionGrantDenial.GRANT_IN_USE
            assert authority.state[APPROVAL_ID] == GrantState.RESERVED
            assert handler.calls == []
        else:
            assert authority.state == {}
    finally:
        await finish_test_calls([task], proceed)


async def test_expiry_rejection_at_consume_never_releases_accepted_work(context):
    """Authority expiry is injected, not proof a real store rechecks it."""
    authority = approved(context)
    original = authority.reserve
    target_accepted = False
    now = authority.approved[APPROVAL_ID].expires_at - timedelta(seconds=1)

    async def reserve(**kwargs):
        reservation = await original(**kwargs)

        consume = reservation.consume

        async def expired_consume():
            assert target_accepted
            if now >= reservation.binding.expires_at:
                raise ExecutionGrantError(ExecutionGrantDenial.APPROVAL_EXPIRED)
            await consume()

        reservation.consume = expired_consume
        return reservation

    async def handler(_context, _arguments, binding):
        nonlocal target_accepted, now
        assert binding is authority.approved[APPROVAL_ID]
        now = binding.expires_at + timedelta(seconds=1)
        target_accepted = True
        return {"job_id": JOB_ID, "status": "running"}

    authority.reserve = reserve
    tool = await bound_execute(handler, authority)
    result = await tool.run(EXECUTE_ARGS)
    assert result.structured_content["job_id"] == JOB_ID
    assert authority.events == ["reserve", "hold"]
    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)
    assert exc.value.code == ExecutionGrantDenial.RECONCILIATION_PENDING

    # Simulated external reconciliation tests only the gate's terminal denial.
    # It does not implement or prove Plan 2 original-job recovery.
    authority.state[APPROVAL_ID] = GrantState.CONSUMED
    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)
    assert exc.value.code == ExecutionGrantDenial.GRANT_CONSUMED


async def test_reserve_suppressing_cancellation_cannot_dispatch(context):
    authority = approved(context)
    original = authority.reserve
    paused, proceed = asyncio.Event(), asyncio.Event()

    async def suppressing_reserve(**kwargs):
        reservation = await original(**kwargs)
        paused.set()
        try:
            await proceed.wait()
        except asyncio.CancelledError:
            return reservation
        return reservation

    authority.reserve = suppressing_reserve
    handler = RecordingHandler()
    tool = await bound_execute(handler, authority)
    task = asyncio.create_task(tool.run(EXECUTE_ARGS))
    try:
        await asyncio.wait_for(paused.wait(), timeout=1)
        task.cancel()
        done, _ = await asyncio.wait([task], timeout=1)
        assert task in done
        assert handler.calls == [], "cancelled reserve dispatched a purchase"
        with pytest.raises(asyncio.CancelledError):
            task.result()
        assert authority.events == ["reserve", "release"]
    finally:
        await finish_test_calls([task], proceed)
