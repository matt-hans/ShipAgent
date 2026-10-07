"""Real interactive/auxiliary workflows at the common conversation boundary."""

from copy import deepcopy

import pytest

from tests.services.conversation_acceptance import run_scenario
from tests.services.provider_scenarios import PROVIDERS, Call, Say, build_provider

PICKUP = {
    "pickup_date": "20261008",
    "ready_time": "0900",
    "close_time": "1700",
    "address_line": "12 Synthetic Road",
    "city": "Oakland",
    "state": "CA",
    "postal_code": "94612",
    "country_code": "US",
    "contact_name": "Synthetic Sender",
    "phone_number": "5550100000",
}


class AuxiliaryUPS:
    """Synthetic carrier seam; records side effects without contacting UPS."""

    def __init__(self):
        self.calls = []

    async def rate_pickup(self, **args):
        self.calls.append(("rate_pickup", deepcopy(args)))
        return {
            "success": True,
            "charges": [
                {
                    "chargeCode": "B",
                    "chargeLabel": "Base Charge",
                    "chargeAmount": "7.50",
                }
            ],
            "grandTotal": "7.50",
        }

    async def schedule_pickup(self, **args):
        self.calls.append(("schedule_pickup", deepcopy(args)))
        return {"success": True, "prn": "SYNTHETIC-PRN"}

    async def cancel_pickup(self, **args):
        self.calls.append(("cancel_pickup", deepcopy(args)))
        return {"success": True}

    async def push_document(self, **args):
        self.calls.append(("push_document", deepcopy(args)))
        return {"success": True}

    async def delete_document(self, **args):
        self.calls.append(("delete_document", deepcopy(args)))
        return {"success": True}

    async def upload_document(self, **args):
        self.calls.append(("upload_document", deepcopy(args)))
        return {"success": True, "documentId": "DOC-SYNTHETIC"}


@pytest.fixture(autouse=True)
def quiet_runtime(monkeypatch):
    monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "false")
    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "false")


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_model_confirmation_flags_cannot_schedule_pickup(kind):
    gateway = AuxiliaryUPS()
    rendered = build_provider(
        kind,
        [
            [Call("schedule", "schedule_pickup", {**PICKUP, "confirmed": True})],
            [Say("Use the pickup preview to confirm.")],
        ],
    )
    observation = await run_scenario(
        script=[], provider=rendered.provider, ups_gateway=gateway
    )
    assert gateway.calls == []
    assert "pickup_result" not in observation.event_names()


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_pickup_preview_user_action_executes_exact_payload_once(
    kind, monkeypatch
):
    import httpx

    from src.api.main import app
    from src.api.routes import conversations

    gateway = AuxiliaryUPS()
    session_id = f"pickup-confirm-{kind}"
    session = conversations._session_manager.get_or_create_session(session_id)
    rendered = build_provider(
        kind,
        [
            [Call("rate", "rate_pickup", PICKUP)],
            [Say("Review the pickup preview.")],
        ],
    )
    observation = await run_scenario(
        script=[],
        provider=rendered.provider,
        ups_gateway=gateway,
        session_id=session_id,
        session=session,
    )
    preview = next(
        e["data"] for e in observation.events if e["event"] == "pickup_preview"
    )
    assert gateway.calls == [("rate_pickup", {**PICKUP, "pickup_type": "oncall"})]
    token = preview["confirmation_token"]
    # The model never needs the browser-only confirmation handle.
    from tests.services.test_conversation_privacy_acceptance import serialized_requests

    assert token not in serialized_requests(observation, rendered)
    assert preview["grand_total"] == "7.50"

    async def get_gateway():
        return gateway

    monkeypatch.setattr("src.services.gateway_provider.get_ups_gateway", get_gateway)
    monkeypatch.setattr(
        "src.services.conversation_handler._persist_artifact_message",
        lambda *args: None,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        body = {"confirmation_token": token, "decision": "confirm"}
        response = await client.post(
            f"/api/v1/conversations/{session_id}/workflow-confirmation", json=body
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "completed"
        duplicate = await client.post(
            f"/api/v1/conversations/{session_id}/workflow-confirmation", json=body
        )
        assert duplicate.status_code == 409
    assert gateway.calls[-1] == ("schedule_pickup", PICKUP)
    assert len(gateway.calls) == 2
    event = conversations._get_event_queue(session_id).get_nowait()
    assert event["event"] == "pickup_result"
    assert event["data"]["prn"] == "SYNTHETIC-PRN"
    assert event["data"]["action"] == "scheduled"


@pytest.mark.parametrize("kind", PROVIDERS)
@pytest.mark.parametrize(
    "tool,args,operation,result_event,result_action",
    [
        (
            "cancel_pickup",
            {"cancel_by": "prn", "prn": "SYNTHETIC-PRN", "confirmed": True},
            "cancel_pickup",
            "pickup_result",
            "cancelled",
        ),
        (
            "push_document_to_shipment",
            {"document_id": "DOC-1", "shipment_identifier": "1ZSYNTHETIC"},
            "push_document",
            "paperless_result",
            "pushed",
        ),
        (
            "delete_paperless_document",
            {"document_id": "DOC-1"},
            "delete_document",
            "paperless_result",
            "deleted",
        ),
    ],
)
async def test_auxiliary_mutation_prepares_then_user_confirms(
    kind, tool, args, operation, result_event, result_action, monkeypatch
):
    import httpx

    from src.api.main import app
    from src.api.routes import conversations

    gateway = AuxiliaryUPS()
    session_id = f"{tool}-{kind}"
    session = conversations._session_manager.get_or_create_session(session_id)
    rendered = build_provider(
        kind, [[Call("prepare", tool, args)], [Say("Please review.")]]
    )
    obs = await run_scenario(
        script=[],
        provider=rendered.provider,
        ups_gateway=gateway,
        session_id=session_id,
        session=session,
    )
    assert gateway.calls == []
    preview = next(e["data"] for e in obs.events if "confirmation_token" in e["data"])
    assert preview["session_id"] == session_id
    from tests.services.test_conversation_privacy_acceptance import serialized_requests

    assert preview["confirmation_token"] not in serialized_requests(obs, rendered)

    async def get_gateway():
        return gateway

    monkeypatch.setattr("src.services.gateway_provider.get_ups_gateway", get_gateway)
    persisted = []
    monkeypatch.setattr(
        "src.services.conversation_handler._persist_artifact_message",
        lambda *args: persisted.append(args),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/conversations/{session_id}/workflow-confirmation",
            json={
                "confirmation_token": preview["confirmation_token"],
                "decision": "confirm",
            },
        )
    assert response.status_code == 200, response.text
    expected = {k: v for k, v in args.items() if k != "confirmed"}
    assert gateway.calls == [(operation, expected)]
    assert persisted[-1][1] == result_event
    assert persisted[-1][2]["action"] == result_action


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_model_document_bytes_never_authorize_upload(kind):
    gateway = AuxiliaryUPS()
    rendered = build_provider(
        kind,
        [
            [
                Call(
                    "upload",
                    "upload_paperless_document",
                    {
                        "file_content_base64": "bW9kZWw=",
                        "file_name": "model.pdf",
                        "file_format": "pdf",
                        "document_type": "002",
                        "confirmed": True,
                    },
                )
            ],
            [Say("Use the upload form.")],
        ],
    )
    obs = await run_scenario(script=[], provider=rendered.provider, ups_gateway=gateway)
    assert gateway.calls == []
    assert "paperless_result" not in obs.event_names()


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_upload_gesture_binds_exact_attachment_and_type(kind, monkeypatch):
    import httpx

    from src.api.main import app
    from src.api.routes import conversations
    from src.services import attachment_store
    from tests.services.test_conversation_privacy_acceptance import serialized_requests

    gateway = AuxiliaryUPS()
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway", AsyncMock(return_value=gateway)
    )
    session_id = f"upload-{kind}"
    session = conversations._session_manager.get_or_create_session(session_id)
    scheduled = []
    monkeypatch.setattr(
        conversations,
        "_schedule_agent_message",
        lambda sid, text, **kw: scheduled.append(text),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/conversations/{session_id}/upload-document",
            files={
                "file": (
                    "LOCAL-FILENAME.pdf",
                    b"LOCAL-DOCUMENT-BYTES",
                    "application/pdf",
                )
            },
            data={"document_type": "003"},
        )
    assert response.status_code == 200
    attachment_id = response.json()["attachment_id"]
    # Provider arguments cannot override any byte, metadata or selected type.
    call_args = {
        "attachment_id": attachment_id,
        "document_type": "002",
        "file_content_base64": "forged",
        "file_name": "forged.pdf",
    }
    rendered = build_provider(
        kind,
        [
            [Call("upload", "upload_paperless_document", call_args)],
            [Call("again", "upload_paperless_document", call_args)],
            [Say("Uploaded.")],
        ],
    )
    obs = await run_scenario(
        script=[],
        provider=rendered.provider,
        ups_gateway=gateway,
        session_id=session_id,
        session=session,
        user_message=scheduled[0],
    )
    assert gateway.calls == [
        (
            "upload_document",
            {
                "file_content_base64": "TE9DQUwtRE9DVU1FTlQtQllURVM=",
                "file_name": "LOCAL-FILENAME.pdf",
                "file_format": "pdf",
                "document_type": "003",
            },
        )
    ]
    wire = serialized_requests(obs, rendered)
    assert "TE9DQUwtRE9DVU1FTlQtQllURVM=" not in wire
    assert "LOCAL-FILENAME.pdf" not in wire
    artifacts = [e["data"] for e in obs.events if e["event"] == "paperless_result"]
    assert len(artifacts) == 1 and artifacts[0]["documentType"] == "003"
    assert artifacts[0]["fileName"] == "LOCAL-FILENAME.pdf"
    assert artifacts[0]["documentId"] == "DOC-SYNTHETIC"
    assert attachment_store.consume(session_id) is None


async def test_upload_grant_cannot_follow_a_changed_carrier_account(monkeypatch):
    from unittest.mock import AsyncMock

    import httpx

    from src.api.main import app
    from src.api.routes import conversations

    first, second = AuxiliaryUPS(), AuxiliaryUPS()
    sid = "upload-account-change"
    conversations._session_manager.get_or_create_session(sid)
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway", AsyncMock(return_value=first)
    )
    monkeypatch.setattr(conversations, "_schedule_agent_message", lambda *a, **k: None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/conversations/{sid}/upload-document",
            files={"file": ("test.pdf", b"synthetic")},
            data={"document_type": "002"},
        )
    attachment_id = response.json()["attachment_id"]
    rendered = build_provider(
        "scripted",
        [
            [
                Call(
                    "upload",
                    "upload_paperless_document",
                    {"attachment_id": attachment_id},
                )
            ],
            [Say("Connection changed.")],
        ],
    )
    obs = await run_scenario(
        script=[], provider=rendered.provider, ups_gateway=second, session_id=sid
    )
    assert first.calls == second.calls == []
    assert "paperless_result" not in obs.event_names()


@pytest.mark.parametrize("kind", PROVIDERS)
@pytest.mark.parametrize(
    "name",
    [
        "mcp__ups__upload_paperless_document",
        "mcp__ups__push_document_to_shipment",
        "mcp__ups__delete_paperless_document",
        "mcp__ups__rate_pickup",
    ],
)
async def test_raw_auxiliary_carrier_calls_are_denied_even_if_registered(kind, name):
    calls = []

    async def spy(args, bridge):
        calls.append(args)
        return {"isError": False, "content": []}

    rendered = build_provider(
        kind, [[Call("raw", name, {"confirmed": True})], [Say("Use a workflow.")]]
    )
    await run_scenario(
        script=[], provider=rendered.provider, exposed_dangerous_tools={name: spy}
    )
    assert calls == []


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_upload_to_attach_chain_uses_handle_returned_on_actual_wire(
    kind, monkeypatch
):
    import json
    from unittest.mock import AsyncMock

    import httpx

    from src.api.main import app
    from src.api.routes import conversations
    from tests.services.provider_scenarios import wire_tool_results

    gateway = AuxiliaryUPS()
    sid = f"document-chain-{kind}"
    session = conversations._session_manager.get_or_create_session(sid)
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway", AsyncMock(return_value=gateway)
    )
    monkeypatch.setattr(conversations, "_schedule_agent_message", lambda *a, **k: None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/conversations/{sid}/upload-document",
            files={"file": ("test.pdf", b"synthetic")},
            data={"document_type": "002"},
        )
    attachment_id = response.json()["attachment_id"]
    received = []

    def follow_upload(body):
        if kind == "scripted":
            text = next(
                p.text for m in body["messages"] if m.role == "tool" for p in m.content
            )
        else:
            text = wire_tool_results(kind, body)[-1]["content"]
        payload = json.loads(text)
        if kind == "gemini":
            payload = payload.get("structured_payload", payload)
        assert "document_handle" in payload, (
            "Upload must return a safe actionable handle"
        )
        received.append(payload["document_handle"])
        return [
            Call(
                "attach",
                "push_document_to_shipment",
                {
                    "document_handle": payload["document_handle"],
                    "shipment_identifier": "1ZSYNTHETIC",
                },
            )
        ]

    rendered = build_provider(
        kind,
        [
            [
                Call(
                    "upload",
                    "upload_paperless_document",
                    {"attachment_id": attachment_id},
                )
            ],
            follow_upload,
            [Say("Review attachment.")],
        ],
    )
    obs = await run_scenario(
        script=[],
        provider=rendered.provider,
        ups_gateway=gateway,
        session_id=sid,
        session=session,
    )
    assert len(received) == 1
    assert [
        payload["action"]
        for _, event, payload in obs.persisted_artifacts
        if event == "paperless_result"
    ] == ["uploaded", "push_preview"]
    preview = next(
        e["data"]
        for e in obs.events
        if e["event"] == "paperless_result"
        and e["data"].get("action") == "push_preview"
    )
    assert preview["documentId"] == "DOC-SYNTHETIC"
    assert len(gateway.calls) == 1  # Only the user-approved upload so far.
    monkeypatch.setattr(
        "src.services.conversation_handler._persist_artifact_message", lambda *a: None
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/conversations/{sid}/workflow-confirmation",
            json={
                "confirmation_token": preview["confirmation_token"],
                "decision": "confirm",
            },
        )
    assert response.status_code == 200
    assert gateway.calls[-1] == (
        "push_document",
        {"document_id": "DOC-SYNTHETIC", "shipment_identifier": "1ZSYNTHETIC"},
    )
    from tests.services.test_conversation_privacy_acceptance import serialized_requests

    wire = serialized_requests(obs, rendered)
    assert "DOC-SYNTHETIC" not in wire and "c3ludGhldGlj" not in wire


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_interactive_preview_runs_real_confirmed_execution(
    kind, privacy_db, monkeypatch
):
    import asyncio
    from unittest.mock import AsyncMock

    import httpx

    from src.api.main import app
    from src.api.routes import preview as preview_routes
    from src.db.connection import get_db
    from src.db.models import Job, JobRow
    from tests.services.batch_acceptance_support import SimulatedUPS
    from tests.services.test_batch_confirmation_acceptance import _declared_tools

    gateway = SimulatedUPS()
    monkeypatch.setattr("src.services.batch_executor.UPSMCPClient", gateway)
    data = AsyncMock()
    data.get_source_info.return_value = None
    monkeypatch.setattr(
        "src.services.batch_engine.get_data_gateway", AsyncMock(return_value=data)
    )
    monkeypatch.setattr(
        "src.services.gateway_provider.get_data_gateway", AsyncMock(return_value=data)
    )

    def database():
        with privacy_db() as db:
            yield db

    app.dependency_overrides[get_db] = database
    rendered = build_provider(
        kind,
        [
            [
                Call(
                    "preview",
                    "preview_interactive_shipment",
                    {
                        "ship_to_name": "User Recipient",
                        "ship_to_address1": "42 User Road",
                        "ship_to_city": "Oakland",
                        "ship_to_state": "CA",
                        "ship_to_zip": "94612",
                        "service": "Ground",
                        "weight": 2,
                    },
                )
            ],
            [Say("Review the shipment.")],
        ],
    )
    try:
        obs = await run_scenario(
            script=[], provider=rendered.provider, ups_gateway=gateway, interactive=True
        )
        preview = next(e["data"] for e in obs.events if e["event"] == "preview_ready")
        assert gateway.rate_calls and gateway.create_calls == []
        assert (
            preview["total_rows"] == 1 and preview["total_estimated_cost_cents"] == 1234
        )
        declared = _declared_tools(kind, obs, rendered)
        assert "preview_interactive_shipment" in declared
        assert not (
            {"ship_command_pipeline", "fetch_rows", "get_source_info", "batch_execute"}
            & declared
        )
        assert not any(name.startswith("mcp__ups__") for name in declared)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/api/v1/jobs/{preview['job_id']}/confirm",
                json={"write_back_enabled": False},
            )
            assert response.status_code == 200, response.text
            tasks = [
                t
                for t in preview_routes._batch_tasks
                if isinstance(t, asyncio.Task)
                and t.get_loop() is asyncio.get_running_loop()
            ]
            if tasks:
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
        assert len(gateway.create_calls) == 1
        with privacy_db() as db:
            job = db.query(Job).filter_by(id=preview["job_id"]).one()
            assert job.is_interactive and job.status == "completed"
            row = db.query(JobRow).filter_by(job_id=job.id).one()
            assert row.tracking_number and row.label_path
    finally:
        app.dependency_overrides.pop(get_db, None)
        await preview_routes.shutdown_batch_runtime(timeout_seconds=5)


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_transit_tracking_and_upload_prompt_keep_safe_results_and_artifacts(kind):
    from tests.services.test_conversation_privacy_acceptance import serialized_requests
    from tests.services.test_tool_workflow_acceptance import _results

    gateway = AuxiliaryUPS()

    async def transit(**args):
        gateway.calls.append(("get_time_in_transit", args))
        return {
            "TimeInTransitResponse": {
                "TransitResponse": {
                    "ServiceSummary": [
                        {
                            "Service": {"Code": "03", "Description": "UPS Ground"},
                            "EstimatedArrival": {
                                "Arrival": {"Date": "20261009"},
                                "BusinessDaysInTransit": "2",
                            },
                            "rawResponse": "LOCAL-SECRET",
                        }
                    ]
                }
            }
        }

    async def tracking(**args):
        gateway.calls.append(("track_package", args))
        return {
            "trackResponse": {
                "shipment": [
                    {
                        "package": [
                            {
                                "trackingNumber": "1ZSYNTHETIC",
                                "currentStatus": {
                                    "code": "D",
                                    "description": "Delivered",
                                },
                                "deliveryDate": [{"date": "20261009"}],
                            }
                        ]
                    }
                ]
            },
            "credentials": "LOCAL-SECRET",
        }

    gateway.get_time_in_transit = transit
    gateway.track_package = tracking
    request = {"TimeInTransitRequest": {"ShipFrom": {"PostalCode": "94612"}}}
    rendered = build_provider(
        kind,
        [
            [
                Call("transit", "get_time_in_transit", {"request_body": request}),
                Call("track", "track_package", {"tracking_number": "1ZSYNTHETIC"}),
                Call(
                    "prompt",
                    "request_document_upload",
                    {"suggested_document_type": "003"},
                ),
            ],
            [Say("Results are ready.")],
        ],
    )
    obs = await run_scenario(script=[], provider=rendered.provider, ups_gateway=gateway)
    assert gateway.calls == [
        ("get_time_in_transit", {"request_body": request}),
        ("track_package", {"tracking_number": "1ZSYNTHETIC"}),
    ]
    assert "20261009" in _results(kind, rendered, obs)[0]["content"]
    assert "1ZSYNTHETIC" in _results(kind, rendered, obs)[1]["content"]
    track = next(e["data"] for e in obs.events if e["event"] == "tracking_result")
    assert (
        track["statusDescription"] == "Delivered"
        and track["trackingNumber"] == "1ZSYNTHETIC"
    )
    assert any(
        event == "tracking_result" and payload == track
        for _, event, payload in obs.persisted_artifacts
    )
    assert "paperless_upload_prompt" in obs.event_names()
    assert "LOCAL-SECRET" not in serialized_requests(obs, rendered)
    assert "LOCAL-SECRET" not in obs.everything_externally_visible()
