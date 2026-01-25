---
phase: 06-batch-execution
plan: 03
subsystem: batch-preview
tags: [batch-execution, preview-generation, cost-estimation, rate-quotes, jinja2]

dependency-graph:
  requires:
    - 06-01 (Write-back tools) for get_rows_by_filter pattern
    - 06-02 (Batch Core Models) for PreviewRow, BatchPreview dataclasses
    - 04-03 (Mapping Generator) for logistics filter environment
    - 03-03 (Rating Tools) for rating_quote pattern
  provides:
    - PreviewGenerator class for batch cost estimation
    - First 20 rows detailed preview with rate quotes
    - Aggregate estimation for remaining rows
    - Warning capture from quote responses
  affects:
    - 06-04 (Preview Mode) uses PreviewGenerator
    - 06-07 (Crash Recovery) may use preview for status display

tech-stack:
  added: []
  patterns:
    - Async callable injection for MCP tools
    - Jinja2 template rendering for payload transformation
    - Decimal for precise currency conversion
    - Word-boundary truncation for display

key-files:
  created:
    - src/orchestrator/batch/preview.py
    - tests/orchestrator/batch/test_preview.py
  modified:
    - src/orchestrator/batch/__init__.py

decisions:
  - name: "Callable injection for MCP tools"
    rationale: "Decouples PreviewGenerator from MCP transport, enables easy testing with mocks"
    alternatives: ["Direct MCP client", "Protocol for MCP interface"]
  - name: "Decimal for cost parsing"
    rationale: "Avoids floating point precision issues with currency amounts"
    alternatives: ["Float multiplication", "String parsing"]
  - name: "Fail-fast on preview error"
    rationale: "User needs to fix data issues before proceeding; partial preview misleading"
    alternatives: ["Skip failed rows", "Mark rows with errors"]

metrics:
  duration: "15 minutes"
  completed: "2026-01-25"
  tests:
    unit: 20
    integration: 0
    total: 20
---

# Phase 6 Plan 03: Batch Preview Generator Summary

**One-liner:** PreviewGenerator fetches first 20 rows via Data MCP, gets individual rate quotes from UPS MCP, estimates remaining rows from average cost, and produces BatchPreview objects for user confirmation.

## What Was Built

### 1. PreviewGenerator Class

```python
class PreviewGenerator:
    MAX_PREVIEW_ROWS = 20  # Per CONTEXT.md Decision 1

    def __init__(
        self,
        data_mcp_call: Callable[[str, dict], Awaitable[dict]],
        ups_mcp_call: Callable[[str, dict], Awaitable[dict]],
        jinja_env: Environment | None = None,
    ) -> None

    async def generate_preview(
        self,
        job_id: str,
        filter_clause: str,
        mapping_template: str,
        shipper_info: dict[str, Any],
    ) -> BatchPreview
```

Key features:
- Async MCP calls via injected callables (testable)
- Jinja2 logistics environment for template rendering
- First 20 rows get individual rate quotes
- Remaining rows estimated from average cost

### 2. Preview Generation Flow

```
1. Call Data MCP: get_rows_by_filter(where=filter_clause, limit=20, offset=0)
   -> Returns rows + total_count

2. For each row (up to 20):
   a. Render Jinja2 template with row data and shipper info
   b. Parse rendered JSON to UPS payload
   c. Call UPS MCP: rating_quote(payload)
   d. Extract cost, warnings, display fields
   e. Create PreviewRow

3. Calculate aggregates:
   - If additional_rows > 0: estimate = avg_cost * additional_rows
   - total_estimated = preview_cost + estimated_remaining

4. Return BatchPreview
```

### 3. Helper Methods

| Method | Purpose |
|--------|---------|
| `_truncate(text, max_len)` | Truncate at word boundary for display |
| `_check_warnings(row_data, quote_result)` | Extract warnings from quote |
| `_parse_cost_cents(amount)` | String to cents with Decimal precision |
| `_extract_recipient_name(payload)` | Get name from UPS payload structure |
| `_extract_city_state(payload)` | Format as "City, ST" |
| `_extract_service(payload)` | Map code to service name |

### 4. Warning Detection

Warnings captured from UPS quote responses:
- `addressCorrection: true` -> "Address correction suggested"
- `warnings` array -> Individual warning messages

### 5. Package Export

```python
from src.orchestrator.batch import PreviewGenerator
```

## Test Coverage

### Small Batch Tests (2)

| Test | Purpose |
|------|---------|
| `test_generate_preview_small_batch` | 5 rows all get quotes |
| `test_preview_row_contains_correct_data` | Verify extracted fields |

### Large Batch Tests (2)

| Test | Purpose |
|------|---------|
| `test_generate_preview_large_batch` | 50 rows, 20 detailed |
| `test_large_batch_average_estimation` | Variable costs averaged |

### Truncation Tests (3)

| Test | Purpose |
|------|---------|
| `test_preview_truncates_long_names` | Names > 20 chars truncated |
| `test_truncate_at_word_boundary` | No mid-word breaks |
| `test_short_names_not_truncated` | Short names unchanged |

### Warning Tests (3)

| Test | Purpose |
|------|---------|
| `test_preview_captures_address_correction_warning` | Address flag captured |
| `test_preview_captures_warnings_array` | Multiple warnings captured |
| `test_preview_counts_rows_with_warnings` | Count aggregation correct |

### Error Handling Tests (2)

| Test | Purpose |
|------|---------|
| `test_preview_handles_quote_error` | UPS error propagated |
| `test_preview_handles_data_mcp_error` | Data error propagated |

### Empty Batch Tests (1)

| Test | Purpose |
|------|---------|
| `test_preview_empty_batch` | 0 rows handled gracefully |

### Cost Calculation Tests (5)

| Test | Purpose |
|------|---------|
| `test_preview_cost_conversion_to_cents` | String to cents |
| `test_preview_cost_handles_whole_numbers` | $100.00 = 10000 cents |
| `test_preview_cost_handles_single_cent` | $0.01 = 1 cent |
| `test_preview_total_cost_aggregation` | Sum of row costs |
| `test_preview_handles_missing_cost` | Missing defaults to 0 |

### MCP Call Tests (2)

| Test | Purpose |
|------|---------|
| `test_data_mcp_called_with_correct_params` | Filter/limit/offset |
| `test_ups_mcp_called_for_each_row` | One call per row |

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `459f01d` | feat | create PreviewGenerator class |
| `5b33d21` | chore | export PreviewGenerator from batch package |
| `fe7dc5e` | test | add unit tests for PreviewGenerator |

## Files

| File | Lines | Description |
|------|-------|-------------|
| `src/orchestrator/batch/preview.py` | 320 | PreviewGenerator implementation |
| `tests/orchestrator/batch/test_preview.py` | 558 | 20 unit tests |
| `src/orchestrator/batch/__init__.py` | +2 | Updated exports |

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

| Criterion | Status |
|-----------|--------|
| PreviewGenerator imports successfully | PASS |
| PreviewGenerator exported from batch package | PASS |
| generate_preview returns BatchPreview with correct structure | PASS |
| First 20 rows get detailed quotes (MAX_PREVIEW_ROWS = 20) | PASS |
| Remaining rows estimated from average | PASS |
| Warnings captured from rate quote responses | PASS |
| All unit tests pass (20/20) | PASS |
| preview.py >= 120 lines | PASS (320) |
| test_preview.py >= 100 lines | PASS (558) |

## Issues Encountered

None.

## Next Steps

Plan 06-04 (BatchExecutor Core) will:
- Implement BatchExecutor using PreviewGenerator
- Execute batches row-by-row with state tracking
- Integrate with mode manager (CONFIRM vs AUTO)
- Emit lifecycle events via BatchEventEmitter

---
*Phase: 06-batch-execution*
*Completed: 2026-01-25*
