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


@pytest.mark.parametrize("prefix", ["", "Diagnostic: "])
@pytest.mark.parametrize("container", [lambda obj: obj, lambda obj: [obj]])
def test_encoded_raw_payloads_are_classified_recursively_at_audit_boundaries(
    privacy_db, prefix, container
):
    from src.db.models import EventType, Job
    from src.services.audit_service import AuditService
    from src.services.decision_audit_service import DecisionAuditService

    encoded = prefix + json.dumps(
        container({"rawResponse": {"arbitrary": SECRET}, "count": 2})
    )
    with privacy_db() as db:
        job = Job(name="Privacy", original_command="quote")
        db.add(job)
        db.commit()
        row = AuditService(db).log_error(
            job.id, EventType.error, "Quote failed", {"diagnostic": encoded}
        )
        assert SECRET not in row.details
        assert "count" in row.details
    prepared, _ = DecisionAuditService._prepare_payload({"diagnostic": encoded})
    assert SECRET not in prepared


@pytest.mark.parametrize("split", range(1, 9))
async def test_secrets_split_across_public_text_deltas_never_escape(privacy_db, split):
    from src.services.conversation_runtime.models import (
        ProviderStreamEvent,
        ProviderStreamEventType,
    )

    text = f"Safe intro. api_key={SECRET}"
    prefix = len("Safe intro. ") + split
    obs = await run_scenario(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_DELTA, text=text[:prefix]
                ),
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_DELTA, text=text[prefix:]
                ),
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE, text=text
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ]
        ],
        fresh_agent=True,
    )
    assert SECRET not in json.dumps(obs.events)
    assert SECRET not in json.dumps(obs.persisted_messages)
    assert "Safe intro." in json.dumps(obs.events)


@pytest.mark.parametrize("prefix", ["", "Settings: "])
def test_structured_user_credentials_redacted_without_losing_authored_address(prefix):
    from src.services.conversation_privacy import provider_authored_text

    value = prefix + json.dumps(
        {"credentials": {"arbitrary": SECRET}, "address": "42 User Road"}
    )
    result = provider_authored_text(value)
    assert SECRET not in result and "42 User Road" in result


@pytest.mark.parametrize("terminal", ["incomplete", "provider_error", "oversized"])
async def test_unfinished_or_oversized_text_never_flushes_partial_content(
    privacy_db, terminal
):
    from src.services.conversation_runtime.models import (
        ProviderStreamEvent,
        ProviderStreamEventType,
    )

    partial = f"api_key={SECRET}"
    if terminal == "oversized":
        partial += "x" * 65536
    events = [
        ProviderStreamEvent(type=ProviderStreamEventType.TEXT_DELTA, text=partial)
    ]
    if terminal == "provider_error":
        events.append(
            ProviderStreamEvent(
                type=ProviderStreamEventType.PROVIDER_ERROR, error_message=SECRET
            )
        )
    events.append(ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE))
    obs = await run_scenario(script=[events], fresh_agent=True)
    assert SECRET not in json.dumps(obs.events)
    assert not obs.persisted_messages
    assert "error" in obs.event_names()


async def test_completed_block_keeps_delta_message_order_and_safe_text(privacy_db):
    from src.services.conversation_runtime.models import (
        ProviderStreamEvent,
        ProviderStreamEventType,
    )

    obs = await run_scenario(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_DELTA, text="Hello "
                ),
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_DELTA, text="there"
                ),
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE, text="Hello there"
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ]
        ],
        fresh_agent=True,
    )
    assert obs.events == [
        {"event": "agent_message_delta", "data": {"text": "Hello there"}},
        {"event": "agent_message", "data": {"text": "Hello there"}},
    ]


async def test_cancellation_discards_unpublished_text_block(privacy_db):
    import asyncio

    from src.services.conversation_runtime.fake_provider import FakeProviderClient
    from src.services.conversation_runtime.models import (
        ProviderStreamEvent,
        ProviderStreamEventType,
    )
    from src.services.conversation_runtime.runtime_session import (
        ConversationRuntimeSession,
    )

    started, release = asyncio.Event(), asyncio.Event()

    class PausedProvider(FakeProviderClient):
        async def stream_turn(self, **kwargs):
            yield ProviderStreamEvent(
                type=ProviderStreamEventType.TEXT_DELTA, text=f"api_key={SECRET}"
            )
            started.set()
            await release.wait()
            yield ProviderStreamEvent(
                type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                text=f"api_key={SECRET}",
            )

    runtime = ConversationRuntimeSession(
        provider=PausedProvider(script=[]),
        system_prompt="system",
        interactive_shipping=False,
        session_id="cancel-block",
    )
    await runtime.start()

    async def collect():
        return [event async for event in runtime.process_message_stream("go")]

    task = asyncio.create_task(collect())
    await asyncio.wait_for(started.wait(), 2)
    await runtime.interrupt()
    release.set()
    assert await asyncio.wait_for(task, 2) == []


@pytest.mark.parametrize("prefix", ["", "Diagnostic: "])
def test_incomplete_structured_secret_has_fixed_safe_fallback(prefix):
    from src.services.conversation_privacy import provider_authored_text

    result = provider_authored_text(prefix + '{"credentials": {"unknown": "' + SECRET)
    assert SECRET not in result and "REDACTED" in result


def test_user_credential_objects_do_not_enter_decision_run_storage(
    privacy_db, monkeypatch
):
    from src.services.decision_audit_service import DecisionAuditService

    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "true")
    run = DecisionAuditService.start_run(
        session_id=None,
        user_message="Settings: " + json.dumps({"credentials": {"arbitrary": SECRET}}),
        model="test",
        interactive_shipping=False,
    )
    assert SECRET not in json.dumps(DecisionAuditService.get_run(run))


@pytest.mark.parametrize("kind", ["anthropic", "openai", "gemini"])
@pytest.mark.parametrize("ending", ["normal", "oversized", "error", "cancel"])
async def test_actual_adapter_transport_closes_owned_request(kind, ending, privacy_db):
    import asyncio

    import httpx

    from src.services.conversation_runtime.runtime_session import (
        ConversationRuntimeSession,
    )
    from tests.services import provider_scenarios as protocol

    render, make_client = {
        "anthropic": (protocol._anthropic_body, protocol._anthropic_client),
        "openai": (protocol._openai_body, protocol._openai_client),
        "gemini": (protocol._gemini_body, protocol._gemini_client),
    }[kind]
    closed, waiting = asyncio.Event(), asyncio.Event()
    text = "x" * 65537 if ending == "oversized" else "Safe block"
    body = render([Say(text)])

    class WireStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            if ending in {"error", "cancel"}:
                parts = body.split(b"\n\n")
                cut = next(i for i, part in enumerate(parts) if b"Safe block" in part)
                yield b"\n\n".join(parts[: cut + 1]) + b"\n\n"
                if ending == "error":
                    raise httpx.ReadError(SECRET)
                waiting.set()
                await asyncio.Event().wait()
            else:
                yield body

        async def aclose(self):
            closed.set()

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, stream=WireStream(), headers={"content-type": "text/event-stream"}
            )
        )
    )
    provider = make_client(client)
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="stream-close",
    )
    await runtime.start()
    events = []

    async def collect():
        async for event in runtime.process_message_stream("go"):
            events.append(event)

    task = asyncio.create_task(collect())
    if ending == "cancel":
        await asyncio.wait_for(waiting.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not events
    else:
        await asyncio.wait_for(task, 2)
        assert [e["event"] for e in events] == (
            ["agent_message_delta", "agent_message"]
            if ending == "normal"
            else ["error"]
        )
    await asyncio.wait_for(closed.wait(), 1)
    assert not client.is_closed  # Shared/injected client ownership is preserved.
    assert SECRET not in json.dumps(events)
    await client.aclose()


async def test_gemini_closing_one_request_does_not_close_concurrent_response(
    privacy_db,
):
    import asyncio

    import httpx

    from src.services.conversation_runtime.runtime_session import (
        ConversationRuntimeSession,
    )
    from tests.services import provider_scenarios as protocol

    normal_waiting, release = asyncio.Event(), asyncio.Event()
    closed = {"large": asyncio.Event(), "normal": asyncio.Event()}

    class WireStream(httpx.AsyncByteStream):
        def __init__(self, name):
            self.name = name

        async def __aiter__(self):
            if self.name == "normal":
                normal_waiting.set()
                await release.wait()
            else:
                await normal_waiting.wait()
            yield protocol._gemini_body(
                [Say("x" * 65537 if self.name == "large" else "Still usable")]
            )

        async def aclose(self):
            closed[self.name].set()

    def handle(request):
        name = "large" if "large" in request.content.decode() else "normal"
        return httpx.Response(
            200, stream=WireStream(name), headers={"content-type": "text/event-stream"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    provider = protocol._gemini_client(client)

    async def collect(name):
        runtime = ConversationRuntimeSession(
            provider=provider,
            system_prompt="system",
            interactive_shipping=False,
            session_id=name,
        )
        await runtime.start()
        return [event async for event in runtime.process_message_stream(name)]

    normal = asyncio.create_task(collect("normal"))
    large = asyncio.create_task(collect("large"))
    large_events = await asyncio.wait_for(large, 2)
    assert [e["event"] for e in large_events] == ["error"]
    await asyncio.wait_for(closed["large"].wait(), 1)
    assert not closed["normal"].is_set() and not client.is_closed
    release.set()
    normal_events = await asyncio.wait_for(normal, 2)
    assert normal_events[-1]["data"]["text"] == "Still usable"
    await asyncio.wait_for(closed["normal"].wait(), 1)
    await client.aclose()


@pytest.mark.parametrize(
    "text",
    [
        "[fragile] leave at side door",
        "[normal] Ground service",
        "[top] do not stack",
        "{Building A} receiving",
        "[1ZUSER123456789012]",
        "Recipient {Building A}",
    ],
)
def test_authored_shipping_prose_is_not_misclassified_as_json(text):
    from src.services.conversation_privacy import provider_authored_text
    from src.utils.redaction import project_public_artifact

    assert provider_authored_text(text) == text
    assert project_public_artifact({"name": text})["name"] == text


@pytest.mark.parametrize("prefix", ["Credentials: ", "Request_body = "])
def test_operational_label_before_json_redacts_the_whole_container(prefix):
    from src.services.audit_service import redact_sensitive
    from src.services.conversation_privacy import provider_authored_text

    value = (
        "Useful instruction. "
        + prefix
        + json.dumps({"arbitrary": SECRET})
        + " Continue safely."
    )
    for projected in (provider_authored_text(value), redact_sensitive(value)):
        assert SECRET not in projected
        assert "Useful instruction." in projected and "Continue safely." in projected


@pytest.mark.parametrize(
    "name,args",
    [
        ("track_package", {"tracking_number": "1ZUSER123456789012"}),
        ("get_pickup_status", {}),
        ("rate_pickup", {}),
        ("get_service_center_facilities", {}),
        ("find_locations", {"location_type": "ups"}),
        ("get_landed_cost", {}),
    ],
)
async def test_auxiliary_gateway_failures_never_log_raw_payloads(
    name, args, privacy_db, caplog
):
    gateway = AsyncMock()
    getattr(gateway, name).side_effect = RuntimeError(SECRET)
    rendered = build_provider(
        "scripted", [[Call("aux", name, args)], [Say("Check settings and retry.")]]
    )
    obs = await run_scenario(
        script=[],
        provider=rendered.provider,
        fresh_agent=True,
        interactive=True,
        ups_gateway=gateway,
    )
    getattr(gateway, name).assert_awaited_once()
    assert SECRET not in caplog.text
    assert SECRET not in obs.everything_externally_visible()


def test_audit_retains_only_typed_quote_estimates_not_imported_preview_rows():
    from src.services.audit_service import redact_sensitive

    payload = {
        "preview_rows": [
            {
                "row_number": 1,
                "estimated_cost_cents": 1234,
                "warnings": [
                    "Rate unavailable. Re-preview before confirming this batch."
                ],
                "recipient_name": SECRET,
                "arbitrary": SECRET,
                "rawResponse": {"nested": SECRET},
                "credentials": SECRET,
            }
        ]
    }
    projected = redact_sensitive(payload)
    assert projected["preview_rows"] == [
        {
            "row_number": 1,
            "estimated_cost_cents": 1234,
            "warnings": ["Rate unavailable. Re-preview before confirming this batch."],
        }
    ]
    assert SECRET not in json.dumps(projected)
    assert payload["preview_rows"][0]["recipient_name"] == SECRET


@pytest.mark.parametrize("invalid", [True, -1, "1234"])
def test_invalid_quote_metadata_cannot_arm_confirmation(privacy_db, invalid):
    from src.db.models import Job, JobRow
    from src.services.batch_executor import BatchConfirmationError, confirm_batch
    from src.services.batch_preview import get_priced_preview, save_priced_preview

    with privacy_db() as db:
        job = Job(name="Invalid quote", original_command="ship")
        db.add(job)
        db.flush()
        row = JobRow(
            job_id=job.id, row_number=1, row_checksum="row-one", order_data="{}"
        )
        db.add(row)
        db.flush()
        save_priced_preview(
            db,
            job,
            [row],
            {
                "confirmation_ready": True,
                "total_rows": 1,
                "additional_rows": 0,
                "total_estimated_cost_cents": 1234,
                "preview_rows": [{"row_number": 1, "estimated_cost_cents": invalid}],
            },
        )
        assert job.preview_hash is None
        preview = get_priced_preview(db, job, [row])
        assert preview is None or preview["confirmation_ready"] is False
        with pytest.raises(BatchConfirmationError):
            confirm_batch(job.id, db)
        assert job.status == "pending"
