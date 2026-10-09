"""Continuation is a dormant, revision-scoped accepted model operation."""

import pytest
from jsonschema import Draft202012Validator

from src.hosted_mcp.server import build_server
from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.registry.catalog import public_tools
from src.registry.models import SideEffectClass
from src.services.agent_runs.clarification import CLARIFICATION_QUESTIONS


def test_continue_contract_has_only_explicit_follow_up_inputs():
    contracts = {tool.name: tool for tool in public_tools()}
    assert "continue_shipagent_task" in contracts
    continuation = contracts["continue_shipagent_task"]
    assert continuation.auth_scopes == ["shipagent.preview"]
    assert continuation.side_effect == SideEffectClass.agent_work
    assert continuation.call_repetition == "idempotent"
    assert continuation.rate_limit_class == "write"
    assert continuation.hosted_readiness == "not_ready"
    assert continuation.provider_export_enabled is False
    assert continuation.execution_target_required is True
    assert set(continuation.input_schema["properties"]) == {
        "conversation_reference",
        "run_reference",
        "expected_revision",
        "task",
        "request_key",
    }
    assert set(continuation.input_schema["required"]) == set(
        continuation.input_schema["properties"]
    )
    assert continuation.input_schema["additionalProperties"] is False
    descriptor = to_mcp_tool_descriptor(continuation)
    assert descriptor["annotations"]["openWorldHint"] is True
    assert descriptor["annotations"]["readOnlyHint"] is False
    result = continuation.output_schema["properties"]
    assert "waiting_for_input" in result["state"]["enum"]
    assert "clarification_required" in result["outcome"]["enum"]
    assert set(result["conversation_state"]["enum"]) == {
        "active",
        "waiting_for_input",
        "completed",
        "failed",
        "cancelled",
    }
    assert result["conversation_revision"]["minimum"] == 1
    assert result["clarification"]["additionalProperties"] is False
    assert set(result["clarification"]["properties"]) == {"code", "question"}


@pytest.mark.asyncio
async def test_default_server_does_not_admit_continuation():
    assert "continue_shipagent_task" not in await build_server().get_tools()


def test_clarification_schema_accepts_only_matching_fixed_questions():
    contract = next(
        tool for tool in public_tools() if tool.name == "continue_shipagent_task"
    )
    validator = Draft202012Validator(
        contract.output_schema["properties"]["clarification"]
    )
    for code, question in CLARIFICATION_QUESTIONS.items():
        assert validator.is_valid({"code": code, "question": question})
        assert not validator.is_valid({"code": code, "question": "PRIVATE_MODEL_TEXT"})
        assert not validator.is_valid(
            {"code": code, "question": question, "extra": True}
        )
        for other, other_question in CLARIFICATION_QUESTIONS.items():
            if other != code:
                assert not validator.is_valid(
                    {"code": code, "question": other_question}
                )
