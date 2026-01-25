"""Data models for batch execution.

Defines dataclasses for batch previews, execution results, and
crash recovery information.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PreviewRow:
    """Single row in preview display.

    Represents one shipment in the batch preview table shown
    before execution in CONFIRM mode.
    """

    row_number: int
    """1-based row number from source data."""

    recipient_name: str
    """Name of the shipment recipient."""

    city_state: str
    """City and state in 'City, ST' format."""

    service: str
    """UPS service name (e.g., 'Ground', 'Next Day Air')."""

    estimated_cost_cents: int
    """Estimated shipping cost in cents."""

    warnings: list[str] = field(default_factory=list)
    """List of warning messages for this row."""


@dataclass
class BatchPreview:
    """Preview of batch before execution.

    Generated in CONFIRM mode to show the user what will be shipped.
    Per CONTEXT.md Decision 1, shows first 20 rows in detail with
    aggregate stats for remaining rows.
    """

    job_id: str
    """Unique identifier for the batch job."""

    total_rows: int
    """Total number of rows in the batch."""

    preview_rows: list[PreviewRow]
    """First 20 rows with full detail."""

    additional_rows: int
    """Number of rows beyond the preview (total_rows - len(preview_rows))."""

    total_estimated_cost_cents: int
    """Estimated total cost for all rows in cents."""

    rows_with_warnings: int
    """Number of rows that have warnings."""


@dataclass
class BatchResult:
    """Result of batch execution.

    Contains final statistics after a batch completes or fails.
    """

    success: bool
    """Whether the batch completed without errors."""

    job_id: str
    """Unique identifier for the batch job."""

    total_rows: int
    """Total number of rows in the batch."""

    processed_rows: int
    """Number of rows that were processed (attempted)."""

    successful_rows: int
    """Number of rows that completed successfully."""

    failed_rows: int
    """Number of rows that failed."""

    total_cost_cents: int
    """Total cost of successful shipments in cents."""

    error_code: Optional[str] = None
    """Error code if batch failed (fail-fast)."""

    error_message: Optional[str] = None
    """Error message if batch failed."""


@dataclass
class InterruptedJobInfo:
    """Information about an interrupted job for recovery prompt.

    Used to present crash recovery options to the user when an
    interrupted job is detected on startup.

    Per CONTEXT.md Decision 3, the user is prompted with:
    'Job X was interrupted at row 47/200. Resume, restart, or cancel?'
    """

    job_id: str
    """Unique identifier for the interrupted job."""

    job_name: str
    """Human-readable name for the job."""

    completed_rows: int
    """Number of rows successfully completed before interruption."""

    total_rows: int
    """Total number of rows in the batch."""

    remaining_rows: int
    """Number of rows left to process (total_rows - completed_rows)."""

    last_row_number: Optional[int] = None
    """Row number of the last successfully processed row."""

    last_tracking_number: Optional[str] = None
    """Tracking number of the last successful shipment."""

    error_code: Optional[str] = None
    """Error code if crash was due to an error."""

    error_message: Optional[str] = None
    """Error message if crash was due to an error."""
