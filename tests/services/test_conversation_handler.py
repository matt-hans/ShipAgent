"""Tests for the shared conversation handler service."""

import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.conversation_handler import (
    compute_source_hash,
    ensure_agent,
    process_message,
)

# Precompute the expected hash for empty contacts list (matches JSON serialization)
_EMPTY_CONTACTS_HASH = hashlib.sha256(json.dumps([], sort_keys=True, default=str).encode()).hexdigest()[:8]
_NONE_HASH = f"none|interactive=False|contacts={_EMPTY_CONTACTS_HASH}"


def _make_test_session_hash(source_hash: str = "none", interactive: bool = False) -> str:
    """Compute the combined hash that ensure_agent() will produce.

    Mirrors the 3-component hash in conversation_handler.ensure_agent():
        f"{source_hash}|interactive={interactive}|contacts={contacts_hash}"
    """
    contacts_hash = hashlib.sha256(json.dumps([], sort_keys=True, default=str).encode()).hexdigest()[:8]
    return f"{source_hash}|interactive={interactive}|contacts={contacts_hash}"


_CONTACTS_PATCH = "src.services.conversation_handler._get_mru_contacts_for_prompt"


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
                "src.services.conversation_handler.create_conversation_agent",
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

        with patch(_CONTACTS_PATCH, return_value=[]):
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
                "src.services.conversation_handler.create_conversation_agent",
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
                "src.services.conversation_handler.create_conversation_agent",
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
                "src.services.conversation_handler.create_conversation_agent",
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
    async def test_process_message_with_fake_runtime_streams_sse_contract(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", "fake")
        monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "false")
        monkeypatch.setenv("AGENT_AUDIT_ENABLED", "false")

        from src.services.conversation_runtime.fake_provider import FakeProviderClient
        from src.services.conversation_runtime.models import (
            ProviderStreamEvent,
            ProviderStreamEventType,
        )
        from src.services.conversation_runtime.runtime_session import (
            ConversationRuntimeSession,
        )

        provider = FakeProviderClient(
            script=[
                [
                    ProviderStreamEvent(
                        type=ProviderStreamEventType.TEXT_DELTA,
                        text="A",
                    ),
                    ProviderStreamEvent(
                        type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                        text="Answer",
                    ),
                    ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
                ]
            ]
        )
        session = MagicMock()
        session.session_id = "handler-fake"
        session.agent = ConversationRuntimeSession(
            provider=provider,
            system_prompt="system",
            interactive_shipping=False,
            session_id="handler-fake",
        )
        await session.agent.start()
        session.agent_source_hash = _make_test_session_hash()
        session.lock = asyncio.Lock()
        session.confirmed_resolutions = {}
        session.interactive_shipping = False

        with (
            patch(
                "src.services.conversation_handler.get_data_gateway",
                new_callable=AsyncMock,
            ) as mock_gw,
            patch(_CONTACTS_PATCH, return_value=[]),
            patch(
                "src.services.conversation_handler._persist_assistant_message",
            ) as persist_assistant,
        ):
            mock_gw.return_value.get_source_info_typed = AsyncMock(return_value=None)
            events = [event async for event in process_message(session, "hello")]

        assert [event["event"] for event in events] == [
            "agent_message_delta",
            "agent_message",
        ]
        persist_assistant.assert_called_once_with("handler-fake", "Answer")

    @pytest.mark.asyncio
    async def test_fake_runtime_artifact_callback_persists_once(self, monkeypatch):
        monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "true")
        monkeypatch.setenv("AGENT_AUDIT_ENABLED", "false")

        class FakeAgent:
            last_turn_count = 0

            def __init__(self):
                self.emitter_bridge = MagicMock(callback=None)

            async def process_message_stream(self, _content):
                self.emitter_bridge.callback(
                    "tracking_result",
                    {"tracking_number": "1Z999"},
                )
                yield {
                    "event": "tracking_result",
                    "data": {"tracking_number": "1Z999"},
                }

        session = MagicMock()
        session.session_id = "artifact-once"
        session.agent = FakeAgent()
        session.agent_source_hash = _make_test_session_hash()
        session.lock = asyncio.Lock()
        session.confirmed_resolutions = {}
        session.interactive_shipping = False
        emitted: list[dict] = []

        with (
            patch(
                "src.services.conversation_handler.get_data_gateway",
                new_callable=AsyncMock,
            ) as mock_gw,
            patch(_CONTACTS_PATCH, return_value=[]),
            patch(
                "src.services.conversation_handler._persist_artifact_message",
            ) as persist_artifact,
        ):
            mock_gw.return_value.get_source_info_typed = AsyncMock(return_value=None)
            async for event in process_message(
                session,
                "track 1Z999",
                emit_callback=lambda event_type, data: emitted.append(
                    {"event": event_type, "data": data}
                ),
            ):
                emitted.append(event)

        assert [event["event"] for event in emitted] == [
            "tracking_result",
            "tracking_result",
        ]
        persist_artifact.assert_called_once_with(
            "artifact-once",
            "tracking_result",
            {"tracking_number": "1Z999"},
        )

    @pytest.mark.asyncio
    async def test_suppresses_transient_assistant_messages_when_artifact_is_emitted(
        self,
        monkeypatch,
    ):
        """Artifact turns hide transient assistant text and persist the artifact."""
        monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "true")

        class FakeAgent:
            def __init__(self):
                self.emitter_bridge = SimpleNamespace(callback=None)

            async def process_message_stream(self, _content):
                if self.emitter_bridge.callback:
                    self.emitter_bridge.callback(
                        "preview_ready",
                        {"job_id": "job-1", "total_rows": 1, "preview_rows": []},
                    )
                yield {"event": "agent_message", "data": {"text": "draft"}}
                yield {"event": "agent_message", "data": {"text": "final"}}

        session = MagicMock()
        session.agent = FakeAgent()
        session.session_id = "svc-suppress"
        session.agent_source_hash = _make_test_session_hash()
        session.lock = asyncio.Lock()

        emitted_events = []

        def _emit(event_type, data):
            emitted_events.append({"event": event_type, "data": data})

        with (
            patch(
                "src.services.conversation_handler.get_data_gateway",
                new_callable=AsyncMock,
            ) as mock_gw,
            patch(_CONTACTS_PATCH, return_value=[]),
            patch(
                "src.services.conversation_handler._persist_artifact_message",
                create=True,
            ) as persist_artifact,
            patch(
                "src.services.conversation_handler._persist_assistant_message",
                create=True,
            ) as persist_assistant,
        ):
            mock_gw.return_value.get_source_info_typed = AsyncMock(return_value=None)
            yielded_events = [
                event
                async for event in process_message(
                    session,
                    "Ship all orders",
                    emit_callback=_emit,
                )
            ]

        assert yielded_events == []
        assert emitted_events == [
            {
                "event": "preview_ready",
                "data": {"job_id": "job-1", "total_rows": 1, "preview_rows": []},
            }
        ]
        persist_artifact.assert_called_once_with(
            "svc-suppress",
            "preview_ready",
            {"job_id": "job-1", "total_rows": 1, "preview_rows": []},
        )
        persist_assistant.assert_not_called()
        session.add_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_suppresses_transient_agent_message_deltas_when_artifact_is_emitted(
        self,
        monkeypatch,
    ):
        """Artifact turns hide transient assistant deltas as well as final text."""
        monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "true")

        class FakeAgent:
            def __init__(self):
                self.emitter_bridge = SimpleNamespace(callback=None)

            async def process_message_stream(self, _content):
                if self.emitter_bridge.callback:
                    self.emitter_bridge.callback(
                        "preview_ready",
                        {"job_id": "job-1", "total_rows": 1, "preview_rows": []},
                    )
                yield {
                    "event": "agent_message_delta",
                    "data": {"text": "draft token"},
                }
                yield {"event": "agent_message", "data": {"text": "final"}}

        session = MagicMock()
        session.agent = FakeAgent()
        session.session_id = "svc-suppress-delta"
        session.agent_source_hash = _make_test_session_hash()
        session.lock = asyncio.Lock()

        emitted_events = []

        def _emit(event_type, data):
            emitted_events.append({"event": event_type, "data": data})

        with (
            patch(
                "src.services.conversation_handler.get_data_gateway",
                new_callable=AsyncMock,
            ) as mock_gw,
            patch(_CONTACTS_PATCH, return_value=[]),
            patch(
                "src.services.conversation_handler._persist_artifact_message",
                create=True,
            ),
            patch(
                "src.services.conversation_handler._persist_assistant_message",
                create=True,
            ) as persist_assistant,
        ):
            mock_gw.return_value.get_source_info_typed = AsyncMock(return_value=None)
            yielded_events = [
                event
                async for event in process_message(
                    session,
                    "Ship all orders",
                    emit_callback=_emit,
                )
            ]

        assert yielded_events == []
        assert emitted_events == [
            {
                "event": "preview_ready",
                "data": {"job_id": "job-1", "total_rows": 1, "preview_rows": []},
            }
        ]
        persist_assistant.assert_not_called()
        session.add_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_yields_bridge_artifact_events_without_external_emit_callback(self):
        """Non-SSE callers still receive artifacts emitted through the bridge."""

        class FakeAgent:
            def __init__(self):
                self.emitter_bridge = SimpleNamespace(callback=None)

            async def process_message_stream(self, _content):
                if self.emitter_bridge.callback:
                    self.emitter_bridge.callback(
                        "preview_ready",
                        {"job_id": "job-1", "total_rows": 1, "preview_rows": []},
                    )
                if False:
                    yield {}

        session = MagicMock()
        session.agent = FakeAgent()
        session.session_id = "svc-bridge-artifact"
        session.agent_source_hash = _make_test_session_hash()
        session.lock = asyncio.Lock()

        with (
            patch(
                "src.services.conversation_handler.get_data_gateway",
                new_callable=AsyncMock,
            ) as mock_gw,
            patch(_CONTACTS_PATCH, return_value=[]),
            patch(
                "src.services.conversation_handler._persist_artifact_message",
                create=True,
            ) as persist_artifact,
        ):
            mock_gw.return_value.get_source_info_typed = AsyncMock(return_value=None)
            events = [
                event
                async for event in process_message(
                    session,
                    "Ship all orders",
                    emit_callback=None,
                )
            ]

        assert events == [
            {
                "event": "preview_ready",
                "data": {"job_id": "job-1", "total_rows": 1, "preview_rows": []},
            }
        ]
        persist_artifact.assert_called_once_with(
            "svc-bridge-artifact",
            "preview_ready",
            {"job_id": "job-1", "total_rows": 1, "preview_rows": []},
        )

    @pytest.mark.asyncio
    async def test_keeps_final_buffered_assistant_message_when_no_artifact(
        self,
        monkeypatch,
    ):
        """Non-artifact turns emit and persist only the final buffered text."""
        monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "true")

        class FakeAgent:
            def __init__(self):
                self.emitter_bridge = SimpleNamespace(callback=None)

            async def process_message_stream(self, _content):
                yield {"event": "agent_message", "data": {"text": "draft"}}
                yield {"event": "agent_message", "data": {"text": "final answer"}}

        session = MagicMock()
        session.agent = FakeAgent()
        session.session_id = "svc-final-buffer"
        session.agent_source_hash = _make_test_session_hash()
        session.lock = asyncio.Lock()

        with (
            patch(
                "src.services.conversation_handler.get_data_gateway",
                new_callable=AsyncMock,
            ) as mock_gw,
            patch(_CONTACTS_PATCH, return_value=[]),
            patch(
                "src.services.conversation_handler._persist_assistant_message",
            ) as persist_assistant,
        ):
            mock_gw.return_value.get_source_info_typed = AsyncMock(return_value=None)
            events = [
                event
                async for event in process_message(
                    session,
                    "Ship all orders",
                )
            ]

        assert events == [
            {"event": "agent_message", "data": {"text": "final answer"}}
        ]
        session.add_message.assert_called_once_with("assistant", "final answer")
        persist_assistant.assert_called_once_with("svc-final-buffer", "final answer")

    @pytest.mark.asyncio
    async def test_yields_agent_events(self, monkeypatch):
        """Yields events from the agent stream."""
        monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "false")

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
