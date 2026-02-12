"""Orchestration Agent using Claude Agent SDK.

The OrchestrationAgent coordinates MCP servers (Data Source, External Sources,
UPS) via stdio transport, providing a unified interface for natural language
shipping commands.

Hybrid UPS architecture:
- Interactive path: Agent calls UPS MCP tools directly (rate_shipment,
  validate_address, track_package, create_shipment, void_shipment,
  recover_label, get_time_in_transit)
- Batch path: BatchEngine uses UPSService (direct Python import of ups-mcp
  ToolManager) for deterministic high-volume execution with per-row state
  tracking and crash recovery

Per CONTEXT.md:
- MCPs spawn eagerly at startup
- Session persists for process lifetime
- Graceful shutdown with 5s timeout

Enhanced with:
- system_prompt parameter for unified domain knowledge injection
- tools_v2 deterministic tools replacing legacy tools
- process_message() with conversation history support
- process_message_stream() async generator for SSE event streaming
"""

import asyncio
import logging
import sys
from collections.abc import AsyncGenerator
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
    validate_void_shipment,
)
from src.orchestrator.agent.tools_v2 import get_all_tool_definitions

logger = logging.getLogger(__name__)


def _create_orchestrator_mcp_server() -> Any:
    """Create SDK MCP server for orchestrator-native tools.

    Uses tools_v2 deterministic-only tools. Legacy tools (tools.py)
    are fully deprecated and not registered.

    Returns:
        McpSdkServerConfig for ClaudeAgentOptions.mcp_servers.
    """
    tools: list[SdkMcpTool[Any]] = []

    for tool_def in get_all_tool_definitions():
        sdk_tool = SdkMcpTool(
            name=tool_def["name"],
            description=tool_def["description"],
            input_schema=tool_def["input_schema"],
            handler=tool_def["handler"],
        )
        tools.append(sdk_tool)

    return create_sdk_mcp_server(
        name="orchestrator",
        version="2.0.0",
        tools=tools,
    )


class OrchestrationAgent:
    """Main orchestration agent coordinating MCPs via Claude Agent SDK.

    Manages the lifecycle of Data Source, External Sources, and UPS MCPs as
    child processes, routes tool calls through hooks, and maintains conversation
    context. The agent has direct access to all 7 UPS MCP tools for interactive
    operations. BatchEngine uses UPSService separately for deterministic batch
    execution.

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
        system_prompt: str | None = None,
        max_turns: int = 50,
        permission_mode: str = "acceptEdits",
    ) -> None:
        """Initialize the Orchestration Agent.

        Args:
            system_prompt: System prompt with domain knowledge. None for default.
            max_turns: Maximum conversation turns before requiring reset.
            permission_mode: SDK permission mode for file operations.
        """
        self._system_prompt = system_prompt
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

        # External Sources Gateway MCP config
        external_config: McpStdioServerConfig = {
            "type": "stdio",
            "command": mcp_configs["external"]["command"],
            "args": mcp_configs["external"]["args"],
            "env": mcp_configs["external"]["env"],
        }

        # UPS MCP config (stdio via uvx)
        ups_config: McpStdioServerConfig = {
            "type": "stdio",
            "command": mcp_configs["ups"]["command"],
            "args": mcp_configs["ups"]["args"],
            "env": mcp_configs["ups"]["env"],
        }

        # Create orchestrator MCP server for in-process tools
        orchestrator_mcp = _create_orchestrator_mcp_server()

        return ClaudeAgentOptions(
            system_prompt=self._system_prompt,
            mcp_servers={
                # In-process orchestrator tools
                "orchestrator": orchestrator_mcp,
                # External MCP servers (stdio child processes)
                "data": data_config,
                "external": external_config,
                "ups": ups_config,
            },
            # Allow all tools from configured MCPs
            allowed_tools=[
                "mcp__orchestrator__*",
                "mcp__data__*",
                "mcp__external__*",
                "mcp__ups__*",
            ],
            # Hook configuration using HookMatcher dataclass
            hooks={
                "PreToolUse": [
                    HookMatcher(
                        matcher="mcp__ups__create_shipment",
                        hooks=[validate_shipping_input],
                    ),
                    HookMatcher(
                        matcher="mcp__ups__void_shipment",
                        hooks=[validate_void_shipment],
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

    async def process_message(
        self, user_input: str, history: list[dict] | None = None
    ) -> str:
        """Process a user message with optional conversation history.

        Similar to process_command but accepts prior conversation context.

        Args:
            user_input: Natural language message from the user.
            history: Optional list of prior messages [{role, content}].

        Returns:
            Agent's text response.

        Raises:
            RuntimeError: If agent not started.
        """
        if not self._started or self._client is None:
            raise RuntimeError("Agent not started. Call start() first.")

        # If history is provided, replay it before sending the new message
        # The SDK client maintains internal state, so we send the full context
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

    async def process_message_stream(
        self, user_input: str, history: list[dict] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Process a user message and yield SSE-compatible event dicts.

        Streams agent events as they occur for real-time UI updates.

        Args:
            user_input: Natural language message from the user.
            history: Optional list of prior messages [{role, content}].

        Yields:
            Event dicts: {"event": "agent_thinking"|"tool_call"|"tool_result"|"agent_message"|"error", "data": {...}}

        Raises:
            RuntimeError: If agent not started.
        """
        if not self._started or self._client is None:
            raise RuntimeError("Agent not started. Call start() first.")

        try:
            await self._client.query(user_input)

            async for message in self._client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            yield {
                                "event": "agent_message",
                                "data": {"text": block.text},
                            }
                        elif hasattr(block, "name"):
                            # Tool use block
                            yield {
                                "event": "tool_call",
                                "data": {
                                    "tool_name": getattr(block, "name", "unknown"),
                                    "tool_input": getattr(block, "input", {}),
                                },
                            }
                elif isinstance(message, ResultMessage):
                    if message.is_error:
                        yield {
                            "event": "error",
                            "data": {"message": str(message.result)},
                        }
                    break
        except Exception as e:
            logger.error("process_message_stream error: %s", e)
            yield {
                "event": "error",
                "data": {"message": str(e)},
            }

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
