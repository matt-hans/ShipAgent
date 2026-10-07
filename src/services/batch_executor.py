"""Shared batch execution service.

Extracts the canonical execute-batch flow from preview.py so both
HTTP routes and InProcessRunner call the same code path. This is
the SINGLE source of truth for batch execution orchestration.

Callers provide a progress_callback to adapt events to their
transport (SSE for HTTP, Rich for CLI, logging for watchdog).
"""

import asyncio
import json
import logging
import os
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update

from src.db.models import Job, JobRow, RowStatus
from src.errors.terminal_diagnostics import project_terminal_diagnostic
from src.services.batch_engine import BatchEngine
from src.services.decision_audit_service import DecisionAuditService
from src.services.job_progress_projection import (
    AuthoritativeJobProgress,
    project_authoritative_job_progress,
)
from src.services.ups_mcp_client import UPSMCPClient

logger = logging.getLogger(__name__)

# Type for progress callback: async def(event_type: str, **kwargs) -> None
ProgressCallback = Callable[..., Coroutine[Any, Any, None]]


class BatchConfirmationError(ValueError):
    """A safe domain rejection that an entry-point adapter can translate."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def confirm_batch(
    job_id: str,
    db: Any,
    *,
    write_back_enabled: bool | None = None,
    selected_service_code: str | None = None,
) -> tuple[Job, str | None]:
    """Validate the entire confirmation, then claim the pending job atomically."""
    from src.services.batch_preview import get_priced_preview, preview_checksum
    from src.services.ups_service_codes import resolve_service_code

    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        raise BatchConfirmationError("not_found", f"Job not found: {job_id}")
    if job.status != "pending":
        raise BatchConfirmationError(
            "invalid",
            f"Job cannot be confirmed. Current status: {job.status}. Only pending jobs can be confirmed.",
        )
    if selected_service_code is not None:
        if not job.is_interactive:
            raise BatchConfirmationError(
                "invalid",
                "selected_service_code is only valid for interactive shipment jobs.",
            )
        selected_service_code = resolve_service_code(
            str(selected_service_code).strip(), default=""
        )
        if not selected_service_code:
            raise BatchConfirmationError("invalid", "Invalid selected_service_code.")
    if not job.preview_hash:
        raise BatchConfirmationError(
            "invalid",
            "Job must be previewed before confirmation. Re-preview to review valid costs.",
        )
    rows = (
        db.query(JobRow)
        .filter(JobRow.job_id == job_id)
        .order_by(JobRow.row_number)
        .all()
    )
    if preview_checksum(rows) != job.preview_hash:
        raise BatchConfirmationError(
            "stale",
            "Job data has changed since preview. Please re-preview before confirming.",
        )
    priced = get_priced_preview(db, job, rows)
    if priced is None or not priced["confirmation_ready"]:
        raise BatchConfirmationError(
            "invalid",
            "Job must be previewed with valid costs before confirmation. Please re-preview.",
        )

    claimed = db.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == "pending",
            Job.preview_hash == job.preview_hash,
        )
        .values(
            status="running",
            started_at=datetime.now(UTC).isoformat(),
            write_back_enabled=bool(
                (
                    job.write_back_enabled
                    if write_back_enabled is None
                    else write_back_enabled
                )
                and not job.is_interactive
            ),
        )
    )
    db.commit()
    if claimed.rowcount != 1:
        raise BatchConfirmationError(
            "invalid",
            "Job cannot be confirmed (concurrent modification). Another request may have already confirmed this job.",
        )
    db.refresh(job)
    return job, selected_service_code


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
                (
                    c.get("platform")
                    if isinstance(c, dict)
                    else getattr(c, "platform", None)
                )
                == "shopify"
                and (
                    c.get("status")
                    if isinstance(c, dict)
                    else getattr(c, "status", None)
                )
                == "connected"
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
                            "Using shipper from Shopify store: %s",
                            shop_info.get("name"),
                        )
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
    service_code_override: str | None = None,
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

    def _sync_authoritative_progress() -> AuthoritativeJobProgress:
        all_rows = (
            db_session.query(JobRow)
            .filter(JobRow.job_id == job_id)
            .order_by(JobRow.row_number)
            .all()
        )
        progress = project_authoritative_job_progress(job, all_rows)
        job.total_rows = progress.total_rows
        job.processed_rows = progress.processed_rows
        job.successful_rows = progress.successful_rows
        job.failed_rows = progress.failed_rows
        job.total_cost_cents = progress.total_cost_cents
        job.total_duties_taxes_cents = progress.total_duties_taxes_cents or None
        job.international_row_count = progress.international_row_count
        return progress

    try:
        shipper = await get_shipper_for_job(job)

        # Resolve UPS credentials via runtime adapter (DB priority, env fallback)
        from src.services.runtime_credentials import resolve_ups_credentials

        ups_creds = resolve_ups_credentials()
        if ups_creds is None:
            raise RuntimeError(
                "No UPS credentials configured. Open Settings to connect UPS."
            )

        logger.info("Batch execution using UPS environment=%s", ups_creds.environment)
        account_number = ups_creds.account_number or os.environ.get(
            "UPS_ACCOUNT_NUMBER", ""
        )

        async with UPSMCPClient(
            client_id=ups_creds.client_id,
            client_secret=ups_creds.client_secret,
            environment=ups_creds.environment,
            account_number=account_number,
        ) as ups:
            engine = BatchEngine(
                ups_service=ups,
                db_session=db_session,
                account_number=account_number,
            )

            async def _progress_adapter(event_type: str, **kwargs) -> None:
                _sync_authoritative_progress()
                db_session.commit()

                if on_progress:
                    await on_progress(event_type, **kwargs)

            result = await engine.execute(
                job_id=job_id,
                rows=rows,
                shipper=shipper,
                service_code=service_code_override,
                on_progress=_progress_adapter,
                write_back_enabled=getattr(job, "write_back_enabled", True),
            )

        # --- Final status + aggregation (owned here, not by callers) ---
        progress = _sync_authoritative_progress()
        successful = progress.successful_rows
        failed = progress.failed_rows
        total_cost = progress.total_cost_cents
        intl_count = progress.international_row_count
        intl_duties = progress.total_duties_taxes_cents

        # Final job update — status, counters, timestamps.
        # Surface write-back failures so users know tracking numbers
        # weren't persisted back to source files (M-2, CWE-391).
        write_back = result.get("write_back", {})
        wb_status = write_back.get("status", "skipped")
        if failed == 0 and wb_status in ("error", "partial"):
            final_status = "completed_with_warnings"
            diagnostic = project_terminal_diagnostic(
                write_back.get("error_code", "E-4001")
            )
            job.error_code = diagnostic.error_code
            job.error_message = diagnostic.message
            raw_failure_count = write_back.get("failure_count")
            failure_count = (
                raw_failure_count
                if isinstance(raw_failure_count, int)
                and not isinstance(raw_failure_count, bool)
                and 0 <= raw_failure_count <= successful
                else 1
            )
            logger.warning(
                "batch_execution_warning action=write_back "
                "error_code=%s failure_count=%d",
                diagnostic.error_code,
                failure_count,
            )
        elif failed == 0:
            final_status = "completed"
        else:
            final_status = "failed"

        # Flush counters separately from the conditional terminal transition.
        # Cancellation can land while the last accepted carrier call completes.
        db_session.flush()
        db_session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "running")
            .values(status=final_status, completed_at=datetime.now(UTC).isoformat())
        )
        db_session.commit()
        db_session.refresh(job)
        final_status = job.status

        logger.info(
            "Batch execution complete for job %s: %d successful, %d failed, "
            "$%.2f total, %d international rows",
            job_id,
            successful,
            failed,
            total_cost / 100,
            intl_count,
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

    except asyncio.CancelledError:
        # The engine reconciles accepted calls before gather propagates cancellation.
        # Preserve completed rows, expose uncertain rows, and stop future launches.
        _sync_authoritative_progress()
        db_session.flush()
        db_session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "running")
            .values(status="cancelled", completed_at=datetime.now(UTC).isoformat())
        )
        db_session.commit()
        raise
    except Exception:
        logger.error("Batch execution failed for job %s", job_id)
        DecisionAuditService.log_event(
            run_id=run_id,
            phase="error",
            event_name="execution.batch.failed",
            actor="system",
            payload={"job_id": job_id, "error_code": "E-4001"},
        )
        _sync_authoritative_progress()
        db_session.flush()
        db_session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "running")
            .values(
                status="failed",
                error_code="E-4001",
                error_message="The row could not be processed because of a system error.",
                completed_at=datetime.now(UTC).isoformat(),
            )
        )
        db_session.commit()
        raise
