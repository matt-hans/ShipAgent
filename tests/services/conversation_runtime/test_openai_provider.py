from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.services.conversation_runtime.models import (
    ProviderContentPart,
    ProviderInputMessage,
    ProviderOutputItem,
    ProviderStreamEventType,
    ProviderToolCall,
    ProviderToolDeclaration,
)
from src.services.conversation_runtime.openai_provider import (
    OpenAIProviderClient,
    to_openai_input,
    to_openai_tool,
)


def test_openai_input_pairs_assistant_function_call_with_tool_output() -> None:
    call = ProviderToolCall(
        call_id="call_123",
        tool_name="get_schema",
        parsed_input={"source": "orders"},
        raw_arguments='{"source":"orders"}',
        metadata={"provider_item_id": "fc_123"},
    )

    input_items = to_openai_input(
        [
            ProviderInputMessage(
                role="user",
                content=[ProviderContentPart(text="Show schema")],
            ),
            ProviderInputMessage(
                role="assistant",
                content=[ProviderContentPart(type="tool_call", tool_call=call)],
            ),
            ProviderInputMessage(
                role="tool",
                content=[ProviderContentPart(text='{"columns":["sku"]}')],
                tool_call_id="call_123",
                metadata={"tool_name": "get_schema"},
            ),
        ]
    )

    assert input_items == [
        {"role": "user", "content": "Show schema"},
        {
            "type": "function_call",
            "call_id": "call_123",
            "name": "get_schema",
            "arguments": '{"source":"orders"}',
            "id": "fc_123",
        },
        {
            "type": "function_call_output",
            "call_id": "call_123",
            "output": '{"columns":["sku"]}',
        },
    ]


def test_openai_input_preserves_reasoning_items_with_tool_outputs() -> None:
    reasoning_item = {
        "id": "rs_123",
        "type": "reasoning",
        "content": [],
        "summary": [],
    }
    raw_function_call = {
        "id": "fc_123",
        "type": "function_call",
        "call_id": "call_123",
        "name": "get_schema",
        "arguments": '{"source":"orders"}',
    }
    reconstructed_call = ProviderToolCall(
        call_id="call_123",
        tool_name="get_schema",
        parsed_input={"source": "orders"},
        raw_arguments='{"source":"orders"}',
    )

    input_items = to_openai_input(
        [
            ProviderInputMessage(
                role="user",
                content=[ProviderContentPart(text="Show schema")],
            ),
            ProviderInputMessage(
                role="assistant",
                content=[
                    ProviderContentPart(
                        type="provider_output_item",
                        provider_output_item=ProviderOutputItem(
                            provider="openai",
                            item=reasoning_item,
                        ),
                    ),
                    ProviderContentPart(
                        type="provider_output_item",
                        provider_output_item=ProviderOutputItem(
                            provider="openai",
                            item=raw_function_call,
                        ),
                    ),
                    ProviderContentPart(
                        type="tool_call",
                        tool_call=reconstructed_call,
                    ),
                ],
            ),
            ProviderInputMessage(
                role="tool",
                content=[ProviderContentPart(text="Schema ready")],
                tool_call_id="call_123",
                metadata={"tool_name": "get_schema"},
            ),
        ]
    )

    assert input_items == [
        {"role": "user", "content": "Show schema"},
        reasoning_item,
        raw_function_call,
        {
            "type": "function_call_output",
            "call_id": "call_123",
            "output": "Schema ready",
        },
    ]


def test_openai_tool_projection_uses_responses_function_shape() -> None:
    tool = to_openai_tool(
        ProviderToolDeclaration(
            name="get_schema",
            description="Read schema",
            input_schema={"type": "object", "properties": {}},
        )
    )

    assert tool == {
        "type": "function",
        "name": "get_schema",
        "description": "Read schema",
        "parameters": {"type": "object", "properties": {}},
        "strict": False,
    }


@pytest.mark.asyncio
async def test_openai_stream_normalizes_text_and_function_call_events() -> None:
    class FakeStream:
        async def __aiter__(self):
            yield SimpleNamespace(
                type="response.output_item.added",
                output_index=0,
                item=SimpleNamespace(
                    type="function_call",
                    id="fc_123",
                    call_id="call_123",
                    name="get_schema",
                    arguments="",
                ),
            )
            yield SimpleNamespace(
                type="response.function_call_arguments.delta",
                output_index=0,
                delta='{"source"',
            )
            yield SimpleNamespace(
                type="response.function_call_arguments.delta",
                output_index=0,
                delta=':"orders"}',
            )
            yield SimpleNamespace(
                type="response.function_call_arguments.done",
                item_id="fc_123",
                arguments='{"source":"orders"}',
            )
            yield SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    id="resp_123",
                    model="gpt-5-mini",
                    status="completed",
                    output=[
                        {
                            "id": "rs_123",
                            "type": "reasoning",
                            "content": [],
                            "summary": [],
                        },
                        {
                            "id": "fc_123",
                            "type": "function_call",
                            "call_id": "call_123",
                            "name": "get_schema",
                            "arguments": '{"source":"orders"}',
                        },
                    ],
                    usage={"input_tokens": 10, "output_tokens": 2},
                ),
            )

    class FakeResponses:
        async def create(self, **kwargs):
            self.kwargs = kwargs
            return FakeStream()

    fake_responses = FakeResponses()
    client = SimpleNamespace(responses=fake_responses)
    provider = OpenAIProviderClient(model="openai:gpt-5-mini", client=client)

    events = [
        event
        async for event in provider.stream_turn(
            messages=[
                ProviderInputMessage(
                    role="user",
                    content=[ProviderContentPart(text="Show schema")],
                )
            ],
            system_instructions=[],
            tools=[],
        )
    ]

    tool_event = next(
        event
        for event in events
        if event.type == ProviderStreamEventType.TOOL_CALL_COMPLETE
    )
    assert json.loads(tool_event.tool_call.raw_arguments) == {"source": "orders"}
    assert tool_event.tool_call.call_id == "call_123"
    assert tool_event.tool_call.tool_name == "get_schema"
    provider_items = [
        event.provider_output_item.item
        for event in events
        if event.type == ProviderStreamEventType.PROVIDER_OUTPUT_ITEM
    ]
    assert provider_items == [
        {"id": "rs_123", "type": "reasoning", "content": [], "summary": []},
        {
            "id": "fc_123",
            "type": "function_call",
            "call_id": "call_123",
            "name": "get_schema",
            "arguments": '{"source":"orders"}',
        },
    ]
    assert fake_responses.kwargs["model"] == "gpt-5-mini"


@pytest.mark.parametrize("raw", ['{"a": ', "[1]", '"s"', "null"])
async def test_malformed_function_arguments_end_in_safe_error_without_a_call(
    raw: str,
) -> None:
    from src.services.conversation_runtime.openai_provider import (
        MALFORMED_ARGUMENTS_MESSAGE,
    )
    from tests.services.provider_scenarios import Call, build_provider

    rendered = build_provider("openai", [[Call("call_1", "get_schema", raw)]])

    events = [
        event
        async for event in rendered.provider.stream_turn(
            messages=[
                ProviderInputMessage(
                    role="user", content=[ProviderContentPart(text="hi")]
                )
            ],
            system_instructions=[],
            tools=[],
        )
    ]

    assert events[-1].type == ProviderStreamEventType.PROVIDER_ERROR
    assert events[-1].safe_error_message == MALFORMED_ARGUMENTS_MESSAGE
    assert all(
        event.type
        not in {
            ProviderStreamEventType.TOOL_CALL_COMPLETE,
            ProviderStreamEventType.STREAM_COMPLETE,
        }
        for event in events
    )


async def test_function_call_without_arguments_still_means_empty_input() -> None:
    from tests.services.provider_scenarios import Call, build_provider

    rendered = build_provider("openai", [[Call("call_1", "get_platform_status", "")]])

    events = [
        event
        async for event in rendered.provider.stream_turn(
            messages=[
                ProviderInputMessage(
                    role="user", content=[ProviderContentPart(text="hi")]
                )
            ],
            system_instructions=[],
            tools=[],
        )
    ]

    [call] = [e.tool_call for e in events if e.tool_call is not None]
    assert call.parsed_input == {}


def _openai_stub(events: list[dict]) -> OpenAIProviderClient:
    class Stream:
        async def __aiter__(self):
            for event in events:
                yield event

    class Responses:
        async def create(self, **_kwargs):
            return Stream()

    return OpenAIProviderClient(
        model="openai:gpt-5-mini",
        client=SimpleNamespace(responses=Responses()),
    )


async def _drain(provider: OpenAIProviderClient) -> list:
    return [
        event
        async for event in provider.stream_turn(
            messages=[
                ProviderInputMessage(
                    role="user", content=[ProviderContentPart(text="hi")]
                )
            ],
            system_instructions=[],
            tools=[],
        )
    ]


def _done(call_id: str | None, arguments: str = "{}") -> dict:
    return {
        "type": "response.function_call_arguments.done",
        "item_id": "fc_1",
        "name": "get_platform_status",
        "arguments": arguments,
        **({"call_id": call_id} if call_id else {}),
    }


def _completed(call_id: str | None, arguments: str = "{}") -> dict:
    item = {
        "type": "function_call",
        "id": "fc_1",
        "name": "get_platform_status",
        "arguments": arguments,
    }
    if call_id:
        item["call_id"] = call_id
    return {"type": "response.completed", "response": {"output": [item]}}


@pytest.mark.parametrize(
    "events",
    [
        pytest.param([_done(None)], id="streamed-done-without-call-id"),
        pytest.param([_completed(None)], id="completed-output-without-call-id"),
        pytest.param(
            [_done("call_1"), _completed(None)], id="streamed-then-id-less-copy"
        ),
    ],
)
async def test_function_call_without_call_id_fails_closed(events: list[dict]) -> None:
    from src.services.conversation_runtime.openai_provider import (
        MALFORMED_ARGUMENTS_MESSAGE,
    )

    produced = await _drain(_openai_stub(events))

    assert produced[-1].type == ProviderStreamEventType.PROVIDER_ERROR
    assert produced[-1].safe_error_message == MALFORMED_ARGUMENTS_MESSAGE
    assert ProviderStreamEventType.STREAM_COMPLETE not in {e.type for e in produced}


async def test_streamed_and_completed_copies_of_one_call_emit_it_once() -> None:
    produced = await _drain(
        _openai_stub([_done("call_1", '{"a": 1}'), _completed("call_1", '{"a": 1}')])
    )

    calls = [e.tool_call for e in produced if e.tool_call is not None]
    assert [(c.call_id, c.parsed_input) for c in calls] == [("call_1", {"a": 1})]
