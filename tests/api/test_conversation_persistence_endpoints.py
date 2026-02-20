"""HTTP-level tests for conversation persistence endpoints.

Tests the 5 new persistence routes via TestClient, verifying
serialization, status codes, query params, and 404 handling.
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
from src.services.conversation_persistence_service import ConversationPersistenceService


@pytest.fixture
def persistence_db():
    """In-memory SQLite for persistence tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    yield session
    session.close()


@pytest.fixture
def patched_client(persistence_db: Session):
    """TestClient with get_db_context patched to use test DB."""
    from src.api.main import app

    @contextmanager
    def _test_db_context():
        yield persistence_db

    with patch("src.db.connection.get_db_context", _test_db_context):
        with TestClient(app) as c:
            yield c


@pytest.fixture
def seeded_session(persistence_db: Session) -> str:
    """Create a session with messages in the test DB."""
    svc = ConversationPersistenceService(persistence_db)
    svc.create_session(session_id="sess-1", mode="batch")
    svc.save_message("sess-1", "user", "Ship all CA orders via Ground")
    svc.save_message("sess-1", "assistant", "I'll process those orders now.")
    svc.update_session_title("sess-1", "CA Ground Batch")
    return "sess-1"


class TestListConversations:
    """GET /api/v1/conversations/"""

    def test_returns_empty_list(self, patched_client: TestClient):
        """Returns empty list when no sessions exist."""
        resp = patched_client.get("/api/v1/conversations/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_sessions(
        self, patched_client: TestClient, seeded_session: str
    ):
        """Returns session summaries with correct fields."""
        resp = patched_client.get("/api/v1/conversations/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        session = data[0]
        assert session["id"] == "sess-1"
        assert session["title"] == "CA Ground Batch"
        assert session["mode"] == "batch"
        assert session["message_count"] == 2
        assert "created_at" in session
        assert "updated_at" in session

    def test_pagination(
        self,
        patched_client: TestClient,
        persistence_db: Session,
    ):
        """Respects limit and offset query params."""
        svc = ConversationPersistenceService(persistence_db)
        for i in range(5):
            svc.create_session(session_id=f"s-{i}", mode="batch")
        resp = patched_client.get(
            "/api/v1/conversations/", params={"limit": 2, "offset": 1}
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestGetSessionMessages:
    """GET /api/v1/conversations/{id}/messages"""

    def test_returns_messages(
        self, patched_client: TestClient, seeded_session: str
    ):
        """Returns session detail with ordered messages."""
        resp = patched_client.get("/api/v1/conversations/sess-1/messages")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session"]["id"] == "sess-1"
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "assistant"
        assert data["messages"][0]["sequence"] == 1

    def test_404_for_missing(self, patched_client: TestClient):
        """Returns 404 for non-existent session."""
        resp = patched_client.get("/api/v1/conversations/nonexistent/messages")
        assert resp.status_code == 404

    def test_pagination_params(
        self, patched_client: TestClient, seeded_session: str
    ):
        """Respects limit and offset query params."""
        resp = patched_client.get(
            "/api/v1/conversations/sess-1/messages",
            params={"limit": 1, "offset": 1},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 1
        assert data["messages"][0]["role"] == "assistant"


class TestUpdateTitle:
    """PATCH /api/v1/conversations/{id}"""

    def test_updates_title(
        self, patched_client: TestClient, seeded_session: str
    ):
        """Updates session title and returns new value."""
        resp = patched_client.patch(
            "/api/v1/conversations/sess-1",
            json={"title": "New Title"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    def test_404_for_missing(self, patched_client: TestClient):
        """Returns 404 for non-existent session."""
        resp = patched_client.patch(
            "/api/v1/conversations/nonexistent",
            json={"title": "No Session"},
        )
        assert resp.status_code == 404

    def test_rejects_empty_title(
        self, patched_client: TestClient, seeded_session: str
    ):
        """Rejects empty string title (422 validation)."""
        resp = patched_client.patch(
            "/api/v1/conversations/sess-1",
            json={"title": ""},
        )
        assert resp.status_code == 422


class TestExportConversation:
    """GET /api/v1/conversations/{id}/export"""

    def test_exports_json(
        self, patched_client: TestClient, seeded_session: str
    ):
        """Returns downloadable JSON with session and messages."""
        resp = patched_client.get("/api/v1/conversations/sess-1/export")
        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]
        assert "attachment" in resp.headers.get("content-disposition", "")
        data = resp.json()
        assert data["session"]["id"] == "sess-1"
        assert len(data["messages"]) == 2
        assert "exported_at" in data

    def test_404_for_missing(self, patched_client: TestClient):
        """Returns 404 for non-existent session."""
        resp = patched_client.get("/api/v1/conversations/nonexistent/export")
        assert resp.status_code == 404


class TestDeleteConversation:
    """DELETE /api/v1/conversations/{id}"""

    def test_soft_deletes(
        self,
        patched_client: TestClient,
        seeded_session: str,
    ):
        """Soft-deletes session, removing it from active listing."""
        # Session appears in list
        resp = patched_client.get("/api/v1/conversations/")
        assert len(resp.json()) == 1

        # Delete
        resp = patched_client.delete("/api/v1/conversations/sess-1")
        assert resp.status_code == 204

        # No longer in active list
        resp = patched_client.get("/api/v1/conversations/")
        assert len(resp.json()) == 0
