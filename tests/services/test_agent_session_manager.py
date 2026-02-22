"""Tests for AgentSessionManager.

Manages per-conversation agent sessions: creation, caching by session ID,
teardown, conversation history, and persistent agent lifecycle.
"""

import asyncio

import pytest

from src.services.agent_session_manager import AgentSession, AgentSessionManager

# =========================================================================
# Session Lifecycle
# =========================================================================


def test_create_new_session():
    """get_or_create_session creates a new session on first call."""
    mgr = AgentSessionManager()
    session = mgr.get_or_create_session("sess-1")
    assert isinstance(session, AgentSession)
    assert session.session_id == "sess-1"


def test_get_existing_session():
    """get_or_create_session returns the same session on subsequent calls."""
    mgr = AgentSessionManager()
    s1 = mgr.get_or_create_session("sess-1")
    s2 = mgr.get_or_create_session("sess-1")
    assert s1 is s2


def test_remove_session():
    """remove_session removes the session."""
    mgr = AgentSessionManager()
    mgr.get_or_create_session("sess-1")
    mgr.remove_session("sess-1")
    assert "sess-1" not in mgr.list_sessions()


def test_remove_nonexistent_session():
    """remove_session is idempotent — no error for missing session."""
    mgr = AgentSessionManager()
    mgr.remove_session("nonexistent")  # should not raise


def test_list_sessions():
    """list_sessions returns all active session IDs."""
    mgr = AgentSessionManager()
    mgr.get_or_create_session("a")
    mgr.get_or_create_session("b")
    mgr.get_or_create_session("c")
    sessions = mgr.list_sessions()
    assert set(sessions) == {"a", "b", "c"}


# =========================================================================
# Message & History
# =========================================================================


def test_add_message():
    """add_message appends to session history."""
    mgr = AgentSessionManager()
    mgr.get_or_create_session("sess-1")
    mgr.add_message("sess-1", "user", "Ship CA orders")
    history = mgr.get_history("sess-1")
    assert len(history) == 1
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Ship CA orders"


def test_get_history():
    """get_history returns ordered conversation messages."""
    mgr = AgentSessionManager()
    mgr.get_or_create_session("sess-1")
    mgr.add_message("sess-1", "user", "Ship CA orders")
    mgr.add_message("sess-1", "assistant", "I'll create a job for that.")
    mgr.add_message("sess-1", "user", "Yes, confirm it.")
    history = mgr.get_history("sess-1")
    assert len(history) == 3
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert history[2]["role"] == "user"


def test_get_history_empty_for_new_session():
    """New sessions have empty history."""
    mgr = AgentSessionManager()
    mgr.get_or_create_session("sess-1")
    assert mgr.get_history("sess-1") == []


def test_get_history_nonexistent_session():
    """get_history returns empty list for unknown session."""
    mgr = AgentSessionManager()
    assert mgr.get_history("nonexistent") == []


def test_add_message_creates_session_if_needed():
    """add_message auto-creates the session if it doesn't exist."""
    mgr = AgentSessionManager()
    mgr.add_message("auto-sess", "user", "Hello")
    assert "auto-sess" in mgr.list_sessions()
    assert len(mgr.get_history("auto-sess")) == 1


def test_session_has_timestamp():
    """Sessions record a created_at timestamp."""
    mgr = AgentSessionManager()
    session = mgr.get_or_create_session("sess-1")
    assert session.created_at is not None


def test_messages_have_timestamps():
    """Messages include a timestamp."""
    mgr = AgentSessionManager()
    mgr.get_or_create_session("sess-1")
    mgr.add_message("sess-1", "user", "hello")
    msg = mgr.get_history("sess-1")[0]
    assert "timestamp" in msg


# =========================================================================
# Agent Persistence (new in SDK leverage update)
# =========================================================================


def test_session_has_agent_attribute():
    """Session has an agent attribute, initially None."""
    session = AgentSession("test")
    assert session.agent is None


def test_session_has_source_hash_attribute():
    """Session has agent_source_hash for data source change detection."""
    session = AgentSession("test")
    assert session.agent_source_hash is None


def test_session_has_lock():
    """Session has an asyncio.Lock for message serialization."""
    session = AgentSession("test")
    assert isinstance(session.lock, asyncio.Lock)


def test_session_has_prewarm_task_attribute():
    """Session has prewarm_task attribute, initially None."""
    session = AgentSession("test")
    assert session.prewarm_task is None


def test_session_has_message_tasks_set():
    """Session tracks in-flight message tasks."""
    session = AgentSession("test")
    assert isinstance(session.message_tasks, set)
    assert len(session.message_tasks) == 0


def test_session_agent_can_be_set():
    """Agent can be set on a session externally."""
    session = AgentSession("test")
    mock_agent = object()  # Any object
    session.agent = mock_agent
    assert session.agent is mock_agent


def test_session_source_hash_can_be_set():
    """Source hash can be set for change tracking."""
    session = AgentSession("test")
    session.agent_source_hash = "csv|orders.csv|100|id,name"
    assert session.agent_source_hash == "csv|orders.csv|100|id,name"


@pytest.mark.asyncio
async def test_stop_session_agent_with_no_agent():
    """stop_session_agent is safe when no agent exists."""
    mgr = AgentSessionManager()
    mgr.get_or_create_session("sess-1")
    await mgr.stop_session_agent("sess-1")  # Should not raise


@pytest.mark.asyncio
async def test_stop_session_agent_nonexistent_session():
    """stop_session_agent is safe for nonexistent session."""
    mgr = AgentSessionManager()
    await mgr.stop_session_agent("nonexistent")  # Should not raise


@pytest.mark.asyncio
async def test_stop_session_agent_calls_stop():
    """stop_session_agent calls agent.stop() and clears reference."""
    from unittest.mock import AsyncMock

    mgr = AgentSessionManager()
    session = mgr.get_or_create_session("sess-1")
    mock_agent = AsyncMock()
    session.agent = mock_agent
    session.agent_source_hash = "test-hash"

    await mgr.stop_session_agent("sess-1")

    mock_agent.stop.assert_awaited_once()
    assert session.agent is None
    assert session.agent_source_hash is None


@pytest.mark.asyncio
async def test_stop_session_agent_handles_errors():
    """stop_session_agent handles errors from agent.stop() gracefully."""
    from unittest.mock import AsyncMock

    mgr = AgentSessionManager()
    session = mgr.get_or_create_session("sess-1")
    mock_agent = AsyncMock()
    mock_agent.stop.side_effect = RuntimeError("stop failed")
    session.agent = mock_agent

    # Should not raise despite agent.stop() failing
    await mgr.stop_session_agent("sess-1")

    # Agent should still be cleared
    assert session.agent is None


def test_session_terminating_defaults_false():
    """Session's terminating flag defaults to False."""
    session = AgentSession("test")
    assert session.terminating is False


def test_get_session_returns_none_for_unknown():
    """get_session returns None for a session that doesn't exist."""
    mgr = AgentSessionManager()
    assert mgr.get_session("nonexistent") is None


def test_get_session_returns_existing():
    """get_session returns the session when it exists."""
    mgr = AgentSessionManager()
    created = mgr.get_or_create_session("sess-1")
    fetched = mgr.get_session("sess-1")
    assert fetched is created


@pytest.mark.asyncio
async def test_cancel_session_prewarm_task_is_idempotent():
    """cancel_session_prewarm_task is safe when missing."""
    mgr = AgentSessionManager()
    await mgr.cancel_session_prewarm_task("missing")


@pytest.mark.asyncio
async def test_cancel_session_prewarm_task_cancels_active_task():
    """Active prewarm task is cancelled and cleared."""
    mgr = AgentSessionManager()
    session = mgr.get_or_create_session("sess-1")

    async def _work() -> None:
        await asyncio.sleep(5)

    task = asyncio.create_task(_work())
    session.prewarm_task = task
    await mgr.cancel_session_prewarm_task("sess-1")
    assert session.prewarm_task is None
    assert task.cancelled()


@pytest.mark.asyncio
async def test_cancel_session_message_tasks_cancels_active_tasks():
    """Active message tasks are cancelled and cleared."""
    mgr = AgentSessionManager()
    session = mgr.get_or_create_session("sess-1")

    async def _work() -> None:
        await asyncio.sleep(5)

    task = asyncio.create_task(_work())
    session.message_tasks.add(task)

    await mgr.cancel_session_message_tasks("sess-1")

    assert len(session.message_tasks) == 0
    assert task.cancelled()


class TestSessionTTL:
    """Tests for L-3: session idle timeout (CWE-613)."""

    @pytest.mark.asyncio
    async def test_session_has_last_active(self):
        """AgentSession tracks last_active timestamp."""
        session = AgentSession("test-1")
        assert hasattr(session, "last_active")
        assert session.last_active is not None

    @pytest.mark.asyncio
    async def test_add_message_updates_last_active(self):
        """add_message refreshes last_active."""
        session = AgentSession("test-1")
        original = session.last_active
        await asyncio.sleep(0.01)
        session.add_message("user", "hello")
        assert session.last_active > original

    @pytest.mark.asyncio
    async def test_reap_idle_sessions_removes_expired(self):
        """reap_idle_sessions removes sessions past TTL."""
        from datetime import UTC, datetime, timedelta

        import src.services.agent_session_manager as sm

        original_ttl = sm._SESSION_TTL_HOURS
        try:
            sm._SESSION_TTL_HOURS = 1  # 1 hour TTL

            mgr = AgentSessionManager()
            session = mgr.get_or_create_session("old-session")
            # Backdate last_active to 2 hours ago
            session.last_active = datetime.now(UTC) - timedelta(hours=2)

            active_session = mgr.get_or_create_session("active-session")
            active_session.last_active = datetime.now(UTC)

            reaped = await mgr.reap_idle_sessions()
            assert reaped == 1
            assert mgr.get_session("old-session") is None
            assert mgr.get_session("active-session") is not None
        finally:
            sm._SESSION_TTL_HOURS = original_ttl

    @pytest.mark.asyncio
    async def test_reap_disabled_when_ttl_zero(self):
        """reap_idle_sessions does nothing when TTL is 0."""
        import src.services.agent_session_manager as sm

        original_ttl = sm._SESSION_TTL_HOURS
        try:
            sm._SESSION_TTL_HOURS = 0

            mgr = AgentSessionManager()
            mgr.get_or_create_session("any-session")
            reaped = await mgr.reap_idle_sessions()
            assert reaped == 0
        finally:
            sm._SESSION_TTL_HOURS = original_ttl
