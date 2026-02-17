"""Batch pipeline tool handlers.

Handles the shipping command pipeline, job creation, row management,
batch preview, and batch execution.
"""

import hashlib
import json
import logging
import os
import re
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from src.db.connection import get_db_context
from src.services.job_service import JobService
from src.services.filter_constants import (
    BUSINESS_PREDICATES,
    REGIONS,
    REGION_ALIASES,
    STATE_ABBREVIATIONS,
    normalize_term,
)
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
    _ok,
    _persist_job_source_signature,
    get_data_gateway,
)
from src.services.errors import UPSServiceError

logger = logging.getLogger(__name__)

_FILTER_QUALIFIER_TERMS = frozenset(
    set(REGION_ALIASES.keys())
    | {
        "company",
        "companies",
        "business",
        "recipient",
        "where",
        "unfulfilled",
        "fulfilled",
        "pending",
        "cancelled",
        "canceled",
    }
)
_NUMERIC_QUALIFIER_PATTERNS = (
    " over ",
    " under ",
    " between ",
    " greater than ",
    " less than ",
    " more than ",
    " at least ",
    " at most ",
    " above ",
    " below ",
)
_STATE_NAME_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, STATE_ABBREVIATIONS.keys()), key=len, reverse=True)) + r")\b"
)


def _command_implies_filter(command: str) -> bool:
    """Return True when the command clearly contains filter qualifiers."""
    normalized = f" {' '.join(normalize_term(command).split())} "
    if any(term in normalized for term in _FILTER_QUALIFIER_TERMS):
        return True
    if any(pattern in normalized for pattern in _NUMERIC_QUALIFIER_PATTERNS):
        return True
    if _STATE_NAME_PATTERN.search(normalized):
        return True
    return False


def _is_confirmation_response(message: str | None) -> bool:
    """True for short confirmation replies (yes/proceed/confirm)."""
    if not message:
        return False
    return message.strip().lower() in {
        "yes", "y", "ok", "okay", "confirm", "proceed", "continue", "go ahead",
    }


def _should_force_fast_path(bridge: EventEmitterBridge | None) -> bool:
    """Force ship_command_pipeline when shipping intent is active in session context."""
    if bridge is None:
        return False
    msg = bridge.last_user_message
    if not msg:
        return False
    text = msg.strip().lower()
    if "ship" in text or "shipment" in text:
        return True
    return _is_confirmation_response(msg) and bool(bridge.last_shipping_command)


def _iter_conditions(group: Any) -> list[Any]:
    """Flatten FilterGroup tree into a list of FilterCondition nodes."""
    conditions: list[Any] = []
    stack = [group]
    while stack:
        node = stack.pop()
        for child in getattr(node, "conditions", []):
            if hasattr(child, "column") and hasattr(child, "operator"):
                conditions.append(child)
            elif hasattr(child, "conditions"):
                stack.append(child)
    return conditions


def _expected_region_from_command(command: str) -> str | None:
    """Return canonical region key referenced in command text, if any."""
    normalized = normalize_term(command)
    for alias, region_key in REGION_ALIASES.items():
        if alias in normalized:
            return region_key
    return None


def _spec_includes_region(spec: Any, region_key: str) -> bool:
    """Check whether resolved spec contains a condition matching region states."""
    expected = {s.upper() for s in REGIONS.get(region_key, [])}
    for cond in _iter_conditions(spec.root):
        op = str(getattr(cond, "operator", ""))
        raw_values = [getattr(o, "value", None) for o in getattr(cond, "operands", [])]
        values = {str(v).upper() for v in raw_values if isinstance(v, str)}
        if op.endswith("in_") or op.endswith("in"):
            if values and values.issubset(expected) and values:
                return True
        if op.endswith("eq") and len(values) == 1 and next(iter(values)) in expected:
            return True
    return False


def _command_requests_business_filter(command: str) -> bool:
    """Detect business/company qualifier in command text."""
    normalized = normalize_term(command)
    return any(t in normalized for t in ("company", "companies", "business"))


def _spec_includes_business_filter(spec: Any) -> bool:
    """Check whether resolved spec includes BUSINESS_RECIPIENT-like predicate."""
    patterns = BUSINESS_PREDICATES["BUSINESS_RECIPIENT"]["target_column_patterns"]
    for cond in _iter_conditions(spec.root):
        op = str(getattr(cond, "operator", ""))
        column = str(getattr(cond, "column", "")).lower()
        if op.endswith("is_not_blank") and any(p in column for p in patterns):
            return True
    return False


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
    if _should_force_fast_path(bridge):
        return _err(
            "For shipping execution commands, do not use add_rows_to_job. "
            "Use ship_command_pipeline with a resolved filter_spec."
        )
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


def _canonical_param(v: Any) -> Any:
    """Normalize a param value for deterministic hashing.

    Ensures dates use UTC ISO8601, decimals are normalized, and no type
    relies on locale-specific str() formatting.

    Args:
        v: Parameter value from CompiledFilter.params.

    Returns:
        JSON-safe canonical representation.
    """
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v.normalize())
    if isinstance(v, float):
        return str(v)
    return v


def _compute_compiled_hash(where_sql: str, params: list[Any]) -> str:
    """Compute deterministic SHA-256 hash of compiled query payload.

    Args:
        where_sql: Parameterized WHERE clause.
        params: Positional parameter values.

    Returns:
        Hex digest of the canonical JSON representation.
    """
    canonical = json.dumps(
        {"where_sql": where_sql, "params": [_canonical_param(p) for p in params]},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def ship_command_pipeline_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Fast-path pipeline for straightforward shipping commands.

    Performs compile → fetch → create job → add rows → preview in one call.
    Accepts exactly one of filter_spec or all_rows=true. Rejects where_clause.
    """
    from src.orchestrator.filter_compiler import compile_filter_spec
    from src.orchestrator.models.filter_spec import (
        FilterCompilationError,
        ResolvedFilterSpec,
    )

    command = str(args.get("command", "")).strip()
    if not command:
        return _err("command is required")

    # Hard cutover: reject legacy where_clause
    if "where_clause" in args:
        return _err(
            "where_clause is not accepted. Use resolve_filter_intent "
            "to create a filter_spec."
        )

    filter_spec_raw = args.get("filter_spec")
    all_rows = bool(args.get("all_rows", False))

    # Exactly one of filter_spec or all_rows must be provided
    if filter_spec_raw and all_rows:
        return _err(
            "Conflicting arguments: provide filter_spec OR all_rows=true, not both."
        )
    if not filter_spec_raw and not all_rows:
        return _err(
            "Either filter_spec or all_rows=true is required. "
            "Use resolve_filter_intent to create a filter, or set "
            "all_rows=true to ship everything."
        )
    if all_rows and _command_implies_filter(command):
        return _err(
            "all_rows=true is not allowed when the command contains filters "
            "(e.g., regions or business/company qualifiers). Resolve and pass "
            "a filter_spec via resolve_filter_intent."
        )

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

    # Compile filter or use all-rows path
    filter_explanation = ""
    filter_audit: dict[str, Any] = {}
    gw = await get_data_gateway()
    source_info = await gw.get_source_info()
    if source_info is None:
        return _err("No data source connected.")
    if not isinstance(source_info, dict):
        logger.warning(
            "ship_command_pipeline expected dict source_info, got %s; "
            "proceeding without schema metadata",
            type(source_info).__name__,
        )
        source_info = {}
    raw_signature = source_info.get("signature", "")
    schema_signature = raw_signature if isinstance(raw_signature, str) else ""

    if filter_spec_raw:
        # Compile FilterSpec → parameterized SQL
        columns = source_info.get("columns", [])
        schema_columns = {col["name"] for col in columns}
        column_types = {col["name"]: col["type"] for col in columns}

        try:
            spec = ResolvedFilterSpec(**filter_spec_raw)
        except Exception as e:
            return _err(f"Invalid filter_spec structure: {e}")

        expected_region = _expected_region_from_command(command)
        if expected_region and not _spec_includes_region(spec, expected_region):
            return _err(
                f"Filter mismatch: command references region '{expected_region}' "
                "but filter_spec does not include a matching state filter. "
                "Re-run resolve_filter_intent with the correct region semantic key."
            )
        if _command_requests_business_filter(command) and not _spec_includes_business_filter(spec):
            return _err(
                "Filter mismatch: command requests companies/business recipients, "
                "but filter_spec does not include a business/company predicate. "
                "Re-run resolve_filter_intent and include BUSINESS_RECIPIENT."
            )

        try:
            compiled = compile_filter_spec(
                spec=spec,
                schema_columns=schema_columns,
                column_types=column_types,
                runtime_schema_signature=schema_signature,
            )
        except FilterCompilationError as e:
            return _err(f"[{e.code.value}] {e.message}")
        except Exception as e:
            logger.error("ship_command_pipeline compile failed: %s", e)
            return _err(f"Filter compilation failed: {e}")

        where_sql = compiled.where_sql
        params = compiled.params
        filter_explanation = compiled.explanation

        # Build audit trail
        spec_hash = hashlib.sha256(
            json.dumps(filter_spec_raw, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        compiled_hash = _compute_compiled_hash(where_sql, params)

        filter_audit = {
            "spec_hash": spec_hash,
            "compiled_hash": compiled_hash,
            "schema_signature": schema_signature,
            "dict_version": spec.canonical_dict_version,
        }
    else:
        # all_rows path
        where_sql = "1=1"
        params = []
        filter_explanation = "All rows (no filter applied)"

    try:
        fetched_rows = await gw.get_rows_by_filter(
            where_sql=where_sql,
            limit=limit,
            params=params,
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
    row_map: dict[int, dict[str, Any]] = {}

    try:
        with get_db_context() as db:
            job_service = JobService(db)
            job = job_service.create_job(name=job_name, original_command=command)
            await _persist_job_source_signature(job.id, db)
            try:
                mapping_started = time.perf_counter()
                row_payload = _build_job_row_data(
                    fetched_rows,
                    service_code_override=service_code,
                    schema_fingerprint=schema_signature,
                )
                logger.info(
                    "mapping_resolution_timing marker=job_row_data_ready "
                    "job_id=%s rows=%d fingerprint=%s elapsed=%.3f",
                    job.id,
                    len(fetched_rows),
                    schema_signature[:12] if schema_signature else "",
                    time.perf_counter() - mapping_started,
                )
                job_service.create_rows(
                    job.id,
                    row_payload,
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
                for db_row in db_rows:
                    try:
                        parsed = json.loads(db_row.order_data) if db_row.order_data else {}
                    except (TypeError, json.JSONDecodeError):
                        parsed = {}
                    row_map[db_row.row_number] = parsed
            except Exception as e:
                logger.error(
                    "ship_command_pipeline preview failed for %s: %s", job.id, e
                )
                return _err(f"Preview failed for job {job.id}: {e}")
    except Exception as e:
        logger.error("ship_command_pipeline create_job failed: %s", e)
        return _err(f"Failed to create job: {e}")

    preview_rows = result.get("preview_rows", [])
    _enrich_preview_rows_from_map(preview_rows, row_map)
    rows_with_warnings = sum(1 for row in preview_rows if row.get("warnings"))
    result["rows_with_warnings"] = rows_with_warnings

    # Attach filter metadata for audit trail
    if filter_explanation:
        result["filter_explanation"] = filter_explanation
    if filter_audit:
        result["filter_audit"] = filter_audit
    if filter_spec_raw:
        result["compiled_filter"] = where_sql

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
    if _should_force_fast_path(bridge):
        return _err(
            "For shipping execution commands, do not use batch_preview directly. "
            "Use ship_command_pipeline with a resolved filter_spec."
        )

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
        return _ok("Landed cost estimate displayed.")
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in get_landed_cost_tool")
        return _err(f"Unexpected error: {e}")
