import pytest

from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.conversation_runtime.models import (
    ProviderCapabilities,
    ProviderInputMessage,
    ProviderResultMetadata,
    ProviderStreamEvent,
    ProviderStreamEventType,
    ProviderSystemInstruction,
    ProviderToolCall,
    ProviderToolDeclaration,
)
from src.services.conversation_runtime.runtime_session import ConversationRuntimeSession


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
            raise RuntimeError(
                "provider secret api_key=sk-test-123 address=1 Main"
            )
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
    assert provider.requests[1]["messages"][-1].role == "tool"
    assert provider.requests[1]["messages"][-1].tool_call_id == "tool-1"


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
