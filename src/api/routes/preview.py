"""Preview and confirmation API routes.

Provides endpoints for fetching batch preview data and confirming
batches for execution. Integrates with UPSMCPClient + BatchEngine for
real shipment creation. Emits SSE progress events for real-time
frontend updates.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.schemas import (
    BatchPreviewResponse,
    ConfirmRequest,
    ConfirmResponse,
    PreviewRowResponse,
)
from src.db.connection import get_db
from src.db.models import Job, JobRow, RowStatus
from src.services.ups_constants import DEFAULT_ORIGIN_COUNTRY
from src.services.ups_service_codes import SERVICE_CODE_NAMES, ServiceCode

logger = logging.getLogger(__name__)

router = APIRouter(tags=["preview"])

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

    # Build preview rows from ALL job rows
    preview_rows: list[PreviewRowResponse] = []
    total_estimated_cost = 0
    rows_with_warnings = 0

    for row in rows:
        warnings: list[str] = []

        if row.error_message:
            warnings.append(row.error_message)

        recipient_name = f"Shipment #{row.row_number}"
        city_state = "Pending"
        service = "UPS Ground"
        order_data_dict: dict | None = None

        if row.order_data:
            try:
                order_data_dict = json.loads(row.order_data)
                recipient_name = order_data_dict.get("ship_to_name", recipient_name)
                city = order_data_dict.get("ship_to_city", "")
                state = order_data_dict.get("ship_to_state", "")
                city_state = f"{city}, {state}" if city and state else "Pending"
                service_code = order_data_dict.get("service_code", ServiceCode.GROUND.value)
                service = SERVICE_CODE_NAMES.get(service_code, "UPS Ground")
            except json.JSONDecodeError:
                pass

        estimated_cost = row.cost_cents or 0
        total_estimated_cost += estimated_cost

        if warnings:
            rows_with_warnings += 1

        # Extract international data from row
        destination_country = getattr(row, "destination_country", None)
        duties_taxes_cents = getattr(row, "duties_taxes_cents", None)
        charge_breakdown_raw = getattr(row, "charge_breakdown", None)
        charge_breakdown = None
        if charge_breakdown_raw:
            try:
                charge_breakdown = json.loads(charge_breakdown_raw)
            except json.JSONDecodeError:
                pass

        preview_rows.append(
            PreviewRowResponse(
                row_number=row.row_number,
                recipient_name=recipient_name,
                city_state=city_state,
                service=service,
                estimated_cost_cents=estimated_cost,
                warnings=warnings,
                order_data=order_data_dict,
                destination_country=destination_country,
                duties_taxes_cents=duties_taxes_cents,
                charge_breakdown=charge_breakdown,
            )
        )

    # Compute international aggregates
    total_duties_taxes = 0
    international_count = 0
    for row in rows:
        if getattr(row, "duties_taxes_cents", None):
            total_duties_taxes += row.duties_taxes_cents
        if getattr(row, "destination_country", None) and row.destination_country not in (DEFAULT_ORIGIN_COUNTRY, "PR"):
            international_count += 1

    return BatchPreviewResponse(
        job_id=job_id,
        total_rows=len(rows),
        preview_rows=preview_rows,
        additional_rows=0,
        total_estimated_cost_cents=total_estimated_cost,
        rows_with_warnings=rows_with_warnings,
        total_duties_taxes_cents=total_duties_taxes if total_duties_taxes > 0 else None,
        international_row_count=international_count,
    )


def _get_sse_observer():
    """Get the shared SSE observer from the progress module.

    Lazily imports to avoid circular imports between route modules.

    Returns:
        SSEProgressObserver instance from progress.py.
    """
    from src.api.routes.progress import sse_observer

    return sse_observer


async def _execute_batch(job_id: str) -> None:
    """Execute batch shipment processing — delegates to shared service.

    Args:
        job_id: The job UUID to process.
    """
    from src.db.connection import get_db as get_db_session
    from src.services.batch_executor import execute_batch

    observer = _get_sse_observer()
    db = next(get_db_session())
    try:
        total_rows = db.query(Job).filter(Job.id == job_id).with_entities(
            Job.total_rows
        ).scalar() or 0
        await observer.on_batch_started(job_id, total_rows)

        async def on_progress(event_type: str, **kwargs) -> None:
            """Adapt progress events to SSE observer calls."""
            if event_type == "row_completed":
                await observer.on_row_completed(
                    job_id, kwargs["row_number"],
                    kwargs.get("tracking_number", ""),
                    kwargs.get("cost_cents", 0),
                )
            elif event_type == "row_failed":
                await observer.on_row_failed(
                    job_id, kwargs["row_number"],
                    kwargs.get("error_code", "E-3005"),
                    kwargs.get("error_message", "Unknown error"),
                )

        result = await execute_batch(job_id, db, on_progress=on_progress)

        if result["failed"] == 0:
            await observer.on_batch_completed(
                job_id, result["successful"] + result["failed"],
                result["successful"], result["total_cost_cents"],
                duties_taxes_cents=result.get("total_duties_taxes_cents", 0),
                international_row_count=result.get("international_row_count", 0),
            )
        else:
            await observer.on_batch_failed(
                job_id, "E-3005",
                f"{result['failed']} row(s) failed during execution",
                result["successful"] + result["failed"],
                duties_taxes_cents=result.get("total_duties_taxes_cents", 0),
                international_row_count=result.get("international_row_count", 0),
            )
    except Exception as e:
        logger.exception("Background batch execution failed for job %s: %s", job_id, e)
        await observer.on_batch_failed(job_id, "E-4001", str(e), 0)
    finally:
        db.close()


async def _execute_batch_safe(job_id: str) -> None:
    """Wrapper that catches and logs errors from batch execution.

    Ensures background task failures are logged and job status is updated
    appropriately even if unexpected errors occur.

    Args:
        job_id: The job UUID to process.
    """
    try:
        await _execute_batch(job_id)
    except Exception as e:
        logger.exception("Background batch execution failed for job %s: %s", job_id, e)
        # Update job to failed status
        from src.db.connection import get_db as get_db_session

        db = next(get_db_session())
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job and job.status == "running":
                job.status = "failed"
                job.error_code = "E-4001"
                job.error_message = f"Background task error: {e}"
                db.commit()
        finally:
            db.close()


@router.post("/jobs/{job_id}/confirm", response_model=ConfirmResponse)
async def confirm_job(
    job_id: str,
    req: ConfirmRequest | None = None,
    db: Session = Depends(get_db),
) -> ConfirmResponse:
    """Confirm a job for execution.

    Updates the job status to 'running' and triggers batch execution
    in the background using asyncio.create_task() to properly schedule
    the async coroutine on the event loop.

    Args:
        job_id: The job UUID.
        req: Optional request body with write-back preference.
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

    # Write-back preference: user toggle overrides, but interactive always off
    if req and req.write_back_enabled is not None:
        job.write_back_enabled = req.write_back_enabled and not job.is_interactive
    else:
        job.write_back_enabled = not job.is_interactive

    # Update job status to running
    job.status = "running"
    job.started_at = datetime.now(UTC).isoformat()
    db.commit()

    # Schedule async batch execution on the event loop
    # Note: BackgroundTasks.add_task() does NOT properly await async functions,
    # so we use asyncio.create_task() which correctly schedules the coroutine.
    asyncio.create_task(_execute_batch_safe(job_id))

    return ConfirmResponse(
        status="confirmed",
        message=f"Job {job_id} confirmed for execution. Processing will begin shortly.",
    )
