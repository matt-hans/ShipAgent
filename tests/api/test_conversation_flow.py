"""Integration tests for the agent-driven conversation flow.

Verifies the full lifecycle: create session → send message → verify
history → cleanup. Uses the FastAPI TestClient against the real app
with mocked agent internals.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


class TestConversationCRUD:
    """Full CRUD lifecycle for conversation sessions."""

    def test_create_and_delete(self):
        """Create a session, verify it exists, delete it, verify gone."""
        # Create
        create_resp = client.post("/api/v1/conversations/")
        assert create_resp.status_code == 201
        session_id = create_resp.json()["session_id"]
        assert isinstance(session_id, str)
        assert len(session_id) > 0

        # Verify history accessible (empty)
        history_resp = client.get(f"/api/v1/conversations/{session_id}/history")
        assert history_resp.status_code == 200
        assert history_resp.json()["messages"] == []

        # Delete
        delete_resp = client.delete(f"/api/v1/conversations/{session_id}")
        assert delete_resp.status_code == 204

        # Verify gone
        send_resp = client.post(
            f"/api/v1/conversations/{session_id}/messages",
            json={"content": "test"},
        )
        assert send_resp.status_code == 404

    def test_multiple_sessions_isolated(self):
        """Messages in one session don't appear in another."""
        r1 = client.post("/api/v1/conversations/")
        r2 = client.post("/api/v1/conversations/")
        sid1 = r1.json()["session_id"]
        sid2 = r2.json()["session_id"]
        assert sid1 != sid2

        # Send message to session 1
        client.post(
            f"/api/v1/conversations/{sid1}/messages",
            json={"content": "Hello from session 1"},
        )

        # Session 2 history should be empty
        h2 = client.get(f"/api/v1/conversations/{sid2}/history")
        assert len(h2.json()["messages"]) == 0

        # Session 1 history should have the message
        h1 = client.get(f"/api/v1/conversations/{sid1}/history")
        assert len(h1.json()["messages"]) >= 1
        assert h1.json()["messages"][0]["content"] == "Hello from session 1"


class TestConversationMessageFlow:
    """Tests for sending messages and verifying history."""

    def test_send_message_accepted(self):
        """Sending a message returns 202 with session_id."""
        create_resp = client.post("/api/v1/conversations/")
        session_id = create_resp.json()["session_id"]

        resp = client.post(
            f"/api/v1/conversations/{session_id}/messages",
            json={"content": "Ship all CA orders via Ground"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["session_id"] == session_id

    def test_message_stored_in_history(self):
        """User messages appear in conversation history."""
        create_resp = client.post("/api/v1/conversations/")
        session_id = create_resp.json()["session_id"]

        client.post(
            f"/api/v1/conversations/{session_id}/messages",
            json={"content": "Rate check for overnight"},
        )

        history = client.get(f"/api/v1/conversations/{session_id}/history")
        messages = history.json()["messages"]
        assert len(messages) >= 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Rate check for overnight"

    def test_multiple_messages_ordered(self):
        """Multiple messages appear in order."""
        create_resp = client.post("/api/v1/conversations/")
        session_id = create_resp.json()["session_id"]

        for msg in ["First message", "Second message", "Third message"]:
            client.post(
                f"/api/v1/conversations/{session_id}/messages",
                json={"content": msg},
            )

        history = client.get(f"/api/v1/conversations/{session_id}/history")
        messages = history.json()["messages"]
        user_messages = [m for m in messages if m["role"] == "user"]
        assert len(user_messages) >= 3
        assert user_messages[0]["content"] == "First message"
        assert user_messages[1]["content"] == "Second message"
        assert user_messages[2]["content"] == "Third message"

    def test_empty_message_rejected(self):
        """Empty message content is rejected by validation."""
        create_resp = client.post("/api/v1/conversations/")
        session_id = create_resp.json()["session_id"]

        resp = client.post(
            f"/api/v1/conversations/{session_id}/messages",
            json={"content": ""},
        )
        assert resp.status_code == 422  # Pydantic validation error


class TestConversationNotFound:
    """Tests for 404 handling on nonexistent sessions."""

    def test_send_to_nonexistent(self):
        """Sending to a nonexistent session returns 404."""
        resp = client.post(
            "/api/v1/conversations/nonexistent-session/messages",
            json={"content": "test"},
        )
        assert resp.status_code == 404

    def test_history_nonexistent(self):
        """Getting history for nonexistent session returns 404."""
        resp = client.get("/api/v1/conversations/nonexistent-session/history")
        assert resp.status_code == 404

    def test_delete_nonexistent_idempotent(self):
        """Deleting nonexistent session returns 204 (idempotent)."""
        resp = client.delete("/api/v1/conversations/nonexistent-session")
        assert resp.status_code == 204


class TestConversationCleanup:
    """Tests for session cleanup and resource management."""

    def test_delete_cleans_history(self):
        """Deleting a session removes its history."""
        create_resp = client.post("/api/v1/conversations/")
        session_id = create_resp.json()["session_id"]

        # Send a message
        client.post(
            f"/api/v1/conversations/{session_id}/messages",
            json={"content": "test message"},
        )

        # Delete
        client.delete(f"/api/v1/conversations/{session_id}")

        # History should be gone (404)
        resp = client.get(f"/api/v1/conversations/{session_id}/history")
        assert resp.status_code == 404

    def test_recreate_after_delete(self):
        """Can create a new session after deleting one."""
        # Create and delete
        r1 = client.post("/api/v1/conversations/")
        sid1 = r1.json()["session_id"]
        client.delete(f"/api/v1/conversations/{sid1}")

        # Create new
        r2 = client.post("/api/v1/conversations/")
        sid2 = r2.json()["session_id"]
        assert sid1 != sid2

        # New session works
        resp = client.post(
            f"/api/v1/conversations/{sid2}/messages",
            json={"content": "new session message"},
        )
        assert resp.status_code == 202
