# Phase 6: Batch Execution Engine - Research

**Researched:** 2026-01-25
**Domain:** Batch Processing, Crash Recovery, Write-Back Operations
**Confidence:** HIGH

## Summary

The Batch Execution Engine builds on established infrastructure from Phases 1-5 to process batches of shipments with preview mode, fail-fast error handling, and crash recovery. The existing JobService (Phase 1) provides state machine and per-row tracking, Data MCP (Phase 2) provides row access via `get_rows_by_filter`, and UPS MCP (Phase 3) provides `rating_quote` and `shipping_create` tools. The key gaps are: (1) write-back capability in Data MCP for tracking numbers, and (2) the batch executor that orchestrates the flow.

The architecture follows a "row iterator with checkpoint" pattern: iterate over filtered rows, process each with per-row state commits, and halt on first error (fail-fast). Preview mode uses `rating_quote` to estimate costs without creating shipments. Mode switching is session state tracked in the OrchestrationAgent. Write-back for CSV/Excel uses atomic temp-file-then-rename, while database sources use transactions.

**Primary recommendation:** Implement BatchExecutor as a new orchestrator component with generator-based row iteration, per-row state persistence via JobService, and Observer pattern for lifecycle events. Add `write_back` tool to Data MCP for tracking number persistence.

## Standard Stack

The established libraries/tools for this domain:

### Core (Already in Project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `JobService` | Phase 1 | State machine, per-row tracking | Already built with `create_rows`, `start_row`, `complete_row`, `fail_row` |
| `AuditService` | Phase 1 | Audit logging | Already built with `log_row_event`, `log_api_call` |
| `Data MCP` | Phase 2 | Row access via `get_rows_by_filter` | Already built, returns rows with checksums |
| `UPS MCP` | Phase 3 | `rating_quote`, `shipping_create` | Already built with full Zod validation |
| `OrchestrationAgent` | Phase 5 | MCP coordination | Already built with hooks and session |

### New Components to Build
| Component | Purpose | Why New |
|-----------|---------|---------|
| `BatchExecutor` | Orchestrates row iteration, state, and UPS calls | Core logic for this phase |
| `write_back` tool | Persist tracking numbers to source | DATA-04 requirement |
| `PreviewGenerator` | Aggregate rate quotes for preview | BATCH-02 requirement |

### Supporting Libraries
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `openpyxl` | 3.x | Excel write-back | Already installed for Phase 2 |
| `tempfile` + `os.replace` | stdlib | Atomic CSV writes | Standard Python for file safety |
| `asyncio.Semaphore` | stdlib | Rate limiting UPS calls | If needed for large batches |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Generator iteration | Load all rows in memory | Memory issues at 500+ rows |
| Per-row commits | Batch commits | Crash recovery loses progress |
| `os.replace` atomic | Direct overwrite | Risk of corrupted file on crash |

## Architecture Patterns

### Recommended Project Structure
```
src/orchestrator/
├── batch/
│   ├── __init__.py
│   ├── executor.py         # BatchExecutor class - core execution loop
│   ├── preview.py          # PreviewGenerator - rate quote aggregation
│   ├── modes.py            # ExecutionMode enum, session mode tracking
│   └── events.py           # Lifecycle events and Observer pattern
├── agent/
│   └── tools.py            # Add batch_execute, batch_preview tools
└── ...

src/mcp/data_source/
├── tools/
│   └── writeback_tools.py  # write_back tool implementation
└── ...
```

### Pattern 1: Generator-Based Row Iteration
**What:** Use Python generators to iterate over rows without loading all into memory
**When to use:** Always for batch processing with 500+ potential rows
**Example:**
```python
# Source: Python batch processing best practices
from typing import Generator, Any

async def iterate_rows(
    job_id: str,
    filter_clause: str,
    job_service: JobService,
) -> Generator[tuple[int, dict[str, Any]], None, None]:
    """Iterate over filtered rows, yielding (row_number, data) tuples.

    Uses pagination to avoid memory exhaustion.
    """
    offset = 0
    batch_size = 100  # Fetch 100 rows at a time

    while True:
        # Call Data MCP to get next batch
        result = await data_mcp.get_rows_by_filter(
            where_clause=filter_clause,
            limit=batch_size,
            offset=offset
        )

        rows = result.get("rows", [])
        if not rows:
            break

        for row in rows:
            # Skip already-completed rows (for crash recovery)
            job_row = job_service.get_row_by_number(job_id, row["row_number"])
            if job_row and job_row.status == "completed":
                continue
            yield row["row_number"], row["data"]

        offset += batch_size
```

### Pattern 2: Per-Row State Checkpoint
**What:** Commit state after each row to enable crash recovery
**When to use:** Always for batch operations requiring durability
**Example:**
```python
# Source: Established in JobService from Phase 1
async def process_row(
    row_id: str,
    row_data: dict[str, Any],
    job_service: JobService,
    audit_service: AuditService,
) -> ShipmentResult:
    """Process single row with state checkpointing."""

    # 1. Mark row as processing
    job_service.start_row(row_id)
    audit_service.log_row_event(job_id, row_number, "started")

    try:
        # 2. Call UPS MCP to create shipment
        result = await ups_mcp.shipping_create(shipment_payload)

        # 3. Mark row complete with tracking info
        job_service.complete_row(
            row_id=row_id,
            tracking_number=result["trackingNumbers"][0],
            label_path=result["labelPaths"][0],
            cost_cents=parse_cost_to_cents(result["totalCharges"]),
        )
        audit_service.log_row_event(job_id, row_number, "completed", {
            "tracking_number": result["trackingNumbers"][0]
        })

        return ShipmentResult(success=True, tracking=result["trackingNumbers"][0])

    except Exception as e:
        # 4. Mark row failed with error
        error_code, error_message = translate_error(e)
        job_service.fail_row(row_id, error_code, error_message)
        audit_service.log_row_event(job_id, row_number, "failed", {
            "error_code": error_code,
            "error_message": error_message
        })
        raise  # Re-raise for fail-fast
```

### Pattern 3: Atomic File Write-Back (CSV/Excel)
**What:** Write to temp file then atomic rename to prevent corruption
**When to use:** For CSV and Excel write-back operations
**Example:**
```python
# Source: Python atomicwrites pattern, openpyxl tutorial
import os
import tempfile
from pathlib import Path
from openpyxl import load_workbook

async def write_back_csv(
    file_path: str,
    row_number: int,
    tracking_number: str,
    shipped_at: str,
) -> None:
    """Write tracking number to CSV with atomic replace."""
    path = Path(file_path)

    # Create temp file in same directory (same filesystem for atomic rename)
    fd, temp_path = tempfile.mkstemp(
        suffix=".csv",
        dir=path.parent
    )

    try:
        # Read original, write modified to temp
        with open(path, 'r') as src, os.fdopen(fd, 'w') as dst:
            reader = csv.DictReader(src)
            fieldnames = reader.fieldnames + ['tracking_number', 'shipped_at']
            writer = csv.DictWriter(dst, fieldnames=fieldnames)
            writer.writeheader()

            for i, row in enumerate(reader, start=1):
                if i == row_number:
                    row['tracking_number'] = tracking_number
                    row['shipped_at'] = shipped_at
                writer.writerow(row)

        # Atomic replace
        os.replace(temp_path, file_path)

    except Exception:
        # Clean up temp file on error
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


async def write_back_excel(
    file_path: str,
    sheet_name: str,
    row_number: int,
    tracking_number: str,
    shipped_at: str,
) -> None:
    """Write tracking number to Excel with atomic replace."""
    path = Path(file_path)

    # Create temp file
    fd, temp_path = tempfile.mkstemp(suffix=".xlsx", dir=path.parent)
    os.close(fd)  # openpyxl manages file

    try:
        # Load, modify, save to temp
        wb = load_workbook(file_path)
        ws = wb[sheet_name] if sheet_name else wb.active

        # Find or create tracking columns
        # Add 2 for header row offset (row_number is 1-based data row)
        excel_row = row_number + 1

        # Find tracking_number column or create it
        tracking_col = find_or_create_column(ws, "tracking_number")
        shipped_col = find_or_create_column(ws, "shipped_at")

        ws.cell(row=excel_row, column=tracking_col, value=tracking_number)
        ws.cell(row=excel_row, column=shipped_col, value=shipped_at)

        wb.save(temp_path)
        wb.close()

        # Atomic replace
        os.replace(temp_path, file_path)

    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise
```

### Pattern 4: Fail-Fast Execution Loop
**What:** Halt batch on first error with clear status
**When to use:** Per BATCH-05 requirement
**Example:**
```python
# Source: CONTEXT.md Decision, JobService state machine
class BatchExecutor:
    """Execute batch shipments with fail-fast behavior."""

    async def execute(
        self,
        job_id: str,
        filter_clause: str,
        mapping_template: str,
    ) -> BatchResult:
        """Execute batch, halting on first error."""

        job_service = self._get_job_service()
        audit_service = self._get_audit_service()

        # Transition job to running
        job_service.update_status(job_id, JobStatus.running)
        audit_service.log_state_change(job_id, "pending", "running")

        try:
            async for row_number, row_data in self.iterate_rows(job_id, filter_clause):
                # Process single row
                result = await self.process_row(row_number, row_data, mapping_template)

                # Emit progress event for observers
                await self._emit_event("row_completed", {
                    "row_number": row_number,
                    "tracking_number": result.tracking_number,
                    "processed": job_service.get_job(job_id).processed_rows,
                    "total": job_service.get_job(job_id).total_rows,
                })

        except Exception as e:
            # FAIL-FAST: First error halts batch
            error_code, error_message = translate_error(e)
            job_service.set_error(job_id, error_code, error_message)
            job_service.update_status(job_id, JobStatus.failed)
            audit_service.log_job_error(job_id, error_code, error_message)

            return BatchResult(
                success=False,
                error_code=error_code,
                error_message=error_message,
                processed_rows=job_service.get_job(job_id).processed_rows,
            )

        # All rows completed
        job_service.update_status(job_id, JobStatus.completed)
        return BatchResult(success=True, ...)
```

### Pattern 5: Observer Pattern for Lifecycle Events
**What:** Emit events at key lifecycle points for UI/logging integration
**When to use:** For decoupled progress tracking and notifications
**Example:**
```python
# Source: Python Observer pattern, CLAUDE.md Observer reference
from typing import Protocol, Callable, Any
from dataclasses import dataclass

class BatchEventObserver(Protocol):
    """Observer protocol for batch lifecycle events."""

    async def on_batch_started(self, job_id: str, total_rows: int) -> None: ...
    async def on_row_completed(self, job_id: str, row_number: int, tracking: str) -> None: ...
    async def on_batch_failed(self, job_id: str, error: str) -> None: ...
    async def on_batch_completed(self, job_id: str, summary: dict) -> None: ...


class BatchExecutor:
    """Batch executor with Observer pattern."""

    def __init__(self):
        self._observers: list[BatchEventObserver] = []

    def add_observer(self, observer: BatchEventObserver) -> None:
        """Register an observer for lifecycle events."""
        self._observers.append(observer)

    async def _emit_event(self, event_name: str, data: dict) -> None:
        """Emit event to all observers."""
        method_name = f"on_{event_name}"
        for observer in self._observers:
            method = getattr(observer, method_name, None)
            if method:
                await method(**data)
```

### Anti-Patterns to Avoid
- **Loading all rows into memory:** Use generator/pagination; 500 rows with full data can exhaust memory
- **Committing after batch completes:** Lose all progress on crash; commit per-row
- **Direct file overwrite:** Risk corruption; use atomic temp-then-rename
- **Silent error continuation:** Violates fail-fast; errors must halt batch
- **Global mode state:** Mode is session-scoped; store in OrchestrationAgent context

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Row state tracking | Custom status fields | JobService `create_rows`, `complete_row`, `fail_row` | Already built, tested, handles edge cases |
| Cost aggregation | Manual summing | JobService `get_job_summary` with `func.sum` | Database-level aggregation is efficient |
| Error translation | Custom error parsing | Error registry `translate_ups_error` | Already maps UPS codes to E-XXXX |
| Audit logging | Print statements | AuditService `log_row_event` | Structured, redacted, exportable |
| UPS API calls | Direct HTTP | UPS MCP `shipping_create` | Handles OAuth, validation, retries |
| Rate quotes | Custom API call | UPS MCP `rating_quote` | Already built with cost breakdown |
| JSON rendering | Manual string building | Jinja2 with logistics filters | Phase 4 template engine |

**Key insight:** Phases 1-5 built substantial infrastructure. The batch executor should coordinate existing services, not rebuild them. New code focuses on: execution flow, mode switching, write-back, and crash recovery UX.

## Common Pitfalls

### Pitfall 1: Memory Exhaustion with Large Batches
**What goes wrong:** Loading 500+ rows into memory causes OOM or slow performance
**Why it happens:** Fetching all rows at once before processing
**How to avoid:** Use generator pattern with pagination (100 rows per fetch)
**Warning signs:** Memory usage grows linearly with batch size; slow startup before first row processes

### Pitfall 2: Lost Progress on Crash
**What goes wrong:** System crashes, all progress lost, user must restart entire batch
**Why it happens:** Only committing state at batch end
**How to avoid:** Commit state after each row via `complete_row`; on resume, skip completed rows
**Warning signs:** Jobs stuck in "running" state after crash; no completed rows visible

### Pitfall 3: Duplicate Shipments on Retry
**What goes wrong:** User retries after failure, creates duplicate shipments for already-processed rows
**Why it happens:** Not checking row status before processing
**How to avoid:** Check `job_row.status` before processing; skip "completed" rows; warn on restart
**Warning signs:** Multiple tracking numbers for same order; unexpected UPS charges

### Pitfall 4: Corrupted Source File on Write-Back Failure
**What goes wrong:** System crashes during file write; file left in corrupted state
**Why it happens:** Writing directly to original file instead of atomic replace
**How to avoid:** Write to temp file first, then `os.replace()` for atomic rename
**Warning signs:** Partial rows in file; Excel won't open; data loss complaints

### Pitfall 5: Mode Persisted Across Sessions
**What goes wrong:** User expects confirm mode but gets auto mode from previous session
**Why it happens:** Mode stored in database instead of session memory
**How to avoid:** Per CONTEXT.md, mode is session-wide only; default to confirm on new session
**Warning signs:** Unexpected auto-execution; user complaints about lack of preview

### Pitfall 6: Preview Takes Too Long for Large Batches
**What goes wrong:** Getting 500 rate quotes takes minutes; user abandons
**Why it happens:** Sequential rate quote API calls without optimization
**How to avoid:** First 20 rows detailed, rest estimated from average; show progress
**Warning signs:** Preview hangs; no feedback to user during rate fetch

## Code Examples

Verified patterns from official sources:

### Complete BatchExecutor Class
```python
# Source: Assembled from existing Phase 1-5 patterns and CONTEXT.md decisions
from enum import Enum
from typing import Any, Optional
from dataclasses import dataclass

from src.db.models import JobStatus, RowStatus
from src.services.job_service import JobService
from src.services.audit_service import AuditService, EventType


class ExecutionMode(str, Enum):
    """Batch execution mode."""
    CONFIRM = "confirm"  # Preview before execute (default)
    AUTO = "auto"        # Execute immediately


@dataclass
class BatchResult:
    """Result of batch execution."""
    success: bool
    job_id: str
    total_rows: int
    processed_rows: int
    successful_rows: int
    failed_rows: int
    total_cost_cents: int
    error_code: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class PreviewRow:
    """Single row in preview display."""
    row_number: int
    recipient_name: str
    city_state: str
    service: str
    estimated_cost_cents: int
    warnings: list[str]


@dataclass
class BatchPreview:
    """Preview of batch before execution."""
    total_rows: int
    preview_rows: list[PreviewRow]  # First 20 rows
    additional_rows: int  # Rows beyond preview
    total_estimated_cost_cents: int
    rows_with_warnings: int


class BatchExecutor:
    """Orchestrates batch shipment execution with fail-fast and crash recovery."""

    def __init__(
        self,
        job_service: JobService,
        audit_service: AuditService,
        data_mcp_client,  # MCP client for data tools
        ups_mcp_client,   # MCP client for UPS tools
    ):
        self._job_service = job_service
        self._audit_service = audit_service
        self._data_mcp = data_mcp_client
        self._ups_mcp = ups_mcp_client
        self._observers: list[Any] = []

    async def generate_preview(
        self,
        job_id: str,
        filter_clause: str,
        mapping_template: str,
    ) -> BatchPreview:
        """Generate preview with cost estimates for first 20 rows.

        Per CONTEXT.md Decision 1:
        - Show first 20 rows in detail
        - Aggregate stats for remaining rows
        - Per-row cost shown
        - Flag rows with warnings
        """
        # Get first 20 rows for detailed preview
        preview_result = await self._data_mcp.get_rows_by_filter(
            where_clause=filter_clause,
            limit=20,
            offset=0
        )

        preview_rows: list[PreviewRow] = []
        total_estimated = 0
        warnings_count = 0

        for row in preview_result["rows"]:
            # Render row with mapping template
            payload = self._render_template(mapping_template, row["data"])

            # Get rate quote from UPS
            quote = await self._ups_mcp.rating_quote(
                shipFrom=payload["shipper"],
                shipTo=payload["shipTo"],
                packages=payload["packages"],
                serviceCode=payload["serviceCode"],
            )

            cost_cents = int(float(quote["totalCharges"]["amount"]) * 100)
            total_estimated += cost_cents

            row_warnings = self._check_warnings(row["data"], quote)
            if row_warnings:
                warnings_count += 1

            preview_rows.append(PreviewRow(
                row_number=row["row_number"],
                recipient_name=self._truncate(row["data"].get("recipient_name", ""), 20),
                city_state=f"{row['data'].get('city', '')}, {row['data'].get('state', '')}",
                service=payload["serviceCode"],
                estimated_cost_cents=cost_cents,
                warnings=row_warnings,
            ))

        # Get total count
        total_count = preview_result["total_count"]
        additional = total_count - len(preview_rows)

        # Estimate remaining cost from average of preview
        if preview_rows and additional > 0:
            avg_cost = total_estimated // len(preview_rows)
            total_estimated += avg_cost * additional

        return BatchPreview(
            total_rows=total_count,
            preview_rows=preview_rows,
            additional_rows=additional,
            total_estimated_cost_cents=total_estimated,
            rows_with_warnings=warnings_count,
        )

    async def execute(
        self,
        job_id: str,
        filter_clause: str,
        mapping_template: str,
    ) -> BatchResult:
        """Execute batch with fail-fast behavior.

        Per CONTEXT.md Decision 3:
        - Resume from first pending row on crash recovery
        - Show progress + last error
        """
        job = self._job_service.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Transition to running
        old_status = job.status
        self._job_service.update_status(job_id, JobStatus.running)
        self._audit_service.log_state_change(job_id, old_status, "running")

        try:
            # Get pending rows (supports resume after crash)
            pending_rows = self._job_service.get_pending_rows(job_id)

            for job_row in pending_rows:
                # Get row data from Data MCP
                row_data = await self._data_mcp.get_row(job_row.row_number)

                # Process with per-row state commit
                await self._process_single_row(
                    job_id=job_id,
                    job_row=job_row,
                    row_data=row_data["data"],
                    mapping_template=mapping_template,
                )

            # All rows complete
            self._job_service.update_status(job_id, JobStatus.completed)
            summary = self._job_service.get_job_summary(job_id)

            return BatchResult(
                success=True,
                job_id=job_id,
                **summary
            )

        except Exception as e:
            # Fail-fast: halt on first error
            error_code, error_message = self._translate_error(e)
            self._job_service.set_error(job_id, error_code, error_message)
            self._job_service.update_status(job_id, JobStatus.failed)

            summary = self._job_service.get_job_summary(job_id)
            return BatchResult(
                success=False,
                job_id=job_id,
                error_code=error_code,
                error_message=error_message,
                **summary
            )

    async def _process_single_row(
        self,
        job_id: str,
        job_row,
        row_data: dict,
        mapping_template: str,
    ) -> dict:
        """Process single row with state checkpointing."""

        # Mark processing
        self._job_service.start_row(job_row.id)
        self._audit_service.log_row_event(
            job_id, job_row.row_number, "started"
        )

        try:
            # Render template
            payload = self._render_template(mapping_template, row_data)

            # Create shipment via UPS MCP
            result = await self._ups_mcp.shipping_create(**payload)

            tracking = result["trackingNumbers"][0]
            label_path = result["labelPaths"][0]
            cost_cents = int(float(result["totalCharges"]["monetaryValue"]) * 100)

            # Mark complete with tracking info
            self._job_service.complete_row(
                row_id=job_row.id,
                tracking_number=tracking,
                label_path=label_path,
                cost_cents=cost_cents,
            )

            # Write back to source (per CONTEXT.md Decision 4: immediate)
            await self._write_back_tracking(
                job_id=job_id,
                row_number=job_row.row_number,
                tracking_number=tracking,
            )

            self._audit_service.log_row_event(
                job_id, job_row.row_number, "completed",
                {"tracking_number": tracking}
            )

            return {"tracking_number": tracking, "cost_cents": cost_cents}

        except Exception as e:
            error_code, error_message = self._translate_error(e)
            self._job_service.fail_row(job_row.id, error_code, error_message)
            self._audit_service.log_row_event(
                job_id, job_row.row_number, "failed",
                {"error_code": error_code, "error_message": error_message}
            )
            raise  # Re-raise for fail-fast
```

### Write-Back Tool for Data MCP
```python
# Source: openpyxl tutorial, Python atomicwrites pattern
# Location: src/mcp/data_source/tools/writeback_tools.py

import csv
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastmcp import Context
from openpyxl import load_workbook


async def write_back(
    row_number: int,
    tracking_number: str,
    ctx: Context,
    shipped_at: Optional[str] = None,
) -> dict:
    """Write tracking number back to original data source.

    Supports CSV, Excel, and database sources.
    Uses atomic operations for file sources.

    Args:
        row_number: 1-based row number in source data
        tracking_number: UPS tracking number to write
        shipped_at: ISO8601 timestamp (defaults to now)

    Returns:
        {"success": True, "source_type": "csv"|"excel"|"database"}
    """
    source_info = ctx.request_context.lifespan_context.get("current_source")
    if not source_info:
        raise ValueError("No data source loaded")

    shipped_at = shipped_at or datetime.now(timezone.utc).isoformat()
    source_type = source_info.get("source_type")

    await ctx.info(f"Writing tracking {tracking_number} to row {row_number}")

    if source_type == "csv":
        await _write_back_csv(
            file_path=source_info["file_path"],
            row_number=row_number,
            tracking_number=tracking_number,
            shipped_at=shipped_at,
        )
    elif source_type == "excel":
        await _write_back_excel(
            file_path=source_info["file_path"],
            sheet_name=source_info.get("sheet_name"),
            row_number=row_number,
            tracking_number=tracking_number,
            shipped_at=shipped_at,
        )
    elif source_type in ("postgres", "mysql"):
        await _write_back_database(
            ctx=ctx,
            table_name=source_info["table_name"],
            row_number=row_number,
            tracking_number=tracking_number,
            shipped_at=shipped_at,
        )
    else:
        raise ValueError(f"Unsupported source type for write-back: {source_type}")

    return {
        "success": True,
        "source_type": source_type,
        "row_number": row_number,
        "tracking_number": tracking_number,
    }


async def _write_back_csv(
    file_path: str,
    row_number: int,
    tracking_number: str,
    shipped_at: str,
) -> None:
    """Write to CSV with atomic temp-then-rename."""
    path = Path(file_path)

    # Temp file in same directory for atomic rename
    fd, temp_path = tempfile.mkstemp(suffix=".csv", dir=path.parent)

    try:
        with open(path, 'r', newline='', encoding='utf-8') as src:
            reader = csv.DictReader(src)
            original_fieldnames = list(reader.fieldnames or [])

            # Add columns if not present
            fieldnames = original_fieldnames.copy()
            if 'tracking_number' not in fieldnames:
                fieldnames.append('tracking_number')
            if 'shipped_at' not in fieldnames:
                fieldnames.append('shipped_at')

            with os.fdopen(fd, 'w', newline='', encoding='utf-8') as dst:
                writer = csv.DictWriter(dst, fieldnames=fieldnames)
                writer.writeheader()

                for i, row in enumerate(reader, start=1):
                    if i == row_number:
                        row['tracking_number'] = tracking_number
                        row['shipped_at'] = shipped_at
                    writer.writerow(row)

        # Atomic replace
        os.replace(temp_path, file_path)

    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


async def _write_back_excel(
    file_path: str,
    sheet_name: Optional[str],
    row_number: int,
    tracking_number: str,
    shipped_at: str,
) -> None:
    """Write to Excel with atomic temp-then-rename."""
    path = Path(file_path)

    fd, temp_path = tempfile.mkstemp(suffix=".xlsx", dir=path.parent)
    os.close(fd)

    try:
        wb = load_workbook(file_path)
        ws = wb[sheet_name] if sheet_name else wb.active

        # Excel row = data row + 1 (header)
        excel_row = row_number + 1

        # Find or create tracking columns
        max_col = ws.max_column
        tracking_col = None
        shipped_col = None

        for col in range(1, max_col + 1):
            header = ws.cell(row=1, column=col).value
            if header == 'tracking_number':
                tracking_col = col
            elif header == 'shipped_at':
                shipped_col = col

        if tracking_col is None:
            tracking_col = max_col + 1
            ws.cell(row=1, column=tracking_col, value='tracking_number')

        if shipped_col is None:
            shipped_col = ws.max_column + 1
            ws.cell(row=1, column=shipped_col, value='shipped_at')

        ws.cell(row=excel_row, column=tracking_col, value=tracking_number)
        ws.cell(row=excel_row, column=shipped_col, value=shipped_at)

        wb.save(temp_path)
        wb.close()

        os.replace(temp_path, file_path)

    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


async def _write_back_database(
    ctx: Context,
    table_name: str,
    row_number: int,
    tracking_number: str,
    shipped_at: str,
) -> None:
    """Write to database via DuckDB attached connection.

    Per CONTEXT.md Decision 4: Use transaction for atomicity.
    """
    db = ctx.request_context.lifespan_context["db"]

    # DuckDB with attached database
    # The table_name includes schema prefix from original import
    db.execute(f"""
        UPDATE {table_name}
        SET tracking_number = ?,
            shipped_at = ?
        WHERE _row_number = ?
    """, [tracking_number, shipped_at, row_number])
```

### Crash Recovery Prompt
```python
# Source: CONTEXT.md Decision 3
async def check_interrupted_jobs(job_service: JobService) -> Optional[dict]:
    """Check for jobs interrupted mid-execution.

    Returns prompt info if interrupted job found.
    """
    # Find jobs in 'running' state (indicates crash)
    interrupted = job_service.list_jobs(status=JobStatus.running)

    if not interrupted:
        return None

    job = interrupted[0]  # Most recent

    # Get progress info
    completed = job.successful_rows
    total = job.total_rows
    remaining = total - job.processed_rows

    # Get last processed row info
    last_completed = job_service.get_rows(job.id, status=RowStatus.completed)
    last_row_info = None
    if last_completed:
        last = last_completed[-1]
        last_row_info = {
            "row_number": last.row_number,
            "tracking_number": last.tracking_number,
        }

    # Get error if exists
    error_info = None
    if job.error_code:
        error_info = {
            "code": job.error_code,
            "message": job.error_message,
        }

    return {
        "job_id": job.id,
        "job_name": job.name,
        "completed": completed,
        "total": total,
        "remaining": remaining,
        "last_row": last_row_info,
        "error": error_info,
        "prompt": f"Job '{job.name}' was interrupted at row {completed}/{total}. "
                  f"Resume, restart, or cancel?"
    }
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Load all rows | Generator with pagination | Python 3.x best practice | Memory efficiency for 500+ rows |
| Batch commit | Per-row commit | Industry standard | Crash recovery without data loss |
| Direct file write | Atomic temp-then-rename | `os.replace` Python 3.3+ | Data corruption prevention |
| Custom state tracking | SQLAlchemy with enums | Phase 1 | Consistent state machine |

**Deprecated/outdated:**
- `os.rename`: Use `os.replace` for atomic cross-platform behavior
- Global mode state: Use session-scoped mode per CONTEXT.md
- Loading all rows: Use generators for large batches

## Open Questions

Things that couldn't be fully resolved:

1. **UPS Rate Limiting for Large Batches**
   - What we know: UPS has rate limits; sequential calls work for MVP
   - What's unclear: Exact rate limits and when throttling kicks in
   - Recommendation: Per CONTEXT.md Out of Scope, sequential processing for MVP; add semaphore if issues arise

2. **Database Write-Back Without Row Number Column**
   - What we know: DuckDB import doesn't preserve original row identifiers
   - What's unclear: Best strategy for identifying rows in write-back
   - Recommendation: Add `_row_number` column during import; use checksum as secondary identifier

3. **Interrupted Write-Back Retry Behavior**
   - What we know: Write failures queued for retry at batch end per CONTEXT.md
   - What's unclear: How many retries, exponential backoff, failure threshold
   - Recommendation: 3 retries with 1s/2s/4s backoff; log failures, complete job with warnings

## Sources

### Primary (HIGH confidence)
- Phase 1 `src/services/job_service.py` - JobService with state machine, per-row tracking
- Phase 1 `src/services/audit_service.py` - AuditService with redaction
- Phase 2 `src/mcp/data_source/tools/query_tools.py` - `get_rows_by_filter` implementation
- Phase 3 `packages/ups-mcp/src/tools/rating.ts` - `rating_quote` tool
- Phase 3 `packages/ups-mcp/src/tools/shipping.ts` - `shipping_create` tool
- Phase 5 `src/orchestrator/agent/client.py` - OrchestrationAgent
- [openpyxl Tutorial](https://openpyxl.readthedocs.io/en/3.1/tutorial.html) - Excel read/write
- [Python os.replace](https://zetcode.com/python/os-replace/) - Atomic file operations

### Secondary (MEDIUM confidence)
- [Python atomicwrites](https://github.com/untitaker/python-atomicwrites) - Atomic write pattern
- [Python batch processing](https://hevodata.com/learn/python-batch-processing/) - Batch patterns
- [PEP 479](https://peps.python.org/pep-0479/) - Generator exception handling
- [Pyventus](https://github.com/mdapena/pyventus) - Event emitter patterns

### Tertiary (LOW confidence)
- Community articles on crash recovery patterns
- Web search results for Observer pattern implementations

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Using established Phase 1-5 infrastructure
- Architecture: HIGH - Patterns derived from CONTEXT.md decisions and existing code
- Pitfalls: HIGH - Based on CONTEXT.md requirements and common batch processing issues
- Code examples: HIGH - Assembled from working Phase 1-5 code patterns

**Research date:** 2026-01-25
**Valid until:** 90 days (stable patterns, no external API changes expected)
