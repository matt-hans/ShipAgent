"""Hosted public MCP surface generated from the canonical registry."""

import inspect
import json
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

from fastmcp import FastMCP
from fastmcp.tools import Tool
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent, ToolAnnotations

from src.provider_adapters.export_filter import exportable_tools
from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.control_plane.result_projection import project_result
from src.registry.models import ProviderExport, ToolContract

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


class BoundRegistryTool(Tool):
    def __init__(
        self, *args: Any, contract: ToolContract, handler: ToolHandler, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        object.__setattr__(self, "_contract", contract)
        object.__setattr__(self, "_handler", handler)

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        result = self._handler(arguments)
        if inspect.isawaitable(result):
            result = await result
        result = project_result(self._contract, result)
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(result, sort_keys=True),
                )
            ],
            structured_content=result,
        )


def build_server(
    tool_handlers: Mapping[str, ToolHandler] | None = None,
    tools: Iterable[ToolContract] | None = None,
) -> FastMCP:
    server = FastMCP("ShipAgentHosted")
    handlers = tool_handlers or {}
    for tool in exportable_tools(ProviderExport.generic_mcp, tools):
        handler = handlers.get(tool.name)
        if handler is None:
            continue
        descriptor = to_mcp_tool_descriptor(tool)
        server.add_tool(
            BoundRegistryTool(
            name=tool.name,
            title=tool.title,
            description=tool.description,
            parameters=descriptor["inputSchema"],
            output_schema=descriptor["outputSchema"],
            annotations=ToolAnnotations(**descriptor["annotations"]),
            contract=tool,
            handler=handler,
        )
        )
    return server
