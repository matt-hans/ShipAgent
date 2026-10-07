"""Authoritative auxiliary previews fail closed at real service boundaries."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from src.orchestrator.agent.tools.core import EventEmitterBridge
from src.orchestrator.agent.tools.pickup import rate_pickup_tool
from src.services.workflow_confirmation import (
    PendingWorkflowActions,
    WorkflowConfirmationError,
    WorkflowExecutionError,
    decide_action,
)
from tests.services.test_auxiliary_workflow_acceptance import PICKUP, AuxiliaryUPS


@pytest.fixture
def bridge():
    result = EventEmitterBridge()
    result.session_id = "owner-session"
    result.events = []
    result.callback = lambda kind, data: result.events.append((kind, data))
    return result


@pytest.mark.parametrize(
    "change",
    [
        {"pickup_date": "20260231"},
        {"pickup_date": True},
        {"ready_time": "1700", "close_time": "0900"},
        {"ready_time": "2500"},
        {"contact_name": ""},
        {"phone_number": None},
        {"extra_billed_option": True},
    ],
)
async def test_invalid_pickup_never_reaches_quote_gateway(change, bridge, monkeypatch):
    acquire = AsyncMock(return_value=AuxiliaryUPS())
    monkeypatch.setattr("src.orchestrator.agent.tools.pickup._get_ups_client", acquire)
    result = await rate_pickup_tool({**PICKUP, **change}, bridge)
    assert result["isError"] is True
    acquire.assert_not_awaited()
    assert bridge.events == []


@pytest.mark.parametrize(
    "quote",
    [
        {"success": False, "grandTotal": "0"},
        {"success": True},
        {"success": True, "grandTotal": "NaN"},
        {"success": True, "grandTotal": "Infinity"},
        {"success": True, "grandTotal": "-1"},
        {"success": True, "grandTotal": True},
    ],
)
async def test_failed_requote_invalidates_older_preview(quote, bridge, monkeypatch):
    gateway = AuxiliaryUPS()
    monkeypatch.setattr(
        "src.orchestrator.agent.tools.pickup._get_ups_client",
        AsyncMock(return_value=gateway),
    )
    await rate_pickup_tool(PICKUP, bridge)
    old = bridge.events[-1][1]["confirmation_token"]
    gateway.rate_pickup = AsyncMock(return_value=quote)
    result = await rate_pickup_tool({**PICKUP, "ready_time": "1000"}, bridge)
    assert result["isError"] is True
    with pytest.raises(WorkflowConfirmationError):
        bridge.workflow_actions.take(old)
    assert len(bridge.events) == 1


async def test_invalid_requote_revokes_older_preview(bridge, monkeypatch):
    gateway = AuxiliaryUPS()
    monkeypatch.setattr(
        "src.orchestrator.agent.tools.pickup._get_ups_client",
        AsyncMock(return_value=gateway),
    )
    await rate_pickup_tool(PICKUP, bridge)
    old = bridge.events[-1][1]["confirmation_token"]
    await rate_pickup_tool({**PICKUP, "ready_time": "bogus"}, bridge)
    with pytest.raises(WorkflowConfirmationError):
        bridge.workflow_actions.take(old)


async def test_payload_is_immutable_and_cancel_consumes_without_carrier(monkeypatch):
    gateway = AuxiliaryUPS()
    actions = PendingWorkflowActions()
    details = deepcopy(PICKUP)
    token = actions.prepare("schedule_pickup", details, gateway)
    details["address_line"] = "Changed after preview"
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway", AsyncMock(return_value=gateway)
    )
    await decide_action(actions, token, "confirm")
    assert gateway.calls == [("schedule_pickup", PICKUP)]
    with pytest.raises(WorkflowConfirmationError):
        await decide_action(actions, token, "confirm")
    token = actions.prepare("schedule_pickup", PICKUP, gateway)
    assert await decide_action(actions, token, "cancel") is None
    with pytest.raises(WorkflowConfirmationError):
        await decide_action(actions, token, "confirm")
    assert len(gateway.calls) == 1


async def test_expiry_session_and_connection_mismatch_fail_closed(monkeypatch):
    gateway = AuxiliaryUPS()
    owner = PendingWorkflowActions()
    other = PendingWorkflowActions()
    token = owner.prepare("schedule_pickup", PICKUP, gateway)
    with pytest.raises(WorkflowConfirmationError):
        await decide_action(other, token, "confirm")
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway",
        AsyncMock(return_value=AuxiliaryUPS()),
    )
    with pytest.raises(WorkflowConfirmationError):
        await decide_action(owner, token, "confirm")
    monkeypatch.setattr("src.services.workflow_confirmation.PREVIEW_TTL_SECONDS", -1)
    token = owner.prepare("schedule_pickup", PICKUP, gateway)
    with pytest.raises(WorkflowConfirmationError):
        await decide_action(owner, token, "confirm")
    assert gateway.calls == []


@pytest.mark.parametrize(
    "failure", [TimeoutError("RAW-SECRET"), RuntimeError("RAW-SECRET")]
)
async def test_ambiguous_outcome_consumes_before_network_and_cannot_retry(
    failure, monkeypatch
):
    gateway = AuxiliaryUPS()
    gateway.schedule_pickup = AsyncMock(side_effect=failure)
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway", AsyncMock(return_value=gateway)
    )
    actions = PendingWorkflowActions()
    token = actions.prepare("schedule_pickup", PICKUP, gateway)
    with pytest.raises(WorkflowExecutionError, match="unconfirmed") as error:
        await decide_action(actions, token, "confirm")
    assert "RAW-SECRET" not in str(error.value)
    with pytest.raises(WorkflowConfirmationError):
        await decide_action(actions, token, "confirm")
    assert gateway.schedule_pickup.await_count == 1


async def test_account_cancellation_resolves_exact_pickup_before_confirmation(
    bridge, monkeypatch
):
    from src.orchestrator.agent.tools.pickup import cancel_pickup_tool

    gateway = AuxiliaryUPS()
    gateway.get_pickup_status = AsyncMock(
        return_value={
            "success": True,
            "pickups": [{"prn": "EXACT-PRN", "pickupDate": "20261008"}],
        }
    )
    monkeypatch.setattr(
        "src.orchestrator.agent.tools.pickup._get_ups_client",
        AsyncMock(return_value=gateway),
    )
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway", AsyncMock(return_value=gateway)
    )
    result = await cancel_pickup_tool({"cancel_by": "account"}, bridge)
    assert result["isError"] is False
    preview = bridge.events[-1][1]
    assert preview["prn"] == "EXACT-PRN"
    await decide_action(
        bridge.workflow_actions, preview["confirmation_token"], "confirm"
    )
    assert gateway.calls == [
        ("cancel_pickup", {"cancel_by": "prn", "prn": "EXACT-PRN"})
    ]


def test_missing_carrier_rate_cannot_be_normalized_into_free_pickup():
    from src.services.ups_mcp_client import UPSMCPClient
    from src.services.workflow_confirmation import valid_pickup_quote

    client = UPSMCPClient("synthetic", "synthetic")
    assert not valid_pickup_quote(client._normalize_rate_pickup_response({}))


@pytest.mark.parametrize("weight", ["NaN", "Infinity", True])
@pytest.mark.parametrize("kind", ("scripted", "anthropic", "openai", "gemini"))
async def test_interactive_weight_is_finite_before_gateway(weight, kind, monkeypatch):
    monkeypatch.setenv("UPS_ACCOUNT_NUMBER", "SYNTHETIC")
    monkeypatch.setattr(
        "src.services.runtime_credentials.resolve_ups_credentials", lambda: None
    )
    from tests.services.conversation_acceptance import run_scenario
    from tests.services.provider_scenarios import Call, Say, build_provider

    rendered = build_provider(
        kind,
        [
            [
                Call(
                    "preview",
                    "preview_interactive_shipment",
                    {
                        "ship_to_name": "Synthetic",
                        "ship_to_address1": "12 Test Road",
                        "ship_to_city": "Oakland",
                        "ship_to_state": "CA",
                        "ship_to_zip": "94612",
                        "service": "ground",
                        "weight": weight,
                    },
                )
            ],
            [Say("Please provide a positive finite weight.")],
        ],
    )
    obs = await run_scenario(script=[], provider=rendered.provider, interactive=True)
    assert obs.ups_gateway_acquisitions == 0
    assert "preview_ready" not in obs.event_names()


async def test_new_user_turn_and_session_removal_revoke_pending_authority(monkeypatch):
    from src.services import attachment_store
    from src.services.agent_session_manager import AgentSessionManager
    from tests.services.conversation_acceptance import run_scenario
    from tests.services.provider_scenarios import Say, build_provider

    manager = AgentSessionManager()
    session = manager.get_or_create_session("new-turn")
    token = session.workflow_actions.prepare("schedule_pickup", PICKUP, AuxiliaryUPS())
    rendered = build_provider("scripted", [[Say("Let's change the plan.")]])
    await run_scenario(
        script=[], provider=rendered.provider, session=session, session_id="new-turn"
    )
    with pytest.raises(WorkflowConfirmationError):
        session.workflow_actions.take(token)
    token = session.workflow_actions.prepare("schedule_pickup", PICKUP, AuxiliaryUPS())
    attachment_store.stage("new-turn", {"file_content_base64": "synthetic"})
    manager.remove_session("new-turn")
    with pytest.raises(WorkflowConfirmationError):
        session.workflow_actions.take(token)
    assert attachment_store.consume("new-turn") is None


@pytest.mark.parametrize("operation", ["push_document", "delete_document"])
async def test_invalid_document_repreview_revokes_previous(
    operation, bridge, monkeypatch
):
    from src.orchestrator.agent.tools.documents import (
        delete_paperless_document_tool,
        push_document_to_shipment_tool,
    )

    handler = (
        push_document_to_shipment_tool
        if operation == "push_document"
        else delete_paperless_document_tool
    )
    monkeypatch.setattr(
        "src.orchestrator.agent.tools.documents._get_ups_client",
        AsyncMock(return_value=AuxiliaryUPS()),
    )
    await handler({"document_id": "DOC", "shipment_identifier": "SHIP"}, bridge)
    token = bridge.events[-1][1]["confirmation_token"]
    await handler({"document_id": ""}, bridge)
    with pytest.raises(WorkflowConfirmationError):
        bridge.workflow_actions.take(token)


async def test_cancelled_inflight_action_cannot_be_retried(monkeypatch):
    import asyncio

    entered = asyncio.Event()
    release = asyncio.Event()
    gateway = AuxiliaryUPS()

    async def call(**args):
        gateway.calls.append(("schedule_pickup", args))
        entered.set()
        await release.wait()

    gateway.schedule_pickup = call
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway", AsyncMock(return_value=gateway)
    )
    actions = PendingWorkflowActions()
    token = actions.prepare("schedule_pickup", PICKUP, gateway)
    task = asyncio.create_task(decide_action(actions, token, "confirm"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(WorkflowConfirmationError):
        await decide_action(actions, token, "confirm")
    assert len(gateway.calls) == 1


async def test_duplicate_concurrent_confirmations_execute_once(monkeypatch):
    import asyncio

    gateway = AuxiliaryUPS()
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway", AsyncMock(return_value=gateway)
    )
    actions = PendingWorkflowActions()
    token = actions.prepare("schedule_pickup", PICKUP, gateway)
    results = await asyncio.gather(
        decide_action(actions, token, "confirm"),
        decide_action(actions, token, "confirm"),
        return_exceptions=True,
    )
    assert len(gateway.calls) == 1
    assert sum(isinstance(result, WorkflowConfirmationError) for result in results) == 1


@pytest.mark.parametrize(
    "normalizer,wrapper",
    [
        ("_normalize_cancel_pickup_response", "PickupCancelResponse"),
        ("_normalize_push_document_response", "PushToImageRepositoryResponse"),
        ("_normalize_delete_document_response", "DeleteResponse"),
        ("_normalize_upload_response", "UploadResponse"),
    ],
)
@pytest.mark.parametrize(
    "shape", [None, {}, [], {"Response": {"ResponseStatus": {"Code": "0"}}}]
)
def test_malformed_acknowledgement_is_never_success(normalizer, wrapper, shape):
    from src.services.ups_mcp_client import UPSMCPClient

    client = UPSMCPClient("synthetic", "synthetic")
    assert getattr(client, normalizer)({wrapper: shape}).get("success") is False


async def test_gateway_acquisition_failure_is_safe_and_consumed(monkeypatch):
    gateway = AuxiliaryUPS()
    actions = PendingWorkflowActions()
    token = actions.prepare("schedule_pickup", PICKUP, gateway)
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway",
        AsyncMock(side_effect=RuntimeError("PRIVATE-ACQUISITION-CANARY")),
    )
    with pytest.raises(WorkflowExecutionError, match="unconfirmed") as error:
        await decide_action(actions, token, "confirm")
    assert "CANARY" not in str(error.value)
    with pytest.raises(WorkflowConfirmationError):
        actions.take(token)
    assert gateway.calls == []


async def test_user_decision_is_audited_without_payload_or_confirmation_handle(
    privacy_db, monkeypatch
):
    from src.db.models import AgentDecisionEvent, AgentDecisionRun
    from src.services.agent_session_manager import AgentSession
    from src.services.conversation_handler import decide_workflow_action

    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "true")
    gateway = AuxiliaryUPS()
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway", AsyncMock(return_value=gateway)
    )
    session = AgentSession("decision-audit")
    token = session.workflow_actions.prepare("schedule_pickup", PICKUP, gateway)
    await decide_workflow_action(session, token, "confirm")
    with privacy_db() as db:
        runs = db.query(AgentDecisionRun).all()
        events = db.query(AgentDecisionEvent).all()
        assert len(runs) == 1
        assert {event.event_name for event in events} >= {
            "workflow.confirmation.received",
            "workflow.confirmation.completed",
        }
        text = str([event.payload_redacted for event in events])
        assert token not in text and PICKUP["address_line"] not in text


@pytest.mark.parametrize("prn", [None, {}, {"raw": "not-an-id"}, [], 123, True, ""])
async def test_schedule_requires_a_real_confirmation_number(prn, monkeypatch):
    gateway = AuxiliaryUPS()
    gateway.schedule_pickup = AsyncMock(return_value={"success": True, "prn": prn})
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway", AsyncMock(return_value=gateway)
    )
    actions = PendingWorkflowActions()
    token = actions.prepare("schedule_pickup", PICKUP, gateway)
    with pytest.raises(WorkflowExecutionError):
        await decide_action(actions, token, "confirm")


@pytest.mark.parametrize("document_id", [123, True, {"unexpected": "body"}, [123]])
def test_upload_cannot_invent_an_identifier_from_malformed_data(document_id):
    from src.services.ups_mcp_client import UPSMCPClient

    client = UPSMCPClient("synthetic", "synthetic")
    result = client._normalize_upload_response(
        {"UploadResponse": {"FormsHistoryDocumentID": {"DocumentID": document_id}}}
    )
    assert result["success"] is False


async def test_decision_endpoint_rejects_wrong_session_and_payload_substitution(
    monkeypatch,
):
    import httpx

    from src.api.main import app
    from src.api.routes import conversations

    gateway = AuxiliaryUPS()
    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "false")
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway", AsyncMock(return_value=gateway)
    )
    monkeypatch.setattr(
        "src.services.conversation_handler._persist_artifact_message", lambda *a: None
    )
    owner = conversations._session_manager.get_or_create_session("endpoint-owner")
    conversations._session_manager.get_or_create_session("endpoint-other")
    token = owner.workflow_actions.prepare("schedule_pickup", PICKUP, gateway)
    body = {"confirmation_token": token, "decision": "confirm"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        wrong = await client.post(
            "/api/v1/conversations/endpoint-other/workflow-confirmation", json=body
        )
        assert wrong.status_code == 409
        changed = await client.post(
            "/api/v1/conversations/endpoint-owner/workflow-confirmation",
            json={**body, "address_line": "SWAPPED"},
        )
        assert changed.status_code == 422
        assert gateway.calls == []
        confirmed = await client.post(
            "/api/v1/conversations/endpoint-owner/workflow-confirmation", json=body
        )
        assert confirmed.status_code == 200
    assert gateway.calls == [("schedule_pickup", PICKUP)]
