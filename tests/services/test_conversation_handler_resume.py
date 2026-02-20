"""Tests for _load_prior_conversation and ensure_agent resume wiring."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
from src.services.conversation_persistence_service import ConversationPersistenceService

# Pre-load submodules so patch() can resolve dotted paths for lazy imports
import src.orchestrator.agent.client  # noqa: F401
import src.orchestrator.agent.system_prompt  # noqa: F401


@pytest.fixture
def db_session():
    """In-memory SQLite for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def _seed_session_with_messages(db_session, session_id: str, count: int = 5):
    """Seed a session with messages for testing."""
    svc = ConversationPersistenceService(db_session)
    svc.create_session(session_id=session_id, mode="batch")
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        svc.save_message(session_id, role, f"Message {i}")


def _mock_db_context(db_session):
    """Create a context manager mock for get_db_context."""
    @contextmanager
    def fake_ctx():
        yield db_session
    return fake_ctx


class TestLoadPriorConversation:
    """Unit tests for _load_prior_conversation helper."""

    def test_returns_none_for_missing_session(self, db_session):
        """Non-existent session returns None."""
        with patch("src.db.connection.get_db_context", _mock_db_context(db_session)):
            from src.services.conversation_handler import _load_prior_conversation
            result = _load_prior_conversation("nonexistent")
            assert result is None

    def test_returns_messages_for_existing_session(self, db_session):
        """Existing session returns {role, content} list."""
        _seed_session_with_messages(db_session, "test-session", count=3)

        with patch("src.db.connection.get_db_context", _mock_db_context(db_session)):
            from src.services.conversation_handler import _load_prior_conversation
            result = _load_prior_conversation("test-session")
            assert result is not None
            assert len(result) == 3
            assert all("role" in m and "content" in m for m in result)

    def test_returns_none_for_empty_messages(self, db_session):
        """Session with no messages returns None."""
        svc = ConversationPersistenceService(db_session)
        svc.create_session(session_id="empty-session", mode="batch")

        with patch("src.db.connection.get_db_context", _mock_db_context(db_session)):
            from src.services.conversation_handler import _load_prior_conversation
            result = _load_prior_conversation("empty-session")
            assert result is None

    def test_db_error_returns_none(self):
        """Database error is caught and returns None."""
        def failing_ctx():
            raise RuntimeError("DB is down")

        with patch("src.db.connection.get_db_context", failing_ctx):
            from src.services.conversation_handler import _load_prior_conversation
            result = _load_prior_conversation("any-session")
            assert result is None


class TestEnsureAgentPriorConversation:
    """Verify ensure_agent loads prior conversation from DB."""

    @pytest.mark.asyncio
    async def test_new_session_passes_none_prior_conversation(self):
        """A brand-new session with no DB history passes None to build_system_prompt."""
        mock_session = MagicMock()
        mock_session.agent = None
        mock_session.agent_source_hash = None
        mock_session.session_id = "new-session-no-db"

        mock_agent_instance = AsyncMock()
        mock_prompt = MagicMock(return_value="test prompt")

        with patch("src.services.conversation_handler._load_prior_conversation", return_value=None), \
             patch("src.services.conversation_handler._get_mru_contacts_for_prompt", return_value=[]), \
             patch("src.orchestrator.agent.system_prompt.build_system_prompt", mock_prompt), \
             patch("src.orchestrator.agent.client.OrchestrationAgent", return_value=mock_agent_instance):

            from src.services.conversation_handler import ensure_agent
            await ensure_agent(mock_session, source_info=None)

            mock_prompt.assert_called_once()
            call_kwargs = mock_prompt.call_args[1]
            assert call_kwargs.get("prior_conversation") is None

    @pytest.mark.asyncio
    async def test_resumed_session_passes_prior_conversation(self, db_session):
        """A session with DB history passes messages to build_system_prompt."""
        _seed_session_with_messages(db_session, "resume-session", count=4)

        mock_session = MagicMock()
        mock_session.agent = None
        mock_session.agent_source_hash = None
        mock_session.session_id = "resume-session"

        mock_agent_instance = AsyncMock()
        mock_prompt = MagicMock(return_value="test prompt")

        def mock_load(session_id):
            """Simulate _load_prior_conversation reading from test DB."""
            svc = ConversationPersistenceService(db_session)
            result = svc.get_session_with_messages(session_id, limit=30)
            if result is None or not result["messages"]:
                return None
            return [
                {"role": m["role"], "content": m["content"]}
                for m in result["messages"]
            ]

        with patch("src.services.conversation_handler._load_prior_conversation", side_effect=mock_load), \
             patch("src.services.conversation_handler._get_mru_contacts_for_prompt", return_value=[]), \
             patch("src.orchestrator.agent.system_prompt.build_system_prompt", mock_prompt), \
             patch("src.orchestrator.agent.client.OrchestrationAgent", return_value=mock_agent_instance):

            from src.services.conversation_handler import ensure_agent
            await ensure_agent(mock_session, source_info=None)

            mock_prompt.assert_called_once()
            call_kwargs = mock_prompt.call_args[1]
            prior = call_kwargs.get("prior_conversation")
            assert prior is not None
            assert len(prior) == 4
            assert prior[0]["content"] == "Message 0"
