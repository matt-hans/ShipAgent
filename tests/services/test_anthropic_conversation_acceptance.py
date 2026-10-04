"""Acceptance: Anthropic Messages adapter through the shared conversation service.

Drives ``process_message`` with the real Anthropic adapter over a mocked HTTP
transport, so the full path (history/system translation -> SSE normalization ->
runtime session -> UI events/persistence) is exercised without network access.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from src.services.conversation_runtime.anthropic_provider import (
    EMPTY_RESPONSE_MESSAGE,
    AnthropicProviderClient,
)
from tests.services.conversation_acceptance import run_scenario
from tests.services.conversation_runtime.test_anthropic_provider import (
    SECRET,
    TEXT_BLOCK,
    block_start,
    json_delta,
    message_end,
    message_start,
    sse,
    stop,
    text_delta,
)


@pytest.fixture(autouse=True)
def _quiet_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "false")
    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "false")


def _provider(
    responses: list[httpx.Response],
) -> tuple[AnthropicProviderClient, list[dict]]:
    requests: list[dict[str, Any]] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return queue.pop(0)

    client = AnthropicProviderClient(
        model="claude-haiku-4-5-20251001",
        api_key=SECRET,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return client, requests


def _stream(*events: Any) -> httpx.Response:
    return httpx.Response(
        200, content=sse(*events), headers={"content-type": "text/event-stream"}
    )


async def test_streamed_text_conversation_preserves_ui_event_contract() -> None:
    provider, requests = _provider(
        [
            _stream(
                message_start(),
                TEXT_BLOCK,
                text_delta(0, "Hello "),
                text_delta(0, "operator"),
                stop(0),
                *message_end(),
            )
        ]
    )

    obs = await run_scenario(script=[], provider=provider, user_message="hi there")

    assert obs.event_names() == [
        "agent_message_delta",
        "agent_message_delta",
        "agent_message",
    ]
    assert [e["data"]["text"] for e in obs.events] == [
        "Hello ",
        "operator",
        "Hello operator",
    ]
    assert obs.persisted_messages == [("acceptance", "Hello operator")]
    [request] = requests
    assert request["system"] == "system" or "system" in request["system"]
    assert request["messages"][-1] == {
        "role": "user",
        "content": [{"type": "text", "text": "hi there"}],
    }
    assert SECRET not in obs.everything_externally_visible()


async def test_tool_round_trip_pairs_results_by_tool_use_id() -> None:
    provider, requests = _provider(
        [
            _stream(
                message_start(),
                block_start(
                    0,
                    {
                        "type": "tool_use",
                        "id": "toolu_status",
                        "name": "get_platform_status",
                        "input": {},
                    },
                ),
                json_delta(0, "{}"),
                stop(0),
                *message_end("tool_use"),
            ),
            _stream(
                message_start(),
                TEXT_BLOCK,
                text_delta(0, "Done."),
                stop(0),
                *message_end(),
            ),
        ]
    )

    async def spy(_args: dict, _bridge: Any) -> dict:
        return {"isError": False, "content": [{"type": "text", "text": "ok"}]}

    obs = await run_scenario(
        script=[],
        provider=provider,
        spy_handlers={"get_platform_status": spy},
    )

    assert obs.persisted_messages == [("acceptance", "Done.")]
    assert len(obs.handler_calls["get_platform_status"]) == 1
    assert len(requests) == 2
    assistant, result = requests[1]["messages"][-2:]
    assert assistant["content"][-1]["id"] == "toolu_status"
    assert result["role"] == "user"
    assert result["content"][0]["type"] == "tool_result"
    assert result["content"][0]["tool_use_id"] == "toolu_status"


async def test_prior_history_is_translated_into_the_request() -> None:
    from unittest.mock import MagicMock  # noqa: F401  (history seeded via agent)

    provider, requests = _provider(
        [
            _stream(
                message_start(),
                TEXT_BLOCK,
                text_delta(0, "ok"),
                stop(0),
                *message_end(),
            )
        ]
    )
    from src.services.conversation_runtime.models import (
        ProviderContentPart,
        ProviderInputMessage,
    )
    from src.services.conversation_runtime.runtime_session import (
        ConversationRuntimeSession,
    )

    agent = ConversationRuntimeSession(
        provider=provider,
        system_prompt="SYS",
        interactive_shipping=False,
        session_id="s",
        prior_conversation=[
            {"role": "user", "content": "earlier question"},
            {"role": "assistant", "content": "earlier answer"},
        ],
    )
    await agent.start()
    _ = ProviderInputMessage, ProviderContentPart
    events = [e async for e in agent.process_message_stream("next")]

    assert events[-1] == {"event": "agent_message", "data": {"text": "ok"}}
    body = requests[0]
    assert body["system"] == "SYS"
    assert [(m["role"], m["content"][0]["text"]) for m in body["messages"]] == [
        ("user", "earlier question"),
        ("assistant", "earlier answer"),
        ("user", "next"),
    ]
    assert agent.last_result_metadata.stop_reason == "end_turn"
    assert agent.last_result_metadata.usage["output_tokens"] == 7


@pytest.mark.parametrize(
    ("response", "needle"),
    [
        (
            httpx.Response(401, json={"error": {"type": "authentication_error"}}),
            "ANTHROPIC_API_KEY",
        ),
        (
            httpx.Response(529, json={"error": {"type": "overloaded_error"}}),
            "temporarily unavailable",
        ),
        (
            _stream(message_start(), *message_end("end_turn", out=0)),
            EMPTY_RESPONSE_MESSAGE,
        ),
    ],
)
async def test_failures_surface_safe_actionable_error_event(
    response: httpx.Response, needle: str
) -> None:
    provider, requests = _provider([response])

    obs = await run_scenario(script=[], provider=provider)

    assert obs.event_names() == ["error"]
    assert needle in obs.events[0]["data"]["message"]
    assert obs.persisted_messages == []
    assert SECRET not in obs.everything_externally_visible()
    assert len(requests) == 1  # no silent retry or provider fallback
