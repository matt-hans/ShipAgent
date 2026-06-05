import asyncio

import pytest

from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.conversation_runtime.models import (
    ProviderCapabilities,
    ProviderInputMessage,
    ProviderOutputItem,
    ProviderResultMetadata,
    ProviderStreamEvent,
    ProviderStreamEventType,
    ProviderSystemInstruction,
    ProviderToolCall,
    ProviderToolDeclaration,
)
from src.services.conversation_runtime.runtime_session import ConversationRuntimeSession


class FakeRuntimeTool:
    name = "get_schema"
    allow_parallel = False

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def handler(self, args: dict):
        self.calls.append(args)
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"column_count":1,"columns":[{"name":"sku","type":"string"}]}',
                }
            ],
        }


class BlockingRuntimeTool(FakeRuntimeTool):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def handler(self, args: dict):
        self.started.set()
        await self.release.wait()
        return await super().handler(args)


class FailingRuntimeTool(FakeRuntimeTool):
    async def handler(self, args: dict):
        self.calls.append(args)
        raise RuntimeError("raw address=1 Main label_url=https://labels.example/leak")


class FakeRuntimeCatalog:
    def __init__(self, tool: FakeRuntimeTool) -> None:
        self.tool = tool

    def has(self, name: str) -> bool:
        return name == self.tool.name

    def get(self, name: str) -> FakeRuntimeTool:
        return self.tool

    def provider_declarations(self) -> list:
        return []


def _message_text(message: ProviderInputMessage) -> str:
    return "".join(part.text for part in message.content)


class RaisingProviderClient:
    def __init__(self) -> None:
        self._capabilities = ProviderCapabilities(
            provider="raising",
            model="raising-model",
            supports_streaming_text=True,
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def stream_turn(
        self,
        *,
        messages: list[ProviderInputMessage],
        system_instructions: list[ProviderSystemInstruction],
        tools: list[ProviderToolDeclaration],
    ):
        _ = messages, system_instructions, tools

        async def _stream_events():
            raise RuntimeError("provider secret api_key=sk-test-123 address=1 Main")
            yield

        return _stream_events()

    async def cancel(self) -> None:
        pass


@pytest.mark.asyncio
async def test_runtime_streams_text_delta_and_complete_message() -> None:
    provider = FakeProviderClient(
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
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                    text="Hello",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ]
        ]
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-text",
    )
    await runtime.start()

    events = [event async for event in runtime.process_message_stream("Hi")]

    assert events == [
        {"event": "agent_message_delta", "data": {"text": "Hel"}},
        {"event": "agent_message_delta", "data": {"text": "lo"}},
        {"event": "agent_message", "data": {"text": "Hello"}},
    ]
    assert runtime.last_turn_count == 1


@pytest.mark.asyncio
async def test_runtime_dispatches_tool_and_feeds_result_back_to_provider() -> None:
    call = ProviderToolCall(
        call_id="tool-1",
        tool_name="get_schema",
        parsed_input={},
    )
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
                    tool_call=call,
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                    text="Schema ready.",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
        ]
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-tool",
    )
    await runtime.start()

    events = [event async for event in runtime.process_message_stream("Show schema")]

    assert [event["event"] for event in events] == ["tool_call", "agent_message"]
    assert provider.requests[1]["messages"][-2].role == "assistant"
    assert provider.requests[1]["messages"][-2].content[-1].type == "tool_call"
    assert provider.requests[1]["messages"][-2].content[-1].tool_call == call
    assert provider.requests[1]["messages"][-1].role == "tool"
    assert provider.requests[1]["messages"][-1].tool_call_id == "tool-1"


@pytest.mark.asyncio
async def test_runtime_preserves_provider_output_items_before_tool_results() -> None:
    reasoning_item = ProviderOutputItem(
        provider="openai",
        item={"id": "rs_123", "type": "reasoning", "summary": []},
    )
    call = ProviderToolCall(
        call_id="tool-1",
        tool_name="get_schema",
        parsed_input={},
    )
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.PROVIDER_OUTPUT_ITEM,
                    provider_output_item=reasoning_item,
                ),
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
                    tool_call=call,
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                    text="Schema ready.",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
        ]
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-provider-output-item",
    )
    await runtime.start()

    events = [event async for event in runtime.process_message_stream("Show schema")]

    assert [event["event"] for event in events] == ["tool_call", "agent_message"]
    assistant_message = provider.requests[1]["messages"][-2]
    assert assistant_message.role == "assistant"
    assert assistant_message.content[0].provider_output_item == reasoning_item
    assert assistant_message.content[1].tool_call == call
    assert provider.requests[1]["messages"][-1].role == "tool"


@pytest.mark.asyncio
async def test_runtime_preserves_safe_history_across_sequential_turns() -> None:
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                    text="First answer.",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                    text="Second answer.",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
        ]
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-history",
    )
    await runtime.start()

    first_events = [event async for event in runtime.process_message_stream("First")]
    second_events = [event async for event in runtime.process_message_stream("Second")]

    assert first_events == [
        {"event": "agent_message", "data": {"text": "First answer."}},
    ]
    assert second_events == [
        {"event": "agent_message", "data": {"text": "Second answer."}},
    ]
    second_request_messages = provider.requests[1]["messages"]
    assert [
        (message.role, _message_text(message)) for message in second_request_messages
    ] == [
        ("user", "First"),
        ("assistant", "First answer."),
        ("user", "Second"),
    ]


@pytest.mark.asyncio
async def test_runtime_seeds_provider_messages_from_prior_conversation() -> None:
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                    text="Fresh answer.",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
        ]
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-resume",
        prior_conversation=[
            {"role": "user", "content": "Older question"},
            {"role": "assistant", "content": "Older answer"},
            {"role": "tool", "content": "unsafe tool result should not seed"},
        ],
    )
    await runtime.start()

    events = [event async for event in runtime.process_message_stream("Fresh")]

    assert events == [
        {"event": "agent_message", "data": {"text": "Fresh answer."}},
    ]
    request_messages = provider.requests[0]["messages"]
    assert [(message.role, _message_text(message)) for message in request_messages] == [
        ("user", "Older question"),
        ("assistant", "Older answer"),
        ("user", "Fresh"),
    ]


@pytest.mark.asyncio
async def test_runtime_yields_tool_call_before_blocking_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = ProviderToolCall(
        call_id="blocking-call",
        tool_name="get_schema",
        parsed_input={"source": "orders"},
    )
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
                    tool_call=call,
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                    text="Schema ready.",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
        ]
    )
    tool = BlockingRuntimeTool()
    monkeypatch.setattr(
        "src.services.conversation_runtime.runtime_session.WorkflowToolCatalog.for_mode",
        lambda **_kwargs: FakeRuntimeCatalog(tool),
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-tool-order",
    )
    await runtime.start()

    stream = runtime.process_message_stream("Show schema")
    first_event = await asyncio.wait_for(stream.__anext__(), timeout=0.2)

    assert first_event == {
        "event": "tool_call",
        "data": {
            "tool_name": "get_schema",
            "tool_input": {"source": "orders"},
            "tool_use_id": "blocking-call",
        },
    }
    assert not tool.started.is_set()

    tool.release.set()
    remaining = [event async for event in stream]
    assert remaining == [
        {"event": "agent_message", "data": {"text": "Schema ready."}},
    ]


@pytest.mark.asyncio
async def test_runtime_dedupes_duplicate_stable_tool_call_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicate_call = ProviderToolCall(
        call_id="duplicate-call",
        tool_name="get_schema",
        parsed_input={},
    )
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
                    tool_call=duplicate_call,
                ),
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
                    tool_call=duplicate_call,
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                    text="Schema ready.",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
        ]
    )
    tool = FakeRuntimeTool()
    monkeypatch.setattr(
        "src.services.conversation_runtime.runtime_session.WorkflowToolCatalog.for_mode",
        lambda **_kwargs: FakeRuntimeCatalog(tool),
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-dedupe",
    )
    await runtime.start()

    events = [event async for event in runtime.process_message_stream("Show schema")]

    assert [event["event"] for event in events] == ["tool_call", "agent_message"]
    assert len(tool.calls) == 1
    assert len(provider.requests[1]["messages"]) == 3
    assert provider.requests[1]["messages"][-2].role == "assistant"
    assert provider.requests[1]["messages"][-1].tool_call_id == "duplicate-call"


@pytest.mark.asyncio
async def test_runtime_dispatches_missing_tool_call_id_as_canonical_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = ProviderToolCall(
        call_id=None,
        tool_name="get_schema",
        parsed_input={},
    )
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
                    tool_call=call,
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                    text="Schema ready.",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
        ]
    )
    tool = FakeRuntimeTool()
    monkeypatch.setattr(
        "src.services.conversation_runtime.runtime_session.WorkflowToolCatalog.for_mode",
        lambda **_kwargs: FakeRuntimeCatalog(tool),
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-missing-tool-id",
    )
    await runtime.start()

    events = [event async for event in runtime.process_message_stream("Show schema")]

    assert events[0] == {
        "event": "tool_call",
        "data": {
            "tool_name": "get_schema",
            "tool_input": {},
        },
    }
    assert len(tool.calls) == 1
    assert provider.requests[1]["messages"][-1].tool_call_id is None


@pytest.mark.asyncio
async def test_runtime_handles_non_streaming_complete_text_provider() -> None:
    provider = FakeProviderClient(
        capabilities=ProviderCapabilities(
            provider="fake",
            model="fake-non-streaming",
            supports_streaming_text=False,
            supports_stable_tool_call_ids=False,
        ),
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                    text="Complete text.",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
        ],
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-non-streaming",
    )
    await runtime.start()

    events = [event async for event in runtime.process_message_stream("Hi")]

    assert events == [
        {"event": "agent_message", "data": {"text": "Complete text."}},
    ]


@pytest.mark.asyncio
async def test_runtime_feeds_internal_tool_failure_back_without_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = ProviderToolCall(
        call_id="failing-call",
        tool_name="get_schema",
        parsed_input={},
    )
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
                    tool_call=call,
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                    text="Handled failure.",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
        ]
    )
    tool = FailingRuntimeTool()
    monkeypatch.setattr(
        "src.services.conversation_runtime.runtime_session.WorkflowToolCatalog.for_mode",
        lambda **_kwargs: FakeRuntimeCatalog(tool),
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-tool-failure",
    )
    await runtime.start()

    events = [event async for event in runtime.process_message_stream("Show schema")]

    assert [event["event"] for event in events] == ["tool_call", "agent_message"]
    tool_result_message = provider.requests[1]["messages"][-1]
    assert tool_result_message.role == "tool"
    assert tool_result_message.metadata["is_error"] is True
    assert "1 Main" not in _message_text(tool_result_message)
    assert "labels.example" not in _message_text(tool_result_message)


@pytest.mark.asyncio
async def test_runtime_captures_result_metadata_without_sse_leak() -> None:
    metadata = ProviderResultMetadata(
        provider="fake",
        model="fake-model",
        session_id="provider-session",
        stop_reason="end_turn",
        result_subtype="success",
        num_turns=3,
        usage={"input_tokens": 1},
        total_cost_usd=0.001,
    )
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.RESULT_METADATA,
                    metadata=metadata,
                ),
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                    text="Done",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
        ]
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-metadata",
    )
    await runtime.start()

    events = [event async for event in runtime.process_message_stream("Hi")]

    assert events == [{"event": "agent_message", "data": {"text": "Done"}}]
    assert runtime.last_result_metadata == metadata
    assert runtime.last_turn_count == 3


@pytest.mark.asyncio
async def test_interrupt_drops_late_events_from_old_generation() -> None:
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_DELTA,
                    text="stale",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                    text="fresh",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
        ]
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-interrupt",
    )
    await runtime.start()

    stream = runtime.process_message_stream("first")
    await runtime.interrupt()
    stale_events = [event async for event in stream]
    fresh_events = [event async for event in runtime.process_message_stream("second")]

    assert stale_events == []
    assert fresh_events == [{"event": "agent_message", "data": {"text": "fresh"}}]


@pytest.mark.asyncio
async def test_process_command_returns_sanitized_error_text() -> None:
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.PROVIDER_ERROR,
                    error_message=(
                        "provider failed for customer Jane at 742 Main St "
                        "api_key=sk-test-123"
                    ),
                ),
            ]
        ]
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-command-error",
    )
    await runtime.start()

    result = await runtime.process_command("Hi")

    assert result.startswith("[Error: ")
    assert "api_key" not in result
    assert "sk-test-123" not in result
    assert "Jane" not in result
    assert "742 Main St" not in result


@pytest.mark.asyncio
async def test_provider_stream_exception_yields_sanitized_error_event() -> None:
    runtime = ConversationRuntimeSession(
        provider=RaisingProviderClient(),
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-provider-exception",
    )
    await runtime.start()

    events = [event async for event in runtime.process_message_stream("Hi")]

    assert len(events) == 1
    assert events[0]["event"] == "error"
    assert "api_key" not in events[0]["data"]["message"]
    assert "sk-test-123" not in events[0]["data"]["message"]
    assert "Jane" not in events[0]["data"]["message"]
    assert "742 Main St" not in events[0]["data"]["message"]
