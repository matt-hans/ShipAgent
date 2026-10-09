"""Real adapter/SDK streams need terminal proof before runtime completion."""

import json
from types import SimpleNamespace

import httpx
import pytest

from src.services.conversation_runtime.models import ProviderStreamEventType
from src.services.conversation_runtime.runtime_session import ConversationRuntimeSession
from tests.services.conversation_runtime.test_gemini_provider import (
    _drain_gemini,
    _real_stream_client,
)
from tests.services.conversation_runtime.test_openai_provider import (
    _drain,
    _openai_stub,
)
from tests.services.provider_scenarios import (
    Call,
    Say,
    _anthropic_body,
    _anthropic_client,
    _gemini_body,
    _gemini_client,
    _openai_body,
    _openai_client,
)

_ADAPTERS = {
    "anthropic": (_anthropic_body, _anthropic_client),
    "openai": (_openai_body, _openai_client),
    "gemini": (_gemini_body, _gemini_client),
}


@pytest.mark.parametrize("provider_name", _ADAPTERS)
@pytest.mark.parametrize("content", ["text", "tool", "partial_tool"])
@pytest.mark.parametrize("completed", [False, True])
async def test_runtime_requires_provider_terminal_proof(
    provider_name, content, completed
):
    """A finished individual call cannot authorize dispatch or another model turn."""
    render, create = _ADAPTERS[provider_name]
    first = render(
        [Say("Synthetic answer")]
        if content == "text"
        else [Call("call_1", "get_schema", {"source": "orders"})]
    )
    if not completed:
        # Each renderer ends with its real provider terminal event/chunk.
        frames = first.rstrip(b"\n").split(b"\n\n")[:-1]
        if content == "partial_tool":
            if provider_name == "openai":
                frames = frames[:-1]  # no function_call_arguments.done
            elif provider_name == "anthropic":
                frames = frames[:-2]  # no block_stop or message_delta
            else:
                payload = json.loads(frames[-1].split(b"data: ", 1)[1])
                call = payload["candidates"][0]["content"]["parts"][0]["functionCall"]
                call["willContinue"] = True
                frames[-1] = b"data: " + json.dumps(payload).encode()
        first = b"\n\n".join(frames) + b"\n\n"
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            content=first if len(requests) == 1 else render([Say("Finished")]),
            headers={"content-type": "text/event-stream"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        runtime = ConversationRuntimeSession(
            provider=create(client),
            allowed_tool_names=frozenset(),
            decision_audit_enabled=False,
            system_prompt="Synthetic",
            interactive_shipping=False,
            session_id="terminal-proof",
        )
        await runtime.start()
        try:
            events = [event async for event in runtime.process_message_stream("Plan")]
            assert runtime.last_turn_completed is completed
            if completed:
                assert len(requests) == (1 if content == "text" else 2)
                assert any(event["event"] == "agent_message" for event in events)
            else:
                assert len(requests) == 1
                assert any(event["event"] == "error" for event in events)
                assert not any(event["event"] == "tool_call" for event in events)
                assert not any(event["event"] == "agent_message" for event in events)
        finally:
            await runtime.stop()


@pytest.mark.parametrize(
    "response",
    [
        None,
        "invalid",
        {},
        {"status": "in_progress", "output": []},
        {"status": "failed", "output": []},
        {"status": "completed"},
        {"status": "completed", "output": "invalid"},
    ],
)
async def test_openai_malformed_terminal_payload_never_completes(response):
    events = await _drain(
        _openai_stub([{"type": "response.completed", "response": response}])
    )
    assert events[-1].type == ProviderStreamEventType.PROVIDER_ERROR
    assert not any(e.type == ProviderStreamEventType.STREAM_COMPLETE for e in events)


@pytest.mark.parametrize(
    "reason",
    [
        None,
        "",
        "FINISH_REASON_UNSPECIFIED",
        "MAX_TOKENS",
        "SAFETY",
        "MALFORMED_FUNCTION_CALL",
        "UNEXPECTED_TOOL_CALL",
        "UNKNOWN",
    ],
)
async def test_gemini_unsuccessful_finish_reason_never_completes(reason):
    chunk = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(parts=[{"text": "Synthetic partial answer"}]),
                finish_reason=reason,
            )
        ]
    )
    events = await _drain_gemini(_real_stream_client([chunk]))
    assert events[-1].type == ProviderStreamEventType.PROVIDER_ERROR
    assert not any(e.type == ProviderStreamEventType.STREAM_COMPLETE for e in events)


@pytest.mark.parametrize("enum_reason", [False, True])
async def test_gemini_positive_terminal_survives_metadata_only_trailer(enum_reason):
    from google.genai.types import FinishReason

    reason = FinishReason.STOP if enum_reason else "STOP"
    provider = _real_stream_client(
        [
            SimpleNamespace(
                candidates=[
                    SimpleNamespace(
                        content=SimpleNamespace(parts=[{"text": "Synthetic answer"}]),
                        finish_reason=reason,
                    )
                ]
            ),
            SimpleNamespace(usage_metadata={"total_token_count": 5}),
        ]
    )
    events = await _drain_gemini(provider)
    assert events[-1].type == ProviderStreamEventType.STREAM_COMPLETE
    metadata = next(e.metadata for e in events if e.metadata is not None)
    assert metadata.usage["total_token_count"] == 5


@pytest.mark.parametrize(
    "later",
    [
        SimpleNamespace(candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")]),
        SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(parts=[{"text": "Unexpected later text"}]),
                )
            ]
        ),
    ],
)
async def test_gemini_terminal_proof_does_not_admit_conflicting_later_chunk(later):
    events = await _drain_gemini(
        _real_stream_client(
            [
                SimpleNamespace(candidates=[SimpleNamespace(finish_reason="STOP")]),
                later,
            ]
        )
    )
    assert events[-1].type == ProviderStreamEventType.PROVIDER_ERROR
    assert not any(e.type == ProviderStreamEventType.STREAM_COMPLETE for e in events)
