"""FastAPI routes for agent decision audit ledger access."""

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from src.services.decision_audit_service import DecisionAuditService

router = APIRouter(prefix="/agent-audit", tags=["agent-audit"])


@router.get("/runs")
def list_runs(
    session_id: str | None = Query(None),
    job_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    """List decision runs with optional filters."""
    return DecisionAuditService.list_runs(
        limit=limit,
        offset=offset,
        session_id=session_id,
        job_id=job_id,
        status=status,
    )


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    """Get one decision run by ID."""
    run = DecisionAuditService.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs/{run_id}/events")
def get_run_events(
    run_id: str,
    phase: str | None = Query(None),
    event_name: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> dict:
    """Get events for a decision run."""
    run = DecisionAuditService.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return DecisionAuditService.list_events(
        run_id=run_id,
        limit=limit,
        offset=offset,
        phase=phase,
        event_name=event_name,
    )


@router.get("/jobs/{job_id}/events")
def get_job_events(
    job_id: str,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> dict:
    """Get decision events correlated to a job."""
    return DecisionAuditService.list_events_for_job(
        job_id=job_id,
        limit=limit,
        offset=offset,
    )


@router.get("/export", response_class=PlainTextResponse)
def export_events(
    run_id: str | None = Query(None),
    job_id: str | None = Query(None),
    started_after: datetime | None = Query(None),
    started_before: datetime | None = Query(None),
) -> PlainTextResponse:
    """Export decision events as JSONL."""
    if not run_id and not job_id and not started_after and not started_before:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one filter (run_id, job_id, started_after, started_before).",
        )

    rows = DecisionAuditService.export_events(
        run_id=run_id,
        job_id=job_id,
        started_after=started_after.isoformat() if started_after else None,
        started_before=started_before.isoformat() if started_before else None,
    )
    content = "\n".join(
        json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)
        for item in rows
    )
    if content:
        content += "\n"
    return PlainTextResponse(
        content=content,
        media_type="application/jsonl",
    )
