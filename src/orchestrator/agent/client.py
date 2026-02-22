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
import time
from collections.abc import AsyncGenerator
from typing import Any

try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        SdkMcpTool,
        TextBlock,
        ToolUseBlock,
        create_sdk_mcp_server,
    )
    from claude_agent_sdk.types import McpStdioServerConfig, StreamEvent
except ModuleNotFoundError as exc:
    if exc.name != "claude_agent_sdk":
        raise
    raise ModuleNotFoundError(
        "No module named 'claude_agent_sdk'. "
        "Start backend with ./scripts/start-backend.sh (project .venv), "
        "or install deps via .venv/bin/python -m pip install -e '.[dev]'."
    ) from exc

from src.orchestrator.agent.config import create_mcp_servers_config
from src.orchestrator.agent.hooks import create_hook_matchers
from src.orchestrator.agent.tools import get_all_tool_definitions
from src.orchestrator.agent.tools.core import EventEmitterBridge
from src.services.decision_audit_service import DecisionAuditService

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
_HAS_STREAM_EVENT = True


def _create_orchestrator_mcp_server(
    event_bridge: EventEmitterBridge,
    interactive_shipping: bool = False,
) -> Any:
    """Create SDK MCP server for orchestrator-native tools.

    Uses deterministic tools from the tools/ package (core, data, pipeline,
    interactive). All tools are registered via get_all_tool_definitions().

    Returns:
        McpSdkServerConfig for ClaudeAgentOptions.mcp_servers.
    """
    tools: list[SdkMcpTool[Any]] = []

    for tool_def in get_all_tool_definitions(
        event_bridge=event_bridge,
        interactive_shipping=interactive_shipping,
    ):
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
        interactive_shipping: bool = False,
        session_id: str | None = None,
    ) -> None:
        """Initialize the Orchestration Agent.

        Args:
            system_prompt: System prompt with domain knowledge. None for default.
            max_turns: Maximum conversation turns before requiring reset.
            permission_mode: SDK permission mode for file operations.
            model: Claude model ID. Defaults to AGENT_MODEL (or legacy
                ANTHROPIC_MODEL) env var, else Haiku 4.5.
            interactive_shipping: Whether interactive single-shipment mode is
                enabled. Passed to hook factory for deterministic enforcement.
            session_id: Conversation session ID. Passed to emitter bridge so
                tool handlers can look up session-scoped attachment data.
        """
        self._system_prompt = system_prompt
        self._model = model or DEFAULT_MODEL
        self._interactive_shipping = interactive_shipping
        self.emitter_bridge = EventEmitterBridge()
        self.emitter_bridge.session_id = session_id
        self._options = self._create_options(max_turns, permission_mode)
        self._client: ClaudeSDKClient | None = None
        self._started = False
        self._start_time: float | None = None
        self._last_turn_count = 0

    def _create_options(
        self, max_turns: int, permission_mode: str
    ) -> ClaudeAgentOptions:
        """Create ClaudeAgentOptions with MCP servers, hooks, and streaming."""
        # Resolve UPS credentials via runtime adapter (DB priority, env fallback)
        from src.services.runtime_credentials import resolve_ups_credentials

        ups_creds = resolve_ups_credentials()
        if ups_creds:
            logger.info("Agent session using UPS environment=%s", ups_creds.environment)

        # Get MCP server configs (UPS key omitted if no credentials)
        mcp_configs = create_mcp_servers_config(ups_credentials=ups_creds)

        # Create orchestrator MCP server for in-process tools
        orchestrator_mcp = _create_orchestrator_mcp_server(
            self.emitter_bridge,
            interactive_shipping=self._interactive_shipping,
        )

        mcp_servers: dict[str, McpStdioServerConfig | Any] = {
            # In-process orchestrator tools (deterministic, no LLM calls)
            "orchestrator": orchestrator_mcp,
            # NOTE: "external" and "data" MCP servers removed from agent.
            # Data source access routes through DataSourceMCPClient singleton
            # in gateway_provider. Agent tools call the gateway directly.
        }

        allowed_tools = [
            "mcp__orchestrator__*",
        ]

        # Only add UPS MCP if credentials are available
        if "ups" in mcp_configs:
            ups_config: McpStdioServerConfig = {
                "type": "stdio",
                "command": mcp_configs["ups"]["command"],
                "args": mcp_configs["ups"]["args"],
                "env": mcp_configs["ups"]["env"],
            }
            mcp_servers["ups"] = ups_config
            allowed_tools.append("mcp__ups__*")
        else:
            logger.warning(
                "UPS MCP not configured — agent will start without UPS tools. "
                "Connect UPS in Settings to enable shipping operations."
            )

        return ClaudeAgentOptions(
            system_prompt=self._system_prompt,
            model=self._model,
            mcp_servers=mcp_servers,
            # Disable all built-in Claude Code tools — we only use MCP tools
            tools=[],
            # Allow all MCP tools without permission prompts
            allowed_tools=allowed_tools,
            hooks=create_hook_matchers(
                interactive_shipping=self._interactive_shipping,
            ),
            # Enable real-time token streaming via StreamEvent
            include_partial_messages=True,
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
            elapsed = time.monotonic() - self._start_time if self._start_time else 0
            raise RuntimeError(
                f"Agent already started (model={self._model}, "
                f"interactive={self._interactive_shipping}, "
                f"uptime={elapsed:.1f}s)"
            )

        logger.info("[OrchestrationAgent] Starting...")

        self._client = ClaudeSDKClient(self._options)
        await self._client.connect()

        self._started = True
        self._start_time = time.monotonic()
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
        self,
        user_input: str,
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
            text_chunk_count = 0
            text_chunk_chars = 0
            DecisionAuditService.log_event_from_context(
                phase="ingress",
                event_name="agent.query.dispatched",
                actor="agent",
                payload={
                    "input_length": len(user_input),
                    "model": self._model,
                    "interactive_shipping": self._interactive_shipping,
                },
            )

            # Track whether we received StreamEvents for text (to avoid
            # duplicate emission from AssistantMessage TextBlocks)
            streamed_text_in_turn = False
            emitted_tool_ids: set[str] = set()
            current_text_parts: list[str] = []

            async for message in self._client.receive_response():
                # --- StreamEvent: real-time deltas (include_partial_messages) ---
                if isinstance(message, StreamEvent):
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
                                text_chunk_count += 1
                                text_chunk_chars += len(text)
                                if text_chunk_count % 20 == 0:
                                    DecisionAuditService.log_event_from_context(
                                        phase="egress",
                                        event_name="agent.text_chunk.batch",
                                        actor="agent",
                                        payload={
                                            "chunks_seen": text_chunk_count,
                                            "chars_seen": text_chunk_chars,
                                        },
                                    )
                                yield {
                                    "event": "agent_message_delta",
                                    "data": {"text": text},
                                }

                    elif event_type == "content_block_stop":
                        # Emit complete text block for history storage
                        if current_text_parts:
                            full_text = "".join(current_text_parts)
                            DecisionAuditService.log_event_from_context(
                                phase="egress",
                                event_name="agent.text_block.completed",
                                actor="agent",
                                payload={
                                    "block_chars": len(full_text),
                                    "chunks_seen": text_chunk_count,
                                },
                            )
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
                            DecisionAuditService.log_event_from_context(
                                phase="tool_call",
                                event_name="agent.tool_call.observed",
                                actor="agent",
                                tool_name=str(block.name),
                                payload={
                                    "tool_input_type": type(block.input).__name__,
                                },
                            )
                        elif isinstance(block, TextBlock):
                            # Only emit if we didn't stream this text
                            if not streamed_text_in_turn:
                                DecisionAuditService.log_event_from_context(
                                    phase="egress",
                                    event_name="agent.text_block.completed",
                                    actor="agent",
                                    payload={"block_chars": len(block.text)},
                                )
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
                        DecisionAuditService.log_event_from_context(
                            phase="error",
                            event_name="agent.result.error",
                            actor="agent",
                            payload={"message": str(message.result)},
                        )
                        yield {
                            "event": "error",
                            "data": {"message": str(message.result)},
                        }
                    else:
                        DecisionAuditService.log_event_from_context(
                            phase="egress",
                            event_name="agent.result.completed",
                            actor="agent",
                            payload={
                                "assistant_turn_count": assistant_turn_count,
                                "streamed_chunks": text_chunk_count,
                                "streamed_chars": text_chunk_chars,
                            },
                        )
                    break

            self._last_turn_count = assistant_turn_count

        except Exception as e:
            self._last_turn_count = 0
            logger.error("process_message_stream error", exc_info=True)
            DecisionAuditService.log_event_from_context(
                phase="error",
                event_name="agent.stream.exception",
                actor="agent",
                payload={"error": str(e)},
            )
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
            except TimeoutError:
                logger.warning(
                    "[OrchestrationAgent] Shutdown timed out after %ss",
                    timeout,
                )

        self._started = False
        self._start_time = None
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
        exc_type: type | None,
        exc_val: BaseException | None,
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
