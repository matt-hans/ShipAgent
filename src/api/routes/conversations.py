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
import base64
import json
import logging
import os
import time
from typing import AsyncGenerator
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sse_starlette.sse import EventSourceResponse

from src.api.schemas_conversations import (
    DOCUMENT_TYPE_LABELS,
    ConversationHistoryMessage,
    ConversationHistoryResponse,
    CreateConversationRequest,
    CreateConversationResponse,
    SendMessageRequest,
    SendMessageResponse,
    UploadDocumentResponse,
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
        session_id=session.session_id,
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
    from src.services.gateway_provider import get_data_gateway

    session = _session_manager.get_or_create_session(session_id)
    try:
        async with session.lock:
            gw = await get_data_gateway()
            source_info = await gw.get_source_info_typed()
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
    """Process a user message — delegates to shared conversation_handler.

    Runs as a background task. Retains route-specific concerns:
    queue delivery, timing metrics, preview metrics, done signaling.

    Args:
        session_id: Conversation session ID.
        content: User message text.
    """
    queue = _get_event_queue(session_id)
    session = _session_manager.get_or_create_session(session_id)

    if session.terminating:
        logger.info("Skipping message for terminating session %s", session_id)
        await queue.put({"event": "done", "data": {}})
        return

    started_at = time.perf_counter()
    first_event_at: float | None = None
    first_event_source = ""
    preview_rows_rated = 0
    preview_total_rows = 0

    def _mark_first_event(source: str) -> None:
        nonlocal first_event_at, first_event_source
        if first_event_at is None:
            first_event_at = time.perf_counter()
            first_event_source = source

    # Queue-pushing callback for tool events (preview_ready, etc.)
    def _emit_to_queue(event_type: str, data: dict) -> None:
        _mark_first_event("tool_emit")
        queue.put_nowait({"event": event_type, "data": data})

    try:
        from src.services.conversation_handler import process_message

        async for event in process_message(
            session, content,
            interactive_shipping=session.interactive_shipping,
            emit_callback=_emit_to_queue,
        ):
            _mark_first_event(str(event.get("event", "unknown")))
            await queue.put(event)

            # Capture preview metrics for timing log
            event_type = event.get("event")
            if event_type == "preview_ready":
                pd = event.get("data", {})
                preview_total_rows = int(pd.get("total_rows", 0))
                preview_rows_rated = len(pd.get("preview_rows", []))

    except Exception as e:
        logger.error("Agent processing failed for session %s: %s", session_id, e)
        _mark_first_event("error")
        await queue.put({"event": "error", "data": {"message": str(e)}})

    # Signal end of response
    await queue.put({"event": "done", "data": {}})

    # Timing log
    elapsed = time.perf_counter() - started_at
    ttfb = (first_event_at - started_at) if first_event_at is not None else -1.0
    agent_turns_count = (
        int(getattr(session.agent, "last_turn_count", 0))
        if session.agent is not None
        else 0
    )
    logger.info(
        "agent_timing marker=done_emitted session_id=%s "
        "agent_turns_count=%d preview_rows_rated=%d preview_total_rows=%d "
        "first_event_source=%s ttfb=%.3f elapsed=%.3f",
        session_id,
        agent_turns_count,
        preview_rows_rated,
        preview_total_rows,
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
    from src.services.gateway_provider import get_data_gateway_if_connected

    effective_payload = payload or CreateConversationRequest()

    session_id = str(uuid4())
    session = _session_manager.get_or_create_session(session_id)
    session.interactive_shipping = effective_payload.interactive_shipping

    # Best-effort prewarm when a source already exists; do not block response.
    # Only check if the gateway is already connected — never open an MCP stdio
    # connection during conversation creation (causes cancel-scope conflicts
    # with FastAPI's request lifecycle).
    try:
        gw = get_data_gateway_if_connected()
        if gw is not None:
            source_info = await gw.get_source_info()
            if source_info is not None and not session.interactive_shipping:
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

    session = _session_manager.get_session(session_id)
    if session is not None and session.terminating:
        raise HTTPException(status_code=409, detail="Session is being terminated")

    # Store user message in history
    _session_manager.add_message(session_id, "user", payload.content)

    # Process via agent in background
    background_tasks.add_task(_process_agent_message, session_id, payload.content)

    return SendMessageResponse(status="accepted", session_id=session_id)


# UPS paperless document upload — allowed file extensions.
_ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "gif", "jpg", "jpeg", "png", "tif"}
# UPS max file size: 10 MB.
_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


@router.post(
    "/{session_id}/upload-document",
    response_model=UploadDocumentResponse,
)
async def upload_document(
    session_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    notes: str = Form(""),
) -> UploadDocumentResponse:
    """Upload a customs/trade document for paperless processing.

    Accepts a binary file via multipart form, validates format and size,
    base64-encodes server-side, stages the data in the attachment store,
    and triggers the agent with a structured ``[DOCUMENT_ATTACHED]`` message.

    Args:
        session_id: Conversation session ID.
        file: Uploaded file (multipart).
        document_type: UPS document type code (e.g. '002').
        notes: Optional notes to include in the agent message.
        background_tasks: FastAPI background task manager.

    Returns:
        UploadDocumentResponse with file metadata.

    Raises:
        HTTPException: 404 if session not found, 409 if terminating,
            400 if file format/size invalid.
    """
    from src.services import attachment_store

    # Validate session exists
    if session_id not in _session_manager.list_sessions():
        raise HTTPException(status_code=404, detail="Session not found")

    session = _session_manager.get_session(session_id)
    if session is not None and session.terminating:
        raise HTTPException(status_code=409, detail="Session is being terminated")

    # Validate file extension
    file_name = file.filename or "document"
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
        )

    # Read and validate file size
    file_bytes = await file.read()
    if len(file_bytes) > _MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds 10 MB limit ({len(file_bytes):,} bytes).",
        )

    # Base64-encode server-side (never enters LLM context)
    file_content_base64 = base64.b64encode(file_bytes).decode("ascii")

    # Stage attachment for the tool handler
    attachment_store.stage(session_id, {
        "file_content_base64": file_content_base64,
        "file_name": file_name,
        "file_format": ext,
        "document_type": document_type,
        "file_size_bytes": len(file_bytes),
    })

    # Build agent message
    doc_type_label = DOCUMENT_TYPE_LABELS.get(document_type, f"Type {document_type}")
    notes_suffix = f" Notes: {notes}" if notes.strip() else ""
    agent_message = (
        f"[DOCUMENT_ATTACHED: {file_name} ({ext}, {doc_type_label})]{notes_suffix}"
    )

    # Store in conversation history and trigger agent processing
    _session_manager.add_message(session_id, "user", agent_message)
    background_tasks.add_task(_process_agent_message, session_id, agent_message)

    return UploadDocumentResponse(
        success=True,
        file_name=file_name,
        file_format=ext,
        file_size_bytes=len(file_bytes),
    )


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
    # Mark session as terminating to prevent concurrent message processing
    session = _session_manager.get_session(session_id)
    if session is not None:
        session.terminating = True

    # Stop prewarm and agent before removing session
    await _session_manager.cancel_session_prewarm_task(session_id)
    await _session_manager.stop_session_agent(session_id)
    _session_manager.remove_session(session_id)
    _event_queues.pop(session_id, None)
    logger.info("Deleted conversation session: %s", session_id)
    return Response(status_code=204)
