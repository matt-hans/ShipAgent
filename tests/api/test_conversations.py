"""Tests for conversations SSE route.

Tests the CRUD operations and basic SSE endpoint registration for the
new agent-driven conversation flow.
"""

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_batch_heuristic_avoids_false_positive_for_personal_phrase():
    """'ship orders to my brother' should not auto-switch to batch mode."""
    from src.orchestrator.agent.intent_detection import is_batch_shipping_request

    assert not is_batch_shipping_request("I want to ship orders to my brother")


def test_batch_heuristic_detects_plural_filtered_command():
    """Plural + filter cues should be treated as batch shipping."""
    from src.orchestrator.agent.intent_detection import is_batch_shipping_request

    assert is_batch_shipping_request(
        "Ship orders to customers in CA where status is unfulfilled",
    )


class TestCreateConversation:
    """Tests for POST /api/v1/conversations/."""

    def test_create_conversation(self):
        """Creates a new conversation session and returns session_id."""
        response = client.post("/api/v1/conversations/")
        assert response.status_code == 201
        data = response.json()
        assert "session_id" in data
        assert isinstance(data["session_id"], str)
        assert len(data["session_id"]) > 0

    def test_create_multiple_conversations(self):
        """Each call creates a unique session."""
        r1 = client.post("/api/v1/conversations/")
        r2 = client.post("/api/v1/conversations/")
        assert r1.json()["session_id"] != r2.json()["session_id"]

    def test_create_conversation_schedules_prewarm_when_source_exists(self):
        """Prewarm task is scheduled when an active source is available."""
        mock_gw = AsyncMock()
        mock_gw.get_source_info = AsyncMock(
            return_value={"active": True, "source_type": "csv"}
        )

        with (
            patch(
                "src.services.gateway_provider.get_data_gateway_if_connected",
                return_value=mock_gw,
            ),
            patch(
                "src.api.routes.conversations.asyncio.create_task",
            ) as mock_create_task,
        ):
            mock_task = MagicMock()
            mock_task.done.return_value = False
            def _fake_create_task(coro):
                coro.close()
                return mock_task

            mock_create_task.side_effect = _fake_create_task

            response = client.post("/api/v1/conversations/")

        assert response.status_code == 201
        mock_create_task.assert_called_once()

    def test_create_conversation_skips_prewarm_in_interactive_mode(self):
        """Interactive sessions should not schedule prewarm even when source exists."""
        mock_gw = AsyncMock()
        mock_gw.get_source_info = AsyncMock(
            return_value={"active": True, "source_type": "csv"}
        )

        with (
            patch(
                "src.services.gateway_provider.get_data_gateway_if_connected",
                return_value=mock_gw,
            ),
            patch(
                "src.api.routes.conversations.asyncio.create_task",
            ) as mock_create_task,
        ):
            response = client.post(
                "/api/v1/conversations/",
                json={"interactive_shipping": True},
            )

        assert response.status_code == 201
        assert response.json()["interactive_shipping"] is True
        mock_create_task.assert_not_called()


class TestSendMessage:
    """Tests for POST /api/v1/conversations/{id}/messages."""

    def test_send_message(self):
        """Sending a message returns 202 accepted."""
        # Create session first
        create_resp = client.post("/api/v1/conversations/")
        session_id = create_resp.json()["session_id"]

        response = client.post(
            f"/api/v1/conversations/{session_id}/messages",
            json={"content": "Ship CA orders via Ground"},
        )
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["session_id"] == session_id

    def test_send_to_nonexistent_returns_404(self):
        """Sending to a nonexistent session returns 404."""
        response = client.post(
            "/api/v1/conversations/nonexistent-id/messages",
            json={"content": "test"},
        )
        assert response.status_code == 404

    def test_message_stored_in_history(self):
        """Messages are stored in session history."""
        create_resp = client.post("/api/v1/conversations/")
        session_id = create_resp.json()["session_id"]

        client.post(
            f"/api/v1/conversations/{session_id}/messages",
            json={"content": "Ship CA orders"},
        )

        # Get history
        history_resp = client.get(f"/api/v1/conversations/{session_id}/history")
        assert history_resp.status_code == 200
        data = history_resp.json()
        assert len(data["messages"]) >= 1
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "Ship CA orders"


class TestStreamEndpoint:
    """Tests for GET /api/v1/conversations/{id}/stream."""

    def test_stream_endpoint_exists(self):
        """Stream endpoint returns SSE content type."""
        from src.api.routes.conversations import _get_event_queue

        create_resp = client.post("/api/v1/conversations/")
        session_id = create_resp.json()["session_id"]
        # Ensure stream yields immediately and closes for deterministic test timing.
        _get_event_queue(session_id).put_nowait({"event": "done", "data": {}})

        # Use stream=True to avoid hanging on long-running SSE
        with client.stream(
            "GET", f"/api/v1/conversations/{session_id}/stream"
        ) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

    def test_stream_nonexistent_returns_404(self):
        """Stream for nonexistent session returns 404."""
        response = client.get("/api/v1/conversations/nonexistent/stream")
        assert response.status_code == 404


class TestDeleteConversation:
    """Tests for DELETE /api/v1/conversations/{id}."""

    def test_delete_conversation(self):
        """Deleting a conversation returns 204."""
        create_resp = client.post("/api/v1/conversations/")
        session_id = create_resp.json()["session_id"]

        response = client.delete(f"/api/v1/conversations/{session_id}")
        assert response.status_code == 204

    def test_delete_nonexistent_is_idempotent(self):
        """Deleting a nonexistent session returns 204 (idempotent)."""
        response = client.delete("/api/v1/conversations/nonexistent-id")
        assert response.status_code == 204

    def test_send_after_delete_returns_404(self):
        """Sending to a deleted session returns 404."""
        create_resp = client.post("/api/v1/conversations/")
        session_id = create_resp.json()["session_id"]

        client.delete(f"/api/v1/conversations/{session_id}")

        response = client.post(
            f"/api/v1/conversations/{session_id}/messages",
            json={"content": "test"},
        )
        assert response.status_code == 404

    def test_delete_cancels_prewarm_task(self):
        """Delete route cancels prewarm task before removing session."""
        create_resp = client.post("/api/v1/conversations/")
        session_id = create_resp.json()["session_id"]

        with patch(
            "src.api.routes.conversations._session_manager.cancel_session_prewarm_task",
            new=AsyncMock(),
        ) as mock_cancel:
            response = client.delete(f"/api/v1/conversations/{session_id}")

        assert response.status_code == 204
        mock_cancel.assert_awaited_once_with(session_id)


class TestTerminatingSessionGuard:
    """Tests for session terminating race condition guard."""

    def test_send_message_to_terminating_session_returns_409(self):
        """Sending to a terminating session returns 409 Conflict."""
        create_resp = client.post("/api/v1/conversations/")
        session_id = create_resp.json()["session_id"]

        # Mark the session as terminating
        from src.api.routes.conversations import _session_manager
        session = _session_manager.get_session(session_id)
        assert session is not None
        session.terminating = True

        response = client.post(
            f"/api/v1/conversations/{session_id}/messages",
            json={"content": "test"},
        )
        assert response.status_code == 409
        assert "terminated" in response.json()["detail"].lower() or "terminating" in response.json()["detail"].lower()

        # Clean up
        session.terminating = False
        _session_manager.remove_session(session_id)


@pytest.mark.asyncio
async def test_shutdown_event_calls_gateway_shutdown(monkeypatch):
    """API lifespan shutdown phase tears down all gateway clients."""
    from src.api.main import lifespan

    mock_app = MagicMock()
    monkeypatch.setenv("FILTER_TOKEN_SECRET", "x" * 40)

    with patch(
        "src.api.main._ensure_agent_sdk_available",
    ), patch(
        "src.api.main.init_db",
    ), patch(
        "src.api.main.run_startup_recovery", new=AsyncMock(),
    ), patch(
        "src.services.gateway_provider.shutdown_gateways",
        new=AsyncMock(),
    ) as mock_shutdown:
        async with lifespan(mock_app):
            pass  # simulate app running
        mock_shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_prewarm_and_first_message_do_not_double_create_agent():
    """Session lock prevents double agent creation during prewarm + first message race."""
    from src.api.routes import conversations

    class _FakeAgent:
        last_turn_count = 0
        emitter_bridge = SimpleNamespace(callback=None)

        async def process_message_stream(self, _content):
            if False:
                yield {}

    session_id = "race-test-session"
    conversations._session_manager.get_or_create_session(session_id)

    creation_count = 0

    async def _fake_ensure_agent(sess, _source_info):
        nonlocal creation_count
        if sess.agent is None:
            creation_count += 1
            sess.agent = _FakeAgent()
            sess.agent_source_hash = "hash"
            return True
        return False

    mock_source_info = MagicMock()
    mock_source_info.source_type = "csv"
    mock_source_info.file_path = "/tmp/orders.csv"
    mock_source_info.row_count = 1
    mock_source_info.columns = []

    mock_gw = AsyncMock()
    mock_gw.get_source_info_typed = AsyncMock(return_value=mock_source_info)

    with (
        patch(
            "src.services.gateway_provider.get_data_gateway",
            new=AsyncMock(return_value=mock_gw),
        ),
        patch(
            "src.api.routes.conversations._ensure_agent",
            new=AsyncMock(side_effect=_fake_ensure_agent),
        ),
    ):
        await asyncio.gather(
            conversations._prewarm_session_agent(session_id),
            conversations._process_agent_message(session_id, "Ship all orders"),
        )

    assert creation_count == 1
    conversations._session_manager.remove_session(session_id)
    conversations._event_queues.pop(session_id, None)


@pytest.mark.asyncio
async def test_process_message_uses_gateway_for_source_info():
    """_process_agent_message uses DataSourceGateway for source info."""
    from src.api.routes import conversations as conversations_mod
    conversations = importlib.reload(conversations_mod)

    class _FakeAgent:
        last_turn_count = 0
        emitter_bridge = SimpleNamespace(callback=None)

        async def process_message_stream(self, _content):
            if False:
                yield {}

    session_id = "gateway-usage-test"
    conversations._session_manager.get_or_create_session(session_id)

    mock_source_info = MagicMock()
    mock_source_info.source_type = "csv"
    mock_source_info.file_path = "/tmp/orders.csv"
    mock_source_info.row_count = 1
    mock_source_info.columns = []

    mock_gw = AsyncMock()
    mock_gw.get_source_info_typed = AsyncMock(return_value=mock_source_info)

    async def _fake_ensure_agent(sess, _source_info):
        sess.agent = _FakeAgent()
        sess.agent_source_hash = "hash"
        return True

    with (
        patch(
            "src.services.gateway_provider.get_data_gateway",
            new=AsyncMock(return_value=mock_gw),
        ),
        patch(
            "src.api.routes.conversations._ensure_agent",
            new=AsyncMock(side_effect=_fake_ensure_agent),
        ),
    ):
        await conversations._process_agent_message(session_id, "Ship one package")

    mock_gw.get_source_info_typed.assert_awaited_once()
    conversations._session_manager.remove_session(session_id)
    conversations._event_queues.pop(session_id, None)


@pytest.mark.asyncio
async def test_process_message_auto_switches_interactive_to_batch_for_batch_command():
    """Interactive sessions auto-switch to batch mode for batch shipping commands."""
    from src.api.routes import conversations as conversations_mod
    conversations = importlib.reload(conversations_mod)

    class _FakeAgent:
        last_turn_count = 0
        emitter_bridge = SimpleNamespace(callback=None)

        async def process_message_stream(self, _content):
            if False:
                yield {}

    session_id = "auto-switch-batch-mode"
    session = conversations._session_manager.get_or_create_session(session_id)
    session.interactive_shipping = True

    mock_source_info = MagicMock()
    mock_source_info.source_type = "csv"
    mock_source_info.file_path = "/tmp/orders.csv"
    mock_source_info.row_count = 100
    mock_source_info.columns = []

    mock_gw = AsyncMock()
    mock_gw.get_source_info_typed = AsyncMock(return_value=mock_source_info)

    observed_modes: list[bool] = []

    async def _fake_ensure_agent(sess, _source_info):
        observed_modes.append(sess.interactive_shipping)
        sess.agent = _FakeAgent()
        sess.agent_source_hash = "hash"
        return True

    with (
        patch(
            "src.services.gateway_provider.get_data_gateway",
            new=AsyncMock(return_value=mock_gw),
        ),
        patch(
            "src.api.routes.conversations._ensure_agent",
            new=AsyncMock(side_effect=_fake_ensure_agent),
        ),
    ):
        await conversations._process_agent_message(
            session_id,
            "Ship all orders going to companies in the Northeast.",
        )

    assert observed_modes == [False]
    assert session.interactive_shipping is False
    conversations._session_manager.remove_session(session_id)
    conversations._event_queues.pop(session_id, None)


@pytest.mark.asyncio
async def test_process_message_suppresses_transient_messages_when_artifact_emitted(
    monkeypatch,
):
    """Transient agent_message events are hidden when an artifact event is emitted."""
    from src.api.routes import conversations as conversations_mod
    conversations = importlib.reload(conversations_mod)

    monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "true")

    class _FakeAgent:
        last_turn_count = 0
        emitter_bridge = SimpleNamespace(callback=None)

        async def process_message_stream(self, _content):
            if self.emitter_bridge.callback:
                self.emitter_bridge.callback(
                    "preview_ready",
                    {"job_id": "job-1", "total_rows": 1, "preview_rows": []},
                )
            yield {"event": "agent_message", "data": {"text": "Let me try one approach"}}
            yield {"event": "agent_message", "data": {"text": "Let me try another approach"}}

    session_id = "suppress-transient-preview"
    conversations._session_manager.get_or_create_session(session_id)

    mock_source_info = MagicMock()
    mock_source_info.source_type = "csv"
    mock_source_info.file_path = "/tmp/orders.csv"
    mock_source_info.row_count = 10
    mock_source_info.columns = []

    mock_gw = AsyncMock()
    mock_gw.get_source_info_typed = AsyncMock(return_value=mock_source_info)

    async def _fake_ensure_agent(sess, _source_info):
        sess.agent = _FakeAgent()
        sess.agent_source_hash = "hash"
        return True

    with (
        patch(
            "src.services.gateway_provider.get_data_gateway",
            new=AsyncMock(return_value=mock_gw),
        ),
        patch(
            "src.api.routes.conversations._ensure_agent",
            new=AsyncMock(side_effect=_fake_ensure_agent),
        ),
    ):
        await conversations._process_agent_message(session_id, "Ship all orders")

    queue = conversations._event_queues[session_id]
    queued_events = []
    while not queue.empty():
        queued_events.append(await queue.get())

    event_names = [event.get("event") for event in queued_events]
    assert "preview_ready" in event_names
    assert "agent_message" not in event_names

    history = conversations._session_manager.get_history(session_id)
    assert all(msg.get("role") != "assistant" for msg in history)

    conversations._session_manager.remove_session(session_id)
    conversations._event_queues.pop(session_id, None)


@pytest.mark.asyncio
async def test_process_message_keeps_final_message_when_no_artifact(monkeypatch):
    """Without artifact events, only the final buffered agent message is emitted."""
    from src.api.routes import conversations as conversations_mod
    conversations = importlib.reload(conversations_mod)

    monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "true")

    class _FakeAgent:
        last_turn_count = 0
        emitter_bridge = SimpleNamespace(callback=None)

        async def process_message_stream(self, _content):
            yield {"event": "agent_message", "data": {"text": "First attempt"}}
            yield {"event": "agent_message", "data": {"text": "Final answer"}}

    session_id = "buffer-final-no-artifact"
    conversations._session_manager.get_or_create_session(session_id)

    mock_source_info = MagicMock()
    mock_source_info.source_type = "csv"
    mock_source_info.file_path = "/tmp/orders.csv"
    mock_source_info.row_count = 10
    mock_source_info.columns = []

    mock_gw = AsyncMock()
    mock_gw.get_source_info_typed = AsyncMock(return_value=mock_source_info)

    async def _fake_ensure_agent(sess, _source_info):
        sess.agent = _FakeAgent()
        sess.agent_source_hash = "hash"
        return True

    with (
        patch(
            "src.services.gateway_provider.get_data_gateway",
            new=AsyncMock(return_value=mock_gw),
        ),
        patch(
            "src.api.routes.conversations._ensure_agent",
            new=AsyncMock(side_effect=_fake_ensure_agent),
        ),
    ):
        await conversations._process_agent_message(session_id, "hello")

    queue = conversations._event_queues[session_id]
    queued_events = []
    while not queue.empty():
        queued_events.append(await queue.get())

    agent_messages = [e for e in queued_events if e.get("event") == "agent_message"]
    assert len(agent_messages) == 1
    assert agent_messages[0]["data"]["text"] == "Final answer"

    history = conversations._session_manager.get_history(session_id)
    assistant_history = [msg for msg in history if msg.get("role") == "assistant"]
    assert len(assistant_history) == 1
    assert assistant_history[0]["content"] == "Final answer"

    conversations._session_manager.remove_session(session_id)
    conversations._event_queues.pop(session_id, None)
