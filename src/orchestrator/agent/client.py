"""Orchestration Agent using Claude Agent SDK.

The OrchestrationAgent coordinates multiple MCP servers (Data Source, UPS)
via stdio transport, providing a unified interface for natural language
shipping commands.

Per CONTEXT.md:
- MCPs spawn eagerly at startup
- Session persists for process lifetime
- Graceful shutdown with 5s timeout
"""

import asyncio
import sys
from typing import Any, Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    SdkMcpTool,
    TextBlock,
    create_sdk_mcp_server,
    tool,
)
from claude_agent_sdk.types import McpStdioServerConfig

from src.orchestrator.agent.config import create_mcp_servers_config
from src.orchestrator.agent.hooks import (
    detect_error_response,
    log_post_tool,
    validate_pre_tool,
    validate_shipping_input,
)
from src.orchestrator.agent.tools import get_orchestrator_tools


def _create_orchestrator_mcp_server() -> Any:
    """Create SDK MCP server for orchestrator-native tools.

    Returns an McpSdkServerConfig that can be passed to ClaudeAgentOptions.mcp_servers.
    """
    tools: list[SdkMcpTool[Any]] = []

    for tool_def in get_orchestrator_tools():
        # Create SdkMcpTool from our tool definitions
        sdk_tool = SdkMcpTool(
            name=tool_def["name"],
            description=tool_def["description"],
            input_schema=tool_def["schema"],
            handler=tool_def["function"],
        )
        tools.append(sdk_tool)

    return create_sdk_mcp_server(
        name="orchestrator",
        version="1.0.0",
        tools=tools,
    )


class OrchestrationAgent:
    """Main orchestration agent coordinating MCPs via Claude Agent SDK.

    Manages the lifecycle of Data Source MCP and UPS MCP as child processes,
    routes tool calls through hooks, and maintains conversation context.

    Usage:
        agent = OrchestrationAgent()
        await agent.start()
        try:
            response = await agent.process_command("Import orders.csv")
            print(response)
        finally:
            await agent.stop()

    Or with async context manager:
        async with OrchestrationAgent() as agent:
            response = await agent.process_command("Import orders.csv")
            print(response)
    """

    def __init__(
        self,
        max_turns: int = 50,
        permission_mode: str = "acceptEdits",
    ) -> None:
        """Initialize the Orchestration Agent.

        Args:
            max_turns: Maximum conversation turns before requiring reset.
            permission_mode: SDK permission mode for file operations.
        """
        self._options = self._create_options(max_turns, permission_mode)
        self._client: Optional[ClaudeSDKClient] = None
        self._started = False

    def _create_options(
        self, max_turns: int, permission_mode: str
    ) -> ClaudeAgentOptions:
        """Create ClaudeAgentOptions with MCP servers and hooks."""
        # Get MCP server configs for external servers
        mcp_configs = create_mcp_servers_config()

        # Convert our MCPServerConfig to SDK's McpStdioServerConfig
        data_config: McpStdioServerConfig = {
            "type": "stdio",
            "command": mcp_configs["data"]["command"],
            "args": mcp_configs["data"]["args"],
            "env": mcp_configs["data"]["env"],
        }

        ups_config: McpStdioServerConfig = {
            "type": "stdio",
            "command": mcp_configs["ups"]["command"],
            "args": mcp_configs["ups"]["args"],
            "env": mcp_configs["ups"]["env"],
        }

        # Create orchestrator MCP server for in-process tools
        orchestrator_mcp = _create_orchestrator_mcp_server()

        return ClaudeAgentOptions(
            mcp_servers={
                # In-process orchestrator tools
                "orchestrator": orchestrator_mcp,
                # External MCP servers (stdio child processes)
                "data": data_config,
                "ups": ups_config,
            },
            # Allow all tools from configured MCPs
            allowed_tools=[
                "mcp__orchestrator__*",
                "mcp__data__*",
                "mcp__ups__*",
            ],
            # Hook configuration using HookMatcher dataclass
            hooks={
                "PreToolUse": [
                    HookMatcher(
                        matcher="mcp__ups__shipping",
                        hooks=[validate_shipping_input],
                    ),
                    HookMatcher(
                        matcher=None,  # All tools
                        hooks=[validate_pre_tool],
                    ),
                ],
                "PostToolUse": [
                    HookMatcher(
                        matcher=None,  # All tools
                        hooks=[log_post_tool, detect_error_response],
                    ),
                ],
            },
            # Session settings
            permission_mode=permission_mode,  # type: ignore[arg-type]
            max_turns=max_turns,
        )

    async def start(self) -> None:
        """Start the agent and spawn MCP servers.

        Raises:
            RuntimeError: If agent is already started.
        """
        if self._started:
            raise RuntimeError("Agent already started")

        print("[OrchestrationAgent] Starting...", file=sys.stderr)

        self._client = ClaudeSDKClient(self._options)
        await self._client.connect()

        self._started = True
        print("[OrchestrationAgent] Started successfully", file=sys.stderr)

    async def process_command(self, user_input: str) -> str:
        """Process a user command and return the response.

        The client maintains conversation context across calls.

        Args:
            user_input: Natural language command from the user.

        Returns:
            Agent's text response.

        Raises:
            RuntimeError: If agent not started.
        """
        if not self._started or self._client is None:
            raise RuntimeError("Agent not started. Call start() first.")

        await self._client.query(user_input)

        response_parts: list[str] = []
        async for message in self._client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_parts.append(block.text)
            elif isinstance(message, ResultMessage):
                if message.is_error:
                    response_parts.append(f"[Error: {message.result}]")
                break

        return "".join(response_parts)

    async def stop(self, timeout: float = 5.0) -> None:
        """Stop the agent gracefully.

        Per CONTEXT.md Decision 1: Graceful shutdown with 5s timeout.

        Args:
            timeout: Seconds to wait for graceful shutdown before force kill.
        """
        if not self._started:
            return

        print("[OrchestrationAgent] Stopping...", file=sys.stderr)

        if self._client:
            try:
                await asyncio.wait_for(self._client.disconnect(), timeout=timeout)
            except asyncio.TimeoutError:
                print(
                    f"[OrchestrationAgent] Shutdown timed out after {timeout}s",
                    file=sys.stderr,
                )

        self._started = False
        self._client = None
        print("[OrchestrationAgent] Stopped", file=sys.stderr)

    @property
    def is_started(self) -> bool:
        """Check if the agent is currently running."""
        return self._started

    async def __aenter__(self) -> "OrchestrationAgent":
        """Async context manager entry - start the agent."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Any,
    ) -> None:
        """Async context manager exit - stop the agent."""
        await self.stop()


async def create_agent() -> OrchestrationAgent:
    """Factory function to create and start an OrchestrationAgent.

    Returns:
        Started OrchestrationAgent ready for commands.

    Example:
        agent = await create_agent()
        try:
            response = await agent.process_command("Import orders.csv")
        finally:
            await agent.stop()
    """
    agent = OrchestrationAgent()
    await agent.start()
    return agent


__all__ = [
    "OrchestrationAgent",
    "create_agent",
]
