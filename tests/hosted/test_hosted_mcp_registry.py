import logging

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from jsonschema import validate

from src.control_plane.auth.context import (
    AuthorizationContext,
    clear_authorization_context,
    set_authorization_context,
)
from src.control_plane.request_controls import RequestControlError, hash_arguments
from src.hosted_mcp.server import (
    PROVIDER_RESULT_ERROR,
    ToolAuthorizationError,
    build_server,
)
from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.registry.catalog import public_tools
from src.registry.identifiers import ShipAgentIdFamily, shipagent_id_prefix
from src.registry.models import ProviderExport
from src.registry.tools.public import FIRST_SLICE_TOOL_NAMES

VALID_HEX_BODY = "0123456789abcdef0123456789abcdef"
VALID_CONFIRMATION_ID = f"sa_confirmation_{VALID_HEX_BODY}"
VALID_CORRELATION_ID = f"sa_correlation_{VALID_HEX_BODY}"
VALID_DEVICE_ID = f"sa_device_{VALID_HEX_BODY}"
VALID_INGRESS_ID = f"sa_ingress_{VALID_HEX_BODY}"
VALID_INPUT_ID = f"sa_input_{VALID_HEX_BODY}"
VALID_JOB_ID = f"sa_job_{VALID_HEX_BODY}"
VALID_LABEL_ID = f"sa_label_{VALID_HEX_BODY}"
VALID_PREVIEW_ID = f"sa_preview_{VALID_HEX_BODY}"
VALID_VALIDATION_ID = f"sa_validation_{VALID_HEX_BODY}"

PREFIXED_COMPACT_CANARY_BODIES = (
    "ApiKeyLiveValue01",
    "BearerTokenValue1",
    "JaneDoeCustomer01",
    "PrivateRecipient1",
    "742MainStreetCity",
    "QXBpS2V5TGl2ZVZhbHVl",
)


@pytest.fixture
def all_scopes_context():
    """Authorize provider calls with every registered public tool scope."""
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset(
            scope for item in public_tools() for scope in item.auth_scopes
        ),
    )
    token = set_authorization_context(context)
    yield context
    clear_authorization_context(token)


def tool(name: str):
    return next(item for item in public_tools() if item.name == name)


def exportable_mcp_tool(name: str):
    return tool(name).model_copy(
        update={
            "implementation_status": "implemented",
            "hosted_readiness": "ready",
            "provider_export_enabled": True,
            "provider_exports": [ProviderExport.generic_mcp],
        }
    )


def status_result(
    *,
    status: str = "ready",
    state: str = "ready",
    capabilities: list[str] | None = None,
):
    return {
        "status": status,
        "executionTarget": {
            "state": state,
            "capabilities": capabilities or ["rate_shipment"],
        },
    }


@pytest.mark.asyncio
async def test_hosted_mcp_server_does_not_register_unbound_catalog_tools():
    server = build_server()
    tools = await server.get_tools()

    assert tools == {}


@pytest.mark.asyncio
async def test_hosted_mcp_server_requires_exportable_and_bound_tools():
    async def track_package_handler(context, arguments):
        return {"status": "in_transit", "events": []}

    async def job_status_handler(context, arguments):
        return {"job_id": arguments["job_id"], "status": "running"}

    registered_tool = exportable_mcp_tool("get_shipagent_status")
    provider_excluded = exportable_mcp_tool("submit_one_off_shipment").model_copy(
        update={"provider_exports": [ProviderExport.openai]}
    )
    unbound_tool = exportable_mcp_tool("get_shipment_rates")

    server = build_server(
        tools=[registered_tool, provider_excluded, unbound_tool],
        tool_handlers={
            "get_shipagent_status": track_package_handler,
            "submit_one_off_shipment": job_status_handler,
        },
    )
    tools = await server.get_tools()

    assert set(tools) == {"get_shipagent_status"}


@pytest.mark.asyncio
async def test_status_tool_bound_from_default_catalog_projects_execution_target_schema():
    async def handler(context, arguments):
        return status_result(capabilities=["get_shipagent_status"])

    server = build_server(tool_handlers={"get_shipagent_status": handler})
    tools = await server.get_tools()
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )

    token = set_authorization_context(context)
    try:
        result = await tools["get_shipagent_status"].run(
            {"correlation_id": VALID_CORRELATION_ID}
        )
    finally:
        clear_authorization_context(token)

    assert result.structured_content == status_result(
        capabilities=["get_shipagent_status"]
    )
    validate(
        instance=result.structured_content,
        schema=tools["get_shipagent_status"].output_schema,
    )


@pytest.mark.asyncio
async def test_loopback_execution_target_status_hides_target_id_and_message():
    try:
        from src.control_plane.execution_targets import LoopbackExecutionTarget
        from src.hosted_mcp.execution_target_handlers import (
            build_execution_target_tool_handlers,
        )
    except ModuleNotFoundError as exc:
        pytest.fail(f"execution target status handler is not available: {exc}")

    server = build_server(
        tool_handlers=build_execution_target_tool_handlers(
            LoopbackExecutionTarget(
                capabilities=["rate_shipment", "get_shipagent_status"]
            )
        )
    )
    tools = await server.get_tools()
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )

    token = set_authorization_context(context)
    try:
        result = await tools["get_shipagent_status"].run(
            {"correlation_id": VALID_CORRELATION_ID}
        )
    finally:
        clear_authorization_context(token)

    assert result.structured_content == {
        "status": "ready",
        "executionTarget": {
            "state": "ready",
            "capabilities": ["rate_shipment", "get_shipagent_status"],
        },
    }
    validate(
        instance=result.structured_content,
        schema=tools["get_shipagent_status"].output_schema,
    )


@pytest.mark.asyncio
async def test_execution_target_status_handler_passes_mcp_arguments():
    from src.control_plane.execution_targets import TargetToolRequest
    from src.control_plane.relay.protocol import (
        ExecutionTargetStatus,
        RelayTargetState,
        ShipAgentStatus,
    )
    from src.hosted_mcp.execution_target_handlers import (
        build_execution_target_tool_handlers,
    )

    captured = {}

    class CapturingExecutionTarget:
        async def invoke(self, request):
            captured["request"] = request
            return ShipAgentStatus(
                status=RelayTargetState.READY,
                execution_target=ExecutionTargetStatus(
                    state=RelayTargetState.READY,
                    target_id="target-1",
                    capabilities=["get_shipagent_status"],
                ),
            ).model_dump(mode="json", by_alias=True)

    server = build_server(
        tool_handlers=build_execution_target_tool_handlers(CapturingExecutionTarget())
    )
    tools = await server.get_tools()
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )

    token = set_authorization_context(context)
    try:
        await tools["get_shipagent_status"].run(
            {"correlation_id": VALID_CORRELATION_ID}
        )
    finally:
        clear_authorization_context(token)

    assert captured["request"] == TargetToolRequest(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        tool_name="get_shipagent_status",
        arguments={"correlation_id": VALID_CORRELATION_ID},
        correlation_id=VALID_CORRELATION_ID,
    )


@pytest.mark.asyncio
async def test_hosted_mcp_tool_metadata_and_schemas_come_from_registry():
    async def handler(context, arguments):
        return status_result()

    contract = exportable_mcp_tool("get_shipagent_status")
    descriptor = to_mcp_tool_descriptor(contract)
    server = build_server(
        tools=[contract],
        tool_handlers={"get_shipagent_status": handler},
    )
    tools = await server.get_tools()
    registered = tools["get_shipagent_status"]

    assert registered.title == contract.title
    assert registered.description == contract.description
    assert registered.parameters == descriptor["inputSchema"]
    assert registered.output_schema == descriptor["outputSchema"]


@pytest.mark.asyncio
async def test_hosted_mcp_bound_handler_result_matches_advertised_schema():
    async def handler(context, arguments):
        return status_result()

    contract = exportable_mcp_tool("get_shipagent_status")
    server = build_server(
        tools=[contract],
        tool_handlers={"get_shipagent_status": handler},
    )
    tools = await server.get_tools()
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )

    token = set_authorization_context(context)
    try:
        result = await tools["get_shipagent_status"].run(
            {"correlation_id": VALID_CORRELATION_ID}
        )
    finally:
        clear_authorization_context(token)

    assert result.structured_content == status_result()
    validate(
        instance=result.structured_content,
        schema=tools["get_shipagent_status"].output_schema,
    )


@pytest.mark.asyncio
async def test_hosted_mcp_handler_rejects_missing_authorization_context():
    async def handler(context, arguments):
        return status_result()

    contract = exportable_mcp_tool("get_shipagent_status")
    server = build_server(
        tools=[contract],
        tool_handlers={"get_shipagent_status": handler},
    )
    tools = await server.get_tools()

    with pytest.raises(ToolAuthorizationError) as exc:
        await tools["get_shipagent_status"].run(
            {"correlation_id": VALID_CORRELATION_ID}
        )

    assert exc.value.code == "missing_authorization_context"


@pytest.mark.asyncio
async def test_hosted_mcp_handler_rejects_missing_scopes():
    async def handler(context, arguments):
        return status_result()

    contract = exportable_mcp_tool("get_shipagent_status")
    server = build_server(
        tools=[contract],
        tool_handlers={"get_shipagent_status": handler},
    )
    tools = await server.get_tools()
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"account:read"}),
    )
    token = set_authorization_context(context)
    try:
        with pytest.raises(ToolAuthorizationError) as exc:
            await tools["get_shipagent_status"].run(
                {"correlation_id": VALID_CORRELATION_ID}
            )
    finally:
        clear_authorization_context(token)

    assert exc.value.code == "insufficient_scope"
    assert exc.value.required_scopes == ["shipagent.status"]


@pytest.mark.asyncio
async def test_hosted_mcp_handler_applies_request_controls_before_invocation():
    calls = []

    class _RequestControls:
        async def require_allowed(
            self,
            *,
            connection_id: str,
            tool_name: str,
            rate_limit_class: str,
            arguments_hash: str,
        ) -> None:
            calls.append(
                {
                    "connection_id": connection_id,
                    "tool_name": tool_name,
                    "rate_limit_class": rate_limit_class,
                    "arguments_hash": arguments_hash,
                }
            )

    invoked = {"value": False}

    async def handler(context, arguments):
        invoked["value"] = True
        return rate_result()

    contract = exportable_mcp_tool("get_shipment_rates").model_copy(
        update={"rate_limit_class": "estimate"}
    )
    server = build_server(
        tools=[contract],
        tool_handlers={"get_shipment_rates": handler},
        request_controls=_RequestControls(),
    )
    tools = await server.get_tools()
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipments:rate"}),
    )
    token = set_authorization_context(context)
    try:
        result = await tools["get_shipment_rates"].run(
            {"input_reference": VALID_INPUT_ID}
        )
    finally:
        clear_authorization_context(token)

    assert invoked["value"] is True
    assert result.structured_content == rate_result()
    assert calls == [
        {
            "connection_id": "pc-1",
            "tool_name": "get_shipment_rates",
            "rate_limit_class": "estimate",
            "arguments_hash": hash_arguments({"input_reference": VALID_INPUT_ID}),
        }
    ]


@pytest.mark.asyncio
async def test_hosted_mcp_handler_translates_request_control_deny():
    invoked = {"value": False}

    async def handler(context, arguments):
        invoked["value"] = True
        return status_result()

    class _RequestControls:
        async def require_allowed(
            self,
            *,
            connection_id: str,
            tool_name: str,
            rate_limit_class: str,
            arguments_hash: str,
        ) -> None:
            raise RequestControlError(
                code="provider_loop_detected",
                message="identical call loop detected",
            )

    contract = exportable_mcp_tool("get_shipagent_status")
    server = build_server(
        tools=[contract],
        tool_handlers={"get_shipagent_status": handler},
        request_controls=_RequestControls(),
    )
    tools = await server.get_tools()
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )
    token = set_authorization_context(context)
    try:
        with pytest.raises(ToolAuthorizationError) as exc:
            await tools["get_shipagent_status"].run(
                {"correlation_id": VALID_CORRELATION_ID}
            )
    finally:
        clear_authorization_context(token)

    assert exc.value.code == "provider_loop_detected"
    assert invoked["value"] is False


@pytest.mark.parametrize("tool_name", FIRST_SLICE_TOOL_NAMES)
def test_first_slice_public_input_schema_rejects_identity_fields(tool_name: str):
    prohibited = {"account_id", "tenant_id", "provider_connection_id", "user_id"}
    contract = tool(tool_name)
    assert prohibited.isdisjoint(set(contract.input_schema["properties"]))


def rate_result(**overrides):
    rate = {
        "service_code": "03",
        "service_name": "UPS Ground",
        "total_charge": "12.34",
        "currency_code": "USD",
        "estimated_delivery_date": "2026-07-25",
    }
    rate.update(overrides)
    return {"rates": [rate], "selected": "03"}


@pytest.mark.parametrize(
    ("tool_name", "arguments", "result"),
    [
        (
            "get_shipagent_status",
            {"correlation_id": VALID_CORRELATION_ID},
            status_result(capabilities=["shipment_ingress"]),
        ),
        (
            "submit_one_off_shipment",
            {"ingress_reference": VALID_INGRESS_ID},
            {"input_reference": VALID_INPUT_ID},
        ),
        (
            "validate_shipment_address",
            {"input_reference": VALID_INPUT_ID},
            {
                "validation_artifact_id": VALID_VALIDATION_ID,
                "valid": True,
                "guidance_codes": ["no_action_required"],
            },
        ),
        (
            "get_shipment_rates",
            {"input_reference": VALID_INPUT_ID},
            rate_result(),
        ),
        (
            "prepare_shipments",
            {"input_reference": VALID_INPUT_ID},
            {
                "preview_id": VALID_PREVIEW_ID,
                "summary": {"shipment_count": 1},
            },
        ),
        (
            "execute_shipments",
            {
                "preview_id": VALID_PREVIEW_ID,
                "confirmation_artifact_id": VALID_CONFIRMATION_ID,
            },
            {"job_id": VALID_JOB_ID, "status": "running"},
        ),
        (
            "get_job_status",
            {"job_id": VALID_JOB_ID},
            {"job_id": VALID_JOB_ID, "status": "completed"},
        ),
        (
            "create_label_download",
            {"job_id": VALID_JOB_ID},
            {"label_artifact_id": VALID_LABEL_ID, "status": "ready"},
        ),
    ],
)
@pytest.mark.asyncio
@pytest.mark.usefixtures("all_scopes_context")
async def test_real_mcp_round_trips_canonical_identifier_fixtures(
    tool_name,
    arguments,
    result,
):
    async def handler(_context, _arguments):
        return result

    server = build_server(
        tools=[exportable_mcp_tool(tool_name)],
        tool_handlers={tool_name: handler},
    )

    async with Client(server) as client:
        response = await client.call_tool(tool_name, arguments)

    assert response.structured_content == result


@pytest.mark.asyncio
@pytest.mark.usefixtures("all_scopes_context")
async def test_real_mcp_round_trips_completed_with_warnings_job_status():
    result = {
        "job_id": VALID_JOB_ID,
        "status": "completed_with_warnings",
    }

    async def handler(_context, _arguments):
        return result

    server = build_server(
        tools=[exportable_mcp_tool("get_job_status")],
        tool_handlers={"get_job_status": handler},
    )

    async with Client(server) as client:
        response = await client.call_tool(
            "get_job_status",
            {"job_id": VALID_JOB_ID},
        )

    assert response.structured_content == result


@pytest.mark.asyncio
@pytest.mark.usefixtures("all_scopes_context")
async def test_hosted_mcp_execute_shipments_metadata_and_schemas_come_from_registry():
    async def handler(_context, arguments):
        return {"job_id": VALID_JOB_ID, "status": "running"}

    contract = exportable_mcp_tool("execute_shipments")
    descriptor = to_mcp_tool_descriptor(contract)
    server = build_server(
        tools=[contract],
        tool_handlers={"execute_shipments": handler},
    )
    tools = await server.get_tools()
    registered = tools["execute_shipments"]

    assert registered.title == contract.title
    assert registered.description == contract.description
    assert registered.annotations.readOnlyHint is False
    assert registered.annotations.destructiveHint is False
    assert registered.annotations.openWorldHint is True
    assert registered.parameters == descriptor["inputSchema"]
    assert registered.output_schema == descriptor["outputSchema"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("all_scopes_context")
async def test_hosted_mcp_execute_shipments_result_matches_advertised_schema():
    async def handler(_context, arguments):
        return {"job_id": VALID_JOB_ID, "status": "running"}

    contract = exportable_mcp_tool("execute_shipments")
    server = build_server(
        tools=[contract],
        tool_handlers={"execute_shipments": handler},
    )
    tools = await server.get_tools()

    result = await tools["execute_shipments"].run(
        {
            "preview_id": VALID_PREVIEW_ID,
            "confirmation_artifact_id": VALID_CONFIRMATION_ID,
        }
    )

    assert result.structured_content == {
        "job_id": VALID_JOB_ID,
        "status": "running",
    }
    validate(
        instance=result.structured_content,
        schema=tools["execute_shipments"].output_schema,
    )


@pytest.mark.parametrize(
    ("tool_name", "arguments", "unsafe_result", "canary"),
    [
        (
            "get_shipagent_status",
            {"correlation_id": VALID_CORRELATION_ID},
            {
                "status": "ready",
                "active_device_id": "https://private.invalid/device",
                "capabilities": ["shipment_ingress"],
            },
            "https://private.invalid/device",
        ),
        (
            "get_shipagent_status",
            {"correlation_id": VALID_CORRELATION_ID},
            {
                "status": "ready",
                "active_device_id": VALID_DEVICE_ID,
                "capabilities": ["Bearer scalar-credential"],
            },
            "Bearer scalar-credential",
        ),
        (
            "submit_one_off_shipment",
            {"ingress_reference": VALID_INGRESS_ID},
            {"input_reference": "Private Recipient at 17 Confidential Avenue"},
            "Private Recipient",
        ),
        (
            "validate_shipment_address",
            {"input_reference": VALID_INPUT_ID},
            {
                "validation_artifact_id": "https://private.invalid/validation",
                "valid": True,
                "guidance_codes": ["no_action_required"],
            },
            "https://private.invalid/validation",
        ),
        (
            "get_shipment_rates",
            {"input_reference": VALID_INPUT_ID},
            rate_result(service_code="https://private.invalid/service"),
            "https://private.invalid/service",
        ),
        (
            "get_shipment_rates",
            {"input_reference": VALID_INPUT_ID},
            rate_result(service_name="Private Recipient"),
            "Private Recipient",
        ),
        (
            "get_shipment_rates",
            {"input_reference": VALID_INPUT_ID},
            rate_result(total_charge="scalar-credential"),
            "scalar-credential",
        ),
        (
            "get_shipment_rates",
            {"input_reference": VALID_INPUT_ID},
            rate_result(currency_code="17 Confidential Avenue"),
            "17 Confidential Avenue",
        ),
        (
            "get_shipment_rates",
            {"input_reference": VALID_INPUT_ID},
            rate_result(estimated_delivery_date="https://private.invalid/date"),
            "https://private.invalid/date",
        ),
        (
            "get_shipment_rates",
            {"input_reference": VALID_INPUT_ID},
            {**rate_result(), "selected": "Bearer scalar-credential"},
            "Bearer scalar-credential",
        ),
        (
            "prepare_shipments",
            {"input_reference": VALID_INPUT_ID},
            {
                "preview_id": "https://private.invalid/preview",
                "summary": {"shipment_count": 1},
            },
            "https://private.invalid/preview",
        ),
        (
            "prepare_shipments",
            {"input_reference": VALID_INPUT_ID},
            {
                "preview_id": VALID_PREVIEW_ID,
                "summary": {"shipment_count": 1_000_001},
            },
            None,
        ),
        (
            "execute_shipments",
            {
                "preview_id": VALID_PREVIEW_ID,
                "confirmation_artifact_id": VALID_CONFIRMATION_ID,
            },
            {
                "job_id": "https://private.invalid/job?token=scalar-credential",
                "status": "running",
            },
            "https://private.invalid/job",
        ),
        (
            "get_job_status",
            {"job_id": VALID_JOB_ID},
            {
                "job_id": "Private Recipient at 17 Confidential Avenue",
                "status": "completed",
            },
            "17 Confidential Avenue",
        ),
        (
            "create_label_download",
            {"job_id": VALID_JOB_ID},
            {
                "label_artifact_id": "https://private.invalid/label",
                "status": "ready",
            },
            "https://private.invalid/label",
        ),
    ],
)
@pytest.mark.asyncio
@pytest.mark.usefixtures("all_scopes_context")
async def test_real_mcp_rejects_canaries_in_every_scalar_family(
    caplog,
    tool_name,
    arguments,
    unsafe_result,
    canary,
):
    async def handler(_context, _arguments):
        return unsafe_result

    contract = exportable_mcp_tool(tool_name)
    server = build_server(
        tools=[contract],
        tool_handlers={tool_name: handler},
    )
    caplog.set_level(logging.WARNING)

    async with Client(server) as client:
        with pytest.raises(ToolError) as exc_info:
            await client.call_tool(tool_name, arguments)

    assert str(exc_info.value) == "Tool result could not be safely returned"
    if canary is not None:
        assert canary not in f"{exc_info.value}\n{caplog.text}"


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        (
            "get_shipagent_status",
            {"correlation_id": "https://private.invalid/correlation"},
        ),
        (
            "submit_one_off_shipment",
            {"ingress_reference": "Private Recipient at 17 Confidential Avenue"},
        ),
        (
            "validate_shipment_address",
            {"input_reference": "Bearer input-credential"},
        ),
        (
            "get_shipment_rates",
            {"input_reference": "https://private.invalid/input"},
        ),
        (
            "prepare_shipments",
            {"input_reference": "Private Recipient"},
        ),
        (
            "execute_shipments",
            {
                "preview_id": "https://private.invalid/preview",
                "confirmation_artifact_id": VALID_CONFIRMATION_ID,
            },
        ),
        (
            "execute_shipments",
            {
                "preview_id": VALID_PREVIEW_ID,
                "confirmation_artifact_id": "Bearer confirmation-credential",
            },
        ),
        (
            "get_job_status",
            {"job_id": "17 Confidential Avenue"},
        ),
        (
            "create_label_download",
            {"job_id": "https://private.invalid/job"},
        ),
    ],
)
@pytest.mark.asyncio
@pytest.mark.usefixtures("all_scopes_context")
async def test_real_mcp_rejects_canaries_in_every_input_identifier(
    tool_name,
    arguments,
):
    handler_called = False

    async def handler(_context, _arguments):
        nonlocal handler_called
        handler_called = True
        return {}

    contract = exportable_mcp_tool(tool_name)
    server = build_server(
        tools=[contract],
        tool_handlers={tool_name: handler},
    )

    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool(tool_name, arguments)

    assert handler_called is False


@pytest.mark.parametrize("family", list(ShipAgentIdFamily))
@pytest.mark.parametrize("canary_body", PREFIXED_COMPACT_CANARY_BODIES)
@pytest.mark.asyncio
@pytest.mark.usefixtures("all_scopes_context")
async def test_real_mcp_rejects_prefixed_compact_canaries_for_every_id_family(
    caplog,
    family,
    canary_body,
):
    canary = f"{shipagent_id_prefix(family)}{canary_body}"
    cases = {
        ShipAgentIdFamily.CORRELATION: (
            "get_shipagent_status",
            {"correlation_id": canary},
            {},
            False,
        ),
        ShipAgentIdFamily.DEVICE: (
            "get_shipagent_status",
            {"correlation_id": VALID_CORRELATION_ID},
            {
                "status": "ready",
                "active_device_id": canary,
                "capabilities": ["shipment_ingress"],
            },
            True,
        ),
        ShipAgentIdFamily.INGRESS: (
            "submit_one_off_shipment",
            {"ingress_reference": canary},
            {},
            False,
        ),
        ShipAgentIdFamily.INPUT: (
            "validate_shipment_address",
            {"input_reference": canary},
            {},
            False,
        ),
        ShipAgentIdFamily.VALIDATION: (
            "validate_shipment_address",
            {"input_reference": VALID_INPUT_ID},
            {
                "validation_artifact_id": canary,
                "valid": True,
                "guidance_codes": ["no_action_required"],
            },
            True,
        ),
        ShipAgentIdFamily.PREVIEW: (
            "execute_shipments",
            {
                "preview_id": canary,
                "confirmation_artifact_id": VALID_CONFIRMATION_ID,
            },
            {},
            False,
        ),
        ShipAgentIdFamily.CONFIRMATION: (
            "execute_shipments",
            {
                "preview_id": VALID_PREVIEW_ID,
                "confirmation_artifact_id": canary,
            },
            {},
            False,
        ),
        ShipAgentIdFamily.JOB: (
            "get_job_status",
            {"job_id": canary},
            {},
            False,
        ),
        ShipAgentIdFamily.LABEL: (
            "create_label_download",
            {"job_id": VALID_JOB_ID},
            {"label_artifact_id": canary, "status": "ready"},
            True,
        ),
    }
    tool_name, arguments, unsafe_result, handler_expected = cases[family]
    handler_called = False

    async def handler(_context, _arguments):
        nonlocal handler_called
        handler_called = True
        return unsafe_result

    server = build_server(
        tools=[exportable_mcp_tool(tool_name)],
        tool_handlers={tool_name: handler},
    )
    caplog.set_level(logging.WARNING)

    async with Client(server) as client:
        with pytest.raises(ToolError) as exc_info:
            await client.call_tool(tool_name, arguments)

    assert handler_called is handler_expected
    assert str(exc_info.value) == PROVIDER_RESULT_ERROR
    assert canary not in f"{exc_info.value}\n{caplog.text}"


@pytest.mark.parametrize("async_failure", [False, True])
@pytest.mark.asyncio
@pytest.mark.usefixtures("all_scopes_context")
async def test_direct_handler_failures_have_no_provider_or_exception_leakage(
    caplog,
    async_failure,
):
    sensitive_failure = (
        "handler credential and private recipient at confidential address"
    )

    def sync_handler(_context, _arguments):
        raise RuntimeError(sensitive_failure)

    async def async_handler(_context, _arguments):
        raise RuntimeError(sensitive_failure)

    handler = async_handler if async_failure else sync_handler
    server = build_server(
        tools=[exportable_mcp_tool("execute_shipments")],
        tool_handlers={"execute_shipments": handler},
    )
    registered = (await server.get_tools())["execute_shipments"]
    caplog.set_level(logging.WARNING)

    with pytest.raises(ToolError) as exc_info:
        await registered.run(
            {
                "preview_id": VALID_PREVIEW_ID,
                "confirmation_artifact_id": VALID_CONFIRMATION_ID,
            }
        )

    assert str(exc_info.value) == PROVIDER_RESULT_ERROR
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert [
        record.getMessage()
        for record in caplog.records
        if record.name == "src.hosted_mcp.server"
    ] == ["Provider tool failure for tool execute_shipments category=handler"]
    assert sensitive_failure not in f"{exc_info.value}\n{caplog.text}"


@pytest.mark.asyncio
@pytest.mark.usefixtures("all_scopes_context")
async def test_direct_projection_failure_has_no_exception_context(caplog):
    async def handler(_context, _arguments):
        return {
            "job_id": "projection credential and private recipient address",
            "status": "running",
        }

    server = build_server(
        tools=[exportable_mcp_tool("execute_shipments")],
        tool_handlers={"execute_shipments": handler},
    )
    registered = (await server.get_tools())["execute_shipments"]
    caplog.set_level(logging.WARNING)

    with pytest.raises(ToolError) as exc_info:
        await registered.run(
            {
                "preview_id": VALID_PREVIEW_ID,
                "confirmation_artifact_id": VALID_CONFIRMATION_ID,
            }
        )

    assert str(exc_info.value) == PROVIDER_RESULT_ERROR
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert [
        record.getMessage()
        for record in caplog.records
        if record.name == "src.hosted_mcp.server"
    ] == ["Provider tool failure for tool execute_shipments category=projection"]
    assert "private recipient address" not in f"{exc_info.value}\n{caplog.text}"


@pytest.mark.parametrize("async_failure", [False, True])
@pytest.mark.asyncio
@pytest.mark.usefixtures("all_scopes_context")
async def test_real_mcp_handler_failures_are_provider_and_log_safe(
    caplog,
    async_failure,
):
    sensitive_failure = "handler token with private customer and address"

    def sync_handler(_context, _arguments):
        raise RuntimeError(sensitive_failure)

    async def async_handler(_context, _arguments):
        raise RuntimeError(sensitive_failure)

    handler = async_handler if async_failure else sync_handler
    server = build_server(
        tools=[exportable_mcp_tool("execute_shipments")],
        tool_handlers={"execute_shipments": handler},
    )
    caplog.set_level(logging.WARNING)

    async with Client(server) as client:
        with pytest.raises(ToolError) as exc_info:
            await client.call_tool(
                "execute_shipments",
                {
                    "preview_id": VALID_PREVIEW_ID,
                    "confirmation_artifact_id": VALID_CONFIRMATION_ID,
                },
            )

    assert str(exc_info.value) == PROVIDER_RESULT_ERROR
    assert [
        record.getMessage()
        for record in caplog.records
        if record.name == "src.hosted_mcp.server"
    ] == ["Provider tool failure for tool execute_shipments category=handler"]
    assert sensitive_failure not in f"{exc_info.value}\n{caplog.text}"


@pytest.mark.parametrize(
    ("failure_mode", "unsafe_result"),
    [
        (
            "schema",
            {
                "job_id": (
                    "https://private.invalid/result?"
                    "credential=projection-token customer=Private Recipient "
                    "address=17 Confidential Avenue"
                ),
                "status": "projection-token",
            },
        ),
        (
            "privacy",
            {
                "job_id": VALID_JOB_ID,
                "status": "running",
                "address_line_1": "17 Confidential Avenue",
            },
        ),
        (
            "size",
            {
                "job_id": "https://private.invalid/result",
                "status": "running",
            },
        ),
        (
            "projection",
            ["projection-token", "Private Recipient"],
        ),
    ],
)
@pytest.mark.asyncio
@pytest.mark.usefixtures("all_scopes_context")
async def test_hosted_mcp_projection_failures_are_provider_and_log_safe(
    caplog,
    failure_mode,
    unsafe_result,
):
    async def handler(_context, arguments):
        return unsafe_result

    contract = exportable_mcp_tool("execute_shipments")
    if failure_mode == "size":
        contract = contract.model_copy(update={"max_result_bytes": 1})
    server = build_server(
        tools=[contract],
        tool_handlers={"execute_shipments": handler},
    )
    caplog.set_level(logging.WARNING)

    async with Client(server) as client:
        with pytest.raises(ToolError) as exc_info:
            await client.call_tool(
                "execute_shipments",
                {
                    "preview_id": VALID_PREVIEW_ID,
                    "confirmation_artifact_id": VALID_CONFIRMATION_ID,
                },
            )

    assert str(exc_info.value) == "Tool result could not be safely returned"
    hosted_logs = [
        record.getMessage()
        for record in caplog.records
        if record.name == "src.hosted_mcp.server"
    ]
    assert hosted_logs == [
        "Provider tool failure for tool execute_shipments category=projection"
    ]
    provider_and_log_output = f"{exc_info.value}\n{caplog.text}"
    for sensitive_value in (
        "https://private.invalid/result",
        "projection-token",
        "Private Recipient",
        "17 Confidential Avenue",
    ):
        assert sensitive_value not in provider_and_log_output


def test_status_schema_admits_every_capability_the_relay_publishes():
    from src.control_plane.execution_targets import PUBLIC_STATUS_CAPABILITIES

    schema = tool("get_shipagent_status").output_schema
    capability_enum = set(
        schema["properties"]["executionTarget"]["properties"]["capabilities"]["items"][
            "enum"
        ]
    )

    assert PUBLIC_STATUS_CAPABILITIES <= capability_enum


def test_status_schema_admits_every_relay_target_state():
    from src.control_plane.relay.protocol import RelayTargetState

    schema = tool("get_shipagent_status").output_schema
    states = {state.value for state in RelayTargetState}

    assert set(schema["properties"]["status"]["enum"]) == states
    assert (
        set(schema["properties"]["executionTarget"]["properties"]["state"]["enum"])
        == states
    )
