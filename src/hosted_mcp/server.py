"""Hosted public MCP surface generated from the canonical registry."""

import inspect
import json
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import UTC, datetime
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
from src.control_plane.execution_grants import (
    ExecutionGrantAuthority,
    ExecutionGrantError,
    ExecutionGrantReservation,
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
        execution_grants: ExecutionGrantAuthority | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        object.__setattr__(self, "_contract", contract)
        object.__setattr__(self, "_handler", handler)
        object.__setattr__(self, "_request_controls", request_controls)
        object.__setattr__(self, "_execution_grants", execution_grants)

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

    @staticmethod
    def _grant_unavailable_error() -> "ToolAuthorizationError":
        return ToolAuthorizationError(
            code="execution_grant_unavailable",
            message="approval could not be verified; prepare and approve again",
        )

    @staticmethod
    def _grant_invalid_error() -> "ToolAuthorizationError":
        return ToolAuthorizationError(
            code="execution_grant_invalid",
            message="approval does not match this request; prepare and approve again",
        )

    async def _reserve_execution_grant(
        self,
        context: AuthorizationContext,
        arguments: dict[str, Any],
    ) -> ExecutionGrantReservation:
        """Reserve the server-side grant for a confirming tool or fail closed.

        Authority comes only from the server-side grant resolved through the
        opaque Approval Request reference; model arguments and history never
        grant it. A reservation that does not exactly match the caller and the
        requested preview is released and rejected.
        """
        authority = getattr(self, "_execution_grants", None)
        approval_request_id = arguments.get("approval_request_id")
        if (
            authority is None
            or self._contract.prepare_tool is None
            or not isinstance(approval_request_id, str)
        ):
            raise self._grant_unavailable_error()
        try:
            reservation = await authority.reserve(
                context=context,
                tool_name=self._contract.name,
                prepare_tool=self._contract.prepare_tool,
                approval_request_id=approval_request_id,
            )
        except ExecutionGrantError as err:
            raise ToolAuthorizationError(
                code=err.denial.value,
                message="approval required before execution; prepare and approve again",
            ) from err
        except Exception as err:  # noqa: BLE001 - grant lookup is a fail-closed boundary.
            raise self._grant_unavailable_error() from err
        if not self._binding_matches(reservation, context, arguments):
            await self._release_quietly(reservation)
            raise self._grant_invalid_error()
        return reservation

    @staticmethod
    def _binding_matches(
        reservation: ExecutionGrantReservation,
        context: AuthorizationContext,
        arguments: dict[str, Any],
    ) -> bool:
        """Check the grant binds this caller, this preview and a live purchase."""
        binding = reservation.binding
        required = (
            binding.execution_target_id,
            binding.policy,
            binding.amount,
            binding.currency_code,
            binding.idempotency_key,
        )
        return (
            binding.account_id == context.account_id
            and binding.provider_connection_id == context.provider_connection_id
            and binding.preview_id == arguments.get("preview_id")
            and binding.expires_at > datetime.now(UTC)
            and all(required)
        )

    async def _release_quietly(self, reservation: ExecutionGrantReservation) -> None:
        """Release a reservation without masking the primary failure."""
        try:
            await reservation.release()
        except Exception:  # noqa: BLE001 - release is best effort; expiry bounds it.
            logger.error(
                "Execution grant release failed for tool %s", self._contract.name
            )

    async def _consume_after_acceptance(
        self, reservation: ExecutionGrantReservation
    ) -> None:
        """Consume the grant once the target accepted; never hide the acceptance."""
        try:
            await reservation.consume()
        except Exception:  # noqa: BLE001 - accepted work must still be reported.
            logger.error(
                "Execution grant consume failed for tool %s", self._contract.name
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

            reservation: ExecutionGrantReservation | None = None
            if self._contract.requires_confirmation:
                reservation = await self._reserve_execution_grant(context, arguments)

            accepted = False
            try:
                result = self._handler(context, arguments)
                if inspect.isawaitable(result):
                    result = await result
                accepted = True
            except Exception:  # noqa: BLE001 - provider handler is a safe boundary.
                failure_category = "handler"
            finally:
                if reservation is not None and not accepted:
                    await self._release_quietly(reservation)
            if accepted and reservation is not None:
                await self._consume_after_acceptance(reservation)

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
    execution_grants: ExecutionGrantAuthority | None = None,
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
                execution_grants=execution_grants,
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
