"""Orchestration Agent using Claude Agent SDK.

The OrchestrationAgent coordinates MCP servers (Data Source, External Sources,
UPS) via stdio transport, providing a unified interface for natural language
shipping commands.

Hybrid UPS architecture:
- Interactive path: Agent calls UPS MCP tools directly (rate_shipment,
  validate_address, track_package, create_shipment, void_shipment,
  recover_label, get_time_in_transit)
- Batch path: BatchEngine uses UPSMCPClient (programmatic MCP over stdio)
  for deterministic high-volume execution with per-row state tracking

SDK features leveraged:
- include_partial_messages: Real-time StreamEvent token streaming
- Persistent sessions: Agent stays alive across messages, SDK maintains
  internal conversation history
- Hooks: PreToolUse/PostToolUse for validation and logging
- Interrupt: Graceful cancellation of in-progress responses

Per CONTEXT.md:
- MCPs spawn eagerly at startup
- Session persists for process lifetime
- Graceful shutdown with 5s timeout
"""

import asyncio
import logging
import os
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
    ToolUseBlock,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import McpStdioServerConfig

# StreamEvent is available when include_partial_messages=True
try:
    from claude_agent_sdk.types import StreamEvent

    _HAS_STREAM_EVENT = True
except ImportError:
    _HAS_STREAM_EVENT = False

from src.orchestrator.agent.config import create_mcp_servers_config
from src.orchestrator.agent.hooks import create_hook_matchers
from src.orchestrator.agent.tools_v2 import get_all_tool_definitions

# Default model resolution:
# 1) AGENT_MODEL (preferred)
# 2) ANTHROPIC_MODEL (backward compatibility)
# 3) Claude Haiku 4.5 (cost-optimized default)
DEFAULT_MODEL = (
    os.environ.get("AGENT_MODEL")
    or os.environ.get("ANTHROPIC_MODEL")
    or "claude-haiku-4-5-20251001"
)

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
        model: str | None = None,
    ) -> None:
        """Initialize the Orchestration Agent.

        Args:
            system_prompt: System prompt with domain knowledge. None for default.
            max_turns: Maximum conversation turns before requiring reset.
            permission_mode: SDK permission mode for file operations.
            model: Claude model ID. Defaults to AGENT_MODEL (or legacy
                ANTHROPIC_MODEL) env var, else Haiku 4.5.
        """
        self._system_prompt = system_prompt
        self._model = model or DEFAULT_MODEL
        self._options = self._create_options(max_turns, permission_mode)
        self._client: Optional[ClaudeSDKClient] = None
        self._started = False
        self._last_turn_count = 0

    def _create_options(
        self, max_turns: int, permission_mode: str
    ) -> ClaudeAgentOptions:
        """Create ClaudeAgentOptions with MCP servers, hooks, and streaming."""
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

        # UPS MCP config (stdio via venv python)
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
            model=self._model,
            mcp_servers={
                # In-process orchestrator tools (deterministic, no LLM calls)
                "orchestrator": orchestrator_mcp,
                # External MCP servers (stdio child processes)
                "data": data_config,
                "external": external_config,
                "ups": ups_config,
            },
            # Disable all built-in Claude Code tools — we only use MCP tools
            tools=[],
            # Allow all MCP tools without permission prompts
            allowed_tools=[
                "mcp__orchestrator__*",
                "mcp__data__*",
                "mcp__external__*",
                "mcp__ups__*",
            ],
            hooks=create_hook_matchers(),
            # Enable real-time token streaming via StreamEvent
            include_partial_messages=_HAS_STREAM_EVENT,
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

        logger.info("[OrchestrationAgent] Starting...")

        self._client = ClaudeSDKClient(self._options)
        await self._client.connect()

        self._started = True
        logger.info("[OrchestrationAgent] Started successfully")

    async def process_command(self, user_input: str) -> str:
        """Process a user command and return the complete response.

        The SDK client maintains conversation context across calls — no need
        to pass history. Each call builds on previous context.

        Args:
            user_input: Natural language command from the user.

        Returns:
            Agent's complete text response.

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

    async def process_message_stream(
        self, user_input: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Process a user message and yield SSE-compatible event dicts.

        Streams agent events as they occur for real-time UI updates.
        When include_partial_messages is enabled (StreamEvent available),
        emits token-by-token text deltas and real-time tool call notifications.

        The SDK client maintains conversation context internally — no need
        to pass history. Each call builds on previous context.

        Yields:
            Event dicts with these event types:
            - "agent_message_delta": Partial text chunk (real-time streaming)
            - "agent_message": Complete text block (for history storage)
            - "tool_call": Tool invocation starting
            - "tool_result": Tool execution result
            - "error": Error occurred

        Raises:
            RuntimeError: If agent not started.
        """
        if not self._started or self._client is None:
            raise RuntimeError("Agent not started. Call start() first.")

        try:
            await self._client.query(user_input)
            assistant_turn_count = 0

            # Track whether we received StreamEvents for text (to avoid
            # duplicate emission from AssistantMessage TextBlocks)
            streamed_text_in_turn = False
            emitted_tool_ids: set[str] = set()
            current_text_parts: list[str] = []

            async for message in self._client.receive_response():
                # --- StreamEvent: real-time deltas (include_partial_messages) ---
                if _HAS_STREAM_EVENT and isinstance(message, StreamEvent):
                    event = message.event
                    event_type = event.get("type")

                    if event_type == "content_block_start":
                        cb = event.get("content_block", {})
                        if cb.get("type") == "tool_use":
                            tool_id = cb.get("id")
                            if not tool_id:
                                # Without a stable ID, skip StreamEvent emission.
                                # AssistantMessage emits the canonical tool call.
                                continue
                            emitted_tool_ids.add(tool_id)
                            yield {
                                "event": "tool_call",
                                "data": {
                                    "tool_name": cb.get("name", "unknown"),
                                    "tool_input": cb.get("input", {}),
                                },
                            }
                        elif cb.get("type") == "text":
                            current_text_parts = []

                    elif event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                streamed_text_in_turn = True
                                current_text_parts.append(text)
                                yield {
                                    "event": "agent_message_delta",
                                    "data": {"text": text},
                                }

                    elif event_type == "content_block_stop":
                        # Emit complete text block for history storage
                        if current_text_parts:
                            full_text = "".join(current_text_parts)
                            yield {
                                "event": "agent_message",
                                "data": {"text": full_text},
                            }
                            current_text_parts = []

                # --- AssistantMessage: complete turn ---
                elif isinstance(message, AssistantMessage):
                    assistant_turn_count += 1
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            block_id = getattr(block, "id", None)
                            if block_id:
                                if block_id in emitted_tool_ids:
                                    continue
                                emitted_tool_ids.add(block_id)
                            yield {
                                "event": "tool_call",
                                "data": {
                                    "tool_name": block.name,
                                    "tool_input": block.input,
                                },
                            }
                        elif isinstance(block, TextBlock):
                            # Only emit if we didn't stream this text
                            if not streamed_text_in_turn:
                                yield {
                                    "event": "agent_message",
                                    "data": {"text": block.text},
                                }
                    # Reset per-turn tracking
                    streamed_text_in_turn = False
                    emitted_tool_ids.clear()

                # --- ResultMessage: agent finished ---
                elif isinstance(message, ResultMessage):
                    if message.is_error:
                        yield {
                            "event": "error",
                            "data": {"message": str(message.result)},
                        }
                    break

            self._last_turn_count = assistant_turn_count

        except Exception as e:
            self._last_turn_count = 0
            logger.error("process_message_stream error: %s", e)
            yield {
                "event": "error",
                "data": {"message": str(e)},
            }

    async def interrupt(self) -> None:
        """Interrupt the agent's current response.

        Cancels in-progress tool calls and LLM generation. The agent
        can accept new messages after interruption.

        No-op if agent is not started or no response is in progress.
        """
        if self._client is not None:
            try:
                await self._client.interrupt()
            except Exception as e:
                logger.warning("Agent interrupt failed: %s", e)

    async def stop(self, timeout: float = 5.0) -> None:
        """Stop the agent gracefully.

        Per CONTEXT.md Decision 1: Graceful shutdown with 5s timeout.

        Args:
            timeout: Seconds to wait for graceful shutdown before force kill.
        """
        if not self._started:
            return

        logger.info("[OrchestrationAgent] Stopping...")

        if self._client:
            try:
                await asyncio.wait_for(self._client.disconnect(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "[OrchestrationAgent] Shutdown timed out after %ss",
                    timeout,
                )

        self._started = False
        self._client = None
        logger.info("[OrchestrationAgent] Stopped")

    @property
    def is_started(self) -> bool:
        """Check if the agent is currently running."""
        return self._started

    @property
    def last_turn_count(self) -> int:
        """Assistant turn count from the most recent streamed request."""
        return self._last_turn_count

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
