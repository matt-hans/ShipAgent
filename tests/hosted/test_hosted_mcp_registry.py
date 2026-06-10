import pytest
from jsonschema import validate

from src.hosted_mcp.server import build_server
from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.registry.catalog import public_tools
from src.registry.models import ProviderExport


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


@pytest.mark.asyncio
async def test_hosted_mcp_server_does_not_register_unbound_catalog_tools():
    server = build_server()
    tools = await server.get_tools()

    assert tools == {}


@pytest.mark.asyncio
async def test_hosted_mcp_server_requires_exportable_and_bound_tools():
    async def execute_shipments_handler(arguments):
        return {"job_id": "job-1", "status": "running"}

    async def job_status_handler(arguments):
        return {"job_id": arguments["job_id"], "status": "running"}

    registered_tool = exportable_mcp_tool("execute_shipments")
    provider_excluded = exportable_mcp_tool("get_job_status").model_copy(
        update={"provider_exports": [ProviderExport.openai]}
    )
    unbound_tool = exportable_mcp_tool("create_label_download")

    server = build_server(
        tools=[registered_tool, provider_excluded, unbound_tool],
        tool_handlers={
            "execute_shipments": execute_shipments_handler,
            "get_job_status": job_status_handler,
        },
    )
    tools = await server.get_tools()

    assert set(tools) == {"execute_shipments"}


@pytest.mark.asyncio
async def test_hosted_mcp_tool_metadata_and_schemas_come_from_registry():
    async def handler(arguments):
        return {"job_id": "job-1", "status": "running"}

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
async def test_hosted_mcp_bound_handler_result_matches_advertised_schema():
    async def handler(arguments):
        return {"job_id": "job-1", "status": "running"}

    contract = exportable_mcp_tool("execute_shipments")
    server = build_server(
        tools=[contract],
        tool_handlers={"execute_shipments": handler},
    )
    tools = await server.get_tools()

    result = await tools["execute_shipments"].run(
        {"preview_id": "preview-1", "confirmation_token": "token-1"}
    )

    assert result.structured_content == {"job_id": "job-1", "status": "running"}
    validate(
        instance=result.structured_content, schema=tools["execute_shipments"].output_schema
    )
