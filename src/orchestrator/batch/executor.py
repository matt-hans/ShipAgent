"""Batch execution engine with fail-fast and crash recovery.

Per CONTEXT.md:
- Decision 3: Resume from first pending row on crash recovery
- Decision 4: Immediate write-back after each successful row

Per RESEARCH.md:
- Pattern 2: Per-row state checkpoint
- Pattern 4: Fail-fast execution loop
"""

import json
import logging
from typing import Any, Callable, Awaitable

from jinja2 import Environment

from src.db.models import JobStatus
from src.services.job_service import JobService
from src.services.audit_service import AuditService, EventType
from src.orchestrator.batch.models import BatchResult
from src.orchestrator.batch.events import BatchEventEmitter
from src.orchestrator.filters.logistics import get_logistics_environment


logger = logging.getLogger(__name__)


class BatchExecutor:
    """Executes batch shipments with fail-fast and crash recovery.

    Orchestrates row-by-row processing with per-row state commits
    for crash recovery. Implements fail-fast behavior per BATCH-05,
    halting the entire batch on the first error.

    Attributes:
        events: Event emitter for registering lifecycle observers.
    """

    def __init__(
        self,
        job_service: JobService,
        audit_service: AuditService,
        data_mcp_call: Callable[[str, dict], Awaitable[dict]],
        ups_mcp_call: Callable[[str, dict], Awaitable[dict]],
        jinja_env: Environment | None = None,
    ) -> None:
        """Initialize the batch executor.

        Args:
            job_service: JobService for state management and row tracking.
            audit_service: AuditService for audit logging.
            data_mcp_call: Async function to call Data MCP tools.
                           Signature: (tool_name, params) -> result dict
            ups_mcp_call: Async function to call UPS MCP tools.
                          Signature: (tool_name, params) -> result dict
            jinja_env: Optional Jinja2 environment for template rendering.
                       Defaults to logistics environment with filters.
        """
        self._job_service = job_service
        self._audit_service = audit_service
        self._data_mcp = data_mcp_call
        self._ups_mcp = ups_mcp_call
        self._jinja_env = jinja_env or get_logistics_environment()
        self._event_emitter = BatchEventEmitter()

    @property
    def events(self) -> BatchEventEmitter:
        """Get event emitter for observer registration.

        Returns:
            BatchEventEmitter for subscribing to lifecycle events.
        """
        return self._event_emitter

    async def execute(
        self,
        job_id: str,
        mapping_template: str,
        shipper_info: dict[str, Any],
        source_name: str = "default",
    ) -> BatchResult:
        """Execute batch shipments with fail-fast behavior.

        Processes all pending rows for the given job, creating UPS
        shipments and writing tracking numbers back to the source.
        On any error, halts immediately (fail-fast) per BATCH-05.

        Supports crash recovery per BATCH-06 by:
        - Only processing rows with status 'pending'
        - Committing state after each row
        - Skipping already-completed rows on resume

        Args:
            job_id: UUID of the job (already created with rows via JobService).
            mapping_template: Jinja2 template string for generating UPS payloads.
            shipper_info: Shipper address and account info for UPS requests.
            source_name: Data source name for get_row calls (default "default").

        Returns:
            BatchResult containing:
            - success: True if all rows completed
            - job_id: The processed job ID
            - Row counts: total, processed, successful, failed
            - total_cost_cents: Sum of all shipment costs
            - error_code/error_message: Set if batch failed

        Raises:
            ValueError: If job_id does not exist.
        """
        # 1. Get job and validate existence
        job = self._job_service.get_job(job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")

        # 2. Transition job to running state
        old_status = job.status
        self._job_service.update_status(job_id, JobStatus.running)

        # 3. Log state change via audit service
        self._audit_service.log_state_change(job_id, old_status, JobStatus.running.value)

        # 4. Emit batch_started event
        await self._event_emitter.emit_batch_started(job_id, job.total_rows)

        try:
            # 5. Get pending rows (supports crash recovery - skips completed)
            pending_rows = self._job_service.get_pending_rows(job_id)

            # 6. Process each row
            for job_row in pending_rows:
                # 6a. Emit row_started event
                await self._event_emitter.emit_row_started(job_id, job_row.row_number)

                # 6b. Get row data from Data MCP
                row_data_result = await self._data_mcp(
                    "get_row",
                    {"source": source_name, "row_number": job_row.row_number},
                )
                row_data = row_data_result.get("data", row_data_result)

                # 6c. Process the single row
                result = await self._process_single_row(
                    job_id=job_id,
                    job_row=job_row,
                    row_data=row_data,
                    mapping_template=mapping_template,
                    shipper_info=shipper_info,
                    source_name=source_name,
                )

                # 6d. Emit row_completed event on success
                await self._event_emitter.emit_row_completed(
                    job_id=job_id,
                    row_number=job_row.row_number,
                    tracking_number=result["tracking_number"],
                    cost_cents=result["cost_cents"],
                )

            # 7. All rows complete - transition to completed
            self._job_service.update_status(job_id, JobStatus.completed)
            self._audit_service.log_state_change(
                job_id, JobStatus.running.value, JobStatus.completed.value
            )

            # Get final summary
            summary = self._job_service.get_job_summary(job_id)

            # Emit batch_completed event
            await self._event_emitter.emit_batch_completed(
                job_id=job_id,
                total_rows=summary["total_rows"],
                successful=summary["successful_rows"],
                total_cost_cents=summary["total_cost_cents"],
            )

            return BatchResult(
                success=True,
                job_id=job_id,
                total_rows=summary["total_rows"],
                processed_rows=summary["processed_rows"],
                successful_rows=summary["successful_rows"],
                failed_rows=summary["failed_rows"],
                total_cost_cents=summary["total_cost_cents"],
            )

        except Exception as e:
            # 8. Fail-fast: set error, transition to failed
            error_code, error_message = self._translate_error(e)

            self._job_service.set_error(job_id, error_code, error_message)
            self._job_service.update_status(job_id, JobStatus.failed)
            self._audit_service.log_state_change(
                job_id, JobStatus.running.value, JobStatus.failed.value
            )
            self._audit_service.log_job_error(job_id, error_code, error_message)

            # Get summary at point of failure
            summary = self._job_service.get_job_summary(job_id)

            # Emit batch_failed event
            await self._event_emitter.emit_batch_failed(
                job_id=job_id,
                error_code=error_code,
                error_message=error_message,
                processed=summary["processed_rows"],
            )

            return BatchResult(
                success=False,
                job_id=job_id,
                total_rows=summary["total_rows"],
                processed_rows=summary["processed_rows"],
                successful_rows=summary["successful_rows"],
                failed_rows=summary["failed_rows"],
                total_cost_cents=summary["total_cost_cents"],
                error_code=error_code,
                error_message=error_message,
            )

    async def _process_single_row(
        self,
        job_id: str,
        job_row: Any,
        row_data: dict[str, Any],
        mapping_template: str,
        shipper_info: dict[str, Any],
        source_name: str,
    ) -> dict[str, Any]:
        """Process a single row with state checkpointing.

        Implements Pattern 2 (per-row state checkpoint) from RESEARCH.md:
        1. Mark row as processing
        2. Render template and call UPS
        3. Complete row with tracking info
        4. Write back to source
        5. Log audit event

        Args:
            job_id: UUID of the parent job.
            job_row: JobRow object being processed.
            row_data: Data from the source row.
            mapping_template: Jinja2 template for payload generation.
            shipper_info: Shipper address and account info.
            source_name: Data source name for write_back.

        Returns:
            Dict with tracking_number, label_path, cost_cents.

        Raises:
            Exception: Any error from UPS API or processing, triggering fail-fast.
        """
        # 1. Mark row as processing
        self._job_service.start_row(job_row.id)
        self._audit_service.log_row_event(
            job_id=job_id,
            row_number=job_row.row_number,
            event="started",
        )

        try:
            # 2. Render template with row data
            payload = self._render_payload(mapping_template, row_data, shipper_info)

            # 3. Call UPS MCP to create shipment
            ups_result = await self._ups_mcp("shipping_create", payload)

            # 4. Extract tracking number, label path, cost
            tracking_number, label_path, cost_cents = self._extract_shipment_result(
                ups_result
            )

            # 5. Mark row complete with tracking info
            self._job_service.complete_row(
                row_id=job_row.id,
                tracking_number=tracking_number,
                label_path=label_path,
                cost_cents=cost_cents,
            )

            # 6. Write back to source (per CONTEXT.md Decision 4: immediate)
            await self._data_mcp(
                "write_back",
                {
                    "row_number": job_row.row_number,
                    "tracking_number": tracking_number,
                },
            )

            # 7. Log audit event
            self._audit_service.log_row_event(
                job_id=job_id,
                row_number=job_row.row_number,
                event="completed",
                details={"tracking_number": tracking_number, "cost_cents": cost_cents},
            )

            return {
                "tracking_number": tracking_number,
                "label_path": label_path,
                "cost_cents": cost_cents,
            }

        except Exception as e:
            # On error: mark row failed, log, and re-raise for fail-fast
            error_code, error_message = self._translate_error(e)

            self._job_service.fail_row(
                row_id=job_row.id,
                error_code=error_code,
                error_message=error_message,
            )

            self._audit_service.log_row_event(
                job_id=job_id,
                row_number=job_row.row_number,
                event="failed",
                details={"error_code": error_code, "error_message": error_message},
            )

            # Emit row_failed event before re-raising
            await self._event_emitter.emit_row_failed(
                job_id=job_id,
                row_number=job_row.row_number,
                error_code=error_code,
                error_message=error_message,
            )

            raise  # Re-raise for fail-fast behavior

    def _render_payload(
        self,
        template: str,
        row_data: dict[str, Any],
        shipper_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Render Jinja2 template to generate UPS payload.

        Combines row data with shipper info and renders through
        the Jinja2 template to produce a UPS-compatible payload.

        Args:
            template: Jinja2 template string.
            row_data: Data from the current source row.
            shipper_info: Shipper address and account info.

        Returns:
            Dict payload for UPS shipping_create.

        Raises:
            Exception: Template rendering errors.
        """
        jinja_template = self._jinja_env.from_string(template)

        # Build context with row data and shipper info
        context = {
            "row": row_data,
            "shipper": shipper_info,
            **row_data,  # Also expose row fields at top level for convenience
        }

        rendered = jinja_template.render(context)

        # Parse JSON result
        return json.loads(rendered)

    def _extract_shipment_result(
        self,
        ups_response: dict[str, Any],
    ) -> tuple[str, str, int]:
        """Extract tracking number, label path, and cost from UPS response.

        Handles the UPS shipping_create response format to extract
        the key shipment details.

        Args:
            ups_response: Response from UPS MCP shipping_create.

        Returns:
            Tuple of (tracking_number, label_path, cost_cents).

        Raises:
            ValueError: If response is missing required fields.
        """
        # Handle different response structures
        # Primary format from UPS MCP
        if "trackingNumber" in ups_response:
            tracking = ups_response["trackingNumber"]
        elif "trackingNumbers" in ups_response and ups_response["trackingNumbers"]:
            tracking = ups_response["trackingNumbers"][0]
        else:
            raise ValueError("UPS response missing tracking number")

        # Label path
        if "labelPath" in ups_response:
            label_path = ups_response["labelPath"]
        elif "labelPaths" in ups_response and ups_response["labelPaths"]:
            label_path = ups_response["labelPaths"][0]
        else:
            label_path = ""

        # Cost in cents
        cost_cents = 0
        if "totalCharges" in ups_response:
            charges = ups_response["totalCharges"]
            if isinstance(charges, dict):
                # {"monetaryValue": "12.50", "currencyCode": "USD"}
                amount = float(charges.get("monetaryValue", 0))
            else:
                amount = float(charges)
            cost_cents = int(amount * 100)
        elif "cost" in ups_response:
            cost_cents = int(float(ups_response["cost"]) * 100)

        return tracking, label_path, cost_cents

    def _translate_error(self, error: Exception) -> tuple[str, str]:
        """Translate exception to error code and message.

        Maps exceptions to the E-XXXX error code format from
        the error registry.

        Args:
            error: Exception that occurred.

        Returns:
            Tuple of (error_code, error_message).
        """
        error_str = str(error)

        # Check for common error patterns
        if "UPS" in error_str or "shipping" in error_str.lower():
            # UPS API errors
            if "auth" in error_str.lower() or "401" in error_str:
                return "E-5001", f"UPS authentication failed: {error_str}"
            elif "rate limit" in error_str.lower() or "429" in error_str:
                return "E-3002", f"UPS rate limit exceeded: {error_str}"
            elif "address" in error_str.lower():
                return "E-3003", f"UPS address validation failed: {error_str}"
            else:
                return "E-3005", f"UPS error: {error_str}"

        elif "template" in error_str.lower() or "jinja" in error_str.lower():
            return "E-4003", f"Template error: {error_str}"

        elif "database" in error_str.lower() or "sql" in error_str.lower():
            return "E-4001", f"Database error: {error_str}"

        elif "file" in error_str.lower() or "path" in error_str.lower():
            return "E-4002", f"File system error: {error_str}"

        elif isinstance(error, ValueError):
            return "E-1001", f"Data error: {error_str}"

        else:
            # Generic system error
            return "E-4001", f"System error: {error_str}"
