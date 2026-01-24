"""FastAPI routes for audit log management.

Provides REST API endpoints for viewing and exporting job audit logs.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from src.api.schemas import AuditLogResponse
from src.db.connection import get_db
from src.db.models import EventType, LogLevel
from src.services import AuditService, JobService

router = APIRouter(prefix="/jobs/{job_id}/logs", tags=["logs"])


def get_job_service(db: Session = Depends(get_db)) -> JobService:
    """Dependency to get JobService instance."""
    return JobService(db)


def get_audit_service(db: Session = Depends(get_db)) -> AuditService:
    """Dependency to get AuditService instance."""
    return AuditService(db)


def _validate_job_exists(job_id: str, job_svc: JobService) -> None:
    """Verify job exists, raise 404 if not found.

    Args:
        job_id: The job UUID to validate.
        job_svc: Job service instance.

    Raises:
        HTTPException: If job not found (404).
    """
    job = job_svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")


def _parse_log_details(log_entry: object) -> dict | None:
    """Parse JSON details from log entry.

    Args:
        log_entry: AuditLog model with details field.

    Returns:
        Parsed dict or None if no details.
    """
    if not log_entry.details:
        return None
    try:
        return json.loads(log_entry.details)
    except json.JSONDecodeError:
        return {"raw": log_entry.details}


@router.get("", response_model=list[AuditLogResponse])
def get_job_logs(
    job_id: str,
    level: str | None = Query(None, description="Filter by log level"),
    event_type: str | None = Query(None, description="Filter by event type"),
    limit: int = Query(1000, ge=1, le=10000),
    job_svc: JobService = Depends(get_job_service),
    audit_svc: AuditService = Depends(get_audit_service),
) -> list:
    """Get audit logs for a job.

    Supports filtering by level (INFO, WARNING, ERROR) and event type.

    Args:
        job_id: The job UUID.
        level: Filter by log level (optional).
        event_type: Filter by event type (optional).
        limit: Maximum number of logs to return.
        job_svc: Job service dependency.
        audit_svc: Audit service dependency.

    Returns:
        List of audit log entries.

    Raises:
        HTTPException: If job not found (404).
    """
    _validate_job_exists(job_id, job_svc)

    log_level = LogLevel(level) if level else None
    log_event_type = EventType(event_type) if event_type else None

    logs = audit_svc.get_logs(
        job_id,
        level=log_level,
        event_type=log_event_type,
        limit=limit,
    )

    # Convert logs to response format with parsed details
    result = []
    for log_entry in logs:
        result.append(
            AuditLogResponse(
                id=log_entry.id,
                job_id=log_entry.job_id,
                timestamp=log_entry.timestamp,
                level=log_entry.level,
                event_type=log_entry.event_type,
                message=log_entry.message,
                details=_parse_log_details(log_entry),
                row_number=log_entry.row_number,
            )
        )
    return result


@router.get("/errors", response_model=list[AuditLogResponse])
def get_job_errors(
    job_id: str,
    limit: int = Query(10, ge=1, le=100),
    job_svc: JobService = Depends(get_job_service),
    audit_svc: AuditService = Depends(get_audit_service),
) -> list:
    """Get recent error logs for a job.

    Args:
        job_id: The job UUID.
        limit: Maximum number of errors to return.
        job_svc: Job service dependency.
        audit_svc: Audit service dependency.

    Returns:
        List of error log entries.

    Raises:
        HTTPException: If job not found (404).
    """
    _validate_job_exists(job_id, job_svc)

    logs = audit_svc.get_recent_errors(job_id, limit=limit)

    result = []
    for log_entry in logs:
        result.append(
            AuditLogResponse(
                id=log_entry.id,
                job_id=log_entry.job_id,
                timestamp=log_entry.timestamp,
                level=log_entry.level,
                event_type=log_entry.event_type,
                message=log_entry.message,
                details=_parse_log_details(log_entry),
                row_number=log_entry.row_number,
            )
        )
    return result


@router.get("/export", response_class=PlainTextResponse)
def export_job_logs(
    job_id: str,
    job_svc: JobService = Depends(get_job_service),
    audit_svc: AuditService = Depends(get_audit_service),
) -> PlainTextResponse:
    """Export all logs for a job as plain text.

    Returns a downloadable text file with formatted log entries.
    Sensitive data is redacted.

    Args:
        job_id: The job UUID.
        job_svc: Job service dependency.
        audit_svc: Audit service dependency.

    Returns:
        Plain text response with Content-Disposition header for download.

    Raises:
        HTTPException: If job not found (404).
    """
    job = job_svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    filename, content = audit_svc.export_logs_for_download(job_id, job.name)

    return PlainTextResponse(
        content=content,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
