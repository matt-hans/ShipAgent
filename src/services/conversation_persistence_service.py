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
        # Compute next sequence number.
        # Note: For SQLite with single-writer semantics, SELECT+INSERT
        # is safe within a single transaction. If migrating to Postgres with
        # concurrent writes, consider using a DB sequence or SELECT FOR UPDATE.
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
        session = self._db.get(ConversationSession, session_id)
        if session:
            session.updated_at = utc_now_iso()

        self._db.commit()
        return msg

    def list_sessions(
        self, active_only: bool = True
    ) -> list[dict[str, Any]]:
        """List conversation sessions with message counts.

        Uses explicit column selection to avoid loading heavy columns
        (context_data) that the sidebar listing doesn't need.

        Args:
            active_only: If True, exclude soft-deleted sessions.

        Returns:
            List of session summary dicts (lightweight — no context_data).
        """
        from sqlalchemy import func

        query = self._db.query(
            ConversationSession.id,
            ConversationSession.title,
            ConversationSession.mode,
            ConversationSession.created_at,
            ConversationSession.updated_at,
            func.count(ConversationMessage.id).label("message_count"),
        ).outerjoin(ConversationMessage).group_by(ConversationSession.id)

        if active_only:
            query = query.filter(ConversationSession.is_active == True)  # noqa: E712

        query = query.order_by(
            ConversationSession.updated_at.desc().nullslast(),
            ConversationSession.created_at.desc(),
        )

        results = []
        for row in query.all():
            results.append({
                "id": row[0],
                "title": row[1],
                "mode": row[2],
                "created_at": row[3],
                "updated_at": row[4],
                "message_count": row[5],
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
        session = self._db.get(ConversationSession, session_id)
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
        session = self._db.get(ConversationSession, session_id)
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
        session = self._db.get(ConversationSession, session_id)
        if session:
            session.context_data = json.dumps(context_data)
            session.updated_at = utc_now_iso()
            self._db.commit()

    def soft_delete_session(self, session_id: str) -> None:
        """Soft-delete a session (set is_active = False).

        Args:
            session_id: Session ID.
        """
        session = self._db.get(ConversationSession, session_id)
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
