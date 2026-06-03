import pytest
from jsonschema import validate

from src.hosted_mcp.server import build_server
from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.registry.catalog import public_tools


@pytest.mark.asyncio
async def test_hosted_mcp_server_registers_public_tools():
    server = build_server()
    tools = await server.get_tools()

    assert "preview_shipments" in tools
    assert "raw_ups_tool" not in tools


@pytest.mark.asyncio
async def test_hosted_mcp_server_registers_only_public_catalog_tools():
    server = build_server()
    tools = await server.get_tools()

    assert set(tools) == {tool.name for tool in public_tools()}


@pytest.mark.asyncio
async def test_hosted_mcp_tool_metadata_comes_from_canonical_registry():
    server = build_server()
    tools = await server.get_tools()
    contract = next(tool for tool in public_tools() if tool.name == "preview_shipments")
    registered = tools["preview_shipments"]

    assert registered.title == contract.title
    assert registered.description == contract.description
    assert registered.annotations.readOnlyHint is True
    assert registered.annotations.destructiveHint is False
    assert registered.annotations.openWorldHint is True


@pytest.mark.asyncio
async def test_hosted_mcp_tool_schemas_come_from_canonical_registry():
    server = build_server()
    tools = await server.get_tools()
    contract = next(tool for tool in public_tools() if tool.name == "preview_shipments")
    descriptor = to_mcp_tool_descriptor(contract)
    registered = tools["preview_shipments"]

    assert registered.parameters == descriptor["inputSchema"]
    assert registered.output_schema == descriptor["outputSchema"]
    assert "order_batch_id" in registered.parameters["required"]
    assert "args" not in registered.parameters["properties"]


@pytest.mark.asyncio
async def test_hosted_mcp_placeholder_outputs_match_advertised_schemas():
    server = build_server()
    tools = await server.get_tools()

    for registered in tools.values():
        result = await registered.run({})

        validate(instance=result.structured_content, schema=registered.output_schema)


@pytest.mark.asyncio
async def test_hosted_mcp_placeholder_handler_returns_pending_binding_status():
    server = build_server()
    tools = await server.get_tools()

    result = await tools["preview_shipments"].run({"order_batch_id": "batch-1"})

    assert result.content[0].text == (
        "preview_shipments is registered from the canonical registry "
        "and is pending workflow binding."
    )
    assert result.structured_content == {
        "preview_id": "pending_workflow_binding",
        "summary": {},
    }
