"""Executed in an SDK-free dependency view by test_sdk_free_runtime.

The application factory, provider adapter, API lifespan/SSE/persistence and CLI
runner are real. Only the external HTTP transport and local data gateway are
synthetic. This is a runtime cutover gate, not a clean-install/package claim.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.util
import json
import sys
import types
from unittest.mock import AsyncMock, patch

import httpx


def assert_sdk_absent():
    assert importlib.util.find_spec("claude_agent_sdk") is None
    try:
        importlib.metadata.distribution("claude-agent-sdk")
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise AssertionError("SDK distribution is installed")
    assert not any(name.startswith("claude_agent_sdk") for name in sys.modules)


async def workflow(surface):
    from src.services.conversation_runtime import anthropic_provider
    from tests.services.conversation_runtime.test_anthropic_provider import (
        TEXT_BLOCK,
        block_start,
        message_end,
        message_start,
        sse,
        stop,
        text_delta,
    )

    replies = [
        sse(
            message_start(),
            block_start(
                0,
                {
                    "type": "tool_use",
                    "id": "source-call",
                    "name": "get_source_info",
                    "input": {},
                },
            ),
            stop(0),
            *message_end("tool_use"),
        ),
        sse(
            message_start(),
            TEXT_BLOCK,
            text_delta(0, "Source has 3 rows."),
            stop(0),
            *message_end(),
        ),
    ]
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, content=replies.pop(0), headers={"content-type": "text/event-stream"}
        )

    class TransportClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(respond)
            super().__init__(*args, **kwargs)

    gateway = AsyncMock()
    gateway.get_source_info_typed.return_value = None
    gateway.get_source_info.return_value = {
        "source_type": "csv",
        "row_count": 3,
        "columns": [],
        "path": "/private/OWNER-SOURCE-CANARY.csv",
    }
    shim = types.SimpleNamespace(**{**vars(httpx), "AsyncClient": TransportClient})
    with (
        patch.object(anthropic_provider, "httpx", shim),
        patch(
            "src.services.conversation_handler.get_data_gateway",
            AsyncMock(return_value=gateway),
        ),
        patch(
            "src.orchestrator.agent.tools.data.get_data_gateway",
            AsyncMock(return_value=gateway),
        ),
    ):
        if surface in {"api", "settings"}:
            from src.api.main import app

            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as api:
                    assert (await api.get("/health")).status_code == 200
                    if surface == "settings":
                        settings = await api.patch(
                            "/api/v1/settings",
                            json={"agent_model": "anthropic:claude-sonnet-4-6"},
                        )
                        assert settings.status_code == 200, settings.text
                    created = await api.post("/api/v1/conversations/")
                    assert created.status_code == 201, created.text
                    sid = created.json()["session_id"]
                    sent = await api.post(
                        f"/api/v1/conversations/{sid}/messages",
                        json={"content": "Describe the source"},
                    )
                    assert sent.status_code == 202, sent.text
                    streamed = await api.get(f"/api/v1/conversations/{sid}/stream")
                    assert streamed.status_code == 200
                    events = [
                        json.loads(line[5:].strip())
                        for line in streamed.text.splitlines()
                        if line.startswith("data:")
                    ]
                    assert any(
                        e["event"] == "tool_call"
                        and e["data"]["tool_name"] == "get_source_info"
                        for e in events
                    ), events
                    assert any(
                        e["event"] == "agent_message"
                        and e["data"]["text"] == "Source has 3 rows."
                        for e in events
                    ), events
                    history = (
                        await api.get(f"/api/v1/conversations/{sid}/messages")
                    ).json()
                    assert [(m["role"], m["content"]) for m in history["messages"]] == [
                        ("user", "Describe the source"),
                        ("assistant", "Source has 3 rows."),
                    ]
                    assert "OWNER-SOURCE-CANARY" not in json.dumps(
                        history
                    ) + json.dumps(events)
                    await api.delete(f"/api/v1/conversations/{sid}")
        else:
            from src.cli.runner import InProcessRunner

            async with InProcessRunner() as runner:
                sid = await runner.create_session()
                events = [
                    event
                    async for event in runner.send_message(sid, "Describe the source")
                ]
                assert any(
                    e.event_type == "tool_call" and e.tool_name == "get_source_info"
                    for e in events
                )
                assert any(
                    e.event_type == "agent_message"
                    and e.content == "Source has 3 rows."
                    for e in events
                ), events
    assert len(requests) == 2
    assert gateway.get_source_info.await_count == 1
    assert requests[0]["model"] == (
        "claude-sonnet-4-6" if surface == "settings" else "claude-haiku-4-5-20251001"
    )
    assert any(
        block.get("tool_use_id") == "source-call"
        for message in requests[1]["messages"]
        for block in message["content"]
    )
    assert "OWNER-SOURCE-CANARY" not in json.dumps(requests)
    assert_sdk_absent()
    print(f"SDK_FREE_{surface.upper()}_WORKFLOW_OK")


if __name__ == "__main__":
    assert_sdk_absent()
    asyncio.run(workflow(sys.argv[1]))
