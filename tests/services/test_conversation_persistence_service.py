"""Tests for ConversationPersistenceService."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, ConversationSession, MessageType
from src.services.conversation_persistence_service import (
    ConversationPersistenceService,
)


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
def svc(db_session: Session):
    """Service under test."""
    return ConversationPersistenceService(db_session)


class TestCreateSession:
    def test_creates_batch_session(self, svc, db_session):
        sess = svc.create_session(session_id="test-1", mode="batch")
        assert sess.id == "test-1"
        assert sess.mode == "batch"
        assert sess.is_active is True

    def test_creates_interactive_session(self, svc, db_session):
        sess = svc.create_session(session_id="test-2", mode="interactive")
        assert sess.mode == "interactive"

    def test_stores_context_data(self, svc, db_session):
        ctx = {"data_source_id": "abc", "agent_source_hash": "xyz"}
        sess = svc.create_session(
            session_id="test-3", mode="batch", context_data=ctx,
        )
        loaded = json.loads(sess.context_data)
        assert loaded["data_source_id"] == "abc"


class TestSaveMessage:
    def test_saves_user_message(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        msg = svc.save_message("s1", role="user", content="Hello")
        assert msg.role == "user"
        assert msg.sequence == 1
        assert msg.message_type == MessageType.text.value

    def test_auto_increments_sequence(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        m1 = svc.save_message("s1", role="user", content="First")
        m2 = svc.save_message("s1", role="assistant", content="Second")
        assert m1.sequence == 1
        assert m2.sequence == 2

    def test_saves_artifact_message(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        metadata = {"action": "preview", "jobId": "j1"}
        msg = svc.save_message(
            "s1", role="system", content="Preview ready",
            message_type=MessageType.system_artifact.value,
            metadata=metadata,
        )
        assert msg.message_type == MessageType.system_artifact.value
        loaded = json.loads(msg.metadata_json)
        assert loaded["jobId"] == "j1"

    def test_updates_session_updated_at(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        svc.save_message("s1", role="user", content="test")
        sess = db_session.get(ConversationSession,"s1")
        assert sess.updated_at is not None


class TestListSessions:
    def test_lists_active_sessions(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        svc.create_session(session_id="s2", mode="interactive")
        svc.save_message("s1", role="user", content="msg")
        results = svc.list_sessions()
        assert len(results) == 2

    def test_excludes_inactive(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        svc.soft_delete_session("s1")
        results = svc.list_sessions(active_only=True)
        assert len(results) == 0

    def test_includes_message_count(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        svc.save_message("s1", role="user", content="a")
        svc.save_message("s1", role="assistant", content="b")
        results = svc.list_sessions()
        assert results[0]["message_count"] == 2


class TestGetSessionWithMessages:
    def test_returns_ordered_messages(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        svc.save_message("s1", role="user", content="first")
        svc.save_message("s1", role="assistant", content="second")
        result = svc.get_session_with_messages("s1")
        assert result is not None
        assert len(result["messages"]) == 2
        assert result["messages"][0]["content"] == "first"
        assert result["messages"][1]["content"] == "second"

    def test_pagination(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        for i in range(10):
            svc.save_message("s1", role="user", content=f"msg {i}")
        result = svc.get_session_with_messages("s1", limit=3, offset=2)
        assert len(result["messages"]) == 3
        assert result["messages"][0]["content"] == "msg 2"

    def test_returns_none_for_missing(self, svc, db_session):
        result = svc.get_session_with_messages("nonexistent")
        assert result is None


class TestUpdateTitle:
    def test_updates_title(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        svc.update_session_title("s1", "Ground Batch - Q3")
        sess = db_session.get(ConversationSession,"s1")
        assert sess.title == "Ground Batch - Q3"


class TestUpdateContext:
    def test_updates_context(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        svc.update_session_context("s1", {"source": "new.csv"})
        sess = db_session.get(ConversationSession,"s1")
        loaded = json.loads(sess.context_data)
        assert loaded["source"] == "new.csv"


class TestSoftDelete:
    def test_soft_deletes(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        svc.soft_delete_session("s1")
        sess = db_session.get(ConversationSession,"s1")
        assert sess.is_active is False


class TestTitleGeneration:
    def test_title_updates_after_generation(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        svc.save_message("s1", "user", "Ship all CA orders via Ground")
        svc.save_message("s1", "assistant", "I'll help ship those orders.")
        svc.update_session_title("s1", "Ground Batch - CA Orders")
        sess = db_session.get(ConversationSession, "s1")
        assert sess.title == "Ground Batch - CA Orders"


class TestExport:
    def test_exports_full_session(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        svc.save_message("s1", role="user", content="hello")
        svc.save_message("s1", role="assistant", content="hi")
        export = svc.export_session_json("s1")
        assert export["session"]["id"] == "s1"
        assert len(export["messages"]) == 2

    def test_export_missing_returns_none(self, svc, db_session):
        assert svc.export_session_json("nope") is None
