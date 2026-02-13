"""Tests for conversations SSE route.

Tests the CRUD operations and basic SSE endpoint registration for the
new agent-driven conversation flow.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


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
        mock_source_info = MagicMock()
        mock_source_info.source_type = "csv"

        with patch(
            "src.services.data_source_service.DataSourceService.get_instance",
        ) as mock_get_instance, patch(
            "src.api.routes.conversations.asyncio.create_task",
        ) as mock_create_task:
            mock_svc = MagicMock()
            mock_svc.get_source_info.return_value = mock_source_info
            mock_get_instance.return_value = mock_svc
            mock_task = MagicMock()
            mock_task.done.return_value = False
            mock_create_task.return_value = mock_task

            response = client.post("/api/v1/conversations/")

        assert response.status_code == 201
        mock_create_task.assert_called_once()


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


@pytest.mark.asyncio
async def test_shutdown_event_calls_cached_ups_cleanup():
    """API shutdown hook tears down cached UPS MCP client."""
    from src.api.main import shutdown_event

    with patch(
        "src.orchestrator.agent.tools_v2.shutdown_cached_ups_client",
        new=AsyncMock(),
    ) as mock_shutdown:
        await shutdown_event()
        mock_shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_prewarm_and_first_message_do_not_double_create_agent():
    """Session lock prevents double agent creation during prewarm + first message race."""
    from src.api.routes import conversations

    class _FakeAgent:
        last_turn_count = 0

        async def process_message_stream(self, _content):
            if False:
                yield {}

    session_id = "race-test-session"
    session = conversations._session_manager.get_or_create_session(session_id)

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

    mock_svc = MagicMock()
    mock_svc.get_source_info.return_value = mock_source_info

    with patch(
        "src.services.data_source_service.DataSourceService.get_instance",
        return_value=mock_svc,
    ), patch(
        "src.api.routes.conversations._ensure_agent",
        new=AsyncMock(side_effect=_fake_ensure_agent),
    ):
        await asyncio.gather(
            conversations._prewarm_session_agent(session_id),
            conversations._process_agent_message(session_id, "Ship all orders"),
        )

    assert creation_count == 1
    conversations._session_manager.remove_session(session_id)
    conversations._event_queues.pop(session_id, None)
