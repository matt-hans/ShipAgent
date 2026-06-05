"""FastAPI routes for agent-driven SSE conversations.

Each conversation session has a persistent conversation agent instance. Runtime
adapters stay behind the provider-neutral conversation service boundary, and
the agent is rebuilt only when the connected data source changes. Sessions are
serialized per-conversation via asyncio.Lock to prevent concurrent access.

Endpoints:
    POST   /conversations/              — Create new session
    POST   /conversations/{id}/messages — Send user message
    GET    /conversations/{id}/stream   — SSE event stream
    GET    /conversations/{id}/history  — Get conversation history
    DELETE /conversations/{id}          — End session (stops agent)
    POST   /conversations/{id}/upload-document — Upload paperless document
    GET    /conversations/              — List persistent sessions (sidebar)
    GET    /conversations/{id}/messages — Load session messages (resume)
    PATCH  /conversations/{id}          — Update session title
    GET    /conversations/{id}/export   — Download session as JSON
"""

import asyncio
import base64
import json
import logging
import os
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sse_starlette.sse import EventSourceResponse

from src.api.schemas_conversations import (
    DOCUMENT_TYPE_LABELS,
    ChatSessionSummary,
    ConversationHistoryMessage,
    ConversationHistoryResponse,
    CreateConversationRequest,
    CreateConversationResponse,
    PersistedMessageResponse,
    SaveArtifactRequest,
    SendMessageRequest,
    SendMessageResponse,
    SessionDetailResponse,
    UpdateTitleRequest,
    UploadDocumentResponse,
)
from src.db.models import AgentDecisionRunStatus
from src.services import conversation_handler
from src.services.agent_session_manager import AgentSessionManager
from src.services.conversation_persistence_service import ConversationPersistenceService
from src.services.decision_audit_context import (
    reset_decision_run_id,
    set_decision_run_id,
)
from src.services.decision_audit_service import DecisionAuditService
from src.services.paperless_constants import (
    UPS_PAPERLESS_ALLOWED_EXTENSIONS,
    UPS_PAPERLESS_UI_ACCEPTED_FORMATS,
    normalize_paperless_extension,
)
from src.utils.redaction import sanitize_error_message

if TYPE_CHECKING:
    from src.services.agent_session_manager import AgentSession

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


def _resolve_session(session_id: str) -> "AgentSession":  # noqa: F821
    """Get or lazily register an agent session.

    If the session exists in the in-memory manager, return it directly.
    Otherwise, check the database — if it exists there (e.g. resumed from
    sidebar or after a backend restart), register it in memory with the
    correct mode. Raises HTTPException 404 if the session doesn't exist
    in either the in-memory manager or the database.

    Args:
        session_id: Conversation session ID.

    Returns:
        The AgentSession for this conversation.

    Raises:
        HTTPException: 404 if session not found anywhere.
        HTTPException: 409 if session is being terminated.
    """
    session = _session_manager.get_session(session_id)

    if session is None:
        from src.db.connection import get_db_context

        with get_db_context() as db:
            svc = ConversationPersistenceService(db)
            db_data = svc.get_session_with_messages(session_id, limit=0)
        if db_data is None or not db_data["session"].get("is_active", True):
            raise HTTPException(status_code=404, detail="Session not found")
        session = _session_manager.get_or_create_session(session_id)
        session.interactive_shipping = db_data["session"].get("mode") == "interactive"
        logger.info(
            "Lazily registered session %s from DB (mode=%s)",
            session_id,
            "interactive" if session.interactive_shipping else "batch",
        )

    if session.terminating:
        raise HTTPException(status_code=409, detail="Session is being terminated")

    return session


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
            rebuilt = await conversation_handler.ensure_agent(
                session,
                source_info,
                interactive_shipping=session.interactive_shipping,
            )
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


def _sanitize_queue_event(event: dict) -> dict:
    """Sanitize sensitive text in events before queueing to SSE clients."""
    if event.get("event") != "error":
        return event
    data = event.get("data")
    if not isinstance(data, dict) or "message" not in data:
        return event
    return {
        **event,
        "data": {
            **data,
            "message": sanitize_error_message(str(data.get("message"))),
        },
    }


async def _process_agent_message(
    session_id: str,
    content: str,
    run_id: str | None = None,
) -> None:
    """Process a user message through the persistent agent.

    Runs as a background task. Reuses the session's provider-neutral
    conversation agent across messages. An asyncio.Lock serializes access per
    session.

    Args:
        session_id: Conversation session ID.
        content: User message text.
    """
    queue = _get_event_queue(session_id)
    session = _session_manager.get_or_create_session(session_id)
    turn_generation: int | None = None

    if session.terminating:
        logger.info("Skipping message for terminating session %s", session_id)
        DecisionAuditService.log_event(
            run_id=run_id,
            phase="error",
            event_name="conversation.processing.skipped_terminating",
            actor="api",
            payload={"session_id": session_id},
        )
        DecisionAuditService.complete_run(
            run_id,
            status=AgentDecisionRunStatus.cancelled,
        )
        await queue.put({"event": "done", "data": {}})
        return

    run_token = set_decision_run_id(run_id)

    def _record_turn_generation(generation: int) -> None:
        nonlocal turn_generation
        turn_generation = generation

    def _turn_can_emit() -> bool:
        if _session_manager.get_session(session_id) is not session:
            return False
        if session.terminating:
            return False
        if turn_generation is None:
            return True
        return session.is_turn_generation_active(turn_generation)

    try:

        def _emit_sync(event_type: str, data: dict) -> None:
            if _turn_can_emit():
                queue.put_nowait(
                    _sanitize_queue_event({"event": event_type, "data": data})
                )

        async for event in conversation_handler.process_message(
            session,
            content,
            interactive_shipping=session.interactive_shipping,
            emit_callback=_emit_sync,
            turn_generation_callback=_record_turn_generation,
        ):
            if not _turn_can_emit():
                break
            await queue.put(_sanitize_queue_event(event))
    except Exception as e:
        logger.error("Agent processing failed for session %s: %s", session_id, e)
        if _turn_can_emit():
            await queue.put(
                {
                    "event": "error",
                    "data": {"message": sanitize_error_message(str(e))},
                }
            )
    finally:
        reset_decision_run_id(run_token)
        if _turn_can_emit():
            await queue.put({"event": "done", "data": {}})
        if (
            turn_generation is not None
            and _session_manager.get_session(session_id) is session
            and session.is_turn_generation_active(turn_generation)
        ):
            session.invalidate_active_turn_generation()


def _schedule_agent_message(
    session_id: str,
    content: str,
    run_id: str | None = None,
) -> None:
    """Schedule agent message processing and bind task to session lifecycle."""
    session = _session_manager.get_or_create_session(session_id)
    task = asyncio.create_task(
        _process_agent_message(session_id, content, run_id=run_id)
    )
    session.message_tasks.add(task)

    def _on_done(done_task: asyncio.Task[None]) -> None:
        session.message_tasks.discard(done_task)
        try:
            done_task.result()
        except asyncio.CancelledError:
            logger.info("Agent message task cancelled for session %s", session_id)
        except Exception:
            logger.exception(
                "Unhandled exception in agent message task for session %s",
                session_id,
            )

    task.add_done_callback(_on_done)


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
            except TimeoutError:
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
        if gw is not None and not session.interactive_shipping:
            # Intentionally avoid awaiting get_source_info() here. Even with an
            # existing connected client, MCP tool calls in request scope can
            # conflict with FastAPI/AnyIO cancellation semantics in tests.
            session.prewarm_task = asyncio.create_task(
                _prewarm_session_agent(session_id)
            )
    except Exception as e:
        logger.warning("Failed to schedule agent prewarm for %s: %s", session_id, e)

    # Persist session to database
    try:
        from src.db.connection import get_db_context

        with get_db_context() as db:
            svc = ConversationPersistenceService(db)
            svc.create_session(
                session_id=session_id,
                mode="interactive"
                if effective_payload.interactive_shipping
                else "batch",
            )
    except Exception as e:
        logger.error("Failed to persist session %s to DB: %s", session_id, e)

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
) -> SendMessageResponse:
    """Send a user message to the conversation agent.

    The message is processed asynchronously. Events are streamed
    via the /stream endpoint.

    Args:
        session_id: Conversation session ID.
        payload: User message request body.

    Returns:
        SendMessageResponse confirming acceptance.

    Raises:
        HTTPException: 404 if session not found.
    """
    session = _resolve_session(session_id)

    # Store user message in history
    _session_manager.add_message(session_id, "user", payload.content)

    # Persist user message to database and set title from first message
    try:
        from src.db.connection import get_db_context

        with get_db_context() as db:
            svc = ConversationPersistenceService(db)
            svc.save_message(session_id, "user", payload.content)
            svc.set_title_from_first_message(session_id, payload.content)
    except Exception as e:
        logger.error("Failed to persist user message to DB: %s", e)

    run_id = DecisionAuditService.start_run(
        session_id=session_id,
        user_message=payload.content,
        model=os.environ.get("AGENT_MODEL") or os.environ.get("ANTHROPIC_MODEL"),
        interactive_shipping=session.interactive_shipping,
    )
    DecisionAuditService.log_event(
        run_id=run_id,
        phase="ingress",
        event_name="conversation.message.accepted",
        actor="api",
        payload={
            "session_id": session_id,
            "content_length": len(payload.content),
            "interactive_shipping": session.interactive_shipping,
        },
    )

    # Process via app-level task (not request-scoped background task)
    _schedule_agent_message(session_id, payload.content, run_id=run_id)

    return SendMessageResponse(status="accepted", session_id=session_id)


# UPS max file size: 10 MB.
_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


@router.post(
    "/{session_id}/upload-document",
    response_model=UploadDocumentResponse,
)
async def upload_document(
    session_id: str,
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

    Returns:
        UploadDocumentResponse with file metadata.

    Raises:
        HTTPException: 404 if session not found, 409 if terminating,
            400 if file format/size invalid.
    """
    from src.services import attachment_store

    session = _resolve_session(session_id)

    # Validate file extension
    file_name = file.filename or "document"
    file_ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    normalized_ext = normalize_paperless_extension(file_ext)
    if normalized_ext is None or file_ext not in UPS_PAPERLESS_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file format '{file_ext}'. "
                f"Allowed: {', '.join(UPS_PAPERLESS_UI_ACCEPTED_FORMATS)}"
            ),
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
    attachment_store.stage(
        session_id,
        {
            "file_content_base64": file_content_base64,
            "file_name": file_name,
            "file_format": normalized_ext,
            "document_type": document_type,
            "file_size_bytes": len(file_bytes),
        },
    )

    # Build agent message
    doc_type_label = DOCUMENT_TYPE_LABELS.get(document_type, f"Type {document_type}")
    notes_suffix = f" Notes: {notes}" if notes.strip() else ""
    agent_message = f"[DOCUMENT_ATTACHED: {file_name} ({normalized_ext}, {doc_type_label})]{notes_suffix}"

    # Store in conversation history and trigger agent processing
    _session_manager.add_message(session_id, "user", agent_message)
    run_id = DecisionAuditService.start_run(
        session_id=session_id,
        user_message=agent_message,
        model=os.environ.get("AGENT_MODEL") or os.environ.get("ANTHROPIC_MODEL"),
        interactive_shipping=bool(session.interactive_shipping)
        if session is not None
        else False,
    )
    DecisionAuditService.log_event(
        run_id=run_id,
        phase="ingress",
        event_name="conversation.document.accepted",
        actor="api",
        payload={
            "session_id": session_id,
            "file_name": file_name,
            "file_format": normalized_ext,
            "file_size_bytes": len(file_bytes),
            "document_type": document_type,
        },
    )
    _schedule_agent_message(session_id, agent_message, run_id=run_id)

    return UploadDocumentResponse(
        success=True,
        file_name=file_name,
        file_format=normalized_ext,
        file_size_bytes=len(file_bytes),
    )


@router.get("/{session_id}/stream")
async def stream_events(request: Request, session_id: str) -> EventSourceResponse:
    """SSE stream of agent events for this conversation.

    Connect to this endpoint after sending a message to receive
    real-time agent events (thinking, tool calls, messages, etc.).

    Security note (F-5, CWE-284): Single-tenant app — session ownership is
    enforced by the perimeter API key middleware (all authenticated requests
    share the same privilege level). Session IDs use UUID v4 (122 bits of
    entropy), making brute-force infeasible. If this application is ever
    extended to multi-tenant, add a session.user_id column and enforce
    ownership checks: ``if session.user_id != authenticated_user.id: 403``.

    Args:
        request: FastAPI request for disconnect detection.
        session_id: Conversation session ID.

    Returns:
        EventSourceResponse streaming agent events.

    Raises:
        HTTPException: 404 if session not found.
    """
    _resolve_session(session_id)

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
    _resolve_session(session_id)

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


async def _teardown_session(session_id: str) -> None:
    """Stop agent, cancel tasks, and remove in-memory state for a session.

    Shared cleanup logic used by delete, bulk-delete, and shutdown paths.
    Marks the session as terminating, cancels background tasks, stops the
    agent, and removes the event queue.

    Args:
        session_id: Conversation session ID to tear down.
    """
    session = _session_manager.get_session(session_id)
    if session is not None:
        session.terminating = True
        session.invalidate_active_turn_generation()
    await _session_manager.cancel_session_message_tasks(session_id)
    await _session_manager.cancel_session_prewarm_task(session_id)
    await _session_manager.stop_session_agent(session_id)
    _session_manager.remove_session(session_id)
    _event_queues.pop(session_id, None)


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
    # Soft-delete from database (keep for history)
    try:
        from src.db.connection import get_db_context

        with get_db_context() as db:
            svc = ConversationPersistenceService(db)
            svc.soft_delete_session(session_id)
    except Exception as e:
        logger.error("Failed to soft-delete session %s from DB: %s", session_id, e)

    await _teardown_session(session_id)
    logger.info("Deleted conversation session: %s", session_id)
    return Response(status_code=204)


@router.post("/bulk-delete", status_code=200)
async def bulk_delete_conversations() -> dict[str, int]:
    """Soft-delete all active conversation sessions.

    Marks every active session as inactive in the database, then stops
    any running agents and clears in-memory state for each.

    Returns:
        JSON with ``deleted`` count.
    """
    from src.db.connection import get_db_context

    # Soft-delete all active sessions in DB
    try:
        with get_db_context() as db:
            svc = ConversationPersistenceService(db)
            count = svc.soft_delete_all_sessions()
    except Exception as e:
        logger.error("Failed to bulk soft-delete sessions: %s", e)
        raise HTTPException(status_code=500, detail="Bulk delete failed") from None

    # Stop all in-memory sessions
    for sid in list(_session_manager.list_sessions()):
        await _teardown_session(sid)

    logger.info("Bulk-deleted %d conversation sessions", count)
    return {"deleted": count}


# === Chat Session Persistence Endpoints ===


@router.get("/", response_model=list[ChatSessionSummary])
async def list_conversations(
    active_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[ChatSessionSummary]:
    """List conversation sessions for the sidebar.

    Args:
        active_only: If True, exclude soft-deleted sessions.
        limit: Max sessions to return (default 50).
        offset: Number of sessions to skip.

    Returns:
        List of session summaries ordered by recency.
    """
    from src.db.connection import get_db_context

    try:
        with get_db_context() as db:
            svc = ConversationPersistenceService(db)
            sessions = svc.list_sessions(
                active_only=active_only,
                limit=limit,
                offset=offset,
            )
        return [ChatSessionSummary(**s) for s in sessions]
    except Exception as exc:
        logger.error("Failed to list conversations: %s", exc)
        raise HTTPException(
            status_code=500, detail="Failed to list conversations"
        ) from None


@router.get("/{session_id}/messages", response_model=SessionDetailResponse)
async def get_session_messages(
    session_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> SessionDetailResponse:
    """Load a session's message history for resume/display.

    Args:
        session_id: Conversation session ID.
        limit: Max messages to return.
        offset: Skip first N messages.

    Returns:
        Session metadata and ordered messages.

    Raises:
        HTTPException: 404 if session not found.
    """
    from src.db.connection import get_db_context

    with get_db_context() as db:
        svc = ConversationPersistenceService(db)
        result = svc.get_session_with_messages(session_id, limit=limit, offset=offset)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionDetailResponse(
        session=ChatSessionSummary(
            **result["session"], message_count=len(result["messages"])
        ),
        messages=[PersistedMessageResponse(**m) for m in result["messages"]],
    )


@router.patch("/{session_id}")
async def update_conversation(
    session_id: str,
    payload: UpdateTitleRequest,
) -> dict:
    """Update a conversation session's title.

    Args:
        session_id: Conversation session ID.
        payload: Title update request.

    Returns:
        Updated session ID and title.
    """
    from src.db.connection import get_db_context

    with get_db_context() as db:
        svc = ConversationPersistenceService(db)
        found = svc.update_session_title(session_id, payload.title)
    if not found:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"id": session_id, "title": payload.title}


@router.get("/{session_id}/export")
async def export_conversation(session_id: str) -> Response:
    """Export a conversation session as JSON download.

    Args:
        session_id: Conversation session ID.

    Returns:
        JSON file download.

    Raises:
        HTTPException: 404 if session not found.
    """
    import json as json_mod

    from src.db.connection import get_db_context

    with get_db_context() as db:
        svc = ConversationPersistenceService(db)
        export = svc.export_session_json(session_id)
    if export is None:
        raise HTTPException(status_code=404, detail="Session not found")

    title_slug = (
        (export["session"].get("title") or "conversation")
        .replace(" ", "-")
        .lower()[:30]
    )
    filename = f"{title_slug}-{session_id[:8]}.json"

    return Response(
        content=json_mod.dumps(export, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{session_id}/artifacts", status_code=201)
async def save_artifact(
    session_id: str,
    payload: SaveArtifactRequest,
) -> dict:
    """Persist a frontend-generated artifact (e.g. CompletionArtifact) to the session.

    This allows artifacts that are assembled client-side to be saved
    to the DB so they render when loading historical conversations.

    Args:
        session_id: Conversation session ID.
        payload: Artifact content and metadata.

    Returns:
        Confirmation with the session ID.

    Raises:
        HTTPException: 500 on persistence failure.
    """
    try:
        from src.db.connection import get_db_context

        with get_db_context() as db:
            svc = ConversationPersistenceService(db)
            svc.save_message(
                session_id,
                role="assistant",
                content=payload.content,
                message_type="system_artifact",
                metadata=payload.metadata,
            )
    except Exception as exc:
        logger.error("Failed to save artifact for %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail="Failed to save artifact") from None
    return {"session_id": session_id, "status": "saved"}


async def shutdown_conversation_runtime() -> None:
    """Shutdown hook to stop all session-scoped async work."""
    for session_id in list(_session_manager.list_sessions()):
        await _teardown_session(session_id)
