"""Preview and confirmation API routes.

Provides endpoints for fetching batch preview data and confirming
batches for execution. Integrates with UPS MCP for real shipment creation.
Emits SSE progress events for real-time frontend updates.
"""

import asyncio
import json
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.schemas import (
    BatchPreviewResponse,
    ConfirmResponse,
    PreviewRowResponse,
)
from src.db.connection import get_db
from src.db.models import Job, JobRow, RowStatus
from src.mcp.ups_client import UpsMcpClient, UpsMcpError
from src.services.ups_payload_builder import (
    build_shipment_request,
    build_shipper_from_env,
    build_shipper_from_shop,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["preview"])

# UPS service code to name mapping
SERVICE_CODE_NAMES = {
    "01": "UPS Next Day Air",
    "02": "UPS 2nd Day Air",
    "03": "UPS Ground",
    "12": "UPS 3 Day Select",
    "13": "UPS Ground Saver",
    "14": "UPS Next Day Air Early",
    "59": "UPS 2nd Day Air A.M.",
}

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
        warnings: list[str] = []

        # Check for common warning conditions
        if row.error_message:
            warnings.append(row.error_message)

        # Parse order data if available
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
                service_code = order_data_dict.get("service_code", "03")
                service = SERVICE_CODE_NAMES.get(service_code, "UPS Ground")
            except json.JSONDecodeError:
                pass  # Fall back to defaults

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
                order_data=order_data_dict,
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


async def _get_shipper_info() -> dict[str, str]:
    """Get shipper information from Shopify or environment.

    Attempts to fetch shop details from Shopify if credentials are configured.
    Falls back to environment variables if Shopify is unavailable.

    Returns:
        Dict containing shipper address details
    """
    # Check if Shopify credentials are configured
    shopify_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    shopify_domain = os.environ.get("SHOPIFY_STORE_DOMAIN")

    if shopify_token and shopify_domain:
        try:
            from src.mcp.external_sources.clients.shopify import ShopifyClient

            client = ShopifyClient()
            authenticated = await client.authenticate({
                "store_url": shopify_domain,
                "access_token": shopify_token,
            })

            if authenticated:
                shop_info = await client.get_shop_info()
                if shop_info:
                    logger.info("Using shipper info from Shopify store: %s", shop_info.get("name"))
                    return build_shipper_from_shop(shop_info)
        except Exception as e:
            logger.warning("Failed to get shop info from Shopify: %s", e)

    # Fall back to environment variables
    logger.info("Using shipper info from environment variables")
    return build_shipper_from_env()


def _get_sse_observer():
    """Get the shared SSE observer from the progress module.

    Lazily imports to avoid circular imports between route modules.

    Returns:
        SSEProgressObserver instance from progress.py.
    """
    from src.api.routes.progress import sse_observer

    return sse_observer


async def _execute_batch(job_id: str) -> None:
    """Execute batch shipment processing in the background.

    Processes each JobRow by calling the UPS MCP shipping_create tool
    and updates row status with real tracking numbers and label paths.
    Emits SSE progress events and updates job counters incrementally
    after each row for real-time frontend progress tracking.

    Args:
        job_id: The job UUID to process.
    """
    from src.db.connection import get_db as get_db_session

    observer = _get_sse_observer()
    db = next(get_db_session())
    total_cost = 0
    successful = 0
    failed = 0
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error("Job not found for execution: %s", job_id)
            return

        # Get all pending rows
        rows = (
            db.query(JobRow)
            .filter(JobRow.job_id == job_id, JobRow.status == RowStatus.pending.value)
            .order_by(JobRow.row_number)
            .all()
        )

        logger.info("Starting batch execution for job %s with %d rows", job_id, len(rows))

        # Emit batch_started SSE event
        await observer.on_batch_started(job_id, len(rows))

        # Get shipper info once for all shipments
        shipper = await _get_shipper_info()

        # Use UPS MCP client for real shipments
        try:
            async with UpsMcpClient() as ups_client:
                for row in rows:
                    # Emit row_started SSE event
                    await observer.on_row_started(job_id, row.row_number)

                    try:
                        # Mark row as processing
                        row.status = RowStatus.processing.value
                        db.commit()

                        # Parse order data
                        order_data = {}
                        if row.order_data:
                            try:
                                order_data = json.loads(row.order_data)
                            except json.JSONDecodeError:
                                raise ValueError("Invalid order_data JSON")

                        # Build shipment request
                        shipment_request = build_shipment_request(
                            order_data=order_data,
                            shipper=shipper,
                        )

                        # Call UPS MCP shipping_create
                        result = await ups_client.call_tool("shipping_create", shipment_request)

                        # Extract results
                        if not result.get("success"):
                            raise ValueError(f"UPS shipping failed: {result}")

                        tracking_numbers = result.get("trackingNumbers", [])
                        label_paths = result.get("labelPaths", [])
                        total_charges = result.get("totalCharges", {})

                        tracking_number = tracking_numbers[0] if tracking_numbers else ""
                        label_path = label_paths[0] if label_paths else ""

                        # Convert cost to cents
                        cost_value = total_charges.get("monetaryValue", "0")
                        try:
                            cost_cents = int(float(cost_value) * 100)
                        except (ValueError, TypeError):
                            cost_cents = row.cost_cents or 0

                        # Update row with shipping result
                        row.tracking_number = tracking_number
                        row.label_path = label_path
                        row.cost_cents = cost_cents
                        row.status = RowStatus.completed.value
                        row.processed_at = datetime.utcnow().isoformat()

                        total_cost += cost_cents
                        successful += 1

                        # Update job counters incrementally for progress polling
                        job.processed_rows = successful + failed
                        job.successful_rows = successful
                        job.failed_rows = failed
                        job.total_cost_cents = total_cost
                        db.commit()

                        # Emit row_completed SSE event
                        await observer.on_row_completed(
                            job_id, row.row_number, tracking_number, cost_cents
                        )

                        logger.info(
                            "Row %d completed: tracking=%s, cost=%d cents, label=%s",
                            row.row_number,
                            tracking_number,
                            cost_cents,
                            label_path,
                        )

                    except UpsMcpError as e:
                        logger.error("Row %d UPS error: %s", row.row_number, e)
                        row.status = RowStatus.failed.value
                        row.error_code = e.code
                        row.error_message = str(e)
                        failed += 1

                        # Update job counters incrementally
                        job.processed_rows = successful + failed
                        job.successful_rows = successful
                        job.failed_rows = failed
                        job.total_cost_cents = total_cost
                        db.commit()

                        # Emit row_failed SSE event
                        await observer.on_row_failed(
                            job_id, row.row_number, e.code, str(e)
                        )

                    except Exception as e:
                        logger.exception("Row %d failed: %s", row.row_number, e)
                        row.status = RowStatus.failed.value
                        row.error_code = "E-3005"
                        row.error_message = str(e)
                        failed += 1

                        # Update job counters incrementally
                        job.processed_rows = successful + failed
                        job.successful_rows = successful
                        job.failed_rows = failed
                        job.total_cost_cents = total_cost
                        db.commit()

                        # Emit row_failed SSE event
                        await observer.on_row_failed(
                            job_id, row.row_number, "E-3005", str(e)
                        )

        except UpsMcpError as e:
            # UPS MCP connection/startup failure - fail all remaining rows
            logger.error("UPS MCP connection failed: %s", e)
            for row in rows:
                if row.status == RowStatus.pending.value:
                    row.status = RowStatus.failed.value
                    row.error_code = e.code
                    row.error_message = str(e)
                    failed += 1
            job.processed_rows = successful + failed
            job.successful_rows = successful
            job.failed_rows = failed
            job.total_cost_cents = total_cost
            db.commit()

            # Emit batch_failed SSE event for connection failure
            await observer.on_batch_failed(
                job_id, e.code, str(e), successful + failed
            )

        # Update job with final status
        job.processed_rows = successful + failed
        job.successful_rows = successful
        job.failed_rows = failed
        job.total_cost_cents = total_cost
        job.status = "completed" if failed == 0 else "failed"
        job.completed_at = datetime.utcnow().isoformat()
        db.commit()

        # Emit final batch event
        if failed == 0:
            await observer.on_batch_completed(
                job_id, len(rows), successful, total_cost
            )
        else:
            await observer.on_batch_failed(
                job_id, "E-3005", f"{failed} row(s) failed during execution",
                successful + failed,
            )

        logger.info(
            "Batch execution complete for job %s: %d successful, %d failed, $%.2f total",
            job_id,
            successful,
            failed,
            total_cost / 100,
        )

    except Exception as e:
        logger.exception("Batch execution failed for job %s: %s", job_id, e)
        # Update job to failed status
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "failed"
            job.error_code = "E-4001"
            job.error_message = str(e)
            db.commit()

        # Emit batch_failed SSE event
        await observer.on_batch_failed(
            job_id, "E-4001", str(e), successful + failed
        )
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
    db: Session = Depends(get_db),
) -> ConfirmResponse:
    """Confirm a job for execution.

    Updates the job status to 'running' and triggers batch execution
    in the background using asyncio.create_task() to properly schedule
    the async coroutine on the event loop.

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
    job.started_at = datetime.utcnow().isoformat()
    db.commit()

    # Schedule async batch execution on the event loop
    # Note: BackgroundTasks.add_task() does NOT properly await async functions,
    # so we use asyncio.create_task() which correctly schedules the coroutine.
    asyncio.create_task(_execute_batch_safe(job_id))

    return ConfirmResponse(
        status="confirmed",
        message=f"Job {job_id} confirmed for execution. Processing will begin shortly.",
    )
