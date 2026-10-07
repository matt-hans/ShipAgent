"""Acceptance: imported batches are previewed, confirmed and executed once.

One provider-neutral script is rendered onto the scripted fake and the real
Anthropic, OpenAI and Gemini adapters over mocked transports, then driven
through ``conversation_handler.process_message`` with the real catalog, policy
gate, dispatcher, ``ship_command_pipeline`` handler, ``BatchEngine`` and
``/jobs/{id}/confirm`` route. Only the data-source and UPS process boundaries
are simulated (``tests/services/batch_acceptance_support``): the imported CSV
goes through the real Data Source MCP tool functions and every shipment
purchase is counted at the simulated UPS gateway.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.api.main import app
from src.api.routes import preview as preview_routes
from src.db.connection import get_db
from src.db.models import Base, Job, JobRow
from src.orchestrator.models.filter_spec import (
    FilterCondition,
    FilterGroup,
    FilterOperator,
    ResolutionStatus,
    ResolvedFilterSpec,
    TypedLiteral,
)
from src.services.decision_audit_service import DecisionAuditService
from tests.services.batch_acceptance_support import (
    CANARY_PREFIX,
    IMPORTED_ORDERS_CSV,
    SHIPPER_ENV,
    ImportedCsvSource,
    SimulatedUPS,
    hard_rejection,
)
from tests.services.conversation_acceptance import Observation, run_scenario
from tests.services.provider_scenarios import (
    ID_PROVIDERS,
    PROVIDERS,
    Call,
    Rendered,
    Say,
    build_provider,
    wire_tool_results,
)

RATE_CENTS = 1234


@pytest.fixture(autouse=True)
def _isolated_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[None]:
    monkeypatch.setenv("SHIPAGENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("UPS_LABELS_OUTPUT_DIR", str(tmp_path / "labels"))
    monkeypatch.setenv("SHIPAGENT_KEYRING_DISABLED", "1")
    monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "false")
    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "false")
    monkeypatch.setenv("FILTER_TOKEN_SECRET", "batch-acceptance-filter-secret-32ch")
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)
    for key, value in SHIPPER_ENV.items():
        monkeypatch.setenv(key, value)
    yield


@pytest.fixture
def session_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'acceptance.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def _get_db() -> Iterator[Session]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    with patch("src.db.connection.SessionLocal", factory):
        yield factory
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.fixture
async def source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[ImportedCsvSource]:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(IMPORTED_ORDERS_CSV)
    gateway = ImportedCsvSource()
    await gateway.import_csv_file(csv_path)
    for target in (
        "src.services.gateway_provider.get_data_gateway",
        "src.services.batch_engine.get_data_gateway",
    ):
        monkeypatch.setattr(target, AsyncMock(return_value=gateway))
    try:
        yield gateway
    finally:
        await preview_routes.shutdown_batch_runtime(timeout_seconds=5)
        gateway.close()


@pytest.fixture
def ups() -> Iterator[SimulatedUPS]:
    simulated = SimulatedUPS(rate=f"{RATE_CENTS / 100:.2f}")
    with patch("src.services.batch_executor.UPSMCPClient", simulated):
        yield simulated


@pytest.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client
    await preview_routes.shutdown_batch_runtime(timeout_seconds=5)


# ---- helpers ----------------------------------------------------------------


async def _state_filter(source: ImportedCsvSource, state: str) -> dict[str, Any]:
    info = await source.get_source_info()
    assert info is not None
    return ResolvedFilterSpec(
        status=ResolutionStatus.RESOLVED,
        root=FilterGroup(
            logic="AND",
            conditions=[
                FilterCondition(
                    column="ship_to_state",
                    operator=FilterOperator.eq,
                    operands=[TypedLiteral(type="string", value=state)],
                )
            ],
        ),
        explanation=f"ship_to_state equals {state}",
        schema_signature=info["signature"],
        canonical_dict_version="1.0",
    ).model_dump()


async def _preview_in_conversation(
    kind: str,
    source: ImportedCsvSource,
    ups: SimulatedUPS,
    *,
    args: dict[str, Any] | None = None,
    extra_turns: list[list[Any]] | None = None,
) -> tuple[Observation, Rendered]:
    call_args = args or {"command": "Ship all orders", "all_rows": True}
    rendered = build_provider(
        kind,
        [
            [Call("call_preview", "ship_command_pipeline", call_args)],
            [Say("Preview ready.")],
            *(extra_turns or []),
        ],
    )
    obs = await run_scenario(
        script=[],
        provider=rendered.provider,
        ups_gateway=ups,
        data_gateway=source,
    )
    return obs, rendered


def _preview_ready(obs: Observation) -> dict[str, Any]:
    ready = [event["data"] for event in obs.events if event["event"] == "preview_ready"]
    assert len(ready) == 1, obs.event_names()
    return ready[0]


def _jobs(factory: sessionmaker[Session]) -> list[Job]:
    with factory() as db:
        jobs = db.query(Job).order_by(Job.created_at).all()
        for job in jobs:
            db.expunge(job)
        return jobs


def _rows(factory: sessionmaker[Session], job_id: str) -> list[JobRow]:
    with factory() as db:
        rows = (
            db.query(JobRow)
            .filter(JobRow.job_id == job_id)
            .order_by(JobRow.row_number)
            .all()
        )
        for row in rows:
            db.expunge(row)
        return rows


def _declared_tools(kind: str, obs: Observation, rendered: Rendered) -> set[str]:
    if kind == "scripted":
        return {tool.name for tool in obs.provider_requests[0]["tools"]}
    tools = rendered.requests[0]["tools"]
    if kind == "gemini":
        return {
            d["name"] for tool in tools for d in tool.get("functionDeclarations", [])
        }
    return {tool["name"] for tool in tools}


def _results(kind: str, rendered: Rendered, obs: Observation) -> list[dict[str, Any]]:
    if kind == "scripted":
        return [
            {"key": r["call_id"], "content": r["content"], "is_error": r["is_error"]}
            for r in obs.tool_results_seen_by_provider()
        ]
    return wire_tool_results(kind, rendered.requests[-1])


async def _confirm(api: httpx.AsyncClient, job_id: str, **body: Any) -> httpx.Response:
    return await api.post(
        f"/api/v1/jobs/{job_id}/confirm",
        json={"write_back_enabled": False, **body},
    )


async def _drain_batches() -> None:
    # The set is process-global; other tests may leave non-task entries in it.
    loop = asyncio.get_running_loop()
    tasks = [
        t
        for t in preview_routes._batch_tasks
        if isinstance(t, asyncio.Task) and t.get_loop() is loop
    ]
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)


async def _progress(api: httpx.AsyncClient, job_id: str) -> dict[str, Any]:
    response = await api.get(f"/api/v1/jobs/{job_id}/progress")
    assert response.status_code == 200
    return response.json()


async def test_confirmed_execution_keeps_source_gateway_offline(
    source: ImportedCsvSource,
    ups: SimulatedUPS,
    api: httpx.AsyncClient,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The source fixture must outlive the conversation and its background work."""

    def forbidden_gateway() -> None:
        raise AssertionError("Acceptance escaped its simulated source gateway")

    monkeypatch.setattr(
        "src.services.gateway_provider.DataSourceMCPClient", forbidden_gateway
    )
    monkeypatch.setattr("src.services.gateway_provider._data_gateway", None)
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    assert (await _confirm(api, job_id)).status_code == 200
    await asyncio.wait_for(_drain_batches(), timeout=5)
    assert len(ups.create_calls) == 4
    assert _jobs(session_factory)[0].status == "completed"


# ---- preview through the conversation ---------------------------------------


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_imported_batch_preview_artifact_and_no_purchase(
    kind: str,
    source: ImportedCsvSource,
    ups: SimulatedUPS,
    session_factory: sessionmaker[Session],
) -> None:
    obs, rendered = await _preview_in_conversation(kind, source, ups)

    ready = _preview_ready(obs)
    jobs = _jobs(session_factory)
    assert [job.status for job in jobs] == ["pending"]
    assert jobs[0].preview_hash
    # Keys the frontend ``BatchPreview`` type (job.types.ts) requires.
    assert {
        "job_id",
        "total_rows",
        "preview_rows",
        "additional_rows",
        "total_estimated_cost_cents",
        "rows_with_warnings",
    } <= set(ready)
    assert ready["job_id"] == jobs[0].id
    assert ready["total_rows"] == 4
    assert ready["total_estimated_cost_cents"] == 4 * RATE_CENTS
    assert [r["row_number"] for r in ready["preview_rows"]] == [1, 2, 3, 4]
    # The same artifact is persisted for history/resume.
    assert [(k, d["job_id"]) for _s, k, d in obs.persisted_artifacts] == [
        ("preview_ready", jobs[0].id)
    ]
    assert [r.status for r in _rows(session_factory, jobs[0].id)] == ["pending"] * 4
    # Previewing rates rows but never purchases.
    assert len(ups.rate_calls) == 4
    assert ups.create_calls == []
    # The model gets a success result, never imported row values.
    (result,) = _results(kind, rendered, obs)
    assert not result.get("is_error")
    assert CANARY_PREFIX not in result["content"]
    assert CANARY_PREFIX not in json.dumps(rendered.requests)


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_batch_mode_exposes_batch_tools_and_not_interactive_ones(
    kind: str,
    source: ImportedCsvSource,
    ups: SimulatedUPS,
    session_factory: sessionmaker[Session],
) -> None:
    obs, rendered = await _preview_in_conversation(kind, source, ups)

    declared = _declared_tools(kind, obs, rendered)
    assert {"ship_command_pipeline", "resolve_filter_intent", "fetch_rows"} <= declared
    assert "preview_interactive_shipment" not in declared
    assert not any(name.startswith("mcp__ups__") for name in declared)


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_deterministic_selection_previews_only_matching_source_rows(
    kind: str,
    source: ImportedCsvSource,
    ups: SimulatedUPS,
    session_factory: sessionmaker[Session],
) -> None:
    spec = await _state_filter(source, "CA")
    args = {"command": "Ship California orders", "filter_spec": spec}

    first, _ = await _preview_in_conversation(kind, source, ups, args=args)
    second, _ = await _preview_in_conversation(kind, source, ups, args=args)

    first_ready, second_ready = _preview_ready(first), _preview_ready(second)
    for ready in (first_ready, second_ready):
        assert ready["total_rows"] == 3
        assert [r["row_number"] for r in ready["preview_rows"]] == [1, 2, 4]
        assert ready["total_estimated_cost_cents"] == 3 * RATE_CENTS
    # Same filter -> identical compiled selection, separate preview jobs.
    assert (
        first_ready["filter_audit"]["compiled_hash"]
        == second_ready["filter_audit"]["compiled_hash"]
    )
    assert first_ready["job_id"] != second_ready["job_id"]
    assert ups.create_calls == []


# ---- execution requires explicit confirmation --------------------------------


@pytest.mark.parametrize("kind", PROVIDERS)
@pytest.mark.parametrize("approved", [True, False])
async def test_model_cannot_execute_a_previewed_batch(
    kind: str,
    approved: bool,
    source: ImportedCsvSource,
    ups: SimulatedUPS,
    session_factory: sessionmaker[Session],
) -> None:
    """``approved=true`` from the model is not the user's Confirm gesture."""
    # Preview first (own conversation), then a second conversation whose model
    # tries to execute that job directly.
    preview_obs, _ = await _preview_in_conversation(kind, source, ups)
    job_id = _preview_ready(preview_obs)["job_id"]

    attempt = build_provider(
        kind,
        [
            [
                Call(
                    "call_exec",
                    "batch_execute",
                    {"job_id": job_id, "approved": approved},
                )
            ],
            [Say("Executed.")],
        ],
    )
    obs = await run_scenario(
        script=[], provider=attempt.provider, ups_gateway=ups, data_gateway=source
    )

    assert ups.create_calls == []
    assert [job.status for job in _jobs(session_factory)] == ["pending"]
    assert [r.status for r in _rows(session_factory, job_id)] == ["pending"] * 4
    (result,) = _results(kind, attempt, obs)
    assert "Confirm" in result["content"]


async def test_confirm_requires_a_preview_and_buys_nothing(
    api: httpx.AsyncClient,
    ups: SimulatedUPS,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        job = Job(name="never previewed", original_command="ship all", status="pending")
        db.add(job)
        db.commit()
        job_id = job.id

    response = await _confirm(api, job_id)
    await _drain_batches()

    assert response.status_code == 400
    assert "previewed" in response.json()["detail"]
    assert ups.create_calls == []
    assert [job.status for job in _jobs(session_factory)] == ["pending"]


# ---- confirmed execution: progress, results, no duplicates -------------------


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_confirmed_batch_executes_once_with_accurate_progress_and_results(
    kind: str,
    source: ImportedCsvSource,
    ups: SimulatedUPS,
    api: httpx.AsyncClient,
    session_factory: sessionmaker[Session],
) -> None:
    obs, _ = await _preview_in_conversation(kind, source, ups)
    ready = _preview_ready(obs)
    job_id = ready["job_id"]
    assert ups.create_calls == []

    # REST preserves the quoted estimate and deterministic row identity.
    rest = (await api.get(f"/api/v1/jobs/{job_id}/preview")).json()
    assert rest["total_estimated_cost_cents"] == ready["total_estimated_cost_cents"]
    assert rest["confirmation_ready"] is True
    assert rest["job_id"] == job_id
    assert rest["total_rows"] == ready["total_rows"]
    assert [r["row_number"] for r in rest["preview_rows"]] == [
        r["row_number"] for r in ready["preview_rows"]
    ]

    response = await _confirm(api, job_id)
    await _drain_batches()

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
    assert sorted(ups.recipients_purchased) == [
        "CANARY Alice Adams",
        "CANARY Bob Brown",
        "CANARY Cara Cole",
        "CANARY Dan Diaz",
    ]
    progress = await _progress(api, job_id)
    assert progress["job_id"] == job_id
    assert progress["status"] == "completed"
    assert (
        progress["total_rows"],
        progress["processed_rows"],
        progress["successful_rows"],
        progress["failed_rows"],
    ) == (4, 4, 4, 0)
    assert progress["total_cost_cents"] == 4 * RATE_CENTS
    rows = _rows(session_factory, job_id)
    assert [r.status for r in rows] == ["completed"] * 4
    assert len({r.tracking_number for r in rows}) == 4
    assert all(r.idempotency_key for r in rows)
    assert len({r.idempotency_key for r in rows}) == 4


@pytest.mark.parametrize("kind", ID_PROVIDERS)
async def test_repeated_pipeline_call_in_one_turn_creates_one_job(
    kind: str,
    source: ImportedCsvSource,
    ups: SimulatedUPS,
    session_factory: sessionmaker[Session],
) -> None:
    call = Call(
        "call_preview",
        "ship_command_pipeline",
        {"command": "Ship all orders", "all_rows": True},
    )
    rendered = build_provider(kind, [[call, call], [Say("Preview ready.")]])
    obs = await run_scenario(
        script=[], provider=rendered.provider, ups_gateway=ups, data_gateway=source
    )

    assert len(_jobs(session_factory)) == 1
    assert len([e for e in obs.events if e["event"] == "preview_ready"]) == 1
    assert len(ups.rate_calls) == 4
    assert ups.create_calls == []


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_repeated_confirm_requests_cannot_duplicate_shipments(
    kind: str,
    source: ImportedCsvSource,
    ups: SimulatedUPS,
    api: httpx.AsyncClient,
    session_factory: sessionmaker[Session],
) -> None:
    obs, _ = await _preview_in_conversation(kind, source, ups)
    job_id = _preview_ready(obs)["job_id"]
    release = ups.hold_creates()

    # Three simultaneous confirms while the first purchase is still in flight.
    responses = await asyncio.gather(*[_confirm(api, job_id) for _ in range(3)])
    await asyncio.wait_for(ups.in_create.wait(), timeout=5)
    release.set()
    await _drain_batches()

    assert sorted(r.status_code for r in responses) == [200, 400, 400]
    assert len(ups.create_calls) == 4
    assert len(set(ups.recipients_purchased)) == 4

    # Sequential replays after completion are rejected too.
    late = [await _confirm(api, job_id) for _ in range(2)]
    await _drain_batches()
    assert [r.status_code for r in late] == [400, 400]
    assert len(ups.create_calls) == 4

    # Stable job ownership: still exactly one job, with its original rows.
    jobs = _jobs(session_factory)
    assert [job.id for job in jobs] == [job_id]
    assert jobs[0].status == "completed"
    assert len(_rows(session_factory, job_id)) == 4


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_second_preview_never_purchases_and_leaves_first_job_owned(
    kind: str,
    source: ImportedCsvSource,
    ups: SimulatedUPS,
    api: httpx.AsyncClient,
    session_factory: sessionmaker[Session],
) -> None:
    first, _ = await _preview_in_conversation(kind, source, ups)
    second, _ = await _preview_in_conversation(kind, source, ups)
    first_id, second_id = (
        _preview_ready(first)["job_id"],
        _preview_ready(second)["job_id"],
    )
    assert first_id != second_id

    await _confirm(api, second_id)
    await _drain_batches()

    # Only the confirmed job's rows were purchased; the other stays pending.
    assert len(ups.create_calls) == 4
    by_id = {job.id: job.status for job in _jobs(session_factory)}
    assert by_id == {first_id: "pending", second_id: "completed"}
    assert {r.status for r in _rows(session_factory, first_id)} == {"pending"}


# ---- failures: recovery behaviour is preserved --------------------------------


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_deterministic_rejection_fails_only_that_row_and_is_not_retried(
    kind: str,
    source: ImportedCsvSource,
    ups: SimulatedUPS,
    api: httpx.AsyncClient,
    session_factory: sessionmaker[Session],
) -> None:
    ups.behaviors["CANARY Bob Brown"] = hard_rejection()
    obs, _ = await _preview_in_conversation(kind, source, ups)
    job_id = _preview_ready(obs)["job_id"]

    await _confirm(api, job_id)
    await _drain_batches()

    progress = await _progress(api, job_id)
    assert (progress["successful_rows"], progress["failed_rows"]) == (3, 1)
    assert progress["status"] == "failed"
    assert [f["row_number"] for f in progress["row_failures"]] == [2]
    statuses = {r.row_number: r.status for r in _rows(session_factory, job_id)}
    assert statuses == {1: "completed", 2: "failed", 3: "completed", 4: "completed"}

    # Replaying the confirm does not retry the failed row.
    retry = await _confirm(api, job_id)
    await _drain_batches()
    assert retry.status_code == 400
    assert len(ups.create_calls) == 4
    assert sorted(ups.recipients_purchased).count("CANARY Bob Brown") == 1


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_ambiguous_carrier_outcome_needs_review_and_is_never_retried(
    kind: str,
    source: ImportedCsvSource,
    ups: SimulatedUPS,
    api: httpx.AsyncClient,
    session_factory: sessionmaker[Session],
) -> None:
    ups.behaviors["CANARY Cara Cole"] = TimeoutError("carrier response lost")
    obs, _ = await _preview_in_conversation(kind, source, ups)
    job_id = _preview_ready(obs)["job_id"]

    await _confirm(api, job_id)
    await _drain_batches()

    statuses = {r.row_number: r.status for r in _rows(session_factory, job_id)}
    assert statuses == {
        1: "completed",
        2: "completed",
        3: "needs_review",
        4: "completed",
    }
    progress = await _progress(api, job_id)
    assert [f["row_number"] for f in progress["row_failures"]] == [3]
    summary = (await api.get(f"/api/v1/jobs/{job_id}/summary")).json()
    assert summary["needs_review_count"] == 1
    assert summary["pending_count"] == 0
    assert summary["in_flight_count"] == 0

    # Neither another confirm nor a model-issued execute may touch the row.
    again = await _confirm(api, job_id)
    await _drain_batches()
    assert again.status_code == 400
    denied = build_provider(
        kind,
        [
            [Call("call_exec", "batch_execute", {"job_id": job_id, "approved": True})],
            [Say("done")],
        ],
    )
    await run_scenario(
        script=[], provider=denied.provider, ups_gateway=ups, data_gateway=source
    )
    assert len(ups.create_calls) == 4
    assert sorted(ups.recipients_purchased).count("CANARY Cara Cole") == 1
    statuses = {r.row_number: r.status for r in _rows(session_factory, job_id)}
    assert statuses[3] == "needs_review"


async def test_audit_trail_links_preview_confirmation_and_execution_to_the_job(
    source: ImportedCsvSource,
    ups: SimulatedUPS,
    api: httpx.AsyncClient,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "true")
    monkeypatch.setenv("AGENT_AUDIT_JSONL_PATH", str(tmp_path / "audit.jsonl"))
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    await _confirm(api, job_id)
    await _drain_batches()

    events = DecisionAuditService.list_events_for_job(job_id=job_id)["events"]
    names = {event["event_name"] for event in events}
    assert {
        "agent.tool_call.observed",
        "pipeline.preview_ready",
        "execution.confirmed",
        "execution.batch.started",
        "execution.batch.completed",
    } <= names
    assert CANARY_PREFIX not in json.dumps(events, default=str)


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_denied_execution_attempt_is_audited_without_job_details(
    kind: str,
    source: ImportedCsvSource,
    ups: SimulatedUPS,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "true")
    monkeypatch.setenv("AGENT_AUDIT_JSONL_PATH", str(tmp_path / "audit.jsonl"))
    attempt = build_provider(
        kind,
        [
            [Call("call_exec", "batch_execute", {"job_id": "job-x", "approved": True})],
            [Say("Executed.")],
        ],
    )
    await run_scenario(
        script=[],
        provider=attempt.provider,
        ups_gateway=ups,
        data_gateway=source,
        session_id="audit-denied",
    )

    (run,) = DecisionAuditService.list_runs(session_id="audit-denied")["runs"]
    events = DecisionAuditService.list_events(run_id=run["id"])["events"]
    denied = [e for e in events if e["event_name"] == "policy.tool_denied"]
    assert len(denied) == 1
    assert denied[0]["tool_name"] == "batch_execute"
    assert denied[0]["payload_redacted"] == {
        "denial_code": "execution_requires_user_confirmation"
    }
    assert "job-x" not in json.dumps(events, default=str)
    assert ups.create_calls == []


async def test_enabled_writeback_uses_imported_fixture_file(
    source, ups, api, session_factory
):
    """Enabled writes stay inside the same test-owned CSV source."""
    obs, _ = await _preview_in_conversation("scripted", source, ups)
    job_id = _preview_ready(obs)["job_id"]
    await _confirm(api, job_id, write_back_enabled=True)
    await _drain_batches()
    import csv

    info = await source.get_source_info()
    with open(info["path"], newline="") as f:
        written = list(csv.DictReader(f))
    assert len(ups.create_calls) == 4
    assert [r["tracking_number"] for r in written] == [
        r.tracking_number for r in _rows(session_factory, job_id)
    ]
