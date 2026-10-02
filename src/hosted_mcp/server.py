"""Hosted public MCP surface generated from the canonical registry."""

import asyncio
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
    ExecutionGrantBinding,
    ExecutionGrantDenial,
    ExecutionGrantError,
    ExecutionGrantReservation,
    PreAcceptFailure,
)
from src.control_plane.request_controls import (
    RequestControlError,
    RequestControls,
    hash_arguments,
)
from src.control_plane.result_projection import project_result
from src.provider_adapters.export_filter import exportable_tools
from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.registry.identifiers import APPROVAL_REQUEST_ID_FIELD, PREVIEW_ID_FIELD
from src.registry.models import ProviderExport, SideEffectClass, ToolContract

ToolHandler = Callable[
    [AuthorizationContext, dict[str, Any]],
    Awaitable[dict[str, Any]] | dict[str, Any],
]
ConfirmedToolHandler = Callable[
    [AuthorizationContext, dict[str, Any], ExecutionGrantBinding],
    Awaitable[dict[str, Any]] | dict[str, Any],
]
MUTATING_SIDE_EFFECTS = frozenset(
    {
        SideEffectClass.write,
        SideEffectClass.purchase,
        SideEffectClass.external_mutation,
        SideEffectClass.destructive,
    }
)
logger = logging.getLogger(__name__)

PROVIDER_RESULT_ERROR = "Tool result could not be safely returned"


class BoundRegistryTool(Tool):
    def __init__(
        self,
        *args: Any,
        contract: ToolContract,
        handler: ToolHandler | ConfirmedToolHandler,
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
        """Build the fail-closed error for an unverifiable approval."""
        return ToolAuthorizationError(
            code=ExecutionGrantDenial.GRANT_UNAVAILABLE.value,
            message="approval could not be verified; prepare and approve again",
        )

    @staticmethod
    def _grant_invalid_error() -> "ToolAuthorizationError":
        """Build the error for an approval that does not match this request."""
        return ToolAuthorizationError(
            code=ExecutionGrantDenial.GRANT_INVALID.value,
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
        grant it. A reservation whose binding is malformed or does not exactly
        match the caller, requested preview and tool policy is released and
        rejected.
        """
        authority = getattr(self, "_execution_grants", None)
        approval_request_id = arguments.get(APPROVAL_REQUEST_ID_FIELD)
        preview_id = arguments.get(PREVIEW_ID_FIELD)
        if (
            authority is None
            or self._contract.prepare_tool is None
            or not isinstance(approval_request_id, str)
            or not isinstance(preview_id, str)
        ):
            self._audit_denial(ExecutionGrantDenial.GRANT_UNAVAILABLE)
            raise self._grant_unavailable_error()
        try:
            reservation = await authority.reserve(
                context=context,
                tool_name=self._contract.name,
                prepare_tool=self._contract.prepare_tool,
                approval_request_id=approval_request_id,
                preview_id=preview_id,
            )
        except ExecutionGrantError as err:
            self._audit_denial(err.denial)
            raise ToolAuthorizationError(
                code=err.denial.value,
                message="approval required before execution; prepare and approve again",
            ) from err
        except Exception as err:  # noqa: BLE001 - grant lookup is a fail-closed boundary.
            self._audit_denial(
                ExecutionGrantDenial.GRANT_UNAVAILABLE, cause=type(err).__name__
            )
            raise self._grant_unavailable_error() from err
        if not self._binding_matches(reservation, context, preview_id):
            await self._release_quietly(reservation)
            self._audit_denial(ExecutionGrantDenial.GRANT_INVALID)
            raise self._grant_invalid_error()
        logger.info("Execution grant reserved for tool %s", self._contract.name)
        return reservation

    def _audit_denial(
        self, denial: ExecutionGrantDenial, cause: str | None = None
    ) -> None:
        """Log a grant denial by tool and code only; no identifiers or amounts."""
        logger.warning(
            "Execution grant denied for tool %s code=%s cause=%s",
            self._contract.name,
            denial.value,
            cause,
        )

    def _binding_matches(
        self,
        reservation: ExecutionGrantReservation,
        context: AuthorizationContext,
        preview_id: str,
    ) -> bool:
        """Check the binding is well formed and fits this caller, preview and tool.

        Any malformed reservation or binding (missing, wrong types, naive expiry)
        is a mismatch rather than an exception, so the caller can release it.
        """
        try:
            binding = reservation.binding
            if not isinstance(binding, ExecutionGrantBinding):
                return False
            binding.validate(policy=self._contract.confirmation_policy)
            return (
                binding.account_id == context.account_id
                and binding.provider_connection_id == context.provider_connection_id
                and binding.preview_id == preview_id
                and binding.expires_at > datetime.now(UTC)
            )
        except Exception:  # noqa: BLE001 - a malformed binding must fail closed.
            return False

    async def _release_quietly(self, reservation: ExecutionGrantReservation) -> None:
        """Release a reservation without masking the primary failure."""
        try:
            await reservation.release()
        except Exception as err:  # noqa: BLE001 - release is best effort; expiry bounds it.
            logger.error(
                "Execution grant release failed for tool %s cause=%s",
                self._contract.name,
                type(err).__name__,
            )

    async def _hold_quietly(self, reservation: ExecutionGrantReservation) -> None:
        """Keep the reservation non-reusable when acceptance is unknown."""
        try:
            await reservation.hold_for_reconciliation()
            logger.warning(
                "Execution grant held for reconciliation for tool %s",
                self._contract.name,
            )
        except Exception as err:  # noqa: BLE001 - never mask the primary failure.
            logger.error(
                "Execution grant hold failed for tool %s cause=%s",
                self._contract.name,
                type(err).__name__,
            )

    async def _consume_after_acceptance(
        self, reservation: ExecutionGrantReservation
    ) -> None:
        """Consume the grant once the target accepted; never hide the acceptance."""
        try:
            await reservation.consume()
        except Exception as err:  # noqa: BLE001 - accepted work must still be reported.
            logger.error(
                "Execution grant consume failed for tool %s cause=%s",
                self._contract.name,
                type(err).__name__,
            )

    async def _invoke_confirmed(
        self,
        context: AuthorizationContext,
        arguments: dict[str, Any],
        reservation: ExecutionGrantReservation,
    ) -> Any:
        """Run the confirmed handler and settle the reservation by outcome.

        Success consumes; a ``PreAcceptFailure`` releases; any other failure or
        cancellation holds the reservation because acceptance is unknown.
        """
        try:
            result = self._handler(context, arguments, reservation.binding)
            if inspect.isawaitable(result):
                result = await result
        except PreAcceptFailure:
            await self._release_quietly(reservation)
            raise
        except asyncio.CancelledError:
            await asyncio.shield(self._hold_quietly(reservation))
            raise
        except Exception:
            await self._hold_quietly(reservation)
            raise
        await self._consume_after_acceptance(reservation)
        return result

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
                if self._contract.requires_confirmation:
                    reservation = await self._reserve_execution_grant(
                        context, arguments
                    )
                    result = await self._invoke_confirmed(
                        context, arguments, reservation
                    )
                else:
                    result = self._handler(context, arguments)
                    if inspect.isawaitable(result):
                        result = await result
            except ToolAuthorizationError:
                raise
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


def _check_registration(
    tool: ToolContract,
    plain: ToolHandler | None,
    confirmed: ConfirmedToolHandler | None,
) -> ToolHandler | ConfirmedToolHandler | None:
    """Return the handler for ``tool`` or raise if it was registered unsafely.

    Confirming tools accept only a binding-aware handler from
    ``confirmed_tool_handlers``; others only a plain handler. A mutating tool
    that skipped confirmation is refused outright.
    """
    if tool.side_effect in MUTATING_SIDE_EFFECTS and not tool.requires_confirmation:
        raise ValueError(f"{tool.name}: mutating tool requires confirmation")
    if tool.requires_confirmation:
        if plain is not None:
            raise ValueError(
                f"{tool.name}: confirming tools must use confirmed_tool_handlers"
            )
        return confirmed
    if confirmed is not None:
        raise ValueError(f"{tool.name} does not require confirmation")
    return plain


def build_server(
    tool_handlers: Mapping[str, ToolHandler] | None = None,
    tools: Iterable[ToolContract] | None = None,
    request_controls: RequestControls | None = None,
    execution_grants: ExecutionGrantAuthority | None = None,
    confirmed_tool_handlers: Mapping[str, ConfirmedToolHandler] | None = None,
) -> FastMCP:
    """Build the hosted MCP server from exportable, handler-bound contracts.

    Confirming tools are bound only through ``confirmed_tool_handlers``, whose
    handlers receive the server-owned ``ExecutionGrantBinding``; with no
    ``execution_grants`` authority they fail closed on every call.
    """
    server = FastMCP("ShipAgentHosted")
    handlers = tool_handlers or {}
    confirmed_handlers = confirmed_tool_handlers or {}
    for tool in exportable_tools(ProviderExport.generic_mcp, tools):
        handler = _check_registration(
            tool, handlers.get(tool.name), confirmed_handlers.get(tool.name)
        )
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
