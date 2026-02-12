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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from src.services.ups_payload_builder import (
    build_shipment_request,
    build_ups_api_payload,
    build_ups_rate_payload,
)
from src.services.errors import UPSServiceError

logger = logging.getLogger(__name__)

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

    MAX_PREVIEW_ROWS = 20

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

    async def preview(
        self,
        job_id: str,
        rows: list[Any],
        shipper: dict[str, str],
        service_code: str | None = None,
    ) -> dict[str, Any]:
        """Generate preview with cost estimates.

        Rates up to MAX_PREVIEW_ROWS individually, estimates the rest
        from the average cost.

        Args:
            job_id: Job UUID for tracking
            rows: List of JobRow objects with order_data
            shipper: Shipper address info
            service_code: Optional service code override

        Returns:
            Dict with total_estimated_cost_cents, preview_rows, etc.
        """
        preview_rows = []
        total_cost_cents = 0

        for row in rows[: self.MAX_PREVIEW_ROWS]:
            order_data = self._parse_order_data(row)
            simplified = build_shipment_request(
                order_data=order_data,
                shipper=shipper,
                service_code=service_code,
            )
            rate_payload = build_ups_rate_payload(
                simplified, account_number=self._account_number,
            )

            rate_error: str | None = None
            try:
                rate_result = await self._ups.get_rate(request_body=rate_payload)
                amount = rate_result.get("totalCharges", {}).get("monetaryValue", "0")
                cost_cents = int(float(amount) * 100)
            except UPSServiceError as e:
                logger.warning("Rate quote failed for row %s: %s", row.row_number, e)
                cost_cents = 0
                rate_error = str(e)

            total_cost_cents += cost_cents

            row_info: dict[str, Any] = {
                "row_number": row.row_number,
                "recipient_name": order_data.get("ship_to_name", f"Row {row.row_number}"),
                "city_state": f"{order_data.get('ship_to_city', '')}, {order_data.get('ship_to_state', '')}",
                "estimated_cost_cents": cost_cents,
            }
            if rate_error:
                row_info["rate_error"] = rate_error
            preview_rows.append(row_info)

        # Estimate remaining rows from average
        additional_rows = max(0, len(rows) - len(preview_rows))
        if additional_rows > 0 and preview_rows:
            avg_cost = total_cost_cents / len(preview_rows)
            total_estimated_cost_cents = total_cost_cents + int(avg_cost * additional_rows)
        else:
            total_estimated_cost_cents = total_cost_cents

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

        Returns:
            Dict with successful, failed, total_cost_cents counts
        """
        max_concurrent = int(os.environ.get("BATCH_CONCURRENCY", "5"))
        semaphore = asyncio.Semaphore(max_concurrent)
        db_lock = asyncio.Lock()

        successful = 0
        failed = 0
        total_cost_cents = 0

        pending_rows = [r for r in rows if r.status == "pending"]

        async def _process_row(row: Any) -> None:
            """Process a single row with concurrency control."""
            nonlocal successful, failed, total_cost_cents

            async with semaphore:
                try:
                    # Parse and build payload (CPU-bound, fast)
                    order_data = self._parse_order_data(row)

                    simplified = build_shipment_request(
                        order_data=order_data,
                        shipper=shipper,
                        service_code=service_code,
                    )

                    api_payload = build_ups_api_payload(
                        simplified, account_number=self._account_number,
                    )

                    # Call UPS via async MCP client
                    result = await self._ups.create_shipment(request_body=api_payload)

                    # Extract results — prefer package tracking number,
                    # fall back to shipment ID (UPS test env masks package-level numbers)
                    tracking_numbers = result.get("trackingNumbers", [])
                    tracking_number = tracking_numbers[0] if tracking_numbers else ""
                    if not tracking_number or "XXXX" in tracking_number:
                        tracking_number = result.get("shipmentIdentificationNumber", tracking_number)

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
                    cost_cents = int(float(charges.get("monetaryValue", "0")) * 100)

                    # Serialize DB writes and progress events
                    async with db_lock:
                        row.tracking_number = tracking_number
                        row.label_path = label_path
                        row.cost_cents = cost_cents
                        row.status = "completed"
                        row.processed_at = datetime.now(UTC).isoformat()
                        self._db.commit()

                        successful += 1
                        total_cost_cents += cost_cents

                        if on_progress:
                            await on_progress(
                                "row_completed", job_id=job_id,
                                row_number=row.row_number,
                                tracking_number=tracking_number,
                                cost_cents=cost_cents,
                            )

                    # Write-back tracking number to source file (best-effort)
                    try:
                        from src.services.data_source_service import DataSourceService

                        ds_svc = DataSourceService.get_instance()
                        if ds_svc.get_source_info() is not None and tracking_number:
                            await ds_svc.write_back(row.row_number, tracking_number)
                    except Exception as wb_err:
                        logger.debug(
                            "Write-back skipped for row %d: %s",
                            row.row_number,
                            wb_err,
                        )

                    logger.info(
                        "Row %d completed: tracking=%s, cost=%d cents",
                        row.row_number, tracking_number, cost_cents,
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
                                "row_failed", job_id=job_id,
                                row_number=row.row_number,
                                error_code=error_code,
                                error_message=error_message,
                            )

                    logger.error("Row %d failed: %s", row.row_number, e)

        # Process all rows concurrently (bounded by semaphore)
        await asyncio.gather(*[_process_row(row) for row in pending_rows])

        return {
            "job_id": job_id,
            "successful": successful,
            "failed": failed,
            "total_cost_cents": total_cost_cents,
            "total_rows": len(rows),
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
