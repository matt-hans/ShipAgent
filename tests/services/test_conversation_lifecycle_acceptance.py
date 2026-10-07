"""Lifecycle through the shared service, real persistence and provider wire adapters."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
from src.services.agent_session_manager import AgentSession
from src.services.conversation_handler import process_message
from src.services.conversation_persistence_service import ConversationPersistenceService
from src.services.settings_service import SettingsService
from tests.services.provider_scenarios import PROVIDERS, Say, build_provider

MODELS = {
    "scripted": "fake",
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "openai:gpt-5-mini",
    "gemini": "gemini:gemini-2.5-flash",
}


@pytest.fixture
def lifecycle(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    @contextmanager
    def context():
        yield db
        db.commit()

    monkeypatch.setattr("src.db.connection.get_db_context", context)
    monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "false")
    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "false")
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(name, "synthetic-lifecycle-key")
    gateway = AsyncMock()
    gateway.get_source_info_typed.return_value = None
    monkeypatch.setattr(
        "src.services.conversation_handler.get_data_gateway",
        AsyncMock(return_value=gateway),
    )
    svc = ConversationPersistenceService(db)
    svc.create_session(session_id="lifecycle", mode="batch")
    yield db, svc
    db.close()
    engine.dispose()


def select_provider(monkeypatch, db, kind, turns):
    rendered = build_provider(kind, turns)
    SettingsService(db).update({"agent_model": MODELS[kind]})
    monkeypatch.setenv(
        "SHIPAGENT_AGENT_RUNTIME",
        {"scripted": "fake", "anthropic": "anthropic_messages"}.get(kind, "auto"),
    )
    names = {
        "scripted": ("fake", "Fake"),
        "anthropic": ("anthropic", "Anthropic"),
        "openai": ("openai", "OpenAI"),
        "gemini": ("gemini", "Gemini"),
    }
    module, cls = names[kind]
    monkeypatch.setattr(
        f"src.services.conversation_runtime.{module}_provider.{cls}ProviderClient",
        lambda **kwargs: rendered.provider,
    )
    return rendered


async def send(session, svc, content):
    from uuid import uuid4

    turn_id = str(uuid4())
    session.add_message("user", content, turn_id=turn_id, queued=True)
    svc.save_message(
        session.session_id,
        "user",
        content,
        metadata={"conversation_turn_id": turn_id, "conversation_turn_state": "queued"},
    )
    return [
        event
        async for event in process_message(
            session, content, session.interactive_shipping, turn_id=turn_id
        )
    ]


def wire(rendered):
    return json.dumps(rendered.requests or rendered.provider.requests, default=asdict)


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_resume_includes_recent_complete_authored_turns_once_with_artifacts_saved_once(
    lifecycle, monkeypatch, kind
):
    db, svc = lifecycle
    for index in range(24):
        svc.save_message("lifecycle", "user", f"historical-question-{index:02d}!")
        svc.save_message("lifecycle", "assistant", f"historical-answer-{index:02d}!")
        svc.save_message(
            "lifecycle",
            "assistant",
            "OWNER-ONLY-ARTIFACT",
            message_type="system_artifact",
            metadata={
                "event_type": "paperless_result",
                "data": {"documentId": "OWNER-DOCUMENT"},
            },
        )
    before = svc.get_session_with_messages("lifecycle")["messages"]
    rendered = select_provider(monkeypatch, db, kind, [[Say("Resumed answer.")]])
    events = await send(AgentSession("lifecycle"), svc, "Current unique question!")
    request = wire(rendered)
    for index in range(24):
        assert request.count(f"historical-question-{index:02d}!") == (
            1 if index >= 9 else 0
        )
        assert request.count(f"historical-answer-{index:02d}!") == (
            1 if index >= 9 else 0
        )
    assert request.count("Current unique question!") == 1
    assert "OWNER-ONLY-ARTIFACT" not in request and "OWNER-DOCUMENT" not in request
    after = svc.get_session_with_messages("lifecycle")["messages"]
    assert len(after) == len(before) + 2
    assert after[:-2] == before
    assert [e["data"].get("text") for e in events if e["event"] == "agent_message"] == [
        "Resumed answer."
    ]


@pytest.mark.parametrize(
    "first,second", [(a, b) for a in PROVIDERS for b in PROVIDERS if a != b]
)
async def test_settings_switch_rebuilds_at_next_turn_and_reseeds_authored_history(
    lifecycle, monkeypatch, first, second
):
    db, svc = lifecycle
    session = AgentSession("lifecycle")
    original = select_provider(
        monkeypatch,
        db,
        first,
        [[Say("Original provider response!")], [Say("STALE PROVIDER!")]],
    )
    await send(session, svc, "First authored request!")
    previous_agent = session.agent
    switched = select_provider(
        monkeypatch, db, second, [[Say("Replacement provider response!")]]
    )
    events = await send(session, svc, "Second authored request!")
    assert [e["data"].get("text") for e in events if e["event"] == "agent_message"] == [
        "Replacement provider response!"
    ]
    assert not previous_agent.is_started
    request = wire(switched)
    for text in (
        "First authored request!",
        "Original provider response!",
        "Second authored request!",
    ):
        assert request.count(text) == 1
    assert "STALE PROVIDER!" not in request
    assert len(original.requests or original.provider.requests) == 1
    messages = svc.get_session_with_messages("lifecycle")["messages"]
    assert [m["content"] for m in messages] == [
        "First authored request!",
        "Original provider response!",
        "Second authored request!",
        "Replacement provider response!",
    ]


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_queued_duplicate_ingress_is_not_future_context_and_resume_orders_turns(
    lifecycle, monkeypatch, kind
):
    import asyncio

    from src.api.routes import conversations as routes
    from src.api.schemas_conversations import SendMessageRequest
    from src.services.agent_session_manager import AgentSessionManager
    from src.services.data_source_mcp_client import DataSourceInfo

    db, svc = lifecycle
    manager = AgentSessionManager()
    monkeypatch.setattr(routes, "_session_manager", manager)
    monkeypatch.setattr(routes, "_event_queues", {})
    gateway = AsyncMock()
    gateway.get_source_info_typed.side_effect = [
        None,
        DataSourceInfo(source_type="csv", row_count=3),
        None,
    ]
    monkeypatch.setattr(
        "src.services.conversation_handler.get_data_gateway",
        AsyncMock(return_value=gateway),
    )
    rendered = select_provider(
        monkeypatch,
        db,
        kind,
        [
            [Say("Answer for first ingress!")],
            [Say("Answer for second ingress!")],
            [Say("Resumed!")],
        ],
    )
    await routes.send_message(
        "lifecycle", SendMessageRequest(content="Same queued question!")
    )
    await routes.send_message(
        "lifecycle", SendMessageRequest(content="Same queued question!")
    )
    session = manager.get_session("lifecycle")
    await asyncio.gather(*list(session.message_tasks))
    requests = rendered.requests or rendered.provider.requests
    assert json.dumps(requests[0], default=asdict).count("Same queued question!") == 1
    assert json.dumps(requests[1], default=asdict).count("Same queued question!") == 2
    assert (
        json.dumps(requests[1], default=asdict).count("Answer for first ingress!") == 1
    )
    await send(AgentSession("lifecycle"), svc, "Resume this conversation!")
    resumed = json.dumps(requests[2], default=asdict)
    # Text locations in each provider's actual transcript must retain logical order.
    first_user = resumed.index("Same queued question!")
    first_answer = resumed.index("Answer for first ingress!")
    second_user = resumed.index("Same queued question!", first_user + 1)
    second_answer = resumed.index("Answer for second ingress!")
    assert first_user < first_answer < second_user < second_answer
    assert len(svc.get_session_with_messages("lifecycle")["messages"]) == 6


@pytest.mark.parametrize("kind", PROVIDERS)
@pytest.mark.parametrize("cancel_task", [False, True])
async def test_interrupted_upload_retains_one_owner_outcome_and_never_replays(
    lifecycle, monkeypatch, kind, cancel_task
):
    import asyncio
    from unittest.mock import MagicMock

    from src.db.models import AgentDecisionRunStatus
    from src.services import attachment_store
    from tests.services.provider_scenarios import Call

    db, svc = lifecycle
    monkeypatch.setattr(
        "src.services.conversation_handler.DecisionAuditService.start_run",
        lambda **kwargs: "upload-audit-run",
    )
    complete = MagicMock()
    monkeypatch.setattr(
        "src.services.conversation_handler.DecisionAuditService.complete_run", complete
    )
    opened, release = asyncio.Event(), asyncio.Event()
    calls = []
    gateway = AsyncMock()

    async def upload(**kwargs):
        calls.append(kwargs)
        opened.set()
        await release.wait()
        return {"success": True, "documentId": "OWNER-ACCEPTED-DOCUMENT"}

    gateway.upload_document.side_effect = upload
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway", AsyncMock(return_value=gateway)
    )
    attachment_id = attachment_store.stage(
        "lifecycle",
        {
            "file_content_base64": "c3ludGhldGlj",
            "file_name": "OWNER-FILE.pdf",
            "file_format": "pdf",
            "document_type": "002",
        },
        gateway=gateway,
    )
    rendered = select_provider(
        monkeypatch,
        db,
        kind,
        [
            [
                Call(
                    "upload",
                    "upload_paperless_document",
                    {"attachment_id": attachment_id},
                )
            ],
            [Say("STALE SUCCESS!")],
        ],
    )
    session = AgentSession("lifecycle")
    events = []

    async def run():
        async for event in process_message(session, "Upload my approved file"):
            events.append(event)

    task = asyncio.create_task(run())
    await opened.wait()
    session.invalidate_active_turn_generation()
    await session.agent.interrupt()
    if cancel_task:
        task.cancel()
    else:
        release.set()
    try:
        await task
    except asyncio.CancelledError:
        pass
    artifacts = [
        m
        for m in svc.get_session_with_messages("lifecycle")["messages"]
        if m["message_type"] == "system_artifact"
    ]
    assert len(artifacts) == 1
    stored = json.dumps(artifacts)
    assert (
        ("unconfirmed" in stored)
        if cancel_task
        else ("OWNER-ACCEPTED-DOCUMENT" in stored)
    )
    assert not any(e["event"] in {"paperless_result", "agent_message"} for e in events)
    assert len(calls) == 1
    assert complete.call_args.kwargs["status"] == AgentDecisionRunStatus.cancelled
    assert not attachment_store.has_pending("lifecycle", attachment_id)
    assert "OWNER-FILE" not in wire(rendered) and "OWNER-ACCEPTED-DOCUMENT" not in wire(
        rendered
    )


async def test_failed_replacement_cannot_reuse_stopped_agent(lifecycle, monkeypatch):
    db, svc = lifecycle
    session = AgentSession("lifecycle")
    select_provider(
        monkeypatch, db, "openai", [[Say("Initial")], [Say("Fresh recovery")]]
    )
    await send(session, svc, "First")
    old = session.agent
    SettingsService(db).update({"agent_model": "gemini:gemini-2.5-flash"})

    def unavailable(**kwargs):
        raise RuntimeError("synthetic constructor failure")

    monkeypatch.setattr(
        "src.services.conversation_runtime.gemini_provider.GeminiProviderClient",
        unavailable,
    )
    # The normal factory projects startup errors into an unavailable agent, so
    # use a failing start to cover rebuild's asynchronous failure boundary.
    from src.services.conversation_agent import UnavailableConversationAgent

    monkeypatch.setattr(
        UnavailableConversationAgent,
        "start",
        AsyncMock(side_effect=RuntimeError("synthetic start failure")),
    )
    with pytest.raises(RuntimeError, match="synthetic start failure"):
        await send(session, svc, "Replace")
    SettingsService(db).update({"agent_model": "openai:gpt-5-mini"})
    events = await send(session, svc, "Recover")
    assert session.agent is not old
    assert [e["data"].get("text") for e in events if e["event"] == "agent_message"] == [
        "Fresh recovery"
    ]


async def test_provider_default_is_snapshotted_before_stopping_old_agent(
    lifecycle, monkeypatch
):
    db, svc = lifecycle
    session = AgentSession("lifecycle")
    select_provider(monkeypatch, db, "openai", [[Say("Initial")]])
    await send(session, svc, "First")
    old = session.agent
    stop = old.stop

    async def change_default_while_stopping():
        monkeypatch.setenv("OPENAI_MODEL", "later-default")
        await stop()

    monkeypatch.setattr(old, "stop", change_default_while_stopping)
    SettingsService(db).update({"agent_model": "openai:default"})
    monkeypatch.setenv("OPENAI_MODEL", "snapshot-default")
    rendered = build_provider("openai", [[Say("Changed")]])
    selected = []

    def construct(**kwargs):
        selected.append(kwargs["model"])
        return rendered.provider

    monkeypatch.setattr(
        "src.services.conversation_runtime.openai_provider.OpenAIProviderClient",
        construct,
    )
    await send(session, svc, "Switch model")
    assert selected == ["openai:snapshot-default"]


async def test_cli_uses_session_mode_and_reseeds_in_memory_history(
    lifecycle, monkeypatch
):
    from src.cli.runner import InProcessRunner

    db, _svc = lifecycle
    runner = InProcessRunner(interactive_shipping=False)
    await runner.__aenter__()
    session_id = await runner.create_session(interactive=True)
    first = select_provider(monkeypatch, db, "openai", [[Say("CLI first response!")]])
    await collect_cli(runner, session_id, "CLI first request!")
    assert "preview_interactive_shipment" in wire(first)
    assert "ship_command_pipeline" not in wire(first)
    second = select_provider(monkeypatch, db, "gemini", [[Say("CLI second response!")]])
    await collect_cli(runner, session_id, "CLI second request!")
    request = wire(second)
    for text in ("CLI first request!", "CLI first response!", "CLI second request!"):
        assert request.count(text) == 1
    await runner.delete_session(session_id)


async def collect_cli(runner, session_id, text):
    return [event async for event in runner.send_message(session_id, text)]


@pytest.mark.parametrize(
    "operation",
    ["schedule_pickup", "cancel_pickup", "push_document", "delete_document"],
)
async def test_cancelled_trusted_action_persists_unknown_outcome_without_new_authority(
    lifecycle, monkeypatch, operation
):
    import asyncio

    from src.services.conversation_handler import decide_workflow_action
    from src.services.workflow_confirmation import WorkflowConfirmationError

    db, svc = lifecycle
    session = AgentSession("lifecycle")
    started = asyncio.Event()
    gateway = AsyncMock()
    calls = []

    async def accepted(**kwargs):
        calls.append(kwargs)
        started.set()
        await asyncio.Event().wait()

    getattr(gateway, operation).side_effect = accepted
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway", AsyncMock(return_value=gateway)
    )
    token = session.workflow_actions.prepare(
        operation, {"document_id": "OWNER-DOC", "prn": "OWNER-PRN"}, gateway
    )
    task = asyncio.create_task(decide_workflow_action(session, token, "confirm"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    stored = svc.get_session_with_messages("lifecycle")["messages"]
    assert len(stored) == 1
    assert "unconfirmed" in json.dumps(stored)
    with pytest.raises(WorkflowConfirmationError):
        await decide_workflow_action(session, token, "confirm")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "first,second",
    [
        (a, b)
        for a in ("openai", "gemini")
        for b in ("anthropic", "openai", "gemini")
        if a != b
    ],
)
async def test_switch_discards_genuine_private_continuation_and_grants_no_execution(
    lifecycle, monkeypatch, first, second
):
    from src.services.workflow_confirmation import WorkflowConfirmationError
    from tests.services.provider_scenarios import Call, Reason, Think

    db, svc = lifecycle
    gateway = AsyncMock()
    gateway.get_source_info.return_value = {"active": False}
    monkeypatch.setattr(
        "src.orchestrator.agent.tools.data.get_data_gateway",
        AsyncMock(return_value=gateway),
    )
    session = AgentSession("lifecycle")
    private = (
        Reason("PRIVATE-CONTINUATION-CANARY")
        if first == "openai"
        else Think("PRIVATE-CONTINUATION-CANARY", "c2lnbmF0dXJl")
    )
    original = select_provider(
        monkeypatch,
        db,
        first,
        [
            [private, Call("source", "get_source_info", {})],
            [Say("Neutral original answer!")],
        ],
    )
    await send(session, svc, "Neutral original question!")
    assert "PRIVATE-CONTINUATION-CANARY" in wire(original)
    token = session.workflow_actions.prepare(
        "cancel_pickup", {"prn": "OWNER-ONLY"}, gateway
    )
    replacement = select_provider(
        monkeypatch,
        db,
        second,
        [
            [
                Call(
                    "forged", "batch_execute", {"job_id": "untrusted", "approved": True}
                )
            ],
            [Say("Ask the user to confirm.")],
        ],
    )
    await send(session, svc, "Continue with the other provider")
    request = wire(replacement)
    assert (
        "PRIVATE-CONTINUATION-CANARY" not in request and "c2lnbmF0dXJl" not in request
    )
    assert (
        "Neutral original answer!" in request
        and "Neutral original question!" in request
    )
    assert "requires the user to press Confirm on the preview" in request
    with pytest.raises(WorkflowConfirmationError):
        session.workflow_actions.take(token)
    gateway.create_shipment.assert_not_awaited()


async def test_settings_change_during_running_turn_applies_only_after_that_turn(
    lifecycle, monkeypatch
):
    import asyncio

    db, svc = lifecycle
    session = AgentSession("lifecycle")
    first = select_provider(
        monkeypatch, db, "openai", [[Say("Old provider completed")]]
    )
    opened, release = asyncio.Event(), asyncio.Event()
    stream_turn = first.provider.stream_turn

    async def blocked_stream(**kwargs):
        async for event in stream_turn(**kwargs):
            opened.set()
            await release.wait()
            yield event

    monkeypatch.setattr(first.provider, "stream_turn", blocked_stream)
    first_task = asyncio.create_task(send(session, svc, "First request during switch"))
    await opened.wait()
    second = select_provider(
        monkeypatch, db, "gemini", [[Say("New provider completed")]]
    )
    second_task = asyncio.create_task(
        send(session, svc, "Second request during switch")
    )
    await asyncio.sleep(0)
    assert len(first.requests) == 1 and not second.requests
    release.set()
    await asyncio.gather(first_task, second_task)
    assert len(first.requests) == len(second.requests) == 1
    assert "Second request during switch" not in wire(first)
    replacement = wire(second)
    for text in (
        "First request during switch",
        "Old provider completed",
        "Second request during switch",
    ):
        assert replacement.count(text) == 1


async def test_session_removed_during_start_discards_and_stops_new_agent(
    lifecycle, monkeypatch
):
    import asyncio

    from src.services.agent_session_manager import AgentSessionManager
    from src.services.conversation_runtime.runtime_session import (
        ConversationRuntimeSession,
    )
    from tests.services.provider_scenarios import build_provider

    db, svc = lifecycle
    manager = AgentSessionManager()
    session = manager.get_or_create_session("lifecycle")
    agent = ConversationRuntimeSession(
        provider=build_provider("scripted", [[Say("Late startup")]]).provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="lifecycle",
    )
    opened, release = asyncio.Event(), asyncio.Event()
    start = agent.start

    async def blocked_start():
        opened.set()
        await release.wait()
        await start()

    monkeypatch.setattr(agent, "start", blocked_start)
    monkeypatch.setattr(
        "src.services.conversation_handler.create_conversation_agent",
        lambda **kwargs: agent,
    )
    task = asyncio.create_task(send(session, svc, "start this turn"))
    await opened.wait()
    await manager.stop_session_agent("lifecycle")
    manager.remove_session("lifecycle")
    release.set()
    assert await task == []
    assert not agent.is_started
    assert session.agent is None


async def test_cli_queued_ingress_and_context_close_share_session_ownership(
    lifecycle, monkeypatch
):
    import asyncio

    from src.cli.runner import InProcessRunner
    from src.services.data_source_mcp_client import DataSourceInfo

    db, _svc = lifecycle
    runner = await InProcessRunner().__aenter__()
    session_id = await runner.create_session()
    gateway = AsyncMock()
    gateway.get_source_info_typed.side_effect = [
        None,
        DataSourceInfo(source_type="csv", row_count=3),
    ]
    monkeypatch.setattr(
        "src.services.conversation_handler.get_data_gateway",
        AsyncMock(return_value=gateway),
    )
    monkeypatch.setattr("src.services.gateway_provider.shutdown_gateways", AsyncMock())
    rendered = select_provider(
        monkeypatch,
        db,
        "openai",
        [[Say("First CLI answer")], [Say("Second CLI answer")]],
    )
    await asyncio.gather(
        collect_cli(runner, session_id, "Repeated CLI request"),
        collect_cli(runner, session_id, "Repeated CLI request"),
    )
    assert json.dumps(rendered.requests[1]).count("Repeated CLI request") == 2
    agent = runner._session_manager.get_session(session_id).agent
    await runner.__aexit__(None, None, None)
    assert not agent.is_started
    assert runner._session_manager.list_sessions() == []


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_current_ingress_is_included_once_after_secret_projection(
    lifecycle, monkeypatch, kind
):
    db, svc = lifecycle
    rendered = select_provider(monkeypatch, db, kind, [[Say("Understood")]])
    await send(
        AgentSession("lifecycle"),
        svc,
        "CURRENT-AUTHORED-MARKER api_key=sk-secret-canary-123",
    )
    request = wire(rendered)
    assert request.count("CURRENT-AUTHORED-MARKER") == 1
    assert "sk-secret-canary-123" not in request


async def test_unavailable_provider_recovers_when_configuration_becomes_usable(
    lifecycle, monkeypatch
):
    db, svc = lifecycle
    rendered = select_provider(
        monkeypatch, db, "openai", [[Say("Provider is now available")]]
    )
    monkeypatch.delenv("OPENAI_API_KEY")
    session = AgentSession("lifecycle")
    first = await send(session, svc, "Try while key is missing")
    assert any(event["event"] == "error" for event in first)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-recovered-key")
    second = await send(session, svc, "Try again with key present")
    assert any(
        event["event"] == "agent_message"
        and event["data"]["text"] == "Provider is now available"
        for event in second
    )
    assert len(rendered.requests) == 1


async def test_queued_turn_uses_mode_after_prior_turn_switches_to_batch(
    lifecycle, monkeypatch
):
    import asyncio

    db, svc = lifecycle
    session = AgentSession("lifecycle")
    session.interactive_shipping = True
    from src.db.models import ConversationSession

    db.get(ConversationSession, "lifecycle").mode = "interactive"
    db.commit()
    rendered = select_provider(
        monkeypatch, db, "openai", [[Say("Batch selected")], [Say("Still batch")]]
    )
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def source():
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        return None

    gateway = AsyncMock()
    gateway.get_source_info_typed.side_effect = source
    monkeypatch.setattr(
        "src.services.conversation_handler.get_data_gateway",
        AsyncMock(return_value=gateway),
    )
    first = asyncio.create_task(
        send(session, svc, "Ship all orders to customers in CA")
    )
    await entered.wait()
    second = asyncio.create_task(send(session, svc, "What is the batch status?"))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)
    assert session.interactive_shipping is False
    assert "preview_interactive_shipment" not in {
        tool["name"] for tool in rendered.requests[1]["tools"]
    }
    assert "ship_command_pipeline" in {
        tool["name"] for tool in rendered.requests[1]["tools"]
    }


async def test_automatic_batch_mode_survives_persisted_session_recreation(
    lifecycle, monkeypatch
):
    from src.api.routes import conversations as routes
    from src.db.models import ConversationSession
    from src.services.agent_session_manager import AgentSessionManager

    db, svc = lifecycle
    db.get(ConversationSession, "lifecycle").mode = "interactive"
    db.commit()
    session = AgentSession("lifecycle")
    session.interactive_shipping = True
    select_provider(monkeypatch, db, "openai", [[Say("Batch selected")]])
    await send(session, svc, "Ship all orders to customers in CA")
    assert svc.get_session_with_messages("lifecycle")["session"]["mode"] == "batch"
    monkeypatch.setattr(routes, "_session_manager", AgentSessionManager())
    assert not routes._resolve_session("lifecycle").interactive_shipping


@pytest.mark.parametrize("task_cancel", [False, True])
async def test_interrupted_conversation_audit_is_cancelled(
    lifecycle, monkeypatch, task_cancel
):
    import asyncio
    from unittest.mock import MagicMock

    from src.db.models import AgentDecisionRunStatus

    db, svc = lifecycle
    session = AgentSession("lifecycle")
    opened, release = asyncio.Event(), asyncio.Event()

    async def source():
        opened.set()
        await release.wait()
        return None

    gateway = AsyncMock()
    gateway.get_source_info_typed.side_effect = source
    monkeypatch.setattr(
        "src.services.conversation_handler.get_data_gateway",
        AsyncMock(return_value=gateway),
    )
    monkeypatch.setattr(
        "src.services.conversation_handler.DecisionAuditService.start_run",
        lambda **kwargs: "audit-run",
    )
    complete = MagicMock()
    monkeypatch.setattr(
        "src.services.conversation_handler.DecisionAuditService.complete_run", complete
    )
    task = asyncio.create_task(send(session, svc, "Wait for source"))
    await opened.wait()
    if task_cancel:
        task.cancel()
    else:
        session.invalidate_active_turn_generation()
        release.set()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert complete.call_args.kwargs["status"] == AgentDecisionRunStatus.cancelled


async def test_service_interruption_after_delta_suppresses_text_and_persistence(
    lifecycle, monkeypatch
):
    db, svc = lifecycle
    session = AgentSession("lifecycle")
    select_provider(monkeypatch, db, "openai", [[Say("Unpublished completed text")]])
    stream = process_message(session, "Speak")
    assert (await anext(stream))["event"] == "agent_message_delta"
    session.invalidate_active_turn_generation()
    # The service must guard its own suspension even without a transport signal.
    assert [event async for event in stream] == []
    assert svc.get_session_with_messages("lifecycle")["messages"] == []


async def test_unset_model_is_snapshotted_before_stopping_old_agent(
    lifecycle, monkeypatch
):
    db, svc = lifecycle
    session = AgentSession("lifecycle")
    select_provider(monkeypatch, db, "openai", [[Say("Initial")]])
    await send(session, svc, "First")
    old = session.agent
    stop = old.stop
    monkeypatch.setattr(
        "src.services.conversation_handler._resolve_agent_model", lambda: None
    )
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", "auto")

    async def change_configuration_while_stopping():
        monkeypatch.setenv("AGENT_MODEL", "openai:later-model")
        await stop()

    monkeypatch.setattr(old, "stop", change_configuration_while_stopping)
    rendered = build_provider("anthropic", [[Say("Default Anthropic")]])
    selected = []

    def construct(**kwargs):
        selected.append(kwargs["model"])
        return rendered.provider

    monkeypatch.setattr(
        "src.services.conversation_runtime.anthropic_provider.AnthropicProviderClient",
        construct,
    )
    await send(session, svc, "Use the default")
    assert selected == ["anthropic:claude-haiku-4-5-20251001"]
