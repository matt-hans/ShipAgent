from inspect import Parameter, signature

import pytest

from src.services.conversation_runtime import (
    ProviderContentPart,
    ProviderInputMessage,
    ProviderStreamEvent,
    ProviderStreamEventType,
    ProviderSystemInstruction,
    ProviderToolCall,
    ProviderToolDeclaration,
)
from src.services.conversation_runtime.fake_provider import FakeProviderClient


def test_fake_provider_default_capabilities_enable_fake_runtime_features() -> None:
    client = FakeProviderClient(script=[])

    assert client.capabilities.provider == "fake"
    assert client.capabilities.model == "fake-model"
    assert client.capabilities.supports_streaming_text is True
    assert client.capabilities.supports_stable_tool_call_ids is True
    assert client.capabilities.supports_usage_metadata is True
    assert client.capabilities.supports_streaming_tool_arguments is False
    assert client.capabilities.supports_parallel_tool_calls is False
    assert client.capabilities.supports_cancellation is False
    assert client.capabilities.supports_provider_session_ids is False


def test_fake_provider_raises_when_script_is_exhausted() -> None:
    client = FakeProviderClient(script=[])

    with pytest.raises(RuntimeError, match="script exhausted"):
        client.stream_turn(
            messages=[],
            system_instructions=[],
            tools=[],
        )


async def test_fake_provider_allows_explicit_empty_script_batch() -> None:
    client = FakeProviderClient(script=[[]])

    events = [
        event
        async for event in client.stream_turn(
            messages=[],
            system_instructions=[],
            tools=[],
        )
    ]

    assert events == []
    assert len(client.requests) == 1


async def test_fake_provider_streams_scripted_events() -> None:
    client = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_DELTA,
                    text="Hel",
                ),
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_DELTA,
                    text="lo",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ]
        ]
    )
    messages = [
        ProviderInputMessage(
            role="user",
            content=[ProviderContentPart(text="Ship these orders")],
        )
    ]

    events = [
        event
        async for event in client.stream_turn(
            messages=messages,
            system_instructions=[],
            tools=[],
        )
    ]

    assert [event.text for event in events[:2]] == ["Hel", "lo"]
    assert events[-1].type == ProviderStreamEventType.STREAM_COMPLETE


async def test_fake_provider_advances_one_script_batch_per_turn() -> None:
    client = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_DELTA,
                    text="first",
                )
            ],
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_DELTA,
                    text="second",
                )
            ],
        ]
    )

    first_events = [
        event
        async for event in client.stream_turn(
            messages=[],
            system_instructions=[],
            tools=[],
        )
    ]
    second_events = [
        event
        async for event in client.stream_turn(
            messages=[],
            system_instructions=[],
            tools=[],
        )
    ]

    assert [event.text for event in first_events] == ["first"]
    assert [event.text for event in second_events] == ["second"]


async def test_fake_provider_reserves_script_batch_when_stream_is_created() -> None:
    client = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_DELTA,
                    text="first",
                )
            ],
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_DELTA,
                    text="second",
                )
            ],
        ]
    )

    first_stream = client.stream_turn(
        messages=[],
        system_instructions=[],
        tools=[],
    )
    second_stream = client.stream_turn(
        messages=[],
        system_instructions=[],
        tools=[],
    )

    second_events = [event async for event in second_stream]
    first_events = [event async for event in first_stream]

    assert [event.text for event in first_events] == ["first"]
    assert [event.text for event in second_events] == ["second"]


async def test_fake_provider_records_messages_and_tool_declarations() -> None:
    client = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
                    tool_call=ProviderToolCall(
                        call_id="tool-1",
                        tool_name="ship_command_pipeline",
                        parsed_input={"all_rows": True},
                    ),
                )
            ]
        ]
    )

    await anext(
        client.stream_turn(
            messages=[],
            system_instructions=[],
            tools=[],
        )
    )

    assert len(client.requests) == 1
    assert client.requests[0]["messages"] == []
    assert client.requests[0]["tools"] == []


async def test_fake_provider_records_request_list_snapshots() -> None:
    client = FakeProviderClient(
        script=[[ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE)]]
    )
    messages = [
        ProviderInputMessage(
            role="user",
            content=[ProviderContentPart(text="original")],
        )
    ]
    system_instructions = [ProviderSystemInstruction(content="system")]
    tools = [
        ProviderToolDeclaration(
            name="ship_command_pipeline",
            description="Preview shipments",
            input_schema={"type": "object"},
        )
    ]

    stream = client.stream_turn(
        messages=messages,
        system_instructions=system_instructions,
        tools=tools,
    )
    messages.clear()
    system_instructions.clear()
    tools.clear()
    await anext(stream)

    assert len(client.requests[0]["messages"]) == 1
    assert len(client.requests[0]["system_instructions"]) == 1
    assert len(client.requests[0]["tools"]) == 1


async def test_fake_provider_records_nested_request_snapshots() -> None:
    client = FakeProviderClient(
        script=[[ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE)]]
    )
    messages = [
        ProviderInputMessage(
            role="user",
            content=[ProviderContentPart(text="original")],
        )
    ]
    tools = [
        ProviderToolDeclaration(
            name="ship_command_pipeline",
            description="Preview shipments",
            input_schema={"type": "object"},
        )
    ]

    stream = client.stream_turn(
        messages=messages,
        system_instructions=[],
        tools=tools,
    )
    messages[0].content.append(ProviderContentPart(text="mutated"))
    tools[0].input_schema["properties"] = {"extra": {"type": "string"}}
    await anext(stream)

    recorded_messages = client.requests[0]["messages"]
    recorded_tools = client.requests[0]["tools"]
    assert recorded_messages[0].content == [ProviderContentPart(text="original")]
    assert recorded_tools[0].input_schema == {"type": "object"}


async def test_fake_provider_cancel_flips_cancelled_flag() -> None:
    client = FakeProviderClient(script=[])

    assert client.cancelled is False

    await client.cancel()

    assert client.cancelled is True


def test_fake_provider_constructor_requires_keyword_script() -> None:
    parameters = signature(FakeProviderClient).parameters

    assert parameters["script"].kind is Parameter.KEYWORD_ONLY
    assert parameters["capabilities"].kind is Parameter.KEYWORD_ONLY


def test_fake_provider_stream_turn_requires_keyword_arguments() -> None:
    parameters = signature(FakeProviderClient.stream_turn).parameters

    assert parameters["messages"].kind is Parameter.KEYWORD_ONLY
    assert parameters["system_instructions"].kind is Parameter.KEYWORD_ONLY
    assert parameters["tools"].kind is Parameter.KEYWORD_ONLY
