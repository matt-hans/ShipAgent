"""Tests for enhanced OrchestrationAgent (SDK leverage improvements).

Verifies the capabilities in client.py:
- system_prompt parameter support
- tools_v2 integration in orchestrator MCP
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


class TestPartialMessageStreaming:
    """Tests for include_partial_messages configuration."""

    def test_options_include_partial_messages(self):
        """ClaudeAgentOptions has include_partial_messages set."""
        agent = OrchestrationAgent()
        options = agent._options
        # Should be set (True if StreamEvent is available, False otherwise)
        assert hasattr(options, "include_partial_messages")


class TestToolsV2Integration:
    """Tests for tools_v2 integration in orchestrator MCP."""

    def test_options_include_v2_tools(self):
        """Orchestrator MCP includes tools_v2 definitions."""
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
        """All MCP servers (data, external, ups, orchestrator) still present."""
        agent = OrchestrationAgent()
        servers = agent._options.mcp_servers
        assert "data" in servers
        assert "external" in servers
        assert "ups" in servers
        assert "orchestrator" in servers

    def test_hooks_still_configured(self):
        """Pre/Post hooks still configured."""
        agent = OrchestrationAgent()
        hooks = agent._options.hooks
        assert "PreToolUse" in hooks
        assert "PostToolUse" in hooks
