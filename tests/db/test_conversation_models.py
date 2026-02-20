"""Tests for ConversationSession and ConversationMessage models."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import (
    Base,
    ConversationMessage,
    ConversationSession,
    MessageType,
    generate_uuid,
    utc_now_iso,
)


@pytest.fixture
def db_session():
    """Create an in-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


class TestMessageTypeEnum:
    """MessageType enum values and str inheritance."""

    def test_text_value(self):
        assert MessageType.text.value == "text"

    def test_system_artifact_value(self):
        assert MessageType.system_artifact.value == "system_artifact"

    def test_error_value(self):
        assert MessageType.error.value == "error"

    def test_tool_call_value(self):
        assert MessageType.tool_call.value == "tool_call"

    def test_is_string(self):
        assert isinstance(MessageType.text, str)


class TestConversationSession:
    """ConversationSession model CRUD."""

    def test_create_session_defaults(self, db_session: Session):
        session = ConversationSession(id=generate_uuid())
        db_session.add(session)
        db_session.commit()

        assert session.mode == "batch"
        assert session.is_active is True
        assert session.title is None
        assert session.context_data is None
        assert session.created_at is not None

    def test_create_session_interactive(self, db_session: Session):
        session = ConversationSession(
            id=generate_uuid(),
            mode="interactive",
            title="Test Session",
        )
        db_session.add(session)
        db_session.commit()

        assert session.mode == "interactive"
        assert session.title == "Test Session"

    def test_soft_delete(self, db_session: Session):
        session = ConversationSession(id=generate_uuid())
        db_session.add(session)
        db_session.commit()

        session.is_active = False
        db_session.commit()

        result = db_session.query(ConversationSession).filter_by(
            is_active=True
        ).all()
        assert len(result) == 0

    def test_context_data_json(self, db_session: Session):
        import json
        ctx = json.dumps({"data_source_id": "abc", "agent_source_hash": "xyz"})
        session = ConversationSession(id=generate_uuid(), context_data=ctx)
        db_session.add(session)
        db_session.commit()

        loaded = json.loads(session.context_data)
        assert loaded["data_source_id"] == "abc"
        assert loaded["agent_source_hash"] == "xyz"


class TestConversationMessage:
    """ConversationMessage model CRUD and relationships."""

    def _make_session(self, db_session: Session) -> ConversationSession:
        s = ConversationSession(id=generate_uuid())
        db_session.add(s)
        db_session.commit()
        return s

    def test_create_message(self, db_session: Session):
        s = self._make_session(db_session)
        msg = ConversationMessage(
            id=generate_uuid(),
            session_id=s.id,
            role="user",
            content="Ship all CA orders",
            sequence=1,
        )
        db_session.add(msg)
        db_session.commit()

        assert msg.message_type == MessageType.text.value
        assert msg.role == "user"
        assert msg.sequence == 1

    def test_message_types(self, db_session: Session):
        s = self._make_session(db_session)
        for i, mt in enumerate(MessageType):
            msg = ConversationMessage(
                id=generate_uuid(),
                session_id=s.id,
                role="system",
                message_type=mt.value,
                content=f"test {mt.value}",
                sequence=i,
            )
            db_session.add(msg)
        db_session.commit()

        msgs = db_session.query(ConversationMessage).filter_by(
            session_id=s.id
        ).order_by(ConversationMessage.sequence).all()
        assert len(msgs) == len(MessageType)

    def test_relationship_cascade_delete(self, db_session: Session):
        s = self._make_session(db_session)
        for i in range(3):
            db_session.add(ConversationMessage(
                id=generate_uuid(),
                session_id=s.id,
                role="user",
                content=f"msg {i}",
                sequence=i,
            ))
        db_session.commit()

        db_session.delete(s)
        db_session.commit()

        remaining = db_session.query(ConversationMessage).all()
        assert len(remaining) == 0

    def test_ordering_by_sequence(self, db_session: Session):
        s = self._make_session(db_session)
        for seq in [3, 1, 2]:
            db_session.add(ConversationMessage(
                id=generate_uuid(),
                session_id=s.id,
                role="user",
                content=f"seq {seq}",
                sequence=seq,
            ))
        db_session.commit()

        msgs = db_session.query(ConversationMessage).filter_by(
            session_id=s.id
        ).order_by(ConversationMessage.sequence).all()
        assert [m.sequence for m in msgs] == [1, 2, 3]

    def test_metadata_json_nullable(self, db_session: Session):
        s = self._make_session(db_session)
        msg = ConversationMessage(
            id=generate_uuid(),
            session_id=s.id,
            role="assistant",
            content="Done",
            sequence=1,
            metadata_json=None,
        )
        db_session.add(msg)
        db_session.commit()
        assert msg.metadata_json is None
