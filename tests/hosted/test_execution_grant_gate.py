"""BoundRegistryTool.run fails closed for confirming tools (ADR 0003/0008)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastmcp.exceptions import ToolError

from src.control_plane.auth.context import (
    AuthorizationContext,
    clear_authorization_context,
    set_authorization_context,
)
from src.control_plane.execution_grants import (
    ExecutionGrantDenial,
    ExecutionGrantError,
)
from src.hosted_mcp.server import (
    PROVIDER_RESULT_ERROR,
    ToolAuthorizationError,
    build_server,
)
from src.registry.catalog import public_tools
from src.registry.models import ProviderExport
from tests.control_plane.execution_grant_fakes import (
    FakeExecutionGrantAuthority,
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
    """Handler that records invocations and returns a fixed result."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    async def __call__(self, _context, arguments):
        self.calls.append(arguments)
        if self.fail:
            raise RuntimeError("target rejected before accepting")
        return {"job_id": JOB_ID, "status": "running"}


async def bound_execute(handler, authority):
    """Build a server with execute_shipments bound and return its tool."""
    server = build_server(
        tools=[execute_contract()],
        tool_handlers={"execute_shipments": handler},
        execution_grants=authority,
    )
    return (await server.get_tools())["execute_shipments"]


async def test_confirming_tool_without_grant_authority_fails_closed(context):
    handler = RecordingHandler()
    tool = await bound_execute(handler, None)

    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)

    assert exc.value.code == "execution_grant_unavailable"
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


async def test_authority_crash_fails_closed_without_leaking_detail(context):
    handler = RecordingHandler()
    authority = FakeExecutionGrantAuthority(
        fail_with=RuntimeError("redis password=hunter2 down")
    )
    tool = await bound_execute(handler, authority)

    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)

    assert exc.value.code == "execution_grant_unavailable"
    assert "hunter2" not in str(exc.value)
    assert handler.calls == []


async def test_approved_request_runs_handler_and_consumes_once(context):
    handler = RecordingHandler()
    authority = FakeExecutionGrantAuthority(
        approved={APPROVAL_ID: make_binding(context, PREVIEW_ID)}
    )
    tool = await bound_execute(handler, authority)

    result = await tool.run(EXECUTE_ARGS)

    assert result.structured_content == {"job_id": JOB_ID, "status": "running"}
    assert handler.calls == [EXECUTE_ARGS]
    assert authority.events == ["reserve", "consume"]


async def test_handler_failure_releases_reservation_without_consuming(context):
    handler = RecordingHandler(fail=True)
    authority = FakeExecutionGrantAuthority(
        approved={APPROVAL_ID: make_binding(context, PREVIEW_ID)}
    )
    tool = await bound_execute(handler, authority)

    with pytest.raises(ToolError, match=PROVIDER_RESULT_ERROR):
        await tool.run(EXECUTE_ARGS)

    assert authority.events == ["reserve", "release"]


@pytest.mark.parametrize(
    "override",
    [
        {"account_id": "acct-other"},
        {"provider_connection_id": "pc-other"},
        {"preview_id": OTHER_PREVIEW_ID},
        {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        {"execution_target_id": ""},
        {"amount": ""},
        {"currency_code": ""},
        {"idempotency_key": ""},
    ],
)
async def test_mismatched_or_incomplete_binding_fails_closed_and_releases(
    context, override
):
    handler = RecordingHandler()
    authority = FakeExecutionGrantAuthority(
        approved={APPROVAL_ID: make_binding(context, PREVIEW_ID, **override)}
    )
    tool = await bound_execute(handler, authority)

    with pytest.raises(ToolAuthorizationError) as exc:
        await tool.run(EXECUTE_ARGS)

    assert exc.value.code == "execution_grant_invalid"
    assert handler.calls == []
    assert authority.events == ["reserve", "release"]


async def test_authority_cannot_be_satisfied_by_model_supplied_flags(context):
    handler = RecordingHandler()
    authority = FakeExecutionGrantAuthority(
        approved={APPROVAL_ID: make_binding(context, PREVIEW_ID)}
    )
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


async def test_consume_failure_after_acceptance_is_logged_not_hidden(context, caplog):
    handler = RecordingHandler()
    authority = FakeExecutionGrantAuthority(
        approved={APPROVAL_ID: make_binding(context, PREVIEW_ID)}
    )

    class _BrokenConsume:
        def __init__(self, inner):
            self.binding = inner.binding

        async def consume(self):
            raise RuntimeError("store unavailable")

        async def release(self):
            raise AssertionError("must not release after acceptance")

    original = authority.reserve

    async def reserve(**kwargs):
        return _BrokenConsume(await original(**kwargs))

    authority.reserve = reserve
    tool = await bound_execute(handler, authority)

    with caplog.at_level("ERROR"):
        result = await tool.run(EXECUTE_ARGS)

    assert result.structured_content == {"job_id": JOB_ID, "status": "running"}
    assert "grant consume failed" in caplog.text
    assert "store unavailable" not in caplog.text


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
