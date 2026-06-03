"""Hosted public MCP surface generated from the canonical registry."""

from typing import Any

from fastmcp import FastMCP

from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.registry.catalog import public_tools


def _handler_for(tool_name: str):
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"{tool_name} is registered from the canonical registry.",
                }
            ],
            "structuredContent": {
                "status": "pending_workflow_binding",
                "tool": tool_name,
                "args": args,
            },
        }

    return handler


def build_server() -> FastMCP:
    server = FastMCP("ShipAgentHosted")
    for tool in public_tools():
        descriptor = to_mcp_tool_descriptor(tool)
        handler = _handler_for(tool.name)
        server.tool(
            handler,
            name=tool.name,
            title=tool.title,
            description=tool.description,
            annotations=descriptor["annotations"],
        )
    return server
