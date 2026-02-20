"""Integration tests for conversation persistence API endpoints.

Tests the persistence service layer directly (not HTTP routes) to verify
the conversation CRUD operations that the new API endpoints depend on.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, ConversationSession


@pytest.fixture
def db_session():
    """In-memory SQLite for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def persistence_svc(db_session):
    """ConversationPersistenceService for seeding test data."""
    from src.services.conversation_persistence_service import (
        ConversationPersistenceService,
    )
    return ConversationPersistenceService(db_session)


class TestListConversations:
    """GET /conversations endpoint."""

    def test_list_returns_sessions(self, persistence_svc, db_session):
        persistence_svc.create_session(session_id="s1", mode="batch")
        persistence_svc.create_session(session_id="s2", mode="interactive")
        sessions = persistence_svc.list_sessions()
        assert len(sessions) == 2

    def test_list_excludes_deleted(self, persistence_svc, db_session):
        persistence_svc.create_session(session_id="s1", mode="batch")
        persistence_svc.soft_delete_session("s1")
        sessions = persistence_svc.list_sessions(active_only=True)
        assert len(sessions) == 0


class TestGetMessages:
    """GET /conversations/{id}/messages endpoint."""

    def test_returns_ordered_messages(self, persistence_svc, db_session):
        persistence_svc.create_session(session_id="s1", mode="batch")
        persistence_svc.save_message("s1", "user", "first")
        persistence_svc.save_message("s1", "assistant", "second")
        result = persistence_svc.get_session_with_messages("s1")
        assert len(result["messages"]) == 2
        assert result["messages"][0]["role"] == "user"

    def test_pagination(self, persistence_svc, db_session):
        persistence_svc.create_session(session_id="s1", mode="batch")
        for i in range(10):
            persistence_svc.save_message("s1", "user", f"msg {i}")
        result = persistence_svc.get_session_with_messages("s1", limit=5)
        assert len(result["messages"]) == 5


class TestSoftDelete:
    """DELETE /conversations/{id} soft delete."""

    def test_soft_deletes(self, persistence_svc, db_session):
        persistence_svc.create_session(session_id="s1", mode="batch")
        persistence_svc.soft_delete_session("s1")
        sess = db_session.get(ConversationSession, "s1")
        assert sess.is_active is False


class TestExport:
    """GET /conversations/{id}/export."""

    def test_exports_json(self, persistence_svc, db_session):
        persistence_svc.create_session(session_id="s1", mode="batch")
        persistence_svc.save_message("s1", "user", "hello")
        export = persistence_svc.export_session_json("s1")
        assert export["session"]["id"] == "s1"
        assert len(export["messages"]) == 1
        assert "exported_at" in export

    def test_export_missing_returns_none(self, persistence_svc):
        assert persistence_svc.export_session_json("nope") is None


class TestUpdateTitle:
    """PATCH /conversations/{id}."""

    def test_updates_title(self, persistence_svc, db_session):
        persistence_svc.create_session(session_id="s1", mode="batch")
        persistence_svc.update_session_title("s1", "Ground Batch")
        sess = db_session.get(ConversationSession, "s1")
        assert sess.title == "Ground Batch"
