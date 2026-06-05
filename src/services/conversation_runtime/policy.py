from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.orchestrator.models.filter_spec import FilterOperator
from src.services.conversation_runtime.models import ProviderToolCall


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def reason(self) -> str:
        hook_output = self.payload.get("hookSpecificOutput")
        if not isinstance(hook_output, dict):
            return ""
        reason = hook_output.get("permissionDecisionReason")
        return reason if isinstance(reason, str) else ""


def _deny(reason: str) -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        payload={
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
    )


def _find_banned_keys_recursive(obj: Any, banned: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        found.update(banned & set(obj.keys()))
        for value in obj.values():
            found.update(_find_banned_keys_recursive(value, banned))
    elif isinstance(obj, list):
        for item in obj:
            found.update(_find_banned_keys_recursive(item, banned))
    return found


def _find_invalid_filter_operator(obj: Any, valid_operators: set[str]) -> str | None:
    if isinstance(obj, dict):
        operator = obj.get("operator")
        if operator is not None and operator not in valid_operators:
            return str(operator)
        for value in obj.values():
            invalid_operator = _find_invalid_filter_operator(value, valid_operators)
            if invalid_operator is not None:
                return invalid_operator
    elif isinstance(obj, list):
        for item in obj:
            invalid_operator = _find_invalid_filter_operator(item, valid_operators)
            if invalid_operator is not None:
                return invalid_operator
    return None


class RuntimePolicyEngine:
    _FILTER_TOOLS = {"resolve_filter_intent", "ship_command_pipeline", "fetch_rows"}
    _BANNED_SQL_KEYS = {"where_clause", "sql", "query", "raw_sql"}
    _DIRECT_UPS_DENIAL_REASONS = {
        "mcp__ups__void_shipment": (
            "Direct mcp__ups__void_shipment is not available in the "
            "provider-neutral runtime until a ShipAgent void workflow wrapper "
            "with preview and confirmation is added."
        ),
        "mcp__ups__schedule_pickup": (
            "Direct mcp__ups__schedule_pickup is not allowed. "
            "Use the schedule_pickup orchestrator tool instead, which enforces "
            "user confirmation before committing."
        ),
        "mcp__ups__cancel_pickup": (
            "Direct mcp__ups__cancel_pickup is not allowed. "
            "Use the cancel_pickup orchestrator tool instead, which enforces "
            "user confirmation before committing."
        ),
        "mcp__ups__track_package": (
            "Direct mcp__ups__track_package is not allowed. "
            "Use the track_package orchestrator tool instead, which emits "
            "tracking result events for the UI."
        ),
        "mcp__ups__find_locations": (
            "Direct mcp__ups__find_locations is not allowed. "
            "Use the find_locations orchestrator tool instead, which emits "
            "location result events for the UI."
        ),
        "mcp__ups__get_service_center_facilities": (
            "Direct mcp__ups__get_service_center_facilities is not allowed. "
            "Use the get_service_center_facilities orchestrator tool instead, "
            "which emits location result events for the UI."
        ),
        "mcp__ups__get_landed_cost_quote": (
            "Direct mcp__ups__get_landed_cost_quote is not allowed. "
            "Use the get_landed_cost orchestrator tool instead, which emits "
            "landed cost result events for the UI."
        ),
    }

    def __init__(self, interactive_shipping: bool) -> None:
        self.interactive_shipping = interactive_shipping

    async def check_pre_tool(self, call: ProviderToolCall) -> PolicyDecision:
        raw_sql_decision = self._deny_raw_sql(call)
        if raw_sql_decision is not None:
            return raw_sql_decision

        filter_structure_decision = self._validate_filter_structure(call)
        if filter_structure_decision is not None:
            return filter_structure_decision

        direct_ups_decision = self._deny_direct_ups(call)
        if direct_ups_decision is not None:
            return direct_ups_decision

        return PolicyDecision(allowed=True)

    def _deny_raw_sql(self, call: ProviderToolCall) -> PolicyDecision | None:
        if call.tool_name not in self._FILTER_TOOLS:
            return None

        found_keys = _find_banned_keys_recursive(
            call.parsed_input,
            self._BANNED_SQL_KEYS,
        )
        if not found_keys:
            return None

        return _deny(
            f"Raw SQL keys {sorted(found_keys)} are not allowed in "
            f"{call.tool_name}. Use resolve_filter_intent to create a "
            "filter_spec instead."
        )

    def _validate_filter_structure(self, call: ProviderToolCall) -> PolicyDecision | None:
        if call.tool_name == "resolve_filter_intent":
            intent = call.parsed_input.get("intent")
            if not isinstance(intent, dict):
                return None

            invalid_operator = _find_invalid_filter_operator(
                intent,
                {operator.value for operator in FilterOperator},
            )
            if invalid_operator is not None:
                return _deny(
                    f"FilterIntent validation failed: Invalid operator "
                    f"{invalid_operator!r}."
                )

            return None

        if call.tool_name not in {"ship_command_pipeline", "fetch_rows"}:
            return None

        if call.parsed_input.get("all_rows"):
            return None

        filter_spec = call.parsed_input.get("filter_spec")
        if not isinstance(filter_spec, dict):
            return None

        if "root" not in filter_spec:
            return _deny(
                "filter_spec must contain a 'root' field. "
                "Use resolve_filter_intent to create a valid filter_spec."
            )

        return None

    def _deny_direct_ups(self, call: ProviderToolCall) -> PolicyDecision | None:
        if call.tool_name == "mcp__ups__create_shipment":
            if self.interactive_shipping:
                return _deny(
                    "Direct shipment creation is not allowed in interactive mode. "
                    "Use the preview_interactive_shipment tool instead."
                )
            return _deny(
                "Interactive shipping is disabled. "
                "Use batch processing for shipment creation."
            )

        reason = self._DIRECT_UPS_DENIAL_REASONS.get(call.tool_name)
        if reason is None:
            return None

        return _deny(reason)

    def detect_error_response(self, response: Any) -> bool:
        if isinstance(response, dict):
            if response.get("error"):
                return True
            if response.get("isError") is True:
                return True
            if response.get("is_error") is True:
                return True
            status = response.get("status") or response.get("statusCode")
            return isinstance(status, int) and status >= 400

        if isinstance(response, str):
            response_lower = response.lower()
            if "error:" in response_lower or '"error"' in response_lower:
                return True
            return "failed" in response_lower and "validation failed" not in response_lower

        return False

    def serialize_response(self, response: Any) -> str:
        if isinstance(response, str):
            return response
        return json.dumps(response, default=str)
