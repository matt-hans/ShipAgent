"""FastAPI routes for agent-driven SSE conversations.

Each conversation session has a persistent OrchestrationAgent instance.
The agent and its MCP servers stay alive across messages, leveraging the
Claude SDK's internal conversation memory. Agent is rebuilt only when the
connected data source changes. Sessions are serialized per-conversation
via asyncio.Lock to prevent concurrent access.

Endpoints:
    POST   /conversations/              — Create new session
    POST   /conversations/{id}/messages — Send user message
    GET    /conversations/{id}/stream   — SSE event stream
    GET    /conversations/{id}/history  — Get conversation history
    DELETE /conversations/{id}          — End session (stops agent)
"""

import asyncio
import json
import logging
import os
import time
from typing import AsyncGenerator
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response
from sse_starlette.sse import EventSourceResponse

from src.api.schemas_conversations import (
    ConversationHistoryMessage,
    ConversationHistoryResponse,
    CreateConversationRequest,
    CreateConversationResponse,
    SendMessageRequest,
    SendMessageResponse,
)
from src.services.agent_session_manager import AgentSessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])

# Module-level session manager — shared across all conversation endpoints.
_session_manager = AgentSessionManager()

# Event queues for SSE streaming — one queue per session.
_event_queues: dict[str, asyncio.Queue] = {}


def _get_event_queue(session_id: str) -> asyncio.Queue:
    """Get or create the event queue for a session.

    Args:
        session_id: Conversation session ID.

    Returns:
        The asyncio.Queue for this session's events.
    """
    if session_id not in _event_queues:
        _event_queues[session_id] = asyncio.Queue()
    return _event_queues[session_id]


async def _try_auto_import_shopify(svc: "DataSourceService") -> "DataSourceInfo | None":
    """Auto-import Shopify orders if Shopify is configured and connected.

    Checks environment for Shopify credentials, validates them,
    fetches orders, and imports them into the DataSourceService.

    Args:
        svc: The DataSourceService singleton to import into.

    Returns:
        DataSourceInfo if import succeeded, None otherwise.
    """
    import os

    access_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    store_domain = os.environ.get("SHOPIFY_STORE_DOMAIN")

    if not access_token or not store_domain:
        return None

    try:
        from src.mcp.external_sources.clients.shopify import ShopifyClient
        from src.mcp.external_sources.models import OrderFilters

        client = ShopifyClient()
        credentials = {"access_token": access_token, "store_url": store_domain}
        is_valid = await client.authenticate(credentials)

        if not is_valid:
            logger.warning("Shopify auto-import: authentication failed")
            return None

        # Fetch orders
        filters = OrderFilters(limit=250)
        orders = await client.fetch_orders(filters)

        if not orders:
            logger.info("Shopify auto-import: no orders found")
            return None

        # Convert ExternalOrder objects to flat dicts for DuckDB.
        # Exclude nested fields (items, raw_data) that don't flatten into columns.
        exclude_fields = {"items", "raw_data"}
        records = [
            {
                k: v
                for k, v in (
                    o.model_dump() if hasattr(o, "model_dump") else dict(o)
                ).items()
                if k not in exclude_fields
            }
            for o in orders
        ]

        # Import into DataSourceService
        store_name = store_domain.replace(".myshopify.com", "")
        source_info = svc.import_from_records(
            records,
            source_type="shopify",
            source_label=store_name,
        )

        logger.info(
            "Shopify auto-import: %d orders from %s",
            len(records),
            store_name,
        )
        return source_info

    except Exception as e:
        logger.warning("Shopify auto-import failed (non-critical): %s", e)
        return None


def _compute_source_hash(source_info: "DataSourceInfo | None") -> str:
    """Compute a simple hash of data source metadata for change detection.

    Args:
        source_info: Current data source info, or None.

    Returns:
        Hash string identifying the data source state.
    """
    if source_info is None:
        return "none"
    parts = [
        source_info.source_type,
        str(source_info.file_path or ""),
        str(source_info.row_count),
        ",".join(c.name for c in source_info.columns),
    ]
    return "|".join(parts)


async def _ensure_agent(
    session: "AgentSession",
    source_info: "DataSourceInfo | None",
) -> bool:
    """Ensure the session has a running agent, creating or rebuilding as needed.

    Creates a new agent on first call or when the data source or
    interactive_shipping flag changes. The agent and its MCP servers
    persist across messages for the session lifetime, leveraging the
    SDK's internal conversation memory.

    Args:
        session: The conversation session.
        source_info: Current data source metadata.

    Returns:
        True if a new agent was started/rebuilt, False if existing reused.
    """
    from src.orchestrator.agent.client import OrchestrationAgent
    from src.orchestrator.agent.system_prompt import build_system_prompt

    source_hash = _compute_source_hash(source_info)
    combined_hash = f"{source_hash}|interactive={session.interactive_shipping}"

    # Reuse existing agent if config hasn't changed
    if session.agent is not None and session.agent_source_hash == combined_hash:
        return False

    # Stop old agent if config changed mid-conversation
    if session.agent is not None:
        logger.info(
            "Config changed for session %s, rebuilding agent "
            "(interactive_shipping=%s)",
            session.session_id,
            session.interactive_shipping,
        )
        try:
            await session.agent.stop()
        except Exception as e:
            logger.warning("Error stopping old agent: %s", e)

    system_prompt = build_system_prompt(
        source_info=source_info,
        interactive_shipping=session.interactive_shipping,
    )
    agent = OrchestrationAgent(
        system_prompt=system_prompt,
        interactive_shipping=session.interactive_shipping,
    )
    await agent.start()

    session.agent = agent
    session.agent_source_hash = combined_hash
    logger.info(
        "Agent started for session %s interactive_shipping=%s",
        session.session_id,
        session.interactive_shipping,
    )
    return True


async def _prewarm_session_agent(session_id: str) -> None:
    """Best-effort prewarm for session agent startup.

    Runs in background after conversation creation when a source is already
    connected. Never raises; first message path remains authoritative.
    """
    from src.services.data_source_service import DataSourceService

    session = _session_manager.get_or_create_session(session_id)
    try:
        async with session.lock:
            svc = DataSourceService.get_instance()
            source_info = svc.get_source_info()
            if source_info is None:
                return
            rebuilt = await _ensure_agent(session, source_info)
            logger.info(
                "Agent prewarm complete: session_id=%s rebuilt=%s source_type=%s",
                session_id,
                rebuilt,
                source_info.source_type,
            )
    except asyncio.CancelledError:
        logger.info("Agent prewarm cancelled for session %s", session_id)
        raise
    except Exception as e:
        logger.warning("Agent prewarm failed for session %s: %s", session_id, e)


async def _process_agent_message(session_id: str, content: str) -> None:
    """Process a user message through the persistent agent.

    Runs as a background task. Reuses the session's agent (SDK maintains
    conversation history internally). The agent and MCP servers stay alive
    across messages. An asyncio.Lock serializes access per session.

    Args:
        session_id: Conversation session ID.
        content: User message text.
    """
    queue = _get_event_queue(session_id)
    session = _session_manager.get_or_create_session(session_id)
    started_at = time.perf_counter()
    first_event_at: float | None = None
    first_event_source = ""
    preview_rows_rated = 0
    preview_total_rows = 0
    auto_import_used = False
    source_type = "none"
    agent_rebuilt = False

    logger.info(
        "agent_timing marker=message_received session_id=%s content_len=%d elapsed=%.3f",
        session_id,
        len(content),
        0.0,
    )

    def _mark_first_event(source: str) -> None:
        nonlocal first_event_at, first_event_source
        if first_event_at is None:
            first_event_at = time.perf_counter()
            first_event_source = source
            logger.info(
                "agent_timing marker=first_event session_id=%s source=%s elapsed=%.3f",
                session_id,
                source,
                first_event_at - started_at,
            )

    async with session.lock:
        try:
            from src.services.data_source_service import DataSourceService

            svc = DataSourceService.get_instance()
            source_info = svc.get_source_info()

            # Auto-import Shopify orders if no file/DB source is loaded.
            if source_info is None:
                source_info = await _try_auto_import_shopify(svc)
                auto_import_used = source_info is not None

            source_type = source_info.source_type if source_info is not None else "none"
            logger.info(
                "agent_timing marker=source_resolved session_id=%s source_type=%s "
                "auto_import_used=%s elapsed=%.3f",
                session_id,
                source_type,
                auto_import_used,
                time.perf_counter() - started_at,
            )

            # Create or reuse agent (persists across messages)
            agent_rebuilt = await _ensure_agent(session, source_info)
            logger.info(
                "agent_timing marker=agent_ready session_id=%s agent_rebuilt=%s elapsed=%.3f",
                session_id,
                agent_rebuilt,
                time.perf_counter() - started_at,
            )

            # Bridge tool events to the SSE queue.
            def _emit_to_queue(event_type: str, data: dict) -> None:
                _mark_first_event("tool_emit")
                queue.put_nowait({"event": event_type, "data": data})

            session.agent.emitter_bridge.callback = _emit_to_queue
            try:
                # Process message — SDK maintains conversation context internally.
                async for event in session.agent.process_message_stream(content):
                    _mark_first_event(str(event.get("event", "unknown")))
                    await queue.put(event)

                    event_type = event.get("event")
                    if event_type == "preview_ready":
                        preview_data = event.get("data", {})
                        preview_total_rows = int(preview_data.get("total_rows", 0))
                        preview_rows_rated = len(preview_data.get("preview_rows", []))

                    # Store complete text blocks in session history.
                    if event_type == "agent_message":
                        text = event.get("data", {}).get("text", "")
                        if text:
                            _session_manager.add_message(
                                session_id,
                                "assistant",
                                text,
                            )
            finally:
                session.agent.emitter_bridge.callback = None

        except Exception as e:
            logger.error("Agent processing failed for session %s: %s", session_id, e)
            _mark_first_event("error")
            await queue.put(
                {
                    "event": "error",
                    "data": {"message": str(e)},
                }
            )

    # Signal end of response
    await queue.put({"event": "done", "data": {}})

    elapsed = time.perf_counter() - started_at
    ttfb = (first_event_at - started_at) if first_event_at is not None else -1.0
    agent_turns_count = (
        int(getattr(session.agent, "last_turn_count", 0))
        if session.agent is not None
        else 0
    )
    logger.info(
        "agent_timing marker=done_emitted session_id=%s source_type=%s "
        "auto_import_used=%s agent_rebuilt=%s agent_turns_count=%d "
        "preview_rows_rated=%d preview_total_rows=%d batch_concurrency=%s "
        "interactive_shipping=%s first_event_source=%s ttfb=%.3f elapsed=%.3f",
        session_id,
        source_type,
        auto_import_used,
        agent_rebuilt,
        agent_turns_count,
        preview_rows_rated,
        preview_total_rows,
        os.environ.get("BATCH_CONCURRENCY", "5"),
        session.interactive_shipping,
        first_event_source,
        ttfb,
        elapsed,
    )


async def _event_generator(
    request: Request,
    session_id: str,
    queue: asyncio.Queue,
) -> AsyncGenerator[dict, None]:
    """Generate SSE events from the session's event queue.

    Args:
        request: FastAPI request for disconnect detection.
        session_id: Conversation session ID.
        queue: Async queue receiving agent events.

    Yields:
        SSE event dictionaries.
    """
    try:
        while True:
            if await request.is_disconnected():
                break

            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)

                # Check for end signal
                if event.get("event") == "done":
                    yield {
                        "data": json.dumps({"event": "done", "data": {}}),
                    }
                    break

                yield {
                    "data": json.dumps(
                        {
                            "event": event.get("event", "unknown"),
                            "data": event.get("data", {}),
                        }
                    ),
                }
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                yield {
                    "data": json.dumps({"event": "ping"}),
                }
    finally:
        # Clean up the queue reference if session was deleted
        pass


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=CreateConversationResponse, status_code=201)
async def create_conversation(
    payload: CreateConversationRequest | None = None,
) -> CreateConversationResponse:
    """Create a new conversation session.

    Args:
        payload: Optional request body. Defaults to interactive_shipping=False.
            Existing no-body POST clients continue to work (backward-compatible).

    Returns:
        CreateConversationResponse with session_id and effective mode.
    """
    from src.services.data_source_service import DataSourceService

    effective_payload = payload or CreateConversationRequest()

    session_id = str(uuid4())
    session = _session_manager.get_or_create_session(session_id)
    session.interactive_shipping = effective_payload.interactive_shipping

    # Best-effort prewarm when a source already exists; do not block response.
    try:
        source_info = DataSourceService.get_instance().get_source_info()
        if source_info is not None:
            session.prewarm_task = asyncio.create_task(
                _prewarm_session_agent(session_id)
            )
    except Exception as e:
        logger.warning("Failed to schedule agent prewarm for %s: %s", session_id, e)

    logger.info(
        "Created conversation session: %s interactive_shipping=%s",
        session_id,
        session.interactive_shipping,
    )
    return CreateConversationResponse(
        session_id=session_id,
        interactive_shipping=session.interactive_shipping,
    )


@router.post("/{session_id}/messages", status_code=202)
async def send_message(
    session_id: str,
    payload: SendMessageRequest,
    background_tasks: BackgroundTasks,
) -> SendMessageResponse:
    """Send a user message to the conversation agent.

    The message is processed asynchronously. Events are streamed
    via the /stream endpoint.

    Args:
        session_id: Conversation session ID.
        payload: User message request body.
        background_tasks: FastAPI background task manager.

    Returns:
        SendMessageResponse confirming acceptance.

    Raises:
        HTTPException: 404 if session not found.
    """
    if session_id not in _session_manager.list_sessions():
        raise HTTPException(status_code=404, detail="Session not found")

    # Store user message in history
    _session_manager.add_message(session_id, "user", payload.content)

    # Process via agent in background
    background_tasks.add_task(_process_agent_message, session_id, payload.content)

    return SendMessageResponse(status="accepted", session_id=session_id)


@router.get("/{session_id}/stream")
async def stream_events(request: Request, session_id: str) -> EventSourceResponse:
    """SSE stream of agent events for this conversation.

    Connect to this endpoint after sending a message to receive
    real-time agent events (thinking, tool calls, messages, etc.).

    Args:
        request: FastAPI request for disconnect detection.
        session_id: Conversation session ID.

    Returns:
        EventSourceResponse streaming agent events.

    Raises:
        HTTPException: 404 if session not found.
    """
    if session_id not in _session_manager.list_sessions():
        raise HTTPException(status_code=404, detail="Session not found")

    queue = _get_event_queue(session_id)

    return EventSourceResponse(
        _event_generator(request, session_id, queue),
        media_type="text/event-stream",
    )


@router.get("/{session_id}/history")
async def get_history(session_id: str) -> ConversationHistoryResponse:
    """Get the conversation history for a session.

    Args:
        session_id: Conversation session ID.

    Returns:
        ConversationHistoryResponse with ordered messages.

    Raises:
        HTTPException: 404 if session not found.
    """
    if session_id not in _session_manager.list_sessions():
        raise HTTPException(status_code=404, detail="Session not found")

    raw_history = _session_manager.get_history(session_id)
    messages = [
        ConversationHistoryMessage(
            role=m["role"],
            content=m["content"],
            timestamp=m.get("timestamp", ""),
        )
        for m in raw_history
    ]

    return ConversationHistoryResponse(session_id=session_id, messages=messages)


@router.delete("/{session_id}", status_code=204)
async def delete_conversation(session_id: str) -> Response:
    """End a conversation session and free resources.

    Stops the persistent agent (and its MCP servers), removes session
    state, and cleans up the event queue. Idempotent — returns 204
    even if session doesn't exist.

    Args:
        session_id: Conversation session ID.

    Returns:
        204 No Content.
    """
    # Stop prewarm and agent before removing session
    await _session_manager.cancel_session_prewarm_task(session_id)
    await _session_manager.stop_session_agent(session_id)
    _session_manager.remove_session(session_id)
    _event_queues.pop(session_id, None)
    logger.info("Deleted conversation session: %s", session_id)
    return Response(status_code=204)
