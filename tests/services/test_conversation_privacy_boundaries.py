"""Operational secrets are excluded from local public artifacts and audit output."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from tests.services.conversation_acceptance import run_scenario
from tests.services.provider_scenarios import PROVIDERS, Call, Say, build_provider

SECRET = "CANARY-OPERATIONAL-NEVER-PUBLIC"
PRIVATE_FIELDS = {
    "apiKey": SECRET,
    "UPS_ACCOUNT_NUMBER": SECRET,
    "clientSecret": SECRET,
    "Authorization": SECRET,
    "labelData": SECRET,
    "GraphicImage": SECRET,
    "documentBytes": SECRET,
    "rawResponse": {"arbitrary": SECRET},
    "request_body": {"arbitrary": SECRET},
    "resolved_payload": {"arbitrary": SECRET},
    "provider_output_item": {"encrypted_content": SECRET},
    "thoughtSignature": SECRET,
}
OWNER_ADDRESS = "Local Owner Recipient at 88 Private Road"
LABEL_REFERENCE = "/api/v1/labels/opaque-label.pdf"


@pytest.fixture(autouse=True)
def isolation(monkeypatch):
    monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "false")
    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "false")


def artifact_payload():
    return {
        "job_id": "job-1",
        "ship_to": {"name": OWNER_ADDRESS},
        "label_url": LABEL_REFERENCE,
        "total_rows": 1,
        "nested": [{**PRIVATE_FIELDS}],
    }


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_artifact_and_tool_call_projections_keep_owner_fields_only(
    kind, privacy_db
):
    async def produce(_args, bridge):
        bridge.emit("preview_ready", artifact_payload())
        return {
            "success": True,
            "rows": [{"recipient_name": OWNER_ADDRESS}],
            **PRIVATE_FIELDS,
        }

    rendered = build_provider(
        kind,
        [
            [
                Call(
                    "preview",
                    "preview_interactive_shipment",
                    {
                        "service": "Ground",
                        "weight": 2,
                        "command": "ship",
                        "credentials": SECRET,
                    },
                )
            ],
            [Say("Review the preview.")],
        ],
    )
    obs = await run_scenario(
        script=[],
        provider=rendered.provider,
        fresh_agent=True,
        interactive=True,
        spy_handlers={"preview_interactive_shipment": produce},
    )
    public = json.dumps({"events": obs.events, "artifacts": obs.persisted_artifacts})
    assert SECRET not in public
    assert OWNER_ADDRESS in public and LABEL_REFERENCE in public
    assert obs.persisted_artifacts


def test_artifact_storage_and_legacy_export_apply_own_projection(privacy_db):
    from src.db.models import ConversationMessage
    from src.services.conversation_persistence_service import (
        ConversationPersistenceService,
    )

    with privacy_db() as db:
        service = ConversationPersistenceService(db)
        service.create_session("privacy")
        message = service.save_message(
            "privacy", "assistant", "", "system_artifact", artifact_payload()
        )
        assert SECRET not in message.metadata_json
        assert (
            OWNER_ADDRESS in message.metadata_json
            and LABEL_REFERENCE in message.metadata_json
        )
        # Simulate metadata stored by an older version, bypassing today's writer.
        message.metadata_json = json.dumps(artifact_payload())
        db.commit()
        assert SECRET not in json.dumps(service.export_session_json("privacy"))
        assert OWNER_ADDRESS in json.dumps(service.export_session_json("privacy"))
        assert db.query(ConversationMessage).count() == 1


def test_decision_and_job_audit_store_and_export_exclude_raw_fields(
    privacy_db, monkeypatch, tmp_path
):
    from src.db.models import AgentDecisionEvent, Job
    from src.services.audit_service import AuditService
    from src.services.decision_audit_service import DecisionAuditService

    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "true")
    monkeypatch.setenv("AGENT_AUDIT_JSONL_PATH", str(tmp_path / "audit.jsonl"))
    run = DecisionAuditService.start_run(
        session_id=None,
        user_message="Ship by Ground",
        model="test",
        interactive_shipping=False,
    )
    assert run
    DecisionAuditService.log_event(
        run_id=run,
        phase="tool_call",
        event_name="test",
        actor="tool",
        payload={"count": 3, **PRIVATE_FIELDS},
    )
    with privacy_db() as db:
        entry = db.query(AgentDecisionEvent).one()
        assert SECRET not in entry.payload_redacted
        assert json.loads(entry.payload_redacted)["count"] == 3
        job = Job(name="Privacy", original_command="Ship by Ground")
        db.add(job)
        db.commit()
        audit = AuditService(db)
        audit.log_api_call(
            job.id,
            "/shipments",
            "POST",
            {"arbitrary": SECRET},
            {"arbitrary": SECRET, **PRIVATE_FIELDS},
            200,
        )
        assert SECRET not in audit.export_logs_text(job.id)
        assert "200" in audit.export_logs_text(job.id)


@pytest.mark.parametrize(
    "failure",
    [
        "source",
        "history",
        "contacts",
        "audit",
        "rate",
        "contact_lookup",
        "preview_rate",
    ],
)
async def test_actual_boundary_failures_do_not_log_exception_payload(
    failure, privacy_db, monkeypatch, caplog
):
    from src.services import conversation_handler
    from tests.services.batch_acceptance_support import SimulatedUPS

    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "false")
    gateway = SimulatedUPS()
    if failure in {"rate", "preview_rate"}:
        gateway.get_rate = AsyncMock(side_effect=RuntimeError(SECRET))
    if failure == "contact_lookup":
        monkeypatch.setattr(
            "src.services.contact_service.ContactService.get_by_handle",
            lambda *_args: (_ for _ in ()).throw(RuntimeError(SECRET)),
        )
    if failure == "source":
        # This method is called by the service before ensure_agent.
        from src.services.agent_session_manager import AgentSession

        session = AgentSession(session_id="privacy")
        data = AsyncMock()
        data.get_source_info_typed.side_effect = RuntimeError(SECRET)
        monkeypatch.setattr(
            conversation_handler, "get_data_gateway", AsyncMock(return_value=data)
        )
        monkeypatch.setattr(
            conversation_handler,
            "ensure_agent",
            AsyncMock(side_effect=RuntimeError("safe stop")),
        )
        with pytest.raises(RuntimeError, match="safe stop"):
            async for _event in conversation_handler.process_message(session, "go"):
                pass
    elif failure in {"history", "contacts", "audit"}:
        from contextlib import contextmanager

        @contextmanager
        def broken_db():
            raise RuntimeError(SECRET)
            yield

        if failure == "audit":
            monkeypatch.setenv("AGENT_AUDIT_ENABLED", "true")
            monkeypatch.setattr(
                "src.services.decision_audit_service.get_db_context", broken_db
            )
            from src.services.decision_audit_service import DecisionAuditService

            DecisionAuditService.start_run(
                session_id=None,
                user_message="go",
                model="test",
                interactive_shipping=False,
            )
        else:
            monkeypatch.setattr("src.db.connection.get_db_context", broken_db)
            if failure == "history":
                conversation_handler._load_prior_conversation("privacy")
            else:
                conversation_handler._get_mru_contacts_for_prompt()
    else:
        call = Call("call", "rate_shipment", {"request_body": {"Service": "03"}})
        if failure == "contact_lookup":
            call = Call("call", "resolve_contact", {"handle": "saved-person"})
        elif failure == "preview_rate":
            call = Call(
                "call",
                "preview_interactive_shipment",
                {
                    "ship_to_handle": "saved-person",
                    "service": "Ground",
                    "weight": 2,
                    "command": "ship",
                },
            )
        rendered = build_provider(
            "scripted", [[call], [Say("Check settings and retry.")]]
        )
        obs = await run_scenario(
            script=[],
            provider=rendered.provider,
            fresh_agent=True,
            interactive=True,
            ups_gateway=gateway,
        )
        assert SECRET not in obs.everything_externally_visible()
    assert SECRET not in caplog.text


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_local_handler_enrichment_cannot_mutate_provider_history(
    kind, privacy_db
):
    from tests.services.test_conversation_privacy_acceptance import serialized_requests

    async def enrich(args, _bridge):
        args["nested"]["credentials"] = SECRET
        args["nested"]["address"] = OWNER_ADDRESS
        return {"success": True, **PRIVATE_FIELDS}

    rendered = build_provider(
        kind,
        [
            [
                Call(
                    "local",
                    "get_job_status",
                    {
                        "job_id": "job-1",
                        "nested": {"status": "requested"},
                    },
                )
            ],
            [Say("Status checked.")],
        ],
    )
    obs = await run_scenario(
        script=[],
        provider=rendered.provider,
        fresh_agent=True,
        spy_handlers={"get_job_status": enrich},
    )
    wire = serialized_requests(obs, rendered)
    assert SECRET not in wire
    assert OWNER_ADDRESS not in wire


def test_legacy_audit_reads_reproject_without_rewriting_history(
    privacy_db, monkeypatch
):
    from src.db.models import AgentDecisionEvent, AgentDecisionRun, AuditLog, Job
    from src.services.audit_service import AuditService
    from src.services.decision_audit_service import DecisionAuditService

    with privacy_db() as db:
        run = AgentDecisionRun(
            user_message_hash="hash",
            user_message_redacted="ship",
            status="completed",
            interactive_shipping=False,
        )
        db.add(run)
        db.flush()
        entry = AgentDecisionEvent(
            run_id=run.id,
            seq=1,
            phase="tool_call",
            actor="tool",
            event_name="legacy",
            payload_hash="hash",
            event_hash="hash",
            payload_redacted=json.dumps(PRIVATE_FIELDS),
        )
        job = Job(name="Legacy", original_command="ship")
        db.add_all([entry, job])
        db.flush()
        log = AuditLog(
            job_id=job.id,
            level="INFO",
            event_type="api_call",
            message="legacy",
            details=json.dumps({"request": {"arbitrary": SECRET}}),
        )
        db.add(log)
        db.commit()
        assert SECRET not in json.dumps(
            DecisionAuditService.export_events(run_id=run.id)
        )
        assert SECRET not in AuditService(db).export_logs_text(job.id)
        assert SECRET in entry.payload_redacted  # Read projection is not a migration


def test_legacy_job_log_api_shape_redacts_details():
    from types import SimpleNamespace

    from src.api.routes.logs import _parse_log_details

    log = SimpleNamespace(
        details=json.dumps({"response": {"arbitrary": SECRET}, **PRIVATE_FIELDS})
    )
    assert SECRET not in json.dumps(_parse_log_details(log))


def test_artifact_text_write_and_legacy_export_remove_labeled_secrets(privacy_db):
    from src.services.conversation_persistence_service import (
        ConversationPersistenceService,
    )

    with privacy_db() as db:
        service = ConversationPersistenceService(db)
        service.create_session("artifact-text")
        row = service.save_message(
            "artifact-text",
            "assistant",
            f"api_key={SECRET} Preview ready",
            "system_artifact",
            {"action": "preview_ready"},
        )
        assert SECRET not in row.content and "Preview ready" in row.content
        row.content = json.dumps(
            {"rawResponse": {"arbitrary": SECRET}, "status": "ready"}
        )
        db.commit()
        assert SECRET not in json.dumps(service.export_session_json("artifact-text"))


@pytest.mark.parametrize(
    "failure",
    [
        "transport",
        "mutating_retry",
        "ELICITATION_INVALID_RESPONSE",
        "STRUCTURAL_FIELDS_REQUIRED",
    ],
)
async def test_real_ups_client_logs_no_transport_or_preflight_payload(
    failure, monkeypatch, caplog
):
    from unittest.mock import MagicMock

    from src.services.mcp_client import MCPToolError
    from src.services.ups_mcp_client import UPSMCPClient

    caplog.set_level("DEBUG", logger="src.services.ups_mcp_client")
    client = UPSMCPClient(client_id="test", client_secret="test", environment="test")
    transport = MagicMock(is_connected=True)
    transport.connect = AsyncMock()
    transport.disconnect = AsyncMock(side_effect=RuntimeError(SECRET))
    transport.call_tool = AsyncMock()
    client._mcp = transport
    if failure == "transport":
        await client._recover_transport(
            "get_rate", RuntimeError(SECRET), client._connection_generation
        )
    elif failure == "mutating_retry":
        transport.call_tool.side_effect = [
            MCPToolError(
                "create_shipment",
                json.dumps(
                    {
                        "status_code": 503,
                        "message": "no healthy upstream",
                        "details": {"raw": SECRET},
                    }
                ),
            ),
            {"ok": True},
        ]
        monkeypatch.setattr("src.services.ups_mcp_client.asyncio.sleep", AsyncMock())
        assert await client._call("create_shipment", {}) == {"ok": True}
    else:
        client._translate_error(
            MCPToolError(
                "create_shipment", json.dumps({"code": failure, "message": SECRET})
            )
        )
    assert SECRET not in caplog.text


async def test_real_mcp_retry_logs_and_audit_do_not_record_raw_error(
    privacy_db, monkeypatch, caplog
):
    from mcp.types import CallToolResult, TextContent

    from mcp import StdioServerParameters
    from src.services.decision_audit_context import (
        reset_decision_run_id,
        set_decision_run_id,
    )
    from src.services.decision_audit_service import DecisionAuditService
    from src.services.mcp_client import MCPClient

    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "true")
    run = DecisionAuditService.start_run(
        session_id=None, user_message="quote", model="test", interactive_shipping=False
    )
    token = set_decision_run_id(run)
    client = MCPClient(
        StdioServerParameters(command="synthetic"), max_retries=1, base_delay=0
    )
    client._session = AsyncMock()
    client._session.call_tool.side_effect = [
        CallToolResult(
            isError=True, content=[TextContent(type="text", text=f"503 {SECRET}")]
        ),
        CallToolResult(content=[TextContent(type="text", text='{"ok": true}')]),
    ]
    try:
        assert await client.call_tool("get_rate", {}) == {"ok": True}
        assert SECRET not in caplog.text
        assert SECRET not in json.dumps(DecisionAuditService.export_events(run_id=run))
    finally:
        reset_decision_run_id(token)
