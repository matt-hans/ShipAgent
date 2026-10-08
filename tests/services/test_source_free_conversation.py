"""Target-owned source-free turns use the canonical runtime without ambient data."""

from unittest.mock import Mock

import pytest

from src.services.agent_session_manager import AgentSession
from src.services.conversation_handler import process_message
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from tests.services.conversation_acceptance import text_turn


async def test_source_free_turn_never_reads_or_writes_ambient_state(monkeypatch):
    from src.services.source_free_conversation import SourceFreeConversationConfig

    ambient = Mock(side_effect=AssertionError("AMBIENT_SOURCE_CANARY"))
    for name in (
        "get_data_gateway",
        "_resolve_agent_model",
        "_get_mru_contacts_for_prompt",
        "_load_prior_conversation",
        "_persist_session_context",
        "_persist_assistant_message",
        "_persist_artifact_message",
        "create_conversation_agent",
    ):
        monkeypatch.setattr(f"src.services.conversation_handler.{name}", ambient)
    for name in (
        "start_run",
        "log_event",
        "update_run_source_signature",
        "complete_run",
    ):
        monkeypatch.setattr(
            f"src.services.decision_audit_service.DecisionAuditService.{name}", ambient
        )
    monkeypatch.setattr("src.db.connection.get_db_context", ambient)
    monkeypatch.setenv("AGENT_MODEL", "AMBIENT_MODEL_CANARY")
    provider = FakeProviderClient(script=[text_turn("I can help plan your shipment.")])
    session = AgentSession(
        "source-free",
        source_free_config=SourceFreeConversationConfig(provider=provider),
    )
    session.add_message(
        "user", "Help me plan a shipment", turn_id="turn-1", queued=True
    )

    events = [
        event
        async for event in process_message(
            session, "Help me plan a shipment", turn_id="turn-1"
        )
    ]

    assert events == [
        {"event": "agent_message", "data": {"text": "I can help plan your shipment."}}
    ]
    assert len(provider.requests) == 1
    assert provider.requests[0]["tools"] == []
    assert "AMBIENT_" not in repr(provider.requests)
    assert ambient.call_count == 0
    assert [message["role"] for message in session.history] == ["user", "assistant"]


@pytest.mark.parametrize(
    "tool_name",
    [
        "save_contact",
        "delete_contact",
        "connect_shopify",
        "connect_amazon",
        "batch_execute",
        "schedule_pickup",
        "cancel_pickup",
        "upload_paperless_document",
        "mcp__ups__create_shipment",
        "get_schema",
        "fetch_rows",
        "invented_read_path",
    ],
)
async def test_invented_tool_is_denied_by_profile_before_dispatch_or_audit(
    monkeypatch, tool_name
):
    from src.services.decision_audit_context import (
        get_decision_run_id,
        reset_decision_run_id,
        set_decision_run_id,
    )
    from src.services.source_free_conversation import SourceFreeConversationConfig
    from tests.services.conversation_acceptance import tool_call_turn

    ambient_audit = Mock(side_effect=AssertionError("AMBIENT_AUDIT_CANARY"))
    monkeypatch.setattr(
        "src.services.decision_audit_service.DecisionAuditService.log_event",
        ambient_audit,
    )
    provider = FakeProviderClient(
        script=[
            tool_call_turn(
                "invented",
                tool_name,
                {
                    "name": "RAW_ARGUMENT_CANARY",
                    "approved": True,
                    "path": "/private/source",
                    "url": "https://example.invalid/source",
                },
            ),
            text_turn("No tool was run."),
        ]
    )
    session = AgentSession(
        "denied", source_free_config=SourceFreeConversationConfig(provider=provider)
    )
    session.add_message("user", "Help plan", turn_id="turn-1", queued=True)
    inherited = set_decision_run_id("OTHER_ACCOUNT_RUN_CANARY")
    try:
        events = [
            event
            async for event in process_message(session, "Help plan", turn_id="turn-1")
        ]
        assert get_decision_run_id() == "OTHER_ACCOUNT_RUN_CANARY"
    finally:
        reset_decision_run_id(inherited)
    results = [
        message
        for message in provider.requests[-1]["messages"]
        if message.role == "tool"
    ]
    assert (
        results[0].content[0].text
        == "This tool is not admitted by the execution profile."
    )
    assert "RAW_ARGUMENT_CANARY" not in repr(events)
    assert ambient_audit.call_count == 0
    assert all(request["tools"] == [] for request in provider.requests)


async def test_cancelling_a_waiter_does_not_interrupt_the_owned_turn():
    import asyncio

    import pytest

    from src.services.source_free_conversation import SourceFreeConversationConfig
    from tests.services.conversation_runtime.test_runtime_lifecycle import (
        OpeningProvider,
    )

    async def collect(session, content, turn):
        return [
            event async for event in process_message(session, content, turn_id=turn)
        ]

    provider = OpeningProvider()
    session = AgentSession(
        "waiter", source_free_config=SourceFreeConversationConfig(provider=provider)
    )
    session.add_message("user", "First", turn_id="first", queued=True)
    active = asyncio.create_task(collect(session, "First", "first"))
    await asyncio.wait_for(provider.opened.wait(), 1)
    session.add_message("user", "Second", turn_id="second", queued=True)
    waiter = asyncio.create_task(collect(session, "Second", "second"))
    await asyncio.sleep(0)
    waiter.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not provider.closed.is_set()
    finally:
        provider.release.set()
        await active


async def test_closing_canonical_stream_restores_context_and_releases_session():
    from src.services.decision_audit_context import (
        get_decision_run_id,
        reset_decision_run_id,
        set_decision_run_id,
    )
    from src.services.source_free_conversation import SourceFreeConversationConfig

    provider = FakeProviderClient(script=[text_turn("Answer.")])
    session = AgentSession(
        "close", source_free_config=SourceFreeConversationConfig(provider=provider)
    )
    session.add_message("user", "Plan", turn_id="turn", queued=True)
    inherited = set_decision_run_id("inherited")
    stream = process_message(session, "Plan", turn_id="turn")
    try:
        assert (await anext(stream))["event"] == "agent_message"
        await stream.aclose()
        assert get_decision_run_id() == "inherited"
        assert not session.lock.locked()
    finally:
        await stream.aclose()
        reset_decision_run_id(inherited)


async def test_rebuild_keeps_accepted_turns_once_and_excludes_future_ingress():
    from src.services.source_free_conversation import SourceFreeConversationConfig

    provider = FakeProviderClient(
        script=[
            text_turn("First answer"),
            text_turn("Second answer"),
            text_turn("Third answer"),
        ]
    )
    session = AgentSession(
        "history", source_free_config=SourceFreeConversationConfig(provider=provider)
    )
    session.add_message("user", "Repeat", turn_id="earlier-unanswered")
    for turn in ("first", "second"):
        session.add_message("user", "Repeat", turn_id=turn, queued=True)
        _ = [event async for event in process_message(session, "Repeat", turn_id=turn)]
    await session.agent.stop()
    session.agent = None
    session.add_message("user", "Repeat", turn_id="third", queued=True)
    session.add_message("user", "FUTURE_INGRESS_CANARY", turn_id="fourth", queued=True)
    _ = [event async for event in process_message(session, "Repeat", turn_id="third")]
    authored = [
        (message.role, "".join(part.text for part in message.content))
        for message in provider.requests[-1]["messages"]
    ]
    assert authored == [
        ("user", "Repeat"),
        ("user", "Repeat"),
        ("assistant", "First answer"),
        ("user", "Repeat"),
        ("assistant", "Second answer"),
        ("user", "Repeat"),
    ]
    assert all(
        message["metadata"]["conversation_turn_state"] == "started"
        for message in session.history
        if message["role"] == "user"
        and message["metadata"]["conversation_turn_id"] in {"first", "second", "third"}
    )


async def test_replaced_agent_is_stopped_and_never_reused_by_restricted_session():
    from src.services.source_free_conversation import SourceFreeConversationConfig

    class ForeignAgent:
        stopped = False
        called = False

        async def stop(self):
            self.stopped = True

        async def process_message_stream(self, _content):
            self.called = True
            yield {"event": "agent_message", "data": {"text": "FOREIGN_SOURCE_CANARY"}}

    provider = FakeProviderClient(
        script=[text_turn("First safe answer"), text_turn("Second safe answer")]
    )
    session = AgentSession(
        "replaced", source_free_config=SourceFreeConversationConfig(provider=provider)
    )
    session.add_message("user", "First", turn_id="first", queued=True)
    _ = [event async for event in process_message(session, "First", turn_id="first")]
    foreign = ForeignAgent()
    session.agent = foreign
    session.add_message("user", "Second", turn_id="second", queued=True)
    events = [
        event async for event in process_message(session, "Second", turn_id="second")
    ]
    assert not foreign.called
    assert foreign.stopped
    assert "FOREIGN_SOURCE_CANARY" not in repr(events)
    assert events == [
        {"event": "agent_message", "data": {"text": "Second safe answer"}}
    ]


async def test_manager_cannot_change_or_omit_a_pinned_execution_profile():
    import pytest

    from src.services.agent_session_manager import AgentSessionManager
    from src.services.source_free_conversation import SourceFreeConversationConfig

    provider = FakeProviderClient(script=[text_turn("Still restricted.")])
    config = SourceFreeConversationConfig(provider=provider)
    manager = AgentSessionManager()
    session = manager.get_or_create_session("pinned", source_free_config=config)
    assert manager.get_or_create_session("pinned") is session
    other_config = SourceFreeConversationConfig(provider=FakeProviderClient(script=[]))
    with pytest.raises(ValueError, match="profile"):
        manager.get_or_create_session("pinned", source_free_config=other_config)
    manager.get_or_create_session("local")
    with pytest.raises(ValueError, match="profile"):
        manager.get_or_create_session("local", source_free_config=config)
    with pytest.raises(AttributeError):
        session.source_free_config = None
    session.interactive_shipping = True
    session.add_message("user", "Plan", turn_id="turn", queued=True)
    events = [
        event
        async for event in process_message(
            manager.get_or_create_session("pinned"), "Plan", turn_id="turn"
        )
    ]
    assert events[-1]["data"]["text"] == "Still restricted."
    assert provider.requests[0]["tools"] == []


async def test_restricted_profile_cannot_enter_ambient_prewarm_or_approval(monkeypatch):
    import pytest

    from src.services.conversation_handler import decide_workflow_action, ensure_agent
    from src.services.source_free_conversation import SourceFreeConversationConfig

    ambient = Mock(side_effect=AssertionError("AMBIENT_ACCESS_CANARY"))
    monkeypatch.setattr(
        "src.services.conversation_handler._resolve_agent_model", ambient
    )
    monkeypatch.setattr(
        "src.services.decision_audit_service.DecisionAuditService.start_run", ambient
    )
    session = AgentSession(
        "alternate",
        source_free_config=SourceFreeConversationConfig(
            provider=FakeProviderClient(script=[])
        ),
    )
    with pytest.raises(ValueError, match="profile"):
        await ensure_agent(session, None)
    with pytest.raises(ValueError, match="profile"):
        await decide_workflow_action(session, "untrusted", "approve")
    assert ambient.call_count == 0


def test_invalid_source_free_profile_cannot_fall_back_to_local():
    import pytest

    with pytest.raises(TypeError, match="profile"):
        AgentSession("invalid", source_free_config={"provider": "untrusted"})


async def test_active_cancellation_closes_provider_and_retains_no_late_answer():
    import asyncio

    from src.services.source_free_conversation import SourceFreeConversationConfig
    from tests.services.conversation_runtime.test_runtime_lifecycle import (
        OpeningProvider,
    )

    provider = OpeningProvider()
    session = AgentSession(
        "active-cancel",
        source_free_config=SourceFreeConversationConfig(provider=provider),
    )
    session.add_message("user", "Plan", turn_id="turn", queued=True)

    async def collect():
        return [
            event async for event in process_message(session, "Plan", turn_id="turn")
        ]

    task = asyncio.create_task(collect())
    await asyncio.wait_for(provider.opened.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.closed.is_set()
    assert not session.lock.locked()
    assert [message["role"] for message in session.history] == ["user"]


async def test_two_restricted_sessions_do_not_share_provider_or_history():
    import asyncio

    from src.services.source_free_conversation import SourceFreeConversationConfig

    providers = [FakeProviderClient(script=[text_turn(f"Reply {n}")]) for n in (1, 2)]
    sessions = [
        AgentSession(
            str(n), source_free_config=SourceFreeConversationConfig(provider=p)
        )
        for n, p in enumerate(providers)
    ]

    async def run(n):
        session = sessions[n]
        content = f"OWNED_TASK_{n}_CANARY"
        session.add_message("user", content, turn_id="same-turn-id", queued=True)
        return [
            event
            async for event in process_message(session, content, turn_id="same-turn-id")
        ]

    await asyncio.gather(run(0), run(1))
    for n, provider in enumerate(providers):
        assert f"OWNED_TASK_{n}_CANARY" in repr(provider.requests)
        assert f"OWNED_TASK_{1 - n}_CANARY" not in repr(provider.requests)
        assert f"OWNED_TASK_{1 - n}_CANARY" not in repr(sessions[n].history)


async def test_tool_admission_does_not_grant_purchase_approval():
    from src.services.conversation_runtime.models import ProviderToolCall
    from src.services.conversation_runtime.policy import RuntimePolicyEngine
    from src.services.policy_decision import PolicyDenialCode

    policy = RuntimePolicyEngine(False, allowed_tool_names=frozenset({"batch_execute"}))
    decision = await policy.check_pre_tool(
        ProviderToolCall(
            call_id="one", tool_name="batch_execute", parsed_input={"approved": True}
        )
    )
    assert not decision.allowed
    assert decision.code == PolicyDenialCode.EXECUTION_REQUIRES_USER_CONFIRMATION


@pytest.mark.parametrize("maximum", [0, 6, True, "3"])
def test_source_free_model_turn_limit_is_explicit_and_bounded(maximum):
    from src.services.source_free_conversation import SourceFreeConversationConfig

    with pytest.raises(ValueError):
        SourceFreeConversationConfig(
            provider=FakeProviderClient(script=[]), max_turns=maximum
        )


async def test_provider_error_never_exposes_raw_detail():
    from src.services.conversation_runtime.models import (
        ProviderStreamEvent,
        ProviderStreamEventType,
    )
    from src.services.source_free_conversation import (
        SOURCE_FREE_ERROR,
        SourceFreeConversationConfig,
    )

    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.PROVIDER_ERROR,
                    error_message="RAW_PROVIDER_CANARY",
                    safe_error_message="ADAPTER_TEXT_CANARY",
                )
            ]
        ]
    )
    session = AgentSession(
        "error", source_free_config=SourceFreeConversationConfig(provider=provider)
    )
    session.add_message("user", "Plan", turn_id="turn", queued=True)
    events = [event async for event in process_message(session, "Plan", turn_id="turn")]
    assert events == [{"event": "error", "data": {"message": SOURCE_FREE_ERROR}}]
    assert "CANARY" not in repr(events)
