import pytest

from src.services.conversation_runtime.models import ProviderToolCall
from src.services.conversation_runtime.policy import RuntimePolicyEngine
from src.services.policy_decision import PolicyDecision, PolicyDenialCode


def _call(tool_name: str, parsed_input: dict | None = None) -> ProviderToolCall:
    return ProviderToolCall(
        call_id="call-1",
        tool_name=tool_name,
        parsed_input=parsed_input or {},
    )


def test_allow_decision_has_no_denial_code_or_reason() -> None:
    decision = PolicyDecision.allow()

    assert decision.allowed is True
    assert decision.code is None
    assert decision.reason == ""


def test_deny_decision_requires_stable_code_and_exposes_no_hook_envelope() -> None:
    decision = PolicyDecision.deny(PolicyDenialCode.RAW_SQL_NOT_ALLOWED, "nope")

    assert decision.allowed is False
    assert decision.code is PolicyDenialCode.RAW_SQL_NOT_ALLOWED
    assert decision.reason == "nope"
    assert not hasattr(decision, "payload")


async def test_denies_raw_sql_before_filter_structure_check() -> None:
    engine = RuntimePolicyEngine(interactive_shipping=False)

    result = await engine.check_pre_tool(
        _call("ship_command_pipeline", {"filter_spec": {"where_clause": "state='CA'"}})
    )

    assert result.allowed is False
    assert result.code is PolicyDenialCode.RAW_SQL_NOT_ALLOWED
    assert "where_clause" in result.reason


async def test_denies_filter_spec_without_root() -> None:
    engine = RuntimePolicyEngine(interactive_shipping=False)

    result = await engine.check_pre_tool(
        _call("ship_command_pipeline", {"filter_spec": {"status": "RESOLVED"}})
    )

    assert result.allowed is False
    assert result.code is PolicyDenialCode.INVALID_FILTER_STRUCTURE


async def test_denies_resolve_filter_intent_with_invalid_operator_without_echo() -> (
    None
):
    engine = RuntimePolicyEngine(interactive_shipping=False)
    leaky = "Jane 1 Main St jane@example.com"

    result = await engine.check_pre_tool(
        _call(
            "resolve_filter_intent",
            {
                "intent": {
                    "root": {
                        "logic": "AND",
                        "conditions": [
                            {"column": "state", "operator": leaky, "operands": []}
                        ],
                    }
                }
            },
        )
    )

    assert result.allowed is False
    assert result.code is PolicyDenialCode.INVALID_FILTER_STRUCTURE
    assert "jane" not in result.reason.lower()
    assert "Main St" not in result.reason


async def test_allows_well_formed_filter_calls() -> None:
    engine = RuntimePolicyEngine(interactive_shipping=False)

    result = await engine.check_pre_tool(
        _call("fetch_rows", {"filter_spec": {"root": {"logic": "AND"}}})
    )

    assert result == PolicyDecision.allow()


@pytest.mark.parametrize("interactive", [True, False])
async def test_denies_direct_shipment_creation_in_either_mode(
    interactive: bool,
) -> None:
    engine = RuntimePolicyEngine(interactive_shipping=interactive)

    result = await engine.check_pre_tool(_call("mcp__ups__create_shipment"))

    assert result.allowed is False
    assert result.code is PolicyDenialCode.DIRECT_SHIPMENT_CREATION_NOT_ALLOWED


async def test_allow_never_grants_purchase_authority_to_shipment_tools() -> None:
    """Allow is only 'not denied by this gate'; it carries no approval data."""
    engine = RuntimePolicyEngine(interactive_shipping=True)

    result = await engine.check_pre_tool(_call("preview_interactive_shipment"))

    assert result.allowed is True
    assert set(vars(result)) == {"allowed", "code", "reason"}


@pytest.mark.parametrize(
    ("tool_name", "expected_wrapper"),
    [
        ("mcp__ups__create_shipment", "preview_interactive_shipment"),
        ("mcp__ups__rate_shipment", "rate_shipment"),
        ("mcp__ups__validate_address", "validate_address"),
        ("mcp__ups__get_time_in_transit", "get_time_in_transit"),
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
    expected_code = (
        PolicyDenialCode.DIRECT_SHIPMENT_CREATION_NOT_ALLOWED
        if tool_name == "mcp__ups__create_shipment"
        else PolicyDenialCode.RAW_CARRIER_CALL_NOT_ALLOWED
    )
    assert result.code is expected_code


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
    assert engine.detect_error_response({"status": "failed", "job_id": "job-1"}) is False
    assert engine.detect_error_response({"data": {"status": "failed"}}) is False
    assert engine.detect_error_response("no errors found") is False
    assert engine.detect_error_response("exception handled cleanly") is False
    assert engine.detect_error_response({"ok": True}) is False


@pytest.mark.parametrize(
    "response",
    [
        {"status": "error"},
        {"status": "errored"},
        {"statusCode": "error"},
        {"data": {"status": "error"}},
        {"data": {"statusCode": "error"}},
        [{"status": "error"}],
        [{"data": {"status": "errored"}}],
        [{"data": [{"statusCode": "error"}]}],
    ],
)
def test_post_tool_error_detection_for_explicit_status_error_markers(
    response: object,
) -> None:
    engine = RuntimePolicyEngine(interactive_shipping=False)

    assert engine.detect_error_response(response) is True
