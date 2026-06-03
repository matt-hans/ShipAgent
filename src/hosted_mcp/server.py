"""Hosted public MCP surface generated from the canonical registry."""

from typing import Any

from fastmcp import FastMCP
from fastmcp.tools import Tool
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent, ToolAnnotations

from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.registry.catalog import public_tools


def _placeholder_value(schema: dict[str, Any]) -> Any:
    schema_type = schema.get("type")
    if schema_type == "object":
        return {
            name: _placeholder_value(property_schema)
            for name, property_schema in schema.get("properties", {}).items()
            if name in schema.get("required", [])
        }
    if schema_type == "array":
        return []
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0.0
    if schema_type == "boolean":
        return False
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    return "pending_workflow_binding"


class RegistryBackedTool(Tool):
    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=(
                        f"{self.name} is registered from the canonical registry "
                        "and is pending workflow binding."
                    ),
                )
            ],
            structured_content=_placeholder_value(self.output_schema or {}),
        )


def build_server() -> FastMCP:
    server = FastMCP("ShipAgentHosted")
    for tool in public_tools():
        descriptor = to_mcp_tool_descriptor(tool)
        server.add_tool(
            RegistryBackedTool(
                name=tool.name,
                title=tool.title,
                description=tool.description,
                parameters=descriptor["inputSchema"],
                output_schema=descriptor["outputSchema"],
                annotations=ToolAnnotations(**descriptor["annotations"]),
            )
        )
    return server
