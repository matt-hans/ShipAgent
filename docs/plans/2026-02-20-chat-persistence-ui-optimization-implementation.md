# Chat Persistence & UI Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transition ShipAgent chat from ephemeral in-memory sessions to database-backed persistent conversations with full resume, visual timeline minimap, copy-to-clipboard, and sidebar chat session management.

**Architecture:** DB-persisted messages + system prompt re-injection for agent resume. Backend owns all persistence (messages saved in route handlers, not frontend). Frontend is display-only for history. Visual timeline uses IntersectionObserver on message elements.

**Tech Stack:** SQLAlchemy 2.0 (Mapped types), FastAPI, React, TypeScript, OKLCH design system, shadcn/ui patterns.

---

## Task 1: Database Models — ConversationSession & ConversationMessage

**Files:**
- Modify: `src/db/models.py:691` (append after CustomCommand)

**Step 1: Write failing tests for the new models**

Create `tests/db/test_conversation_models.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_conversation_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'ConversationSession' from 'src.db.models'`

**Step 3: Implement the models**

Add to `src/db/models.py` after line 691 (after `CustomCommand`):

```python
class MessageType(str, Enum):
    """Type classification for conversation messages.

    Used by the visual timeline to determine dot color without
    parsing metadata JSON.
    """

    text = "text"
    system_artifact = "system_artifact"
    error = "error"
    tool_call = "tool_call"


class ConversationSession(Base):
    """Persistent conversation session.

    Stores session metadata including mode, title, and context data
    (active data source, source hash) for context-aware resume.

    Attributes:
        id: UUID primary key (same as runtime session_id).
        title: Agent-generated title (nullable until first response).
        mode: Shipping mode — 'batch' or 'interactive'.
        context_data: JSON blob with data source reference and agent_source_hash.
        is_active: Soft delete flag (False = archived).
        created_at: ISO8601 creation timestamp.
        updated_at: ISO8601 last-update timestamp.
    """

    __tablename__ = "conversation_sessions"
    __table_args__ = (
        Index("ix_convsess_active_updated", "is_active", "updated_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="batch"
    )
    context_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )
    updated_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    messages: Mapped[list["ConversationMessage"]] = relationship(
        "ConversationMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.sequence",
    )

    def __repr__(self) -> str:
        return f"<ConversationSession(id={self.id!r}, title={self.title!r})>"


class ConversationMessage(Base):
    """Persistent conversation message.

    Stores rendered messages (user text, agent text, artifacts, errors)
    for history display and agent context re-injection on resume.

    Attributes:
        id: UUID primary key.
        session_id: FK to ConversationSession.
        role: Message role — 'user', 'assistant', or 'system'.
        message_type: Classification for timeline rendering.
        content: Message text content.
        metadata_json: Optional JSON with artifact data (action, preview, etc.).
        sequence: Ordering within session (monotonically increasing).
        created_at: ISO8601 creation timestamp.
    """

    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_convmsg_session_seq", "session_id", "sequence"),
        Index("ix_convmsg_session_type", "session_id", "message_type"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversation_sessions.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    message_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=MessageType.text.value
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )

    session: Mapped["ConversationSession"] = relationship(
        "ConversationSession", back_populates="messages"
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationMessage(id={self.id!r}, role={self.role!r}, "
            f"seq={self.sequence})>"
        )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/db/test_conversation_models.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/db/models.py tests/db/test_conversation_models.py
git commit -m "feat: add ConversationSession and ConversationMessage DB models"
```

---

## Task 2: Conversation Persistence Service

**Files:**
- Create: `src/services/conversation_persistence_service.py`
- Test: `tests/services/test_conversation_persistence_service.py`

**Step 1: Write failing tests**

Create `tests/services/test_conversation_persistence_service.py`:

```python
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
        sess = db_session.query(ConversationSession).get("s1")
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
        sess = db_session.query(ConversationSession).get("s1")
        assert sess.title == "Ground Batch - Q3"


class TestUpdateContext:
    def test_updates_context(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        svc.update_session_context("s1", {"source": "new.csv"})
        sess = db_session.query(ConversationSession).get("s1")
        loaded = json.loads(sess.context_data)
        assert loaded["source"] == "new.csv"


class TestSoftDelete:
    def test_soft_deletes(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        svc.soft_delete_session("s1")
        sess = db_session.query(ConversationSession).get("s1")
        assert sess.is_active is False


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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_conversation_persistence_service.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement the service**

Create `src/services/conversation_persistence_service.py`:

```python
"""Persistence service for conversation sessions and messages.

Thin layer between API routes and SQLAlchemy models. All conversation
history reads and writes go through this service. The frontend never
writes messages — the backend owns all persistence.
"""

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from src.db.models import (
    ConversationMessage,
    ConversationSession,
    MessageType,
    generate_uuid,
    utc_now_iso,
)


class ConversationPersistenceService:
    """CRUD operations for persistent conversation sessions and messages.

    Args:
        db: SQLAlchemy session (sync).
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def create_session(
        self,
        session_id: str,
        mode: str = "batch",
        context_data: dict[str, Any] | None = None,
    ) -> ConversationSession:
        """Create a new conversation session row.

        Args:
            session_id: UUID for the session (matches runtime session_id).
            mode: 'batch' or 'interactive'.
            context_data: Optional JSON-serializable context snapshot.

        Returns:
            The created ConversationSession.
        """
        session = ConversationSession(
            id=session_id,
            mode=mode,
            context_data=json.dumps(context_data) if context_data else None,
        )
        self._db.add(session)
        self._db.commit()
        return session

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str = MessageType.text.value,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        """Append a message to a session with auto-incrementing sequence.

        Args:
            session_id: Parent session ID.
            role: 'user', 'assistant', or 'system'.
            content: Message text.
            message_type: Classification for timeline (default 'text').
            metadata: Optional artifact metadata dict.

        Returns:
            The created ConversationMessage.
        """
        # Compute next sequence number
        max_seq = (
            self._db.query(ConversationMessage.sequence)
            .filter_by(session_id=session_id)
            .order_by(ConversationMessage.sequence.desc())
            .first()
        )
        next_seq = (max_seq[0] + 1) if max_seq else 1

        msg = ConversationMessage(
            id=generate_uuid(),
            session_id=session_id,
            role=role,
            message_type=message_type,
            content=content,
            metadata_json=json.dumps(metadata) if metadata else None,
            sequence=next_seq,
        )
        self._db.add(msg)

        # Update session's updated_at
        session = self._db.query(ConversationSession).get(session_id)
        if session:
            session.updated_at = utc_now_iso()

        self._db.commit()
        return msg

    def list_sessions(
        self, active_only: bool = True
    ) -> list[dict[str, Any]]:
        """List conversation sessions with message counts.

        Args:
            active_only: If True, exclude soft-deleted sessions.

        Returns:
            List of session summary dicts.
        """
        from sqlalchemy import func

        query = self._db.query(
            ConversationSession,
            func.count(ConversationMessage.id).label("message_count"),
        ).outerjoin(ConversationMessage).group_by(ConversationSession.id)

        if active_only:
            query = query.filter(ConversationSession.is_active == True)  # noqa: E712

        query = query.order_by(ConversationSession.created_at.desc())

        results = []
        for session, count in query.all():
            results.append({
                "id": session.id,
                "title": session.title,
                "mode": session.mode,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "message_count": count,
            })
        return results

    def get_session_with_messages(
        self,
        session_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any] | None:
        """Load a session with its messages for resume/display.

        Args:
            session_id: Session ID.
            limit: Max messages to return (None = all).
            offset: Skip first N messages.

        Returns:
            Dict with 'session' and 'messages' keys, or None if not found.
        """
        session = self._db.query(ConversationSession).get(session_id)
        if session is None:
            return None

        query = (
            self._db.query(ConversationMessage)
            .filter_by(session_id=session_id)
            .order_by(ConversationMessage.sequence)
            .offset(offset)
        )
        if limit is not None:
            query = query.limit(limit)

        messages = [
            {
                "id": m.id,
                "role": m.role,
                "message_type": m.message_type,
                "content": m.content,
                "metadata": json.loads(m.metadata_json) if m.metadata_json else None,
                "sequence": m.sequence,
                "created_at": m.created_at,
            }
            for m in query.all()
        ]

        return {
            "session": {
                "id": session.id,
                "title": session.title,
                "mode": session.mode,
                "context_data": json.loads(session.context_data) if session.context_data else None,
                "is_active": session.is_active,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            },
            "messages": messages,
        }

    def update_session_title(self, session_id: str, title: str) -> None:
        """Set the session title.

        Args:
            session_id: Session ID.
            title: New title string.
        """
        session = self._db.query(ConversationSession).get(session_id)
        if session:
            session.title = title
            session.updated_at = utc_now_iso()
            self._db.commit()

    def update_session_context(
        self, session_id: str, context_data: dict[str, Any]
    ) -> None:
        """Update the session's context snapshot.

        Args:
            session_id: Session ID.
            context_data: New context dict.
        """
        session = self._db.query(ConversationSession).get(session_id)
        if session:
            session.context_data = json.dumps(context_data)
            session.updated_at = utc_now_iso()
            self._db.commit()

    def soft_delete_session(self, session_id: str) -> None:
        """Soft-delete a session (set is_active = False).

        Args:
            session_id: Session ID.
        """
        session = self._db.query(ConversationSession).get(session_id)
        if session:
            session.is_active = False
            session.updated_at = utc_now_iso()
            self._db.commit()

    def export_session_json(
        self, session_id: str
    ) -> dict[str, Any] | None:
        """Export a full session with all messages as JSON.

        Args:
            session_id: Session ID.

        Returns:
            Complete session dict suitable for JSON download, or None.
        """
        result = self.get_session_with_messages(session_id)
        if result is None:
            return None

        return {
            "exported_at": utc_now_iso(),
            "session": result["session"],
            "messages": result["messages"],
        }
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_conversation_persistence_service.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/services/conversation_persistence_service.py tests/services/test_conversation_persistence_service.py
git commit -m "feat: add ConversationPersistenceService for chat history CRUD"
```

---

## Task 3: API Schemas for Chat Sessions

**Files:**
- Modify: `src/api/schemas_conversations.py` (append new schemas)

**Step 1: Write failing test**

Create `tests/api/test_conversation_schemas.py`:

```python
"""Tests for conversation persistence Pydantic schemas."""

from src.api.schemas_conversations import (
    ChatSessionSummary,
    SessionDetailResponse,
    PersistedMessageResponse,
    UpdateTitleRequest,
)


def test_chat_session_summary_fields():
    s = ChatSessionSummary(
        id="abc",
        title="Test",
        mode="batch",
        created_at="2026-02-20T00:00:00Z",
        updated_at=None,
        message_count=5,
    )
    assert s.id == "abc"
    assert s.message_count == 5


def test_persisted_message_response():
    m = PersistedMessageResponse(
        id="msg-1",
        role="user",
        message_type="text",
        content="hello",
        metadata=None,
        sequence=1,
        created_at="2026-02-20T00:00:00Z",
    )
    assert m.sequence == 1


def test_session_detail_response():
    r = SessionDetailResponse(
        session=ChatSessionSummary(
            id="s1", title=None, mode="interactive",
            created_at="2026-02-20T00:00:00Z",
            updated_at=None, message_count=0,
        ),
        messages=[],
    )
    assert r.session.mode == "interactive"


def test_update_title_request():
    req = UpdateTitleRequest(title="New Title")
    assert req.title == "New Title"
```

**Step 2: Run to verify fail**

Run: `pytest tests/api/test_conversation_schemas.py -v`
Expected: FAIL with `ImportError`

**Step 3: Add schemas to `src/api/schemas_conversations.py`**

Append after existing schemas (after line 81):

```python
class ChatSessionSummary(BaseModel):
    """Lightweight session summary for sidebar listing."""

    id: str
    title: str | None
    mode: str
    created_at: str
    updated_at: str | None
    message_count: int


class PersistedMessageResponse(BaseModel):
    """Persisted message for history display."""

    id: str
    role: str
    message_type: str
    content: str
    metadata: dict | None
    sequence: int
    created_at: str


class SessionDetailResponse(BaseModel):
    """Full session with messages for resume."""

    session: ChatSessionSummary
    messages: list[PersistedMessageResponse]


class UpdateTitleRequest(BaseModel):
    """Request to rename a session."""

    title: str
```

**Step 4: Run tests**

Run: `pytest tests/api/test_conversation_schemas.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/api/schemas_conversations.py tests/api/test_conversation_schemas.py
git commit -m "feat: add Pydantic schemas for chat session persistence"
```

---

## Task 4: API Endpoints — List, Messages, Delete, Export, Update Title

**Files:**
- Modify: `src/api/routes/conversations.py` (add new endpoints, modify existing create/send/delete)

**Step 1: Write failing integration tests**

Create `tests/api/test_conversations_persistence.py`:

```python
"""Integration tests for conversation persistence API endpoints."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base


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
        from src.db.models import ConversationSession
        sess = db_session.query(ConversationSession).get("s1")
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
        from src.db.models import ConversationSession
        sess = db_session.query(ConversationSession).get("s1")
        assert sess.title == "Ground Batch"
```

**Step 2: Run tests**

Run: `pytest tests/api/test_conversations_persistence.py -v`
Expected: All PASS (these test the service layer directly; route integration requires the running app)

**Step 3: Add API endpoints to `src/api/routes/conversations.py`**

Add these new endpoints. The exact insertion points:

1. After imports (top of file), add:
```python
from src.services.conversation_persistence_service import ConversationPersistenceService
from src.api.schemas_conversations import (
    ChatSessionSummary,
    SessionDetailResponse,
    PersistedMessageResponse,
    UpdateTitleRequest,
)
```

2. Add a module-level helper to get the persistence service (after `_event_queues` on line 69):
```python
def _get_persistence_service() -> ConversationPersistenceService:
    """Get a ConversationPersistenceService with a fresh DB session."""
    from src.db.connection import SessionLocal
    return ConversationPersistenceService(SessionLocal())
```

3. Add new endpoints before the `shutdown_conversation_runtime` function (before line 939):

```python
@router.get("/", response_model=list[ChatSessionSummary])
async def list_conversations(
    active_only: bool = True,
) -> list[ChatSessionSummary]:
    """List conversation sessions for the sidebar.

    Args:
        active_only: If True, exclude soft-deleted sessions.

    Returns:
        List of session summaries ordered by recency.
    """
    svc = _get_persistence_service()
    sessions = svc.list_sessions(active_only=active_only)
    return [ChatSessionSummary(**s) for s in sessions]


@router.get("/{session_id}/messages", response_model=SessionDetailResponse)
async def get_session_messages(
    session_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> SessionDetailResponse:
    """Load a session's message history for resume/display.

    Args:
        session_id: Conversation session ID.
        limit: Max messages to return.
        offset: Skip first N messages.

    Returns:
        Session metadata and ordered messages.

    Raises:
        HTTPException: 404 if session not found.
    """
    svc = _get_persistence_service()
    result = svc.get_session_with_messages(session_id, limit=limit, offset=offset)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionDetailResponse(
        session=ChatSessionSummary(**result["session"], message_count=len(result["messages"])),
        messages=[PersistedMessageResponse(**m) for m in result["messages"]],
    )


@router.patch("/{session_id}")
async def update_conversation(
    session_id: str,
    payload: UpdateTitleRequest,
) -> dict:
    """Update a conversation session's title.

    Args:
        session_id: Conversation session ID.
        payload: Title update request.

    Returns:
        Updated session ID and title.
    """
    svc = _get_persistence_service()
    svc.update_session_title(session_id, payload.title)
    return {"id": session_id, "title": payload.title}


@router.get("/{session_id}/export")
async def export_conversation(session_id: str) -> Response:
    """Export a conversation session as JSON download.

    Args:
        session_id: Conversation session ID.

    Returns:
        JSON file download.

    Raises:
        HTTPException: 404 if session not found.
    """
    import json as json_mod

    svc = _get_persistence_service()
    export = svc.export_session_json(session_id)
    if export is None:
        raise HTTPException(status_code=404, detail="Session not found")

    title_slug = (export["session"].get("title") or "conversation").replace(" ", "-").lower()[:30]
    filename = f"{title_slug}-{session_id[:8]}.json"

    return Response(
        content=json_mod.dumps(export, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

4. **Modify `create_conversation`** (line 637): After creating the in-memory session, also create a DB row:

Add after line 656 (`session.interactive_shipping = effective_payload.interactive_shipping`):
```python
    # Persist session to database
    try:
        persistence = _get_persistence_service()
        persistence.create_session(
            session_id=session_id,
            mode="interactive" if effective_payload.interactive_shipping else "batch",
        )
    except Exception as e:
        logger.warning("Failed to persist session %s to DB: %s", session_id, e)
```

5. **Modify `send_message`** (line 685): After storing in-memory, also persist user message to DB:

Add after line 713 (`_session_manager.add_message(session_id, "user", payload.content)`):
```python
    # Persist user message to database
    try:
        persistence = _get_persistence_service()
        persistence.save_message(session_id, "user", payload.content)
    except Exception as e:
        logger.warning("Failed to persist user message to DB: %s", e)
```

6. **Modify `_process_agent_message`**: After the agent finishes, persist assistant message to DB.

Add after line 483 (the block that adds agent message to in-memory history when `buffered_agent_messages` has content and no artifact was emitted):
```python
                        # Persist assistant message to DB
                        try:
                            persistence = _get_persistence_service()
                            persistence.save_message(
                                session_id, "assistant", final_text,
                            )
                        except Exception as exc:
                            logger.warning("Failed to persist assistant msg: %s", exc)
```

Also add persistence for non-transient agent messages (after line 442):
```python
                            # Persist assistant message to DB
                            try:
                                persistence = _get_persistence_service()
                                persistence.save_message(
                                    session_id, "assistant", text,
                                )
                            except Exception as exc:
                                logger.warning("Failed to persist assistant msg: %s", exc)
```

And persist artifact events — add after line 461 (`await queue.put(event)`), inside the artifact_events check:
```python
                    # Persist artifact events to DB
                    if isinstance(event_type, str) and event_type in artifact_events:
                        try:
                            persistence = _get_persistence_service()
                            persistence.save_message(
                                session_id,
                                "system",
                                event_type,
                                message_type="system_artifact",
                                metadata=event.get("data"),
                            )
                        except Exception as exc:
                            logger.warning("Failed to persist artifact event: %s", exc)
```

7. **Modify `delete_conversation`** (line 910): Change to soft-delete instead of hard-delete:

Add before line 933 (`_session_manager.remove_session(session_id)`):
```python
    # Soft-delete from database (keep for history)
    try:
        persistence = _get_persistence_service()
        persistence.soft_delete_session(session_id)
    except Exception as e:
        logger.warning("Failed to soft-delete session %s from DB: %s", session_id, e)
```

**Step 4: Run tests**

Run: `pytest tests/api/test_conversations_persistence.py tests/services/test_conversation_persistence_service.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/api/routes/conversations.py src/api/schemas_conversations.py tests/api/test_conversations_persistence.py
git commit -m "feat: add conversation persistence API endpoints (list, messages, export, title)"
```

---

## Task 5: System Prompt — Prior Conversation Injection

**Files:**
- Modify: `src/orchestrator/agent/system_prompt.py:257` (add `prior_conversation` parameter)
- Test: `tests/orchestrator/agent/test_system_prompt_resume.py`

**Step 1: Write failing test**

Create `tests/orchestrator/agent/test_system_prompt_resume.py`:

```python
"""Tests for prior conversation injection in system prompt."""

from src.orchestrator.agent.system_prompt import build_system_prompt


def test_no_prior_conversation_by_default():
    prompt = build_system_prompt()
    assert "Prior Conversation" not in prompt


def test_prior_conversation_injected():
    history = [
        {"role": "user", "content": "Ship CA orders via Ground"},
        {"role": "assistant", "content": "I'll help with that."},
    ]
    prompt = build_system_prompt(prior_conversation=history)
    assert "Prior Conversation" in prompt
    assert "Ship CA orders via Ground" in prompt
    assert "I'll help with that." in prompt


def test_prior_conversation_truncation():
    history = [
        {"role": "user", "content": f"Message {i}"}
        for i in range(50)
    ]
    prompt = build_system_prompt(prior_conversation=history)
    # Should truncate to last ~30 messages
    assert "Message 49" in prompt
    assert "Message 0" not in prompt


def test_prior_conversation_empty_list():
    prompt = build_system_prompt(prior_conversation=[])
    assert "Prior Conversation" not in prompt
```

**Step 2: Run to verify fail**

Run: `pytest tests/orchestrator/agent/test_system_prompt_resume.py -v`
Expected: FAIL with `TypeError: build_system_prompt() got an unexpected keyword argument 'prior_conversation'`

**Step 3: Modify `build_system_prompt()` in `src/orchestrator/agent/system_prompt.py`**

Update the function signature at line 257 to add the new parameter:

```python
def build_system_prompt(
    source_info: DataSourceInfo | None = None,
    interactive_shipping: bool = False,
    column_samples: dict[str, list] | None = None,
    contacts: list[dict] | None = None,
    prior_conversation: list[dict] | None = None,
) -> str:
```

Add a new helper function before `build_system_prompt` (around line 255):

```python
MAX_RESUME_MESSAGES = 30


def _build_prior_conversation_section(
    messages: list[dict],
) -> str:
    """Build a prior conversation section for session resume.

    Truncates to the last MAX_RESUME_MESSAGES to control prompt size.

    Args:
        messages: List of {role, content} dicts from persisted history.

    Returns:
        Formatted conversation history section, or empty string.
    """
    if not messages:
        return ""

    truncated = messages[-MAX_RESUME_MESSAGES:]
    lines = [
        "## Prior Conversation (Resumed Session)",
        "",
        "You are resuming a prior conversation. Here is the recent history:",
        "",
    ]
    for msg in truncated:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        # Truncate very long messages in history
        if len(content) > 500:
            content = content[:497] + "..."
        lines.append(f"[{role}]: {content}")

    if len(messages) > MAX_RESUME_MESSAGES:
        omitted = len(messages) - MAX_RESUME_MESSAGES
        lines.insert(4, f"({omitted} earlier messages omitted)")
        lines.insert(5, "")

    return "\n".join(lines)
```

At the end of `build_system_prompt()`, before the final return (line 580+), add:

```python
    # Prior conversation section for session resume
    prior_section = ""
    if prior_conversation:
        prior_section = _build_prior_conversation_section(prior_conversation)
```

And include `{prior_section}` in the f-string return, after `{contacts_section}` (around line 592):

```python
{contacts_section}
{prior_section}
## Filter Generation Rules
```

**Step 4: Run tests**

Run: `pytest tests/orchestrator/agent/test_system_prompt_resume.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/orchestrator/agent/system_prompt.py tests/orchestrator/agent/test_system_prompt_resume.py
git commit -m "feat: add prior conversation injection to system prompt for session resume"
```

---

## Task 6: Frontend — TypeScript Types & API Client

**Files:**
- Modify: `frontend/src/types/api.ts` (add new types)
- Modify: `frontend/src/lib/api.ts` (add new API functions)

**Step 1: Add TypeScript types to `frontend/src/types/api.ts`**

Append after existing types:

```typescript
// === Chat Session Persistence ===

export interface ChatSessionSummary {
  id: string;
  title: string | null;
  mode: 'batch' | 'interactive';
  created_at: string;
  updated_at: string | null;
  message_count: number;
}

export interface PersistedMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  message_type: 'text' | 'system_artifact' | 'error' | 'tool_call';
  content: string;
  metadata: Record<string, unknown> | null;
  sequence: number;
  created_at: string;
}

export interface SessionDetail {
  session: ChatSessionSummary;
  messages: PersistedMessage[];
}
```

**Step 2: Add API functions to `frontend/src/lib/api.ts`**

Add after `deleteConversation` (after line 458):

```typescript
// === Chat Session Persistence API ===

import type { ChatSessionSummary, SessionDetail } from '@/types/api';

/**
 * List conversation sessions for the sidebar.
 */
export async function listConversations(
  activeOnly = true,
): Promise<ChatSessionSummary[]> {
  const response = await fetch(
    `${API_BASE}/conversations/?active_only=${activeOnly}`,
  );
  return parseResponse<ChatSessionSummary[]>(response);
}

/**
 * Load a session's message history for resume/display.
 */
export async function getConversationMessages(
  sessionId: string,
  limit?: number,
  offset = 0,
): Promise<SessionDetail> {
  const params = new URLSearchParams({ offset: String(offset) });
  if (limit !== undefined) params.set('limit', String(limit));
  const response = await fetch(
    `${API_BASE}/conversations/${sessionId}/messages?${params}`,
  );
  return parseResponse<SessionDetail>(response);
}

/**
 * Update a conversation session's title.
 */
export async function updateConversationTitle(
  sessionId: string,
  title: string,
): Promise<void> {
  const response = await fetch(`${API_BASE}/conversations/${sessionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (!response.ok) await parseResponse(response);
}

/**
 * Export a conversation session as JSON file download.
 */
export async function exportConversation(sessionId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE}/conversations/${sessionId}/export`,
  );
  if (!response.ok) throw new ApiError(response.status, 'Export failed');
  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="(.+?)"/);
  const filename = match?.[1] || 'conversation-export.json';
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
```

**Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/lib/api.ts
git commit -m "feat: add chat session persistence types and API client functions"
```

---

## Task 7: Frontend — AppState & useConversation Changes

**Files:**
- Modify: `frontend/src/hooks/useAppState.tsx` (add chat session state)
- Modify: `frontend/src/hooks/useConversation.ts` (add loadSession, startNewChat, modify reset)

**Step 1: Add state to `useAppState.tsx`**

In the `AppState` interface (after line 173, before the closing `}`):

```typescript
  // Chat session history for sidebar
  chatSessions: ChatSessionSummary[];
  setChatSessions: (sessions: ChatSessionSummary[]) => void;
  chatSessionsVersion: number;
  refreshChatSessions: () => void;
  activeSessionTitle: string | null;
  setActiveSessionTitle: (title: string | null) => void;
```

Add the import at top:
```typescript
import type { ChatSessionSummary } from '@/types/api';
```

In the `AppStateProvider` (add state declarations after existing ones around line 184+):

```typescript
  const [chatSessions, setChatSessions] = React.useState<ChatSessionSummary[]>([]);
  const [chatSessionsVersion, setChatSessionsVersion] = React.useState(0);
  const [activeSessionTitle, setActiveSessionTitle] = React.useState<string | null>(null);

  const refreshChatSessions = React.useCallback(() => {
    setChatSessionsVersion((v) => v + 1);
  }, []);
```

Add these to the context value object:
```typescript
  chatSessions,
  setChatSessions,
  chatSessionsVersion,
  refreshChatSessions,
  activeSessionTitle,
  setActiveSessionTitle,
```

**Step 2: Add `loadSession` and `startNewChat` to `useConversation.ts`**

Add new functions to the hook. After the `reset` function:

```typescript
  const loadSession = useCallback(async (
    sessionId: string,
    mode: 'batch' | 'interactive',
    messages: ConversationMessage[],
  ) => {
    // Close current SSE and clear events (without deleting old session)
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    sessionGenerationRef.current += 1;
    setEvents([]);

    // Set the new session
    sessionIdRef.current = sessionId;
    sessionModeRef.current = mode === 'interactive';
    setSessionId(sessionId);

    // Connect SSE for live events on this session
    connectSSE(sessionId);
  }, [connectSSE]);

  const startNewChat = useCallback(async () => {
    // Close current SSE without deleting session (it auto-saved)
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    sessionGenerationRef.current += 1;
    setEvents([]);
    sessionIdRef.current = null;
    sessionModeRef.current = null;
    creatingSessionPromiseRef.current = null;
    setSessionId(null);
    setIsProcessing(false);
  }, []);
```

Add to the return interface:
```typescript
  loadSession,
  startNewChat,
```

Update the `UseConversationReturn` interface to include:
```typescript
  loadSession: (sessionId: string, mode: 'batch' | 'interactive', messages: ConversationMessage[]) => Promise<void>;
  startNewChat: () => Promise<void>;
```

**Step 3: Modify `reset()` to NOT delete the session**

In the existing `reset` function, change the session deletion to be conditional — only delete if no persistence (for mode switches where user wants to start fresh):

The key change: when `reset()` is called from mode switching, it should still delete. When called from `startNewChat()`, it should not. The simplest approach: `startNewChat()` handles its own cleanup without calling `reset()`.

No change needed to `reset()` — it already works correctly for mode switches. `startNewChat()` is a separate function that preserves the session.

**Step 4: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 5: Commit**

```bash
git add frontend/src/hooks/useAppState.tsx frontend/src/hooks/useConversation.ts
git commit -m "feat: add chat session state and loadSession/startNewChat to hooks"
```

---

## Task 8: Frontend — ChatSessionsPanel Component

**Files:**
- Create: `frontend/src/components/sidebar/ChatSessionsPanel.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx` (integrate panel)

**Step 1: Create `ChatSessionsPanel.tsx`**

Mirrors the `JobHistoryPanel` pattern. File: `frontend/src/components/sidebar/ChatSessionsPanel.tsx`:

```tsx
/**
 * Chat sessions panel for the sidebar.
 *
 * Lists persistent conversation sessions grouped by recency.
 * Supports session switching, deletion, and new chat creation.
 */

import * as React from 'react';
import { useAppState } from '@/hooks/useAppState';
import { cn, formatTimeAgo } from '@/lib/utils';
import { listConversations, deleteConversation, getConversationMessages, exportConversation } from '@/lib/api';
import type { ChatSessionSummary, PersistedMessage } from '@/types/api';
import type { ConversationMessage } from '@/hooks/useAppState';
import { TrashIcon, PlusIcon, DownloadIcon } from '@/components/ui/icons';

/** Mode badge for session items. */
function ModeBadge({ mode }: { mode: string }) {
  return (
    <span className={cn(
      'text-[9px] font-mono px-1.5 py-0.5 rounded',
      mode === 'interactive'
        ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
        : 'bg-primary/10 text-primary border border-primary/20'
    )}>
      {mode === 'interactive' ? 'Interactive' : 'Batch'}
    </span>
  );
}

/** Group sessions by relative date. */
function groupByDate(sessions: ChatSessionSummary[]): Record<string, ChatSessionSummary[]> {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);

  const groups: Record<string, ChatSessionSummary[]> = {};

  for (const session of sessions) {
    const date = new Date(session.created_at);
    let group: string;
    if (date >= today) group = 'Today';
    else if (date >= yesterday) group = 'Yesterday';
    else if (date >= weekAgo) group = 'Previous 7 Days';
    else group = 'Older';

    if (!groups[group]) groups[group] = [];
    groups[group].push(session);
  }

  return groups;
}

interface ChatSessionsPanelProps {
  onLoadSession: (
    sessionId: string,
    mode: 'batch' | 'interactive',
    messages: ConversationMessage[],
  ) => void;
  onNewChat: () => void;
  activeSessionId?: string | null;
}

export function ChatSessionsPanel({
  onLoadSession,
  onNewChat,
  activeSessionId,
}: ChatSessionsPanelProps) {
  const { chatSessionsVersion, setChatSessions } = useAppState();
  const [sessions, setSessions] = React.useState<ChatSessionSummary[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [deletingId, setDeletingId] = React.useState<string | null>(null);

  const loadSessions = React.useCallback(async () => {
    try {
      const data = await listConversations();
      setSessions(data);
      setChatSessions(data);
    } catch (err) {
      console.error('Failed to load chat sessions:', err);
    } finally {
      setIsLoading(false);
    }
  }, [setChatSessions]);

  React.useEffect(() => {
    loadSessions();
  }, [loadSessions, chatSessionsVersion]);

  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    setDeletingId(sessionId);
    try {
      await deleteConversation(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
    } catch (err) {
      console.error('Failed to delete session:', err);
    } finally {
      setDeletingId(null);
    }
  };

  const handleExport = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    try {
      await exportConversation(sessionId);
    } catch (err) {
      console.error('Failed to export session:', err);
    }
  };

  const handleSelect = async (session: ChatSessionSummary) => {
    if (session.id === activeSessionId) return;
    try {
      const detail = await getConversationMessages(session.id);
      const messages: ConversationMessage[] = detail.messages.map((m: PersistedMessage) => ({
        id: m.id,
        role: m.role === 'assistant' ? 'system' : m.role as 'user' | 'system',
        content: m.content,
        timestamp: new Date(m.created_at),
        metadata: m.metadata ? m.metadata as ConversationMessage['metadata'] : undefined,
      }));
      onLoadSession(session.id, session.mode as 'batch' | 'interactive', messages);
    } catch (err) {
      console.error('Failed to load session:', err);
    }
  };

  const grouped = groupByDate(sessions);
  const groupOrder = ['Today', 'Yesterday', 'Previous 7 Days', 'Older'];

  if (isLoading) {
    return (
      <div className="p-3 space-y-2">
        <div className="h-4 w-24 bg-slate-800 rounded shimmer" />
        <div className="h-10 bg-slate-800 rounded shimmer" />
        <div className="h-10 bg-slate-800 rounded shimmer" />
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-300">Chat Sessions</span>
        <button
          onClick={onNewChat}
          className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded bg-primary/20 text-primary hover:bg-primary/30 transition-colors"
          title="New chat"
        >
          <PlusIcon className="w-3 h-3" />
          New Chat
        </button>
      </div>

      <div className="space-y-3 max-h-[250px] overflow-y-auto scrollable">
        {sessions.length === 0 ? (
          <p className="text-xs text-slate-500 text-center py-4">
            No conversations yet. Start typing to begin.
          </p>
        ) : (
          groupOrder.map((group) => {
            const items = grouped[group];
            if (!items || items.length === 0) return null;
            return (
              <div key={group}>
                <p className="text-[10px] font-mono text-slate-600 uppercase tracking-wider mb-1.5">
                  {group}
                </p>
                <div className="space-y-1">
                  {items.map((session) => (
                    <div
                      key={session.id}
                      className={cn(
                        'group relative w-full text-left p-2 rounded-md transition-colors cursor-pointer',
                        'border border-transparent',
                        activeSessionId === session.id
                          ? 'bg-primary/10 border-primary/30'
                          : 'hover:bg-slate-800/50'
                      )}
                      onClick={() => handleSelect(session)}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <p className="text-xs text-slate-200 line-clamp-1">
                            {session.title || 'New conversation...'}
                          </p>
                          <div className="flex items-center gap-1.5 mt-1">
                            <ModeBadge mode={session.mode} />
                            <span className="text-[10px] font-mono text-slate-500">
                              {formatTimeAgo(session.updated_at || session.created_at)}
                            </span>
                          </div>
                        </div>
                        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={(e) => handleExport(e, session.id)}
                            className="p-1 rounded hover:bg-slate-700 text-slate-500 hover:text-slate-300"
                            title="Export"
                          >
                            <DownloadIcon className="w-3 h-3" />
                          </button>
                          <button
                            onClick={(e) => handleDelete(e, session.id)}
                            disabled={deletingId === session.id}
                            className="p-1 rounded hover:bg-red-500/20 text-slate-500 hover:text-red-400"
                            title="Delete"
                          >
                            <TrashIcon className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
```

**Step 2: Integrate into `Sidebar.tsx`**

Add import at top (line 11):
```typescript
import { ChatSessionsPanel } from '@/components/sidebar/ChatSessionsPanel';
```

Update `SidebarProps` interface to add callbacks:
```typescript
interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  onSelectJob: (job: Job | null) => void;
  activeJobId?: string;
  onLoadSession: (sessionId: string, mode: 'batch' | 'interactive', messages: ConversationMessage[]) => void;
  onNewChat: () => void;
  activeSessionId?: string | null;
}
```

Add import for ConversationMessage:
```typescript
import type { ConversationMessage } from '@/hooks/useAppState';
```

In the expanded content (between DataSourceSection and JobHistorySection, line 80):
```tsx
          {/* Chat Sessions Section */}
          <div className="border-b border-slate-800">
            <ChatSessionsPanel
              onLoadSession={onLoadSession}
              onNewChat={onNewChat}
              activeSessionId={activeSessionId}
            />
          </div>
```

**Step 3: Check icons exist — add PlusIcon and DownloadIcon if missing**

Check `frontend/src/components/ui/icons.tsx` for `PlusIcon` and `DownloadIcon`. If missing, add them following the existing SVG icon pattern.

**Step 4: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 5: Commit**

```bash
git add frontend/src/components/sidebar/ChatSessionsPanel.tsx frontend/src/components/layout/Sidebar.tsx
git commit -m "feat: add ChatSessionsPanel to sidebar with session listing and management"
```

---

## Task 9: Frontend — CopyButton on Messages

**Files:**
- Modify: `frontend/src/components/command-center/messages.tsx`

**Step 1: Add CopyButton component to `messages.tsx`**

Add after the imports (after line 16):

```tsx
import { CopyIcon, CheckIcon } from '@/components/ui/icons';

/** Copy-to-clipboard button with brief checkmark feedback. */
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      console.error('Failed to copy to clipboard');
    }
  };

  return (
    <button
      onClick={handleCopy}
      className="absolute top-2 right-2 p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity bg-slate-800/80 hover:bg-slate-700 text-slate-400 hover:text-slate-200"
      title="Copy to clipboard"
    >
      {copied ? (
        <CheckIcon className="w-3.5 h-3.5 text-green-400" />
      ) : (
        <CopyIcon className="w-3.5 h-3.5" />
      )}
    </button>
  );
}
```

Add `import * as React from 'react';` at the top if not already present.

**Step 2: Add CopyButton to SystemMessage**

Wrap the existing content div with `group` class and add CopyButton. Modify `SystemMessage` (lines 19-38):

```tsx
export function SystemMessage({ message }: { message: ConversationMessage }) {
  return (
    <div className="flex gap-3 animate-fade-in-up">
      <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-cyan-600/20 border border-cyan-500/30 flex items-center justify-center">
        <PackageIcon className="w-4 h-4 text-cyan-400" />
      </div>

      <div className="flex-1 space-y-2 relative group">
        <div className="message-system prose prose-invert max-w-none prose-sm prose-p:leading-relaxed prose-pre:bg-slate-800/50 prose-pre:border prose-pre:border-slate-700/50">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {message.content}
          </ReactMarkdown>
        </div>
        <CopyButton text={message.content} />

        <span className="text-[10px] font-mono text-slate-500">
          {formatRelativeTime(message.timestamp)}
        </span>
      </div>
    </div>
  );
}
```

**Step 3: Add CopyButton to UserMessage**

```tsx
export function UserMessage({ message }: { message: ConversationMessage }) {
  return (
    <div className="flex gap-3 justify-end animate-fade-in-up">
      <div className="flex-1 space-y-2 flex flex-col items-end relative group">
        <div className="message-user">
          <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        </div>
        <CopyButton text={message.content} />

        <span className="text-[10px] font-mono text-slate-500">
          {formatRelativeTime(message.timestamp)}
        </span>
      </div>
    </div>
  );
}
```

**Step 4: Verify TypeScript compiles and check icons**

Check that `CopyIcon` and `CheckIcon` exist in `frontend/src/components/ui/icons.tsx`. If missing, add:

```tsx
export function CopyIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
    </svg>
  );
}

export function CheckIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}
```

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 5: Commit**

```bash
git add frontend/src/components/command-center/messages.tsx frontend/src/components/ui/icons.tsx
git commit -m "feat: add copy-to-clipboard button on chat message bubbles"
```

---

## Task 10: Frontend — Visual Timeline Minimap

**Files:**
- Create: `frontend/src/components/command-center/ChatTimeline.tsx`
- Modify: `frontend/src/components/CommandCenter.tsx` (integrate timeline + data-message-id)

**Step 1: Create `ChatTimeline.tsx`**

```tsx
/**
 * Visual timeline minimap for chat navigation.
 *
 * Thin vertical line with color-coded dots representing messages.
 * Syncs with scroll position via IntersectionObserver.
 * Click a dot to scroll to the corresponding message.
 */

import * as React from 'react';
import { cn } from '@/lib/utils';
import type { ConversationMessage } from '@/hooks/useAppState';

/** Map message to timeline dot color. */
function getDotColor(message: ConversationMessage): string {
  if (message.metadata?.action === 'error') return 'bg-red-400';
  if (message.metadata?.action) return 'bg-amber-400'; // artifact
  if (message.role === 'user') return 'bg-slate-400';
  return 'bg-cyan-400'; // assistant
}

interface ChatTimelineProps {
  messages: ConversationMessage[];
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
}

export function ChatTimeline({ messages, scrollContainerRef }: ChatTimelineProps) {
  const [visibleIds, setVisibleIds] = React.useState<Set<string>>(new Set());

  // Observe which messages are in the viewport
  React.useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const observer = new IntersectionObserver(
      (entries) => {
        setVisibleIds((prev) => {
          const next = new Set(prev);
          for (const entry of entries) {
            const id = entry.target.getAttribute('data-message-id');
            if (!id) continue;
            if (entry.isIntersecting) next.add(id);
            else next.delete(id);
          }
          return next;
        });
      },
      { root: container, threshold: 0.3 },
    );

    const elements = container.querySelectorAll('[data-message-id]');
    elements.forEach((el) => observer.observe(el));

    return () => observer.disconnect();
  }, [scrollContainerRef, messages.length]);

  const handleDotClick = (messageId: string) => {
    const el = scrollContainerRef.current?.querySelector(
      `[data-message-id="${messageId}"]`,
    );
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  if (messages.length === 0) return null;

  return (
    <div className="relative w-4 flex-shrink-0 flex flex-col items-center py-6">
      {/* Vertical line */}
      <div className="absolute top-6 bottom-6 w-px bg-slate-800" />

      {/* Dots */}
      <div className="relative flex flex-col justify-between h-full w-full items-center">
        {messages.map((msg) => {
          const isVisible = visibleIds.has(msg.id);
          return (
            <button
              key={msg.id}
              onClick={() => handleDotClick(msg.id)}
              className={cn(
                'relative z-10 rounded-full transition-all duration-200 cursor-pointer',
                getDotColor(msg),
                isVisible ? 'w-2.5 h-2.5 opacity-100 shadow-lg' : 'w-1.5 h-1.5 opacity-50',
              )}
              title={`${msg.role}: ${msg.content.slice(0, 40)}...`}
            />
          );
        })}
      </div>
    </div>
  );
}
```

**Step 2: Integrate into `CommandCenter.tsx`**

Add import (after line 33):
```tsx
import { ChatTimeline } from '@/components/command-center/ChatTimeline';
```

Add a ref for the scroll container. After `messagesEndRef` (line 103):
```tsx
  const scrollContainerRef = React.useRef<HTMLDivElement>(null);
```

Modify the messages area (line 478) to include `ref` and timeline:
```tsx
      {/* Messages area with timeline */}
      <div className="flex flex-1 overflow-hidden">
        <div ref={scrollContainerRef} className="command-messages-shell flex-1 overflow-y-auto scrollable p-6">
```

Add `data-message-id` to each message element. In the conversation map (line 483), wrap each message:
```tsx
            {conversation.map((message) => (
              <div key={message.id} data-message-id={message.id}>
                {message.metadata?.action === 'complete' ? (
```

Remove the `key={message.id}` from the inner elements since it's now on the wrapper div.

After the closing `</div>` of the scroll container, add the timeline:
```tsx
        {/* Visual Timeline */}
        {conversation.length > 3 && (
          <ChatTimeline
            messages={conversation}
            scrollContainerRef={scrollContainerRef}
          />
        )}
      </div>
```

**Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add frontend/src/components/command-center/ChatTimeline.tsx frontend/src/components/CommandCenter.tsx
git commit -m "feat: add visual timeline minimap for chat navigation"
```

---

## Task 11: Integration — Wire Sidebar to CommandCenter

**Files:**
- Modify: `frontend/src/components/CommandCenter.tsx` (add session loading handler)
- Modify: `frontend/src/App.tsx` (pass callbacks through Sidebar)

**Step 1: Add session loading to CommandCenter**

Add a `handleLoadSession` callback in `CommandCenter` that:
1. Sets `interactiveShipping` from session mode
2. Clears current conversation
3. Populates conversation from loaded messages
4. Calls `conv.loadSession()`
5. Refreshes chat sessions list

```tsx
  const handleLoadSession = React.useCallback(async (
    sessionId: string,
    mode: 'batch' | 'interactive',
    messages: ConversationMessage[],
  ) => {
    // Set mode BEFORE rendering to prevent flicker
    setInteractiveShipping(mode === 'interactive');

    // Clear current state
    clearConversation();
    setPreview(null);
    setCurrentJobId(null);
    setExecutingJobId(null);

    // Populate conversation from loaded messages
    for (const msg of messages) {
      addMessage(msg);
    }

    // Connect to the session
    await conv.loadSession(sessionId, mode, messages);
    setConversationSessionId(sessionId);
  }, [conv, setInteractiveShipping, clearConversation, addMessage, setConversationSessionId]);

  const handleNewChat = React.useCallback(async () => {
    await conv.startNewChat();
    clearConversation();
    setPreview(null);
    setCurrentJobId(null);
    setExecutingJobId(null);
    setConversationSessionId(null);
    refreshChatSessions();
  }, [conv, clearConversation, setConversationSessionId, refreshChatSessions]);
```

Note: `refreshChatSessions` needs to be added to the destructured values from `useAppState()`.

**Step 2: Pass callbacks through App.tsx to Sidebar**

In `App.tsx`, pass `handleLoadSession` and `handleNewChat` from `CommandCenter` to `Sidebar`. This requires lifting the callbacks up or using context. The simplest approach: pass them via props from `App.tsx` through `Sidebar`.

Look at `App.tsx` to see how Sidebar and CommandCenter are connected, then wire the props through.

**Step 3: Verify TypeScript compiles and test manually**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add frontend/src/components/CommandCenter.tsx frontend/src/App.tsx frontend/src/components/layout/Sidebar.tsx
git commit -m "feat: wire sidebar session loading to CommandCenter"
```

---

## Task 12: Title Generation — Background Haiku Task

**Files:**
- Modify: `src/api/routes/conversations.py` (add title generation after first response)

**Step 1: Write test**

Add to `tests/services/test_conversation_persistence_service.py`:

```python
class TestTitleGeneration:
    def test_title_updates_after_generation(self, svc, db_session):
        svc.create_session(session_id="s1", mode="batch")
        svc.save_message("s1", "user", "Ship all CA orders via Ground")
        svc.save_message("s1", "assistant", "I'll help ship those orders.")
        svc.update_session_title("s1", "Ground Batch - CA Orders")
        from src.db.models import ConversationSession
        sess = db_session.query(ConversationSession).get("s1")
        assert sess.title == "Ground Batch - CA Orders"
```

**Step 2: Add title generation function to `conversations.py`**

Add a background task function:

```python
async def _generate_session_title(session_id: str) -> None:
    """Generate a session title via a lightweight Haiku call.

    Fire-and-forget background task. Runs after the first assistant
    response is saved. Updates the DB title field.
    """
    try:
        svc = _get_persistence_service()
        result = svc.get_session_with_messages(session_id, limit=2)
        if result is None or len(result["messages"]) < 2:
            return

        # Already has a title — skip
        if result["session"].get("title"):
            return

        user_msg = result["messages"][0]["content"][:200]
        assistant_msg = result["messages"][1]["content"][:200]

        from anthropic import AsyncAnthropic

        client = AsyncAnthropic()
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=30,
            messages=[{
                "role": "user",
                "content": (
                    f"Generate a concise 3-6 word title for this shipping conversation. "
                    f"Return ONLY the title, no quotes or explanation.\n\n"
                    f"User: {user_msg}\n"
                    f"Assistant: {assistant_msg}"
                ),
            }],
        )

        title = response.content[0].text.strip()[:255]
        if title:
            svc.update_session_title(session_id, title)
            logger.info("Generated title for session %s: %s", session_id, title)

    except Exception as e:
        logger.warning("Title generation failed for session %s: %s", session_id, e)
```

**Step 3: Trigger title generation after first assistant response**

In `_process_agent_message`, after persisting the first assistant message, check if this is the first response and fire the background task:

```python
    # Check if this is the first assistant message — generate title
    try:
        persistence = _get_persistence_service()
        result = persistence.get_session_with_messages(session_id, limit=3)
        if result and not result["session"].get("title"):
            assistant_count = sum(1 for m in result["messages"] if m["role"] == "assistant")
            if assistant_count == 1:
                asyncio.create_task(_generate_session_title(session_id))
    except Exception:
        pass  # Title generation is best-effort
```

**Step 4: Run tests**

Run: `pytest tests/services/test_conversation_persistence_service.py -v -k title`
Expected: PASS

**Step 5: Commit**

```bash
git add src/api/routes/conversations.py tests/services/test_conversation_persistence_service.py
git commit -m "feat: add background Haiku title generation for chat sessions"
```

---

## Task 13: Run Full Test Suite

**Step 1: Run all existing tests (excluding known hangers)**

Run: `pytest -x -k "not stream and not sse and not progress and not test_stream_endpoint_exists" --timeout=30`
Expected: All pass (existing tests should not be broken by new DB tables)

**Step 2: Run new tests specifically**

Run: `pytest tests/db/test_conversation_models.py tests/services/test_conversation_persistence_service.py tests/api/test_conversations_persistence.py tests/api/test_conversation_schemas.py tests/orchestrator/agent/test_system_prompt_resume.py -v`
Expected: All PASS

**Step 3: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve test/type issues from chat persistence integration"
```

---

## Summary of All Commits

| # | Commit Message | Files |
|---|---------------|-------|
| 1 | `feat: add ConversationSession and ConversationMessage DB models` | models.py, test |
| 2 | `feat: add ConversationPersistenceService for chat history CRUD` | service, test |
| 3 | `feat: add Pydantic schemas for chat session persistence` | schemas, test |
| 4 | `feat: add conversation persistence API endpoints` | routes, test |
| 5 | `feat: add prior conversation injection to system prompt` | system_prompt, test |
| 6 | `feat: add chat session persistence types and API client` | types, api.ts |
| 7 | `feat: add chat session state and hooks` | useAppState, useConversation |
| 8 | `feat: add ChatSessionsPanel to sidebar` | panel, sidebar |
| 9 | `feat: add copy-to-clipboard on messages` | messages, icons |
| 10 | `feat: add visual timeline minimap` | ChatTimeline, CommandCenter |
| 11 | `feat: wire sidebar session loading to CommandCenter` | CommandCenter, App |
| 12 | `feat: add background Haiku title generation` | routes, test |
| 13 | `fix: resolve integration issues` | any fixes |
