"""Persistence service for conversation sessions and messages.

Thin layer between API routes and SQLAlchemy models. All conversation
history reads and writes go through this service. The frontend never
writes messages — the backend owns all persistence.
"""

import asyncio
import json
import logging
import os
from typing import Any, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

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

        messages = []
        for m in query.all():
            metadata = None
            if m.metadata_json:
                try:
                    metadata = json.loads(m.metadata_json)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Corrupted metadata_json for message %s", m.id)
            messages.append({
                "id": m.id,
                "role": m.role,
                "message_type": m.message_type,
                "content": m.content,
                "metadata": metadata,
                "sequence": m.sequence,
                "created_at": m.created_at,
            })

        context = None
        if session.context_data:
            try:
                context = json.loads(session.context_data)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Corrupted context_data for session %s", session.id)

        return {
            "session": {
                "id": session.id,
                "title": session.title,
                "mode": session.mode,
                "context_data": context,
                "is_active": session.is_active,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            },
            "messages": messages,
        }

    def update_session_title(self, session_id: str, title: str) -> bool:
        """Set the session title.

        Args:
            session_id: Session ID.
            title: New title string.

        Returns:
            True if session found and updated, False if not found.
        """
        session = self._db.get(ConversationSession, session_id)
        if session is None:
            return False
        session.title = title
        session.updated_at = utc_now_iso()
        self._db.commit()
        return True

    def update_session_context(
        self, session_id: str, context_data: dict[str, Any]
    ) -> bool:
        """Update the session's context snapshot.

        Args:
            session_id: Session ID.
            context_data: New context dict.

        Returns:
            True if session found and updated, False if not found.
        """
        session = self._db.get(ConversationSession, session_id)
        if session is None:
            return False
        session.context_data = json.dumps(context_data)
        session.updated_at = utc_now_iso()
        self._db.commit()
        return True

    def soft_delete_session(self, session_id: str) -> bool:
        """Soft-delete a session (set is_active = False).

        Args:
            session_id: Session ID.

        Returns:
            True if session found and deleted, False if not found.
        """
        session = self._db.get(ConversationSession, session_id)
        if session is None:
            return False
        session.is_active = False
        session.updated_at = utc_now_iso()
        self._db.commit()
        return True

    def count_assistant_messages(self, session_id: str) -> int:
        """Count assistant messages in a session.

        Args:
            session_id: Session ID.

        Returns:
            Number of assistant messages.
        """
        return (
            self._db.query(ConversationMessage)
            .filter_by(session_id=session_id, role="assistant")
            .count()
        )

    def has_title(self, session_id: str) -> bool:
        """Check if a session already has a title.

        Args:
            session_id: Session ID.

        Returns:
            True if session exists and has a non-empty title.
        """
        session = self._db.get(ConversationSession, session_id)
        return session is not None and bool(session.title)

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


# Default model for lightweight title generation
TITLE_MODEL = os.environ.get("TITLE_MODEL", "claude-haiku-4-5-20251001")


async def generate_session_title(session_id: str) -> None:
    """Generate a session title via a lightweight Haiku call.

    Fire-and-forget background task. Runs after the first assistant
    response is saved. Reads messages and writes the title back to DB.

    Args:
        session_id: Conversation session ID.
    """
    from src.db.connection import get_db_context

    try:
        with get_db_context() as db:
            svc = ConversationPersistenceService(db)
            result = svc.get_session_with_messages(session_id, limit=2)

        if result is None or len(result["messages"]) < 2:
            return

        if result["session"].get("title"):
            return

        user_msg = result["messages"][0]["content"][:200]
        assistant_msg = result["messages"][1]["content"][:200]

        from anthropic import AsyncAnthropic

        client = AsyncAnthropic()
        response = await client.messages.create(
            model=TITLE_MODEL,
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

        if not response.content:
            return
        title = response.content[0].text.strip()[:255]
        if title:
            with get_db_context() as db:
                svc = ConversationPersistenceService(db)
                svc.update_session_title(session_id, title)
            logger.info("Generated title for session %s: %s", session_id, title)

    except Exception as e:
        logger.warning("Title generation failed for session %s: %s", session_id, e)


def maybe_trigger_title_generation(session_id: str) -> None:
    """Check if this is the first assistant message and fire title generation.

    Best-effort — failures are logged at debug level.

    Args:
        session_id: Conversation session ID.
    """
    from src.db.connection import get_db_context

    try:
        with get_db_context() as db:
            svc = ConversationPersistenceService(db)
            if svc.has_title(session_id):
                return
            if svc.count_assistant_messages(session_id) == 1:
                asyncio.create_task(generate_session_title(session_id))
    except Exception as e:
        logger.debug("Title generation check failed for %s: %s", session_id, e)
