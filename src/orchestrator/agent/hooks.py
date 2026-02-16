"""Hook implementations for Claude Agent SDK integration.

This module provides PreToolUse and PostToolUse hooks for validation and logging
that integrate with the Claude Agent SDK's hook system.

Hooks follow these principles (per CONTEXT.md Decision 3):
- Pre-hooks validate schema and business rules
- Post-hooks check responses for errors and log all executions
- Hooks can reject but never modify inputs or outputs (validate only)
- All logging goes to stderr (stdout is reserved for MCP protocol)

Usage:
    from src.orchestrator.agent.hooks import create_hook_matchers

    # In ClaudeAgentOptions configuration:
    options = ClaudeAgentOptions(
        hooks=create_hook_matchers()
    )
"""

from __future__ import annotations

import sys
import logging
from datetime import datetime, timezone
from typing import Any

from claude_agent_sdk import HookMatcher


__all__ = [
    "validate_pre_tool",
    "validate_shipping_input",
    "validate_void_shipment",
    "validate_data_query",
    "log_post_tool",
    "detect_error_response",
    "create_hook_matchers",
    "create_shipping_hook",
    "validate_schedule_pickup",
    "validate_cancel_pickup",
]

logger = logging.getLogger(__name__)


# =============================================================================
# Pre-Tool Validation Hooks
# =============================================================================


async def validate_shipping_input(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Validate tool_input is a well-formed dict for create_shipment.

    Business-field validation (shipper, shipTo, packages, etc.) is delegated
    to UPS MCP preflight, which returns structured ToolError payloads with
    a ``missing`` array when required fields are absent. This hook only
    guards against structurally invalid inputs (non-dict types).

    Args:
        input_data: Contains 'tool_name' and 'tool_input' keys
        tool_use_id: Unique identifier for this tool use
        context: Hook context from Claude Agent SDK

    Returns:
        Empty dict to allow, or hookSpecificOutput with denial to block
    """
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Log validation attempt to stderr
    _log_to_stderr(f"[VALIDATION] Pre-hook checking: {tool_name} | ID: {tool_use_id}")

    # Validate create_shipment tool (mcp__ups__create_shipment)
    if "create_shipment" in tool_name:
        # Only deny when tool_input is not a dict (e.g. None, str, list).
        # Empty dicts and partial payloads are allowed — MCP preflight
        # handles missing-field validation and returns actionable errors.
        if not isinstance(tool_input, dict):
            return _deny_with_reason(
                "Invalid tool_input: expected a dict, "
                f"got {type(tool_input).__name__}."
            )

    return {}  # Allow operation


async def validate_void_shipment(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Validate UPS void_shipment tool inputs before execution.

    Validates:
    - For `void_shipment`: Require a tracking number or shipment ID
    - Return denial with clear reason if missing
    - Return empty dict `{}` to allow operation

    Args:
        input_data: Contains 'tool_name' and 'tool_input' keys
        tool_use_id: Unique identifier for this tool use
        context: Hook context from Claude Agent SDK

    Returns:
        Empty dict to allow, or hookSpecificOutput with denial to block
    """
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    _log_to_stderr(f"[VALIDATION] Pre-hook checking: {tool_name} | ID: {tool_use_id}")

    if "void_shipment" in tool_name:
        # Check for tracking number / shipment identification number
        tracking = (
            tool_input.get("trackingNumber")
            or tool_input.get("ShipmentIdentificationNumber")
            or tool_input.get("shipmentIdentificationNumber")
        )
        if not tracking:
            return _deny_with_reason(
                "Missing required shipment identifier. "
                "The 'trackingNumber' or 'ShipmentIdentificationNumber' field is required to void a shipment."
            )

    return {}  # Allow operation


async def validate_data_query(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Validate data query tool inputs before execution.

    For `query_data`: Warns if no WHERE clause on large data (informational only).
    Does not block operations - just provides helpful warnings.

    Args:
        input_data: Contains 'tool_name' and 'tool_input' keys
        tool_use_id: Unique identifier for this tool use
        context: Hook context from Claude Agent SDK

    Returns:
        Empty dict (informational warnings only, does not block)
    """
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Log validation attempt to stderr
    _log_to_stderr(f"[VALIDATION] Pre-hook checking: {tool_name} | ID: {tool_use_id}")

    # Warn about queries without WHERE clause
    if "query_data" in tool_name:
        sql_query = tool_input.get("query", "").upper()
        if "SELECT" in sql_query and "WHERE" not in sql_query:
            _log_to_stderr(
                f"[WARNING] Query without WHERE clause may return large result set: "
                f"{tool_input.get('query', '')[:100]}..."
            )

    # Check for potentially dangerous operations (informational warning)
    if "query_data" in tool_name:
        sql_query = tool_input.get("query", "").upper()
        dangerous_keywords = ["DROP", "DELETE", "TRUNCATE", "ALTER", "INSERT", "UPDATE"]
        for keyword in dangerous_keywords:
            if keyword in sql_query:
                _log_to_stderr(
                    f"[WARNING] Query contains potentially dangerous keyword: {keyword}"
                )
                break

    return {}  # Allow operation (warnings only)


async def validate_pre_tool(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Generic pre-validation entry point for all tool calls.

    Routes to specific validators based on tool_name substring:
    - create_shipment -> validate_shipping_input
    - void_shipment -> validate_void_shipment
    - query_data -> validate_data_query

    This is the default pre-hook for all tools when specific
    matchers are not provided.

    Args:
        input_data: Contains 'tool_name' and 'tool_input' keys
        tool_use_id: Unique identifier for this tool use
        context: Hook context from Claude Agent SDK

    Returns:
        Empty dict to allow, or hookSpecificOutput with denial to block
    """
    tool_name = input_data.get("tool_name", "")

    # Log validation attempt to stderr
    _log_to_stderr(f"[VALIDATION] Pre-hook (generic): {tool_name} | ID: {tool_use_id}")

    # Route to specific validators based on tool name
    if "create_shipment" in tool_name:
        return await validate_shipping_input(input_data, tool_use_id, context)
    elif "void_shipment" in tool_name:
        return await validate_void_shipment(input_data, tool_use_id, context)
    elif "query_data" in tool_name:
        return await validate_data_query(input_data, tool_use_id, context)

    # Default: allow all other tools
    return {}


# =============================================================================
# Post-Tool Logging Hooks
# =============================================================================


async def log_post_tool(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Log all tool executions for audit trail.

    Logs to stderr with: tool_name, tool_use_id, success status.
    Post-hooks never modify the flow - they return empty dict.

    Args:
        input_data: Contains 'tool_name' and 'tool_response' keys
        tool_use_id: Unique identifier for this tool use
        context: Hook context from Claude Agent SDK

    Returns:
        Empty dict (post-hooks don't modify flow)
    """
    tool_name = input_data.get("tool_name", "")
    tool_response = input_data.get("tool_response")

    # Determine success/failure
    is_error = _is_error_response(tool_response)
    success_status = "FAILURE" if is_error else "SUCCESS"

    # Log to stderr (never stdout - that's MCP protocol)
    timestamp = datetime.now(timezone.utc).isoformat()
    _log_to_stderr(
        f"[AUDIT] {timestamp} | Tool: {tool_name} | ID: {tool_use_id} | "
        f"Status: {success_status}"
    )

    return {}


async def detect_error_response(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Detect error indicators in tool responses.

    Checks tool_response for common error indicators:
    - Dict with "error" or "isError" keys
    - String responses containing "error" patterns
    - HTTP error status patterns

    Logs warnings for detected errors but does not block
    (informational only, post-hooks cannot block).

    Args:
        input_data: Contains 'tool_name' and 'tool_response' keys
        tool_use_id: Unique identifier for this tool use
        context: Hook context from Claude Agent SDK

    Returns:
        Empty dict (informational only)
    """
    tool_name = input_data.get("tool_name", "")
    tool_response = input_data.get("tool_response")

    if _is_error_response(tool_response):
        error_detail = _extract_error_detail(tool_response)
        _log_to_stderr(
            f"[ERROR DETECTED] Tool: {tool_name} | ID: {tool_use_id} | "
            f"Error: {error_detail}"
        )

    return {}


# =============================================================================
# Helper Functions
# =============================================================================


def _is_error_response(response: Any) -> bool:
    """Check if a tool response indicates an error.

    Handles:
    - Dict responses with "error", "isError", or "is_error" keys
    - String responses containing "error" patterns
    - None responses (considered success)

    Args:
        response: The tool response to check

    Returns:
        True if response indicates an error, False otherwise
    """
    if response is None:
        return False

    if isinstance(response, dict):
        # Check for explicit error keys
        if response.get("error"):
            return True
        if response.get("isError") is True:
            return True
        if response.get("is_error") is True:
            return True
        # Check for HTTP-style error status
        status = response.get("status") or response.get("statusCode")
        if isinstance(status, int) and status >= 400:
            return True

    if isinstance(response, str):
        response_lower = response.lower()
        # Check for common error patterns
        if "error:" in response_lower or '"error"' in response_lower:
            return True
        if "failed" in response_lower and "validation failed" not in response_lower:
            return True

    return False


def _extract_error_detail(response: Any) -> str:
    """Extract error detail from a response for logging.

    Args:
        response: The tool response containing an error

    Returns:
        A string describing the error (truncated if long)
    """
    max_length = 200

    if isinstance(response, dict):
        error = response.get("error")
        if isinstance(error, str):
            return error[:max_length] if len(error) > max_length else error
        if isinstance(error, dict):
            message = error.get("message", str(error))
            return message[:max_length] if len(message) > max_length else message
        # Try other common error fields
        for key in ["message", "errorMessage", "error_message", "detail"]:
            if key in response:
                msg = str(response[key])
                return msg[:max_length] if len(msg) > max_length else msg

    if isinstance(response, str):
        return response[:max_length] if len(response) > max_length else response

    return str(response)[:max_length]


def _deny_with_reason(reason: str) -> dict[str, Any]:
    """Create a denial response for pre-tool hooks.

    Args:
        reason: Human-readable explanation of why the tool call was denied

    Returns:
        Hook output dict with permissionDecision: "deny"
    """
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _log_to_stderr(message: str) -> None:
    """Log a message to stderr (never stdout - that's MCP protocol).

    Args:
        message: The message to log
    """
    try:
        print(message, file=sys.stderr)
    except (BrokenPipeError, OSError):
        # In daemonized/reloaded environments stderr may be closed; logging
        # should never break hook execution.
        if "[VALIDATION]" in message or "[ERROR" in message:
            logger.warning("stderr unavailable, hook message: %s", message)
        else:
            logger.debug("Dropped stderr hook log: %s", message)


async def validate_schedule_pickup(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Deny direct MCP schedule_pickup calls — force orchestrator wrapper.

    Scheduling a pickup is a financial commitment.  The orchestrator
    wrapper ``schedule_pickup_tool`` enforces a ``confirmed=True`` gate
    that the direct MCP tool cannot.  This hook deterministically denies
    the direct path so the agent is forced through the safe wrapper.

    Args:
        input_data: Contains 'tool_name' and 'tool_input' keys.
        tool_use_id: Unique identifier for this tool use.
        context: Hook context from Claude Agent SDK.

    Returns:
        hookSpecificOutput with denial.
    """
    _log_to_stderr(
        f"[VALIDATION] Pre-hook DENYING direct schedule_pickup | ID: {tool_use_id}"
    )
    return _deny_with_reason(
        "Direct mcp__ups__schedule_pickup is not allowed. "
        "Use the schedule_pickup orchestrator tool instead, which enforces "
        "user confirmation before committing."
    )


async def validate_cancel_pickup(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Deny direct MCP cancel_pickup calls — force orchestrator wrapper.

    Cancelling a pickup is irreversible.  The orchestrator wrapper
    ``cancel_pickup_tool`` enforces a ``confirmed=True`` gate.

    Args:
        input_data: Contains 'tool_name' and 'tool_input' keys.
        tool_use_id: Unique identifier for this tool use.
        context: Hook context from Claude Agent SDK.

    Returns:
        hookSpecificOutput with denial.
    """
    _log_to_stderr(
        f"[VALIDATION] Pre-hook DENYING direct cancel_pickup | ID: {tool_use_id}"
    )
    return _deny_with_reason(
        "Direct mcp__ups__cancel_pickup is not allowed. "
        "Use the cancel_pickup orchestrator tool instead, which enforces "
        "user confirmation before committing."
    )


# =============================================================================
# Hook Factory — Instance-Scoped Enforcement
# =============================================================================


def create_shipping_hook(
    interactive_shipping: bool = False,
):
    """Factory that creates a create_shipment pre-hook with mode enforcement.

    Deterministically denies ``mcp__ups__create_shipment`` in **both** modes:
    - interactive_shipping=False → directs user to batch processing.
    - interactive_shipping=True  → directs agent to ``preview_interactive_shipment``.

    All other tool calls pass through unmodified.

    Args:
        interactive_shipping: Whether interactive single-shipment mode is enabled.

    Returns:
        Async hook function with interactive_shipping captured via closure.
    """

    async def _validate_shipping(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        """Validate create_shipment with mode-aware enforcement."""
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        _log_to_stderr(
            f"[VALIDATION] Pre-hook checking: {tool_name} | ID: {tool_use_id} | "
            f"interactive={interactive_shipping}"
        )

        if "create_shipment" in tool_name:
            if not interactive_shipping:
                return _deny_with_reason(
                    "Interactive shipping is disabled. "
                    "Use batch processing for shipment creation."
                )
            else:
                return _deny_with_reason(
                    "Direct shipment creation is not allowed in interactive mode. "
                    "Use the preview_interactive_shipment tool instead."
                )

        return {}

    return _validate_shipping


# =============================================================================
# Hook Matcher Factory
# =============================================================================


def create_hook_matchers(
    interactive_shipping: bool = False,
) -> dict[str, list[HookMatcher]]:
    """Create hook matchers with mode-aware enforcement.

    Returns a dict structure ready for ClaudeAgentOptions(hooks=...).
    Uses HookMatcher dataclass instances as required by the Claude Agent SDK.

    The create_shipment pre-hook is produced by ``create_shipping_hook()``
    so the ``interactive_shipping`` flag is captured per-instance via closure,
    avoiding global mutable state.

    Args:
        interactive_shipping: Whether interactive single-shipment mode is enabled.

    Returns:
        Dict with PreToolUse and PostToolUse hook configurations.
    """
    shipping_hook = create_shipping_hook(interactive_shipping=interactive_shipping)

    return {
        "PreToolUse": [
            HookMatcher(
                matcher="mcp__ups__create_shipment",
                hooks=[shipping_hook],
            ),
            HookMatcher(
                matcher="mcp__ups__void_shipment",
                hooks=[validate_void_shipment],
            ),
            HookMatcher(
                matcher="mcp__ups__schedule_pickup",
                hooks=[validate_schedule_pickup],
            ),
            HookMatcher(
                matcher="mcp__ups__cancel_pickup",
                hooks=[validate_cancel_pickup],
            ),
            HookMatcher(
                matcher=None,
                hooks=[validate_pre_tool],
            ),
        ],
        "PostToolUse": [
            HookMatcher(
                matcher=None,
                hooks=[log_post_tool, detect_error_response],
            ),
        ],
    }
