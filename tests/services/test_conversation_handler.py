"""Tests for the shared conversation handler service."""

import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.conversation_handler import compute_source_hash, ensure_agent, process_message

# Precompute the expected hash for empty contacts list
_EMPTY_CONTACTS_HASH = hashlib.sha256(str([]).encode()).hexdigest()[:8]
_NONE_HASH = f"none|interactive=False|contacts={_EMPTY_CONTACTS_HASH}"


class TestComputeSourceHash:
    """Tests for source hash computation."""

    def test_none_returns_none_string(self):
        """None source returns 'none'."""
        assert compute_source_hash(None) == "none"

    def test_same_input_same_hash(self):
        """Same source info produces same hash."""
        info = {"source_type": "csv", "path": "/tmp/test.csv"}
        assert compute_source_hash(info) == compute_source_hash(info)

    def test_different_input_different_hash(self):
        """Different source info produces different hash."""
        info1 = {"source_type": "csv", "path": "/tmp/a.csv"}
        info2 = {"source_type": "csv", "path": "/tmp/b.csv"}
        assert compute_source_hash(info1) != compute_source_hash(info2)


class TestEnsureAgent:
    """Tests for the ensure_agent() lifecycle function."""

    @pytest.mark.asyncio
    async def test_creates_agent_when_none_exists(self):
        """Creates and starts a new agent when session has no agent."""
        session = MagicMock()
        session.agent = None
        session.agent_source_hash = None
        session.session_id = "sess-1"

        mock_agent = AsyncMock()
        with (
            patch(
                "src.orchestrator.agent.client.OrchestrationAgent",
                return_value=mock_agent,
            ),
            patch(
                "src.orchestrator.agent.system_prompt.build_system_prompt",
                return_value="test prompt",
            ),
        ):
            result = await ensure_agent(session, source_info=None)

        assert result is True
        mock_agent.start.assert_called_once()
        assert session.agent is mock_agent

    @pytest.mark.asyncio
    async def test_reuses_agent_when_hash_unchanged(self):
        """Reuses existing agent when source hash matches."""
        session = MagicMock()
        session.agent = MagicMock()
        session.agent_source_hash = _NONE_HASH

        with patch(
            "src.services.conversation_handler._get_mru_contacts_for_prompt",
            return_value=[],
        ):
            result = await ensure_agent(session, source_info=None)

        assert result is False  # No new agent created

    @pytest.mark.asyncio
    async def test_rebuilds_agent_when_hash_changes(self):
        """Stops old agent and creates new one when source changes."""
        old_agent = AsyncMock()
        session = MagicMock()
        session.agent = old_agent
        session.agent_source_hash = "old_hash|interactive=False"
        session.session_id = "sess-1"

        new_agent = AsyncMock()
        with (
            patch(
                "src.orchestrator.agent.client.OrchestrationAgent",
                return_value=new_agent,
            ),
            patch(
                "src.orchestrator.agent.system_prompt.build_system_prompt",
                return_value="test prompt",
            ),
        ):
            result = await ensure_agent(session, source_info=None)

        assert result is True
        old_agent.stop.assert_called_once()
        new_agent.start.assert_called_once()
        assert session.agent is new_agent


class TestProcessMessage:
    """Tests for the process_message() streaming function."""

    @pytest.mark.asyncio
    async def test_yields_agent_events(self):
        """Yields events from the agent stream."""
        session = MagicMock()
        session.agent = MagicMock()
        session.agent_source_hash = _NONE_HASH
        session.lock = asyncio.Lock()

        # Mock agent stream
        async def fake_stream(content):
            yield {"event": "agent_message_delta", "data": {"text": "Hello"}}
            yield {"event": "agent_message", "data": {"text": "Hello world"}}

        session.agent.process_message_stream = fake_stream
        session.agent.emitter_bridge = MagicMock()

        with (
            patch(
                "src.services.conversation_handler.get_data_gateway",
                new_callable=AsyncMock,
            ) as mock_gw,
            patch(
                "src.services.conversation_handler._get_mru_contacts_for_prompt",
                return_value=[],
            ),
        ):
            mock_gw.return_value.get_source_info_typed = AsyncMock(return_value=None)
            events = []
            async for event in process_message(session, "Hello"):
                events.append(event)

        assert len(events) == 2
        assert events[0]["event"] == "agent_message_delta"
        assert events[1]["event"] == "agent_message"

    @pytest.mark.asyncio
    async def test_stores_assistant_history(self):
        """Stores assistant text in session history."""
        session = MagicMock()
        session.agent = MagicMock()
        session.agent_source_hash = _NONE_HASH
        session.lock = asyncio.Lock()

        async def fake_stream(content):
            yield {"event": "agent_message", "data": {"text": "Response text"}}

        session.agent.process_message_stream = fake_stream
        session.agent.emitter_bridge = MagicMock()

        with (
            patch(
                "src.services.conversation_handler.get_data_gateway",
                new_callable=AsyncMock,
            ) as mock_gw,
            patch(
                "src.services.conversation_handler._get_mru_contacts_for_prompt",
                return_value=[],
            ),
        ):
            mock_gw.return_value.get_source_info_typed = AsyncMock(return_value=None)
            async for _ in process_message(session, "Hello"):
                pass

        session.add_message.assert_called_once_with("assistant", "Response text")

    @pytest.mark.asyncio
    async def test_does_not_store_user_message(self):
        """Does NOT store user message — caller owns that."""
        session = MagicMock()
        session.agent = MagicMock()
        session.agent_source_hash = _NONE_HASH
        session.lock = asyncio.Lock()

        async def fake_stream(content):
            yield {"event": "agent_message", "data": {"text": "OK"}}

        session.agent.process_message_stream = fake_stream
        session.agent.emitter_bridge = MagicMock()

        with (
            patch(
                "src.services.conversation_handler.get_data_gateway",
                new_callable=AsyncMock,
            ) as mock_gw,
            patch(
                "src.services.conversation_handler._get_mru_contacts_for_prompt",
                return_value=[],
            ),
        ):
            mock_gw.return_value.get_source_info_typed = AsyncMock(return_value=None)
            async for _ in process_message(session, "User says hello"):
                pass

        # Only "assistant" messages stored, never "user"
        calls = session.add_message.call_args_list
        for call in calls:
            assert call[0][0] != "user", "process_message must not store user messages"

    @pytest.mark.asyncio
    async def test_sets_and_clears_emitter_callback(self):
        """Sets emitter bridge callback before processing and clears after."""
        session = MagicMock()
        session.agent = MagicMock()
        session.agent_source_hash = _NONE_HASH
        session.lock = asyncio.Lock()
        bridge = MagicMock()
        session.agent.emitter_bridge = bridge

        callback_was_set = False

        async def fake_stream(content):
            nonlocal callback_was_set
            callback_was_set = bridge.callback is not None
            yield {"event": "agent_message", "data": {"text": "Done"}}

        session.agent.process_message_stream = fake_stream

        callback = MagicMock()
        with (
            patch(
                "src.services.conversation_handler.get_data_gateway",
                new_callable=AsyncMock,
            ) as mock_gw,
            patch(
                "src.services.conversation_handler._get_mru_contacts_for_prompt",
                return_value=[],
            ),
        ):
            mock_gw.return_value.get_source_info_typed = AsyncMock(return_value=None)
            async for _ in process_message(
                session, "Test", emit_callback=callback
            ):
                pass

        # Callback was set during processing
        assert callback_was_set is True
        # Callback should be cleared in finally block
        assert bridge.callback is None
