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

import base64
import hashlib
import hmac as hmac_mod
import json
import os
import sys
import logging
import time
from datetime import datetime, timezone
from typing import Any

try:
    from claude_agent_sdk import HookMatcher
except ModuleNotFoundError as exc:
    if exc.name != "claude_agent_sdk":
        raise

    class HookMatcher:  # type: ignore[no-redef]
        """Fallback stub when claude_agent_sdk is unavailable."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ModuleNotFoundError(
                "No module named 'claude_agent_sdk'. "
                "Start backend with ./scripts/start-backend.sh (project .venv), "
                "or install deps via .venv/bin/python -m pip install -e '.[dev]'."
            ) from exc


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
    "validate_track_package",
    "validate_find_locations",
    "validate_get_service_center_facilities",
    "validate_landed_cost_quote",
    "deny_raw_sql_in_filter_tools",
    "validate_intent_on_resolve",
    "validate_filter_spec_on_pipeline",
]

logger = logging.getLogger(__name__)


def _determinism_mode() -> str:
    """Return determinism enforcement mode ('warn' or 'enforce')."""
    raw = os.environ.get("DETERMINISM_ENFORCEMENT_MODE", "warn").strip().lower()
    return "enforce" if raw == "enforce" else "warn"


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


async def validate_track_package(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Deny direct MCP track_package calls — force orchestrator wrapper.

    The orchestrator wrapper ``track_package_tool`` emits a
    ``tracking_result`` event for the frontend TrackingCard and
    performs mismatch detection. The direct MCP tool bypasses
    both of these.

    Args:
        input_data: Contains 'tool_name' and 'tool_input' keys.
        tool_use_id: Unique identifier for this tool use.
        context: Hook context from Claude Agent SDK.

    Returns:
        hookSpecificOutput with denial.
    """
    _log_to_stderr(
        f"[VALIDATION] Pre-hook DENYING direct track_package | ID: {tool_use_id}"
    )
    return _deny_with_reason(
        "Direct mcp__ups__track_package is not allowed. "
        "Use the track_package orchestrator tool instead, which emits "
        "tracking result events for the UI."
    )


async def validate_find_locations(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Deny direct MCP find_locations calls — force orchestrator wrapper.

    The orchestrator wrapper ``find_locations_tool`` emits a
    ``location_result`` event for the frontend LocationCard.
    Direct MCP calls bypass that event path and fall back to plain text.

    Args:
        input_data: Contains 'tool_name' and 'tool_input' keys.
        tool_use_id: Unique identifier for this tool use.
        context: Hook context from Claude Agent SDK.

    Returns:
        hookSpecificOutput with denial.
    """
    _log_to_stderr(
        f"[VALIDATION] Pre-hook DENYING direct find_locations | ID: {tool_use_id}"
    )
    return _deny_with_reason(
        "Direct mcp__ups__find_locations is not allowed. "
        "Use the find_locations orchestrator tool instead, which emits "
        "location result events for the UI."
    )


async def validate_get_service_center_facilities(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Deny direct MCP get_service_center_facilities calls.

    Forces usage through the orchestrator wrapper so the frontend receives
    ``location_result`` events and renders the LocationCard.

    Args:
        input_data: Contains 'tool_name' and 'tool_input' keys.
        tool_use_id: Unique identifier for this tool use.
        context: Hook context from Claude Agent SDK.

    Returns:
        hookSpecificOutput with denial.
    """
    _log_to_stderr(
        "[VALIDATION] Pre-hook DENYING direct get_service_center_facilities "
        f"| ID: {tool_use_id}"
    )
    return _deny_with_reason(
        "Direct mcp__ups__get_service_center_facilities is not allowed. "
        "Use the get_service_center_facilities orchestrator tool instead, "
        "which emits location result events for the UI."
    )


async def validate_landed_cost_quote(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Deny direct MCP landed-cost calls — force orchestrator wrapper.

    The orchestrator wrapper ``get_landed_cost_tool`` emits a
    ``landed_cost_result`` event for the frontend LandedCostCard.
    Direct MCP calls bypass that event path and degrade to plain text.

    Args:
        input_data: Contains 'tool_name' and 'tool_input' keys.
        tool_use_id: Unique identifier for this tool use.
        context: Hook context from Claude Agent SDK.

    Returns:
        hookSpecificOutput with denial.
    """
    _log_to_stderr(
        f"[VALIDATION] Pre-hook DENYING direct landed_cost_quote | ID: {tool_use_id}"
    )
    return _deny_with_reason(
        "Direct mcp__ups__get_landed_cost_quote is not allowed. "
        "Use the get_landed_cost orchestrator tool instead, which emits "
        "landed cost result events for the UI."
    )


# =============================================================================
# Filter Enforcement Hooks
# =============================================================================

# Tools subject to filter enforcement
_FILTER_SCOPED_TOOLS = frozenset({
    "resolve_filter_intent",
    "ship_command_pipeline",
    "fetch_rows",
})

# Banned keys that indicate raw SQL injection attempts
_BANNED_SQL_KEYS = frozenset({"where_clause", "sql", "query", "raw_sql"})


def _find_banned_keys_recursive(obj: Any, banned: frozenset[str]) -> set[str]:
    """Recursively search dicts/lists for banned key names.

    Args:
        obj: The object to traverse (dict, list, or scalar).
        banned: Set of banned key names.

    Returns:
        Set of banned keys found at any nesting depth.
    """
    found: set[str] = set()
    if isinstance(obj, dict):
        found.update(banned & set(obj.keys()))
        for value in obj.values():
            found.update(_find_banned_keys_recursive(value, banned))
    elif isinstance(obj, list):
        for item in obj:
            found.update(_find_banned_keys_recursive(item, banned))
    return found


async def deny_raw_sql_in_filter_tools(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Deny raw SQL keys in filter-related tool payloads.

    Scoped to: resolve_filter_intent, ship_command_pipeline, fetch_rows.
    Recursively inspects payload for banned keys: where_clause, sql, query, raw_sql.

    Args:
        input_data: Contains 'tool_name' and 'tool_input' keys.
        tool_use_id: Unique identifier for this tool use.
        context: Hook context from Claude Agent SDK.

    Returns:
        Empty dict to allow, or hookSpecificOutput with denial to block.
    """
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Only enforce on filter-scoped tools
    if tool_name not in _FILTER_SCOPED_TOOLS:
        return {}

    if not isinstance(tool_input, dict):
        return {}

    found_keys = _find_banned_keys_recursive(tool_input, _BANNED_SQL_KEYS)
    if found_keys:
        _log_to_stderr(
            f"[FILTER ENFORCEMENT] DENYING raw SQL keys {found_keys} "
            f"in {tool_name} | ID: {tool_use_id}"
        )
        return _deny_with_reason(
            f"Raw SQL keys {sorted(found_keys)} are not allowed in {tool_name}. "
            "Use resolve_filter_intent to create a filter_spec instead."
        )

    return {}


async def validate_intent_on_resolve(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Validate FilterIntent structure before resolution.

    Performs lightweight structural checks on the intent payload before
    the resolver processes it. Catches invalid operators early.

    Args:
        input_data: Contains 'tool_name' and 'tool_input' keys.
        tool_use_id: Unique identifier for this tool use.
        context: Hook context from Claude Agent SDK.

    Returns:
        Empty dict to allow, or hookSpecificOutput with denial to block.
    """
    tool_name = input_data.get("tool_name", "")
    if tool_name != "resolve_filter_intent":
        return {}

    tool_input = input_data.get("tool_input", {})
    intent = tool_input.get("intent")
    if not isinstance(intent, dict):
        return {}

    # Validate operators in conditions recursively
    from src.orchestrator.models.filter_spec import FilterOperator
    valid_ops = {op.value for op in FilterOperator}

    def _check_node(node: Any) -> str | None:
        """Check a node for invalid operators. Returns error or None."""
        if not isinstance(node, dict):
            return None
        # It's a condition if it has "operator"
        if "operator" in node:
            op = node["operator"]
            if op not in valid_ops:
                return f"Invalid operator {op!r}. Valid: {sorted(valid_ops)}."
        # It's a group if it has "conditions"
        if "conditions" in node and isinstance(node["conditions"], list):
            for child in node["conditions"]:
                err = _check_node(child)
                if err:
                    return err
        return None

    root = intent.get("root")
    if root:
        err = _check_node(root)
        if err:
            _log_to_stderr(
                f"[FILTER ENFORCEMENT] DENYING invalid intent: {err} | ID: {tool_use_id}"
            )
            return _deny_with_reason(f"FilterIntent validation failed: {err}")

    return {}


async def validate_filter_spec_on_pipeline(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Validate filter_spec structure and Tier-B token on pipeline/fetch_rows.

    Enforcement checklist (all must pass or deny):
    1. If all_rows=true and no filter_spec, allow.
    2. If filter_spec has status NEEDS_CONFIRMATION:
       a. resolution_token MUST be present
       b. HMAC signature is valid (not tampered)
       c. Token TTL has not expired
       d. Token schema_signature matches filter_spec
       e. Token dict_version matches filter_spec
       f. Token resolved_spec_hash matches SHA-256 of incoming root

    Args:
        input_data: Contains 'tool_name' and 'tool_input' keys.
        tool_use_id: Unique identifier for this tool use.
        context: Hook context from Claude Agent SDK.

    Returns:
        Empty dict to allow, or hookSpecificOutput with denial to block.
    """
    tool_name = input_data.get("tool_name", "")
    if tool_name not in ("ship_command_pipeline", "fetch_rows"):
        return {}

    tool_input = input_data.get("tool_input", {})

    # all_rows path — no filter_spec validation needed
    if tool_input.get("all_rows"):
        return {}

    filter_spec = tool_input.get("filter_spec")
    if not isinstance(filter_spec, dict):
        return {}

    # Enforce resolution_token for ALL filter_specs regardless of status.
    # A client could flip status from NEEDS_CONFIRMATION to RESOLVED to bypass
    # validation. The token is the server-side proof of provenance.
    token = filter_spec.get("resolution_token")
    if not token:
        _log_to_stderr(
            f"[FILTER ENFORCEMENT] DENYING missing resolution_token "
            f"for filter_spec | ID: {tool_use_id}"
        )
        return _deny_with_reason(
            "All filter_spec submissions require a resolution_token proving "
            "server-side provenance. Use resolve_filter_intent first."
        )

    def _deny_token(reason: str, message: str) -> dict[str, Any]:
        logger.warning(
            "metric=token_validation_failure_total reason=%s tool=%s",
            reason,
            tool_name,
        )
        return _deny_with_reason(message)

    secret = os.environ.get("FILTER_TOKEN_SECRET", "")
    if not secret:
        return _deny_token(
            "secret_missing",
            "FILTER_TOKEN_SECRET is not configured. Cannot validate resolution token."
        )

    try:
        decoded = json.loads(base64.urlsafe_b64decode(token))
    except (json.JSONDecodeError, ValueError):
        return _deny_token(
            "token_malformed",
            "Resolution token is malformed (invalid base64/JSON).",
        )

    # Check expiry
    if time.time() > decoded.get("expires_at", 0):
        _log_to_stderr(
            f"[FILTER ENFORCEMENT] DENYING expired token | ID: {tool_use_id}"
        )
        return _deny_token(
            "token_expired",
            "Resolution token has expired. Re-resolve the filter.",
        )

    # Verify HMAC signature
    signature = decoded.pop("signature", None)
    if signature is None:
        return _deny_token(
            "signature_missing",
            "Resolution token missing HMAC signature.",
        )

    payload_json = json.dumps(decoded, sort_keys=True)
    expected_sig = hmac_mod.new(
        secret.encode(), payload_json.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac_mod.compare_digest(signature, expected_sig):
        _log_to_stderr(
            f"[FILTER ENFORCEMENT] DENYING tampered token | ID: {tool_use_id}"
        )
        return _deny_token(
            "signature_invalid",
            "Resolution token HMAC signature is invalid (tampered).",
        )

    # Check schema_signature binding
    if decoded.get("schema_signature") != filter_spec.get("schema_signature"):
        return _deny_token(
            "schema_signature_mismatch",
            "Resolution token schema_signature does not match filter_spec. "
            "The data source may have changed."
        )

    # Check dict_version binding
    if decoded.get("canonical_dict_version") != filter_spec.get("canonical_dict_version"):
        return _deny_token(
            "dict_version_mismatch",
            "Resolution token dict_version does not match filter_spec. "
            "Canonical dictionaries may have been updated."
        )

    # Check resolved_spec_hash binding.
    # IMPORTANT: use the same serializer that the resolver uses
    # (FilterGroup.model_dump_json()) so key ordering is identical.
    # json.dumps(sort_keys=True) produces a different string than Pydantic's
    # model_dump_json() because their key orderings differ, causing a permanent
    # hash mismatch that denies every filter_spec that went through resolve_filter_intent.
    root = filter_spec.get("root", {})
    try:
        from src.orchestrator.models.filter_spec import FilterGroup as _FilterGroup
        root_json = _FilterGroup(**root).model_dump_json()
    except Exception:
        # Fallback: if the root dict cannot be parsed back into a FilterGroup
        # (malformed payload), treat it as a tamper attempt.
        return _deny_token(
            "spec_hash_malformed",
            "Resolution token spec hash could not be computed: filter_spec root is malformed.",
        )
    actual_hash = hashlib.sha256(root_json.encode()).hexdigest()
    if decoded.get("resolved_spec_hash") != actual_hash:
        return _deny_token(
            "spec_hash_mismatch",
            "Resolution token spec hash does not match the filter_spec root. "
            "The filter may have been modified after resolution."
        )

    mode = _determinism_mode()
    # Transition-safe checks for new deterministic binding fields.
    for key in (
        "source_fingerprint",
        "compiler_version",
        "mapping_version",
        "normalizer_version",
    ):
        token_val = str(decoded.get(key, "") or "")
        spec_val = str(filter_spec.get(key, "") or "")
        if not token_val or not spec_val:
            logger.warning(
                "metric=token_binding_missing_total field=%s tool=%s mode=%s",
                key,
                tool_name,
                mode,
            )
            if mode == "enforce":
                return _deny_token(
                    f"{key}_missing",
                    f"Resolution token/filter_spec missing required binding field "
                    f"'{key}'. Re-run resolve_filter_intent.",
                )
            continue
        if token_val != spec_val:
            return _deny_token(
                f"{key}_mismatch",
                f"Resolution token field '{key}' does not match filter_spec.",
            )

    # Check resolution_status — token must prove RESOLVED status.
    # A NEEDS_CONFIRMATION token cannot be used to execute; the agent must
    # go through confirm → re-resolve to get a RESOLVED token.
    token_status = decoded.get("resolution_status", "")
    if token_status != "RESOLVED":
        _log_to_stderr(
            f"[FILTER ENFORCEMENT] DENYING non-RESOLVED token (status={token_status}) "
            f"| ID: {tool_use_id}"
        )
        return _deny_token(
            "status_not_resolved",
            f"Resolution token has status '{token_status}', not 'RESOLVED'. "
            "Tier-B filters require user confirmation before execution. "
            "Use confirm_filter_interpretation then re-resolve."
        )

    return {}


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
            # Filter enforcement hooks — deny_raw_sql first (ordering invariant)
            HookMatcher(
                matcher="resolve_filter_intent",
                hooks=[deny_raw_sql_in_filter_tools, validate_intent_on_resolve],
            ),
            HookMatcher(
                matcher="ship_command_pipeline",
                hooks=[deny_raw_sql_in_filter_tools, validate_filter_spec_on_pipeline],
            ),
            HookMatcher(
                matcher="fetch_rows",
                hooks=[deny_raw_sql_in_filter_tools, validate_filter_spec_on_pipeline],
            ),
            # UPS safety hooks
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
                matcher="mcp__ups__track_package",
                hooks=[validate_track_package],
            ),
            HookMatcher(
                matcher="mcp__ups__find_locations",
                hooks=[validate_find_locations],
            ),
            HookMatcher(
                matcher="mcp__ups__get_service_center_facilities",
                hooks=[validate_get_service_center_facilities],
            ),
            HookMatcher(
                matcher="mcp__ups__get_landed_cost_quote",
                hooks=[validate_landed_cost_quote],
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
