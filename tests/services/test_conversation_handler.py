"""Tests for the shared conversation handler service."""

import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.conversation_handler import (
    _get_active_platform_summaries,
    compute_source_hash,
    ensure_agent,
    process_message,
)

# Precompute the expected hash for empty contacts list (matches JSON serialization)
_EMPTY_CONTACTS_HASH = hashlib.sha256(json.dumps([], sort_keys=True, default=str).encode()).hexdigest()[:8]
_EMPTY_PLATFORMS_HASH = hashlib.sha256(json.dumps([], sort_keys=True, default=str).encode()).hexdigest()[:8]
_PROMPT_CONTEXT_VERSION = "2026-02-28-platform-context-v2"


def _make_test_session_hash(
    source_hash: str = "none",
    interactive: bool = False,
    platforms: list[dict] | None = None,
) -> str:
    """Compute the combined hash that ensure_agent() will produce.

    Mirrors the ensure_agent hash in conversation_handler.
    """
    contacts_hash = hashlib.sha256(json.dumps([], sort_keys=True, default=str).encode()).hexdigest()[:8]
    platforms_hash = hashlib.sha256(
        json.dumps(platforms or [], sort_keys=True, default=str).encode(),
    ).hexdigest()[:8]
    return (
        f"v={_PROMPT_CONTEXT_VERSION}|{source_hash}|interactive={interactive}"
        f"|contacts={contacts_hash}|platforms={platforms_hash}"
    )


_CONTACTS_PATCH = "src.services.conversation_handler._get_mru_contacts_for_prompt"
_PLATFORMS_PATCH = "src.services.conversation_handler._get_active_platform_summaries"


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
        session.agent = AsyncMock()
        session.agent_source_hash = _make_test_session_hash()

        with (
            patch(_CONTACTS_PATCH, return_value=[]),
            patch(_PLATFORMS_PATCH, return_value=[]),
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


    @pytest.mark.asyncio
    async def test_fetches_column_samples_in_batch_mode(self):
        """Fetches column samples when source_info present and batch mode."""
        session = MagicMock()
        session.agent = None
        session.agent_source_hash = None
        session.session_id = "sess-1"

        mock_source = MagicMock()
        mock_source.__dict__ = {"source_type": "csv", "path": "/tmp/test.csv"}
        mock_agent = AsyncMock()
        mock_gw = AsyncMock()
        mock_gw.get_column_samples = AsyncMock(return_value={"city": ["NYC", "LA"]})

        with (
            patch(
                "src.orchestrator.agent.client.OrchestrationAgent",
                return_value=mock_agent,
            ),
            patch(
                "src.orchestrator.agent.system_prompt.build_system_prompt",
                return_value="test prompt",
            ) as mock_build,
            patch(
                "src.services.conversation_handler.get_data_gateway",
                new_callable=AsyncMock,
                return_value=mock_gw,
            ),
        ):
            result = await ensure_agent(session, source_info=mock_source, interactive_shipping=False)

        assert result is True
        mock_gw.get_column_samples.assert_called_once_with(max_samples=5)
        # Verify column_samples was passed to build_system_prompt
        _, kwargs = mock_build.call_args
        assert kwargs["column_samples"] == {"city": ["NYC", "LA"]}

    @pytest.mark.asyncio
    async def test_skips_column_samples_in_interactive_mode(self):
        """Skips column samples fetch in interactive mode."""
        session = MagicMock()
        session.agent = None
        session.agent_source_hash = None
        session.session_id = "sess-1"

        mock_source = MagicMock()
        mock_source.__dict__ = {"source_type": "csv", "path": "/tmp/test.csv"}
        mock_agent = AsyncMock()

        with (
            patch(
                "src.orchestrator.agent.client.OrchestrationAgent",
                return_value=mock_agent,
            ),
            patch(
                "src.orchestrator.agent.system_prompt.build_system_prompt",
                return_value="test prompt",
            ) as mock_build,
        ):
            result = await ensure_agent(session, source_info=mock_source, interactive_shipping=True)

        assert result is True
        # Verify column_samples is None in interactive mode
        _, kwargs = mock_build.call_args
        assert kwargs["column_samples"] is None


class TestProcessMessage:
    """Tests for the process_message() streaming function."""

    @pytest.mark.asyncio
    async def test_yields_agent_events(self):
        """Yields events from the agent stream."""
        session = MagicMock()
        session.agent = MagicMock()
        session.session_id = "sess-test-001"
        session.agent_source_hash = _make_test_session_hash()
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
            patch(_CONTACTS_PATCH, return_value=[]),
            patch(_PLATFORMS_PATCH, return_value=[]),
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
        session.session_id = "sess-test-001"
        session.agent_source_hash = _make_test_session_hash()
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
            patch(_CONTACTS_PATCH, return_value=[]),
            patch(_PLATFORMS_PATCH, return_value=[]),
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
        session.session_id = "sess-test-001"
        session.agent_source_hash = _make_test_session_hash()
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
            patch(_CONTACTS_PATCH, return_value=[]),
            patch(_PLATFORMS_PATCH, return_value=[]),
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
        session.session_id = "sess-test-001"
        session.agent_source_hash = _make_test_session_hash()
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
            patch(_CONTACTS_PATCH, return_value=[]),
            patch(_PLATFORMS_PATCH, return_value=[]),
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

    @pytest.mark.asyncio
    async def test_bootstraps_source_from_platforms_when_missing(self):
        """Missing source triggers refresh on sync-ready platforms before ensure_agent."""
        session = MagicMock()
        session.agent = MagicMock()
        session.session_id = "sess-test-001"
        session.agent_source_hash = _make_test_session_hash()
        session.lock = asyncio.Lock()

        async def fake_stream(content):
            yield {"event": "agent_message", "data": {"text": "Ready"}}

        session.agent.process_message_stream = fake_stream
        session.agent.emitter_bridge = MagicMock()

        mock_source = MagicMock()
        mock_gw = AsyncMock()
        mock_gw.get_source_info_typed = AsyncMock(side_effect=[None, mock_source])

        mock_summary = SimpleNamespace(
            platform_id="shopify",
            display_name="Shopify",
            credential_ref="primary",
            connection_status="disconnected",
            has_credentials=True,
            last_sync_row_count=42,
            account_label=None,
            is_active=True,
        )
        mock_registry = MagicMock()
        mock_registry.get_platforms_summary.return_value = [mock_summary]
        mock_activation = MagicMock()
        mock_activation.activate_platform = AsyncMock(return_value=MagicMock())

        with (
            patch(
                "src.services.conversation_handler.get_data_gateway",
                new_callable=AsyncMock,
                return_value=mock_gw,
            ),
            patch(
                "src.services.gateway_provider.get_platform_registry",
                return_value=mock_registry,
            ),
            patch(
                "src.services.gateway_provider.get_activation_service",
                return_value=mock_activation,
            ),
            patch(
                "src.services.conversation_handler.ensure_agent",
                new=AsyncMock(return_value=False),
            ) as mock_ensure_agent,
        ):
            async for _ in process_message(session, "Ship all orders"):
                pass

        mock_activation.activate_platform.assert_awaited_once_with(
            platform_id="shopify",
            credential_ref="primary",
            mode="refresh",
        )
        assert mock_ensure_agent.await_count == 1
        assert mock_ensure_agent.await_args.args[1] is mock_source


class TestPlatformSummaryNormalization:
    """Tests for prompt-facing platform summary normalization."""

    def test_uses_effective_sync_ready_status_for_active_credentialed_profile(self):
        """Disconnected runtime status is normalized when profile is sync-ready."""
        mock_summary = SimpleNamespace(
            platform_id="amazon",
            display_name="Amazon Seller Central",
            connection_status="disconnected",
            has_credentials=True,
            last_sync_row_count=None,
            account_label="US Store",
            is_active=True,
        )
        mock_registry = MagicMock()
        mock_registry.get_platforms_summary.return_value = [mock_summary]

        with patch(
            "src.services.gateway_provider.get_platform_registry",
            return_value=mock_registry,
        ):
            summaries = _get_active_platform_summaries()

        assert len(summaries) == 1
        assert summaries[0]["connection_status"] == "sync_ready"
        assert summaries[0]["raw_connection_status"] == "disconnected"
