---
phase: 06-batch-execution
plan: 01
subsystem: data-writeback
tags: [data-mcp, write-back, tracking-numbers, atomic-operations, csv, excel, database]

dependency-graph:
  requires:
    - 02-02 (CSV Import) for CSV file structure understanding
    - 02-03 (Excel Import) for Excel workbook handling
    - 02-04 (Database Import) for DuckDB query patterns
  provides:
    - write_back MCP tool for persisting tracking numbers
    - Atomic file operations for crash safety
    - Support for CSV, Excel, and database sources
  affects:
    - 06-02 (BatchExecutor) can persist tracking numbers after shipment
    - 06-06 (Per-Row Commit) relies on write_back for state persistence

tech-stack:
  added: []
  patterns:
    - Atomic temp+rename for file operations
    - DuckDB parameterized queries for SQL injection prevention
    - Helper function for SQL table name extraction

key-files:
  created:
    - tests/mcp/test_writeback_tools.py
  modified:
    - src/mcp/data_source/tools/writeback_tools.py (bug fixes)
    - src/mcp/data_source/server.py (already had registration)
    - tests/mcp/test_integration.py (updated tool count)

decisions:
  - name: "Keyword exact match instead of substring"
    rationale: "Substring check 'ORDER in table_ref' matches 'orders' incorrectly"
    alternatives: ["Regex word boundary", "Tokenize SQL"]
  - name: "Reject subqueries in table extraction"
    rationale: "Cannot UPDATE a subquery result set"
    alternatives: ["Parse full SQL AST", "Only support explicit table names"]
  - name: "mkstemp instead of NamedTemporaryFile for test fixtures"
    rationale: "NamedTemporaryFile with yield inside 'with' doesn't flush"
    alternatives: ["Explicit flush", "Close before yield"]

metrics:
  duration: "18 minutes"
  completed: "2026-01-25"
  tests:
    unit: 25
    integration: 0
    total: 25
---

# Phase 6 Plan 01: Write-Back Tool Summary

**One-liner:** MCP tool for atomic write-back of tracking numbers to CSV, Excel, and database sources with 25 unit tests covering all source types and error cases.

## What Was Built

### 1. write_back MCP Tool (Already Existed)

The implementation was already committed in previous work. This plan fixed bugs and added comprehensive tests.

**Tool signature:**
```python
async def write_back(
    row_number: int,
    tracking_number: str,
    ctx: Context,
    shipped_at: Optional[str] = None,
) -> dict
```

**Returns:**
```python
{
    "success": True,
    "source_type": "csv",  # or "excel", "database"
    "row_number": 1,
    "tracking_number": "1Z999AA10123456784"
}
```

### 2. Source-Specific Implementations

**CSV Write-Back (`_write_back_csv`):**
- Read original CSV with `csv.DictReader`
- Add `tracking_number` and `shipped_at` columns if missing
- Update target row (1-based indexing)
- Write to temp file via `tempfile.mkstemp` in same directory
- Atomic rename via `os.replace`
- Clean up temp file on error

**Excel Write-Back (`_write_back_excel`):**
- Load workbook via `openpyxl.load_workbook`
- Support named sheets (from `current_source["sheet"]`)
- Find or create tracking columns in header row
- Map row_number to Excel row (data row + 1 for header)
- Write to temp file, atomic rename
- Clean up on error

**Database Write-Back (`_write_back_database`):**
- Extract table name from stored query
- Use parameterized UPDATE query (`$1, $2, $3` syntax)
- Requires `_row_number` column (added during import)
- Fail safely for complex queries (JOINs, subqueries)

### 3. Table Name Extraction Helper

```python
def _extract_table_name(query: str) -> Optional[str]
```

Handles:
- Simple SELECT: `SELECT * FROM orders` -> `"orders"`
- With WHERE: `SELECT * FROM orders WHERE id=1` -> `"orders"`
- Schema prefix: `SELECT * FROM public.orders` -> `"public.orders"`
- JOINs: Extracts first table (limitation documented)
- Subqueries: Returns `None` (not supported)

### 4. Bug Fixes Applied

**Bug 1: Substring keyword match**
```python
# BEFORE (bug): "orders" contains "ORDER" substring
for keyword in ["WHERE", "ORDER", ...]:
    if keyword in table_ref.upper():  # True for "orders"!
        return None

# AFTER (fixed): Exact match only
keywords = {"WHERE", "ORDER", "GROUP", ...}
if table_ref.upper() in keywords:
    return None
```

**Bug 2: Missing subquery detection**
```python
# ADDED: Reject subqueries
if table_ref.startswith("("):
    return None
```

### 5. Test Fixes Applied

**Test fixture flush issue:**
```python
# BEFORE (bug): File not flushed when yield inside 'with'
with tempfile.NamedTemporaryFile(...) as f:
    f.write(content)
    yield f.name  # File still open in write mode!

# AFTER (fixed): Close before yield
fd, path = tempfile.mkstemp(suffix=".csv")
with os.fdopen(fd, "w", ...) as f:
    f.write(content)
yield path  # File fully flushed and closed
```

**Timing test precision:**
```python
# BEFORE: Microseconds not in ISO format
before = datetime.now(timezone.utc)  # 2026-01-25T12:00:00.123456Z
# shipped_at format: 2026-01-25T12:00:00Z (no microseconds)
# Comparison fails: before > shipped_at

# AFTER: Truncate to seconds
before = datetime.now(timezone.utc).replace(microsecond=0)
after = datetime.now(...) + timedelta(seconds=1)  # Buffer
```

## Test Coverage

### CSV Tests (5)
- `test_write_back_csv_adds_columns`: New columns created when missing
- `test_write_back_csv_updates_existing`: Updates existing tracking column
- `test_write_back_csv_preserves_data`: Other columns unchanged
- `test_write_back_csv_default_shipped_at`: Defaults to current UTC time
- `test_write_back_csv_atomic_on_error`: Temp file cleaned up on error

### Excel Tests (4)
- `test_write_back_excel_adds_columns`: New columns added to header
- `test_write_back_excel_updates_existing`: Updates existing values
- `test_write_back_excel_correct_row`: Row number maps correctly
- `test_write_back_excel_sheet_selection`: Named sheets work

### Database Tests (2)
- `test_write_back_database_updates_row`: UPDATE executes correctly
- `test_write_back_database_parameterized`: SQL injection prevented

### Error Handling Tests (6)
- `test_write_back_no_source_loaded`: Error when no source
- `test_write_back_unsupported_type`: Error for unknown types
- `test_write_back_csv_row_not_found`: CSV row bounds check
- `test_write_back_excel_row_not_found`: Excel row bounds check
- `test_write_back_excel_sheet_not_found`: Missing sheet error
- `test_write_back_database_complex_query`: Subquery rejection

### Table Name Extraction Tests (8)
- `test_simple_select`: Basic extraction
- `test_select_with_where`: WHERE clause handling
- `test_select_with_schema`: Schema prefix support
- `test_select_with_columns`: Named columns work
- `test_lowercase_from`: Case-insensitive FROM
- `test_no_from_clause`: Returns None for invalid SQL
- `test_empty_query`: Empty string handling
- `test_join_query`: JOIN extracts first table

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `546f7db` | feat | create write_back tool implementation (prior) |
| `74b1827` | feat | register write_back tool in Data MCP server (prior) |
| `5bd3020` | fix | fix write_back bugs and add unit tests |

## Files Modified

| File | Lines | Description |
|------|-------|-------------|
| `src/mcp/data_source/tools/writeback_tools.py` | 393 | Bug fixes for keyword matching |
| `tests/mcp/test_writeback_tools.py` | 660 | 25 unit tests (new file) |
| `tests/mcp/test_integration.py` | +3 | Updated tool count to 13 |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed substring keyword match in _extract_table_name**
- **Found during:** Test execution
- **Issue:** "orders" table name returned None because "ORDER" is substring of "ORDERS"
- **Fix:** Changed from substring check to exact keyword match
- **Files modified:** `src/mcp/data_source/tools/writeback_tools.py`
- **Commit:** `5bd3020`

**2. [Rule 1 - Bug] Added subquery detection**
- **Found during:** Test execution
- **Issue:** Subqueries like `SELECT * FROM (SELECT...)` extracted "(SELECT" as table
- **Fix:** Reject table references starting with "("
- **Files modified:** `src/mcp/data_source/tools/writeback_tools.py`
- **Commit:** `5bd3020`

**3. [Rule 1 - Bug] Fixed test fixture file flush**
- **Found during:** Test execution
- **Issue:** CSV tests reading 0 rows because file not flushed
- **Fix:** Use `mkstemp` + `os.fdopen` pattern instead of `NamedTemporaryFile`
- **Files modified:** `tests/mcp/test_writeback_tools.py`
- **Commit:** `5bd3020`

**4. [Rule 1 - Bug] Fixed timing test precision**
- **Found during:** Test execution
- **Issue:** `shipped_at` loses microseconds, comparison fails
- **Fix:** Truncate `before` to seconds, add 1s buffer to `after`
- **Files modified:** `tests/mcp/test_writeback_tools.py`
- **Commit:** `5bd3020`

### Test File Location

The plan specified `tests/unit/mcp/data_source/test_writeback_tools.py` but the project uses `tests/mcp/test_writeback_tools.py` convention. Used actual project structure.

## Verification Results

| Criterion | Status |
|-----------|--------|
| write_back imported from module | PASS |
| write_back registered in MCP server | PASS |
| All unit tests pass | PASS (25/25) |
| CSV atomic temp+rename | PASS |
| Excel atomic temp+rename | PASS |
| Database parameterized queries | PASS |

## Issues Encountered

None - implementation was complete, only needed bug fixes and tests.

## Next Steps

Plan 06-02 (Batch Core Models) will define:
- BatchMode enum (confirm/auto)
- BatchResult data class
- Observer pattern for lifecycle events

---
*Phase: 06-batch-execution*
*Completed: 2026-01-25*
