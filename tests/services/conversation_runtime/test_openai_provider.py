from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.services.conversation_runtime.models import (
    ProviderContentPart,
    ProviderInputMessage,
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
                    output=[],
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
    assert fake_responses.kwargs["model"] == "gpt-5-mini"
