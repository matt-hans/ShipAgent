"""Shared batch execution service.

Extracts the canonical execute-batch flow from preview.py so both
HTTP routes and InProcessRunner call the same code path. This is
the SINGLE source of truth for batch execution orchestration.

Callers provide a progress_callback to adapt events to their
transport (SSE for HTTP, Rich for CLI, logging for watchdog).
"""

import json
import logging
import os
from typing import Any, Callable, Coroutine

from src.db.models import Job, JobRow, JobStatus, RowStatus
from src.services.batch_engine import BatchEngine
from src.services.decision_audit_service import DecisionAuditService
from src.services.ups_mcp_client import UPSMCPClient

logger = logging.getLogger(__name__)

# Type for progress callback: async def(event_type: str, **kwargs) -> None
ProgressCallback = Callable[..., Coroutine[Any, Any, None]]


async def get_shipper_for_job(job: Job) -> dict:
    """Resolve shipper address for a job.

    Matches the exact 3-tier priority from preview.py:_execute_batch:
    (1) Persisted shipper_json on the job (from interactive preview).
    (2) Env-based shipper when a local data source (CSV/Excel) is active.
    (3) Shopify shop address when no local data source is active.

    This is async because tier (3) requires querying the Shopify MCP server.

    Args:
        job: The Job model instance.

    Returns:
        Shipper address dict.
    """
    from src.services.ups_payload_builder import build_shipper

    # Tier 1: persisted shipper from interactive preview
    if job.shipper_json:
        try:
            return json.loads(job.shipper_json)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error("Malformed shipper_json for job %s: %s", job.id, e)

    # Tier 2: env-based shipper when local data source is active
    from src.services.gateway_provider import get_data_gateway
    gw = await get_data_gateway()
    source_info = await gw.get_source_info()
    if source_info is not None:
        logger.info("Using env shipper for local data source job %s", job.id)
        return build_shipper()

    # Tier 3: Shopify shop address when no local source is active
    try:
        shopify_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
        shopify_domain = os.environ.get("SHOPIFY_STORE_DOMAIN")
        if shopify_token and shopify_domain:
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
                        logger.info("Using shipper from Shopify store: %s", shop_info.get("name"))
                        return build_shipper(shop_info)
    except Exception as e:
        logger.warning("Failed to get shop info from Shopify: %s", e)

    # Final fallback: env-based shipper
    logger.info("Using env shipper (no local source, no Shopify) for job %s", job.id)
    return build_shipper()


async def execute_batch(
    job_id: str,
    db_session: Any,
    on_progress: ProgressCallback | None = None,
) -> dict:
    """Execute batch shipment processing — full lifecycle.

    This is the canonical execution path. Both preview.py routes
    and InProcessRunner.approve_job() call this function.

    Owns the COMPLETE lifecycle:
    - Row iteration + UPS calls via BatchEngine
    - Per-row progress counter updates on the Job model
    - Final status transition (completed/failed)
    - International data aggregation (duties/taxes, country counts)
    - Completion timestamp
    - Error handling with fallback status

    Callers do NOT need to perform any post-execution status updates.

    Args:
        job_id: The job UUID to process.
        db_session: SQLAlchemy session.
        on_progress: Optional async callback for progress events.

    Returns:
        Result dict with successful, failed, total_cost_cents,
        status, international_row_count, total_duties_taxes_cents keys.

    Raises:
        ValueError: If job not found.
    """
    from datetime import UTC, datetime

    from src.services.ups_constants import DEFAULT_ORIGIN_COUNTRY

    job = db_session.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise ValueError(f"Job not found: {job_id}")
    run_id = DecisionAuditService.resolve_run_id_for_job(job_id)
    DecisionAuditService.log_event(
        run_id=run_id,
        phase="execution",
        event_name="execution.batch.started",
        actor="system",
        payload={"job_id": job_id, "job_status": job.status},
    )

    rows = (
        db_session.query(JobRow)
        .filter(JobRow.job_id == job_id, JobRow.status == RowStatus.pending.value)
        .order_by(JobRow.row_number)
        .all()
    )

    shipper = await get_shipper_for_job(job)

    base_url = os.environ.get("UPS_BASE_URL", "https://wwwcie.ups.com")
    environment = "test" if "wwwcie" in base_url else "production"
    account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "")

    try:
        async with UPSMCPClient(
            client_id=os.environ.get("UPS_CLIENT_ID", ""),
            client_secret=os.environ.get("UPS_CLIENT_SECRET", ""),
            environment=environment,
            account_number=account_number,
        ) as ups:
            engine = BatchEngine(
                ups_service=ups,
                db_session=db_session,
                account_number=account_number,
            )

            # Wrap progress callback to update job counters
            successful = 0
            failed = 0
            total_cost = 0

            async def _progress_adapter(event_type: str, **kwargs) -> None:
                nonlocal successful, failed, total_cost
                if event_type == "row_completed":
                    successful += 1
                    total_cost += kwargs.get("cost_cents", 0)
                elif event_type == "row_failed":
                    failed += 1

                job.processed_rows = successful + failed
                job.successful_rows = successful
                job.failed_rows = failed
                job.total_cost_cents = total_cost
                db_session.commit()

                if on_progress:
                    await on_progress(event_type, **kwargs)

            result = await engine.execute(
                job_id=job_id,
                rows=rows,
                shipper=shipper,
                on_progress=_progress_adapter,
                write_back_enabled=getattr(job, "write_back_enabled", True),
            )

        # --- Final status + aggregation (owned here, not by callers) ---
        successful = result["successful"]
        failed = result["failed"]
        total_cost = result["total_cost_cents"]

        # Aggregate international row-level data onto job
        intl_rows = (
            db_session.query(JobRow)
            .filter(
                JobRow.job_id == job_id,
                JobRow.destination_country.isnot(None),
            )
            .all()
        )
        intl_count = sum(
            1 for r in intl_rows
            if r.destination_country not in (DEFAULT_ORIGIN_COUNTRY, "PR")
        )
        intl_duties = sum(r.duties_taxes_cents or 0 for r in intl_rows)

        # Final job update — status, counters, timestamps
        final_status = "completed" if failed == 0 else "failed"
        job.processed_rows = successful + failed
        job.successful_rows = successful
        job.failed_rows = failed
        job.total_cost_cents = total_cost
        job.international_row_count = intl_count
        job.total_duties_taxes_cents = intl_duties if intl_duties > 0 else None
        job.status = final_status
        job.completed_at = datetime.now(UTC).isoformat()
        db_session.commit()

        logger.info(
            "Batch execution complete for job %s: %d successful, %d failed, "
            "$%.2f total, %d international rows",
            job_id, successful, failed, total_cost / 100, intl_count,
        )
        DecisionAuditService.log_event(
            run_id=run_id,
            phase="execution",
            event_name="execution.batch.completed",
            actor="system",
            payload={
                "job_id": job_id,
                "successful": successful,
                "failed": failed,
                "processed_rows": successful + failed,
                "total_cost_cents": total_cost,
                "international_row_count": intl_count,
                "total_duties_taxes_cents": intl_duties,
                "status": final_status,
            },
        )

        return {
            "successful": successful,
            "failed": failed,
            "total_cost_cents": total_cost,
            "status": final_status,
            "international_row_count": intl_count,
            "total_duties_taxes_cents": intl_duties,
        }

    except Exception as e:
        logger.exception("Batch execution failed for job %s: %s", job_id, e)
        DecisionAuditService.log_event(
            run_id=run_id,
            phase="error",
            event_name="execution.batch.failed",
            actor="system",
            payload={"job_id": job_id, "error": str(e)},
        )
        # Update job to failed status
        job = db_session.query(Job).filter(Job.id == job_id).first()
        if job and job.status == "running":
            job.status = "failed"
            job.error_code = "E-4001"
            job.error_message = str(e)
            db_session.commit()
        raise
