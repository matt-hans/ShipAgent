"""FastAPI routes for agent-driven SSE conversations.

Replaces the legacy /commands/ endpoint. Each conversation creates
an agent session, accepts user messages, and streams agent events
back via Server-Sent Events.

Endpoints:
    POST   /conversations/              — Create new session
    POST   /conversations/{id}/messages — Send user message
    GET    /conversations/{id}/stream   — SSE event stream
    GET    /conversations/{id}/history  — Get conversation history
    DELETE /conversations/{id}          — End session
"""

import asyncio
import json
import logging
from typing import AsyncGenerator
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response
from sse_starlette.sse import EventSourceResponse

from src.api.schemas_conversations import (
    ConversationHistoryMessage,
    ConversationHistoryResponse,
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
            {k: v for k, v in (o.model_dump() if hasattr(o, "model_dump") else dict(o)).items()
             if k not in exclude_fields}
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


async def _process_agent_message(session_id: str, content: str) -> None:
    """Process a user message through the agent and push events to the queue.

    Runs as a background task. Builds the system prompt with the current
    data source schema, creates/reuses the agent for this session, and
    streams events to the session's event queue.

    Args:
        session_id: Conversation session ID.
        content: User message text.
    """
    queue = _get_event_queue(session_id)

    try:
        # Build system prompt with current data source schema
        from src.orchestrator.agent.system_prompt import build_system_prompt
        from src.services.data_source_service import DataSourceService

        svc = DataSourceService.get_instance()
        source_info = svc.get_source_info()

        # Auto-import Shopify orders if no file/DB source is loaded
        if source_info is None:
            source_info = await _try_auto_import_shopify(svc)

        system_prompt = build_system_prompt(source_info=source_info)

        # Get conversation history
        history = _session_manager.get_history(session_id)

        # Create agent and process message
        from src.orchestrator.agent.client import OrchestrationAgent

        agent = OrchestrationAgent(system_prompt=system_prompt)
        await agent.start()

        try:
            async for event in agent.process_message_stream(
                content, history=history
            ):
                await queue.put(event)

                # If the event is an agent_message, store it in history
                if event.get("event") == "agent_message":
                    text = event.get("data", {}).get("text", "")
                    if text:
                        _session_manager.add_message(
                            session_id, "assistant", text
                        )
        finally:
            await agent.stop()

    except Exception as e:
        logger.error("Agent processing failed for session %s: %s", session_id, e)
        await queue.put({
            "event": "error",
            "data": {"message": str(e)},
        })

    # Signal end of response
    await queue.put({"event": "done", "data": {}})


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
                    "data": json.dumps({
                        "event": event.get("event", "unknown"),
                        "data": event.get("data", {}),
                    }),
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
async def create_conversation() -> CreateConversationResponse:
    """Create a new conversation session.

    Returns:
        CreateConversationResponse with the new session_id.
    """
    session_id = str(uuid4())
    _session_manager.get_or_create_session(session_id)
    logger.info("Created conversation session: %s", session_id)
    return CreateConversationResponse(session_id=session_id)


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

    Idempotent — returns 204 even if session doesn't exist.

    Args:
        session_id: Conversation session ID.

    Returns:
        204 No Content.
    """
    _session_manager.remove_session(session_id)
    _event_queues.pop(session_id, None)
    logger.info("Deleted conversation session: %s", session_id)
    return Response(status_code=204)
