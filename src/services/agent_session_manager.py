"""Agent session manager for per-conversation lifecycle.

Manages agent sessions keyed by conversation ID. Each session maintains
its own conversation history and a persistent OrchestrationAgent instance.
The agent stays alive across messages within the same session, leveraging
the Claude SDK's internal conversation memory. MCP servers are spawned once
on first message and persist until session deletion.

Example:
    mgr = AgentSessionManager()
    session = mgr.get_or_create_session("conv-123")
    mgr.add_message("conv-123", "user", "Ship CA orders")
    history = mgr.get_history("conv-123")
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class AgentSession:
    """A single conversation session with a persistent agent.

    The agent instance persists across messages so the Claude SDK maintains
    internal conversation history. An asyncio.Lock serializes message
    processing to prevent concurrent access to the same agent.

    Attributes:
        session_id: Unique conversation identifier.
        history: Ordered list of messages [{role, content, timestamp}].
        created_at: When the session was created.
        agent: Persistent OrchestrationAgent instance (None until first message).
        agent_source_hash: Hash of the data source used to build the agent's
            system prompt. If the data source changes, the agent is rebuilt.
        interactive_shipping: Whether interactive single-shipment mode is enabled.
        terminating: Whether a DELETE request is in progress for this session.
        lock: Async lock serializing message processing for this session.
        prewarm_task: Optional best-effort background task for agent prewarm.
    """

    def __init__(self, session_id: str) -> None:
        """Initialize a new session.

        Args:
            session_id: Unique conversation identifier.
        """
        self.session_id = session_id
        self.history: list[dict] = []
        self.created_at = datetime.now(timezone.utc)
        self.agent: Any = None  # OrchestrationAgent, set by conversations route
        self.agent_source_hash: str | None = None
        self.interactive_shipping: bool = False
        self.terminating: bool = False
        self.confirmed_resolutions: dict[str, Any] = {}  # token → confirmed ResolvedFilterSpec
        self.lock = asyncio.Lock()
        self.prewarm_task: asyncio.Task[Any] | None = None

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

    def get_session(self, session_id: str) -> AgentSession | None:
        """Get a session without auto-creating. Returns None if not found.

        Args:
            session_id: Unique conversation identifier.

        Returns:
            The AgentSession if it exists, None otherwise.
        """
        return self._sessions.get(session_id)

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
        """Remove a session from tracking (sync).

        Does NOT stop the agent — call stop_session_agent() first for
        async cleanup. Idempotent.

        Args:
            session_id: Session to remove.
        """
        session = self._sessions.pop(session_id, None)
        if session is not None:
            logger.info("Removed agent session: %s", session_id)

    async def stop_session_agent(self, session_id: str) -> None:
        """Stop the persistent agent for a session (async).

        Call this before remove_session() to cleanly shut down MCP servers.
        Idempotent — does nothing if no agent or session.

        Args:
            session_id: Session whose agent should be stopped.
        """
        session = self._sessions.get(session_id)
        if session is None or session.agent is None:
            return

        try:
            await session.agent.stop()
        except Exception as e:
            logger.warning("Error stopping agent for session %s: %s", session_id, e)
        finally:
            session.agent = None
            session.agent_source_hash = None

    async def cancel_session_prewarm_task(self, session_id: str) -> None:
        """Cancel and await a session's prewarm task, if active."""
        session = self._sessions.get(session_id)
        if session is None or session.prewarm_task is None:
            return
        task = session.prewarm_task
        session.prewarm_task = None
        if task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(
                "Error while cancelling prewarm task for session %s: %s",
                session_id,
                e,
            )

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
