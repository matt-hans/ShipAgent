"""Shared internals for orchestration agent tools.

Contains the EventEmitterBridge, response helpers (_ok/_err),
UPS client cache, row normalization utilities, and preview helpers.
All tool handler submodules import from here.
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

from src.db.connection import get_db_context
from src.services.audit_service import AuditService, EventType
from src.services.column_mapping import (
    apply_mapping,
    auto_map_columns,
    validate_mapping,
)
from src.services.ups_service_codes import (
    SERVICE_ALIASES,
    SERVICE_CODE_NAMES,
    translate_service_name,
)
from src.services.job_service import JobService

# Re-export gateway accessors for tool handler convenience
from src.services.gateway_provider import get_data_gateway, get_external_sources_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event Emission + Session Cache Bridge
# ---------------------------------------------------------------------------

_MAX_FETCH_CACHE_ENTRIES = 20


class EventEmitterBridge:
    """Per-agent mutable bridge for session-sensitive tool state."""

    def __init__(self) -> None:
        self.callback: Callable[[str, dict], None] | None = None
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


async def _persist_job_source_signature(job_id: str, db: Any) -> None:
    """Persist source signature metadata for replay safety checks."""
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
) -> list[dict[str, Any]]:
    """Convert source rows into JobRow create payload with checksums.

    Args:
        rows: Source rows fetched from the connected data source.
        service_code_override: Optional UPS service code to force across all rows.
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
        row_data.append(
            {
                "row_number": i,
                "row_checksum": checksum,
                "order_data": row_json,
            }
        )
    return row_data


def _normalize_rows_for_shipping(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize source rows into canonical order_data keys for UPS payloads.

    CSV/Excel imports often use arbitrary headers. This function auto-maps
    those headers into the canonical ship_to_* keys expected by
    build_shipment_request().
    """
    if not rows:
        return rows

    source_columns: list[str] = sorted(
        {str(k) for row in rows if isinstance(row, dict) for k in row.keys()}
    )
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

        out: dict[str, Any] = dict(row)
        mapped = apply_mapping(mapping, row)
        for key, value in mapped.items():
            if value is not None and value != "":
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

    return normalized


def _command_explicitly_requests_service(command: str) -> bool:
    """Return True when the command text explicitly specifies a UPS service."""
    text = command.lower()
    for alias in SERVICE_ALIASES:
        if alias in text:
            return True
    return bool(re.search(r"\b(01|02|03|07|08|11|12|13|14|54|59|65)\b", text))


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
            od.get("service_code", "03"),
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
    return _ok(
        {
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
    )
