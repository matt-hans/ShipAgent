"""Shared conversation handling service.

Extracts the canonical agent session orchestration from conversations.py
so both HTTP routes and InProcessRunner call the same code path.
"""

import hashlib
import logging
from typing import Any, AsyncIterator

from src.services.agent_session_manager import AgentSession, AgentSessionManager
from src.services.gateway_provider import get_data_gateway

logger = logging.getLogger(__name__)


def compute_source_hash(source_info: Any) -> str:
    """Compute hash of current data source for change detection.

    Args:
        source_info: Data source info from gateway.

    Returns:
        Hash string for comparison.
    """
    if source_info is None:
        return "none"
    raw = str(source_info)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def ensure_agent(
    session: AgentSession,
    source_info: Any,
    interactive_shipping: bool = False,
) -> bool:
    """Ensure the agent exists and is current for the session.

    Creates a new OrchestrationAgent if none exists or if the data source
    has changed. This is the canonical agent creation path.

    Args:
        session: The agent session to ensure.
        source_info: Current data source info.
        interactive_shipping: Whether to create in interactive mode.

    Returns:
        True if a new agent was created, False if reused existing.
    """
    from src.orchestrator.agent.client import OrchestrationAgent
    from src.orchestrator.agent.system_prompt import build_system_prompt

    source_hash = compute_source_hash(source_info)
    combined_hash = f"{source_hash}|interactive={interactive_shipping}"

    # Reuse existing agent if config hasn't changed
    if session.agent is not None and session.agent_source_hash == combined_hash:
        return False

    # Stop existing agent if config changed mid-conversation
    if session.agent is not None:
        try:
            await session.agent.stop()
        except Exception as e:
            logger.warning("Error stopping old agent: %s", e)

    system_prompt = build_system_prompt(
        source_info=source_info,
        interactive_shipping=interactive_shipping,
    )

    agent = OrchestrationAgent(
        system_prompt=system_prompt,
        interactive_shipping=interactive_shipping,
        session_id=session.session_id,
    )
    await agent.start()

    session.agent = agent
    session.agent_source_hash = combined_hash
    session.interactive_shipping = interactive_shipping

    return True


async def process_message(
    session: AgentSession,
    content: str,
    interactive_shipping: bool = False,
    emit_callback: Any | None = None,
) -> AsyncIterator[dict]:
    """Process a user message through the agent, yielding SSE-compatible events.

    This is the canonical message processing path. Both conversations.py
    and InProcessRunner.send_message() call this function.

    IMPORTANT — History Write Ownership:
        The CALLER owns history writes (both user and assistant messages).
        - conversations.py route adds user message before calling this function.
        - InProcessRunner.send_message() adds user message before calling this.
        This function does NOT add user messages — only stores assistant
        response text from agent_message events (see below).

    Args:
        session: The agent session.
        content: User message content.
        interactive_shipping: Whether in interactive mode.
        emit_callback: Optional callback for emitter bridge tool events.

    Yields:
        Event dicts with 'event' and 'data' keys.
    """
    async with session.lock:
        # Get current data source
        try:
            gw = await get_data_gateway()
            source_info = await gw.get_source_info_typed()
        except Exception:
            source_info = None

        # Ensure agent exists (creates + starts if needed)
        await ensure_agent(session, source_info, interactive_shipping)

        # Wire emitter bridge for tool events (preview_ready, etc.)
        if emit_callback:
            session.agent.emitter_bridge.callback = emit_callback

        try:
            async for event in session.agent.process_message_stream(content):
                yield event

                # Store complete text blocks in session history
                if event.get("event") == "agent_message":
                    text = event.get("data", {}).get("text", "")
                    if text:
                        session.add_message("assistant", text)
        finally:
            if emit_callback:
                session.agent.emitter_bridge.callback = None
