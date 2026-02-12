"""Tests for AgentSessionManager.

Manages per-conversation agent sessions: creation, caching by session ID,
teardown, and conversation history.
"""

from src.services.agent_session_manager import AgentSession, AgentSessionManager


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
