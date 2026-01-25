---
phase: 06-batch-execution
plan: 02
subsystem: batch-core-models
tags: [batch-execution, execution-modes, observer-pattern, lifecycle-events, dataclasses]

dependency-graph:
  requires:
    - 01-01 (Database Models) for ISO8601 timestamp conventions
    - 06-CONTEXT for Decision 1 (preview) and Decision 2 (mode switching)
  provides:
    - ExecutionMode enum (CONFIRM/AUTO)
    - SessionModeManager with locking
    - BatchEventObserver Protocol for lifecycle events
    - BatchEventEmitter for publishing events
    - PreviewRow, BatchPreview, BatchResult, InterruptedJobInfo dataclasses
  affects:
    - 06-03 (BatchExecutor) uses all models and events
    - 06-04 (Preview Mode) uses PreviewRow and BatchPreview
    - 06-06 (Per-Row Commit) uses BatchResult
    - 06-07 (Crash Recovery) uses InterruptedJobInfo

tech-stack:
  added: []
  patterns:
    - Observer pattern with Protocol for type safety
    - str+Enum for JSON-serializable enums
    - Dataclasses with field defaults for optional attributes
    - Exception isolation in event emission

key-files:
  created:
    - src/orchestrator/batch/__init__.py
    - src/orchestrator/batch/modes.py
    - src/orchestrator/batch/events.py
    - src/orchestrator/batch/models.py
    - tests/orchestrator/batch/__init__.py
    - tests/orchestrator/batch/test_modes.py
    - tests/orchestrator/batch/test_events.py
  modified: []

decisions:
  - name: "str+Enum inheritance for ExecutionMode"
    rationale: "JSON serialization friendly, consistent with Phase 1 enums"
    alternatives: ["Plain Enum", "IntEnum"]
  - name: "Protocol for BatchEventObserver"
    rationale: "Structural subtyping allows any conforming class without inheritance"
    alternatives: ["ABC", "Callable type"]
  - name: "Exception isolation in event emission"
    rationale: "One broken observer should not stop event delivery to others"
    alternatives: ["Fail-fast on observer error", "Retry on error"]

metrics:
  duration: "Continuation of prior session"
  completed: "2026-01-25"
  tests:
    unit: 28
    integration: 0
    total: 28
---

# Phase 6 Plan 02: Batch Core Models Summary

**One-liner:** Observer pattern for batch lifecycle events plus execution mode management with locking to prevent mid-execution mode changes, enabling the BatchExecutor to emit progress updates and respect confirm/auto mode.

## What Was Built

### 1. ExecutionMode Enum

```python
class ExecutionMode(str, Enum):
    CONFIRM = "confirm"  # Preview before execute (default)
    AUTO = "auto"        # Execute immediately
```

Per CONTEXT.md Decision 2:
- Default mode is CONFIRM (preview before execute)
- Mode applies session-wide
- Mid-preview switch allowed
- Mid-execution switch blocked

### 2. SessionModeManager Class

```python
class SessionModeManager:
    def __init__(self) -> None           # Default CONFIRM, unlocked
    def mode(self) -> ExecutionMode      # Property: current mode
    def set_mode(self, mode) -> None     # Set mode (raises if locked)
    def lock(self) -> None               # Lock during execution
    def unlock(self) -> None             # Unlock after execution
    def is_locked(self) -> bool          # Check lock state
    def reset(self) -> None              # Reset to CONFIRM, unlocked
```

Features:
- Thread-safe mode tracking
- Locking prevents mode changes during batch execution
- Clear error message when locked: "Cannot change execution mode while batch is executing"
- `reset()` for new session initialization

### 3. BatchEventObserver Protocol

```python
class BatchEventObserver(Protocol):
    async def on_batch_started(self, job_id: str, total_rows: int) -> None
    async def on_row_started(self, job_id: str, row_number: int) -> None
    async def on_row_completed(self, job_id: str, row_number: int, tracking_number: str, cost_cents: int) -> None
    async def on_row_failed(self, job_id: str, row_number: int, error_code: str, error_message: str) -> None
    async def on_batch_completed(self, job_id: str, total_rows: int, successful: int, total_cost_cents: int) -> None
    async def on_batch_failed(self, job_id: str, error_code: str, error_message: str, processed: int) -> None
```

6 lifecycle events covering the full batch execution workflow:
- Batch started/completed/failed at job level
- Row started/completed/failed at row level

### 4. BatchEventEmitter Class

```python
class BatchEventEmitter:
    def add_observer(self, observer: BatchEventObserver) -> None
    def remove_observer(self, observer: BatchEventObserver) -> None
    async def emit_batch_started(...) -> None
    async def emit_row_started(...) -> None
    async def emit_row_completed(...) -> None
    async def emit_row_failed(...) -> None
    async def emit_batch_completed(...) -> None
    async def emit_batch_failed(...) -> None
```

Key behavior:
- Exceptions from individual observers are caught and logged
- Other observers still receive events even if one fails
- No observers doesn't raise (graceful degradation)

### 5. Result Dataclasses

**PreviewRow** - Single row in preview display:
```python
@dataclass
class PreviewRow:
    row_number: int           # 1-based from source
    recipient_name: str       # Shipment recipient
    city_state: str          # "City, ST" format
    service: str             # UPS service name
    estimated_cost_cents: int
    warnings: list[str]      # Warning messages
```

**BatchPreview** - Preview before execution (CONFIRM mode):
```python
@dataclass
class BatchPreview:
    job_id: str
    total_rows: int
    preview_rows: list[PreviewRow]  # First 20 per CONTEXT.md
    additional_rows: int             # Beyond preview
    total_estimated_cost_cents: int
    rows_with_warnings: int
```

**BatchResult** - Execution outcome:
```python
@dataclass
class BatchResult:
    success: bool
    job_id: str
    total_rows: int
    processed_rows: int
    successful_rows: int
    failed_rows: int
    total_cost_cents: int
    error_code: Optional[str] = None
    error_message: Optional[str] = None
```

**InterruptedJobInfo** - Crash recovery prompt:
```python
@dataclass
class InterruptedJobInfo:
    job_id: str
    job_name: str
    completed_rows: int
    total_rows: int
    remaining_rows: int
    last_row_number: Optional[int] = None
    last_tracking_number: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
```

### 6. Package Exports

```python
from src.orchestrator.batch import (
    ExecutionMode,
    SessionModeManager,
    BatchEventObserver,
    BatchEventEmitter,
    BatchResult,
    PreviewRow,
    BatchPreview,
    InterruptedJobInfo,
)
```

## Test Coverage

### Mode Tests (15)

| Test | Purpose |
|------|---------|
| `test_confirm_value` | CONFIRM = "confirm" |
| `test_auto_value` | AUTO = "auto" |
| `test_enum_is_str` | ExecutionMode inherits str |
| `test_default_mode_is_confirm` | Manager defaults to CONFIRM |
| `test_default_not_locked` | Manager starts unlocked |
| `test_set_mode_to_auto` | Mode can be changed to AUTO |
| `test_set_mode_to_confirm` | Mode can be changed back |
| `test_locked_mode_raises_error` | ValueError when locked |
| `test_lock_sets_locked` | lock() sets locked state |
| `test_unlock_allows_change` | unlock() permits changes |
| `test_unlock_clears_locked` | unlock() clears state |
| `test_reset_returns_to_confirm` | reset() restores CONFIRM |
| `test_reset_unlocks` | reset() clears lock |
| `test_reset_full_state` | reset() restores both |
| `test_multiple_mode_changes` | Sequential changes work |
| `test_locked_preserves_mode` | Lock doesn't change mode |

### Event Tests (12)

| Test | Purpose |
|------|---------|
| `test_add_observer` | Observer added to list |
| `test_remove_observer` | Observer removed from list |
| `test_remove_observer_not_present_raises` | ValueError if not present |
| `test_emit_batch_started_calls_observers` | All observers notified |
| `test_emit_row_started_calls_observers` | Row start event works |
| `test_emit_row_completed_calls_observers` | Row complete event works |
| `test_emit_row_failed_calls_observers` | Row failed event works |
| `test_emit_batch_completed_calls_observers` | Batch complete event works |
| `test_emit_batch_failed_calls_observers` | Batch failed event works |
| `test_observer_exception_doesnt_stop_others` | Exception isolation |
| `test_multiple_events_in_sequence` | Full workflow sequence |
| `test_no_observers_doesnt_raise` | Empty observer list OK |

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `24938de` | feat | create batch package with modes module |
| `40af20e` | feat | add Observer pattern for batch lifecycle events |
| `2707f90` | feat | add batch result models and unit tests |

## Files Created

| File | Lines | Description |
|------|-------|-------------|
| `src/orchestrator/batch/__init__.py` | 26 | Package exports |
| `src/orchestrator/batch/modes.py` | 77 | ExecutionMode + SessionModeManager |
| `src/orchestrator/batch/events.py` | 278 | Observer protocol + emitter |
| `src/orchestrator/batch/models.py` | 137 | 4 dataclasses |
| `tests/orchestrator/batch/__init__.py` | 0 | Test package init |
| `tests/orchestrator/batch/test_modes.py` | 135 | 15 mode tests |
| `tests/orchestrator/batch/test_events.py` | 240 | 12 event tests |

## Deviations from Plan

### Test Directory Location

The plan specified `tests/unit/orchestrator/batch/` but the project uses `tests/orchestrator/batch/` convention. Used actual project structure.

## Verification Results

| Criterion | Status |
|-----------|--------|
| `from src.orchestrator.batch import ExecutionMode, SessionModeManager` | PASS |
| `from src.orchestrator.batch import BatchEventObserver, BatchEventEmitter` | PASS |
| `from src.orchestrator.batch import BatchResult, PreviewRow, BatchPreview` | PASS |
| Mode manager defaults to CONFIRM | PASS |
| Mode manager supports locking | PASS |
| Event emitter calls all observers | PASS |
| Event emitter handles exceptions gracefully | PASS |
| All unit tests pass (28/28) | PASS |
| modes.py >= 40 lines | PASS (77) |
| events.py >= 60 lines | PASS (278) |
| models.py >= 80 lines | PASS (137) |
| Protocol pattern in events.py | PASS |

## Issues Encountered

None - implementation was already complete from a prior session. This execution verified and documented the work.

## Next Steps

Plan 06-03 (BatchExecutor Core) will:
- Implement the BatchExecutor class using these models
- Execute batches with mode-aware behavior
- Emit lifecycle events via BatchEventEmitter
- Return BatchResult on completion

---
*Phase: 06-batch-execution*
*Completed: 2026-01-25*
