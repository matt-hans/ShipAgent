"""Preview and confirmation API routes.

Provides endpoints for fetching batch preview data and confirming
batches for execution.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.schemas import (
    BatchPreviewResponse,
    ConfirmResponse,
    PreviewRowResponse,
)
from src.db.connection import get_db
from src.db.models import Job, JobRow

router = APIRouter(tags=["preview"])

# Maximum number of rows to include in preview
MAX_PREVIEW_ROWS = 10


@router.get("/jobs/{job_id}/preview", response_model=BatchPreviewResponse)
def get_job_preview(job_id: str, db: Session = Depends(get_db)) -> BatchPreviewResponse:
    """Get batch preview for a job.

    Returns preview data including sample rows with estimated costs
    and warnings, plus aggregate totals.

    Args:
        job_id: The job UUID.
        db: Database session.

    Returns:
        BatchPreviewResponse with preview data.

    Raises:
        HTTPException: If job not found.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    # Get all rows for the job
    rows = (
        db.query(JobRow)
        .filter(JobRow.job_id == job_id)
        .order_by(JobRow.row_number)
        .all()
    )

    if not rows:
        raise HTTPException(
            status_code=400,
            detail="Job has no rows for preview. Command may not have been processed yet.",
        )

    # Build preview rows from job rows
    preview_rows: list[PreviewRowResponse] = []
    total_estimated_cost = 0
    rows_with_warnings = 0

    for row in rows[:MAX_PREVIEW_ROWS]:
        # Extract preview data from row
        # The row may have metadata stored in a JSON field or we derive from available data
        warnings: list[str] = []

        # Check for common warning conditions
        if row.error_message:
            warnings.append(row.error_message)

        # Build recipient name and city/state from available data
        # In MVP, this comes from the job metadata or we use placeholder values
        # Since job rows store processed results, we'll use generic placeholders
        # Real implementation would parse mapping_template output
        recipient_name = f"Shipment #{row.row_number}"
        city_state = "Pending"
        service = "UPS Ground"

        # Cost is stored in cents
        estimated_cost = row.cost_cents or 0
        total_estimated_cost += estimated_cost

        if warnings:
            rows_with_warnings += 1

        preview_rows.append(
            PreviewRowResponse(
                row_number=row.row_number,
                recipient_name=recipient_name,
                city_state=city_state,
                service=service,
                estimated_cost_cents=estimated_cost,
                warnings=warnings,
            )
        )

    # Calculate totals for all rows (not just preview)
    for row in rows[MAX_PREVIEW_ROWS:]:
        total_estimated_cost += row.cost_cents or 0
        if row.error_message:
            rows_with_warnings += 1

    return BatchPreviewResponse(
        job_id=job_id,
        total_rows=len(rows),
        preview_rows=preview_rows,
        additional_rows=max(0, len(rows) - MAX_PREVIEW_ROWS),
        total_estimated_cost_cents=total_estimated_cost,
        rows_with_warnings=rows_with_warnings,
    )


@router.post("/jobs/{job_id}/confirm", response_model=ConfirmResponse)
def confirm_job(job_id: str, db: Session = Depends(get_db)) -> ConfirmResponse:
    """Confirm a job for execution.

    Updates the job status to 'running' to trigger batch execution.

    Args:
        job_id: The job UUID.
        db: Database session.

    Returns:
        ConfirmResponse with status and message.

    Raises:
        HTTPException: If job not found or not in pending status.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if job.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Job cannot be confirmed. Current status: {job.status}. "
            "Only pending jobs can be confirmed.",
        )

    # Update job status to running
    job.status = "running"
    db.commit()

    return ConfirmResponse(
        status="confirmed",
        message=f"Job {job_id} confirmed for execution. Processing will begin shortly.",
    )
