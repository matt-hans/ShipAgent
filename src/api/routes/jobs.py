"""FastAPI routes for job management.

Provides REST API endpoints for job CRUD operations, status updates,
row retrieval, and summary metrics.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.schemas import (
    JobCreate,
    JobListResponse,
    JobResponse,
    JobRowResponse,
    JobSummaryResponse,
    JobUpdate,
    SkipRowsRequest,
)
from src.db.connection import get_db
from src.db.models import Job, JobRow, JobStatus, RowStatus
from src.services import AuditService, EventType, InvalidStateTransition, JobService
from src.services.data_source_service import DataSourceService

router = APIRouter(prefix="/jobs", tags=["jobs"])


def get_job_service(db: Session = Depends(get_db)) -> JobService:
    """Dependency to get JobService instance."""
    return JobService(db)


def get_audit_service(db: Session = Depends(get_db)) -> AuditService:
    """Dependency to get AuditService instance."""
    return AuditService(db)


@router.post("", response_model=JobResponse, status_code=201)
def create_job(
    job_data: JobCreate,
    job_svc: JobService = Depends(get_job_service),
    audit_svc: AuditService = Depends(get_audit_service),
) -> Job:
    """Create a new job.

    Args:
        job_data: Job creation data.
        job_svc: Job service dependency.
        audit_svc: Audit service dependency.

    Returns:
        The created job.
    """
    job = job_svc.create_job(
        name=job_data.name,
        original_command=job_data.original_command,
        description=job_data.description,
        mode=job_data.mode.value,
    )
    audit_svc.log_state_change(job.id, "none", "pending")
    source_signature = DataSourceService.get_instance().get_source_signature()
    if source_signature is not None:
        audit_svc.log_info(
            job_id=job.id,
            event_type=EventType.row_event,
            message="job_source_signature",
            details={"source_signature": source_signature},
        )
    return job


@router.get("", response_model=JobListResponse)
def list_jobs(
    status: str | None = Query(None, description="Filter by status"),
    name: str | None = Query(None, description="Filter by name (partial match)"),
    created_after: date | None = Query(
        None, description="Filter jobs created after date"
    ),
    created_before: date | None = Query(
        None, description="Filter jobs created before date"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> JobListResponse:
    """List jobs with optional filters.

    Supports filtering by status, name (partial match), and date range.
    Results are paginated and sorted by created_at DESC.

    Args:
        status: Filter by job status (optional).
        name: Filter by name with partial match (optional).
        created_after: Filter jobs created after this date (optional).
        created_before: Filter jobs created before this date (optional).
        limit: Maximum number of jobs to return.
        offset: Number of jobs to skip.
        db: Database session dependency.

    Returns:
        Paginated list of jobs.
    """
    query = db.query(Job)

    if status:
        query = query.filter(Job.status == JobStatus(status))

    if name:
        query = query.filter(Job.name.ilike(f"%{name}%"))

    if created_after:
        query = query.filter(Job.created_at >= created_after.isoformat())

    if created_before:
        query = query.filter(Job.created_at <= created_before.isoformat() + "T23:59:59")

    # Get total count before pagination
    total = query.count()

    # Apply pagination and ordering
    jobs = query.order_by(Job.created_at.desc()).limit(limit).offset(offset).all()

    return JobListResponse(
        jobs=[JobSummaryResponse.model_validate(j) for j in jobs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    job_svc: JobService = Depends(get_job_service),
) -> Job:
    """Get a job by ID.

    Args:
        job_id: The job UUID.
        job_svc: Job service dependency.

    Returns:
        The requested job.

    Raises:
        HTTPException: If job not found (404).
    """
    job = job_svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.patch("/{job_id}/status", response_model=JobResponse)
def update_job_status(
    job_id: str,
    update: JobUpdate,
    job_svc: JobService = Depends(get_job_service),
    audit_svc: AuditService = Depends(get_audit_service),
) -> Job:
    """Update job status.

    Only valid state transitions are allowed per the job state machine.

    Args:
        job_id: The job UUID.
        update: Status update data.
        job_svc: Job service dependency.
        audit_svc: Audit service dependency.

    Returns:
        The updated job.

    Raises:
        HTTPException: If job not found (404) or invalid transition (400).
    """
    job = job_svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    old_status = job.status

    try:
        job = job_svc.update_status(job_id, JobStatus(update.status.value))
        audit_svc.log_state_change(job_id, old_status, update.status.value)
        return job
    except InvalidStateTransition:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid state transition: {old_status} -> {update.status.value}",
        )


@router.delete("/{job_id}", status_code=204)
def delete_job(
    job_id: str,
    job_svc: JobService = Depends(get_job_service),
) -> None:
    """Delete a job and all associated data.

    Args:
        job_id: The job UUID.
        job_svc: Job service dependency.

    Raises:
        HTTPException: If job not found (404).
    """
    if not job_svc.delete_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return None


@router.get("/{job_id}/rows", response_model=list[JobRowResponse])
def get_job_rows(
    job_id: str,
    status: str | None = Query(None, description="Filter by row status"),
    job_svc: JobService = Depends(get_job_service),
) -> list:
    """Get all rows for a job, optionally filtered by status.

    Args:
        job_id: The job UUID.
        status: Filter by row status (optional).
        job_svc: Job service dependency.

    Returns:
        List of job rows.

    Raises:
        HTTPException: If job not found (404).
    """
    job = job_svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    row_status = RowStatus(status) if status else None
    rows = job_svc.get_rows(job_id, status=row_status)
    return rows


@router.get("/{job_id}/summary")
def get_job_summary(
    job_id: str,
    job_svc: JobService = Depends(get_job_service),
) -> dict:
    """Get job summary with aggregated metrics.

    Args:
        job_id: The job UUID.
        job_svc: Job service dependency.

    Returns:
        Dictionary with job metrics.

    Raises:
        HTTPException: If job not found (404).
    """
    job = job_svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job_svc.get_job_summary(job_id)


@router.patch("/{job_id}/rows/skip")
def skip_rows(
    job_id: str,
    body: SkipRowsRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Mark specific rows as skipped before execution.

    Only allowed on jobs in 'pending' status. Rows must currently be 'pending'
    to be skipped.

    Args:
        job_id: The job UUID.
        body: Request body with row numbers to skip.
        db: Database session dependency.

    Returns:
        Dictionary with the count of rows successfully skipped.

    Raises:
        HTTPException: If job not found (404) or job not pending (400).
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    if job.status != JobStatus.pending.value:
        raise HTTPException(
            status_code=400,
            detail="Can only skip rows on pending jobs",
        )

    updated = (
        db.query(JobRow)
        .filter(
            JobRow.job_id == job_id,
            JobRow.row_number.in_(body.row_numbers),
            JobRow.status == RowStatus.pending.value,
        )
        .update({JobRow.status: RowStatus.skipped.value}, synchronize_session="fetch")
    )
    db.commit()
    return {"skipped": updated}
