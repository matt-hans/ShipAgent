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

import asyncio
import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import sqlglot

from src.db.connection import get_db_context
from src.orchestrator.models.intent import SERVICE_ALIASES
from src.services.column_mapping import apply_mapping, auto_map_columns, translate_service_name, validate_mapping
from src.services.data_source_service import DataSourceService
from src.services.job_service import JobService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event Emission (module-level bridge to SSE queue)
# ---------------------------------------------------------------------------

# Module-level mutable reference for the event emitter callback.
# Using a simple module-level variable instead of contextvars.ContextVar
# because the SDK's in-process MCP server runs tool handlers in a context
# established during agent.start() — before set_event_emitter() is called.
# ContextVar changes after task creation are invisible to child tasks.
# Per-session locking in conversations.py ensures only one message
# processes at a time, making this safe for concurrent sessions.
_event_emitter_callback: Callable[[str, dict], None] | None = None

# Cache fetched row sets so the agent can pass compact fetch_id values
# between tools instead of large row arrays through model context.
_fetched_rows_cache: dict[str, list[dict[str, Any]]] = {}
_fetched_rows_order: list[str] = []
_MAX_FETCH_CACHE_ENTRIES = 20


def set_event_emitter(callback: Callable[[str, dict], None] | None) -> None:
    """Set or clear the event emitter callback.

    Called by conversations.py before/after agent message processing
    to bridge tool events to the SSE queue.

    Args:
        callback: Function accepting (event_type, data) to push SSE events,
                  or None to clear.
    """
    global _event_emitter_callback
    _event_emitter_callback = callback


def _emit_event(event_type: str, data: dict[str, Any]) -> None:
    """Emit a structured event to the frontend via the module-level callback.

    No-op if no emitter is set (e.g. in tests or non-SSE contexts).

    Args:
        event_type: SSE event name (e.g. "preview_ready").
        data: Event payload dict.
    """
    if _event_emitter_callback is not None:
        _event_emitter_callback(event_type, data)


def _store_fetched_rows(rows: list[dict[str, Any]]) -> str:
    """Store fetched rows in an in-memory cache and return a fetch_id."""
    fetch_id = str(uuid4())
    _fetched_rows_cache[fetch_id] = rows
    _fetched_rows_order.append(fetch_id)

    while len(_fetched_rows_order) > _MAX_FETCH_CACHE_ENTRIES:
        oldest = _fetched_rows_order.pop(0)
        _fetched_rows_cache.pop(oldest, None)
    return fetch_id


def _consume_fetched_rows(fetch_id: str) -> list[dict[str, Any]] | None:
    """Get and remove cached rows for a fetch_id."""
    rows = _fetched_rows_cache.pop(fetch_id, None)
    if fetch_id in _fetched_rows_order:
        _fetched_rows_order.remove(fetch_id)
    return rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(data: Any) -> dict[str, Any]:
    """Build a successful tool response.

    Args:
        data: Serializable data to return.

    Returns:
        MCP tool response dict with isError=False.
    """
    return {
        "isError": False,
        "content": [{"type": "text", "text": json.dumps(data, default=str)}],
    }


def _err(message: str) -> dict[str, Any]:
    """Build an error tool response.

    Args:
        message: Human-readable error message.

    Returns:
        MCP tool response dict with isError=True.
    """
    return {
        "isError": True,
        "content": [{"type": "text", "text": message}],
    }


def _get_data_source_service() -> DataSourceService:
    """Get the singleton DataSourceService instance.

    Returns:
        The active DataSourceService.
    """
    return DataSourceService.get_instance()


def _build_job_row_data(
    rows: list[dict[str, Any]],
    service_code_override: str | None = None,
) -> list[dict[str, Any]]:
    """Convert source rows into JobRow create payload with checksums.

    Args:
        rows: Source rows fetched from the connected data source.
        service_code_override: Optional UPS service code to force across all rows.
            When set, this value is persisted into each row's order_data so
            preview and execution use identical service selection.
    """
    normalized_rows = _normalize_rows_for_shipping(rows)
    if service_code_override:
        for row in normalized_rows:
            if isinstance(row, dict):
                row["service_code"] = service_code_override

    row_data = []
    for i, row in enumerate(normalized_rows, start=1):
        row_json = json.dumps(row, sort_keys=True, default=str)
        checksum = hashlib.md5(row_json.encode()).hexdigest()
        row_data.append({
            "row_number": i,
            "row_checksum": checksum,
            "order_data": row_json,
        })
    return row_data


def _normalize_rows_for_shipping(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize source rows into canonical order_data keys for UPS payloads.

    CSV/Excel imports often use arbitrary headers (e.g., "Recipient Name",
    "Address", "Zip"). This function auto-maps those headers into the
    canonical ship_to_* keys expected by build_shipment_request().
    """
    if not rows:
        return rows

    source_columns: list[str] = sorted({
        str(k)
        for row in rows
        if isinstance(row, dict)
        for k in row.keys()
    })
    mapping = auto_map_columns(source_columns)
    missing_required = validate_mapping(mapping)
    if missing_required:
        logger.warning(
            "Auto column mapping incomplete for %d rows: %s",
            len(rows),
            "; ".join(missing_required),
        )

    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            normalized.append(row)
            continue

        # Preserve original row fields for traceability, then overlay mapped
        # canonical keys used by payload builders.
        out: dict[str, Any] = dict(row)
        mapped = apply_mapping(mapping, row)
        for key, value in mapped.items():
            if value is not None and value != "":
                out[key] = value

        # Fallback name fields commonly present in CSV exports.
        if not out.get("ship_to_name"):
            for key in ("recipient_name", "customer_name", "name"):
                value = row.get(key)
                if value:
                    out["ship_to_name"] = value
                    break

        # Default country to US if absent.
        if not out.get("ship_to_country"):
            out["ship_to_country"] = "US"

        # Normalize service names/codes when present.
        if out.get("service_code"):
            out["service_code"] = translate_service_name(str(out["service_code"]))
        elif row.get("service"):
            out["service_code"] = translate_service_name(str(row["service"]))

        normalized.append(out)

    return normalized


def _command_explicitly_requests_service(command: str) -> bool:
    """Return True when the command text explicitly specifies a UPS service.

    This prevents accidental service overrides when the agent auto-fills a
    default service_code for commands like "ship all California orders".
    """
    text = command.lower()
    for alias in SERVICE_ALIASES:
        if alias in text:
            return True

    # Accept explicit numeric UPS service code mentions as user intent.
    return bool(re.search(r"\b(01|02|03|11|12|13|14|59)\b", text))


# ---------------------------------------------------------------------------
# Shared UPS MCP Client (module-level cache)
# ---------------------------------------------------------------------------

_ups_client: Any | None = None
_ups_client_lock = asyncio.Lock()


def _build_ups_client() -> Any:
    """Build a UPSMCPClient configured from environment variables."""
    from src.services.ups_mcp_client import UPSMCPClient

    base_url = os.environ.get("UPS_BASE_URL", "https://wwwcie.ups.com")
    environment = "test" if "wwwcie" in base_url else "production"

    return UPSMCPClient(
        client_id=os.environ.get("UPS_CLIENT_ID", ""),
        client_secret=os.environ.get("UPS_CLIENT_SECRET", ""),
        environment=environment,
        account_number=os.environ.get("UPS_ACCOUNT_NUMBER", ""),
    )


async def _get_ups_client() -> Any:
    """Get the cached UPSMCPClient, creating it lazily if needed."""
    global _ups_client

    if _ups_client is not None:
        connected = getattr(_ups_client, "is_connected", False)
        if isinstance(connected, bool) and connected:
            return _ups_client

    async with _ups_client_lock:
        if _ups_client is not None:
            connected = getattr(_ups_client, "is_connected", False)
            if isinstance(connected, bool) and connected:
                return _ups_client
            await _ups_client.connect()
            return _ups_client
        client = _build_ups_client()
        await client.connect()
        _ups_client = client
        return _ups_client


async def _reset_ups_client() -> None:
    """Tear down and clear the cached UPSMCPClient."""
    global _ups_client

    async with _ups_client_lock:
        if _ups_client is None:
            return
        try:
            await _ups_client.disconnect()
        except Exception as e:
            logger.warning("Failed to disconnect cached UPS client: %s", e)
        finally:
            _ups_client = None


async def shutdown_cached_ups_client() -> None:
    """Shutdown hook for FastAPI app lifecycle."""
    await _reset_ups_client()


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
    svc = _get_data_source_service()
    info = svc.get_source_info()
    if info is None:
        return _err("No data source connected. Ask the user to connect a CSV, Excel, or database source.")

    return _ok({
        "source_type": info.source_type,
        "file_path": info.file_path,
        "row_count": info.row_count,
        "column_count": len(info.columns),
    })


async def get_schema_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Get the column schema of the currently connected data source.

    Args:
        args: Empty dict (no arguments needed).

    Returns:
        Tool response with list of column definitions.
    """
    svc = _get_data_source_service()
    info = svc.get_source_info()
    if info is None:
        return _err("No data source connected.")

    columns = [
        {"name": col.name, "type": col.type, "nullable": col.nullable}
        for col in info.columns
    ]
    return _ok({"columns": columns})


async def fetch_rows_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Fetch rows from the connected data source with optional SQL filter.

    Args:
        args: Dict with optional 'where_clause' (str) and 'limit' (int).

    Returns:
        Tool response with matched rows and count.
    """
    svc = _get_data_source_service()
    where_clause = args.get("where_clause")
    limit = args.get("limit", 250)
    include_rows = bool(args.get("include_rows", False))

    try:
        rows = await svc.get_rows_by_filter(where_clause=where_clause, limit=limit)
        fetch_id = _store_fetched_rows(rows)
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
            return _ok({"job_id": job.id, "status": job.status})
    except Exception as e:
        logger.error("create_job_tool failed: %s", e)
        return _err(f"Failed to create job: {e}")


async def add_rows_to_job_tool(args: dict[str, Any]) -> dict[str, Any]:
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
        cached_rows = _consume_fetched_rows(fetch_id)
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
            return _ok({
                "job_id": job_id,
                "rows_added": len(created),
            })
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


SERVICE_CODE_NAMES: dict[str, str] = {
    "01": "UPS Next Day Air",
    "02": "UPS 2nd Day Air",
    "03": "UPS Ground",
    "12": "UPS 3 Day Select",
    "13": "UPS Next Day Air Saver",
    "14": "UPS Next Day Air Early",
    "59": "UPS 2nd Day Air A.M.",
}


def _enrich_preview_rows_from_map(
    preview_rows: list[dict[str, Any]],
    row_map: dict[int, dict[str, Any]],
) -> list[dict]:
    """Normalize preview rows using an in-memory row_number -> order_data map."""
    for row in preview_rows:
        od = row_map.get(row.get("row_number", -1), {})
        row["service"] = SERVICE_CODE_NAMES.get(
            od.get("service_code", "03"), "UPS Ground",
        )
        row["order_data"] = od
        # Normalize rate_error -> warnings array.
        rate_error = row.pop("rate_error", None)
        if rate_error:
            row["warnings"] = [rate_error]
        elif "warnings" not in row:
            row["warnings"] = []
    return preview_rows


def _enrich_preview_rows(job_id: str, preview_rows: list[dict]) -> list[dict]:
    """Normalize preview rows for the frontend BatchPreview type.

    Adds service name, order_data, and converts rate_error → warnings array.

    Args:
        job_id: Job UUID for DB row lookup.
        preview_rows: Raw rows from BatchEngine.preview().

    Returns:
        Enriched preview rows.
    """
    # Build row_number → order_data map from DB
    with get_db_context() as db:
        db_rows = JobService(db).get_rows(job_id)
        row_map: dict[int, dict] = {}
        for r in db_rows:
            if r.order_data:
                try:
                    row_map[r.row_number] = json.loads(r.order_data)
                except (json.JSONDecodeError, TypeError):
                    pass

    return _enrich_preview_rows_from_map(preview_rows, row_map)


async def ship_command_pipeline_tool(args: dict[str, Any]) -> dict[str, Any]:
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

    source_service = _get_data_source_service()
    try:
        fetched_rows = await source_service.get_rows_by_filter(
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
                logger.error("ship_command_pipeline preview failed for %s: %s", job.id, e)
                return _err(f"Preview failed for job {job.id}: {e}")
    except Exception as e:
        logger.error("ship_command_pipeline create_job failed: %s", e)
        return _err(f"Failed to create job: {e}")

    preview_rows = result.get("preview_rows", [])
    normalized_rows = _normalize_rows_for_shipping(fetched_rows)
    row_map = {i: row for i, row in enumerate(normalized_rows, start=1)}
    _enrich_preview_rows_from_map(preview_rows, row_map)
    rows_with_warnings = sum(1 for row in preview_rows if row.get("warnings"))
    result["rows_with_warnings"] = rows_with_warnings

    # IMPORTANT: Emit full payload to frontend before returning slim LLM payload.
    _emit_event("preview_ready", result)

    return _ok({
        "status": "preview_ready",
        "job_id": result.get("job_id"),
        "total_rows": result.get("total_rows", 0),
        "total_estimated_cost_cents": result.get("total_estimated_cost_cents", 0),
        "rows_with_warnings": rows_with_warnings,
        "message": (
            "Preview card has been displayed to the user. STOP HERE. "
            "Respond with one brief sentence asking the user to review "
            "the preview and click Confirm or Cancel."
        ),
    })


async def batch_preview_tool(args: dict[str, Any]) -> dict[str, Any]:
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
        rows_with_warnings = sum(
            1 for r in preview_rows if r.get("warnings")
        )
        result["rows_with_warnings"] = rows_with_warnings

        # IMPORTANT: Emit full preview payload to frontend before
        # returning a slim tool response to the LLM.
        _emit_event("preview_ready", result)

        return _ok({
            "status": "preview_ready",
            "job_id": job_id,
            "total_rows": result.get("total_rows", 0),
            "total_estimated_cost_cents": result.get("total_estimated_cost_cents", 0),
            "rows_with_warnings": rows_with_warnings,
            "message": (
                "Preview card has been displayed to the user. STOP HERE. "
                "Respond with one brief sentence asking the user to review "
                "the preview and click Confirm or Cancel."
            ),
        })
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

    # Report the authoritative data source status.
    # Shopify connection is only meaningful when its data has been imported
    # into the DataSourceService (DuckDB). Env vars alone are not sufficient
    # because the agent queries DuckDB, not the Shopify API directly.
    try:
        from src.services.data_source_service import DataSourceService

        svc = DataSourceService.get_instance()
        source_info = svc.get_source_info()
        if source_info:
            platforms["data_source"] = {
                "connected": True,
                "source_type": source_info.source_type,
                "label": source_info.file_path,
                "row_count": source_info.row_count,
                "column_count": len(source_info.columns),
            }
            # Shopify is connected only if it is the active data source.
            if source_info.source_type == "shopify":
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
            # Check if Shopify is at least configured (will auto-import on first message)
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


# ---------------------------------------------------------------------------
# Tool Definitions Registry
# ---------------------------------------------------------------------------


def get_all_tool_definitions() -> list[dict[str, Any]]:
    """Return all tool definitions for the orchestration agent.

    Each definition includes name, description, input_schema, and handler.

    Returns:
        List of tool definition dicts.
    """
    return [
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
            "handler": ship_command_pipeline_tool,
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
            "handler": fetch_rows_tool,
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
            "handler": add_rows_to_job_tool,
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
            "handler": batch_preview_tool,
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
    ]
