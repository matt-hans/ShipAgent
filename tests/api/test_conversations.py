"""Tests for conversations SSE route.

Tests the CRUD operations and basic SSE endpoint registration for the
new agent-driven conversation flow.
"""

from unittest.mock import AsyncMock, patch

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
