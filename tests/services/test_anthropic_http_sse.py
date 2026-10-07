"""Anthropic runtime through the real conversation HTTP route and SSE wire.

Drives the FastAPI app in-process (create -> POST message -> GET stream ->
history) with the runtime chosen purely by environment. Only the outbound
Anthropic transport is mocked (``httpx.MockTransport``). Route, session
manager, runtime selector, provider, SSE serialization and persistence are real.
"""

from __future__ import annotations

import asyncio
import json
import types
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
from src.services.conversation_runtime import anthropic_provider
from tests.services.conversation_runtime.test_anthropic_provider import (
    SECRET,
    TEXT_BLOCK,
    message_end,
    message_start,
    sse,
    stop,
    text_delta,
)

API = "/api/v1/conversations"


@pytest.fixture
def anthropic_wire(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Isolated DB + env-selected Anthropic runtime + mocked Anthropic transport."""
    from src.db import connection

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        connection,
        "SessionLocal",
        sessionmaker(autocommit=False, autoflush=False, bind=engine),
    )
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", "anthropic_messages")
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "false")
    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "false")

    state: dict[str, Any] = {"requests": [], "responses": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(
            {"headers": dict(request.headers), "body": json.loads(request.content)}
        )
        return state["responses"].pop(0)

    mock_transport = httpx.MockTransport(handler)

    class _MockedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = mock_transport
            super().__init__(*args, **kwargs)

    # Module-local shim so only the Anthropic adapter sees the mocked transport.
    monkeypatch.setattr(
        anthropic_provider,
        "httpx",
        types.SimpleNamespace(**{**vars(httpx), "AsyncClient": _MockedAsyncClient}),
    )
    yield state


def _stream_response(*events: Any) -> httpx.Response:
    return httpx.Response(
        200, content=sse(*events), headers={"content-type": "text/event-stream"}
    )


async def _converse(content: str) -> tuple[list[dict], dict, str]:
    """POST a message, read the SSE wire, return (events, history, session_id)."""
    from src.api.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api:
        created = await api.post(f"{API}/")
        assert created.status_code == 201
        session_id = created.json()["session_id"]
        sent = await api.post(f"{API}/{session_id}/messages", json={"content": content})
        assert sent.status_code == 202
        async with asyncio.timeout(20):
            stream = await api.get(f"{API}/{session_id}/stream")
        assert stream.status_code == 200
        assert "text/event-stream" in stream.headers["content-type"]
        events = [
            json.loads(line.removeprefix("data:").strip())
            for line in stream.text.splitlines()
            if line.startswith("data:")
        ]
        history = await api.get(f"{API}/{session_id}/messages")
        assert history.status_code == 200
        await api.delete(f"{API}/{session_id}")
    return events, history.json(), session_id


async def test_env_selected_anthropic_streams_over_real_route_and_sse(
    anthropic_wire: dict[str, Any],
) -> None:
    anthropic_wire["responses"].append(
        _stream_response(
            message_start(),
            TEXT_BLOCK,
            text_delta(0, "Hello "),
            text_delta(0, "operator"),
            stop(0),
            *message_end(),
        )
    )

    events, history, _ = await _converse("hi there")

    assert events == [
        {"event": "agent_message_delta", "data": {"text": "Hello operator"}},
        {"event": "agent_message", "data": {"text": "Hello operator"}},
        {"event": "done", "data": {}},
    ]
    assert [(m["role"], m["content"]) for m in history["messages"]] == [
        ("user", "hi there"),
        ("assistant", "Hello operator"),
    ]
    [request] = anthropic_wire["requests"]
    assert request["headers"]["x-api-key"] == SECRET
    assert request["body"]["stream"] is True
    assert request["body"]["messages"][-1] == {
        "role": "user",
        "content": [{"type": "text", "text": "hi there"}],
    }
    wire = json.dumps(events) + json.dumps(history)
    assert SECRET not in wire


async def test_provider_failure_surfaces_one_safe_error_event_over_sse(
    anthropic_wire: dict[str, Any],
) -> None:
    anthropic_wire["responses"].append(
        httpx.Response(401, json={"error": {"type": "authentication_error"}})
    )

    events, history, _ = await _converse("hi there")

    assert [e["event"] for e in events] == ["error", "done"]
    assert "ANTHROPIC_API_KEY" in events[0]["data"]["message"]
    assert SECRET not in json.dumps(events)
    assert [m["role"] for m in history["messages"]] == ["user"]
    assert len(anthropic_wire["requests"]) == 1
