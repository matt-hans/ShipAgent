# Design: Universal Data Ingestion Engine

**Date:** 2026-02-20
**Status:** Approved

## 1. Objective

Enhance the Data Source MCP to support every commonly used local file format in logistics shipping workflows. Target formats: `.csv`, `.tsv`, `.txt`, `.ssv`, `.dat`, `.xlsx`, `.xls`, `.json`, `.xml`, `.edi`, `.x12`, `.edifact`, `.fwf`. The system must flatten all formats into DuckDB's `imported_data` table, making them instantly compatible with the existing `column_mapping.py` auto-mapper and `BatchEngine` pipeline.

### Design Principles

- **DuckDB-only** — No pandas dependency. Use DuckDB native functions, `xmltodict` (12KB), and `python-calamine` (2MB) as the only new dependencies.
- **Agent-first** — Smart auto-detection handles 90% of imports. Agent reasoning (via `sniff_file`) handles the rest.
- **Companion file write-back** — Hierarchical/EDI formats get a `{filename}_results.csv` instead of in-place mutation, preserving upstream schema integrity.
- **Zero column mapping changes** — The existing 52-rule token-based auto-mapper already handles flattened column names (`shipTo_name`, `ShipTo_Address_Line1`).

## 2. Architecture: Adapter Pattern

### 2.1 Adapter Hierarchy

All adapters inherit from `BaseSourceAdapter` and produce a DuckDB `imported_data` table with `_source_row_num`.

```
BaseSourceAdapter (ABC)
├── DelimitedAdapter        # .csv, .tsv, .ssv, .txt, .dat  [refactored from CSVAdapter]
├── ExcelAdapter            # .xlsx, .xls                    [enhanced with calamine]
├── JSONAdapter             # .json                          [NEW]
├── XMLAdapter              # .xml                           [NEW]
├── FixedWidthAdapter       # .fwf, .dat, .txt               [NEW]
├── EDIAdapter              # .edi, .x12, .edifact           [ENHANCED - dual mode]
└── DatabaseAdapter         # Postgres, MySQL                [UNCHANGED]
```

| Adapter | Target Formats | Implementation Strategy |
|---------|---------------|------------------------|
| **DelimitedAdapter** | .csv, .tsv, .ssv, .txt, .dat | Refactored `CSVAdapter`. DuckDB `read_csv(auto_detect=true)`. Handles any delimiter automatically. |
| **ExcelAdapter** | .xlsx, .xls | Enhanced. `openpyxl` for .xlsx, `python-calamine` for legacy .xls. |
| **JSONAdapter** | .json | DuckDB `read_json_auto` for flat arrays. Python recursive flattening for nested structures. |
| **XMLAdapter** | .xml | `xmltodict` → Python dict → recursive flattening → DuckDB. Auto-detects repeating record nodes. |
| **FixedWidthAdapter** | .fwf, .dat, .txt | Pure Python string slicing at agent-specified byte positions. |
| **EDIAdapter** | .edi, .x12, .edifact | Dual-mode: normalized (current strict schema) or dynamic (preserves all segments as prefixed columns). |
| **DatabaseAdapter** | Postgres, MySQL | Unchanged. |

### 2.2 Format Router

The `import_file` tool routes files to adapters via extension mapping:

```python
EXTENSION_MAP = {
    # Delimited (DuckDB auto-detects delimiter)
    ".csv": "delimited",
    ".tsv": "delimited",
    ".ssv": "delimited",
    ".dat": "delimited",      # First try delimited; fallback to sniff_file
    ".txt": "delimited",      # First try delimited; fallback to sniff_file
    # Structured
    ".json": "json",
    ".xml": "xml",
    # Spreadsheets
    ".xlsx": "excel",
    ".xls": "excel",
    # EDI
    ".edi": "edi",
    ".x12": "edi",
    ".edifact": "edi",
    # Fixed-width (explicit only — no auto-detection)
    ".fwf": "fixed_width",
}
```

**Ambiguity resolution for `.txt` and `.dat`:**
1. Try `DelimitedAdapter` with DuckDB auto-detect.
2. If result has only 1 column and >0 rows → return warning: `{"status": "ambiguous", "suggestion": "use sniff_file to inspect"}`.
3. Agent calls `sniff_file`, reasons about the format, then retries with explicit parameters.

### 2.3 Shared Flattening Logic

JSON, XML, and EDI (dynamic mode) all use a shared utility for converting nested structures to flat DuckDB tables.

**Recursive flattener:**
```python
def flatten_record(record: dict, separator: str = "_", prefix: str = "") -> dict:
    """Recursively flatten nested dicts. Arrays become JSON strings."""
    flat = {}
    for key, value in record.items():
        full_key = f"{prefix}{separator}{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(flatten_record(value, separator, full_key))
        elif isinstance(value, list):
            flat[full_key] = json.dumps(value)  # Preserve arrays as JSON text
        else:
            flat[full_key] = value
    return flat
```

**Shared DuckDB loader:**
```python
def load_flat_records_to_duckdb(conn, records: list[dict]) -> ImportResult:
    """Load flat dicts into DuckDB imported_data table.

    Handles heterogeneous keys (not all records have all fields).
    Adds _source_row_num. Returns ImportResult with discovered schema.
    """
    # 1. Collect all unique keys across all records (union of all fields)
    # 2. CREATE TABLE imported_data (_source_row_num BIGINT, col1 VARCHAR, ...)
    # 3. INSERT each record with NULL for missing keys
    # 4. DESCRIBE imported_data → schema
    # 5. Return ImportResult
```

**Design rationale:**
- Underscore separator (`shipTo_name`) is compatible with `column_mapping.py`'s tokenizer which splits on underscores.
- Arrays preserved as JSON strings maintain "One Row = One Shipment" cardinality — prevents item-level explosion into multiple rows.
- Shared loader is reused by JSONAdapter, XMLAdapter, EDIAdapter (dynamic), and FixedWidthAdapter.

## 3. Tool Interface (Agent Surface)

### 3.1 `import_file` — Smart Router (Primary)

The default tool for ~90% of import tasks.

```python
async def import_file(
    file_path: str,
    ctx: Context,
    format_hint: str | None = None,  # 'delimited', 'excel', 'json', 'xml', 'edi'
    delimiter: str | None = None,     # Override for delimited files
    quotechar: str | None = None,     # Override for delimited files
    sheet: str | None = None,         # Excel sheet name
    record_path: str | None = None,   # XML/JSON path to repeating element
    header: bool = True,              # Whether first row/line is header
    dynamic: bool = False,            # EDI: use dynamic flattening
) -> dict:
    """Import any supported file format into DuckDB.

    Routes to the appropriate adapter based on file extension.
    Use format_hint to override auto-detection.
    """
```

**Router logic:**
1. Extract extension from `file_path`.
2. If `format_hint` provided, use it to override extension routing.
3. Instantiate appropriate adapter and call `import_data()`.
4. Check for ambiguity (1-column result on delimited → warning).
5. Update `current_source` in lifespan context.
6. Return `ImportResult.model_dump()`.

**Backward compatibility:**
- `import_csv` becomes a thin wrapper: `return await import_file(file_path, ctx, format_hint="delimited", delimiter=delimiter, header=header)`
- `import_excel` becomes a thin wrapper: `return await import_file(file_path, ctx, format_hint="excel", sheet=sheet, header=header)`
- Existing agent tools calling `import_csv`/`import_excel` continue to work.

### 3.2 `sniff_file` — Agent Eyes

Allows the agent to inspect raw file content when auto-detection fails.

```python
async def sniff_file(
    file_path: str,
    ctx: Context,
    num_lines: int = 10,
    offset: int = 0,
) -> str:
    """Read raw text lines from a file for agent inspection.

    Returns the first N lines as raw text, allowing the agent
    to reason about format (delimiters, fixed-width columns, etc.).
    """
```

**Agent reasoning examples:**
- "I see columns aligned at character positions 0, 20, 35. This is fixed-width."
- "I see pipe `|` characters separating values. I'll call `import_file` with `delimiter='|'`."
- "This appears to be binary/encoded. I'll report an unsupported format to the user."

### 3.3 `import_fixed_width` — Specialist

Called by the agent after analyzing `sniff_file` output.

```python
async def import_fixed_width(
    file_path: str,
    ctx: Context,
    col_specs: list[tuple[int, int]],  # [(start, end), (0, 10), (10, 25), ...]
    names: list[str] | None = None,     # ["OrderID", "Date", ...]
    header: bool = False,               # Fixed-width files rarely have headers
) -> dict:
    """Import a fixed-width format file using explicit column positions.

    The agent determines col_specs by inspecting the file via sniff_file.
    """
```

### 3.4 Agent Workflow (System Prompt Updates)

Add this decision tree to the agent's system prompt:

```
File Import Decision Tree:
1. DEFAULT: Call import_file(path). Auto-detection handles CSV, TSV, Excel, JSON, XML, EDI.
2. CHECK: Did the import succeed with expected columns?
   - Yes → Proceed to mapping/shipping.
   - No (1 column found) → Call sniff_file(path) to inspect raw content.
3. REASON: Analyze the sniffed text.
   - Delimited with unusual separator → import_file(path, delimiter="X")
   - Fixed-width alignment → import_fixed_width(path, col_specs=[...], names=[...])
   - Binary/unreadable → Report error to user.
```

### 3.5 Unchanged Tools

These existing tools remain as-is:
- `import_database(connection_string, query, ...)` — Database snapshot
- `import_records(records, source_label, ...)` — Platform data (Shopify, etc.)
- `list_sheets(file_path)` — Excel sheet listing (enhanced for .xls)
- `list_tables(connection_string, ...)` — Database table listing
- `get_source_info(ctx)` — Active source metadata
- `clear_source(ctx)` — Drop imported_data

## 4. Adapter Implementation Details

### 4.1 DelimitedAdapter (refactored from CSVAdapter)

**Changes from current CSVAdapter:**
- Rename class `CSVAdapter` → `DelimitedAdapter`
- Change `source_type` property to `"delimited"`
- Add optional `quotechar` parameter
- Store detected delimiter in `current_source` metadata (for write-back)
- DuckDB's `read_csv(auto_detect=true, sample_size=-1)` already handles TSV, pipe, semicolon

**Delimiter storage for write-back:**
```python
# After successful import, store in session:
current_source["detected_delimiter"] = detected_delimiter  # e.g., "\t", "|", ";"
```

### 4.2 ExcelAdapter Enhancement (.xls support)

**Routing by extension:**
```python
def import_data(self, conn, file_path, sheet=None, header=True):
    ext = Path(file_path).suffix.lower()
    if ext == ".xls":
        return self._import_xls(conn, file_path, sheet, header)
    else:
        return self._import_xlsx(conn, file_path, sheet, header)  # existing logic
```

**`.xls` reader via python-calamine:**
```python
from python_calamine import CalamineWorkbook

def _import_xls(self, conn, file_path, sheet, header):
    wb = CalamineWorkbook.from_path(file_path)
    ws = wb.get_sheet_by_name(sheet) if sheet else wb.get_sheet_by_index(0)
    rows = ws.to_python()  # Returns list[list[Any]]
    # Same logic as existing openpyxl path: extract headers, filter empty rows, INSERT
```

**`list_sheets` enhancement:**
```python
def list_sheets(self, file_path):
    ext = Path(file_path).suffix.lower()
    if ext == ".xls":
        wb = CalamineWorkbook.from_path(file_path)
        return wb.sheet_names
    else:
        return load_workbook(file_path, read_only=True).sheetnames  # existing
```

### 4.3 JSONAdapter

**Two-tier approach:**

**Tier 1 — Flat JSON arrays** (DuckDB native):
```python
def import_data(self, conn, file_path, record_path=None, header=True):
    # Try DuckDB native read_json_auto first
    conn.execute(f"""
        CREATE OR REPLACE TABLE _raw_json AS
        SELECT * FROM read_json_auto('{file_path}')
    """)
    schema = conn.execute("DESCRIBE _raw_json").fetchall()

    # Check if result is flat (no STRUCT or LIST types in top-level columns)
    if all(not col[1].startswith(("STRUCT", "MAP")) for col in schema):
        # Flat — add _source_row_num directly
        conn.execute("""
            CREATE OR REPLACE TABLE imported_data AS
            SELECT ROW_NUMBER() OVER () AS _source_row_num, *
            FROM _raw_json
        """)
        conn.execute("DROP TABLE _raw_json")
        return self._build_import_result(conn)

    # Nested — fall through to Tier 2
    conn.execute("DROP TABLE _raw_json")
    return self._import_nested_json(conn, file_path, record_path)
```

**Tier 2 — Nested JSON** (Python flattening):
```python
def _import_nested_json(self, conn, file_path, record_path=None):
    with open(file_path) as f:
        data = json.load(f)

    records = self._discover_records(data, record_path)
    flat_records = [flatten_record(r) for r in records]
    return load_flat_records_to_duckdb(conn, flat_records)
```

**Record discovery:**
```python
def _discover_records(self, data, record_path=None):
    if record_path:
        # Navigate to specified path: "Orders/Order" → data["Orders"]["Order"]
        for key in record_path.split("/"):
            data = data[key]
        return data if isinstance(data, list) else [data]

    if isinstance(data, list):
        return data  # Top-level array

    if isinstance(data, dict):
        # Find first key whose value is a list of dicts
        for key, value in data.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
        # No list found — treat entire dict as single record
        return [data]

    raise ValueError("Cannot discover records in JSON file")
```

### 4.4 XMLAdapter

```python
import xmltodict

class XMLAdapter(BaseSourceAdapter):
    source_type = "xml"

    def import_data(self, conn, file_path, record_path=None, header=True):
        with open(file_path) as f:
            raw = xmltodict.parse(f.read())

        records = self._discover_records(raw, record_path)
        # Strip XML artifacts: @attributes, #text, namespace prefixes
        cleaned = [self._clean_xml_record(r) for r in records]
        flat_records = [flatten_record(r) for r in cleaned]
        return load_flat_records_to_duckdb(conn, flat_records)

    def _clean_xml_record(self, record):
        """Remove XML-specific artifacts from dict keys."""
        cleaned = {}
        for key, value in record.items():
            # Strip namespace prefixes: "ns0:Name" → "Name"
            clean_key = key.split(":")[-1] if ":" in key else key
            # Strip attribute prefix: "@id" → "id"
            clean_key = clean_key.lstrip("@")
            # Handle #text: promote to parent value
            if clean_key == "#text":
                continue  # Handled by parent
            if isinstance(value, dict):
                if "#text" in value:
                    cleaned[clean_key] = value["#text"]
                else:
                    cleaned[clean_key] = self._clean_xml_record(value)
            elif isinstance(value, list):
                cleaned[clean_key] = [
                    self._clean_xml_record(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                cleaned[clean_key] = value
        return cleaned

    def _discover_records(self, data, record_path=None):
        """Find the repeating element in XML dict structure."""
        if record_path:
            for key in record_path.split("/"):
                data = data[key]
            return data if isinstance(data, list) else [data]

        # Auto-detect: find deepest key with largest list of dicts
        return self._find_largest_list(data)

    def _find_largest_list(self, data, best=None):
        """Recursively find the list[dict] with most items."""
        if isinstance(data, list) and data and isinstance(data[0], dict):
            if best is None or len(data) > len(best):
                best = data
        if isinstance(data, dict):
            for value in data.values():
                result = self._find_largest_list(value, best)
                if result is not None:
                    best = result
        return best or ([data] if isinstance(data, dict) else [])
```

### 4.5 FixedWidthAdapter

```python
class FixedWidthAdapter(BaseSourceAdapter):
    source_type = "fixed_width"

    def import_data(self, conn, file_path, col_specs, names=None, header=False):
        """Parse fixed-width file using explicit column positions.

        Args:
            col_specs: List of (start, end) byte positions for each column.
            names: Column names. If None, generated as col_0, col_1, ...
            header: If True, skip the first line (treat as header row).
        """
        with open(file_path) as f:
            lines = f.readlines()

        start_line = 1 if header else 0
        if names is None and header and lines:
            # Try to extract names from header line using same col_specs
            names = [
                lines[0][start:end].strip()
                for start, end in col_specs
            ]

        if names is None:
            names = [f"col_{i}" for i in range(len(col_specs))]

        records = []
        for line in lines[start_line:]:
            if not line.strip():
                continue  # Skip empty lines
            record = {}
            for i, (start, end) in enumerate(col_specs):
                record[names[i]] = line[start:end].strip()
            records.append(record)

        return load_flat_records_to_duckdb(conn, records)
```

### 4.6 EDI Adapter Enhancement (Dual Mode)

**Normalized mode** (default, backward compatible):
- Current behavior. Maps to `NormalizedOrder` with fixed 16-column schema.
- Used when `dynamic=False` (default).

**Dynamic mode** (opt-in):
- Flattens ALL parsed segments into prefixed columns.
- X12 example: `N1_ST_Name`, `N4_ST_City`, `REF_PO_Number`, `PO1_1_ProductId`
- EDIFACT example: `NAD_ST_Name`, `LIN_1_ProductId`
- Uses `load_flat_records_to_duckdb()`.

```python
def import_data(self, conn, file_path, dynamic=False):
    content = Path(file_path).read_text()

    if not dynamic:
        # Existing normalized path
        return self._import_normalized(conn, content)

    # Dynamic flattening path
    if content.lstrip().startswith("ISA"):
        records = self._parse_x12_dynamic(content)
    elif content.lstrip().startswith("UNB"):
        records = self._parse_edifact_dynamic(content)
    else:
        raise ValueError("Cannot detect EDI format")

    return load_flat_records_to_duckdb(conn, records)
```

## 5. Write-Back Strategy

### 5.1 Flat Formats (In-Place Atomic)

**CSV/TSV/SSV/DAT** — Enhanced `apply_csv_updates_atomic`:
- Read `detected_delimiter` from `current_source` metadata.
- Write back using the same delimiter (not always comma).
- `csv.DictWriter(f, fieldnames=ordered_fieldnames, delimiter=stored_delimiter)`

**Excel (.xlsx/.xls)** — Existing `apply_excel_updates_atomic` works for .xlsx. For .xls:
- Read via calamine, write via openpyxl as .xlsx (format upgrade on write-back).
- Or: write companion file (safer for legacy formats).

### 5.2 Hierarchical/Complex Formats (Companion File)

For JSON, XML, and EDI sources, generate a companion results file:

```python
def write_back_companion(
    source_path: str,
    row_updates: dict[int, dict[str, Any]],
    reference_column: str | None = None,
) -> str:
    """Generate a companion results CSV for non-flat source formats.

    Returns the path to the generated companion file.
    """
    companion_path = f"{Path(source_path).stem}_results.csv"
    companion_full = Path(source_path).parent / companion_path

    # Columns: Original_Row_Number, Reference_ID, Tracking_Number, Shipped_At
    # Reference_ID sourced from the column identified as the order reference
    # during mapping (e.g., po_number, orderId, reference_number)

    # Append mode: each write-back call adds rows (for per-row batch execution)
    # First call creates the file with headers; subsequent calls append.
```

**MCP write_back tool dispatch:**
```python
if source_type in ("json", "xml", "edi"):
    return _write_back_companion(source_path, row_number, tracking_number, shipped_at)
elif source_type == "delimited":
    return _write_back_delimited(source_path, row_number, tracking_number, shipped_at, delimiter)
elif source_type == "excel":
    return _write_back_excel(source_path, row_number, tracking_number, shipped_at, sheet)
```

## 6. Frontend Changes

### 6.1 DataSourcePanel Upload UI

Replace the two-button layout with an expanded format selector:

**Option A — Single "Import File" button** (simpler):
```typescript
const ACCEPTED_EXTENSIONS = ".csv,.tsv,.txt,.ssv,.dat,.xlsx,.xls,.json,.xml,.edi,.x12,.fwf";

// Single button that opens file picker with all supported types
<button onClick={() => openFilePicker(ACCEPTED_EXTENSIONS)}>
  Import File
</button>
```

**Option B — Grouped buttons** (more discoverable):
```
[Spreadsheet ▾]     [Text Data ▾]     [Structured ▾]
  .csv, .tsv           .json              .edi
  .xlsx, .xls          .xml               .x12
  .ssv, .dat           .fwf
  .txt
```

Decision: Use **Option A** (single button) for simplicity, with a tooltip listing supported formats.

### 6.2 Backend Route Changes

**`data_sources.py` upload endpoint:**

```python
SUPPORTED_EXTENSIONS = {
    ".csv": "delimited", ".tsv": "delimited", ".ssv": "delimited",
    ".txt": "delimited", ".dat": "delimited",
    ".xlsx": "excel", ".xls": "excel",
    ".json": "json", ".xml": "xml",
    ".edi": "edi", ".x12": "edi", ".edifact": "edi",
    ".fwf": "fixed_width",
}

ext = os.path.splitext(file.filename)[1].lower()
if ext not in SUPPORTED_EXTENSIONS:
    raise HTTPException(
        status_code=400,
        detail=f"Unsupported file type: {ext}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS.keys()))}"
    )
source_type = SUPPORTED_EXTENSIONS[ext]
```

**MCP tool dispatch:**
- For most types: call `import_file(file_path, format_hint=source_type)`.
- For `.fwf`: the route cannot auto-import; it should call `import_file` which will return an error directing the agent to use `sniff_file` + `import_fixed_width`.

### 6.3 API Client (api.ts)

No changes needed — `uploadDataSource(file: File)` already sends FormData. The backend handles routing.

## 7. Column Mapping Impact

**Zero changes to `_AUTO_MAP_RULES`.**

The existing 52 rules with token-based canonicalization handle flattened column names:

| Flattened Column | Tokens | Matching Rule | Maps To |
|-----------------|--------|---------------|---------|
| `shipTo_name` | `{shipto, name}` | `(["ship", "name"], ...)` | `shipTo.name` |
| `ShipTo_Address_Line1` | `{shipto, address, line1}` | `(["address"], ["2","3"], ...)` | `shipTo.addressLine1` |
| `ShipTo_Address_City` | `{shipto, address, city}` | `(["city"], ...)` | `shipTo.city` |
| `OrderID` | `{orderid}` | `(["order"], ["_id","status"], ...)` | `referenceNumber` |
| `recipient_name` | `{recipient, name}` | `(["recipient", "name"], ...)` | `shipTo.name` |
| `po_number` | `{po, number}` | `(["order"], ...)` or custom | `referenceNumber` |

This is the core architectural insight: the column mapper is format-agnostic by design.

## 8. Dependencies

| Package | PyPI Name | Size | Purpose |
|---------|-----------|------|---------|
| `xmltodict` | `xmltodict` | ~12KB | XML → Python dict conversion |
| `python-calamine` | `python-calamine` | ~2MB | Legacy .xls file reading (Rust-based) |

**Not added:** `pandas` (150MB, unnecessary — DuckDB + pure Python suffice).

## 9. Testing Strategy

### 9.1 Test Fixtures

Create sample files in `tests/fixtures/data_sources/`:

| File | Format | Content |
|------|--------|---------|
| `orders.csv` | Standard CSV | 5 rows, shipping data |
| `orders.tsv` | Tab-separated | Same data as CSV |
| `orders_pipe.txt` | Pipe-delimited | Same data |
| `orders_semicolon.ssv` | Semicolon-separated | Same data |
| `orders.json` | Flat JSON array | Same data |
| `orders_nested.json` | Nested JSON | shipTo objects, items arrays |
| `orders.xml` | XML with repeating `<Order>` | Same data |
| `orders.xlsx` | Modern Excel | Same data |
| `orders.xls` | Legacy Excel | Same data |
| `report.fwf` | Fixed-width | Same data, fixed columns |
| `orders.edi` | X12 850 | Same data as EDI |

### 9.2 Test Categories

| Category | Tests | Approach |
|----------|-------|----------|
| **Adapter unit tests** | Each adapter with sample fixtures | `pytest tests/mcp/data_source/adapters/` |
| **Router tests** | Extension mapping, format_hint override, ambiguity detection | Unit tests for router function |
| **Flattening tests** | Nested JSON/XML → flat dict correctness | Various nesting depths, edge cases |
| **Write-back tests** | Companion file generation, delimiter preservation | Integration tests with temp files |
| **sniff_file tests** | Raw text return, line count, offset | Unit tests |
| **Fixed-width tests** | Column slicing at correct positions | Known-good fixtures |
| **Integration tests** | Full pipeline: import → schema → map → preview → write-back | End-to-end per format |
| **Backward compat tests** | `import_csv` / `import_excel` wrappers still work | Existing test suite passes |

### 9.3 Test Count Estimate

~60-80 new test functions across adapter, router, flattening, and integration tests.

## 10. Implementation Phases

All phases ship together as a single release.

| Phase | Work | Files Modified/Created |
|-------|------|----------------------|
| **1. Dependencies** | Add `xmltodict`, `python-calamine` to requirements | `requirements.txt`, `pyproject.toml` |
| **2. Shared utilities** | `flatten_record()`, `load_flat_records_to_duckdb()` | `src/mcp/data_source/utils.py` |
| **3. DelimitedAdapter** | Rename CSVAdapter, add quotechar, store delimiter | `adapters/csv_adapter.py` → `adapters/delimited_adapter.py` |
| **4. ExcelAdapter** | Add calamine fallback for .xls | `adapters/excel_adapter.py` |
| **5. JSONAdapter** | New adapter with two-tier approach | `adapters/json_adapter.py` (new) |
| **6. XMLAdapter** | New adapter with xmltodict + cleaning | `adapters/xml_adapter.py` (new) |
| **7. FixedWidthAdapter** | New adapter with pure Python parsing | `adapters/fixed_width_adapter.py` (new) |
| **8. EDI enhancement** | Add dynamic mode to existing adapter | `adapters/edi_adapter.py` |
| **9. MCP tools** | `import_file`, `sniff_file`, `import_fixed_width` + backward compat wrappers | `tools/import_tools.py` |
| **10. Write-back** | Companion file generation, delimiter-aware delimited write-back | `tools/writeback_tools.py`, `write_back_utils.py` |
| **11. Backend route** | Expand extension map in upload endpoint | `src/api/routes/data_sources.py` |
| **12. Frontend** | Single "Import File" button, accept all extensions | `frontend/src/components/sidebar/DataSourcePanel.tsx` |
| **13. System prompt** | Add file import decision tree | `src/orchestrator/agent/system_prompt.py` |
| **14. Tests** | Fixtures + adapter/router/integration tests | `tests/fixtures/data_sources/`, `tests/mcp/data_source/` |

## 11. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| DuckDB `read_json_auto` fails on deeply nested JSON | Import fails | Fall through to Python flattening (Tier 2) |
| `xmltodict` chokes on malformed XML | Import fails | Wrap in try/except, return clear error with line number |
| `python-calamine` doesn't handle specific .xls features (macros, pivot tables) | Partial import | calamine handles data sheets; macros/pivots are outside scope |
| Fixed-width agent reasoning fails | Agent can't determine column positions | User can manually specify positions; sniff_file provides raw data |
| Companion file write conflicts (concurrent writes) | Data corruption | Use append mode with file locking (fcntl) |
| Existing tests break from CSVAdapter rename | CI failure | Keep `CSVAdapter` as an alias for `DelimitedAdapter` |

## 12. Non-Goals

- **Parquet/Arrow/ORC** — Binary columnar formats are outside the logistics file scope.
- **Google Sheets / cloud storage** — Requires OAuth flows; separate feature.
- **Multi-table JSON/XML** — We flatten to a single table. Relational joins are out of scope.
- **EDI generation** — We import EDI; we don't produce EDI output (997/856) in this phase.
- **Streaming/incremental import** — All imports are full-file reads into memory.
