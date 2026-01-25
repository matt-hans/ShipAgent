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
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Avoid import errors if SDK not installed yet
    pass


__all__ = [
    "validate_pre_tool",
    "validate_shipping_input",
    "validate_data_query",
    "log_post_tool",
    "detect_error_response",
    "create_hook_matchers",
]


# =============================================================================
# Pre-Tool Validation Hooks
# =============================================================================


async def validate_shipping_input(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Validate UPS shipping tool inputs before execution.

    Validates:
    - For `shipping_create`: Require shipper and shipTo fields
    - Return denial with clear reason if missing required fields
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

    # Log validation attempt to stderr
    _log_to_stderr(f"[VALIDATION] Pre-hook checking: {tool_name} | ID: {tool_use_id}")

    # Validate shipping_create tool
    if "shipping_create" in tool_name:
        # Check for required shipper information
        if not tool_input.get("shipper"):
            return _deny_with_reason(
                "Missing required shipper information. "
                "The 'shipper' field must include name and address details."
            )

        # Check for required shipTo information
        if not tool_input.get("shipTo"):
            return _deny_with_reason(
                "Missing required recipient information. "
                "The 'shipTo' field must include name and address details."
            )

        # Validate shipper has minimum required fields
        shipper = tool_input.get("shipper", {})
        if not shipper.get("name"):
            return _deny_with_reason(
                "Missing shipper name. The 'shipper.name' field is required."
            )
        if not shipper.get("address"):
            return _deny_with_reason(
                "Missing shipper address. The 'shipper.address' field is required."
            )

        # Validate shipTo has minimum required fields
        ship_to = tool_input.get("shipTo", {})
        if not ship_to.get("name"):
            return _deny_with_reason(
                "Missing recipient name. The 'shipTo.name' field is required."
            )
        if not ship_to.get("address"):
            return _deny_with_reason(
                "Missing recipient address. The 'shipTo.address' field is required."
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

    Routes to specific validators based on tool_name prefix:
    - mcp__ups__shipping_* -> validate_shipping_input
    - mcp__data__query_* -> validate_data_query

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
    if "shipping_create" in tool_name:
        return await validate_shipping_input(input_data, tool_use_id, context)
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
    print(message, file=sys.stderr)


# =============================================================================
# Hook Matcher Factory
# =============================================================================


def create_hook_matchers() -> dict[str, list[dict[str, Any]]]:
    """Create hook matchers for ClaudeAgentOptions.hooks configuration.

    Returns a dict structure ready for ClaudeAgentOptions(hooks=create_hook_matchers()).

    Structure:
        {
            "PreToolUse": [
                {"matcher": "mcp__ups__shipping", "hooks": [validate_shipping_input]},
                {"matcher": None, "hooks": [validate_pre_tool]}  # All tools
            ],
            "PostToolUse": [
                {"matcher": None, "hooks": [log_post_tool, detect_error_response]}
            ]
        }

    Matchers:
        - matcher=None means "all tools"
        - matcher="mcp__ups__shipping" means "tools starting with that prefix"

    Returns:
        Dict with PreToolUse and PostToolUse hook configurations
    """
    return {
        "PreToolUse": [
            # Specific validation for UPS shipping tools
            {
                "matcher": "mcp__ups__shipping",
                "hooks": [validate_shipping_input],
                "description": "Validates shipper and shipTo fields for shipping operations",
            },
            # Specific validation for data query tools
            {
                "matcher": "mcp__data__query",
                "hooks": [validate_data_query],
                "description": "Warns about queries without WHERE clause",
            },
            # Generic validation for all tools (fallback)
            {
                "matcher": None,
                "hooks": [validate_pre_tool],
                "description": "Generic pre-validation for all tools",
            },
        ],
        "PostToolUse": [
            # Audit logging and error detection for all tools
            {
                "matcher": None,
                "hooks": [log_post_tool, detect_error_response],
                "description": "Logs all tool executions and detects errors",
            },
        ],
    }
