"""Shared conversation handling service.

Extracts the canonical agent session orchestration from conversations.py
so both HTTP routes and InProcessRunner call the same code path.
"""

import asyncio
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
from src.services.agent_session_manager import AgentSession, current_conversation_turn
from src.services.conversation_agent import (
    UnavailableConversationAgent,
    create_conversation_agent,
)
from src.services.conversation_privacy import (
    TEXT_BLOCK_PRIVACY_ERROR,
    PublicTextBlock,
    TextBlockPrivacyError,
    provider_authored_text,
    provider_conversation_history,
)
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
from src.utils.redaction import project_public_artifact

logger = logging.getLogger(__name__)


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
        logger.warning("Failed to fetch MRU contacts for prompt: %s", type(e).__name__)
        return []


def _contacts_rebuild_signature(contacts: list[dict]) -> list[dict]:
    """Return contact content sorted independently from MRU prompt order."""
    return sorted(
        contacts,
        key=lambda contact: (
            str(contact.get("handle") or ""),
            str(contact.get("city") or ""),
            str(contact.get("state_province") or ""),
            bool(contact.get("use_as_ship_to")),
            bool(contact.get("use_as_shipper")),
        ),
    )


def _load_prior_conversation(session_id: str) -> list[dict] | None:
    """Load authored history from DB; the adapter applies its history budget.

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
            result = svc.get_session_with_messages(session_id)
            if result is None or not result["messages"]:
                return None
            return provider_conversation_history(result["messages"])
    except Exception as e:
        logger.warning(
            "Failed to load prior conversation for %s: %s", session_id, type(e).__name__
        )
        return None


def _without_current_user_turn(
    prior_conversation: list[dict] | None,
    current_user_message: str | None,
) -> list[dict] | None:
    """Drop the just-persisted current user turn from resume history."""
    if not prior_conversation or current_user_message is None:
        return prior_conversation
    current_text = provider_authored_text(current_user_message)
    # Turn IDs handle real queued callers. For legacy callers, only inspect the
    # trailing unanswered user suffix; never remove a completed older exchange.
    for index in range(len(prior_conversation) - 1, -1, -1):
        message = prior_conversation[index]
        if message.get("role") != "user":
            break
        if message.get("content") == current_text:
            return prior_conversation[:index] or None
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
        logger.error(
            "Failed to persist session context for %s: %s",
            session_id,
            type(exc).__name__,
        )


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
            turn_id = current_conversation_turn.get()
            svc.save_message(
                session_id,
                "assistant",
                text,
                metadata={"conversation_turn_id": turn_id} if turn_id else None,
            )
    except Exception as exc:
        logger.error(
            "Failed to persist assistant msg for %s: %s", session_id, type(exc).__name__
        )


def _persist_artifact_message(session_id: str, event_type: str, data: dict) -> None:
    """Persist a tool artifact event as a replayable system artifact message."""
    meta_key = _ARTIFACT_METADATA_KEY.get(event_type, event_type)
    metadata = {"action": event_type, meta_key: project_public_artifact(data)}
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
            type(exc).__name__,
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
            type(exc).__name__,
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

    generation = getattr(session, "turn_generation", None)
    source_hash = compute_source_hash(source_info)
    # Snapshot settings under the session turn lock, before any stop/start await.
    model = (
        _resolve_agent_model()
        or os.environ.get("AGENT_MODEL")
        or os.environ.get("ANTHROPIC_MODEL")
    )
    runtime = os.environ.get("SHIPAGENT_AGENT_RUNTIME", "auto").strip().lower()
    if (model or "").startswith("openai:") or (model is None and runtime == "openai"):
        from src.services.conversation_runtime.openai_provider import (
            resolve_openai_model,
        )

        model = "openai:" + resolve_openai_model(model)
    elif (model or "").startswith("gemini:") or (model is None and runtime == "gemini"):
        from src.services.conversation_runtime.gemini_provider import (
            resolve_gemini_model,
        )

        model = "gemini:" + resolve_gemini_model(model)
    model_signature = json.dumps(
        [
            model,
            runtime,
            os.environ.get("OPENAI_MODEL", ""),
            os.environ.get("GEMINI_MODEL", ""),
        ]
    )

    # Fetch MRU contacts for prompt injection (C1 fix)
    contacts = _get_mru_contacts_for_prompt()
    contacts_hash = hashlib.sha256(
        json.dumps(
            _contacts_rebuild_signature(contacts),
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()[:8]

    combined_hash = (
        f"{source_hash}|interactive={interactive_shipping}|contacts={contacts_hash}"
    )

    # Reuse existing agent if config hasn't changed
    if (
        session.agent is not None
        and not isinstance(session.agent, UnavailableConversationAgent)
        and session.agent_source_hash == combined_hash
        and session.agent_model_signature == model_signature
    ):
        return False

    # Stop existing agent if config changed mid-conversation
    if session.agent is not None:
        old_agent = session.agent
        session.agent = None
        session.agent_source_hash = None
        session.agent_model_signature = None
        try:
            await old_agent.stop()
        except Exception as e:
            logger.warning("Error stopping old agent: %s", type(e).__name__)
        session.confirmed_resolutions.clear()

    # Load prior conversation for resumed sessions
    prior_conversation = _without_current_user_turn(
        provider_conversation_history(
            _load_prior_conversation(session.session_id) or session.history
        )
        or None,
        current_user_message,
    )

    shared_runtime = runtime in {
        "fake",
        "openai",
        "gemini",
        "anthropic_messages",
        "anthropic-messages",
    } or (runtime in {"", "auto"} and (model or "").startswith(("openai:", "gemini:")))
    system_prompt = build_system_prompt(
        source_info=source_info,
        interactive_shipping=interactive_shipping,
        contacts=contacts,
        prior_conversation=None if shared_runtime else prior_conversation,
    )

    agent = create_conversation_agent(
        system_prompt=system_prompt,
        interactive_shipping=interactive_shipping,
        session_id=session.session_id,
        model=model,
        runtime=runtime,
        prior_conversation=prior_conversation,
    )
    try:
        await agent.start()
    except BaseException:
        try:
            await agent.stop()
        except Exception as exc:
            logger.warning(
                "Failed startup cleanup exception_type=%s", type(exc).__name__
            )
        raise

    if getattr(session, "terminating", False) is True or (
        isinstance(generation, int)
        and not session.is_turn_generation_active(generation)
    ):
        await agent.stop()
        return False

    session.agent = agent
    session.agent_source_hash = combined_hash
    session.agent_model_signature = model_signature
    session.interactive_shipping = interactive_shipping

    return True


async def process_message(
    session: AgentSession,
    content: str,
    interactive_shipping: bool = False,
    emit_callback: Any | None = None,
    turn_generation_callback: Any | None = None,
    turn_id: str | None = None,
) -> AsyncIterator[dict]:
    """Process a user message through the agent, yielding SSE-compatible events.

    This is the canonical message processing path. Both conversations.py
    and InProcessRunner.send_message() call this function.

    IMPORTANT — History Write Ownership:
        The CALLER owns accepted user ingress; this service owns assistant text.
        - conversations.py route adds user message before calling this function.
        - InProcessRunner.send_message() adds user message before calling this.
        Callers tag queued ingress with a turn_id so later submissions cannot
        enter earlier turns. This function claims that ingress and stores assistant
        response text from agent_message events (see below).

    Args:
        session: The agent session.
        content: User message content.
        interactive_shipping: Whether in interactive mode.
        emit_callback: Optional callback for emitter bridge tool events.

    Yields:
        Event dicts with 'event' and 'data' keys.
    """
    turn_token = current_conversation_turn.set(turn_id)
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
            # Queued callers may have captured a mode that a preceding turn
            # changed while they waited. Session ownership wins at this boundary.
            interactive_shipping = session.interactive_shipping
            if turn_id:
                for message in session.history:
                    metadata = message.get("metadata") or {}
                    if metadata.get("conversation_turn_id") == turn_id:
                        metadata["conversation_turn_state"] = "started"
                from src.db.connection import get_db_context
                from src.services.conversation_persistence_service import (
                    ConversationPersistenceService,
                )

                try:
                    with get_db_context() as db:
                        ConversationPersistenceService(db).start_conversation_turn(
                            session.session_id, turn_id
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to persist conversation turn state exception_type=%s",
                        type(exc).__name__,
                    )
            is_current_turn = _begin_turn_guard(session, turn_generation_callback)

            def _turn_active() -> bool:
                nonlocal run_status
                active = is_current_turn()
                if not active:
                    run_status = AgentDecisionRunStatus.cancelled
                return active

            from src.services.workflow_confirmation import PendingWorkflowActions

            if isinstance(
                getattr(session, "workflow_actions", None), PendingWorkflowActions
            ):
                session.workflow_actions.clear()

            try:
                gw = await get_data_gateway()
                source_info = await gw.get_source_info_typed()
            except Exception as exc:
                logger.warning(
                    "Failed to resolve data source for %s exception_type=%s",
                    session.session_id,
                    type(exc).__name__,
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
                    type(exc).__name__,
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
                try:
                    from src.db.connection import get_db_context
                    from src.services.conversation_persistence_service import (
                        ConversationPersistenceService,
                    )

                    with get_db_context() as db:
                        ConversationPersistenceService(db).update_session_mode(
                            session.session_id, "batch"
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to persist conversation mode exception_type=%s",
                        type(exc).__name__,
                    )

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
            public_text_block = PublicTextBlock()
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
                            type(exc).__name__,
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
                fingerprint = (
                    event_type
                    + ":"
                    + hashlib.sha256(
                        json.dumps(data, sort_keys=True, default=str).encode()
                    ).hexdigest()
                )
                if fingerprint in persisted_events:
                    return
                persisted_events.add(fingerprint)
                _persist_artifact_message(session.session_id, event_type, data)

            def _service_emit(event_type: str, data: dict) -> None:
                nonlocal artifact_emitted
                if not _turn_active():
                    return
                event_data = project_public_artifact(data or {})
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
                bridge.effect_callback = (
                    lambda event_type, data: _persist_artifact_once(
                        event_type, project_public_artifact(data)
                    )
                )
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
                from src.services.workflow_confirmation import PendingWorkflowActions

                if isinstance(
                    getattr(session, "workflow_actions", None), PendingWorkflowActions
                ):
                    bridge.workflow_actions = session.workflow_actions

            try:
                async for event in session.agent.process_message_stream(content):
                    if not _turn_active():
                        return
                    for bridge_event in _drain_pending_bridge_events():
                        if not _turn_active():
                            return
                        yield bridge_event
                        if not _turn_active():
                            return

                    event_type = event.get("event")
                    data = event.get("data", {})
                    if not isinstance(data, dict):
                        data = {}
                    data = project_public_artifact(data)
                    event = {**event, "data": data}

                    if isinstance(event_type, str):
                        if hide_transient_chat and event_type in _LIVE_ARTIFACT_EVENTS:
                            artifact_emitted = True
                        _persist_artifact_once(event_type, data)
                        _track_preview_ready(event_type, data)

                    if event_type == "agent_message_delta":
                        try:
                            public_text_block.observe(data.get("text", ""))
                        except TextBlockPrivacyError:
                            await session.agent.interrupt()
                            run_status = AgentDecisionRunStatus.failed
                            yield {
                                "event": "error",
                                "data": {"message": TEXT_BLOCK_PRIVACY_ERROR},
                            }
                            return
                        continue

                    if event_type == "agent_message":
                        try:
                            text, streamed = public_text_block.complete(
                                data.get("text", "")
                            )
                        except TextBlockPrivacyError:
                            await session.agent.interrupt()
                            run_status = AgentDecisionRunStatus.failed
                            yield {
                                "event": "error",
                                "data": {"message": TEXT_BLOCK_PRIVACY_ERROR},
                            }
                            return
                        event = {**event, "data": {**data, "text": text}}
                        if streamed and not hide_transient_chat and text:
                            yield {
                                "event": "agent_message_delta",
                                "data": {"text": text},
                            }
                        if not _turn_active():
                            return
                        if hide_transient_chat:
                            if text:
                                buffered_agent_messages.append(text)
                            continue
                        if text:
                            session.add_message("assistant", text)
                            _persist_assistant_message(session.session_id, text)
                    elif event_type == "error":
                        public_text_block = PublicTextBlock()
                        run_status = AgentDecisionRunStatus.failed

                    yield event
                    if not _turn_active():
                        return

                if not _turn_active():
                    return
                if public_text_block.length:
                    await session.agent.interrupt()
                    run_status = AgentDecisionRunStatus.failed
                    yield {
                        "event": "error",
                        "data": {"message": TEXT_BLOCK_PRIVACY_ERROR},
                    }
                    return

                for bridge_event in _drain_pending_bridge_events():
                    if not _turn_active():
                        return
                    yield bridge_event
                    if not _turn_active():
                        return

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
                    bridge.effect_callback = None
    except (asyncio.CancelledError, GeneratorExit):
        run_status = AgentDecisionRunStatus.cancelled
        raise
    except Exception as exc:
        run_status = AgentDecisionRunStatus.failed
        _log_decision_event(
            run_id=active_run_id,
            phase="error",
            event_name="conversation.processing.failed",
            actor="system",
            payload={"exception_type": type(exc).__name__},
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
                        type(exc).__name__,
                    )
        finally:
            current_conversation_turn.reset(turn_token)
            reset_decision_job_id(job_token)
            if run_token is not None:
                reset_decision_run_id(run_token)


async def decide_workflow_action(
    session: AgentSession,
    confirmation_token: str,
    decision: str,
    emit_callback: Callable[[str, dict], None] | None = None,
) -> dict[str, str]:
    """Trusted UI boundary for session-bound auxiliary workflow confirmations."""
    import asyncio

    from src.services.workflow_confirmation import (
        WorkflowConfirmationError,
        decide_action,
    )

    async with session.lock:
        if session.terminating:
            raise WorkflowConfirmationError("Conversation is no longer active.")
        run_id = DecisionAuditService.start_run(
            session_id=session.session_id,
            user_message=f"User chose {decision} on an auxiliary workflow preview.",
            model=None,
            interactive_shipping=session.interactive_shipping,
        )
        status = AgentDecisionRunStatus.failed
        _log_decision_event(
            run_id=run_id,
            phase="ingress",
            event_name="workflow.confirmation.received",
            actor="api",
            payload={"decision": decision},
        )
        try:
            result = await decide_action(
                session.workflow_actions,
                confirmation_token,
                decision,
                record_outcome=lambda event_type, data: _persist_artifact_message(
                    session.session_id, event_type, data
                ),
            )
            if result is None:
                status = AgentDecisionRunStatus.cancelled
                _log_decision_event(
                    run_id=run_id,
                    phase="egress",
                    event_name="workflow.confirmation.cancelled",
                    actor="system",
                )
                return {"status": "cancelled"}
            event_type, data = result
            _persist_artifact_message(session.session_id, event_type, data)
            if emit_callback and not session.terminating:
                emit_callback(event_type, data)
            status = AgentDecisionRunStatus.completed
            _log_decision_event(
                run_id=run_id,
                phase="egress",
                event_name="workflow.confirmation.completed",
                actor="system",
                payload={"action": data.get("action"), "artifact": event_type},
            )
            return {"status": "completed"}
        except asyncio.CancelledError:
            status = AgentDecisionRunStatus.cancelled
            _log_decision_event(
                run_id=run_id,
                phase="error",
                event_name="workflow.confirmation.interrupted",
                actor="system",
            )
            raise
        except Exception as exc:
            _log_decision_event(
                run_id=run_id,
                phase="error",
                event_name="workflow.confirmation.failed",
                actor="system",
                payload={"exception_type": type(exc).__name__},
            )
            raise
        finally:
            DecisionAuditService.complete_run(run_id, status=status)
