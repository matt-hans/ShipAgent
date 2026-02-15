"""Preview and confirmation API routes.

Provides endpoints for fetching batch preview data and confirming
batches for execution. Integrates with UPSMCPClient + BatchEngine for
real shipment creation. Emits SSE progress events for real-time
frontend updates.
"""

import asyncio
import json
import logging
import os
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.schemas import (
    BatchPreviewResponse,
    ConfirmResponse,
    PreviewRowResponse,
)
from src.db.connection import get_db
from src.db.models import Job, JobRow, RowStatus
from src.services.batch_engine import BatchEngine
from src.services.ups_mcp_client import UPSMCPClient
from src.services.ups_payload_builder import (
    build_shipment_request,
    build_shipper_from_env,
    build_shipper_from_shop,
)
from src.services.ups_service_codes import SERVICE_CODE_NAMES

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
                service_code = order_data_dict.get("service_code", "03")
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
        if getattr(row, "destination_country", None) and row.destination_country not in ("US", "PR"):
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


async def _get_shipper_info() -> dict[str, str]:
    """Get shipper information from Shopify or environment.

    Checks if Shopify is connected via the ExternalSourcesMCPClient gateway.
    If connected, fetches shop details via the get_shop_info MCP tool.
    Falls back to environment variables if Shopify is unavailable.

    Returns:
        Dict containing shipper address details.
    """
    shopify_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    shopify_domain = os.environ.get("SHOPIFY_STORE_DOMAIN")

    if shopify_token and shopify_domain:
        try:
            from src.services.gateway_provider import get_external_sources_client

            ext = await get_external_sources_client()
            connections = await ext.list_connections()
            shopify_connected = any(
                (c.get("platform") if isinstance(c, dict) else getattr(c, "platform", None)) == "shopify"
                and (c.get("status") if isinstance(c, dict) else getattr(c, "status", None)) == "connected"
                for c in connections.get("connections", [])
            )

            if not shopify_connected:
                result = await ext.connect_platform(
                    platform="shopify",
                    credentials={"access_token": shopify_token},
                    store_url=shopify_domain,
                )
                shopify_connected = result.get("success", False)

            if shopify_connected:
                shop_result = await ext.get_shop_info("shopify")
                if shop_result.get("success"):
                    shop_info = shop_result.get("shop", {})
                    if shop_info:
                        logger.info(
                            "Using shipper info from Shopify store: %s",
                            shop_info.get("name"),
                        )
                        return build_shipper_from_shop(shop_info)
        except Exception as e:
            logger.warning("Failed to get shop info from Shopify: %s", e)

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

    Creates a UPSMCPClient and BatchEngine, then delegates row processing
    to the engine. Updates job counters and emits SSE progress events
    via a progress callback adapter.

    Args:
        job_id: The job UUID to process.
    """
    from src.db.connection import get_db as get_db_session

    observer = _get_sse_observer()
    db = next(get_db_session())
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

        # Get shipper info once for all shipments.
        # Priority: (1) persisted shipper from interactive preview,
        # (2) env-based shipper for local data sources (CSV/Excel),
        # (3) Shopify shop address when no local source is active.
        if job.shipper_json:
            try:
                shipper = json.loads(job.shipper_json)
                logger.info("Using persisted shipper for job %s", job_id)
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(
                    "Malformed shipper_json for job %s: %s — falling back to env",
                    job_id,
                    e,
                )
                shipper = build_shipper_from_env()
        else:
            from src.services.gateway_provider import get_data_gateway

            gw = await get_data_gateway()
            source_info = await gw.get_source_info()
            if source_info is not None:
                shipper = build_shipper_from_env()
                logger.info("Using env shipper for local data source job %s", job_id)
            else:
                shipper = await _get_shipper_info()

        # Derive UPS environment from base URL
        base_url = os.environ.get("UPS_BASE_URL", "https://wwwcie.ups.com")
        environment = "test" if "wwwcie" in base_url else "production"
        account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "")

        # Create UPSMCPClient (async MCP over stdio)
        async with UPSMCPClient(
            client_id=os.environ.get("UPS_CLIENT_ID", ""),
            client_secret=os.environ.get("UPS_CLIENT_SECRET", ""),
            environment=environment,
            account_number=account_number,
        ) as ups:
            # Create BatchEngine
            engine = BatchEngine(
                ups_service=ups,
                db_session=db,
                account_number=account_number,
            )

            # SSE progress adapter — bridges BatchEngine callbacks to SSE observer
            successful = 0
            failed = 0
            total_cost = 0

            async def on_progress(event_type: str, **kwargs) -> None:
                """Adapt BatchEngine progress events to SSE observer calls."""
                nonlocal successful, failed, total_cost

                if event_type == "row_completed":
                    successful += 1
                    total_cost += kwargs.get("cost_cents", 0)
                    # Update job counters incrementally
                    job.processed_rows = successful + failed
                    job.successful_rows = successful
                    job.failed_rows = failed
                    job.total_cost_cents = total_cost
                    db.commit()
                    await observer.on_row_completed(
                        job_id, kwargs["row_number"],
                        kwargs.get("tracking_number", ""),
                        kwargs.get("cost_cents", 0),
                    )
                elif event_type == "row_failed":
                    failed += 1
                    job.processed_rows = successful + failed
                    job.successful_rows = successful
                    job.failed_rows = failed
                    job.total_cost_cents = total_cost
                    db.commit()
                    await observer.on_row_failed(
                        job_id, kwargs["row_number"],
                        kwargs.get("error_code", "E-3005"),
                        kwargs.get("error_message", "Unknown error"),
                    )

            # Execute batch (disable write-back for interactive jobs)
            result = await engine.execute(
                job_id=job_id,
                rows=rows,
                shipper=shipper,
                on_progress=on_progress,
                write_back_enabled=not getattr(job, "is_interactive", False),
            )

        successful = result["successful"]
        failed = result["failed"]
        total_cost = result["total_cost_cents"]

        # Aggregate international row-level data onto job
        intl_rows = (
            db.query(JobRow)
            .filter(
                JobRow.job_id == job_id,
                JobRow.destination_country.isnot(None),
            )
            .all()
        )
        intl_count = len(intl_rows)
        intl_duties = sum(r.duties_taxes_cents or 0 for r in intl_rows)

        # Update job with final status
        job.processed_rows = successful + failed
        job.successful_rows = successful
        job.failed_rows = failed
        job.total_cost_cents = total_cost
        job.international_row_count = intl_count
        job.total_duties_taxes_cents = intl_duties if intl_duties > 0 else None
        job.status = "completed" if failed == 0 else "failed"
        job.completed_at = datetime.now(UTC).isoformat()
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
            job_id, "E-4001", str(e), 0
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
