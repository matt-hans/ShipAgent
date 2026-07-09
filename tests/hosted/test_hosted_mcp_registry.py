import pytest
from jsonschema import validate

from src.control_plane.auth.context import (
    AuthorizationContext,
    clear_authorization_context,
    set_authorization_context,
)
from src.control_plane.request_controls import RequestControlError, hash_arguments
from src.hosted_mcp.server import (
    ToolAuthorizationError,
    build_server,
)
from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.registry.catalog import public_tools
from src.registry.models import ProviderExport
from src.registry.tools.public import FIRST_SLICE_TOOL_NAMES


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
    target_id: str | None = "target-1",
    capabilities: list[str] | None = None,
    message: str | None = None,
):
    return {
        "status": status,
        "executionTarget": {
            "state": state,
            "target_id": target_id,
            "capabilities": capabilities or ["rate", "ship"],
            "message": message,
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
        return {
            "status": "ready",
            "executionTarget": {
                "state": "ready",
                "target_id": "loopback",
                "capabilities": ["get_shipagent_status"],
                "message": None,
            },
        }

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
        result = await tools["get_shipagent_status"].run({"correlation_id": "corr-1"})
    finally:
        clear_authorization_context(token)

    assert result.structured_content == {
        "status": "ready",
        "executionTarget": {
            "state": "ready",
            "target_id": "loopback",
            "capabilities": ["get_shipagent_status"],
            "message": None,
        },
    }
    validate(
        instance=result.structured_content,
        schema=tools["get_shipagent_status"].output_schema,
    )


@pytest.mark.asyncio
async def test_loopback_execution_target_status_runs_through_hosted_mcp_tool():
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
        result = await tools["get_shipagent_status"].run({"correlation_id": "corr-1"})
    finally:
        clear_authorization_context(token)

    assert result.structured_content == {
        "status": "ready",
        "executionTarget": {
            "state": "ready",
            "target_id": "loopback",
            "capabilities": ["rate_shipment", "get_shipagent_status"],
            "message": None,
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
        await tools["get_shipagent_status"].run({"correlation_id": "corr-1"})
    finally:
        clear_authorization_context(token)

    assert captured["request"] == TargetToolRequest(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        tool_name="get_shipagent_status",
        arguments={"correlation_id": "corr-1"},
        correlation_id="corr-1",
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
        result = await tools["get_shipagent_status"].run({"correlation_id": "corr-1"})
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
        await tools["get_shipagent_status"].run({"correlation_id": "corr-1"})

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
            await tools["get_shipagent_status"].run({"correlation_id": "corr-1"})
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
        return {"rates": [{"carrier": "UPS"}], "selected": "ups"}

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
        result = await tools["get_shipment_rates"].run({"shipment_id": "ship-1"})
    finally:
        clear_authorization_context(token)

    assert invoked["value"] is True
    assert result.structured_content == {"rates": [{"carrier": "UPS"}], "selected": "ups"}
    assert calls == [
        {
            "connection_id": "pc-1",
            "tool_name": "get_shipment_rates",
            "rate_limit_class": "estimate",
            "arguments_hash": hash_arguments({"shipment_id": "ship-1"}),
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
            await tools["get_shipagent_status"].run({"correlation_id": "corr-1"})
    finally:
        clear_authorization_context(token)

    assert exc.value.code == "provider_loop_detected"
    assert invoked["value"] is False


@pytest.mark.parametrize("tool_name", FIRST_SLICE_TOOL_NAMES)
def test_first_slice_public_input_schema_rejects_identity_fields(tool_name: str):
    prohibited = {"account_id", "tenant_id", "provider_connection_id", "user_id"}
    contract = tool(tool_name)
    assert prohibited.isdisjoint(set(contract.input_schema["properties"]))
