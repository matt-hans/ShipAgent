"""Batch pipeline tool handlers.

Handles the shipping command pipeline, job creation, row management,
batch preview, and batch execution.
"""

import json
import logging
import os
from typing import Any

from src.db.connection import get_db_context
from src.mcp.data_source.models import SOURCE_ROW_NUM_COLUMN
from src.services.job_service import JobService
from src.services.ups_service_codes import translate_service_name

from src.orchestrator.agent.tools.core import (
    EventEmitterBridge,
    _build_job_row_data,
    _command_explicitly_requests_service,
    _consume_fetched_rows,
    _emit_event,
    _emit_preview_ready,
    _enrich_preview_rows,
    _enrich_preview_rows_from_map,
    _err,
    _get_ups_client,
    _normalize_rows_for_shipping,
    _ok,
    _persist_job_source_signature,
    _store_fetched_rows,
    get_data_gateway,
)
from src.services.errors import UPSServiceError

logger = logging.getLogger(__name__)


async def create_job_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Create a new job in the state database.

    Args:
        args: Dict with 'name' (str) and 'command' (str).

    Returns:
        Tool response with job_id and status.
    """
    name = args.get("name", "Untitled Job")
    command = args.get("command", "")

    try:
        with get_db_context() as db:
            svc = JobService(db)
            job = svc.create_job(name=name, original_command=command)
            await _persist_job_source_signature(job.id, db)
            return _ok({"job_id": job.id, "status": job.status})
    except Exception as e:
        logger.error("create_job_tool failed: %s", e)
        return _err(f"Failed to create job: {e}")


async def add_rows_to_job_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Add fetched rows to a job so batch preview and execution can process them.

    This bridges the gap between fetch_rows (which retrieves data) and
    batch_preview/batch_execute (which need rows stored in the job).

    Args:
        args: Dict with 'job_id' (str) and 'rows' (list of row dicts from fetch_rows).

    Returns:
        Tool response with rows_added count.
    """
    job_id = args.get("job_id", "")
    fetch_id = args.get("fetch_id", "")
    rows = args.get("rows", [])

    if not job_id:
        return _err("job_id is required")
    if fetch_id:
        cached_rows = _consume_fetched_rows(fetch_id, bridge=bridge)
        if cached_rows is None:
            return _err(
                "fetch_id not found or expired. Re-run fetch_rows and pass the new fetch_id.",
            )
        rows = cached_rows

    if not rows:
        return _err("Either fetch_id or non-empty rows list is required")

    try:
        with get_db_context() as db:
            svc = JobService(db)
            row_data = _build_job_row_data(rows)

            created = svc.create_rows(job_id, row_data)
            return _ok(
                {
                    "job_id": job_id,
                    "rows_added": len(created),
                }
            )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        logger.error("add_rows_to_job_tool failed: %s", e)
        return _err(f"Failed to add rows to job: {e}")


async def get_job_status_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Get the summary/status of a job.

    Args:
        args: Dict with 'job_id' (str).

    Returns:
        Tool response with job summary metrics.
    """
    job_id = args.get("job_id", "")
    if not job_id:
        return _err("job_id is required")

    try:
        with get_db_context() as db:
            svc = JobService(db)
            summary = svc.get_job_summary(job_id)
            return _ok(summary)
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        logger.error("get_job_status_tool failed: %s", e)
        return _err(f"Failed to get job status: {e}")


async def _run_batch_preview(job_id: str) -> dict[str, Any]:
    """Internal helper — run batch preview via BatchEngine.

    Separated for testability. In production this creates a BatchEngine
    with the cached UPSMCPClient (async MCP) and calls preview().

    Args:
        job_id: Job UUID.

    Returns:
        Preview result dict from BatchEngine.
    """
    from src.services.batch_engine import BatchEngine
    from src.services.ups_payload_builder import build_shipper

    account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "")
    shipper = build_shipper()
    ups = await _get_ups_client()

    with get_db_context() as db:
        engine = BatchEngine(
            ups_service=ups,
            db_session=db,
            account_number=account_number,
        )
        svc = JobService(db)
        rows = svc.get_rows(job_id)
        result = await engine.preview(
            job_id=job_id,
            rows=rows,
            shipper=shipper,
        )
    return result


async def ship_command_pipeline_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Fast-path pipeline for straightforward shipping commands.

    Performs fetch -> create job -> add rows -> preview in one tool call.
    """
    command = str(args.get("command", "")).strip()
    if not command:
        return _err("command is required")

    where_clause = args.get("where_clause")
    limit = int(args.get("limit", 250))
    job_name = str(args.get("job_name") or command or "Shipping Job")
    raw_service_code = args.get("service_code")
    service_code: str | None = None
    if raw_service_code:
        resolved = translate_service_name(str(raw_service_code))
        if _command_explicitly_requests_service(command):
            service_code = resolved
            logger.info(
                "ship_command_pipeline applying explicit service override=%s",
                service_code,
            )
        else:
            logger.info(
                "ship_command_pipeline ignoring implicit service_code=%s for "
                "command without explicit service; using row-level service data",
                raw_service_code,
            )

    gw = await get_data_gateway()
    try:
        fetched_rows = await gw.get_rows_by_filter(
            where_clause=where_clause,
            limit=limit,
        )
    except Exception as e:
        logger.error("ship_command_pipeline fetch failed: %s", e)
        return _err(f"Failed to fetch rows: {e}")

    if not fetched_rows:
        return _err("No rows matched the provided filter.")

    from src.services.batch_engine import BatchEngine
    from src.services.ups_payload_builder import build_shipper

    account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "")
    shipper = build_shipper()
    ups = await _get_ups_client()

    try:
        with get_db_context() as db:
            job_service = JobService(db)
            job = job_service.create_job(name=job_name, original_command=command)
            await _persist_job_source_signature(job.id, db)
            try:
                job_service.create_rows(
                    job.id,
                    _build_job_row_data(
                        fetched_rows,
                        service_code_override=service_code,
                    ),
                )
            except Exception as e:
                # Cleanup orphan job when rows fail to persist.
                try:
                    job_service.delete_job(job.id)
                except Exception as cleanup_err:
                    logger.warning(
                        "ship_command_pipeline cleanup failed for job %s: %s",
                        job.id,
                        cleanup_err,
                    )
                logger.error("ship_command_pipeline create_rows failed: %s", e)
                return _err(f"Failed to add rows to job: {e}")

            engine = BatchEngine(
                ups_service=ups,
                db_session=db,
                account_number=account_number,
            )
            db_rows = job_service.get_rows(job.id)
            try:
                result = await engine.preview(
                    job_id=job.id,
                    rows=db_rows,
                    shipper=shipper,
                    service_code=service_code,
                )
            except Exception as e:
                logger.error(
                    "ship_command_pipeline preview failed for %s: %s", job.id, e
                )
                return _err(f"Preview failed for job {job.id}: {e}")
    except Exception as e:
        logger.error("ship_command_pipeline create_job failed: %s", e)
        return _err(f"Failed to create job: {e}")

    preview_rows = result.get("preview_rows", [])
    normalized_rows = _normalize_rows_for_shipping(fetched_rows)
    if service_code:
        for row in normalized_rows:
            if isinstance(row, dict):
                row["service_code"] = service_code
    # Key row_map by source row number to match JobRow.row_number.
    # Check both _row_number and _source_row_num for compatibility.
    row_map = {}
    for idx, row in enumerate(normalized_rows, start=1):
        key = row.get("_row_number") or row.get(SOURCE_ROW_NUM_COLUMN) or idx
        row_map[key] = row
    _enrich_preview_rows_from_map(preview_rows, row_map)
    rows_with_warnings = sum(1 for row in preview_rows if row.get("warnings"))
    result["rows_with_warnings"] = rows_with_warnings

    return _emit_preview_ready(
        result=result,
        rows_with_warnings=rows_with_warnings,
        bridge=bridge,
    )


async def batch_preview_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Run batch preview (rate all rows) for a job.

    Emits a 'preview_ready' event to the frontend SSE queue so the
    PreviewCard renders, while still returning the result to the LLM
    for conversational context.

    Args:
        args: Dict with 'job_id' (str).

    Returns:
        Tool response with preview data (row count, estimated cost, etc.).
    """
    job_id = args.get("job_id", "")
    if not job_id:
        return _err("job_id is required")

    try:
        result = await _run_batch_preview(job_id)

        # Enrich rows for the frontend
        preview_rows = result.get("preview_rows", [])
        _enrich_preview_rows(job_id, preview_rows)

        # Count warnings after normalization
        rows_with_warnings = sum(1 for r in preview_rows if r.get("warnings"))
        result["rows_with_warnings"] = rows_with_warnings

        return _emit_preview_ready(
            result=result,
            rows_with_warnings=rows_with_warnings,
            bridge=bridge,
            job_id_override=job_id,
        )
    except Exception as e:
        logger.error("batch_preview_tool failed: %s", e)
        return _err(f"Batch preview failed: {e}")


async def batch_execute_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Execute a confirmed batch job (create shipments).

    Requires explicit approval. Returns error if approved is not True.

    Args:
        args: Dict with 'job_id' (str) and 'approved' (bool).

    Returns:
        Tool response with execution status, or error if not approved.
    """
    job_id = args.get("job_id", "")
    approved = args.get("approved", False)

    if not approved:
        return _err(
            "Batch execution requires user approval. "
            "Set approved=True only after the user has confirmed the preview."
        )

    if not job_id:
        return _err("job_id is required")

    try:
        from src.services.batch_engine import BatchEngine
        from src.services.ups_payload_builder import build_shipper

        account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "")
        shipper = build_shipper()
        ups = await _get_ups_client()

        with get_db_context() as db:
            engine = BatchEngine(
                ups_service=ups,
                db_session=db,
                account_number=account_number,
            )
            svc = JobService(db)
            rows = svc.get_rows(job_id)
            result = await engine.execute(
                job_id=job_id,
                rows=rows,
                shipper=shipper,
            )
        return _ok(result)
    except Exception as e:
        logger.error("batch_execute_tool failed: %s", e)
        return _err(f"Batch execution failed: {e}")


async def get_landed_cost_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Estimate duties, taxes, and fees for an international shipment.

    Emits a landed_cost_result event to the frontend.

    Args:
        args: Dict with currency_code, export_country_code,
              import_country_code, commodities, and optional kwargs.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with landed cost breakdown, or error envelope.
    """
    try:
        client = await _get_ups_client()
        result = await client.get_landed_cost(**args)
        payload = {"action": "landed_cost", "success": True, **result}
        _emit_event("landed_cost_result", payload, bridge=bridge)
        return _ok({"success": True, "action": "landed_cost", **result})
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in get_landed_cost_tool")
        return _err(f"Unexpected error: {e}")
