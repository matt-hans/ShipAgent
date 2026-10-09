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
from fastmcp.server.dependencies import get_context, get_http_request
from fastmcp.tools import Tool
from fastmcp.tools.tool import ToolResult
from jsonschema import validate
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from mcp.types import Tool as MCPTool

from src.control_plane.auth.context import (
    AuthorizationContext,
    get_authorization_context,
)
from src.control_plane.auth.oauth_contract import (
    PUBLIC_SCOPES,
    validate_resource_metadata_url,
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
GRANT_SETTLEMENT_TIMEOUT_SECONDS = 5.0


class _OAuthErrorResult(ToolResult):
    """Serialize auth failures as MCP error results without success-schema checks."""

    def to_mcp_result(self) -> CallToolResult:
        return CallToolResult(content=self.content, isError=True, _meta=self.meta)


class BoundRegistryTool(Tool):
    def __init__(
        self,
        *args: Any,
        contract: ToolContract,
        handler: ToolHandler | ConfirmedToolHandler,
        request_controls: RequestControls | None = None,
        execution_grants: ExecutionGrantAuthority | None = None,
        oauth_resource_metadata_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        if oauth_resource_metadata_url is not None:
            validate_resource_metadata_url(oauth_resource_metadata_url)
            if not set(contract.auth_scopes) <= set(PUBLIC_SCOPES):
                raise ValueError("configured MCP tools must use public OAuth scopes")
        super().__init__(*args, **kwargs)
        object.__setattr__(self, "_contract", contract)
        object.__setattr__(self, "_handler", handler)
        object.__setattr__(self, "_request_controls", request_controls)
        object.__setattr__(self, "_execution_grants", execution_grants)
        object.__setattr__(self, "_settlement_tasks", set())
        object.__setattr__(
            self, "_oauth_resource_metadata_url", oauth_resource_metadata_url
        )

    def _oauth_error(self, *, missing_context: bool = False) -> _OAuthErrorResult:
        error = "invalid_token" if missing_context else "insufficient_scope"
        description = (
            "Authentication is required"
            if missing_context
            else "Additional authorization is required"
        )
        scopes = " ".join(self._contract.auth_scopes)
        challenge = (
            f'Bearer resource_metadata="{self._oauth_resource_metadata_url}", '
            f'error="{error}", error_description="{description}", scope="{scopes}"'
        )
        return _OAuthErrorResult(
            content=[TextContent(type="text", text=description)],
            meta={"mcp/www_authenticate": [challenge]},
        )

    def to_mcp_tool(
        self, *, include_fastmcp_meta: bool | None = None, **overrides: Any
    ) -> MCPTool:
        """Preserve the registry descriptor and expose its OAuth requirements."""
        descriptor = (
            super()
            .to_mcp_tool(include_fastmcp_meta=include_fastmcp_meta, **overrides)
            .model_dump(by_alias=True, exclude_none=True)
        )
        schemes = [{"type": "oauth2", "scopes": list(self._contract.auth_scopes)}]
        descriptor["securitySchemes"] = schemes
        descriptor["_meta"] = {
            **descriptor.get("_meta", {}),
            "securitySchemes": schemes,
        }
        return MCPTool.model_validate(descriptor)

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
            message="approval could not be verified; check approval and existing execution status",
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
    ) -> tuple[ExecutionGrantReservation, ExecutionGrantBinding]:
        """Reserve the server-side grant for a confirming tool or fail closed.

        Authority comes only from the server-side grant resolved through the
        opaque Approval Request reference; model arguments and history never
        grant it. A reservation whose binding is malformed or does not exactly
        match the caller, requested preview and tool policy is released and
        rejected. Returns the reservation with the one binding that was
        validated; only that object reaches the handler. Raises only
        ``ToolAuthorizationError`` (or cancellation), never a handler error.
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
            message = "approval required before execution; check approval and existing execution status"
            if err.denial in {
                ExecutionGrantDenial.GRANT_IN_USE,
                ExecutionGrantDenial.GRANT_CONSUMED,
                ExecutionGrantDenial.RECONCILIATION_PENDING,
            }:
                message = "execution is in use or already accepted; check or recover the original job"
            raise ToolAuthorizationError(
                code=err.denial.value,
                message=message,
            ) from err
        except Exception as err:  # noqa: BLE001 - grant lookup is a fail-closed boundary.
            self._audit_denial(
                ExecutionGrantDenial.GRANT_UNAVAILABLE, cause=type(err).__name__
            )
            raise self._grant_unavailable_error() from err
        caller = asyncio.current_task()
        if caller is not None and caller.cancelling():
            # A misbehaving authority may swallow cancellation while returning
            # ownership. No handler has run, so fenced pre-dispatch release is
            # safe; never dispatch merely because reserve returned an object.
            await self._settle(reservation, "release")
            raise asyncio.CancelledError
        binding = self._validated_binding(reservation, context, preview_id)
        if binding is None:
            await self._settle(reservation, "release")
            self._audit_denial(ExecutionGrantDenial.GRANT_INVALID)
            raise self._grant_invalid_error()
        logger.info("Execution grant reserved for tool %s", self._contract.name)
        return reservation, binding

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

    def _validated_binding(
        self,
        reservation: ExecutionGrantReservation,
        context: AuthorizationContext,
        preview_id: str,
    ) -> ExecutionGrantBinding | None:
        """Read the binding once and return it only if valid for this call.

        The exact ``ExecutionGrantBinding`` type is required so a subclass cannot
        override ``validate``. Any malformed reservation or binding (missing,
        wrong type or fields, naive expiry) yields ``None`` rather than an
        exception so the caller can release it.
        """
        try:
            binding = reservation.binding
            if type(binding) is not ExecutionGrantBinding:
                return None
            binding.validate(policy=self._contract.confirmation_policy)
            if (
                binding.account_id == context.account_id
                and binding.provider_connection_id == context.provider_connection_id
                and binding.preview_id == preview_id
                and binding.expires_at > datetime.now(UTC)
            ):
                return binding
        except Exception:  # noqa: BLE001 - a malformed binding must fail closed.
            pass
        return None

    def _observe_settlement(self, task: asyncio.Task[None], operation: str) -> None:
        """Retain and observe late outcomes without logging authority payloads."""
        self._settlement_tasks.discard(task)
        cause = "CancelledError" if task.cancelled() else None
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                cause = type(error).__name__
        label = "hold" if operation == "hold_for_reconciliation" else operation
        if cause is not None:
            logger.error(
                "Execution grant %s failed for tool %s cause=%s",
                label,
                self._contract.name,
                cause,
            )
        elif operation == "hold_for_reconciliation":
            logger.warning(
                "Execution grant held for reconciliation for tool %s",
                self._contract.name,
            )

    async def _settle(
        self, reservation: ExecutionGrantReservation, operation: str
    ) -> None:
        """Bound local settlement waiting; a timeout never authorizes replay.

        Consume and its failure-to-hold fallback share one monotonic deadline.
        Caller cancellation waits only within that budget. Cancelling the local
        operation at expiry does not prove its remote write was rolled back:
        reserve must already be non-reusable, and every write must be fenced.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + GRANT_SETTLEMENT_TIMEOUT_SECONDS
        cancelled = False
        while True:

            async def invoke(action: str = operation) -> None:
                await getattr(reservation, action)()

            task = asyncio.create_task(invoke())
            self._settlement_tasks.add(task)
            task.add_done_callback(
                lambda done, action=operation: self._observe_settlement(done, action)
            )
            while not task.done():
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    await asyncio.wait([task], timeout=remaining)
                except asyncio.CancelledError:
                    cancelled = True
            if not task.done():
                logger.error(
                    "Execution grant settlement deadline exceeded for tool %s operation=%s",
                    self._contract.name,
                    operation,
                )
                task.cancel()
                break
            failed = task.cancelled() or task.exception() is not None
            if not failed or operation != "consume" or loop.time() >= deadline:
                break
            operation = "hold_for_reconciliation"
        if cancelled:
            raise asyncio.CancelledError

    async def _invoke_confirmed(
        self,
        context: AuthorizationContext,
        arguments: dict[str, Any],
        reservation: ExecutionGrantReservation,
        binding: ExecutionGrantBinding,
    ) -> Any:
        """Run the confirmed handler and settle the reservation by outcome.

        Success consumes; a ``PreAcceptFailure`` releases; any other failure or
        cancellation holds the reservation because acceptance is unknown. Every
        settlement path has one bounded deadline; cancellation never releases
        possibly accepted work.
        """
        try:
            result = self._handler(context, arguments, binding)
            if inspect.isawaitable(result):
                result = await result
        except PreAcceptFailure:
            await self._settle(reservation, "release")
            raise
        except BaseException:
            await self._settle(reservation, "hold_for_reconciliation")
            raise
        await self._settle(reservation, "consume")
        return result

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            request = get_http_request()
        except RuntimeError:
            # A configured HTTP server must prove the current request even if
            # transport metadata has gone missing. Only legacy non-HTTP callers
            # may explicitly authorize through the in-process context seam.
            context = (
                get_authorization_context()
                if self._oauth_resource_metadata_url is None
                else None
            )
        else:
            # get_http_request has an initialization-time HTTP ContextVar fallback.
            # Only the SDK's current message metadata proves this is the request
            # being authorized, rather than an inherited transport request.
            try:
                message_context = get_context().request_context
            except RuntimeError:
                message_context = None
            context = (
                getattr(request.state, "authorization", None)
                if message_context is not None and message_context.request is request
                else None
            )
            if not isinstance(context, AuthorizationContext):
                context = None
        if context is None:
            if self._oauth_resource_metadata_url is not None:
                return self._oauth_error(missing_context=True)
            raise self._context_missing_error()

        missing = set(self._contract.auth_scopes) - context.scopes
        if missing:
            if self._oauth_resource_metadata_url is not None:
                return self._oauth_error()
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
                        **(
                            {"call_repetition": self._contract.call_repetition}
                            if self._contract.call_repetition != "guarded"
                            else {}
                        ),
                    )
                except RequestControlError as err:
                    raise self._loop_guard_or_rate_limit_error(err) from err

            # Gate denials raise ToolAuthorizationError and pass through; handler
            # errors never do, so a handler cannot forge a gate-specific error.
            reservation = None
            if self._contract.requires_confirmation:
                reservation, binding = await self._reserve_execution_grant(
                    context, arguments
                )
            try:
                if reservation is not None:
                    result = await self._invoke_confirmed(
                        context, arguments, reservation, binding
                    )
                else:
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
    oauth_resource_metadata_url: str | None = None,
) -> FastMCP:
    """Build the hosted MCP server from exportable, handler-bound contracts.

    Confirming tools are bound only through ``confirmed_tool_handlers``, whose
    handlers receive the server-owned ``ExecutionGrantBinding``; with no
    ``execution_grants`` authority they fail closed on every call.
    """
    if oauth_resource_metadata_url is not None:
        validate_resource_metadata_url(oauth_resource_metadata_url)
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
                oauth_resource_metadata_url=oauth_resource_metadata_url,
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
