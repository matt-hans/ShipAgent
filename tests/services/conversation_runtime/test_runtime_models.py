from inspect import Parameter, iscoroutinefunction, signature
from typing import get_args, get_type_hints

from src.services.conversation_runtime import (
    ModelProviderClient,
    ProviderCapabilities,
    ProviderContentPart,
    ProviderFinalResult,
    ProviderInputMessage,
    ProviderOutputItem,
    ProviderResultMetadata,
    ProviderRole,
    ProviderStreamEvent,
    ProviderStreamEventType,
    ProviderToolCall,
    ProviderToolResult,
)


def test_provider_capabilities_default_to_weakest_common_contract() -> None:
    capabilities = ProviderCapabilities(provider="fake", model="fake-model")

    assert capabilities.supports_streaming_text is False
    assert capabilities.supports_streaming_tool_arguments is False
    assert capabilities.supports_parallel_tool_calls is False
    assert capabilities.supports_cancellation is False
    assert capabilities.supports_usage_metadata is False
    assert capabilities.supports_stable_tool_call_ids is False
    assert capabilities.supports_provider_session_ids is False


def test_provider_role_is_exported_from_runtime_package() -> None:
    assert get_args(ProviderRole) == (
        "system",
        "developer",
        "user",
        "assistant",
        "tool",
    )


def test_provider_tool_result_safe_payload_shape() -> None:
    result = ProviderToolResult(
        call_id="call-1",
        tool_name="fetch_rows",
        content="Fetched 10 rows. Use fetch_id to continue.",
        structured_payload={"fetch_id": "fetch-1", "total_count": 10},
        is_error=False,
    )

    assert result.call_id == "call-1"
    assert result.structured_payload == {"fetch_id": "fetch-1", "total_count": 10}


def test_provider_final_result_keeps_normalized_metadata() -> None:
    metadata = ProviderResultMetadata(
        provider="fake",
        model="fake-model",
        session_id="provider-session",
        stop_reason="end_turn",
        result_subtype="success",
        num_turns=2,
        usage={"input_tokens": 10, "output_tokens": 5},
        total_cost_usd=0.01,
        raw_usage_provider={"input_tokens": 10, "output_tokens": 5},
    )

    result = ProviderFinalResult(text="Done", metadata=metadata)

    assert result.text == "Done"
    assert result.metadata.provider == "fake"
    assert result.metadata.model == "fake-model"
    assert result.metadata.session_id == "provider-session"
    assert result.metadata.stop_reason == "end_turn"
    assert result.metadata.result_subtype == "success"
    assert result.metadata.num_turns == 2
    assert result.metadata.usage == {"input_tokens": 10, "output_tokens": 5}
    assert result.metadata.total_cost_usd == 0.01
    assert result.metadata.raw_usage_provider == {
        "input_tokens": 10,
        "output_tokens": 5,
    }


def test_tool_call_event_carries_parsed_input_and_raw_arguments() -> None:
    call = ProviderToolCall(
        call_id="tool-1",
        tool_name="ship_command_pipeline",
        parsed_input={"all_rows": True},
        raw_arguments='{"all_rows": true}',
    )

    event = ProviderStreamEvent(
        type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
        tool_call=call,
    )

    assert event.tool_call is call
    assert event.tool_call.parsed_input == {"all_rows": True}
    assert event.tool_call.raw_arguments == '{"all_rows": true}'


def test_assistant_message_can_carry_tool_call_content_part() -> None:
    call = ProviderToolCall(
        call_id="call-1",
        tool_name="get_schema",
        parsed_input={},
    )

    message = ProviderInputMessage(
        role="assistant",
        content=[ProviderContentPart(type="tool_call", tool_call=call)],
    )

    assert message.content[0].type == "tool_call"
    assert message.content[0].tool_call is call


def test_assistant_message_can_carry_provider_output_item_part() -> None:
    output_item = ProviderOutputItem(
        provider="openai",
        item={"id": "rs_123", "type": "reasoning", "summary": []},
    )

    message = ProviderInputMessage(
        role="assistant",
        content=[
            ProviderContentPart(
                type="provider_output_item",
                provider_output_item=output_item,
            )
        ],
    )

    assert message.content[0].type == "provider_output_item"
    assert message.content[0].provider_output_item is output_item


def test_stream_event_metadata_uses_normalized_result_metadata_contract() -> None:
    annotations = get_type_hints(ProviderStreamEvent)

    assert annotations["metadata"] == ProviderResultMetadata | None


def test_model_provider_stream_turn_requires_keyword_arguments() -> None:
    parameters = signature(ModelProviderClient.stream_turn).parameters

    assert parameters["messages"].kind is Parameter.KEYWORD_ONLY
    assert parameters["system_instructions"].kind is Parameter.KEYWORD_ONLY
    assert parameters["tools"].kind is Parameter.KEYWORD_ONLY


def test_model_provider_stream_turn_returns_async_iterator_without_await() -> None:
    assert iscoroutinefunction(ModelProviderClient.stream_turn) is False
