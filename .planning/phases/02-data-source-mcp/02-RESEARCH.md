# Phase 2: Data Source MCP - Research

**Researched:** 2026-01-24
**Domain:** MCP Server Development, Data Import/Processing, Schema Discovery
**Confidence:** HIGH

## Summary

This research covers the implementation of the Data Source MCP server using FastMCP (Python), with DuckDB as the analytics engine for CSV/Excel/Database imports. The architecture follows a clean separation: FastMCP handles the MCP protocol layer, DuckDB provides high-performance SQL analytics over data sources, and openpyxl enables Excel write-back for tracking numbers.

The standard approach is:
1. FastMCP server exposing tools for data import, schema discovery, and row access
2. DuckDB for unified SQL interface over CSV, Excel, and database sources
3. In-memory data storage (ephemeral session model per CONTEXT.md decisions)
4. SHA-256 row checksums computed at import time for data integrity

**Primary recommendation:** Use FastMCP v2 (stable) with DuckDB 1.3.x for data processing. Implement schema discovery using DuckDB's auto-detection with fallback to string type for mixed columns. Store imported data in DuckDB in-memory tables for query performance.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastmcp | 2.x (pin `<3`) | MCP server framework | Official recommended framework, handles protocol compliance |
| duckdb | 1.3.x | SQL analytics engine | 10-1000x faster than Pandas for analytics, native CSV/Excel/DB support |
| hashlib | stdlib | SHA-256 checksums | Built-in Python, no external dependencies |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| openpyxl | 3.1+ | Excel read/write | Required for write-back of tracking numbers to .xlsx files |
| pandas | 2.2+ | DataFrame bridge | For complex transforms; DuckDB can query pandas DataFrames directly |
| python-dateutil | 2.9+ | Date parsing | For ambiguous date format detection and parsing |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| DuckDB | Pure Pandas | DuckDB is 10-1000x faster for large datasets; Pandas alone struggles with memory |
| openpyxl | xlsxwriter | xlsxwriter can only write, not read; openpyxl does both |
| dateutil | dateparser | dateparser has more formats but heavier dependency; dateutil is sufficient |

**Installation:**
```bash
pip install 'fastmcp<3' duckdb openpyxl pandas python-dateutil
```

## Architecture Patterns

### Recommended Project Structure
```
src/
  mcp/
    data_source/
      __init__.py
      server.py           # FastMCP server definition
      tools/
        __init__.py
        import_tools.py   # import_csv, import_excel, import_database
        schema_tools.py   # get_schema, override_column_type
        query_tools.py    # query_data, get_row, get_rows_by_filter
        checksum_tools.py # compute_checksums, verify_checksum
      adapters/
        __init__.py
        base.py           # BaseSourceAdapter ABC
        csv_adapter.py    # CSV import logic
        excel_adapter.py  # Excel import with sheet selection
        db_adapter.py     # PostgreSQL/MySQL via DuckDB extensions
      models.py           # Pydantic models for tool inputs/outputs
      utils.py            # Checksum computation, date parsing helpers
```

### Pattern 1: FastMCP Tool Definition with Context
**What:** Use FastMCP decorators with Context parameter for accessing lifespan-managed resources.
**When to use:** All MCP tools that need database access or session state.
**Example:**
```python
# Source: https://gofastmcp.com/python-sdk/fastmcp-server-context
from fastmcp import FastMCP, Context

mcp = FastMCP("DataSource")

@mcp.tool
async def import_csv(file_path: str, ctx: Context) -> dict:
    """Import CSV file and discover schema.

    Args:
        file_path: Path to the CSV file to import

    Returns:
        Dictionary with schema, row_count, and any warnings
    """
    db = ctx.lifespan_context.get("db")
    await ctx.info(f"Importing CSV from {file_path}")

    # DuckDB auto-detects CSV format
    result = db.execute(f"""
        CREATE OR REPLACE TABLE imported_data AS
        SELECT * FROM read_csv('{file_path}', auto_detect=true)
    """)

    schema = db.execute("DESCRIBE imported_data").fetchall()
    row_count = db.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]

    return {
        "schema": [{"name": col[0], "type": col[1]} for col in schema],
        "row_count": row_count,
        "warnings": []
    }
```

### Pattern 2: DuckDB In-Memory with Lifespan
**What:** Create in-memory DuckDB connection in lifespan, share across tools.
**When to use:** For ephemeral session data storage (per CONTEXT.md decisions).
**Example:**
```python
# Source: https://duckdb.org/docs/stable/clients/python/overview
from contextlib import asynccontextmanager
import duckdb

@asynccontextmanager
async def lifespan(app):
    # Initialize in-memory DuckDB connection
    conn = duckdb.connect(":memory:")

    # Install extensions for database connectivity
    conn.execute("INSTALL postgres; INSTALL mysql;")
    conn.execute("LOAD postgres; LOAD mysql;")

    yield {"db": conn}

    # Cleanup on shutdown
    conn.close()

mcp = FastMCP("DataSource", lifespan=lifespan)
```

### Pattern 3: SHA-256 Row Checksum Computation
**What:** Compute deterministic checksums for each row for integrity verification.
**When to use:** At import time and before job creation (snapshot integrity).
**Example:**
```python
# Source: https://docs.python.org/3/library/hashlib.html
import hashlib
import json

def compute_row_checksum(row_data: dict) -> str:
    """Compute SHA-256 checksum for a row.

    Uses JSON serialization with sorted keys for deterministic output.
    """
    # Sort keys for consistent ordering
    canonical = json.dumps(row_data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

def compute_all_checksums(conn, table_name: str = "imported_data") -> list[dict]:
    """Compute checksums for all rows in imported data."""
    rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
    columns = [desc[0] for desc in conn.description]

    checksums = []
    for i, row in enumerate(rows, start=1):
        row_dict = dict(zip(columns, row))
        checksums.append({
            "row_number": i,
            "row_checksum": compute_row_checksum(row_dict)
        })
    return checksums
```

### Pattern 4: Database Snapshot Import
**What:** Use DuckDB ATTACH to snapshot external database tables.
**When to use:** PostgreSQL/MySQL imports (per CONTEXT.md: snapshot on import, not live).
**Example:**
```python
# Source: https://duckdb.org/docs/stable/core_extensions/postgres
def import_from_postgres(conn, connection_string: str, query: str) -> dict:
    """Import data from PostgreSQL as a snapshot.

    Args:
        conn: DuckDB connection
        connection_string: PostgreSQL connection string
        query: SQL query to execute (must include WHERE for large tables)
    """
    # Attach PostgreSQL database (read-only)
    conn.execute(f"ATTACH '{connection_string}' AS pg_source (TYPE postgres, READ_ONLY)")

    # Copy data into local DuckDB table (creates snapshot)
    conn.execute(f"""
        CREATE OR REPLACE TABLE imported_data AS
        {query.replace('FROM ', 'FROM pg_source.')}
    """)

    # Detach - connection string is not stored
    conn.execute("DETACH pg_source")

    row_count = conn.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]
    return {"row_count": row_count}
```

### Anti-Patterns to Avoid
- **Keeping database connections open:** Per CONTEXT.md, snapshot on import, then detach. Never maintain live connections.
- **Storing connection strings:** Never persist credentials. Use them only during import, then discard.
- **Using pandas for large datasets:** DuckDB handles large files natively; don't load into pandas first.
- **Hardcoding date formats:** Use auto-detection with ambiguity warnings per CONTEXT.md decisions.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CSV parsing | Custom parser | DuckDB `read_csv` | Handles encoding, delimiters, quoting, multi-line values automatically |
| Excel reading | cell-by-cell parsing | DuckDB `read_xlsx` + openpyxl | DuckDB reads efficiently; openpyxl handles formatting for write-back |
| Schema inference | Type guessing logic | DuckDB auto-detect | Built-in type detection with configurable fallbacks |
| Database connections | Raw psycopg2/mysql-connector | DuckDB postgres/mysql extensions | Unified SQL interface, snapshot semantics built-in |
| Date parsing | regex patterns | dateutil.parser | Handles ISO, US, EU formats with ambiguity detection |
| Row hashing | Custom serialization | hashlib + JSON | stdlib, deterministic with sorted keys |

**Key insight:** DuckDB provides a unified SQL interface over CSV, Excel, Parquet, PostgreSQL, and MySQL. Leverage this instead of writing separate adapters for each format. The adapters become thin wrappers around DuckDB operations.

## Common Pitfalls

### Pitfall 1: Mixed Type Columns
**What goes wrong:** Column contains both "123" and "ABC", DuckDB infers numeric, fails on text.
**Why it happens:** Auto-detection samples only first N rows.
**How to avoid:** Per CONTEXT.md decision, configure DuckDB to use VARCHAR fallback:
```python
# Force string type when detection fails
conn.execute("""
    CREATE TABLE imported_data AS
    SELECT * FROM read_csv('file.csv',
        sample_size=-1,  -- Scan entire file
        ignore_errors=true,  -- Don't fail on type mismatches
        all_varchar=false  -- Try detection first
    )
""")
```
**Warning signs:** Import succeeds but rows have NULL values unexpectedly.

### Pitfall 2: Ambiguous Date Formats
**What goes wrong:** "01/02/03" parsed as Jan 2, 2003 (US) instead of Feb 1, 2003 (EU).
**Why it happens:** No single format can be assumed.
**How to avoid:** Per CONTEXT.md, detect ambiguity and warn user:
```python
from dateutil.parser import parse, parserinfo

def detect_date_ambiguity(date_str: str) -> dict:
    """Check if date string is ambiguous between US/EU formats."""
    try:
        us_date = parse(date_str, dayfirst=False)
        eu_date = parse(date_str, dayfirst=True)

        if us_date != eu_date:
            return {
                "ambiguous": True,
                "us_interpretation": us_date.isoformat(),
                "eu_interpretation": eu_date.isoformat(),
                "default_used": "US (MM/DD/YYYY)"
            }
        return {"ambiguous": False, "parsed": us_date.isoformat()}
    except:
        return {"ambiguous": False, "parsed": None, "error": "Unparseable"}
```
**Warning signs:** Dates in output don't match expected values.

### Pitfall 3: Large Table Imports Without Filters
**What goes wrong:** User selects 10M row table, system runs out of memory.
**Why it happens:** No guardrails on import size.
**How to avoid:** Per CONTEXT.md, require WHERE clause for tables > 10k rows:
```python
def validate_database_import(conn, table_name: str, query: str) -> dict:
    """Validate database import doesn't pull excessive data."""
    # Check row count first
    count_result = conn.execute(f"""
        SELECT COUNT(*) FROM pg_source.{table_name}
    """).fetchone()[0]

    if count_result > 10000 and "WHERE" not in query.upper():
        return {
            "error": "LARGE_TABLE_NO_FILTER",
            "message": f"Table has {count_result:,} rows. Add a WHERE clause to filter.",
            "suggestion": f"Example: SELECT * FROM {table_name} WHERE created_at > '2026-01-01'"
        }
    return {"valid": True}
```
**Warning signs:** Import hangs or crashes on large tables.

### Pitfall 4: MCP stdout/stderr Mixing
**What goes wrong:** Debug prints go to stdout, corrupting JSON-RPC protocol.
**Why it happens:** Using print() instead of proper logging.
**How to avoid:** Use FastMCP Context logging:
```python
@mcp.tool
async def import_csv(file_path: str, ctx: Context) -> dict:
    # CORRECT: Use context logging (goes to stderr)
    await ctx.info(f"Starting import of {file_path}")

    # WRONG: print() goes to stdout, breaks protocol
    # print(f"Importing {file_path}")  # DON'T DO THIS
```
**Warning signs:** MCP client receives parse errors or garbled responses.

### Pitfall 5: Non-Atomic Write-Back
**What goes wrong:** Tracking numbers partially written when job fails mid-way.
**Why it happens:** Writing after each row instead of at job completion.
**How to avoid:** Per CONTEXT.md, write-back only on job completion (handled by orchestrator, not MCP):
```python
def write_back_tracking_numbers(file_path: str, tracking_data: list[dict]) -> dict:
    """Write tracking numbers back to Excel file atomically.

    Called ONLY after entire job completes successfully.
    """
    from openpyxl import load_workbook

    wb = load_workbook(file_path)
    ws = wb.active

    # Find or create tracking number column
    tracking_col = None
    for col in range(1, ws.max_column + 1):
        if ws.cell(row=1, column=col).value == "tracking_number":
            tracking_col = col
            break
    if tracking_col is None:
        tracking_col = ws.max_column + 1
        ws.cell(row=1, column=tracking_col, value="tracking_number")

    # Write all tracking numbers
    for item in tracking_data:
        row = item["row_number"] + 1  # Account for header
        ws.cell(row=row, column=tracking_col, value=item["tracking_number"])

    wb.save(file_path)
    return {"rows_updated": len(tracking_data)}
```
**Warning signs:** Source file has some tracking numbers but job shows as failed.

## Code Examples

Verified patterns from official sources:

### DuckDB CSV Import with Auto-Detection
```python
# Source: https://duckdb.org/docs/stable/data/csv/auto_detection
import duckdb

conn = duckdb.connect(":memory:")

# Import with full auto-detection
conn.execute("""
    CREATE TABLE imported_data AS
    SELECT * FROM read_csv('orders.csv',
        auto_detect = true,
        sample_size = -1,      -- Scan entire file for type detection
        ignore_errors = true,  -- Don't fail on malformed rows
        null_padding = true    -- Handle missing columns
    )
""")

# Get inferred schema
schema = conn.execute("DESCRIBE imported_data").fetchall()
for col_name, col_type, null, key, default, extra in schema:
    print(f"{col_name}: {col_type}")
```

### DuckDB Excel Import with Sheet Selection
```python
# Source: https://duckdb.org/docs/stable/guides/file_formats/excel_import
import duckdb

conn = duckdb.connect(":memory:")

# Import specific sheet
conn.execute("""
    CREATE TABLE imported_data AS
    SELECT * FROM read_xlsx('orders.xlsx',
        sheet = 'January Orders',
        header = true,
        all_varchar = false,     -- Try type detection
        empty_as_varchar = true  -- Handle empty cells gracefully
    )
""")

# List available sheets (requires loading file first)
# Note: DuckDB doesn't expose sheet list directly; use openpyxl for discovery
from openpyxl import load_workbook
wb = load_workbook('orders.xlsx', read_only=True)
sheet_names = wb.sheetnames
wb.close()
```

### FastMCP Server with Lifespan
```python
# Source: https://gofastmcp.com/deployment/running-server
from contextlib import asynccontextmanager
from fastmcp import FastMCP, Context
import duckdb

@asynccontextmanager
async def lifespan(app):
    """Initialize resources for MCP server lifetime."""
    conn = duckdb.connect(":memory:")
    conn.execute("INSTALL postgres; INSTALL mysql;")
    conn.execute("LOAD postgres; LOAD mysql;")

    yield {"db": conn, "current_source": None}

    conn.close()

mcp = FastMCP("DataSource", lifespan=lifespan)

@mcp.tool
async def get_schema(ctx: Context) -> dict:
    """Get schema of currently imported data."""
    db = ctx.lifespan_context.get("db")

    try:
        schema = db.execute("DESCRIBE imported_data").fetchall()
        return {
            "columns": [
                {"name": col[0], "type": col[1], "nullable": col[2] == "YES"}
                for col in schema
            ]
        }
    except duckdb.CatalogException:
        return {"error": "NO_DATA_IMPORTED", "message": "No data has been imported yet"}

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

### Date Parsing with Ambiguity Detection
```python
# Source: https://dateutil.readthedocs.io/en/stable/parser.html
from dateutil.parser import parse, ParserError
from typing import Optional
import re

# Excel serial date detection
EXCEL_SERIAL_PATTERN = re.compile(r'^\d{5}$')

def parse_date_with_warnings(value: str) -> dict:
    """Parse date string with ambiguity detection.

    Returns:
        dict with 'value', 'format_detected', 'warnings'
    """
    if not value or not isinstance(value, str):
        return {"value": None, "format_detected": None, "warnings": []}

    value = value.strip()
    warnings = []

    # Check for Excel serial date
    if EXCEL_SERIAL_PATTERN.match(value):
        from datetime import datetime, timedelta
        serial = int(value)
        # Excel epoch is Dec 30, 1899
        excel_epoch = datetime(1899, 12, 30)
        parsed = excel_epoch + timedelta(days=serial)
        return {
            "value": parsed.date().isoformat(),
            "format_detected": "excel_serial",
            "warnings": []
        }

    try:
        # Try US format (default)
        us_parsed = parse(value, dayfirst=False)

        # Check for ambiguity
        try:
            eu_parsed = parse(value, dayfirst=True)
            if us_parsed.date() != eu_parsed.date():
                warnings.append({
                    "type": "AMBIGUOUS_DATE",
                    "message": f"Date '{value}' could be {us_parsed.strftime('%b %d, %Y')} (US) or {eu_parsed.strftime('%b %d, %Y')} (EU). Using US format.",
                    "us_interpretation": us_parsed.date().isoformat(),
                    "eu_interpretation": eu_parsed.date().isoformat()
                })
        except ParserError:
            pass

        return {
            "value": us_parsed.date().isoformat(),
            "format_detected": "auto",
            "warnings": warnings
        }
    except ParserError:
        return {
            "value": value,  # Keep original as string
            "format_detected": None,
            "warnings": [{"type": "UNPARSEABLE_DATE", "message": f"Could not parse '{value}' as date"}]
        }
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| MCP v1 SDK | FastMCP 2.x/3.x | 2024-2025 | Simplified server development, decorator-based tools |
| Pandas for CSV | DuckDB read_csv | 2023-2024 | 10-1000x faster, lower memory |
| psycopg2/mysql-connector | DuckDB postgres/mysql extensions | 2024 | Unified SQL interface, snapshot semantics |
| MCP Python SDK v1.x | v2.x (alpha) | Q1 2026 | New features, use v1.x for production now |

**Deprecated/outdated:**
- **MCP Python SDK v2**: Currently in pre-alpha. Use v1.x or FastMCP 2.x for production until Q1 2026 stable release.
- **FastMCP 3.0**: Currently in beta. Pin to `fastmcp<3` for stability.
- **gspread for Google Sheets**: Per requirements, Google Sheets is deferred to v2.

## Open Questions

Things that couldn't be fully resolved:

1. **Excel Write-Back Column Discovery**
   - What we know: openpyxl can write to specific cells; need to find/create tracking_number column
   - What's unclear: Should tracking_number column be appended or should we use a user-specified column?
   - Recommendation: Append new column if not exists; user can override column name via tool parameter

2. **DuckDB Connection Lifecycle in Async Context**
   - What we know: DuckDB connection is not thread-safe; single connection per session works
   - What's unclear: Behavior when multiple concurrent tool calls occur
   - Recommendation: Use single connection; FastMCP handles request serialization via async

3. **Type Override Persistence**
   - What we know: CONTEXT.md allows per-column type override after import
   - What's unclear: How to persist overrides within ephemeral session
   - Recommendation: Store overrides in lifespan_context; apply via DuckDB CAST when querying

## Sources

### Primary (HIGH confidence)
- [DuckDB Python API](https://duckdb.org/docs/stable/clients/python/overview) - CSV/Excel import, type detection
- [DuckDB CSV Auto-Detection](https://duckdb.org/docs/stable/data/csv/auto_detection) - Schema inference
- [DuckDB PostgreSQL Extension](https://duckdb.org/docs/stable/core_extensions/postgres) - Database connectivity
- [DuckDB MySQL Extension](https://duckdb.org/docs/stable/core_extensions/mysql) - Database connectivity
- [FastMCP Documentation](https://gofastmcp.com) - Server framework, context, lifespan
- [FastMCP Context Object](https://gofastmcp.com/python-sdk/fastmcp-server-context) - Tool context, logging
- [Python hashlib](https://docs.python.org/3/library/hashlib.html) - SHA-256 checksums
- [dateutil parser](https://dateutil.readthedocs.io/en/stable/parser.html) - Date parsing

### Secondary (MEDIUM confidence)
- [MCPcat Error Handling Guide](https://mcpcat.io/guides/error-handling-custom-mcp-servers/) - Best practices
- [FastMCP GitHub](https://github.com/jlowin/fastmcp) - Community patterns
- [openpyxl Documentation](https://openpyxl.readthedocs.io/en/stable/) - Excel operations

### Tertiary (LOW confidence)
- WebSearch results on MCP pitfalls - Community-reported issues, may not be current

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official documentation and PyPI versions verified
- Architecture: HIGH - Based on FastMCP official docs and DuckDB guides
- Pitfalls: MEDIUM - Mix of official docs and community experience

**Research date:** 2026-01-24
**Valid until:** 2026-02-24 (30 days - stable technologies)
