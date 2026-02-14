"""Deterministic SDK tools for the orchestration agent.

Each tool wraps an existing service with a thin interface returning
MCP-compatible response dicts. No tool calls the LLM internally —
all operations are deterministic.

Tool response format:
    {"isError": False, "content": [{"type": "text", "text": "..."}]}
    {"isError": True,  "content": [{"type": "text", "text": "error msg"}]}

Example:
    result = await get_source_info_tool({})
    defs = get_all_tool_definitions()
"""

import json
import logging
import os
from typing import Any

import sqlglot

from src.db.connection import get_db_context
from src.services.column_mapping import translate_service_name
from src.services.job_service import JobService

# Import shared internals from tools/core
from src.orchestrator.agent.tools.core import (
    EventEmitterBridge,
    SERVICE_CODE_NAMES,
    _bind_bridge,
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
    _reset_ups_client,
    _store_fetched_rows,
    get_data_gateway,
    get_external_sources_client,
    shutdown_cached_ups_client,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Source Tools
# ---------------------------------------------------------------------------


async def get_source_info_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Get metadata about the currently connected data source.

    Args:
        args: Empty dict (no arguments needed).

    Returns:
        Tool response with source_type, file_path, row_count, column count.
    """
    gw = await get_data_gateway()
    info = await gw.get_source_info()
    if info is None:
        return _err(
            "No data source connected. Ask the user to connect a CSV, Excel, or database source."
        )

    return _ok(
        {
            "source_type": info.get("source_type"),
            "file_path": info.get("path"),
            "row_count": info.get("row_count", 0),
            "column_count": len(info.get("columns", [])),
        }
    )


async def get_schema_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Get the column schema of the currently connected data source.

    Args:
        args: Empty dict (no arguments needed).

    Returns:
        Tool response with list of column definitions.
    """
    gw = await get_data_gateway()
    info = await gw.get_source_info()
    if info is None:
        return _err("No data source connected.")

    columns = [
        {"name": col["name"], "type": col["type"], "nullable": col.get("nullable", True)}
        for col in info.get("columns", [])
    ]
    return _ok({"columns": columns})


async def fetch_rows_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Fetch rows from the connected data source with optional SQL filter.

    Args:
        args: Dict with optional 'where_clause' (str) and 'limit' (int).

    Returns:
        Tool response with matched rows and count.
    """
    gw = await get_data_gateway()
    where_clause = args.get("where_clause")
    limit = args.get("limit", 250)
    include_rows = bool(args.get("include_rows", False))

    try:
        rows = await gw.get_rows_by_filter(where_clause=where_clause, limit=limit)
        fetch_id = _store_fetched_rows(rows, bridge=bridge)
        payload: dict[str, Any] = {
            "fetch_id": fetch_id,
            "row_count": len(rows),
            "sample_rows": rows[:2],
            "message": "Use fetch_id with add_rows_to_job. Avoid passing full rows through the model.",
        }
        if include_rows:
            payload["rows"] = rows
        return _ok(payload)
    except Exception as e:
        logger.error("fetch_rows_tool failed: %s", e)
        return _err(f"Failed to fetch rows: {e}")


# ---------------------------------------------------------------------------
# Filter Validation Tool
# ---------------------------------------------------------------------------


async def validate_filter_syntax_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Validate SQL WHERE clause syntax using sqlglot.

    Args:
        args: Dict with 'where_clause' (str).

    Returns:
        Tool response with valid=True/False and optional error message.
    """
    where_clause = args.get("where_clause", "")
    try:
        sqlglot.parse(f"SELECT * FROM t WHERE {where_clause}")
        return _ok({"valid": True, "where_clause": where_clause})
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError) as e:
        return _ok({"valid": False, "error": str(e), "where_clause": where_clause})


# ---------------------------------------------------------------------------
# Job Management Tools
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Batch Processing Tools
# ---------------------------------------------------------------------------


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
    from src.services.ups_payload_builder import build_shipper_from_env

    account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "")
    shipper = build_shipper_from_env()
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
    from src.services.ups_payload_builder import build_shipper_from_env

    account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "")
    shipper = build_shipper_from_env()
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
    row_map = {i: row for i, row in enumerate(normalized_rows, start=1)}
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
        from src.services.ups_payload_builder import build_shipper_from_env

        account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "")
        shipper = build_shipper_from_env()
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


# ---------------------------------------------------------------------------
# Interactive Shipping Tools
# ---------------------------------------------------------------------------

_SHIP_FROM_KEY_MAP: dict[str, str] = {
    "name": "name",
    "phone": "phone",
    "address1": "addressLine1",
    "address_line1": "addressLine1",
    "addressLine1": "addressLine1",
    "city": "city",
    "state": "stateProvinceCode",
    "state_province_code": "stateProvinceCode",
    "stateProvinceCode": "stateProvinceCode",
    "zip": "postalCode",
    "postal_code": "postalCode",
    "postalCode": "postalCode",
    "country": "countryCode",
    "country_code": "countryCode",
    "countryCode": "countryCode",
}


def _normalize_ship_from(raw: dict[str, Any]) -> dict[str, str]:
    """Normalize agent-facing ship_from keys and values to canonical shipper format.

    Accepts any of the mapped key variants and produces the exact keys
    expected by downstream functions (build_shipment_request, ShipperInfo).
    Values are coerced to str and normalized:
    - phone -> normalize_phone() (strip non-digits, ensure 10-digit format)
    - postalCode -> normalize_zip() (strip to 5-digit or 5+4 format)
    Unknown keys are silently dropped. Empty values are skipped.

    Args:
        raw: Agent-provided ship_from override dict.

    Returns:
        Dict with canonical shipper keys and normalized values.
    """
    from src.services.ups_payload_builder import normalize_phone, normalize_zip

    normalized: dict[str, str] = {}
    for k, v in raw.items():
        canonical = _SHIP_FROM_KEY_MAP.get(k)
        if canonical and v:
            v = str(v).strip()
            if not v:
                continue
            if canonical == "phone":
                result = normalize_phone(v)
                if result == "5555555555":
                    continue  # skip invalid phone override
                v = result
            elif canonical == "postalCode":
                v = normalize_zip(v)
            normalized[canonical] = v
    return normalized


def _mask_account(acct: str) -> str:
    """Mask a UPS account number for display.

    Args:
        acct: Raw account number string.

    Returns:
        Masked string showing only first 2 and last 2 characters.
    """
    if len(acct) <= 4:
        return "****"
    return acct[:2] + "*" * (len(acct) - 4) + acct[-2:]


async def preview_interactive_shipment_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Preview a single interactive shipment with auto-populated shipper.

    Resolves shipper from env vars (with optional overrides), creates a Job
    with is_interactive=True, rates the shipment, and emits a preview_ready
    SSE event for the frontend InteractivePreviewCard.

    Args:
        args: Dict with ship_to fields, optional service/weight/ship_from override.

    Returns:
        Tool response with preview data or error.
    """
    from src.db.models import JobStatus
    from src.services.batch_engine import BatchEngine
    from src.services.ups_payload_builder import (
        build_shipment_request,
        build_shipper_from_env,
        resolve_packaging_code,
        resolve_service_code,
    )

    # Safe coercion: None → "", non-string → str, then strip
    def _str(val: Any, default: str = "") -> str:
        if val is None:
            return default
        return str(val).strip()

    # Required fields
    ship_to_name = _str(args.get("ship_to_name"))
    ship_to_address1 = _str(args.get("ship_to_address1"))
    ship_to_city = _str(args.get("ship_to_city"))
    ship_to_state = _str(args.get("ship_to_state"))
    ship_to_zip = _str(args.get("ship_to_zip"))
    command = _str(args.get("command"))

    if not all([ship_to_name, ship_to_address1, ship_to_city, ship_to_state, ship_to_zip]):
        return _err(
            "Missing required fields: ship_to_name, ship_to_address1, "
            "ship_to_city, ship_to_state, ship_to_zip are all required."
        )

    # Optional fields
    ship_to_address2 = _str(args.get("ship_to_address2"))
    ship_to_phone = _str(args.get("ship_to_phone"))
    ship_to_country = _str(args.get("ship_to_country"), "US") or "US"
    service = _str(args.get("service"), "Ground")
    raw_packaging = args.get("packaging_type")
    packaging_type = str(raw_packaging).strip() if raw_packaging is not None else None

    # Validate weight — coerce safely, return structured error on bad input
    try:
        weight = float(args.get("weight", 1.0))
        if weight <= 0:
            return _err("Weight must be a positive number.")
    except (ValueError, TypeError):
        return _err(
            f"Invalid weight value: {args.get('weight')!r}. "
            "Provide a numeric weight in pounds (e.g., 1.0, 5, 10.5)."
        )

    # Config guard: ensure UPS account number is set
    account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "").strip()
    if not account_number:
        return _err(
            "UPS_ACCOUNT_NUMBER environment variable is not set. "
            "Configure it in your .env file before using interactive shipping."
        )

    # Resolve shipper from env, overlay optional overrides
    shipper = build_shipper_from_env()
    ship_from_override = args.get("ship_from")
    if isinstance(ship_from_override, dict) and ship_from_override:
        normalized_overrides = _normalize_ship_from(ship_from_override)
        for k, v in normalized_overrides.items():
            if v:
                shipper[k] = v

    # Resolve service code
    service_code = resolve_service_code(service)

    # Construct order_data with canonical keys.
    # Store raw packaging_type (not pre-resolved) — build_packages() in
    # ups_payload_builder.py handles the single canonical resolve.  This
    # prevents double-resolution that corrupts alphanumeric codes (2a/2b/2c).
    order_data: dict[str, Any] = {
        "ship_to_name": ship_to_name,
        "ship_to_address1": ship_to_address1,
        "ship_to_city": ship_to_city,
        "ship_to_state": ship_to_state,
        "ship_to_postal_code": ship_to_zip,
        "ship_to_country": ship_to_country,
        "service_code": service_code,
        "weight": weight,
        "packaging_type": packaging_type,
    }
    if ship_to_address2:
        order_data["ship_to_address2"] = ship_to_address2
    if ship_to_phone:
        order_data["ship_to_phone"] = ship_to_phone

    # Create Job with interactive flag
    try:
        with get_db_context() as db:
            job_service = JobService(db)
            job = job_service.create_job(
                name=f"Ship to {ship_to_name}",
                original_command=command or f"Ship to {ship_to_name}",
            )
            job.is_interactive = True
            job.shipper_json = json.dumps(shipper)
            db.commit()

            # Create single row
            try:
                job_service.create_rows(
                    job.id,
                    _build_job_row_data([order_data]),
                )
            except Exception as e:
                try:
                    job_service.delete_job(job.id)
                except Exception as cleanup_err:
                    logger.warning(
                        "interactive preview cleanup failed for job %s: %s",
                        job.id,
                        cleanup_err,
                    )
                logger.error("interactive preview create_rows failed: %s", e)
                return _err(f"Failed to create shipment row: {e}")

            # Rate via BatchEngine preview
            ups = await _get_ups_client()
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
                job_service.update_status(job.id, JobStatus.failed)
                logger.error("interactive preview rate failed for job %s: %s", job.id, e)
                return _err(f"Rating failed for job {job.id}: {e}")

            job_id = job.id

    except Exception as e:
        logger.error("preview_interactive_shipment failed: %s", e)
        return _err(f"Failed to create interactive shipment: {e}")

    # Enrich preview rows
    preview_rows = result.get("preview_rows", [])
    row_map = {1: order_data}
    _enrich_preview_rows_from_map(preview_rows, row_map)
    rows_with_warnings = sum(1 for r in preview_rows if r.get("warnings"))
    result["rows_with_warnings"] = rows_with_warnings

    # Build resolved payload for expandable view
    try:
        resolved_payload = build_shipment_request(
            order_data=order_data,
            shipper=shipper,
            service_code=service_code,
        )
    except Exception:
        resolved_payload = {}

    # Add interactive metadata to result
    result["interactive"] = True
    result["shipper"] = shipper
    result["ship_to"] = {
        "name": ship_to_name,
        "address1": ship_to_address1,
        "address2": ship_to_address2,
        "city": ship_to_city,
        "state": ship_to_state,
        "postal_code": ship_to_zip,
        "country": ship_to_country,
        "phone": ship_to_phone,
    }
    result["account_number"] = _mask_account(account_number)
    result["service_name"] = SERVICE_CODE_NAMES.get(service_code, f"UPS Service {service_code}")
    result["service_code"] = service_code
    result["weight_lbs"] = weight
    result["packaging_type"] = resolve_packaging_code(packaging_type)
    result["resolved_payload"] = resolved_payload

    return _emit_preview_ready(
        result=result,
        rows_with_warnings=rows_with_warnings,
        bridge=bridge,
        job_id_override=job_id,
    )


# ---------------------------------------------------------------------------
# Platform Tools
# ---------------------------------------------------------------------------


async def get_platform_status_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Check which external platforms are connected.

    Args:
        args: Empty dict (no arguments needed).

    Returns:
        Tool response with platform connection statuses.
    """
    import os

    platforms: dict[str, Any] = {}

    # Report the authoritative data source status via gateway.
    # Shopify connection is only meaningful when its data has been imported
    # into DuckDB via the gateway. Env vars alone are not sufficient
    # because the agent queries DuckDB, not the Shopify API directly.
    try:
        gw = await get_data_gateway()
        source_info = await gw.get_source_info()
        if source_info:
            platforms["data_source"] = {
                "connected": True,
                "source_type": source_info.get("source_type"),
                "label": source_info.get("path"),
                "row_count": source_info.get("row_count", 0),
                "column_count": len(source_info.get("columns", [])),
            }
            # Shopify is connected only if it is the active data source.
            if source_info.get("source_type") == "shopify":
                store_domain = os.environ.get("SHOPIFY_STORE_DOMAIN", "")
                store_name = store_domain.replace(".myshopify.com", "")
                platforms["shopify"] = {
                    "connected": True,
                    "shop_name": store_name,
                    "store_domain": store_domain,
                }
            else:
                # Shopify env vars may be set but data isn't loaded yet.
                access_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
                store_domain = os.environ.get("SHOPIFY_STORE_DOMAIN")
                platforms["shopify"] = {
                    "connected": False,
                    "configured": bool(access_token and store_domain),
                    "note": "Shopify credentials found but another source is active",
                }
        else:
            platforms["data_source"] = {"connected": False}
            # Check if Shopify is at least configured.
            access_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
            store_domain = os.environ.get("SHOPIFY_STORE_DOMAIN")
            platforms["shopify"] = {
                "connected": False,
                "configured": bool(access_token and store_domain),
            }
    except Exception:
        platforms["data_source"] = {"connected": False}
        platforms["shopify"] = {"connected": False}

    return _ok({"platforms": platforms})


async def connect_shopify_tool(
    args: dict[str, Any],
    bridge: "EventEmitterBridge | None" = None,
) -> dict[str, Any]:
    """Connect to Shopify and import orders as active data source.

    Reads SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN from env.
    Calls ExternalSourcesMCPClient to connect + fetch, then
    DataSourceGateway to import records.

    Args:
        args: Empty dict (credentials read from env).
        bridge: Optional event emitter bridge.

    Returns:
        MCP tool response dict.
    """
    access_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    store_domain = os.environ.get("SHOPIFY_STORE_DOMAIN")

    if not access_token or not store_domain:
        return _err(
            "Shopify credentials not configured. Set SHOPIFY_ACCESS_TOKEN "
            "and SHOPIFY_STORE_DOMAIN environment variables."
        )

    ext = await get_external_sources_client()

    # Connect
    connect_result = await ext.connect_platform(
        platform="shopify",
        credentials={"access_token": access_token},
        store_url=f"https://{store_domain}",
    )
    if not connect_result.get("success"):
        return _err(
            f"Failed to connect to Shopify: "
            f"{connect_result.get('error', 'Unknown error')}"
        )

    # Fetch orders
    orders_result = await ext.fetch_orders("shopify", limit=250)
    if not orders_result.get("success"):
        return _err(
            f"Failed to fetch Shopify orders: "
            f"{orders_result.get('error', 'Unknown error')}"
        )

    orders = orders_result.get("orders", [])
    if not orders:
        return _err("No orders found in Shopify store.")

    # Flatten orders for import (exclude nested objects)
    flat_orders = []
    for o in orders:
        flat = {
            k: v
            for k, v in o.items()
            if k not in ("items", "raw_data") and v is not None
        }
        flat_orders.append(flat)

    # Import via gateway
    gw = await get_data_gateway()
    import_result = await gw.import_from_records(flat_orders, "shopify")

    count = import_result.get("row_count", len(flat_orders))
    return _ok({
        "message": (
            f"Connected to Shopify and imported {count} orders "
            f"as active data source."
        ),
        "platform": "shopify",
        "orders_imported": count,
    })


# ---------------------------------------------------------------------------
# Tool Definitions Registry
# ---------------------------------------------------------------------------


def get_all_tool_definitions(
    event_bridge: EventEmitterBridge | None = None,
    interactive_shipping: bool = False,
) -> list[dict[str, Any]]:
    """Return all tool definitions for the orchestration agent.

    Each definition includes name, description, input_schema, and handler.

    Returns:
        List of tool definition dicts.
    """
    bridge = event_bridge or EventEmitterBridge()
    definitions = [
        {
            "name": "get_source_info",
            "description": "Get metadata about the currently connected data source (type, path, row count).",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
            "handler": get_source_info_tool,
        },
        {
            "name": "get_schema",
            "description": "Get the column schema (names, types) of the connected data source.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
            "handler": get_schema_tool,
        },
        {
            "name": "ship_command_pipeline",
            "description": (
                "Fast shipping pipeline for straightforward commands. "
                "This tool fetches rows, creates a job, stores rows, and "
                "generates the preview in one call."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "where_clause": {
                        "type": "string",
                        "description": (
                            "Optional SQL WHERE clause without the 'WHERE' keyword. "
                            "Omit to ship all rows."
                        ),
                    },
                    "command": {
                        "type": "string",
                        "description": "Original user shipping command.",
                    },
                    "job_name": {
                        "type": "string",
                        "description": "Optional human-readable job name.",
                    },
                    "service_code": {
                        "type": "string",
                        "description": "Optional UPS service code (e.g., 03 for Ground).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows to fetch (default 250).",
                        "default": 250,
                    },
                },
                "required": ["command"],
            },
            "handler": _bind_bridge(ship_command_pipeline_tool, bridge),
        },
        {
            "name": "fetch_rows",
            "description": (
                "Fetch rows from the data source and return a compact fetch_id "
                "reference for downstream tools. Avoid sending full row arrays "
                "through model context unless explicitly needed."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "where_clause": {
                        "type": "string",
                        "description": "SQL WHERE clause without the 'WHERE' keyword. Omit for all rows.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows to return (default 250).",
                        "default": 250,
                    },
                    "include_rows": {
                        "type": "boolean",
                        "description": (
                            "Set true only when full row objects are strictly "
                            "needed in the response. Default false for speed."
                        ),
                        "default": False,
                    },
                },
            },
            "handler": _bind_bridge(fetch_rows_tool, bridge),
        },
        {
            "name": "validate_filter_syntax",
            "description": "Validate a SQL WHERE clause for syntax correctness before using it.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "where_clause": {
                        "type": "string",
                        "description": "SQL WHERE clause to validate.",
                    },
                },
                "required": ["where_clause"],
            },
            "handler": validate_filter_syntax_tool,
        },
        {
            "name": "create_job",
            "description": "Create a new shipping job in the state database.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Human-readable job name.",
                    },
                    "command": {
                        "type": "string",
                        "description": "The original user command.",
                    },
                },
                "required": ["name", "command"],
            },
            "handler": create_job_tool,
        },
        {
            "name": "add_rows_to_job",
            "description": (
                "Add fetched rows to a job. Call this AFTER create_job and "
                "BEFORE batch_preview. Prefer passing fetch_id from fetch_rows "
                "instead of full rows for faster execution."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job UUID from create_job.",
                    },
                    "rows": {
                        "type": "array",
                        "description": (
                            "Optional full row array from fetch_rows. Prefer fetch_id."
                        ),
                        "items": {"type": "object"},
                    },
                    "fetch_id": {
                        "type": "string",
                        "description": (
                            "Preferred compact reference returned by fetch_rows."
                        ),
                    },
                },
                "required": ["job_id"],
            },
            "handler": _bind_bridge(add_rows_to_job_tool, bridge),
        },
        {
            "name": "get_job_status",
            "description": "Get the summary and progress of a job.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job UUID.",
                    },
                },
                "required": ["job_id"],
            },
            "handler": get_job_status_tool,
        },
        {
            "name": "batch_preview",
            "description": "Run batch preview (rate all rows) for a job. Shows estimated costs before execution.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job UUID to preview.",
                    },
                },
                "required": ["job_id"],
            },
            "handler": _bind_bridge(batch_preview_tool, bridge),
        },
        {
            "name": "batch_execute",
            "description": "Execute a confirmed batch job (create shipments). Requires user approval.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job UUID to execute.",
                    },
                    "approved": {
                        "type": "boolean",
                        "description": "Must be True — set only after user confirms the preview.",
                    },
                },
                "required": ["job_id", "approved"],
            },
            "handler": batch_execute_tool,
        },
        {
            "name": "get_platform_status",
            "description": "Check which external platforms (Shopify, etc.) are connected.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
            "handler": get_platform_status_tool,
        },
        {
            "name": "connect_shopify",
            "description": (
                "Connect to Shopify using env credentials, fetch orders, "
                "and import them as the active data source. Call this when "
                "no data source is active and Shopify env vars are configured."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
            },
            "handler": _bind_bridge(connect_shopify_tool, bridge),
        },
    ]

    if not interactive_shipping:
        return definitions

    # In interactive mode, expose only status tools + interactive preview
    interactive_allowed = {"get_job_status", "get_platform_status", "preview_interactive_shipment"}
    interactive_defs = [d for d in definitions if d["name"] in interactive_allowed]

    # Add the preview_interactive_shipment tool definition
    interactive_defs.append(
        {
            "name": "preview_interactive_shipment",
            "description": (
                "Preview a single interactive shipment. Auto-populates shipper from "
                "config, rates the shipment, creates a Job record, and displays "
                "the InteractivePreviewCard for user confirmation."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "ship_to_name": {
                        "type": "string",
                        "description": "Recipient full name.",
                    },
                    "ship_to_address1": {
                        "type": "string",
                        "description": "Recipient street address line 1.",
                    },
                    "ship_to_address2": {
                        "type": "string",
                        "description": "Recipient street address line 2 (optional).",
                    },
                    "ship_to_city": {
                        "type": "string",
                        "description": "Recipient city.",
                    },
                    "ship_to_state": {
                        "type": "string",
                        "description": "Recipient state/province code (e.g. CA, NY).",
                    },
                    "ship_to_zip": {
                        "type": "string",
                        "description": "Recipient postal/ZIP code.",
                    },
                    "ship_to_phone": {
                        "type": "string",
                        "description": "Recipient phone number (optional).",
                    },
                    "ship_to_country": {
                        "type": "string",
                        "description": "Recipient country code (default US).",
                        "default": "US",
                    },
                    "service": {
                        "type": "string",
                        "description": "UPS service name or code (default Ground).",
                        "default": "Ground",
                    },
                    "weight": {
                        "type": "number",
                        "description": "Package weight in lbs (default 1.0).",
                        "default": 1.0,
                    },
                    "packaging_type": {
                        "type": "string",
                        "description": "UPS packaging type name or code (optional).",
                    },
                    "command": {
                        "type": "string",
                        "description": "Original user command text.",
                    },
                    "ship_from": {
                        "type": "object",
                        "description": (
                            "Optional shipper address overrides. Accepts keys: "
                            "name, phone, address1, city, state, zip, country. "
                            "Overrides are merged on top of env-configured defaults."
                        ),
                    },
                },
                "required": [
                    "ship_to_name",
                    "ship_to_address1",
                    "ship_to_city",
                    "ship_to_state",
                    "ship_to_zip",
                    "command",
                ],
            },
            "handler": _bind_bridge(preview_interactive_shipment_tool, bridge),
        },
    )

    return interactive_defs
