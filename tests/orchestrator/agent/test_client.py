"""Integration tests for src/orchestrator/agent/client.py.

Tests verify:
- OrchestrationAgent can be instantiated
- Agent lifecycle (start/stop) works correctly
- Context manager interface works
- Agent maintains conversation context
- UPS MCP is registered alongside other MCP servers

Note: Full integration tests require ANTHROPIC_API_KEY and MCP servers.
These tests are marked with @pytest.mark.integration for selective running.
"""

import asyncio
import os

import pytest

from src.orchestrator.agent.client import OrchestrationAgent, create_agent


class TestOrchestrationAgentUnit:
    """Unit tests for OrchestrationAgent that don't require API key."""

    def test_can_instantiate(self):
        """Should create agent without errors."""
        agent = OrchestrationAgent()
        assert agent is not None
        assert not agent.is_started

    def test_default_options(self):
        """Should have default options configured."""
        agent = OrchestrationAgent()
        # Check internal options exist
        assert agent._options is not None

    def test_custom_max_turns(self):
        """Should accept custom max_turns."""
        agent = OrchestrationAgent(max_turns=100)
        assert agent is not None

    def test_custom_permission_mode(self):
        """Should accept custom permission_mode."""
        agent = OrchestrationAgent(permission_mode="bypassPermissions")
        assert agent is not None

    def test_has_lifecycle_methods(self):
        """Should have start, stop, process_command methods."""
        agent = OrchestrationAgent()
        assert hasattr(agent, "start")
        assert hasattr(agent, "stop")
        assert hasattr(agent, "process_command")
        assert asyncio.iscoroutinefunction(agent.start)
        assert asyncio.iscoroutinefunction(agent.stop)
        assert asyncio.iscoroutinefunction(agent.process_command)

    def test_has_context_manager(self):
        """Should support async context manager."""
        agent = OrchestrationAgent()
        assert hasattr(agent, "__aenter__")
        assert hasattr(agent, "__aexit__")

    def test_is_started_property(self):
        """is_started should be accessible and false initially."""
        agent = OrchestrationAgent()
        assert hasattr(agent, "is_started")
        assert agent.is_started is False

    @pytest.mark.asyncio
    async def test_process_command_requires_start(self):
        """Should raise error if process_command called before start."""
        agent = OrchestrationAgent()
        with pytest.raises(RuntimeError, match="not started"):
            await agent.process_command("test")

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        """Stop should be safe to call even if not started."""
        agent = OrchestrationAgent()
        await agent.stop()  # Should not raise
        assert not agent.is_started


class TestAgentOptions:
    """Tests for agent options configuration."""

    def test_options_has_mcp_servers(self):
        """Options should configure MCP servers."""
        agent = OrchestrationAgent()
        options = agent._options
        assert options.mcp_servers is not None
        assert len(options.mcp_servers) >= 4  # orchestrator, data, external, ups

    def test_options_has_allowed_tools(self):
        """Options should configure allowed tools."""
        agent = OrchestrationAgent()
        options = agent._options
        assert options.allowed_tools is not None
        assert len(options.allowed_tools) >= 1

    def test_options_has_hooks(self):
        """Options should configure hooks."""
        agent = OrchestrationAgent()
        options = agent._options
        assert options.hooks is not None

    def test_has_data_mcp(self):
        """Options should include Data MCP."""
        agent = OrchestrationAgent()
        mcp_servers = agent._options.mcp_servers
        assert "data" in mcp_servers

    def test_has_external_mcp(self):
        """Options should include External Sources MCP."""
        agent = OrchestrationAgent()
        mcp_servers = agent._options.mcp_servers
        assert "external" in mcp_servers

    def test_has_orchestrator_mcp(self):
        """Options should include orchestrator MCP for native tools."""
        agent = OrchestrationAgent()
        mcp_servers = agent._options.mcp_servers
        assert "orchestrator" in mcp_servers

    def test_has_ups_mcp(self):
        """Options should include UPS MCP for interactive UPS operations."""
        agent = OrchestrationAgent()
        mcp_servers = agent._options.mcp_servers
        assert "ups" in mcp_servers

    def test_allowed_tools_includes_wildcards(self):
        """Allowed tools should include MCP wildcards."""
        agent = OrchestrationAgent()
        allowed = agent._options.allowed_tools
        # Should have wildcards for each MCP namespace
        has_orchestrator = any("orchestrator" in t for t in allowed)
        has_data = any("data" in t for t in allowed)
        has_external = any("external" in t for t in allowed)
        has_ups = any("ups" in t for t in allowed)
        assert has_orchestrator
        assert has_data
        assert has_external
        assert has_ups


class TestAgentHooksConfiguration:
    """Tests for agent hooks configuration."""

    def test_has_pretooluse_hooks(self):
        """Options should configure PreToolUse hooks."""
        agent = OrchestrationAgent()
        hooks = agent._options.hooks
        assert "PreToolUse" in hooks
        assert len(hooks["PreToolUse"]) >= 1

    def test_has_posttooluse_hooks(self):
        """Options should configure PostToolUse hooks."""
        agent = OrchestrationAgent()
        hooks = agent._options.hooks
        assert "PostToolUse" in hooks
        assert len(hooks["PostToolUse"]) >= 1


@pytest.mark.integration
class TestOrchestrationAgentIntegration:
    """Integration tests requiring ANTHROPIC_API_KEY.

    Run with: pytest -m integration
    Skip with: pytest -m "not integration"
    """

    @pytest.fixture
    def skip_without_api_key(self):
        """Skip test if API key not available."""
        if not os.environ.get("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set")

    @pytest.mark.asyncio
    async def test_agent_lifecycle(self, skip_without_api_key):
        """Agent should start, process command, and stop."""
        agent = OrchestrationAgent()

        await agent.start()
        assert agent.is_started

        # Process a simple command
        response = await agent.process_command("List available tools")
        assert response  # Got some response

        await agent.stop()
        assert not agent.is_started

    @pytest.mark.asyncio
    async def test_context_manager(self, skip_without_api_key):
        """Agent should work as context manager."""
        async with OrchestrationAgent() as agent:
            assert agent.is_started
            response = await agent.process_command("What tools are available?")
            assert response

        # Agent should be stopped after exit
        assert not agent.is_started

    @pytest.mark.asyncio
    async def test_create_agent_factory(self, skip_without_api_key):
        """create_agent should return started agent."""
        agent = await create_agent()
        assert agent.is_started

        await agent.stop()

    @pytest.mark.asyncio
    async def test_conversation_context(self, skip_without_api_key):
        """Agent should maintain context across commands."""
        async with OrchestrationAgent() as agent:
            # First command establishes context
            await agent.process_command("Remember the number 42")

            # Second command references previous context
            response = await agent.process_command("What number did I mention?")

            # Response should reference 42 (context maintained)
            assert "42" in response

    @pytest.mark.asyncio
    async def test_start_twice_raises_error(self, skip_without_api_key):
        """Starting an already-started agent should raise error."""
        agent = OrchestrationAgent()
        await agent.start()

        try:
            with pytest.raises(RuntimeError, match="already started"):
                await agent.start()
        finally:
            await agent.stop()


class TestAgentGracefulShutdown:
    """Tests for graceful shutdown behavior."""

    @pytest.mark.asyncio
    async def test_stop_accepts_custom_timeout(self):
        """Stop should accept custom timeout parameter."""
        agent = OrchestrationAgent()
        # Should not raise, even without starting
        await agent.stop(timeout=1.0)

    def test_default_stop_timeout(self):
        """Stop should use 5 second default timeout."""
        # This is documented behavior per CONTEXT.md Decision 1
        # We verify by checking the method signature accepts timeout
        import inspect
        sig = inspect.signature(OrchestrationAgent.stop)
        timeout_param = sig.parameters.get("timeout")
        assert timeout_param is not None
        assert timeout_param.default == 5.0
