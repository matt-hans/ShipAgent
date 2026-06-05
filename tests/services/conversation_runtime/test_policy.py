import pytest

from src.services.conversation_runtime.models import ProviderToolCall
from src.services.conversation_runtime.policy import RuntimePolicyEngine


async def test_denies_raw_sql_before_filter_structure_check() -> None:
    engine = RuntimePolicyEngine(interactive_shipping=False)
    call = ProviderToolCall(
        call_id="call-1",
        tool_name="ship_command_pipeline",
        parsed_input={"filter_spec": {"where_clause": "state='CA'"}},
    )

    result = await engine.check_pre_tool(call)

    assert result.allowed is False
    assert result.payload["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "where_clause" in result.payload["hookSpecificOutput"][
        "permissionDecisionReason"
    ]


async def test_denies_filter_spec_without_root() -> None:
    engine = RuntimePolicyEngine(interactive_shipping=False)
    call = ProviderToolCall(
        call_id="call-1",
        tool_name="ship_command_pipeline",
        parsed_input={"filter_spec": {"status": "RESOLVED"}},
    )

    result = await engine.check_pre_tool(call)

    assert result.allowed is False
    assert result.payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert result.payload["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "root" in result.reason


async def test_denies_resolve_filter_intent_with_invalid_operator() -> None:
    engine = RuntimePolicyEngine(interactive_shipping=False)
    call = ProviderToolCall(
        call_id="call-1",
        tool_name="resolve_filter_intent",
        parsed_input={
            "intent": {
                "root": {
                    "logic": "AND",
                    "conditions": [
                        {
                            "column": "state",
                            "operator": "EXPLODE",
                            "operands": [],
                        }
                    ],
                }
            }
        },
    )

    result = await engine.check_pre_tool(call)

    assert result.allowed is False
    assert "Invalid operator" in result.reason


@pytest.mark.parametrize(
    ("tool_name", "expected_wrapper"),
    [
        ("mcp__ups__create_shipment", "preview_interactive_shipment"),
        ("mcp__ups__void_shipment", "not available"),
        ("mcp__ups__schedule_pickup", "schedule_pickup"),
        ("mcp__ups__cancel_pickup", "cancel_pickup"),
        ("mcp__ups__track_package", "track_package"),
        ("mcp__ups__find_locations", "find_locations"),
        (
            "mcp__ups__get_service_center_facilities",
            "get_service_center_facilities",
        ),
        ("mcp__ups__get_landed_cost_quote", "get_landed_cost"),
    ],
)
async def test_denies_direct_ups_tools(
    tool_name: str,
    expected_wrapper: str,
) -> None:
    engine = RuntimePolicyEngine(interactive_shipping=True)
    call = ProviderToolCall(
        call_id="call-1",
        tool_name=tool_name,
        parsed_input={},
    )

    result = await engine.check_pre_tool(call)

    assert result.allowed is False
    assert expected_wrapper in result.reason


def test_post_tool_error_detection_for_dict_and_string() -> None:
    engine = RuntimePolicyEngine(interactive_shipping=False)

    assert engine.detect_error_response({"is_error": True}) is True
    assert engine.detect_error_response({"isError": True}) is True
    assert engine.detect_error_response({"error": "bad"}) is True
    assert engine.detect_error_response({"status": 400}) is True
    assert engine.detect_error_response({"statusCode": 500}) is True
    assert engine.detect_error_response("UPS error: unavailable") is True
    assert engine.detect_error_response('response {"error": "bad"}') is True
    assert engine.detect_error_response("UPS request failed") is True
    assert engine.detect_error_response("validation failed: missing address") is False
    assert engine.detect_error_response("no errors found") is False
    assert engine.detect_error_response("exception handled cleanly") is False
    assert engine.detect_error_response({"ok": True}) is False
