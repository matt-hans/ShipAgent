"""Agent session manager for per-conversation lifecycle.

Manages agent sessions keyed by conversation ID. Each session maintains
its own conversation history. The actual OrchestrationAgent creation is
handled externally (wired in the conversations route).

Example:
    mgr = AgentSessionManager()
    session = mgr.get_or_create_session("conv-123")
    mgr.add_message("conv-123", "user", "Ship CA orders")
    history = mgr.get_history("conv-123")
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AgentSession:
    """A single conversation session with an agent.

    Attributes:
        session_id: Unique conversation identifier.
        history: Ordered list of messages [{role, content, timestamp}].
        created_at: When the session was created.
    """

    def __init__(self, session_id: str) -> None:
        """Initialize a new session.

        Args:
            session_id: Unique conversation identifier.
        """
        self.session_id = session_id
        self.history: list[dict] = []
        self.created_at = datetime.now(timezone.utc)

    def add_message(self, role: str, content: str) -> None:
        """Append a message to the conversation history.

        Args:
            role: Message role ('user' or 'assistant').
            content: Message content text.
        """
        self.history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


class AgentSessionManager:
    """Manages per-conversation agent sessions.

    Thread-safe for single-process usage (FastAPI's async loop).
    Not designed for multi-process deployment.

    Attributes:
        _sessions: Dict of session_id → AgentSession.
    """

    def __init__(self) -> None:
        """Initialize with no active sessions."""
        self._sessions: dict[str, AgentSession] = {}

    def get_or_create_session(self, session_id: str) -> AgentSession:
        """Get an existing session or create a new one.

        Args:
            session_id: Unique conversation identifier.

        Returns:
            The AgentSession for this conversation.
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = AgentSession(session_id)
            logger.info("Created new agent session: %s", session_id)
        return self._sessions[session_id]

    def remove_session(self, session_id: str) -> None:
        """Remove a session and free resources.

        Idempotent — does nothing if session doesn't exist.

        Args:
            session_id: Session to remove.
        """
        session = self._sessions.pop(session_id, None)
        if session is not None:
            logger.info("Removed agent session: %s", session_id)

    def list_sessions(self) -> list[str]:
        """List all active session IDs.

        Returns:
            List of active session ID strings.
        """
        return list(self._sessions.keys())

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """Add a message to a session's history.

        Auto-creates the session if it doesn't exist.

        Args:
            session_id: Target session.
            role: Message role ('user' or 'assistant').
            content: Message content text.
        """
        session = self.get_or_create_session(session_id)
        session.add_message(role, content)

    def get_history(self, session_id: str) -> list[dict]:
        """Get the conversation history for a session.

        Args:
            session_id: Target session.

        Returns:
            List of message dicts [{role, content, timestamp}].
            Empty list if session doesn't exist.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return []
        return list(session.history)
