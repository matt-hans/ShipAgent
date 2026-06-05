"""Shared conversation handling service.

Extracts the canonical agent session orchestration from conversations.py
so both HTTP routes and InProcessRunner call the same code path.
"""

import hashlib
import json
import logging
import os
from collections.abc import AsyncIterator, Callable
from typing import Any

from src.db.models import AgentDecisionRunStatus
from src.orchestrator.agent.intent_detection import (
    is_batch_shipping_request,
    is_confirmation_response,
    is_shipping_request,
)
from src.services.agent_session_manager import AgentSession
from src.services.conversation_agent import create_conversation_agent
from src.services.decision_audit_context import (
    get_decision_job_id,
    get_decision_run_id,
    reset_decision_job_id,
    reset_decision_run_id,
    set_decision_job_id,
    set_decision_run_id,
)
from src.services.decision_audit_service import DecisionAuditService
from src.services.gateway_provider import get_data_gateway

logger = logging.getLogger(__name__)

# Max messages to load for system prompt injection on resume
MAX_RESUME_MESSAGES = 30


def _resolve_agent_model() -> str | None:
    """Read agent_model from DB settings, returning None on failure."""
    try:
        from src.db.connection import get_db_context
        from src.services.settings_service import SettingsService

        with get_db_context() as db:
            return SettingsService(db).get_or_create().agent_model
    except Exception:
        logger.warning("Failed to read agent_model from settings")
        return None


def _get_mru_contacts_for_prompt() -> list[dict]:
    """Fetch MRU contacts for system prompt injection.

    Uses get_db_context for clean session management.
    Returns up to MAX_PROMPT_CONTACTS contacts sorted by last_used_at DESC.

    Returns:
        List of contact dicts with handle, city, state_province,
        use_as_ship_to, use_as_shipper keys.
    """
    from src.db.connection import get_db_context
    from src.orchestrator.agent.system_prompt import MAX_PROMPT_CONTACTS
    from src.services.contact_service import ContactService

    try:
        with get_db_context() as db:
            svc = ContactService(db)
            contacts = svc.get_mru_contacts(limit=MAX_PROMPT_CONTACTS)
            return [
                {
                    "handle": c.handle,
                    "city": c.city,
                    "state_province": c.state_province,
                    "use_as_ship_to": c.use_as_ship_to,
                    "use_as_shipper": c.use_as_shipper,
                }
                for c in contacts
            ]
    except Exception as e:
        logger.warning("Failed to fetch MRU contacts for prompt: %s", e)
        return []


def _load_prior_conversation(session_id: str) -> list[dict] | None:
    """Load prior conversation messages from DB for system prompt injection.

    Mirrors the _get_mru_contacts_for_prompt() pattern: uses get_db_context
    for clean session management, returns data or None on failure.

    Args:
        session_id: The conversation session ID.

    Returns:
        List of {role, content} dicts, or None if no history exists.
    """
    from src.db.connection import get_db_context
    from src.services.conversation_persistence_service import (
        ConversationPersistenceService,
    )

    try:
        with get_db_context() as db:
            svc = ConversationPersistenceService(db)
            result = svc.get_session_with_messages(
                session_id, limit=MAX_RESUME_MESSAGES
            )
            if result is None or not result["messages"]:
                return None
            return [
                {"role": m["role"], "content": m["content"]} for m in result["messages"]
            ]
    except Exception as e:
        logger.warning("Failed to load prior conversation for %s: %s", session_id, e)
        return None


def _without_current_user_turn(
    prior_conversation: list[dict] | None,
    current_user_message: str | None,
) -> list[dict] | None:
    """Drop the just-persisted current user turn from resume history."""
    if not prior_conversation or current_user_message is None:
        return prior_conversation
    last_message = prior_conversation[-1]
    if (
        last_message.get("role") == "user"
        and last_message.get("content") == current_user_message
    ):
        trimmed = prior_conversation[:-1]
        return trimmed or None
    return prior_conversation


def _begin_turn_guard(
    session: AgentSession,
    turn_generation_callback: Any | None,
) -> Callable[[], bool]:
    begin_turn_generation = getattr(session, "begin_turn_generation", None)
    is_turn_generation_active = getattr(session, "is_turn_generation_active", None)
    if not callable(begin_turn_generation) or not callable(is_turn_generation_active):
        return lambda: getattr(session, "terminating", False) is not True

    turn_generation = begin_turn_generation()
    if turn_generation_callback is not None:
        turn_generation_callback(turn_generation)

    def turn_active() -> bool:
        if getattr(session, "terminating", False) is True:
            return False
        return bool(is_turn_generation_active(turn_generation))

    return turn_active


def compute_source_hash(source_info: Any) -> str:
    """Compute hash of current data source for change detection.

    Args:
        source_info: Data source info from gateway.

    Returns:
        Hash string for comparison.
    """
    if source_info is None:
        return "none"
    try:
        raw = json.dumps(source_info.__dict__, sort_keys=True, default=str)
    except (TypeError, AttributeError):
        raw = str(source_info)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _build_source_signature(source_info: Any | None) -> dict[str, Any] | None:
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


def _persist_session_context(session_id: str, source_info: Any | None) -> None:
    """Persist current source context to the conversation session record."""
    try:
        if source_info is None:
            return

        from src.db.connection import get_db_context
        from src.services.conversation_persistence_service import (
            ConversationPersistenceService,
        )
        from src.services.saved_data_source_service import SavedDataSourceService

        saved_source_id: str | None = None
        file_path = getattr(source_info, "file_path", None) or ""
        source_type = getattr(source_info, "source_type", None) or ""
        row_count = getattr(source_info, "row_count", 0) or 0

        ds_type: str | None = None
        if source_type in ("csv", "excel", "database"):
            ds_type = "local"
        elif source_type == "shopify":
            ds_type = "shopify"
        elif source_type == "amazon":
            ds_type = "amazon"

        with get_db_context() as db:
            if ds_type == "local" and file_path:
                sources = SavedDataSourceService.list_sources(
                    db,
                    source_type=source_type,
                )
                for src in sources:
                    if src.file_path and src.file_path == file_path:
                        saved_source_id = src.id
                        break

            label = file_path.rsplit("/", 1)[-1] if file_path else source_type
            context_data = {
                "data_source": {
                    "type": ds_type,
                    "source_type": source_type,
                    "saved_source_id": saved_source_id,
                    "file_path": file_path or None,
                    "label": label,
                    "row_count": row_count,
                },
            }

            svc = ConversationPersistenceService(db)
            svc.update_session_context(session_id, context_data)
    except Exception as exc:
        logger.error("Failed to persist session context for %s: %s", session_id, exc)


_LIVE_ARTIFACT_EVENTS: set[str] = {
    "preview_partial",
    "preview_ready",
    "pickup_preview",
    "pickup_result",
    "location_result",
    "landed_cost_result",
    "paperless_upload_prompt",
    "paperless_result",
    "tracking_result",
    "contact_saved",
}

_PERSISTABLE_ARTIFACTS: set[str] = {
    "preview_ready",
    "pickup_result",
    "location_result",
    "landed_cost_result",
    "paperless_result",
    "tracking_result",
    "contact_saved",
}

_ARTIFACT_METADATA_KEY: dict[str, str] = {
    "preview_ready": "batchPreview",
    "pickup_result": "pickup",
    "location_result": "location",
    "landed_cost_result": "landedCost",
    "paperless_result": "paperless",
    "tracking_result": "tracking",
    "contact_saved": "contactSaved",
}


def _hide_transient_chat_enabled() -> bool:
    """Return whether artifact turns should hide transient assistant text."""
    raw = os.environ.get("AGENT_HIDE_TRANSIENT_CHAT", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _persist_assistant_message(session_id: str, text: str) -> None:
    """Persist assistant text best-effort without blocking the stream."""
    try:
        from src.db.connection import get_db_context
        from src.services.conversation_persistence_service import (
            ConversationPersistenceService,
        )

        with get_db_context() as db:
            svc = ConversationPersistenceService(db)
            svc.save_message(session_id, "assistant", text)
    except Exception as exc:
        logger.error("Failed to persist assistant msg for %s: %s", session_id, exc)


def _persist_artifact_message(session_id: str, event_type: str, data: dict) -> None:
    """Persist a tool artifact event as a replayable system artifact message."""
    meta_key = _ARTIFACT_METADATA_KEY.get(event_type, event_type)
    metadata = {"action": event_type, meta_key: data}
    try:
        from src.db.connection import get_db_context
        from src.services.conversation_persistence_service import (
            ConversationPersistenceService,
        )

        with get_db_context() as db:
            svc = ConversationPersistenceService(db)
            svc.save_message(
                session_id,
                role="assistant",
                content="",
                message_type="system_artifact",
                metadata=metadata,
            )
    except Exception as exc:
        logger.error(
            "Failed to persist artifact %s for %s: %s",
            event_type,
            session_id,
            exc,
        )


def _log_decision_event(
    *,
    run_id: str | None,
    phase: str,
    event_name: str,
    actor: str,
    payload: dict[str, Any] | None = None,
    latency_ms: int | None = None,
) -> None:
    """Write a decision audit event best-effort."""
    try:
        DecisionAuditService.log_event(
            run_id=run_id,
            phase=phase,
            event_name=event_name,
            actor=actor,
            payload=payload,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        logger.warning(
            "Decision audit log_event failed for %s/%s: %s",
            run_id,
            event_name,
            exc,
        )


async def ensure_agent(
    session: AgentSession,
    source_info: Any,
    interactive_shipping: bool = False,
    current_user_message: str | None = None,
) -> bool:
    """Ensure the agent exists and is current for the session.

    Creates a new conversation agent if none exists or if the data source has
    changed. This is the canonical agent creation path.

    Args:
        session: The agent session to ensure.
        source_info: Current data source info.
        interactive_shipping: Whether to create in interactive mode.

    Returns:
        True if a new agent was created, False if reused existing.
    """
    from src.orchestrator.agent.system_prompt import build_system_prompt

    source_hash = compute_source_hash(source_info)

    # Fetch MRU contacts for prompt injection (C1 fix)
    contacts = _get_mru_contacts_for_prompt()
    contacts_hash = hashlib.sha256(
        json.dumps(contacts, sort_keys=True, default=str).encode()
    ).hexdigest()[:8]

    combined_hash = (
        f"{source_hash}|interactive={interactive_shipping}|contacts={contacts_hash}"
    )

    # Reuse existing agent if config hasn't changed
    if session.agent is not None and session.agent_source_hash == combined_hash:
        return False

    # Stop existing agent if config changed mid-conversation
    if session.agent is not None:
        try:
            await session.agent.stop()
        except Exception as e:
            logger.warning("Error stopping old agent: %s", e)
        session.confirmed_resolutions.clear()

    # Fetch column samples for filter grounding (batch mode only)
    column_samples = None
    if source_info is not None and not interactive_shipping:
        try:
            gw = await get_data_gateway()
            column_samples = await gw.get_column_samples(max_samples=5)
        except Exception as e:
            logger.debug("Could not fetch column samples: %s", e)

    # Load prior conversation for resumed sessions
    prior_conversation = _without_current_user_turn(
        _load_prior_conversation(session.session_id),
        current_user_message,
    )

    system_prompt = build_system_prompt(
        source_info=source_info,
        interactive_shipping=interactive_shipping,
        column_samples=column_samples,
        contacts=contacts,
        prior_conversation=prior_conversation,
    )

    agent = create_conversation_agent(
        system_prompt=system_prompt,
        interactive_shipping=interactive_shipping,
        session_id=session.session_id,
        model=_resolve_agent_model(),
        prior_conversation=prior_conversation,
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
    turn_generation_callback: Any | None = None,
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
    existing_run_id = get_decision_run_id()
    active_run_id = existing_run_id
    run_token = None
    job_token = set_decision_job_id(None)
    run_status = AgentDecisionRunStatus.completed

    if active_run_id is None:
        active_run_id = DecisionAuditService.start_run(
            session_id=session.session_id,
            user_message=content,
            model=None,
            interactive_shipping=interactive_shipping,
        )
        run_token = set_decision_run_id(active_run_id)

    try:
        async with session.lock:
            _turn_active = _begin_turn_guard(session, turn_generation_callback)

            try:
                gw = await get_data_gateway()
                source_info = await gw.get_source_info_typed()
            except Exception as exc:
                logger.warning(
                    "Failed to resolve data source for %s: %s", session.session_id, exc
                )
                source_info = None
            if not _turn_active():
                return

            source_type = (
                getattr(source_info, "source_type", "none")
                if source_info is not None
                else "none"
            )
            try:
                DecisionAuditService.update_run_source_signature(
                    active_run_id,
                    _build_source_signature(source_info),
                )
            except Exception as exc:
                logger.warning(
                    "Decision audit source signature update failed for %s: %s",
                    active_run_id,
                    exc,
                )
            _log_decision_event(
                run_id=active_run_id,
                phase="ingress",
                event_name="conversation.processing.started",
                actor="api",
                payload={
                    "session_id": session.session_id,
                    "content_length": len(content),
                    "source_type": source_type,
                },
            )
            _persist_session_context(session.session_id, source_info)

            if session.interactive_shipping and is_batch_shipping_request(content):
                logger.info(
                    "Switching session %s from interactive to batch mode for "
                    "batch shipping command.",
                    session.session_id,
                )
                session.interactive_shipping = False
                interactive_shipping = False

            await ensure_agent(
                session,
                source_info,
                interactive_shipping,
                current_user_message=content,
            )
            if not _turn_active():
                return

            persisted_events: set[str] = set()
            hide_transient_chat = _hide_transient_chat_enabled()
            artifact_emitted = False
            buffered_agent_messages: list[str] = []
            preview_ready_logged = False
            pending_bridge_events: list[dict[str, Any]] = []

            def _drain_pending_bridge_events() -> list[dict[str, Any]]:
                events = [*pending_bridge_events]
                pending_bridge_events.clear()
                return events

            def _track_preview_ready(event_type: str, data: dict[str, Any]) -> None:
                nonlocal preview_ready_logged
                if event_type != "preview_ready":
                    return
                event_job_id = data.get("job_id")
                if isinstance(event_job_id, str) and event_job_id:
                    set_decision_job_id(event_job_id)
                    try:
                        DecisionAuditService.set_run_job_id(active_run_id, event_job_id)
                    except Exception as exc:
                        logger.warning(
                            "Decision audit set_run_job_id failed for %s: %s",
                            active_run_id,
                            exc,
                        )
                    if not preview_ready_logged:
                        preview_ready_logged = True
                        _log_decision_event(
                            run_id=active_run_id,
                            phase="pipeline",
                            event_name="pipeline.preview_ready",
                            actor="system",
                            payload={
                                "job_id": event_job_id,
                                "total_rows": data.get("total_rows", 0),
                            },
                        )

            def _persist_artifact_once(event_type: str, data: dict[str, Any]) -> None:
                if event_type not in _PERSISTABLE_ARTIFACTS:
                    return
                if event_type in persisted_events:
                    return
                persisted_events.add(event_type)
                _persist_artifact_message(session.session_id, event_type, data)

            def _service_emit(event_type: str, data: dict) -> None:
                nonlocal artifact_emitted
                if not _turn_active():
                    return
                event_data = data or {}
                if hide_transient_chat and event_type in _LIVE_ARTIFACT_EVENTS:
                    artifact_emitted = True
                if isinstance(event_type, str):
                    _persist_artifact_once(event_type, event_data)
                    _track_preview_ready(event_type, event_data)
                if emit_callback:
                    emit_callback(event_type, event_data)
                else:
                    pending_bridge_events.append(
                        {"event": event_type, "data": event_data}
                    )

            bridge = getattr(session.agent, "emitter_bridge", None)
            if bridge is not None:
                bridge.callback = _service_emit
                bridge.last_user_message = content
                if is_shipping_request(content):
                    bridge.last_shipping_command = content
                elif is_confirmation_response(content):
                    # Preserve the previous shipping command for confirmation turns.
                    pass
                else:
                    bridge.last_shipping_command = None
                bridge.confirmed_resolutions = session.confirmed_resolutions

            try:
                async for event in session.agent.process_message_stream(content):
                    if not _turn_active():
                        return
                    for bridge_event in _drain_pending_bridge_events():
                        if not _turn_active():
                            return
                        yield bridge_event

                    event_type = event.get("event")
                    data = event.get("data", {})
                    if not isinstance(data, dict):
                        data = {}

                    if isinstance(event_type, str):
                        if hide_transient_chat and event_type in _LIVE_ARTIFACT_EVENTS:
                            artifact_emitted = True
                        _persist_artifact_once(event_type, data)
                        _track_preview_ready(event_type, data)

                    if event_type == "agent_message_delta" and hide_transient_chat:
                        continue

                    if event_type == "agent_message":
                        text = event.get("data", {}).get("text", "")
                        if hide_transient_chat:
                            if text:
                                buffered_agent_messages.append(text)
                            continue
                        if text:
                            session.add_message("assistant", text)
                            _persist_assistant_message(session.session_id, text)
                    elif event_type == "error":
                        run_status = AgentDecisionRunStatus.failed

                    yield event

                for bridge_event in _drain_pending_bridge_events():
                    if not _turn_active():
                        return
                    yield bridge_event

                if hide_transient_chat:
                    if not _turn_active():
                        return
                    if artifact_emitted:
                        logger.info(
                            "agent_transient_chat_suppressed session_id=%s buffered=%d",
                            session.session_id,
                            len(buffered_agent_messages),
                        )
                    elif buffered_agent_messages:
                        final_text = buffered_agent_messages[-1]
                        if final_text:
                            session.add_message("assistant", final_text)
                            _persist_assistant_message(session.session_id, final_text)
                            yield {
                                "event": "agent_message",
                                "data": {"text": final_text},
                            }
            finally:
                bridge = getattr(session.agent, "emitter_bridge", None)
                if bridge is not None:
                    bridge.callback = None
    except Exception as exc:
        run_status = AgentDecisionRunStatus.failed
        _log_decision_event(
            run_id=active_run_id,
            phase="error",
            event_name="conversation.processing.failed",
            actor="system",
            payload={"error": str(exc)},
        )
        raise
    finally:
        try:
            if active_run_id is not None:
                agent_turns_count = (
                    int(getattr(session.agent, "last_turn_count", 0))
                    if session.agent is not None
                    else 0
                )
                _log_decision_event(
                    run_id=active_run_id,
                    phase="egress",
                    event_name="conversation.processing.completed",
                    actor="api",
                    payload={
                        "session_id": session.session_id,
                        "agent_turns_count": agent_turns_count,
                        "status": run_status.value,
                    },
                )
                try:
                    DecisionAuditService.complete_run(
                        active_run_id,
                        status=run_status,
                        job_id=get_decision_job_id(),
                    )
                except Exception as exc:
                    logger.warning(
                        "Decision audit complete_run failed for %s: %s",
                        active_run_id,
                        exc,
                    )
        finally:
            reset_decision_job_id(job_token)
            if run_token is not None:
                reset_decision_run_id(run_token)
