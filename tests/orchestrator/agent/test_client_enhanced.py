"""Tests for enhanced OrchestrationAgent (SDK leverage improvements).

Verifies the capabilities in client.py:
- system_prompt parameter support
- tools/ package integration in orchestrator MCP
- process_message_stream() yielding event dicts (no history param)
- include_partial_messages for real-time streaming
- model configuration
- interrupt() support
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator.agent.client import OrchestrationAgent


class TestSystemPromptSupport:
    """Tests for system_prompt parameter."""

    def test_constructor_accepts_system_prompt(self):
        """OrchestrationAgent accepts a system_prompt parameter."""
        agent = OrchestrationAgent(system_prompt="You are ShipAgent.")
        assert agent._system_prompt == "You are ShipAgent."

    def test_constructor_default_system_prompt_is_none(self):
        """Default system_prompt is None (backward compatible)."""
        agent = OrchestrationAgent()
        assert agent._system_prompt is None

    def test_options_include_system_prompt(self):
        """ClaudeAgentOptions includes the system prompt when provided."""
        agent = OrchestrationAgent(system_prompt="Test prompt")
        options = agent._options
        assert options.system_prompt == "Test prompt"

    def test_options_system_prompt_none_when_not_provided(self):
        """ClaudeAgentOptions system_prompt is None when not provided."""
        agent = OrchestrationAgent()
        options = agent._options
        assert options.system_prompt is None


class TestModelConfiguration:
    """Tests for model parameter and configuration."""

    def test_constructor_accepts_model(self):
        """OrchestrationAgent accepts a model parameter."""
        agent = OrchestrationAgent(model="claude-opus-4-6")
        assert agent._model == "claude-opus-4-6"

    def test_default_model_is_set(self):
        """Default model is set (not None)."""
        agent = OrchestrationAgent()
        assert agent._model is not None
        assert len(agent._model) > 0

    def test_options_include_model(self):
        """ClaudeAgentOptions includes the model."""
        agent = OrchestrationAgent(model="test-model")
        assert agent._options.model == "test-model"

    def test_uses_agent_model_env_when_set(self, monkeypatch):
        """AGENT_MODEL env var is preferred for default selection."""
        monkeypatch.setenv("AGENT_MODEL", "claude-haiku-4-5-20251001")
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        from importlib import reload
        import src.orchestrator.agent.client as client_mod

        reload(client_mod)
        agent = client_mod.OrchestrationAgent()
        assert agent._model == "claude-haiku-4-5-20251001"

    def test_uses_legacy_anthropic_model_env_when_agent_model_missing(self, monkeypatch):
        """ANTHROPIC_MODEL remains supported for backward compatibility."""
        monkeypatch.delenv("AGENT_MODEL", raising=False)
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
        from importlib import reload
        import src.orchestrator.agent.client as client_mod

        reload(client_mod)
        agent = client_mod.OrchestrationAgent()
        assert agent._model == "claude-sonnet-4-5-20250929"


class TestPartialMessageStreaming:
    """Tests for include_partial_messages configuration."""

    def test_options_include_partial_messages(self):
        """ClaudeAgentOptions has include_partial_messages set."""
        agent = OrchestrationAgent()
        options = agent._options
        # Should be set (True if StreamEvent is available, False otherwise)
        assert hasattr(options, "include_partial_messages")


class TestToolsV2Integration:
    """Tests for tools/ package integration in orchestrator MCP."""

    def test_options_include_v2_tools(self):
        """Orchestrator MCP includes tool definitions from tools/ package."""
        agent = OrchestrationAgent()
        mcp_servers = agent._options.mcp_servers
        assert "orchestrator" in mcp_servers

    def test_orchestrator_mcp_still_registered(self):
        """Orchestrator MCP server is still present in options."""
        agent = OrchestrationAgent()
        assert "orchestrator" in agent._options.mcp_servers


class TestProcessMessageStream:
    """Tests for process_message_stream() async generator."""

    def test_has_process_message_stream_method(self):
        """Agent has process_message_stream method."""
        agent = OrchestrationAgent()
        assert hasattr(agent, "process_message_stream")

    def test_process_message_stream_no_history_param(self):
        """process_message_stream no longer accepts history parameter.

        The SDK maintains conversation history internally, so the
        history parameter was removed.
        """
        import inspect

        sig = inspect.signature(OrchestrationAgent.process_message_stream)
        assert "history" not in sig.parameters

    def test_process_message_stream_accepts_user_input(self):
        """process_message_stream accepts user_input parameter."""
        import inspect

        sig = inspect.signature(OrchestrationAgent.process_message_stream)
        assert "user_input" in sig.parameters

    @pytest.mark.asyncio
    async def test_dedups_tool_call_between_stream_and_assistant_by_id(self):
        """StreamEvent and AssistantMessage for same tool id emit one tool_call."""

        class FakeStreamEvent:
            def __init__(self, event):
                self.event = event

        class FakeToolUseBlock:
            def __init__(self, block_id, name, block_input):
                self.id = block_id
                self.name = name
                self.input = block_input

        class FakeAssistantMessage:
            def __init__(self, content):
                self.content = content

        class FakeResultMessage:
            def __init__(self, is_error=False, result=""):
                self.is_error = is_error
                self.result = result

        async def _gen():
            yield FakeStreamEvent({
                "type": "content_block_start",
                "content_block": {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "batch_preview",
                    "input": {"job_id": "j1"},
                },
            })
            yield FakeAssistantMessage([
                FakeToolUseBlock("tool-1", "batch_preview", {"job_id": "j1"}),
            ])
            yield FakeResultMessage()

        agent = OrchestrationAgent()
        agent._started = True
        agent._client = MagicMock()
        agent._client.query = AsyncMock(return_value=None)
        agent._client.receive_response = MagicMock(return_value=_gen())

        with patch("src.orchestrator.agent.client._HAS_STREAM_EVENT", True), \
             patch("src.orchestrator.agent.client.StreamEvent", FakeStreamEvent), \
             patch("src.orchestrator.agent.client.AssistantMessage", FakeAssistantMessage), \
             patch("src.orchestrator.agent.client.ToolUseBlock", FakeToolUseBlock), \
             patch("src.orchestrator.agent.client.ResultMessage", FakeResultMessage):
            events = [e async for e in agent.process_message_stream("Ship CA orders")]

        tool_calls = [e for e in events if e["event"] == "tool_call"]
        assert len(tool_calls) == 1

    @pytest.mark.asyncio
    async def test_missing_stream_event_id_emits_from_assistant_only(self):
        """When StreamEvent tool_use has no id, AssistantMessage provides the tool_call."""

        class FakeStreamEvent:
            def __init__(self, event):
                self.event = event

        class FakeToolUseBlock:
            def __init__(self, block_id, name, block_input):
                self.id = block_id
                self.name = name
                self.input = block_input

        class FakeAssistantMessage:
            def __init__(self, content):
                self.content = content

        class FakeResultMessage:
            def __init__(self, is_error=False, result=""):
                self.is_error = is_error
                self.result = result

        async def _gen():
            yield FakeStreamEvent({
                "type": "content_block_start",
                "content_block": {
                    "type": "tool_use",
                    "name": "batch_preview",
                    "input": {},
                },
            })
            yield FakeAssistantMessage([
                FakeToolUseBlock("tool-2", "batch_preview", {"job_id": "j2"}),
            ])
            yield FakeResultMessage()

        agent = OrchestrationAgent()
        agent._started = True
        agent._client = MagicMock()
        agent._client.query = AsyncMock(return_value=None)
        agent._client.receive_response = MagicMock(return_value=_gen())

        with patch("src.orchestrator.agent.client._HAS_STREAM_EVENT", True), \
             patch("src.orchestrator.agent.client.StreamEvent", FakeStreamEvent), \
             patch("src.orchestrator.agent.client.AssistantMessage", FakeAssistantMessage), \
             patch("src.orchestrator.agent.client.ToolUseBlock", FakeToolUseBlock), \
             patch("src.orchestrator.agent.client.ResultMessage", FakeResultMessage):
            events = [e async for e in agent.process_message_stream("Ship CA orders")]

        tool_calls = [e for e in events if e["event"] == "tool_call"]
        assert len(tool_calls) == 1
        assert tool_calls[0]["data"]["tool_input"] == {"job_id": "j2"}

    @pytest.mark.asyncio
    async def test_tool_dedup_tracking_resets_each_assistant_turn(self):
        """Same tool id can appear in later turns due per-turn dedup reset."""

        class FakeToolUseBlock:
            def __init__(self, block_id, name, block_input):
                self.id = block_id
                self.name = name
                self.input = block_input

        class FakeAssistantMessage:
            def __init__(self, content):
                self.content = content

        class FakeResultMessage:
            def __init__(self, is_error=False, result=""):
                self.is_error = is_error
                self.result = result

        async def _gen():
            yield FakeAssistantMessage([
                FakeToolUseBlock("same-id", "fetch_rows", {"where_clause": "state='CA'"}),
            ])
            yield FakeAssistantMessage([
                FakeToolUseBlock("same-id", "fetch_rows", {"where_clause": "state='NY'"}),
            ])
            yield FakeResultMessage()

        agent = OrchestrationAgent()
        agent._started = True
        agent._client = MagicMock()
        agent._client.query = AsyncMock(return_value=None)
        agent._client.receive_response = MagicMock(return_value=_gen())

        with patch("src.orchestrator.agent.client._HAS_STREAM_EVENT", False), \
             patch("src.orchestrator.agent.client.AssistantMessage", FakeAssistantMessage), \
             patch("src.orchestrator.agent.client.ToolUseBlock", FakeToolUseBlock), \
             patch("src.orchestrator.agent.client.ResultMessage", FakeResultMessage):
            events = [e async for e in agent.process_message_stream("Ship orders")]

        tool_calls = [e for e in events if e["event"] == "tool_call"]
        assert len(tool_calls) == 2

    @pytest.mark.asyncio
    async def test_records_last_turn_count_from_assistant_messages(self):
        """last_turn_count reflects assistant turns in last streamed request."""

        class FakeTextBlock:
            def __init__(self, text):
                self.text = text

        class FakeAssistantMessage:
            def __init__(self, content):
                self.content = content

        class FakeResultMessage:
            def __init__(self, is_error=False, result=""):
                self.is_error = is_error
                self.result = result

        async def _gen():
            yield FakeAssistantMessage([FakeTextBlock("one")])
            yield FakeAssistantMessage([FakeTextBlock("two")])
            yield FakeResultMessage()

        agent = OrchestrationAgent()
        agent._started = True
        agent._client = MagicMock()
        agent._client.query = AsyncMock(return_value=None)
        agent._client.receive_response = MagicMock(return_value=_gen())

        with patch("src.orchestrator.agent.client._HAS_STREAM_EVENT", False), \
             patch("src.orchestrator.agent.client.AssistantMessage", FakeAssistantMessage), \
             patch("src.orchestrator.agent.client.TextBlock", FakeTextBlock), \
             patch("src.orchestrator.agent.client.ResultMessage", FakeResultMessage):
            _ = [e async for e in agent.process_message_stream("Ship orders")]

        assert agent.last_turn_count == 2


class TestInterruptSupport:
    """Tests for interrupt() method."""

    def test_has_interrupt_method(self):
        """Agent has interrupt method."""
        agent = OrchestrationAgent()
        assert hasattr(agent, "interrupt")
        assert asyncio.iscoroutinefunction(agent.interrupt)

    @pytest.mark.asyncio
    async def test_interrupt_without_client_is_safe(self):
        """Calling interrupt without a client should not raise."""
        agent = OrchestrationAgent()
        await agent.interrupt()  # Should not raise


class TestBackwardCompatibility:
    """Ensure existing functionality still works."""

    def test_no_args_constructor_works(self):
        """Default constructor (no args) still works."""
        agent = OrchestrationAgent()
        assert agent is not None
        assert not agent.is_started

    def test_process_command_still_exists(self):
        """process_command method still exists."""
        agent = OrchestrationAgent()
        assert hasattr(agent, "process_command")
        assert asyncio.iscoroutinefunction(agent.process_command)

    def test_mcp_servers_still_configured(self):
        """Core MCP servers (ups, orchestrator) still present; data via gateway."""
        agent = OrchestrationAgent()
        servers = agent._options.mcp_servers
        assert "ups" in servers
        assert "orchestrator" in servers
        # Data MCP removed from agent — gateway_provider owns the singleton
        assert "data" not in servers

    def test_hooks_still_configured(self):
        """Pre/Post hooks still configured."""
        agent = OrchestrationAgent()
        hooks = agent._options.hooks
        assert "PreToolUse" in hooks
        assert "PostToolUse" in hooks
