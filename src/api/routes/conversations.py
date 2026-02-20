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
import time
from typing import Any, AsyncGenerator
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
    SendMessageRequest,
    SendMessageResponse,
    SessionDetailResponse,
    UpdateTitleRequest,
    UploadDocumentResponse,
)
from src.services.conversation_persistence_service import ConversationPersistenceService
from src.orchestrator.agent.intent_detection import (
    is_batch_shipping_request,
    is_confirmation_response,
    is_shipping_request,
)
from src.db.models import AgentDecisionRunStatus
from src.services.agent_session_manager import AgentSessionManager
from src.services.decision_audit_context import (
    get_decision_job_id,
    reset_decision_job_id,
    reset_decision_run_id,
    set_decision_job_id,
    set_decision_run_id,
)
from src.services.decision_audit_service import DecisionAuditService
from src.services.paperless_constants import (
    UPS_PAPERLESS_ALLOWED_EXTENSIONS,
    UPS_PAPERLESS_UI_ACCEPTED_FORMATS,
    normalize_paperless_extension,
)

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
        str(getattr(source_info, "signature", "") or ""),
    ]
    return "|".join(parts)


def _build_source_signature(source_info: "DataSourceInfo | None") -> dict[str, Any] | None:
    """Build a stable source signature payload from typed source info."""
    if source_info is None:
        return None
    columns = getattr(source_info, "columns", []) or []
    column_names = [getattr(col, "name", "") for col in columns]
    return {
        "source_type": getattr(source_info, "source_type", "unknown"),
        "source_ref": getattr(source_info, "file_path", "") or "",
        "schema_fingerprint": getattr(source_info, "signature", "") or "",
        "row_count": getattr(source_info, "row_count", 0) or 0,
        "columns": column_names,
    }


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
        # Source changed — invalidate confirmed semantic cache bound to prior schema.
        session.confirmed_resolutions.clear()

    # Fetch column samples for filter grounding (batch mode only).
    column_samples: dict[str, list] | None = None
    if source_info is not None and not session.interactive_shipping:
        try:
            from src.services.gateway_provider import get_data_gateway

            gw_for_samples = await get_data_gateway()
            column_samples = await gw_for_samples.get_column_samples(max_samples=5)
        except Exception as e:
            logger.warning("Failed to fetch column samples: %s", e)

    # Load prior conversation for resumed sessions
    from src.services.conversation_handler import _load_prior_conversation
    prior_conversation = _load_prior_conversation(session.session_id)

    system_prompt = build_system_prompt(
        source_info=source_info,
        interactive_shipping=session.interactive_shipping,
        column_samples=column_samples,
        prior_conversation=prior_conversation,
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


async def _process_agent_message(
    session_id: str,
    content: str,
    run_id: str | None = None,
) -> None:
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

    started_at = time.perf_counter()
    first_event_at: float | None = None
    first_event_source = ""
    preview_rows_rated = 0
    preview_total_rows = 0
    preview_first_partial_logged = False
    preview_total_logged = False
    source_type = "none"
    agent_rebuilt = False
    raw_hide_transient = os.environ.get("AGENT_HIDE_TRANSIENT_CHAT", "true").strip().lower()
    hide_transient_chat = raw_hide_transient not in {"0", "false", "no", "off"}
    buffered_agent_messages: list[str] = []
    artifact_emitted = False
    run_status: AgentDecisionRunStatus = AgentDecisionRunStatus.completed
    artifact_events = {
        "preview_partial",
        "preview_ready",
        "pickup_preview",
        "pickup_result",
        "location_result",
        "landed_cost_result",
        "paperless_upload_prompt",
        "paperless_result",
        "tracking_result",
    }

    logger.info(
        "agent_timing marker=message_received session_id=%s content_len=%d elapsed=%.3f",
        session_id,
        len(content),
        0.0,
    )

    def _track_preview_event(
        event_type: str,
        data: dict[str, Any],
        source: str,
    ) -> None:
        nonlocal preview_rows_rated, preview_total_rows
        nonlocal preview_first_partial_logged, preview_total_logged

        if event_type == "preview_partial":
            rows_rated = int(data.get("rows_rated", 0))
            total_rows = int(data.get("total_rows", 0))
            preview_rows_rated = max(preview_rows_rated, rows_rated)
            preview_total_rows = max(preview_total_rows, total_rows)
            if not preview_first_partial_logged:
                preview_first_partial_logged = True
                logger.info(
                    "metric=preview_first_partial_latency_ms session_id=%s "
                    "source=%s value=%d",
                    session_id,
                    source,
                    int((time.perf_counter() - started_at) * 1000),
                )
            return

        if event_type == "preview_ready":
            preview_total_rows = int(data.get("total_rows", preview_total_rows))
            preview_rows_rated = len(data.get("preview_rows", []))
            if not preview_total_logged:
                preview_total_logged = True
                logger.info(
                    "metric=preview_total_latency_ms session_id=%s source=%s value=%d",
                    session_id,
                    source,
                    int((time.perf_counter() - started_at) * 1000),
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

    run_token = set_decision_run_id(run_id)
    job_token = set_decision_job_id(None)

    async with session.lock:
        try:
            from src.services.gateway_provider import get_data_gateway

            gw = await get_data_gateway()
            source_info = await gw.get_source_info_typed()
            DecisionAuditService.update_run_source_signature(
                run_id,
                _build_source_signature(source_info),
            )
            DecisionAuditService.log_event(
                run_id=run_id,
                phase="ingress",
                event_name="conversation.processing.started",
                actor="api",
                payload={
                    "session_id": session_id,
                    "content_length": len(content),
                    "source_type": getattr(source_info, "source_type", "none")
                    if source_info is not None
                    else "none",
                },
            )

            source_type = source_info.source_type if source_info is not None else "none"
            logger.info(
                "agent_timing marker=source_resolved session_id=%s source_type=%s elapsed=%.3f",
                session_id,
                source_type,
                time.perf_counter() - started_at,
            )

            # Auto-failover: batch shipping commands require FilterSpec tools.
            # If the session is in interactive mode, switch to batch mode and
            # rebuild so resolve_filter_intent/ship_command_pipeline are available.
            if (
                session.interactive_shipping
                and is_batch_shipping_request(content)
            ):
                logger.info(
                    "Switching session %s from interactive to batch mode for "
                    "batch shipping command.",
                    session_id,
                )
                session.interactive_shipping = False

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
                nonlocal artifact_emitted
                _mark_first_event("tool_emit")
                _track_preview_event(event_type, data, "tool_emit")
                if hide_transient_chat and event_type in artifact_events:
                    artifact_emitted = True
                queue.put_nowait({"event": event_type, "data": data})

            session.agent.emitter_bridge.callback = _emit_to_queue
            session.agent.emitter_bridge.last_user_message = content
            if is_shipping_request(content):
                session.agent.emitter_bridge.last_shipping_command = content
            elif is_confirmation_response(content):
                # Keep prior shipping command context for one confirmation turn.
                pass
            else:
                session.agent.emitter_bridge.last_shipping_command = None
            session.agent.emitter_bridge.confirmed_resolutions = (
                session.confirmed_resolutions
            )
            try:
                # Process message — SDK maintains conversation context internally.
                async for event in session.agent.process_message_stream(content):
                    event_type = event.get("event")
                    _mark_first_event(str(event_type or "unknown"))
                    if isinstance(event_type, str):
                        _track_preview_event(
                            event_type,
                            event.get("data", {}),
                            "agent_stream",
                        )
                    if hide_transient_chat and event_type in artifact_events:
                        artifact_emitted = True

                    if event_type == "agent_message":
                        text = event.get("data", {}).get("text", "")
                        if hide_transient_chat:
                            if text:
                                buffered_agent_messages.append(text)
                            continue
                        if text:
                            _session_manager.add_message(session_id, "assistant", text)
                            _persist_assistant_message(session_id, text)
                    elif event_type == "error":
                        run_status = AgentDecisionRunStatus.failed
                    elif event_type == "preview_ready":
                        event_job_id = event.get("data", {}).get("job_id")
                        if isinstance(event_job_id, str) and event_job_id:
                            set_decision_job_id(event_job_id)
                            DecisionAuditService.set_run_job_id(run_id, event_job_id)
                            DecisionAuditService.log_event(
                                run_id=run_id,
                                phase="pipeline",
                                event_name="pipeline.preview_ready",
                                actor="system",
                                payload={
                                    "job_id": event_job_id,
                                    "total_rows": event.get("data", {}).get("total_rows", 0),
                                },
                            )

                    await queue.put(event)

                if hide_transient_chat:
                    if artifact_emitted:
                        logger.info(
                            "agent_transient_chat_suppressed session_id=%s buffered=%d",
                            session_id,
                            len(buffered_agent_messages),
                        )
                    elif buffered_agent_messages:
                        final_text = buffered_agent_messages[-1]
                        if final_text:
                            await queue.put(
                                {
                                    "event": "agent_message",
                                    "data": {"text": final_text},
                                }
                            )
                            _session_manager.add_message(
                                session_id,
                                "assistant",
                                final_text,
                            )
                            _persist_assistant_message(session_id, final_text)
            finally:
                session.agent.emitter_bridge.callback = None

        except Exception as e:
            logger.error("Agent processing failed for session %s: %s", session_id, e)
            _mark_first_event("error")
            run_status = AgentDecisionRunStatus.failed
            DecisionAuditService.log_event(
                run_id=run_id,
                phase="error",
                event_name="conversation.processing.failed",
                actor="system",
                payload={"error": str(e)},
            )
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
        "agent_rebuilt=%s agent_turns_count=%d "
        "preview_rows_rated=%d preview_total_rows=%d batch_concurrency=%s "
        "interactive_shipping=%s first_event_source=%s ttfb=%.3f elapsed=%.3f",
        session_id,
        source_type,
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
    try:
        DecisionAuditService.log_event(
            run_id=run_id,
            phase="egress",
            event_name="conversation.processing.completed",
            actor="api",
            payload={
                "session_id": session_id,
                "agent_turns_count": agent_turns_count,
                "preview_rows_rated": preview_rows_rated,
                "preview_total_rows": preview_total_rows,
                "first_event_source": first_event_source,
                "ttfb_ms": int(ttfb * 1000) if ttfb >= 0 else None,
                "elapsed_ms": int(elapsed * 1000),
            },
            latency_ms=int(elapsed * 1000),
        )
        DecisionAuditService.complete_run(
            run_id,
            status=run_status,
            job_id=get_decision_job_id(),
        )
    finally:
        reset_decision_job_id(job_token)
        reset_decision_run_id(run_token)


def _persist_assistant_message(session_id: str, text: str) -> None:
    """Persist an assistant message to the database and trigger title generation.

    Best-effort — failures are logged at error level but do not block
    the SSE event stream.

    Args:
        session_id: Conversation session ID.
        text: Assistant message text.
    """
    from src.services.conversation_persistence_service import maybe_trigger_title_generation

    try:
        from src.db.connection import get_db_context
        with get_db_context() as db:
            svc = ConversationPersistenceService(db)
            svc.save_message(session_id, "assistant", text)
        maybe_trigger_title_generation(session_id)
    except Exception as exc:
        logger.error("Failed to persist assistant msg for %s: %s", session_id, exc)


def _schedule_agent_message(
    session_id: str,
    content: str,
    run_id: str | None = None,
) -> None:
    """Schedule agent message processing and bind task to session lifecycle."""
    session = _session_manager.get_or_create_session(session_id)
    task = asyncio.create_task(_process_agent_message(session_id, content, run_id=run_id))
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
                mode="interactive" if effective_payload.interactive_shipping else "batch",
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
    if session_id not in _session_manager.list_sessions():
        raise HTTPException(status_code=404, detail="Session not found")

    session = _session_manager.get_session(session_id)
    if session is not None and session.terminating:
        raise HTTPException(status_code=409, detail="Session is being terminated")

    # Store user message in history
    _session_manager.add_message(session_id, "user", payload.content)

    # Persist user message to database
    try:
        from src.db.connection import get_db_context
        with get_db_context() as db:
            svc = ConversationPersistenceService(db)
            svc.save_message(session_id, "user", payload.content)
    except Exception as e:
        logger.error("Failed to persist user message to DB: %s", e)

    run_id = DecisionAuditService.start_run(
        session_id=session_id,
        user_message=payload.content,
        model=os.environ.get("AGENT_MODEL") or os.environ.get("ANTHROPIC_MODEL"),
        interactive_shipping=bool(session.interactive_shipping) if session is not None else False,
    )
    DecisionAuditService.log_event(
        run_id=run_id,
        phase="ingress",
        event_name="conversation.message.accepted",
        actor="api",
        payload={
            "session_id": session_id,
            "content_length": len(payload.content),
            "interactive_shipping": bool(session.interactive_shipping) if session is not None else False,
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

    # Validate session exists
    if session_id not in _session_manager.list_sessions():
        raise HTTPException(status_code=404, detail="Session not found")

    session = _session_manager.get_session(session_id)
    if session is not None and session.terminating:
        raise HTTPException(status_code=409, detail="Session is being terminated")

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
    attachment_store.stage(session_id, {
        "file_content_base64": file_content_base64,
        "file_name": file_name,
        "file_format": normalized_ext,
        "document_type": document_type,
        "file_size_bytes": len(file_bytes),
    })

    # Build agent message
    doc_type_label = DOCUMENT_TYPE_LABELS.get(document_type, f"Type {document_type}")
    notes_suffix = f" Notes: {notes}" if notes.strip() else ""
    agent_message = (
        f"[DOCUMENT_ATTACHED: {file_name} ({normalized_ext}, {doc_type_label})]{notes_suffix}"
    )

    # Store in conversation history and trigger agent processing
    _session_manager.add_message(session_id, "user", agent_message)
    run_id = DecisionAuditService.start_run(
        session_id=session_id,
        user_message=agent_message,
        model=os.environ.get("AGENT_MODEL") or os.environ.get("ANTHROPIC_MODEL"),
        interactive_shipping=bool(session.interactive_shipping) if session is not None else False,
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

    # Soft-delete from database (keep for history)
    try:
        from src.db.connection import get_db_context
        with get_db_context() as db:
            svc = ConversationPersistenceService(db)
            svc.soft_delete_session(session_id)
    except Exception as e:
        logger.error("Failed to soft-delete session %s from DB: %s", session_id, e)

    # Stop prewarm and agent before removing session
    await _session_manager.cancel_session_prewarm_task(session_id)
    await _session_manager.cancel_session_message_tasks(session_id)
    await _session_manager.stop_session_agent(session_id)
    _session_manager.remove_session(session_id)
    _event_queues.pop(session_id, None)
    logger.info("Deleted conversation session: %s", session_id)
    return Response(status_code=204)


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
                active_only=active_only, limit=limit, offset=offset,
            )
        return [ChatSessionSummary(**s) for s in sessions]
    except Exception as exc:
        logger.error("Failed to list conversations: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list conversations")


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
        session=ChatSessionSummary(**result["session"], message_count=len(result["messages"])),
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

    title_slug = (export["session"].get("title") or "conversation").replace(" ", "-").lower()[:30]
    filename = f"{title_slug}-{session_id[:8]}.json"

    return Response(
        content=json_mod.dumps(export, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def shutdown_conversation_runtime() -> None:
    """Shutdown hook to stop all session-scoped async work."""
    for session_id in list(_session_manager.list_sessions()):
        session = _session_manager.get_session(session_id)
        if session is not None:
            session.terminating = True
        await _session_manager.cancel_session_prewarm_task(session_id)
        await _session_manager.cancel_session_message_tasks(session_id)
        await _session_manager.stop_session_agent(session_id)
        _session_manager.remove_session(session_id)
        _event_queues.pop(session_id, None)
