"""Consolidated batch engine for preview and execution.

Replaces both src/api/routes/preview.py execution logic and
src/orchestrator/batch/executor.py. Single engine for both
REST API and orchestrator agent paths.

Example:
    async with UPSMCPClient(...) as ups:
        engine = BatchEngine(ups_service=ups, db_session=session, account_number="X")
        result = await engine.execute(job_id="...", rows=rows, shipper=shipper)
"""

import asyncio
import base64
import json
import logging
import os
import traceback
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Awaitable, Callable

from src.services.ups_constants import DEFAULT_ORIGIN_COUNTRY, UPS_CARRIER_NAME
from src.services.ups_payload_builder import (
    build_shipment_request,
    build_ups_api_payload,
    build_ups_rate_payload,
)
from src.services.ups_service_codes import ServiceCode
from src.services.errors import UPSServiceError
from src.services.gateway_provider import get_data_gateway, get_external_sources_client
from src.services.international_rules import get_requirements, validate_international_readiness

logger = logging.getLogger(__name__)


def _dollars_to_cents(amount: str) -> int:
    """Convert dollar string to cents using Decimal to avoid float drift.

    Args:
        amount: Dollar amount as string (e.g., "45.50").

    Returns:
        Integer cents value.
    """
    return int(Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)

# Default labels output directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LABELS_DIR = PROJECT_ROOT / "labels"

# Callback type for progress reporting
ProgressCallback = Callable[..., Awaitable[None]]


class BatchEngine:
    """Consolidated batch preview and execution engine.

    Uses deterministic payload building + UPSMCPClient for all UPS calls.
    Supports progress callbacks for SSE integration.

    Attributes:
        _ups: UPS client (UPSMCPClient) for async UPS API calls
        _db: Database session for row state updates
        _account_number: UPS account number for billing
    """

    DEFAULT_PREVIEW_MAX_ROWS = 50

    def __init__(
        self,
        ups_service: Any,
        db_session: Any,
        account_number: str,
        labels_dir: str | None = None,
    ) -> None:
        """Initialize batch engine.

        Args:
            ups_service: Async UPS client (UPSMCPClient)
            db_session: SQLAlchemy session for state updates
            account_number: UPS account number
            labels_dir: Directory for label files (default: PROJECT_ROOT/labels)
        """
        self._ups = ups_service
        self._db = db_session
        self._account_number = account_number
        self._labels_dir = labels_dir or os.environ.get(
            "UPS_LABELS_OUTPUT_DIR", str(DEFAULT_LABELS_DIR)
        )

    @staticmethod
    def _resolve_concurrency() -> int:
        """Resolve preview/execute concurrency from env with safe fallback."""
        raw = os.environ.get("BATCH_CONCURRENCY", "5")
        try:
            value = int(raw)
        except ValueError:
            logger.warning("Invalid BATCH_CONCURRENCY=%r, defaulting to 5", raw)
            return 5
        return max(1, value)

    async def preview(
        self,
        job_id: str,
        rows: list[Any],
        shipper: dict[str, str],
        service_code: str | None = None,
    ) -> dict[str, Any]:
        """Generate preview with cost estimates.

        Rates up to BATCH_PREVIEW_MAX_ROWS concurrently (bounded by semaphore),
        estimates the rest from the average cost when capped.

        Args:
            job_id: Job UUID for tracking
            rows: List of JobRow objects with order_data
            shipper: Shipper address info
            service_code: Optional service code override

        Returns:
            Dict with total_estimated_cost_cents, preview_rows, etc.
        """
        started_at = datetime.now(UTC)
        # Use same concurrency setting as execute for consistent performance.
        max_concurrent = self._resolve_concurrency()
        semaphore = asyncio.Semaphore(max_concurrent)

        preview_rows: list[dict[str, Any]] = []
        total_cost_cents = 0
        rows_lock = asyncio.Lock()
        row_durations: list[float] = []

        # Pre-hydrate commodities for international rows that need them.
        # Collect order IDs, bulk-fetch from MCP, then inject into order data.
        commodity_cache: dict[str, list[dict]] = {}
        if rows:
            order_ids = []
            for r in rows:
                try:
                    od = self._parse_order_data(r)
                    oid = od.get("order_id") or od.get("order_number")
                    if oid:
                        order_ids.append(str(oid))
                except Exception as e:
                    logger.warning(
                        "Skipping commodity lookup for row %s (parse error): %s",
                        getattr(r, "row_number", "?"),
                        e,
                    )
            if order_ids:
                try:
                    raw = await self._get_commodities_bulk(order_ids)
                    commodity_cache = {str(k): v for k, v in raw.items()}
                except Exception as e:
                    logger.warning("Commodity bulk fetch failed (non-critical): %s", e)

        async def _rate_row(row: Any) -> None:
            """Rate a single row with concurrency control."""
            nonlocal total_cost_cents
            row_started = datetime.now(UTC)

            async with semaphore:
                order_data: dict[str, Any] = {}
                rate_error: str | None = None
                cost_cents = 0
                try:
                    order_data = self._parse_order_data(row)

                    # International validation (preview)
                    dest_country = order_data.get("ship_to_country", DEFAULT_ORIGIN_COUNTRY)
                    eff_service = service_code or order_data.get("service_code", ServiceCode.GROUND.value)
                    origin_country = shipper.get("countryCode", DEFAULT_ORIGIN_COUNTRY)
                    requirements = get_requirements(origin_country, dest_country, eff_service)

                    if requirements.not_shippable_reason:
                        raise ValueError(requirements.not_shippable_reason)

                    # Hydrate commodities from cache if needed
                    if requirements.requires_commodities and not order_data.get("commodities"):
                        oid = str(order_data.get("order_id") or order_data.get("order_number") or "")
                        if oid and oid in commodity_cache:
                            order_data["commodities"] = commodity_cache[oid]

                    if requirements.is_international or requirements.requires_invoice_line_total:
                        validation_errors = validate_international_readiness(
                            order_data, requirements,
                        )
                        if validation_errors:
                            raise ValueError(
                                "; ".join(e.message for e in validation_errors)
                            )

                    simplified = build_shipment_request(
                        order_data=order_data,
                        shipper=shipper,
                        service_code=service_code,
                    )
                    rate_payload = build_ups_rate_payload(
                        simplified,
                        account_number=self._account_number,
                    )
                    rate_result = await self._ups.get_rate(request_body=rate_payload)
                    amount = rate_result.get("totalCharges", {}).get(
                        "monetaryValue", "0"
                    )
                    cost_cents = _dollars_to_cents(amount)
                except UPSServiceError as e:
                    logger.warning(
                        "Rate quote failed for row %s: %s", row.row_number, e
                    )
                    rate_error = str(e)
                except Exception as e:
                    # Keep preview resilient: malformed row data or payload
                    # build issues should surface as row warnings, not hard fail.
                    err_msg = str(e) or f"{type(e).__name__} (no message)"
                    logger.warning(
                        "Preview row %s degraded to warning (non-fatal): %s [%s]\n%s",
                        row.row_number,
                        err_msg,
                        type(e).__name__,
                        traceback.format_exc(),
                    )
                    rate_error = err_msg
                finally:
                    row_elapsed = (datetime.now(UTC) - row_started).total_seconds()
                    row_durations.append(row_elapsed)

                # Serialize row list append and cost accumulation
                async with rows_lock:
                    nonlocal total_cost_cents
                    total_cost_cents += cost_cents

                    row_info: dict[str, Any] = {
                        "row_number": row.row_number,
                        "recipient_name": order_data.get(
                            "ship_to_name", f"Row {row.row_number}"
                        ),
                        "city_state": f"{order_data.get('ship_to_city', '')}, {order_data.get('ship_to_state', '')}",
                        "estimated_cost_cents": cost_cents,
                    }
                    if rate_error:
                        row_info["rate_error"] = rate_error
                    preview_rows.append(row_info)

        try:
            preview_cap = int(
                os.environ.get(
                    "BATCH_PREVIEW_MAX_ROWS",
                    str(self.DEFAULT_PREVIEW_MAX_ROWS),
                ),
            )
        except ValueError:
            preview_cap = self.DEFAULT_PREVIEW_MAX_ROWS
        rows_to_rate = rows if preview_cap <= 0 else rows[:preview_cap]
        await asyncio.gather(*[_rate_row(row) for row in rows_to_rate])

        # Sort preview rows by row_number for consistent ordering
        preview_rows.sort(key=lambda r: r["row_number"])

        # Estimate remaining rows from average
        additional_rows = max(0, len(rows) - len(preview_rows))
        if additional_rows > 0 and preview_rows:
            avg_cost = total_cost_cents / len(preview_rows)
            total_estimated_cost_cents = total_cost_cents + int(
                avg_cost * additional_rows
            )
        else:
            total_estimated_cost_cents = total_cost_cents

        total_elapsed = (datetime.now(UTC) - started_at).total_seconds()
        avg_row = (sum(row_durations) / len(row_durations)) if row_durations else 0.0
        p95_row = 0.0
        if row_durations:
            ordered = sorted(row_durations)
            idx = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
            p95_row = ordered[idx]
        logger.info(
            "Batch preview timing: job_id=%s rows_total=%d rows_rated=%d "
            "concurrency=%d preview_cap=%d total=%.2fs avg_row=%.2fs p95_row=%.2fs",
            job_id,
            len(rows),
            len(preview_rows),
            max_concurrent,
            preview_cap,
            total_elapsed,
            avg_row,
            p95_row,
        )

        return {
            "job_id": job_id,
            "total_rows": len(rows),
            "preview_rows": preview_rows,
            "additional_rows": additional_rows,
            "total_estimated_cost_cents": total_estimated_cost_cents,
        }

    async def execute(
        self,
        job_id: str,
        rows: list[Any],
        shipper: dict[str, str],
        service_code: str | None = None,
        on_progress: ProgressCallback | None = None,
        write_back_enabled: bool = True,
    ) -> dict[str, Any]:
        """Execute batch shipment processing with concurrent UPS API calls.

        Processes rows concurrently (up to MAX_CONCURRENT) for speed, while
        serializing DB writes and SSE progress events via a lock.

        Args:
            job_id: Job UUID
            rows: List of JobRow objects
            shipper: Shipper address info
            service_code: Optional service code override
            on_progress: Optional async callback for SSE events
            write_back_enabled: Whether to write tracking numbers back to
                the data source. Defaults to True. Set to False for
                interactive shipments that have no source to write back to.

        Returns:
            Dict with successful, failed, total_cost_cents counts
        """
        max_concurrent = self._resolve_concurrency()
        semaphore = asyncio.Semaphore(max_concurrent)
        db_lock = asyncio.Lock()

        successful = 0
        failed = 0
        total_cost_cents = 0
        successful_write_back_updates: dict[int, dict[str, str]] = {}

        pending_rows = [r for r in rows if r.status == "pending"]

        # Pre-hydrate commodities for international rows that need them.
        exec_commodity_cache: dict[str, list[dict]] = {}
        if pending_rows:
            order_ids = []
            for r in pending_rows:
                try:
                    od = self._parse_order_data(r)
                    oid = od.get("order_id") or od.get("order_number")
                    if oid:
                        order_ids.append(str(oid))
                except Exception as e:
                    logger.warning(
                        "Skipping commodity lookup for row %s (parse error): %s",
                        getattr(r, "row_number", "?"),
                        e,
                    )
            if order_ids:
                try:
                    raw = await self._get_commodities_bulk(order_ids)
                    exec_commodity_cache = {str(k): v for k, v in raw.items()}
                except Exception as e:
                    logger.warning("Commodity bulk fetch failed (non-critical): %s", e)

        async def _process_row(row: Any) -> None:
            """Process a single row with concurrency control."""
            nonlocal successful, failed, total_cost_cents

            async with semaphore:
                try:
                    # Parse and build payload (CPU-bound, fast)
                    order_data = self._parse_order_data(row)

                    # International validation (execute)
                    dest_country = order_data.get("ship_to_country", DEFAULT_ORIGIN_COUNTRY)
                    eff_service = service_code or order_data.get("service_code", ServiceCode.GROUND.value)
                    origin_country = shipper.get("countryCode", DEFAULT_ORIGIN_COUNTRY)
                    requirements = get_requirements(origin_country, dest_country, eff_service)

                    if requirements.not_shippable_reason:
                        raise ValueError(requirements.not_shippable_reason)

                    # Hydrate commodities from cache if needed
                    if requirements.requires_commodities and not order_data.get("commodities"):
                        oid = str(order_data.get("order_id") or order_data.get("order_number") or "")
                        if oid and oid in exec_commodity_cache:
                            order_data["commodities"] = exec_commodity_cache[oid]

                    if requirements.is_international or requirements.requires_invoice_line_total:
                        validation_errors = validate_international_readiness(
                            order_data, requirements,
                        )
                        if validation_errors:
                            raise ValueError(
                                "; ".join(e.message for e in validation_errors)
                            )

                    simplified = build_shipment_request(
                        order_data=order_data,
                        shipper=shipper,
                        service_code=service_code,
                    )

                    api_payload = build_ups_api_payload(
                        simplified,
                        account_number=self._account_number,
                    )

                    # Call UPS via async MCP client
                    result = await self._ups.create_shipment(request_body=api_payload)

                    # Extract results — prefer package tracking number,
                    # fall back to shipment ID (UPS test env masks package-level numbers)
                    tracking_numbers = result.get("trackingNumbers", [])
                    tracking_number = tracking_numbers[0] if tracking_numbers else ""
                    if not tracking_number or "XXXX" in tracking_number:
                        tracking_number = result.get(
                            "shipmentIdentificationNumber", tracking_number
                        )

                    # Save label with unique filename per row
                    label_path = ""
                    label_data_list = result.get("labelData", [])
                    if label_data_list and label_data_list[0]:
                        label_path = self._save_label(
                            tracking_number,
                            label_data_list[0],
                            job_id=job_id,
                            row_number=row.row_number,
                        )

                    # Cost in cents
                    charges = result.get("totalCharges", {})
                    cost_cents = _dollars_to_cents(charges.get("monetaryValue", "0"))

                    # International charge breakdown and destination storage
                    row_dest_country = dest_country if dest_country.upper() != DEFAULT_ORIGIN_COUNTRY else None
                    row_duties_taxes_cents = None
                    row_charge_breakdown = None

                    charge_breakdown = result.get("chargeBreakdown")
                    if charge_breakdown:
                        row_charge_breakdown = json.dumps(charge_breakdown)
                        duties = charge_breakdown.get("dutiesAndTaxes", {})
                        if duties.get("monetaryValue"):
                            row_duties_taxes_cents = _dollars_to_cents(
                                duties["monetaryValue"]
                            )

                    # Serialize DB writes and progress events
                    async with db_lock:
                        row.tracking_number = tracking_number
                        row.label_path = label_path
                        row.cost_cents = cost_cents
                        row.destination_country = row_dest_country
                        row.duties_taxes_cents = row_duties_taxes_cents
                        row.charge_breakdown = row_charge_breakdown
                        row.status = "completed"
                        row.processed_at = datetime.now(UTC).isoformat()
                        self._db.commit()

                        successful += 1
                        total_cost_cents += cost_cents
                        if tracking_number:
                            successful_write_back_updates[row.row_number] = {
                                "tracking_number": tracking_number,
                                "shipped_at": row.processed_at or "",
                            }

                        if on_progress:
                            await on_progress(
                                "row_completed",
                                job_id=job_id,
                                row_number=row.row_number,
                                tracking_number=tracking_number,
                                cost_cents=cost_cents,
                            )

                    logger.info(
                        "Row %d completed: tracking=%s, cost=%d cents",
                        row.row_number,
                        tracking_number,
                        cost_cents,
                    )

                except (UPSServiceError, ValueError, Exception) as e:
                    error_code = getattr(e, "code", "E-3005")
                    error_message = str(e)

                    async with db_lock:
                        row.status = "failed"
                        row.error_code = error_code
                        row.error_message = error_message
                        self._db.commit()

                        failed += 1

                        if on_progress:
                            await on_progress(
                                "row_failed",
                                job_id=job_id,
                                row_number=row.row_number,
                                error_code=error_code,
                                error_message=error_message,
                            )

                    logger.error("Row %d failed: %s", row.row_number, e)

        # Process all rows concurrently (bounded by semaphore)
        await asyncio.gather(*[_process_row(row) for row in pending_rows])

        write_back_result: dict[str, Any] = {
            "status": "skipped",
            "message": "No successful tracking updates to write back.",
        }
        if successful_write_back_updates and not write_back_enabled:
            write_back_result = {
                "status": "skipped",
                "message": "Write-back disabled for interactive shipment.",
            }
        elif successful_write_back_updates:
            try:
                gw = await get_data_gateway()
                source_info = await gw.get_source_info()
                if source_info is not None:
                    source_type = source_info.get("source_type", "")

                    # Route to external platform or local file write-back
                    if source_type in (
                        "shopify", "woocommerce", "sap", "oracle",
                    ):
                        ext = await get_external_sources_client()
                        gw_result = await self._write_back_external(
                            ext, source_type,
                            successful_write_back_updates, rows,
                        )
                    else:
                        gw_result = await gw.write_back_batch(
                            successful_write_back_updates,
                        )

                    # Normalize gateway result to include a status key
                    failures = gw_result.get("failure_count", 0)
                    gw_result["status"] = (
                        "partial" if failures > 0 else "success"
                    )
                    write_back_result = gw_result
                    logger.info(
                        (
                            "Batch write-back finished: job_id=%s success=%s "
                            "failures=%s status=%s source=%s"
                        ),
                        job_id,
                        write_back_result.get("success_count"),
                        write_back_result.get("failure_count"),
                        write_back_result["status"],
                        source_type,
                    )
                    if failures > 0:
                        logger.warning(
                            (
                                "Batch write-back had failures: "
                                "job_id=%s success=%s failures=%s"
                            ),
                            job_id,
                            write_back_result.get("success_count"),
                            failures,
                        )
                else:
                    write_back_result = {
                        "status": "skipped",
                        "message": "No active source connected for write-back.",
                    }
            except Exception as wb_err:
                write_back_result = {
                    "status": "error",
                    "message": str(wb_err),
                }
                logger.warning(
                    (
                        "Batch write-back raised after shipment processing: "
                        "job_id=%s error=%s (recovery: replay_write_back_from_job)"
                    ),
                    job_id,
                    wb_err,
                )

        return {
            "job_id": job_id,
            "successful": successful,
            "failed": failed,
            "total_cost_cents": total_cost_cents,
            "total_rows": len(rows),
            "write_back": write_back_result,
        }

    async def _write_back_external(
        self,
        ext_client: Any,
        platform: str,
        updates: dict[int, dict[str, Any]],
        rows: list[Any],
    ) -> dict[str, Any]:
        """Route tracking write-back to an external platform.

        Instead of writing tracking numbers back to a local file (CSV/Excel),
        this method pushes them to the originating platform (e.g., Shopify)
        via the ExternalSourcesMCPClient.

        Args:
            ext_client: ExternalSourcesMCPClient instance
            platform: Platform identifier (shopify, woocommerce, etc.)
            updates: Map of row_number → {tracking_number, shipped_at}
            rows: List of JobRow objects for order_data lookup

        Returns:
            Dict matching write_back_batch schema:
            {success_count, failure_count, errors}
        """
        success = 0
        failures = 0
        errors: list[dict[str, Any]] = []

        row_map = {r.row_number: r for r in rows}

        for row_number, data in updates.items():
            row = row_map.get(row_number)
            if not row:
                failures += 1
                errors.append({
                    "row_number": row_number,
                    "error": f"Row {row_number} not found in job rows",
                })
                continue

            if not row.order_data:
                failures += 1
                errors.append({
                    "row_number": row_number,
                    "error": "Missing order_data on row",
                })
                continue
            try:
                order_data = json.loads(row.order_data)
            except (json.JSONDecodeError, TypeError):
                failures += 1
                errors.append({
                    "row_number": row_number,
                    "error": "Malformed order_data JSON on row",
                })
                continue
            order_id = order_data.get("order_id")
            if not order_id:
                failures += 1
                errors.append({
                    "row_number": row_number,
                    "error": "Missing order_id in order_data",
                })
                continue

            try:
                result = await ext_client.update_tracking(
                    platform=platform,
                    order_id=str(order_id),
                    tracking_number=data["tracking_number"],
                    carrier=UPS_CARRIER_NAME,
                )
                if result.get("success"):
                    success += 1
                else:
                    failures += 1
                    errors.append({
                        "row_number": row_number,
                        "error": result.get("error", "Unknown platform error"),
                    })
            except Exception as e:
                failures += 1
                errors.append({
                    "row_number": row_number,
                    "error": str(e),
                })

        return {
            "success_count": success,
            "failure_count": failures,
            "errors": errors,
        }

    def _parse_order_data(self, row: Any) -> dict[str, Any]:
        """Parse order_data JSON from a JobRow.

        Args:
            row: JobRow with order_data JSON string

        Returns:
            Parsed order data dict

        Raises:
            ValueError: If order_data is invalid JSON
        """
        if not row.order_data:
            return {}
        try:
            return json.loads(row.order_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid order_data JSON on row {row.row_number}: {e}")

    async def _get_commodities_bulk(
        self, order_ids: list[int | str],
    ) -> dict[int | str, list[dict]]:
        """Fetch commodities for orders via the data source gateway.

        Resolves the process-global DataSourceMCPClient via get_data_gateway()
        (already imported at module level). Delegates to its
        get_commodities_bulk() method which calls the MCP tool.
        Returns empty dict on any failure (non-critical for batch flow).

        Args:
            order_ids: List of order IDs to retrieve commodities for.

        Returns:
            Dict mapping order_id to list of commodity dicts.
        """
        try:
            gateway = await get_data_gateway()
            return await gateway.get_commodities_bulk(order_ids)
        except Exception as e:
            logger.warning("Commodity fetch failed (non-critical): %s", e)
            return {}

    def _save_label(
        self,
        tracking_number: str,
        base64_data: str,
        job_id: str = "",
        row_number: int = 0,
    ) -> str:
        """Save base64-encoded label to disk with unique filename per row.

        Uses job_id prefix and row_number to guarantee unique filenames even
        when the UPS sandbox returns identical tracking numbers for all
        shipments (e.g. "1ZXXXXXXXXXXXXXXXX").

        Args:
            tracking_number: UPS tracking number (may not be unique in sandbox)
            base64_data: Base64-encoded PDF label
            job_id: Job UUID for filename uniqueness
            row_number: 1-based row number within the job

        Returns:
            Absolute path to saved label file
        """
        labels_dir = Path(self._labels_dir)
        labels_dir.mkdir(parents=True, exist_ok=True)

        # Use job_id prefix + row_number to guarantee unique filenames
        # even when UPS sandbox returns the same tracking number for all rows
        job_prefix = job_id[:8] if job_id else "unknown"
        filename = f"{job_prefix}_row{row_number:03d}_{tracking_number}.pdf"
        filepath = labels_dir / filename

        pdf_bytes = base64.b64decode(base64_data)
        filepath.write_bytes(pdf_bytes)

        return str(filepath)
