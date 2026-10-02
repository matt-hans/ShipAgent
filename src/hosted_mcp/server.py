"""Hosted public MCP surface generated from the canonical registry."""

import inspect
import json
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from fastmcp.tools.tool import ToolResult
from jsonschema import validate
from mcp.types import TextContent, ToolAnnotations

from src.control_plane.auth.context import (
    AuthorizationContext,
    get_authorization_context,
)
from src.control_plane.request_controls import (
    RequestControlError,
    RequestControls,
    hash_arguments,
)
from src.control_plane.result_projection import project_result
from src.provider_adapters.export_filter import exportable_tools
from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.registry.models import ProviderExport, ToolContract

ToolHandler = Callable[
    [AuthorizationContext, dict[str, Any]],
    Awaitable[dict[str, Any]] | dict[str, Any],
]
logger = logging.getLogger(__name__)

PROVIDER_RESULT_ERROR = "Tool result could not be safely returned"


class BoundRegistryTool(Tool):
    def __init__(
        self,
        *args: Any,
        contract: ToolContract,
        handler: ToolHandler,
        request_controls: RequestControls | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        object.__setattr__(self, "_contract", contract)
        object.__setattr__(self, "_handler", handler)
        object.__setattr__(self, "_request_controls", request_controls)

    @staticmethod
    def _context_missing_error() -> "ToolAuthorizationError":
        return ToolAuthorizationError(
            code="missing_authorization_context",
            message="authorization context unavailable",
        )

    @staticmethod
    def _missing_scopes_error(required_scopes: list[str]) -> "ToolAuthorizationError":
        return ToolAuthorizationError(
            code="insufficient_scope",
            message="insufficient scopes",
            required_scopes=required_scopes,
        )

    @staticmethod
    def _loop_guard_or_rate_limit_error(
        err: RequestControlError,
    ) -> "ToolAuthorizationError":
        return ToolAuthorizationError(
            code=err.code,
            message=err.message,
            retry_after_seconds=err.retry_after_seconds,
        )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        context = get_authorization_context()
        if context is None:
            raise self._context_missing_error()

        missing = set(self._contract.auth_scopes) - context.scopes
        if missing:
            raise self._missing_scopes_error(sorted(missing))

        failure_category: str | None = None
        result: Any = None
        try:
            validate(instance=arguments, schema=self._contract.input_schema)
        except Exception:  # noqa: BLE001 - provider input is a fail-closed boundary.
            failure_category = "input"

        if failure_category is None:
            request_controls = getattr(self, "_request_controls", None)
            if request_controls is not None:
                try:
                    await request_controls.require_allowed(
                        connection_id=context.provider_connection_id,
                        tool_name=self._contract.name,
                        rate_limit_class=self._contract.rate_limit_class,
                        arguments_hash=hash_arguments(arguments),
                    )
                except RequestControlError as err:
                    raise self._loop_guard_or_rate_limit_error(err) from err

            try:
                result = self._handler(context, arguments)
                if inspect.isawaitable(result):
                    result = await result
            except Exception:  # noqa: BLE001 - provider handler is a safe boundary.
                failure_category = "handler"

        if failure_category is None:
            try:
                result = project_result(self._contract, result)
            except Exception:  # noqa: BLE001 - projection is a safe boundary.
                failure_category = "projection"

        if failure_category is not None:
            logger.warning(
                "Provider tool failure for tool %s category=%s",
                self._contract.name,
                failure_category,
            )
            raise ToolError(PROVIDER_RESULT_ERROR)

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
    request_controls: RequestControls | None = None,
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
                request_controls=request_controls,
            )
        )
    return server


class ToolAuthorizationError(PermissionError):
    """Raised when tool invocation cannot be authorized."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        required_scopes: list[str] | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.code = code
        self.required_scopes = required_scopes
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)
