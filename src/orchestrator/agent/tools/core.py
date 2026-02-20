"""Shared internals for orchestration agent tools.

Contains the EventEmitterBridge, response helpers (_ok/_err),
UPS client cache, row normalization utilities, and preview helpers.
All tool handler submodules import from here.
"""

import hashlib
import json
import logging
import re
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from src.db.connection import get_db_context
from src.mcp.data_source.models import SOURCE_ROW_NUM_COLUMN
from src.services.audit_service import AuditService, EventType
from src.services.column_mapping import (
    apply_mapping,
    auto_map_columns,
    validate_mapping,
)
from src.services.gateway_provider import get_data_gateway, get_external_sources_client  # noqa: F401
from src.services.job_service import JobService
from src.services.mapping_cache import (
    compute_mapping_hash,
    get_or_compute_mapping_with_diagnostics,
)
from src.services.decision_audit_service import DecisionAuditService
from src.services.ups_service_codes import (
    SERVICE_ALIASES,
    SERVICE_CODE_NAMES,
    ServiceCode,
    translate_service_name,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event Emission + Session Cache Bridge
# ---------------------------------------------------------------------------

_MAX_FETCH_CACHE_ENTRIES = 20


class EventEmitterBridge:
    """Per-agent mutable bridge for session-sensitive tool state."""

    def __init__(self) -> None:
        self.callback: Callable[[str, dict], None] | None = None
        self.session_id: str | None = None
        self.last_user_message: str | None = None
        self.last_shipping_command: str | None = None
        # Best-effort recovery cache for same-turn resolve -> pipeline flows.
        self.last_resolved_filter_spec: dict[str, Any] | None = None
        self.last_resolved_filter_command: str | None = None
        self.last_resolved_filter_schema_signature: str | None = None
        self.confirmed_resolutions: dict[str, Any] = {}
        self._fetched_rows_cache: dict[str, list[dict[str, Any]]] = {}
        self._fetched_rows_order: list[str] = []

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a structured event through the registered callback."""
        if self.callback is not None:
            self.callback(event_type, data)

    def store_rows(self, rows: list[dict[str, Any]]) -> str:
        """Store fetched rows and return a fetch_id handle."""
        fetch_id = str(uuid4())
        self._fetched_rows_cache[fetch_id] = rows
        self._fetched_rows_order.append(fetch_id)
        while len(self._fetched_rows_order) > _MAX_FETCH_CACHE_ENTRIES:
            oldest = self._fetched_rows_order.pop(0)
            self._fetched_rows_cache.pop(oldest, None)
        return fetch_id

    def consume_rows(self, fetch_id: str) -> list[dict[str, Any]] | None:
        """Get and remove cached rows for a fetch_id."""
        rows = self._fetched_rows_cache.pop(fetch_id, None)
        if fetch_id in self._fetched_rows_order:
            self._fetched_rows_order.remove(fetch_id)
        return rows


def _emit_event(
    event_type: str,
    data: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> None:
    """Emit a structured event to the frontend through the provided bridge."""
    if bridge is not None:
        bridge.emit(event_type, data)


def _store_fetched_rows(
    rows: list[dict[str, Any]],
    bridge: EventEmitterBridge | None = None,
) -> str:
    """Store fetched rows in bridge-local cache and return a fetch_id."""
    if bridge is None:
        raise RuntimeError("EventEmitterBridge is required for row cache access.")
    return bridge.store_rows(rows)


def _consume_fetched_rows(
    fetch_id: str,
    bridge: EventEmitterBridge | None = None,
) -> list[dict[str, Any]] | None:
    """Get and remove cached rows for a fetch_id from bridge-local cache."""
    if bridge is None:
        return None
    return bridge.consume_rows(fetch_id)


# ---------------------------------------------------------------------------
# Response Helpers
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


# ---------------------------------------------------------------------------
# Bridge Binding
# ---------------------------------------------------------------------------


def _bind_bridge(
    handler: Callable[..., Any],
    bridge: "EventEmitterBridge",
) -> Callable[[dict[str, Any]], Any]:
    """Bind an EventEmitterBridge to a tool handler."""

    async def _wrapped(args: dict[str, Any]) -> Any:
        return await handler(args, bridge=bridge)

    return _wrapped


# ---------------------------------------------------------------------------
# Job / Row Helpers
# ---------------------------------------------------------------------------


async def _persist_job_source_signature(
    job_id: str,
    db: Any,
    source_signature: dict[str, Any] | None = None,
) -> None:
    """Persist source signature metadata for replay safety checks.

    Accepts an optional precomputed signature to avoid an extra MCP round trip
    when the caller already fetched source metadata in the same flow.
    """
    signature = source_signature
    if signature is None:
        gw = await get_data_gateway()
        signature = await gw.get_source_signature()
    if signature is None:
        return

    try:
        audit = AuditService(db)
        audit.log_info(
            job_id=job_id,
            event_type=EventType.row_event,
            message="job_source_signature",
            details={"source_signature": signature},
        )
    except Exception as e:
        logger.warning(
            "Failed to persist job source signature for job %s: %s",
            job_id,
            e,
        )


def _build_job_row_data(
    rows: list[dict[str, Any]],
    service_code_override: str | None = None,
    schema_fingerprint: str | None = None,
) -> list[dict[str, Any]]:
    """Convert source rows into JobRow create payload with checksums.

    Args:
        rows: Source rows fetched from the connected data source.
        service_code_override: Optional UPS service code to force across all rows.
        schema_fingerprint: Optional source schema fingerprint for cache lookup.
    """
    normalized_rows = _normalize_rows_for_shipping(
        rows,
        schema_fingerprint=schema_fingerprint,
    )
    if service_code_override:
        for row in normalized_rows:
            if isinstance(row, dict):
                row["service_code"] = service_code_override

    row_data = []
    for idx, row in enumerate(normalized_rows, start=1):
        # Extract source row identity set by _normalize_rows() from MCP response.
        # Fallback to 1-based index if neither key exists — guarantees non-None.
        source_row = (
            row.pop("_row_number", None)
            or row.pop(SOURCE_ROW_NUM_COLUMN, None)
            or idx
        )
        row.pop("_checksum", None)  # Clean MCP metadata before serialization
        row_json = json.dumps(row, sort_keys=True, default=str)
        checksum = hashlib.md5(row_json.encode()).hexdigest()
        row_data.append(
            {
                "row_number": source_row,
                "row_checksum": checksum,
                "order_data": row_json,
            }
        )
    return row_data


def _build_job_row_data_with_metadata(
    rows: list[dict[str, Any]],
    service_code_override: str | None = None,
    packaging_type_override: str | None = None,
    schema_fingerprint: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Build job row payloads and return mapping_hash metadata.

    When a service_code_override is provided, applies compatibility validation
    via apply_compatibility_corrections() — the same shared path used by
    batch_engine during execution. Auto-correctable issues (e.g., express
    packaging with ground service) are fixed in-place; hard errors are surfaced
    as _validation_warnings for display in the preview card.

    Args:
        rows: Source rows from data source.
        service_code_override: Optional service code applied to all rows.
        packaging_type_override: Optional packaging code applied to all rows.
        schema_fingerprint: Source schema fingerprint for mapping cache.

    Returns:
        Tuple of (row_data_list, mapping_hash).
    """
    normalized_rows, mapping_hash = _normalize_rows_for_shipping_with_metadata(
        rows,
        schema_fingerprint=schema_fingerprint,
    )
    if packaging_type_override:
        for row in normalized_rows:
            if isinstance(row, dict):
                row["packaging_type"] = packaging_type_override
    if service_code_override:
        from src.services.ups_payload_builder import apply_compatibility_corrections
        for row in normalized_rows:
            if isinstance(row, dict):
                row["service_code"] = service_code_override
                # Shared validation + auto-correction (same function used by batch_engine).
                # Check returned issues for hard errors so preview surfaces them.
                issues = apply_compatibility_corrections(row, service_code_override)
                hard_errors = [
                    i for i in issues
                    if i.severity == "error" and not i.auto_corrected
                ]
                if hard_errors:
                    existing = row.get("_validation_warnings", [])
                    if isinstance(existing, str):
                        existing = [existing] if existing else []
                    row["_validation_warnings"] = existing + [
                        f"[VALIDATION] {i.message}" for i in hard_errors
                    ]

    row_data = []
    for idx, row in enumerate(normalized_rows, start=1):
        source_row = (
            row.pop("_row_number", None)
            or row.pop(SOURCE_ROW_NUM_COLUMN, None)
            or idx
        )
        row.pop("_checksum", None)
        row_json = json.dumps(row, sort_keys=True, default=str)
        checksum = hashlib.md5(row_json.encode()).hexdigest()
        row_data.append(
            {
                "row_number": source_row,
                "row_checksum": checksum,
                "order_data": row_json,
            }
        )
    return row_data, mapping_hash


def _normalize_rows_for_shipping(
    rows: list[dict[str, Any]],
    schema_fingerprint: str | None = None,
) -> list[dict[str, Any]]:
    """Normalize source rows into canonical order_data keys for UPS payloads.

    CSV/Excel imports often use arbitrary headers. This function auto-maps
    those headers into the canonical ship_to_* keys expected by
    build_shipment_request().
    """
    normalized_rows, _ = _normalize_rows_for_shipping_with_metadata(
        rows,
        schema_fingerprint=schema_fingerprint,
    )
    return normalized_rows


def _normalize_rows_for_shipping_with_metadata(
    rows: list[dict[str, Any]],
    schema_fingerprint: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Normalize source rows to canonical order_data keys and return mapping metadata.

    Applies heuristic auto-mapping from source columns to UPS field paths,
    logs the mapping selection trace to the decision audit system, and
    falls back to service name translation for service_code fields.

    Args:
        rows: Source rows with arbitrary column names.
        schema_fingerprint: Optional fingerprint for mapping cache lookup.

    Returns:
        Tuple of (normalized_rows, mapping_hash). mapping_hash is None when
        no schema_fingerprint is provided.
    """
    if not rows:
        return rows, None

    source_columns: list[str] = sorted(
        {str(k) for row in rows if isinstance(row, dict) for k in row.keys()}
    )
    if schema_fingerprint:
        mapping, mapping_hash, mapping_meta = get_or_compute_mapping_with_diagnostics(
            source_columns=source_columns,
            schema_fingerprint=schema_fingerprint,
            sample_rows=rows,
        )
    else:
        mapping = auto_map_columns(source_columns)
        mapping_hash = compute_mapping_hash(mapping)
        mapping_meta = {
            "cache_hit": False,
            "cache_source": "none",
            "schema_fingerprint": schema_fingerprint or "",
            "selection_trace": {},
        }
    missing_required = validate_mapping(mapping)
    if missing_required:
        logger.warning(
            "Auto column mapping incomplete for %d rows: %s",
            len(rows),
            "; ".join(missing_required),
        )
    DecisionAuditService.log_event_from_context(
        phase="mapping",
        event_name="mapping.selection_trace",
        actor="system",
        payload={
            "schema_fingerprint": schema_fingerprint or "",
            "mapping_hash": mapping_hash,
            "mapped_field_count": len(mapping),
            "missing_required": missing_required,
            "cache_hit": mapping_meta.get("cache_hit", False),
            "cache_source": mapping_meta.get("cache_source", "unknown"),
            "selection_trace": mapping_meta.get("selection_trace", {}),
        },
    )

    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            normalized.append(row)
            continue

        out: dict[str, Any] = dict(row)
        mapped = apply_mapping(mapping, row)
        for key, value in mapped.items():
            existing = out.get(key)
            if (existing is None or existing == "") and value is not None and value != "":
                out[key] = value

        if not out.get("ship_to_name"):
            for key in ("recipient_name", "customer_name", "name"):
                value = row.get(key)
                if value:
                    out["ship_to_name"] = value
                    break

        if out.get("service_code"):
            out["service_code"] = translate_service_name(str(out["service_code"]))
        elif row.get("service"):
            out["service_code"] = translate_service_name(str(row["service"]))

        normalized.append(out)

    return normalized, mapping_hash


def _command_explicitly_requests_service(command: str) -> bool:
    """Return True when the command text explicitly specifies a UPS service."""
    text = command.lower()
    for alias in SERVICE_ALIASES:
        if alias in text:
            return True
    return bool(re.search(r"\b(01|02|03|07|08|11|12|13|14|54|59|65)\b", text))


# ---------------------------------------------------------------------------
# Shared UPS MCP Client (delegated to gateway_provider)
# ---------------------------------------------------------------------------


async def _get_ups_client() -> Any:
    """Get the singleton UPSMCPClient via gateway_provider."""
    from src.services.gateway_provider import get_ups_gateway

    return await get_ups_gateway()


async def shutdown_cached_ups_client() -> None:
    """No-op — UPS lifecycle managed by gateway_provider.shutdown_gateways()."""
    pass


# ---------------------------------------------------------------------------
# Preview Enrichment Helpers
# ---------------------------------------------------------------------------


def _enrich_preview_rows_from_map(
    preview_rows: list[dict[str, Any]],
    row_map: dict[int, dict[str, Any]],
) -> list[dict]:
    """Normalize preview rows using an in-memory row_number -> order_data map."""
    for row in preview_rows:
        od = row_map.get(row.get("row_number", -1), {})
        row["service"] = SERVICE_CODE_NAMES.get(
            od.get("service_code", ServiceCode.GROUND.value),
            "UPS Ground",
        )
        row["order_data"] = od
        rate_error = row.pop("rate_error", None)
        if rate_error:
            row["warnings"] = [rate_error]
        elif "warnings" not in row:
            row["warnings"] = []
    return preview_rows


def _enrich_preview_rows(job_id: str, preview_rows: list[dict]) -> list[dict]:
    """Normalize preview rows for the frontend BatchPreview type.

    Adds service name, order_data, and converts rate_error -> warnings array.
    """
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


def _emit_preview_ready(
    result: dict[str, Any],
    rows_with_warnings: int,
    bridge: EventEmitterBridge | None = None,
    job_id_override: str | None = None,
) -> dict[str, Any]:
    """Emit preview SSE payload and return slim LLM tool payload."""
    _emit_event("preview_ready", result, bridge=bridge)
    # Reset shipping turn context after a preview has been emitted.
    if bridge is not None:
        bridge.last_shipping_command = None
    response = {
        "status": "preview_ready",
        "job_id": job_id_override or result.get("job_id"),
        "total_rows": result.get("total_rows", 0),
        "total_estimated_cost_cents": result.get("total_estimated_cost_cents", 0),
        "rows_with_warnings": rows_with_warnings,
        "message": (
            "Preview card has been displayed to the user. STOP HERE. "
            "Respond with one brief sentence asking the user to review "
            "the preview and click Confirm or Cancel."
        ),
    }
    # Include filter metadata fields for transparency and audit
    for key in ("filter_explanation", "compiled_filter", "filter_audit"):
        if key in result:
            response[key] = result[key]
    return _ok(response)
