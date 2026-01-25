---
phase: 06-batch-execution
plan: 04
subsystem: batch-execution
tags: [batch, executor, fail-fast, crash-recovery]

dependency-graph:
  requires: ["06-01", "06-02"]
  provides: ["BatchExecutor", "execution-loop", "fail-fast"]
  affects: ["06-05", "06-06", "06-07"]

tech-stack:
  added: []
  patterns: ["per-row-state-checkpoint", "fail-fast-execution"]

key-files:
  created:
    - src/orchestrator/batch/executor.py
    - tests/orchestrator/batch/test_executor.py
  modified:
    - src/orchestrator/batch/__init__.py

decisions:
  - id: "06-04-01"
    title: "Callable pattern for MCP calls"
    choice: "Async callable functions instead of direct client"
    rationale: "Decouples executor from MCP implementation, enables testing"
  - id: "06-04-02"
    title: "Event emission before re-raise"
    choice: "Emit row_failed event before re-raising exception"
    rationale: "Observers notified of failure even when fail-fast halts execution"

metrics:
  duration: "5 minutes"
  completed: "2026-01-25"
  tasks: 3
  tests-added: 19
  total-tests: 67
---

# Phase 6 Plan 4: BatchExecutor Core Summary

**One-liner:** BatchExecutor with fail-fast execution loop, per-row state checkpoints, and crash recovery via pending row iteration.

## What Was Built

### BatchExecutor Class (457 lines)

The core execution engine implementing requirements BATCH-01, BATCH-05, and BATCH-06:

```python
class BatchExecutor:
    """Executes batch shipments with fail-fast and crash recovery."""

    async def execute(
        self,
        job_id: str,
        mapping_template: str,
        shipper_info: dict[str, Any],
        source_name: str = "default",
    ) -> BatchResult:
        """Execute batch with fail-fast behavior."""
```

**Key Features:**
- **Fail-fast execution:** Halts entire batch on first error (BATCH-05)
- **Crash recovery:** Only processes pending rows, skips completed (BATCH-06)
- **Per-row state commits:** `start_row`, `complete_row`, `fail_row` called per row
- **Immediate write-back:** Tracking numbers written to source after each success
- **Event emission:** Full lifecycle events for UI integration

### Execution Flow

1. Validate job exists, transition to `running`
2. Log state change via AuditService
3. Emit `batch_started` event
4. For each pending row:
   - Emit `row_started`
   - Fetch row data from Data MCP
   - Process single row (render template, call UPS, write-back)
   - Emit `row_completed` or `row_failed`
   - On error: fail-fast, transition to `failed`
5. On success: transition to `completed`, emit `batch_completed`

### Error Translation

Maps exceptions to E-XXXX error codes:
- UPS auth errors -> E-5001
- UPS rate limits -> E-3002
- UPS address errors -> E-3003
- Template errors -> E-4003
- Generic errors -> E-4001

### Unit Tests (19 tests)

Comprehensive test coverage:
- `test_execute_success` - 3 rows all succeed
- `test_execute_fail_fast` - Second row fails, third never processed
- `test_execute_crash_recovery` - 2 completed, 3 pending, only pending processed
- `test_execute_state_commits` - `start_row` before `complete_row`
- `test_execute_write_back` - write_back called per row
- `test_execute_events_emitted` - All lifecycle events
- `test_execute_audit_logging` - State changes and row events logged
- `test_execute_empty_batch` - 0 rows completes successfully
- Error translation and result extraction tests

## Key Links

| From | To | Via | Pattern |
|------|-----|-----|---------|
| executor.py | JobService | State management | `job_service.start_row/complete_row/fail_row` |
| executor.py | AuditService | Audit logging | `audit_service.log_row_event` |
| executor.py | UPS MCP | Shipment creation | `ups_mcp("shipping_create", payload)` |
| executor.py | Data MCP | Write-back | `data_mcp("write_back", {row_number, tracking_number})` |

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

| Check | Status |
|-------|--------|
| BatchExecutor imports successfully | PASSED |
| BatchExecutor exported from batch package | PASSED |
| execute method processes pending rows | PASSED |
| Fail-fast halts on first error | PASSED |
| Crash recovery skips completed rows | PASSED |
| State committed per-row | PASSED |
| Write-back called after each success | PASSED |
| Events emitted for lifecycle points | PASSED |
| Audit logging for operations | PASSED |
| All unit tests pass | PASSED (19/19) |

## Next Phase Readiness

**Blockers:** None

**Ready for:**
- 06-05: Batch Orchestration Tools (integrates BatchExecutor)
- 06-06: Crash Recovery UX (uses InterruptedJobInfo)
- 06-07: Integration Tests (end-to-end batch flow)

## Commits

| Hash | Type | Description |
|------|------|-------------|
| af3d3ef | feat | Add BatchExecutor class with fail-fast and crash recovery |
| d78f558 | chore | Export BatchExecutor from batch package |
| fc208e4 | test | Add unit tests for BatchExecutor |
