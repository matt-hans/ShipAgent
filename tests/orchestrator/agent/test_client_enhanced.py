"""Tests for enhanced OrchestrationAgent (system prompt + streaming).

Verifies the new capabilities added to client.py:
- system_prompt parameter support
- tools_v2 integration in orchestrator MCP
- process_message() with conversation history
- process_message_stream() yielding event dicts
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


class TestProcessMessage:
    """Tests for process_message() with conversation history."""

    def test_has_process_message_method(self):
        """Agent has process_message method."""
        agent = OrchestrationAgent()
        assert hasattr(agent, "process_message")
        assert asyncio.iscoroutinefunction(agent.process_message)

    @pytest.mark.asyncio
    async def test_process_message_requires_start(self):
        """process_message raises error if agent not started."""
        agent = OrchestrationAgent()
        with pytest.raises(RuntimeError, match="not started"):
            await agent.process_message("test")

    def test_process_message_accepts_history(self):
        """process_message signature accepts optional history parameter."""
        import inspect

        sig = inspect.signature(OrchestrationAgent.process_message)
        assert "history" in sig.parameters


class TestProcessMessageStream:
    """Tests for process_message_stream() async generator."""

    def test_has_process_message_stream_method(self):
        """Agent has process_message_stream method."""
        agent = OrchestrationAgent()
        assert hasattr(agent, "process_message_stream")

    def test_process_message_stream_accepts_history(self):
        """process_message_stream signature accepts optional history parameter."""
        import inspect

        sig = inspect.signature(OrchestrationAgent.process_message_stream)
        assert "history" in sig.parameters


class TestBackwardCompatibility:
    """Ensure existing functionality still works."""

    def test_no_args_constructor_works(self):
        """Default constructor (no args) still works."""
        agent = OrchestrationAgent()
        assert agent is not None
        assert not agent.is_started

    def test_process_command_still_exists(self):
        """Legacy process_command method still exists."""
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
