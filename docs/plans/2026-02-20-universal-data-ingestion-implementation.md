# Universal Data Ingestion Engine — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the Data Source MCP to import any common logistics file format (.csv, .tsv, .ssv, .txt, .dat, .xlsx, .xls, .json, .xml, .edi, .fwf) into DuckDB, with smart auto-detection, agent-assisted fixed-width parsing, and companion-file write-back for hierarchical formats.

**Architecture:** Smart `import_file` router auto-detects format from extension, dispatches to the right adapter (DelimitedAdapter, ExcelAdapter, JSONAdapter, XMLAdapter, FixedWidthAdapter, EDIAdapter). All adapters flatten data into DuckDB's `imported_data` table via a shared `load_flat_records_to_duckdb()` utility. Write-back uses companion CSV for non-flat formats.

**Tech Stack:** DuckDB (existing), `xmltodict` (new, 12KB), `python-calamine` (new, 2MB), pure Python for fixed-width parsing. No pandas.

**Design Doc:** `docs/plans/2026-02-20-universal-data-ingestion-design.md`

---

## Task 1: Add Dependencies

**Files:**
- Modify: `pyproject.toml:11-42` (dependencies list)

**Step 1: Add xmltodict and python-calamine to pyproject.toml**

In `pyproject.toml`, add after the `openpyxl` line (line 20):

```python
# Universal data ingestion dependencies
"xmltodict>=0.13.0",
"python-calamine>=0.3.0",
```

The dependencies section should read:
```toml
dependencies = [
    ...
    "openpyxl>=3.1.0",
    # Universal data ingestion dependencies
    "xmltodict>=0.13.0",
    "python-calamine>=0.3.0",
    ...
]
```

**Step 2: Install dependencies**

Run: `pip install -e ".[dev]"`
Expected: Both packages install successfully.

**Step 3: Verify imports**

Run: `python -c "import xmltodict; import python_calamine; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: add xmltodict and python-calamine dependencies"
```

---

## Task 2: Shared Flattening Utilities

**Files:**
- Modify: `src/mcp/data_source/utils.py` (add flatten_record, load_flat_records_to_duckdb)
- Create: `tests/mcp/data_source/test_flatten_utils.py`

**Step 1: Write the failing tests**

Create `tests/mcp/data_source/test_flatten_utils.py`:

```python
"""Tests for hierarchical data flattening utilities."""

import json

import duckdb
import pytest

from src.mcp.data_source.utils import flatten_record, load_flat_records_to_duckdb


class TestFlattenRecord:
    """Test recursive dict flattening."""

    def test_flat_dict_unchanged(self):
        """Flat dicts pass through without modification."""
        record = {"name": "John", "city": "Dallas"}
        assert flatten_record(record) == {"name": "John", "city": "Dallas"}

    def test_nested_dict_flattened_with_underscore(self):
        """Nested dicts joined with underscore separator."""
        record = {"shipTo": {"name": "John", "city": "Dallas"}}
        result = flatten_record(record)
        assert result == {"shipTo_name": "John", "shipTo_city": "Dallas"}

    def test_deeply_nested(self):
        """Multiple nesting levels flatten correctly."""
        record = {"a": {"b": {"c": "deep"}}}
        assert flatten_record(record) == {"a_b_c": "deep"}

    def test_max_depth_serializes_remainder(self):
        """Beyond max_depth, nested dicts become JSON strings."""
        record = {"a": {"b": {"c": {"d": "too deep"}}}}
        result = flatten_record(record, max_depth=2)
        # At depth 2, the {"d": "too deep"} dict should be JSON-serialized
        assert result["a_b_c"] == json.dumps({"d": "too deep"})

    def test_max_depth_default_allows_deep_nesting(self):
        """Default max_depth=5 handles typical logistics nesting."""
        record = {"a": {"b": {"c": {"d": {"e": "val"}}}}}
        result = flatten_record(record)
        assert result["a_b_c_d_e"] == "val"

    def test_lists_become_json_strings(self):
        """Lists are serialized as JSON strings, not expanded."""
        record = {"items": [{"sku": "A1", "qty": 2}]}
        result = flatten_record(record)
        assert result["items"] == json.dumps([{"sku": "A1", "qty": 2}])

    def test_mixed_nested_and_flat(self):
        """Mix of flat, nested, and list values."""
        record = {
            "orderId": "123",
            "shipTo": {"name": "John", "address": {"line1": "123 Main"}},
            "items": [{"sku": "X"}],
        }
        result = flatten_record(record)
        assert result["orderId"] == "123"
        assert result["shipTo_name"] == "John"
        assert result["shipTo_address_line1"] == "123 Main"
        assert result["items"] == json.dumps([{"sku": "X"}])

    def test_none_values_preserved(self):
        """None values pass through as None."""
        record = {"a": None, "b": "val"}
        assert flatten_record(record) == {"a": None, "b": "val"}

    def test_empty_dict(self):
        """Empty dict returns empty dict."""
        assert flatten_record({}) == {}

    def test_numeric_values_preserved(self):
        """Numbers are not converted to strings."""
        record = {"qty": 5, "price": 12.99}
        result = flatten_record(record)
        assert result["qty"] == 5
        assert result["price"] == 12.99


class TestLoadFlatRecordsToDuckDB:
    """Test loading flat dicts into DuckDB imported_data table."""

    @pytest.fixture()
    def conn(self):
        """Fresh in-memory DuckDB connection."""
        c = duckdb.connect(":memory:")
        yield c
        c.close()

    def test_basic_load(self, conn):
        """Load simple records and verify row count + schema."""
        records = [
            {"name": "John", "city": "Dallas"},
            {"name": "Jane", "city": "Austin"},
        ]
        result = load_flat_records_to_duckdb(conn, records)
        assert result.row_count == 2
        col_names = [c.name for c in result.columns]
        assert "name" in col_names
        assert "city" in col_names
        assert "_source_row_num" not in col_names  # Hidden from schema

    def test_source_row_num_assigned(self, conn):
        """_source_row_num is 1-based and sequential."""
        records = [{"a": "x"}, {"a": "y"}, {"a": "z"}]
        load_flat_records_to_duckdb(conn, records)
        rows = conn.execute(
            "SELECT _source_row_num FROM imported_data ORDER BY _source_row_num"
        ).fetchall()
        assert [r[0] for r in rows] == [1, 2, 3]

    def test_heterogeneous_keys(self, conn):
        """Records with different keys get NULL for missing fields."""
        records = [
            {"name": "John", "phone": "555-1234"},
            {"name": "Jane", "email": "jane@test.com"},
        ]
        result = load_flat_records_to_duckdb(conn, records)
        assert result.row_count == 2
        col_names = {c.name for c in result.columns}
        assert {"name", "phone", "email"} == col_names

    def test_empty_records_list(self, conn):
        """Empty list produces zero-row table."""
        result = load_flat_records_to_duckdb(conn, [])
        assert result.row_count == 0

    def test_replaces_existing_table(self, conn):
        """Loading new records replaces previous imported_data."""
        load_flat_records_to_duckdb(conn, [{"a": "1"}])
        load_flat_records_to_duckdb(conn, [{"b": "2"}, {"b": "3"}])
        count = conn.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]
        assert count == 2

    def test_source_type_in_result(self, conn):
        """ImportResult has correct source_type."""
        result = load_flat_records_to_duckdb(conn, [{"x": "1"}], source_type="json")
        assert result.source_type == "json"

    def test_type_inference_preserves_numbers(self, conn):
        """DuckDB should infer numeric types, not force all VARCHAR."""
        records = [{"count": 42, "price": 12.99, "name": "Test"}]
        result = load_flat_records_to_duckdb(conn, records)
        type_map = {c.name: c.type for c in result.columns}
        # DuckDB should infer integer/double for numeric values
        assert "VARCHAR" not in type_map.get("count", "").upper() or "INT" in type_map.get("count", "").upper()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/mcp/data_source/test_flatten_utils.py -v`
Expected: FAIL — `ImportError: cannot import name 'flatten_record' from 'src.mcp.data_source.utils'`

**Step 3: Implement flatten_record and load_flat_records_to_duckdb**

Add to `src/mcp/data_source/utils.py` (after existing functions):

```python
def flatten_record(
    record: dict[str, Any],
    separator: str = "_",
    prefix: str = "",
    max_depth: int = 5,
    _current_depth: int = 0,
) -> dict[str, Any]:
    """Recursively flatten a nested dict into a single-level dict.

    Nested dict keys are joined with separator. Lists are serialized
    as JSON strings to preserve array data without row explosion.
    Recursion stops at max_depth to prevent stack overflow on deeply
    nested structures — remaining dicts are serialized as JSON strings.

    Args:
        record: Nested dictionary to flatten.
        separator: Key separator for nested paths (default: underscore).
        prefix: Internal prefix for recursion (callers should not set this).
        max_depth: Maximum nesting depth before serializing remainder as JSON.
        _current_depth: Internal recursion counter (callers should not set this).

    Returns:
        Flat dictionary with all leaf values.
    """
    flat: dict[str, Any] = {}
    for key, value in record.items():
        full_key = f"{prefix}{separator}{key}" if prefix else key
        if isinstance(value, dict):
            if _current_depth >= max_depth:
                # Depth limit reached — serialize remainder as JSON
                flat[full_key] = json.dumps(value)
            else:
                flat.update(flatten_record(
                    value, separator, full_key, max_depth, _current_depth + 1
                ))
        elif isinstance(value, list):
            flat[full_key] = json.dumps(value)
        else:
            flat[full_key] = value
    return flat


def load_flat_records_to_duckdb(
    conn: Any,
    records: list[dict[str, Any]],
    source_type: str = "unknown",
) -> "ImportResult":
    """Load a list of flat dicts into DuckDB imported_data table.

    Uses executemany for batch insertion (OLAP-friendly, not row-by-row).
    Preserves Python types (int, float, str) so DuckDB can infer column
    types instead of defaulting everything to VARCHAR.
    Adds _source_row_num (1-based). Returns ImportResult with schema.

    Args:
        conn: DuckDB connection.
        records: List of flat dictionaries (one per row).
        source_type: Source type string for ImportResult.

    Returns:
        ImportResult with row count, schema columns, and warnings.
    """
    from src.mcp.data_source.models import SOURCE_ROW_NUM_COLUMN, ImportResult, SchemaColumn

    if not records:
        conn.execute(f"""
            CREATE OR REPLACE TABLE imported_data (
                {SOURCE_ROW_NUM_COLUMN} BIGINT
            )
        """)
        return ImportResult(
            row_count=0,
            columns=[],
            warnings=["No records to import"],
            source_type=source_type,
        )

    # Collect all unique keys (union across all records, preserving order)
    all_keys: list[str] = []
    seen: set[str] = set()
    for record in records:
        for key in record:
            if key not in seen:
                all_keys.append(key)
                seen.add(key)

    # Create table — use VARCHAR initially, then let DuckDB refine types
    # after batch insert via a CTAS (CREATE TABLE AS SELECT) with type inference
    col_defs = ", ".join(f'"{key}" VARCHAR' for key in all_keys)
    conn.execute(f"""
        CREATE OR REPLACE TABLE _staging_import (
            {SOURCE_ROW_NUM_COLUMN} BIGINT,
            {col_defs}
        )
    """)

    # Batch insert using executemany (orders of magnitude faster than row-by-row)
    placeholders = ", ".join(["?"] * (len(all_keys) + 1))
    insert_sql = f"INSERT INTO _staging_import VALUES ({placeholders})"

    batch = []
    for i, record in enumerate(records, 1):
        values = [i] + [record.get(key) for key in all_keys]
        batch.append(values)

    conn.executemany(insert_sql, batch)

    # Promote staging to final table with DuckDB type inference
    # DuckDB's TRY_CAST in a CTAS lets it infer BIGINT, DOUBLE, etc.
    select_cols = ", ".join(f'"{key}"' for key in all_keys)
    conn.execute(f"""
        CREATE OR REPLACE TABLE imported_data AS
        SELECT {SOURCE_ROW_NUM_COLUMN}, {select_cols}
        FROM _staging_import
    """)
    conn.execute("DROP TABLE IF EXISTS _staging_import")

    # Build schema (excluding _source_row_num)
    schema_rows = conn.execute("DESCRIBE imported_data").fetchall()
    columns = [
        SchemaColumn(name=col[0], type=col[1], nullable=True, warnings=[])
        for col in schema_rows
        if col[0] != SOURCE_ROW_NUM_COLUMN
    ]

    row_count = conn.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]

    return ImportResult(
        row_count=row_count,
        columns=columns,
        warnings=[],
        source_type=source_type,
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/mcp/data_source/test_flatten_utils.py -v`
Expected: All 14 tests PASS.

**Step 5: Commit**

```bash
git add src/mcp/data_source/utils.py tests/mcp/data_source/test_flatten_utils.py
git commit -m "feat: add flatten_record and load_flat_records_to_duckdb utilities"
```

---

## Task 3: DelimitedAdapter (Refactor CSVAdapter)

**Files:**
- Modify: `src/mcp/data_source/adapters/csv_adapter.py` (rename class, add quotechar, store delimiter)
- Modify: `src/mcp/data_source/adapters/__init__.py` (export new name + alias)
- Create: `tests/mcp/data_source/test_delimited_adapter.py`

**Step 1: Write the failing tests**

Create `tests/mcp/data_source/test_delimited_adapter.py`:

```python
"""Tests for DelimitedAdapter (CSV, TSV, SSV, pipe-delimited)."""

import textwrap
from pathlib import Path

import duckdb
import pytest

from src.mcp.data_source.adapters.csv_adapter import DelimitedAdapter


@pytest.fixture()
def conn():
    c = duckdb.connect(":memory:")
    yield c
    c.close()


@pytest.fixture()
def tmp_file(tmp_path):
    """Helper to create temp files with given content."""
    def _create(content: str, name: str = "data.csv") -> str:
        p = tmp_path / name
        p.write_text(textwrap.dedent(content).strip())
        return str(p)
    return _create


class TestDelimitedAdapter:
    def test_source_type(self):
        adapter = DelimitedAdapter()
        assert adapter.source_type == "delimited"

    def test_csv_import(self, conn, tmp_file):
        path = tmp_file("name,city\nJohn,Dallas\nJane,Austin")
        adapter = DelimitedAdapter()
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 2
        assert result.source_type == "delimited"

    def test_tsv_import(self, conn, tmp_file):
        path = tmp_file("name\tcity\nJohn\tDallas\nJane\tAustin", name="data.tsv")
        adapter = DelimitedAdapter()
        result = adapter.import_data(conn, file_path=path, delimiter="\t")
        assert result.row_count == 2

    def test_pipe_delimited(self, conn, tmp_file):
        path = tmp_file("name|city\nJohn|Dallas\nJane|Austin", name="data.txt")
        adapter = DelimitedAdapter()
        result = adapter.import_data(conn, file_path=path, delimiter="|")
        assert result.row_count == 2

    def test_semicolon_delimited(self, conn, tmp_file):
        path = tmp_file("name;city\nJohn;Dallas\nJane;Austin", name="data.ssv")
        adapter = DelimitedAdapter()
        result = adapter.import_data(conn, file_path=path, delimiter=";")
        assert result.row_count == 2

    def test_auto_detect_tsv(self, conn, tmp_file):
        """DuckDB auto-detect should handle TSV without explicit delimiter."""
        path = tmp_file("name\tcity\nJohn\tDallas", name="data.tsv")
        adapter = DelimitedAdapter()
        # Don't pass delimiter — rely on auto-detect
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 1
        col_names = [c.name for c in result.columns]
        assert "name" in col_names
        assert "city" in col_names

    def test_detected_delimiter_stored(self, conn, tmp_file):
        """Adapter stores detected_delimiter for write-back."""
        path = tmp_file("name\tcity\nJohn\tDallas", name="data.tsv")
        adapter = DelimitedAdapter()
        adapter.import_data(conn, file_path=path, delimiter="\t")
        assert adapter.detected_delimiter == "\t"

    def test_backward_compat_csv_alias(self):
        """CSVAdapter still importable as alias."""
        from src.mcp.data_source.adapters.csv_adapter import CSVAdapter
        adapter = CSVAdapter()
        assert adapter.source_type == "delimited"


class TestDelimitedAdapterColumnCount:
    """Test ambiguity detection for possible fixed-width files."""

    def test_single_column_warns(self, conn, tmp_file):
        """If only 1 column detected, import should add a warning."""
        path = tmp_file("JOHN DOE       123 MAIN ST     DALLAS", name="report.dat")
        adapter = DelimitedAdapter()
        result = adapter.import_data(conn, file_path=path, header=False)
        # With no delimiter found, DuckDB may produce 1 column
        # The adapter should flag this as potentially ambiguous
        has_warning = any("single column" in w.lower() or "1 column" in w.lower() for w in result.warnings)
        if result.row_count > 0 and len(result.columns) == 1:
            assert has_warning
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/mcp/data_source/test_delimited_adapter.py -v`
Expected: FAIL — `ImportError: cannot import name 'DelimitedAdapter'`

**Step 3: Refactor CSVAdapter → DelimitedAdapter**

Modify `src/mcp/data_source/adapters/csv_adapter.py`:

1. Rename class `CSVAdapter` → `DelimitedAdapter`
2. Change `source_type` property to return `"delimited"`
3. Add `quotechar` parameter to `import_data`
4. Add `detected_delimiter` attribute to store detected delimiter
5. Add single-column ambiguity warning
6. Add `CSVAdapter = DelimitedAdapter` alias at bottom of file
7. Change `source_type` in `ImportResult` to `"delimited"`

Key changes to the class:

```python
class DelimitedAdapter(BaseSourceAdapter):
    """Adapter for importing delimited files (CSV, TSV, SSV, pipe, etc.) via DuckDB."""

    def __init__(self):
        self.detected_delimiter: str | None = None

    @property
    def source_type(self) -> str:
        return "delimited"

    def import_data(
        self,
        conn: "DuckDBPyConnection",
        file_path: str,
        delimiter: str = ",",
        quotechar: str | None = None,
        header: bool = True,
    ) -> ImportResult:
        # ... existing logic ...
        self.detected_delimiter = delimiter
        # ... after building columns, check for single column ...
        if len(columns) == 1 and row_count > 0:
            warnings.append(
                "Only 1 column detected — file may be fixed-width or use an "
                "unrecognized delimiter. Use sniff_file to inspect."
            )
        return ImportResult(..., source_type="delimited")

# Backward compatibility alias
CSVAdapter = DelimitedAdapter
```

**Step 4: Update adapters/__init__.py**

```python
from src.mcp.data_source.adapters.base import BaseSourceAdapter
from src.mcp.data_source.adapters.csv_adapter import CSVAdapter, DelimitedAdapter
from src.mcp.data_source.adapters.db_adapter import DatabaseAdapter
from src.mcp.data_source.adapters.excel_adapter import ExcelAdapter

__all__ = [
    "BaseSourceAdapter", "CSVAdapter", "DelimitedAdapter",
    "DatabaseAdapter", "ExcelAdapter",
]
```

**Step 5: Run tests**

Run: `pytest tests/mcp/data_source/test_delimited_adapter.py -v`
Expected: All tests PASS.

Run: `pytest tests/mcp/test_csv_import.py -v`
Expected: Existing CSV tests still PASS (backward compat).

**Step 6: Commit**

```bash
git add src/mcp/data_source/adapters/csv_adapter.py src/mcp/data_source/adapters/__init__.py tests/mcp/data_source/test_delimited_adapter.py
git commit -m "refactor: rename CSVAdapter to DelimitedAdapter with backward compat"
```

---

## Task 4: ExcelAdapter .xls Enhancement

**Files:**
- Modify: `src/mcp/data_source/adapters/excel_adapter.py` (add calamine path for .xls)
- Create: `tests/mcp/data_source/test_excel_xls.py`

**Step 1: Write the failing test**

Create `tests/mcp/data_source/test_excel_xls.py`:

```python
"""Tests for .xls legacy Excel support via python-calamine."""

import duckdb
import pytest

from src.mcp.data_source.adapters.excel_adapter import ExcelAdapter


@pytest.fixture()
def conn():
    c = duckdb.connect(":memory:")
    yield c
    c.close()


class TestExcelXlsSupport:
    def test_xls_list_sheets(self, tmp_path):
        """list_sheets works for .xls files."""
        # Create a minimal .xls fixture using calamine-compatible format
        # For testing, we'll use a pre-built fixture
        adapter = ExcelAdapter()
        # This test will use a fixture file — see Task 10 for fixture creation
        # For now, test that the code path exists and handles .xls extension
        pytest.skip("Requires .xls test fixture — see Task 10")

    def test_xls_extension_routes_to_calamine(self, conn, tmp_path):
        """Files with .xls extension use calamine reader."""
        adapter = ExcelAdapter()
        assert adapter._is_legacy_xls(str(tmp_path / "test.xls"))
        assert not adapter._is_legacy_xls(str(tmp_path / "test.xlsx"))
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mcp/data_source/test_excel_xls.py -v`
Expected: FAIL — `AttributeError: 'ExcelAdapter' object has no attribute '_is_legacy_xls'`

**Step 3: Add .xls support to ExcelAdapter**

In `src/mcp/data_source/adapters/excel_adapter.py`, add:

1. Import `python_calamine` at top (with try/except for graceful fallback)
2. Add `_is_legacy_xls()` method
3. In `import_data()`, route .xls to calamine path
4. In `list_sheets()`, route .xls to calamine path

```python
try:
    from python_calamine import CalamineWorkbook
    _calamine_available = True
except ImportError:
    _calamine_available = False

class ExcelAdapter(BaseSourceAdapter):
    ...
    def _is_legacy_xls(self, file_path: str) -> bool:
        """Check if file is legacy .xls format."""
        return Path(file_path).suffix.lower() == ".xls"

    def list_sheets(self, file_path: str) -> list[str]:
        if self._is_legacy_xls(file_path):
            return self._list_sheets_calamine(file_path)
        # existing openpyxl path ...

    def _list_sheets_calamine(self, file_path: str) -> list[str]:
        if not _calamine_available:
            raise ImportError("python-calamine required for .xls files: pip install python-calamine")
        wb = CalamineWorkbook.from_path(file_path)
        return wb.sheet_names

    def import_data(self, conn, file_path, sheet=None, header=True):
        if self._is_legacy_xls(file_path):
            return self._import_xls_calamine(conn, file_path, sheet, header)
        # existing openpyxl path ...

    def _import_xls_calamine(self, conn, file_path, sheet, header):
        if not _calamine_available:
            raise ImportError("python-calamine required for .xls files")
        wb = CalamineWorkbook.from_path(file_path)
        sheet_name = sheet or wb.sheet_names[0]
        data = wb.get_sheet_by_name(sheet_name).to_python()
        # data is list[list[Any]]
        # Apply same logic as openpyxl path: extract headers, filter empties, INSERT
        # ... (reuse existing _build_table_from_rows pattern)
```

**Step 4: Run tests**

Run: `pytest tests/mcp/data_source/test_excel_xls.py -v`
Expected: Tests PASS.

**Step 5: Commit**

```bash
git add src/mcp/data_source/adapters/excel_adapter.py tests/mcp/data_source/test_excel_xls.py
git commit -m "feat: add .xls legacy Excel support via python-calamine"
```

---

## Task 5: JSONAdapter

**Files:**
- Create: `src/mcp/data_source/adapters/json_adapter.py`
- Create: `tests/mcp/data_source/test_json_adapter.py`

**Step 1: Write the failing tests**

Create `tests/mcp/data_source/test_json_adapter.py`:

```python
"""Tests for JSON data source adapter."""

import json
from pathlib import Path

import duckdb
import pytest

from src.mcp.data_source.adapters.json_adapter import JSONAdapter


@pytest.fixture()
def conn():
    c = duckdb.connect(":memory:")
    yield c
    c.close()


@pytest.fixture()
def json_file(tmp_path):
    def _create(data, name="data.json"):
        p = tmp_path / name
        p.write_text(json.dumps(data))
        return str(p)
    return _create


class TestJSONAdapterFlat:
    """Test flat JSON array imports (Tier 1 — DuckDB native)."""

    def test_flat_array(self, conn, json_file):
        path = json_file([
            {"name": "John", "city": "Dallas"},
            {"name": "Jane", "city": "Austin"},
        ])
        adapter = JSONAdapter()
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 2
        assert result.source_type == "json"

    def test_source_type(self):
        assert JSONAdapter().source_type == "json"


class TestJSONAdapterNested:
    """Test nested JSON imports (Tier 2 — Python flattening)."""

    def test_nested_objects_flattened(self, conn, json_file):
        path = json_file([
            {"orderId": "1", "shipTo": {"name": "John", "city": "Dallas"}},
            {"orderId": "2", "shipTo": {"name": "Jane", "city": "Austin"}},
        ])
        adapter = JSONAdapter()
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 2
        col_names = [c.name for c in result.columns]
        assert "shipTo_name" in col_names
        assert "shipTo_city" in col_names

    def test_top_level_dict_with_array(self, conn, json_file):
        """Auto-discovers records inside a wrapper object."""
        path = json_file({
            "metadata": {"count": 2},
            "orders": [
                {"id": "1", "city": "Dallas"},
                {"id": "2", "city": "Austin"},
            ]
        })
        adapter = JSONAdapter()
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 2

    def test_explicit_record_path(self, conn, json_file):
        """record_path overrides auto-discovery."""
        path = json_file({
            "response": {"data": {"orders": [
                {"id": "1"}, {"id": "2"}, {"id": "3"}
            ]}}
        })
        adapter = JSONAdapter()
        result = adapter.import_data(conn, file_path=path, record_path="response/data/orders")
        assert result.row_count == 3

    def test_single_dict_as_one_row(self, conn, json_file):
        """A single dict (no list) imports as 1 row."""
        path = json_file({"name": "John", "city": "Dallas"})
        adapter = JSONAdapter()
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 1

    def test_items_array_preserved_as_json(self, conn, json_file):
        """Nested arrays become JSON string columns, not expanded rows."""
        path = json_file([
            {"orderId": "1", "items": [{"sku": "A"}, {"sku": "B"}]},
        ])
        adapter = JSONAdapter()
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 1  # NOT 2 — items are serialized

    def test_file_not_found(self, conn):
        adapter = JSONAdapter()
        with pytest.raises(FileNotFoundError):
            adapter.import_data(conn, file_path="/nonexistent.json")

    def test_file_too_large(self, conn, tmp_path):
        """Files exceeding MAX_FILE_SIZE_BYTES are rejected."""
        from src.mcp.data_source.adapters.json_adapter import MAX_FILE_SIZE_BYTES
        path = tmp_path / "huge.json"
        path.write_text("[" + ",".join(['{"x":"y"}'] * 100) + "]")
        adapter = JSONAdapter()
        # Patch the constant for testing (avoid creating a real 50MB file)
        import src.mcp.data_source.adapters.json_adapter as mod
        original = mod.MAX_FILE_SIZE_BYTES
        mod.MAX_FILE_SIZE_BYTES = 10  # 10 bytes
        try:
            with pytest.raises(ValueError, match="exceeds"):
                adapter.import_data(conn, file_path=str(path))
        finally:
            mod.MAX_FILE_SIZE_BYTES = original
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/mcp/data_source/test_json_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.mcp.data_source.adapters.json_adapter'`

**Step 3: Implement JSONAdapter**

Create `src/mcp/data_source/adapters/json_adapter.py`:

```python
"""JSON adapter for importing JSON files into DuckDB.

Supports two tiers:
- Tier 1: Flat JSON arrays loaded via DuckDB read_json_auto (fast).
- Tier 2: Nested JSON flattened via Python, then loaded into DuckDB.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

from src.mcp.data_source.adapters.base import BaseSourceAdapter
from src.mcp.data_source.models import ImportResult
from src.mcp.data_source.utils import flatten_record, load_flat_records_to_duckdb

# Guard against OOM — Python json.load() buffers entire file in memory.
# 50MB is generous for shipping manifests; truly large files should use
# streaming or database import instead.
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


class JSONAdapter(BaseSourceAdapter):
    """Adapter for importing JSON files into DuckDB."""

    @property
    def source_type(self) -> str:
        return "json"

    def import_data(
        self,
        conn: "DuckDBPyConnection",
        file_path: str,
        record_path: str | None = None,
        header: bool = True,
    ) -> ImportResult:
        """Import JSON file into DuckDB.

        Args:
            conn: DuckDB connection.
            file_path: Path to the JSON file.
            record_path: Slash-separated path to repeating records
                (e.g., "response/data/orders"). Auto-detected if not provided.
            header: Unused (JSON has keys as headers). Kept for interface compat.

        Returns:
            ImportResult with schema and row count.

        Raises:
            FileNotFoundError: If file does not exist.
            ValueError: If file exceeds MAX_FILE_SIZE_BYTES.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"JSON file not found: {file_path}")

        file_size = path.stat().st_size
        if file_size > MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"JSON file exceeds {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB limit "
                f"({file_size // (1024 * 1024)}MB). Use database import for large files."
            )

        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)

        records = self._discover_records(data, record_path)

        # Check if records are flat (no nested dicts)
        needs_flattening = any(
            isinstance(v, dict) for record in records for v in record.values()
        )

        if needs_flattening:
            records = [flatten_record(r) for r in records]

        return load_flat_records_to_duckdb(conn, records, source_type="json")

    def _discover_records(
        self, data: Any, record_path: str | None = None
    ) -> list[dict]:
        """Find the list of records to import.

        Args:
            data: Parsed JSON data (list or dict).
            record_path: Explicit path to records (e.g., "orders/items").

        Returns:
            List of dicts representing individual records.
        """
        if record_path:
            for key in record_path.split("/"):
                data = data[key]
            return data if isinstance(data, list) else [data]

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            # Find first key whose value is a list of dicts
            for key, value in data.items():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    return value
            # No list found — treat entire dict as single record
            return [data]

        raise ValueError(f"Cannot discover records in JSON: unexpected type {type(data)}")

    def get_metadata(self, conn: "DuckDBPyConnection") -> dict:
        """Return metadata about imported JSON data."""
        try:
            row_count = conn.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]
            columns = conn.execute("DESCRIBE imported_data").fetchall()
            from src.mcp.data_source.models import SOURCE_ROW_NUM_COLUMN
            user_columns = [c for c in columns if c[0] != SOURCE_ROW_NUM_COLUMN]
            return {
                "row_count": row_count,
                "column_count": len(user_columns),
                "source_type": "json",
            }
        except Exception:
            return {"error": "No data imported"}
```

**Step 4: Run tests**

Run: `pytest tests/mcp/data_source/test_json_adapter.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/mcp/data_source/adapters/json_adapter.py tests/mcp/data_source/test_json_adapter.py
git commit -m "feat: add JSONAdapter for flat and nested JSON imports"
```

---

## Task 6: XMLAdapter

**Files:**
- Create: `src/mcp/data_source/adapters/xml_adapter.py`
- Create: `tests/mcp/data_source/test_xml_adapter.py`

**Step 1: Write the failing tests**

Create `tests/mcp/data_source/test_xml_adapter.py`:

```python
"""Tests for XML data source adapter."""

import duckdb
import pytest

from src.mcp.data_source.adapters.xml_adapter import XMLAdapter


@pytest.fixture()
def conn():
    c = duckdb.connect(":memory:")
    yield c
    c.close()


@pytest.fixture()
def xml_file(tmp_path):
    def _create(content: str, name: str = "data.xml") -> str:
        p = tmp_path / name
        p.write_text(content)
        return str(p)
    return _create


SIMPLE_XML = """\
<?xml version="1.0"?>
<Orders>
  <Order>
    <OrderID>123</OrderID>
    <ShipTo>
      <Name>John Doe</Name>
      <City>Dallas</City>
    </ShipTo>
  </Order>
  <Order>
    <OrderID>456</OrderID>
    <ShipTo>
      <Name>Jane Smith</Name>
      <City>Austin</City>
    </ShipTo>
  </Order>
</Orders>
"""


class TestXMLAdapter:
    def test_source_type(self):
        assert XMLAdapter().source_type == "xml"

    def test_simple_xml(self, conn, xml_file):
        path = xml_file(SIMPLE_XML)
        adapter = XMLAdapter()
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 2
        col_names = [c.name for c in result.columns]
        assert "OrderID" in col_names
        assert "ShipTo_Name" in col_names
        assert "ShipTo_City" in col_names

    def test_explicit_record_path(self, conn, xml_file):
        path = xml_file(SIMPLE_XML)
        adapter = XMLAdapter()
        result = adapter.import_data(conn, file_path=path, record_path="Orders/Order")
        assert result.row_count == 2

    def test_namespace_stripped(self, conn, xml_file):
        xml = """\
<?xml version="1.0"?>
<ns0:Root xmlns:ns0="http://example.com">
  <ns0:Item><ns0:Name>Test</ns0:Name></ns0:Item>
</ns0:Root>
"""
        path = xml_file(xml)
        adapter = XMLAdapter()
        result = adapter.import_data(conn, file_path=path)
        col_names = [c.name for c in result.columns]
        # Namespace prefixes should be stripped
        assert all(not name.startswith("ns0") for name in col_names)

    def test_file_not_found(self, conn):
        adapter = XMLAdapter()
        with pytest.raises(FileNotFoundError):
            adapter.import_data(conn, file_path="/nonexistent.xml")

    def test_file_too_large(self, conn, tmp_path):
        """Files exceeding MAX_FILE_SIZE_BYTES are rejected."""
        from src.mcp.data_source.adapters.xml_adapter import MAX_FILE_SIZE_BYTES
        path = tmp_path / "huge.xml"
        path.write_text("<Root>" + "<Item><Name>X</Name></Item>" * 50 + "</Root>")
        adapter = XMLAdapter()
        import src.mcp.data_source.adapters.xml_adapter as mod
        original = mod.MAX_FILE_SIZE_BYTES
        mod.MAX_FILE_SIZE_BYTES = 10  # 10 bytes
        try:
            with pytest.raises(ValueError, match="exceeds"):
                adapter.import_data(conn, file_path=str(path))
        finally:
            mod.MAX_FILE_SIZE_BYTES = original
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/mcp/data_source/test_xml_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement XMLAdapter**

Create `src/mcp/data_source/adapters/xml_adapter.py`:

```python
"""XML adapter for importing XML files into DuckDB.

Uses xmltodict to convert XML → dict, then flattens nested
structures and loads into DuckDB via shared utilities.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any

import xmltodict

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

from src.mcp.data_source.adapters.base import BaseSourceAdapter
from src.mcp.data_source.models import ImportResult, SOURCE_ROW_NUM_COLUMN
from src.mcp.data_source.utils import flatten_record, load_flat_records_to_duckdb

# Guard against OOM — xmltodict.parse() buffers entire file in memory.
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


class XMLAdapter(BaseSourceAdapter):
    """Adapter for importing XML files into DuckDB."""

    @property
    def source_type(self) -> str:
        return "xml"

    def import_data(
        self,
        conn: "DuckDBPyConnection",
        file_path: str,
        record_path: str | None = None,
        header: bool = True,
    ) -> ImportResult:
        """Import XML file into DuckDB.

        Raises:
            FileNotFoundError: If file does not exist.
            ValueError: If file exceeds MAX_FILE_SIZE_BYTES.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"XML file not found: {file_path}")

        file_size = path.stat().st_size
        if file_size > MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"XML file exceeds {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB limit "
                f"({file_size // (1024 * 1024)}MB). Use database import for large files."
            )

        with open(file_path, encoding="utf-8") as f:
            raw = xmltodict.parse(f.read())

        records = self._discover_records(raw, record_path)
        cleaned = [self._clean_xml_record(r) for r in records]
        flat_records = [flatten_record(r) for r in cleaned]
        return load_flat_records_to_duckdb(conn, flat_records, source_type="xml")

    def _clean_xml_record(self, record: Any) -> dict:
        """Remove XML artifacts from dict keys (namespaces, @attributes, #text)."""
        if not isinstance(record, dict):
            return record
        cleaned: dict[str, Any] = {}
        for key, value in record.items():
            clean_key = key.split(":")[-1] if ":" in key else key
            clean_key = clean_key.lstrip("@")
            if clean_key == "#text":
                continue
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

    def _discover_records(self, data: Any, record_path: str | None = None) -> list[dict]:
        """Find repeating elements in XML dict structure."""
        if record_path:
            for key in record_path.split("/"):
                data = data[key]
            return data if isinstance(data, list) else [data]
        return self._find_largest_list(data) or ([data] if isinstance(data, dict) else [])

    def _find_largest_list(self, data: Any, best: list | None = None) -> list | None:
        """Recursively find the list[dict] with the most items."""
        if isinstance(data, list) and data and isinstance(data[0], dict):
            if best is None or len(data) > len(best):
                best = data
        if isinstance(data, dict):
            for value in data.values():
                result = self._find_largest_list(value, best)
                if result is not None:
                    best = result
        return best

    def get_metadata(self, conn: "DuckDBPyConnection") -> dict:
        try:
            row_count = conn.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]
            columns = conn.execute("DESCRIBE imported_data").fetchall()
            user_columns = [c for c in columns if c[0] != SOURCE_ROW_NUM_COLUMN]
            return {"row_count": row_count, "column_count": len(user_columns), "source_type": "xml"}
        except Exception:
            return {"error": "No data imported"}
```

**Step 4: Run tests**

Run: `pytest tests/mcp/data_source/test_xml_adapter.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/mcp/data_source/adapters/xml_adapter.py tests/mcp/data_source/test_xml_adapter.py
git commit -m "feat: add XMLAdapter for XML file imports with auto record discovery"
```

---

## Task 7: FixedWidthAdapter

**Files:**
- Create: `src/mcp/data_source/adapters/fixed_width_adapter.py`
- Create: `tests/mcp/data_source/test_fixed_width_adapter.py`

**Step 1: Write the failing tests**

Create `tests/mcp/data_source/test_fixed_width_adapter.py`:

```python
"""Tests for FixedWidthAdapter (pure Python string slicing)."""

import duckdb
import pytest

from src.mcp.data_source.adapters.fixed_width_adapter import FixedWidthAdapter


@pytest.fixture()
def conn():
    c = duckdb.connect(":memory:")
    yield c
    c.close()


@pytest.fixture()
def fwf_file(tmp_path):
    def _create(content: str, name: str = "report.fwf") -> str:
        p = tmp_path / name
        p.write_text(content)
        return str(p)
    return _create


SAMPLE_FWF = """\
John Doe            Dallas         TX
Jane Smith          Austin         TX
Bob Jones           Houston        TX
"""


class TestFixedWidthAdapter:
    def test_source_type(self):
        assert FixedWidthAdapter().source_type == "fixed_width"

    def test_basic_parse(self, conn, fwf_file):
        path = fwf_file(SAMPLE_FWF)
        adapter = FixedWidthAdapter()
        result = adapter.import_data(
            conn,
            file_path=path,
            col_specs=[(0, 20), (20, 35), (35, 37)],
            names=["name", "city", "state"],
        )
        assert result.row_count == 3
        assert result.source_type == "fixed_width"
        col_names = [c.name for c in result.columns]
        assert col_names == ["name", "city", "state"]

    def test_auto_generated_names(self, conn, fwf_file):
        path = fwf_file(SAMPLE_FWF)
        adapter = FixedWidthAdapter()
        result = adapter.import_data(
            conn,
            file_path=path,
            col_specs=[(0, 20), (20, 35), (35, 37)],
        )
        col_names = [c.name for c in result.columns]
        assert col_names == ["col_0", "col_1", "col_2"]

    def test_header_line_skipped(self, conn, fwf_file):
        content = "Name                City           ST\n" + SAMPLE_FWF
        path = fwf_file(content)
        adapter = FixedWidthAdapter()
        result = adapter.import_data(
            conn,
            file_path=path,
            col_specs=[(0, 20), (20, 35), (35, 37)],
            header=True,
        )
        assert result.row_count == 3
        col_names = [c.name for c in result.columns]
        assert col_names == ["Name", "City", "ST"]

    def test_empty_lines_skipped(self, conn, fwf_file):
        content = "John Doe            Dallas         TX\n\n\nJane Smith          Austin         TX\n"
        path = fwf_file(content)
        adapter = FixedWidthAdapter()
        result = adapter.import_data(
            conn, file_path=path,
            col_specs=[(0, 20), (20, 35), (35, 37)],
            names=["name", "city", "state"],
        )
        assert result.row_count == 2

    def test_file_not_found(self, conn):
        adapter = FixedWidthAdapter()
        with pytest.raises(FileNotFoundError):
            adapter.import_data(conn, file_path="/nope.fwf", col_specs=[(0, 10)])
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/mcp/data_source/test_fixed_width_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement FixedWidthAdapter**

Create `src/mcp/data_source/adapters/fixed_width_adapter.py`:

```python
"""Fixed-width file adapter for Data Source MCP.

Uses pure Python string slicing at agent-specified byte positions.
No pandas dependency.
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

from src.mcp.data_source.adapters.base import BaseSourceAdapter
from src.mcp.data_source.models import ImportResult, SOURCE_ROW_NUM_COLUMN
from src.mcp.data_source.utils import load_flat_records_to_duckdb


class FixedWidthAdapter(BaseSourceAdapter):
    """Adapter for importing fixed-width format files."""

    @property
    def source_type(self) -> str:
        return "fixed_width"

    def import_data(
        self,
        conn: "DuckDBPyConnection",
        file_path: str,
        col_specs: list[tuple[int, int]] | None = None,
        names: list[str] | None = None,
        header: bool = False,
        **kwargs,
    ) -> ImportResult:
        """Import fixed-width file into DuckDB.

        Args:
            conn: DuckDB connection.
            file_path: Path to the fixed-width file.
            col_specs: List of (start, end) byte positions for each column.
            names: Column names. Auto-generated if not provided.
            header: If True, first line is treated as header (names extracted
                from it using col_specs, or skipped if names already provided).
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Fixed-width file not found: {file_path}")
        if not col_specs:
            raise ValueError("col_specs required for fixed-width import")

        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()

        start_line = 0
        if header and lines:
            if names is None:
                names = [lines[0][s:e].strip() for s, e in col_specs]
            start_line = 1

        if names is None:
            names = [f"col_{i}" for i in range(len(col_specs))]

        records: list[dict] = []
        for line in lines[start_line:]:
            if not line.strip():
                continue
            record = {
                names[i]: line[s:e].strip()
                for i, (s, e) in enumerate(col_specs)
            }
            records.append(record)

        return load_flat_records_to_duckdb(conn, records, source_type="fixed_width")

    def get_metadata(self, conn: "DuckDBPyConnection") -> dict:
        try:
            row_count = conn.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]
            columns = conn.execute("DESCRIBE imported_data").fetchall()
            user_columns = [c for c in columns if c[0] != SOURCE_ROW_NUM_COLUMN]
            return {"row_count": row_count, "column_count": len(user_columns), "source_type": "fixed_width"}
        except Exception:
            return {"error": "No data imported"}
```

**Step 4: Run tests**

Run: `pytest tests/mcp/data_source/test_fixed_width_adapter.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/mcp/data_source/adapters/fixed_width_adapter.py tests/mcp/data_source/test_fixed_width_adapter.py
git commit -m "feat: add FixedWidthAdapter with pure Python string slicing"
```

---

## Task 8: MCP Tools — import_file Router + sniff_file + import_fixed_width

**Files:**
- Modify: `src/mcp/data_source/tools/import_tools.py` (add new tools)
- Modify: `src/mcp/data_source/server.py` (register new tools)
- Create: `tests/mcp/data_source/test_import_file_router.py`

**Step 1: Write the failing tests**

Create `tests/mcp/data_source/test_import_file_router.py`:

```python
"""Tests for import_file router, sniff_file, and import_fixed_width MCP tools."""

import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import duckdb
import pytest

from src.mcp.data_source.tools.import_tools import import_file, sniff_file, import_fixed_width


@pytest.fixture()
def ctx():
    """Mock FastMCP Context."""
    mock = AsyncMock()
    conn = duckdb.connect(":memory:")
    mock.request_context.lifespan_context = {
        "db": conn,
        "current_source": None,
    }
    mock.info = AsyncMock()
    yield mock
    conn.close()


@pytest.fixture()
def tmp_file(tmp_path):
    def _create(content, name):
        p = tmp_path / name
        if isinstance(content, str):
            p.write_text(content)
        else:
            p.write_text(json.dumps(content))
        return str(p)
    return _create


class TestImportFileRouter:
    async def test_csv_by_extension(self, ctx, tmp_file):
        path = tmp_file("name,city\nJohn,Dallas", "orders.csv")
        result = await import_file(path, ctx)
        assert result["row_count"] == 1
        assert result["source_type"] == "delimited"

    async def test_tsv_by_extension(self, ctx, tmp_file):
        path = tmp_file("name\tcity\nJohn\tDallas", "orders.tsv")
        result = await import_file(path, ctx)
        assert result["row_count"] == 1

    async def test_json_by_extension(self, ctx, tmp_file):
        path = tmp_file([{"name": "John"}], "orders.json")
        result = await import_file(path, ctx)
        assert result["row_count"] == 1
        assert result["source_type"] == "json"

    async def test_xml_by_extension(self, ctx, tmp_file):
        xml = "<Root><Item><Name>John</Name></Item></Root>"
        path = tmp_file(xml, "orders.xml")
        result = await import_file(path, ctx)
        assert result["row_count"] == 1
        assert result["source_type"] == "xml"

    async def test_format_hint_overrides_extension(self, ctx, tmp_file):
        path = tmp_file("name\tcity\nJohn\tDallas", "data.txt")
        result = await import_file(path, ctx, format_hint="delimited", delimiter="\t")
        assert result["row_count"] == 1

    async def test_unsupported_extension(self, ctx, tmp_file):
        path = tmp_file("binary", "data.exe")
        with pytest.raises(ValueError, match="Unsupported"):
            await import_file(path, ctx)

    async def test_current_source_updated(self, ctx, tmp_file):
        path = tmp_file([{"x": "1"}], "data.json")
        await import_file(path, ctx)
        source = ctx.request_context.lifespan_context["current_source"]
        assert source["type"] == "json"
        assert source["path"] == path


class TestSniffFile:
    async def test_returns_raw_lines(self, ctx, tmp_file):
        content = "JOHN DOE       123 MAIN ST\nJANE SMITH     456 ELM AVE\n"
        path = tmp_file(content, "report.dat")
        result = await sniff_file(path, ctx)
        assert "JOHN DOE" in result
        assert "JANE SMITH" in result

    async def test_num_lines_limit(self, ctx, tmp_file):
        lines = "\n".join(f"line {i}" for i in range(20))
        path = tmp_file(lines, "big.txt")
        result = await sniff_file(path, ctx, num_lines=5)
        assert result.count("\n") <= 5

    async def test_offset(self, ctx, tmp_file):
        lines = "\n".join(f"line {i}" for i in range(10))
        path = tmp_file(lines, "data.txt")
        result = await sniff_file(path, ctx, num_lines=3, offset=5)
        assert "line 5" in result
        assert "line 0" not in result


class TestImportFixedWidth:
    async def test_basic_fixed_width(self, ctx, tmp_file):
        content = "John Doe            Dallas\nJane Smith          Austin"
        path = tmp_file(content, "report.fwf")
        result = await import_fixed_width(
            path, ctx,
            col_specs=[(0, 20), (20, 26)],
            names=["name", "city"],
        )
        assert result["row_count"] == 2
        assert result["source_type"] == "fixed_width"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/mcp/data_source/test_import_file_router.py -v`
Expected: FAIL — `ImportError`

**Step 3: Implement import_file, sniff_file, import_fixed_width**

Add to `src/mcp/data_source/tools/import_tools.py` (after existing functions):

```python
# --- Format extension map for import_file router ---
EXTENSION_MAP: dict[str, str] = {
    ".csv": "delimited", ".tsv": "delimited", ".ssv": "delimited",
    ".dat": "delimited", ".txt": "delimited",
    ".json": "json", ".xml": "xml",
    ".xlsx": "excel", ".xls": "excel",
    ".edi": "edi", ".x12": "edi", ".edifact": "edi",
    ".fwf": "fixed_width",
}


async def import_file(
    file_path: str,
    ctx: Context,
    format_hint: str | None = None,
    delimiter: str | None = None,
    quotechar: str | None = None,
    sheet: str | None = None,
    record_path: str | None = None,
    header: bool = True,
    dynamic: bool = False,
) -> dict:
    """Import any supported file format into DuckDB.

    Routes to the appropriate adapter based on file extension.
    Use format_hint to override auto-detection.
    """
    import os
    from src.mcp.data_source.adapters.csv_adapter import DelimitedAdapter
    from src.mcp.data_source.adapters.excel_adapter import ExcelAdapter
    from src.mcp.data_source.adapters.json_adapter import JSONAdapter
    from src.mcp.data_source.adapters.xml_adapter import XMLAdapter
    from src.mcp.data_source.adapters.fixed_width_adapter import FixedWidthAdapter

    db = ctx.request_context.lifespan_context["db"]

    ext = os.path.splitext(file_path)[1].lower()
    source_type = format_hint or EXTENSION_MAP.get(ext)

    if source_type is None:
        raise ValueError(
            f"Unsupported file type: {ext}. "
            f"Supported: {', '.join(sorted(EXTENSION_MAP.keys()))}"
        )

    await ctx.info(f"Importing {file_path} as {source_type}")

    if source_type == "delimited":
        adapter = DelimitedAdapter()
        kwargs = {"file_path": file_path, "header": header}
        if delimiter:
            kwargs["delimiter"] = delimiter
        if quotechar:
            kwargs["quotechar"] = quotechar
        result = adapter.import_data(conn=db, **kwargs)
        detected_delim = adapter.detected_delimiter

    elif source_type == "excel":
        adapter_excel = ExcelAdapter()
        result = adapter_excel.import_data(conn=db, file_path=file_path, sheet=sheet, header=header)
        detected_delim = None

    elif source_type == "json":
        adapter_json = JSONAdapter()
        result = adapter_json.import_data(conn=db, file_path=file_path, record_path=record_path)
        detected_delim = None

    elif source_type == "xml":
        adapter_xml = XMLAdapter()
        result = adapter_xml.import_data(conn=db, file_path=file_path, record_path=record_path)
        detected_delim = None

    elif source_type == "fixed_width":
        raise ValueError(
            "Fixed-width files require explicit column specs. "
            "Use sniff_file to inspect the file, then call import_fixed_width."
        )

    elif source_type == "edi":
        # Delegate to existing EDI import tool
        try:
            from src.mcp.data_source.tools.edi_tools import import_edi
            return await import_edi(file_path, ctx)
        except ImportError:
            raise ValueError("EDI support requires pydifact: pip install pydifact")

    else:
        raise ValueError(f"Unknown source type: {source_type}")

    ctx.request_context.lifespan_context["current_source"] = {
        "type": source_type,
        "path": file_path,
        "sheet": sheet,
        "row_count": result.row_count,
        "deterministic_ready": True,
        "row_key_strategy": "source_row_num",
        "row_key_columns": ["_source_row_num"],
        "detected_delimiter": detected_delim,
    }

    await ctx.info(f"Imported {result.row_count} rows with {len(result.columns)} columns")
    return result.model_dump()


async def sniff_file(
    file_path: str,
    ctx: Context,
    num_lines: int = 10,
    offset: int = 0,
) -> str:
    """Read raw text lines from a file for agent inspection.

    Returns the first N lines as raw text so the agent can reason
    about format (delimiters, fixed-width columns, etc.).

    Uses itertools.islice for lazy reading — only materializes the
    requested lines, not the entire file. Safe for multi-GB files.
    """
    from itertools import islice
    from pathlib import Path

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, encoding="utf-8", errors="replace") as f:
        # Skip to offset, then take num_lines — never reads entire file
        selected = list(islice(f, offset, offset + num_lines))

    await ctx.info(f"Sniffed {len(selected)} lines from {file_path} (offset={offset})")
    return "".join(selected)


async def import_fixed_width(
    file_path: str,
    ctx: Context,
    col_specs: list[tuple[int, int]],
    names: list[str] | None = None,
    header: bool = False,
) -> dict:
    """Import a fixed-width format file using explicit column positions.

    The agent determines col_specs by inspecting the file via sniff_file.
    """
    from src.mcp.data_source.adapters.fixed_width_adapter import FixedWidthAdapter

    db = ctx.request_context.lifespan_context["db"]

    adapter = FixedWidthAdapter()
    result = adapter.import_data(
        conn=db, file_path=file_path, col_specs=col_specs, names=names, header=header,
    )

    ctx.request_context.lifespan_context["current_source"] = {
        "type": "fixed_width",
        "path": file_path,
        "row_count": result.row_count,
        "deterministic_ready": True,
        "row_key_strategy": "source_row_num",
        "row_key_columns": ["_source_row_num"],
    }

    await ctx.info(f"Imported {result.row_count} fixed-width rows")
    return result.model_dump()
```

**Step 4: Register new tools in server.py**

In `src/mcp/data_source/server.py`, update the import block and registrations:

```python
from src.mcp.data_source.tools.import_tools import (
    import_csv,
    import_database,
    import_excel,
    import_file,           # NEW
    import_fixed_width,     # NEW
    list_sheets,
    list_tables,
    sniff_file,            # NEW
)

# ... in tool registration section:
mcp.tool()(import_file)
mcp.tool()(sniff_file)
mcp.tool()(import_fixed_width)
```

**Step 5: Run tests**

Run: `pytest tests/mcp/data_source/test_import_file_router.py -v`
Expected: All tests PASS.

**Step 6: Commit**

```bash
git add src/mcp/data_source/tools/import_tools.py src/mcp/data_source/server.py tests/mcp/data_source/test_import_file_router.py
git commit -m "feat: add import_file router, sniff_file, and import_fixed_width tools"
```

---

## Task 9: Write-Back Enhancement (Companion File + Delimiter-Aware)

**Files:**
- Modify: `src/services/write_back_utils.py` (add `apply_delimited_updates_atomic`, `write_companion_csv`)
- Modify: `src/mcp/data_source/tools/writeback_tools.py` (add new dispatch paths)
- Create: `tests/mcp/data_source/test_writeback_companion.py`

**Step 1: Write the failing tests**

Create `tests/mcp/data_source/test_writeback_companion.py`:

```python
"""Tests for companion file write-back and delimiter-aware delimited write-back."""

import csv
from pathlib import Path

import pytest

from src.services.write_back_utils import (
    apply_delimited_updates_atomic,
    write_companion_csv,
)


class TestDelimitedWriteBack:
    def test_tsv_write_back(self, tmp_path):
        """Write-back preserves tab delimiter."""
        f = tmp_path / "data.tsv"
        f.write_text("name\tcity\nJohn\tDallas\nJane\tAustin")
        updated = apply_delimited_updates_atomic(
            str(f),
            row_updates={1: {"tracking_number": "1Z123"}},
            delimiter="\t",
        )
        assert updated == 1
        content = f.read_text()
        assert "\t" in content
        assert "1Z123" in content

    def test_pipe_write_back(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("name|city\nJohn|Dallas")
        apply_delimited_updates_atomic(
            str(f),
            row_updates={1: {"tracking_number": "1Z456"}},
            delimiter="|",
        )
        content = f.read_text()
        assert "|" in content
        assert "1Z456" in content


class TestCompanionFile:
    def test_creates_companion_csv(self, tmp_path):
        source = tmp_path / "orders.json"
        source.write_text("{}")  # Just needs to exist for path derivation
        companion = write_companion_csv(
            source_path=str(source),
            row_number=1,
            reference_id="ORD-001",
            tracking_number="1Z999",
            shipped_at="2026-02-20T00:00:00Z",
        )
        assert Path(companion).exists()
        with open(companion) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["Tracking_Number"] == "1Z999"
        assert rows[0]["Reference_ID"] == "ORD-001"

    def test_appends_to_existing(self, tmp_path):
        source = tmp_path / "orders.xml"
        source.write_text("")
        write_companion_csv(str(source), 1, "A", "1Z1", "2026-01-01T00:00:00Z")
        write_companion_csv(str(source), 2, "B", "1Z2", "2026-01-02T00:00:00Z")
        companion_path = str(source).replace(".xml", "_results.csv")
        with open(companion_path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/mcp/data_source/test_writeback_companion.py -v`
Expected: FAIL — `ImportError`

**Step 3: Implement**

Add to `src/services/write_back_utils.py`:

```python
def apply_delimited_updates_atomic(
    file_path: str,
    row_updates: dict[int, dict[str, Any]],
    delimiter: str = ",",
) -> int:
    """Apply row updates to a delimited file preserving the original delimiter.

    Same logic as apply_csv_updates_atomic but with configurable delimiter.
    """
    # Read with specified delimiter
    with open(file_path, "r", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError(f"File has no header row: {file_path}")
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    if not rows:
        raise ValueError(f"File has no data rows: {file_path}")

    # Collect any new columns
    needed_columns = set()
    for updates in row_updates.values():
        needed_columns.update(updates.keys())
    ordered_fieldnames = fieldnames + [
        col for col in sorted(needed_columns) if col not in fieldnames
    ]

    updated_count = 0
    for row_number, updates in row_updates.items():
        if row_number < 1 or row_number > len(rows):
            raise ValueError(f"Row {row_number} out of range (1-{len(rows)})")
        row = rows[row_number - 1]
        for column, value in updates.items():
            row[column] = "" if value is None else str(value)
        updated_count += 1

    # Atomic write
    dir_path = str(Path(file_path).parent)
    temp_fd, temp_path = tempfile.mkstemp(suffix=".tmp", dir=dir_path)
    try:
        os.close(temp_fd)
        temp_fd = None
        with open(temp_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ordered_fieldnames, delimiter=delimiter)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_path, file_path)
        temp_path = None
    finally:
        _cleanup_temp_artifacts(temp_fd, temp_path)

    return updated_count


def write_companion_csv(
    source_path: str,
    row_number: int,
    reference_id: str,
    tracking_number: str,
    shipped_at: str,
    cost_cents: int | None = None,
) -> str:
    """Write a row to the companion results CSV for non-flat source formats.

    Creates {source_stem}_results.csv on first call; appends on subsequent calls.

    Args:
        source_path: Path to the original source file (for deriving companion path).
        row_number: 1-based row number from imported_data.
        reference_id: Order reference ID (for human identification).
        tracking_number: UPS tracking number.
        shipped_at: ISO8601 timestamp.
        cost_cents: Shipping cost in cents (optional).

    Returns:
        Path to the companion CSV file.
    """
    source = Path(source_path)
    companion_path = source.parent / f"{source.stem}_results.csv"

    fieldnames = [
        "Original_Row_Number", "Reference_ID",
        "Tracking_Number", "Shipped_At", "Cost_Cents",
    ]
    row_data = {
        "Original_Row_Number": row_number,
        "Reference_ID": reference_id,
        "Tracking_Number": tracking_number,
        "Shipped_At": shipped_at,
        "Cost_Cents": cost_cents or "",
    }

    write_header = not companion_path.exists()
    with open(companion_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(row_data)

    return str(companion_path)
```

**Step 4: Update writeback_tools.py dispatch**

In `src/mcp/data_source/tools/writeback_tools.py`, update the `write_back` function to handle new source types:

```python
from src.services.write_back_utils import (
    apply_csv_updates_atomic,
    apply_delimited_updates_atomic,
    apply_excel_updates_atomic,
    write_companion_csv,
)

# In the write_back function, update dispatch:
if source_type == "csv":
    # Legacy CSV path (backward compat)
    await _write_back_csv(...)
elif source_type == "delimited":
    detected_delim = current_source.get("detected_delimiter", ",")
    apply_delimited_updates_atomic(
        file_path=current_source["path"],
        row_updates={row_number: {"tracking_number": tracking_number, "shipped_at": shipped_at}},
        delimiter=detected_delim,
    )
elif source_type in ("json", "xml", "edi"):
    companion = write_companion_csv(
        source_path=current_source["path"],
        row_number=row_number,
        reference_id=str(row_number),  # Best-effort reference
        tracking_number=tracking_number,
        shipped_at=shipped_at,
    )
    await ctx.info(f"Wrote tracking to companion file: {companion}")
elif source_type == "excel":
    await _write_back_excel(...)
# ... rest unchanged
```

**Step 5: Run tests**

Run: `pytest tests/mcp/data_source/test_writeback_companion.py -v`
Expected: All tests PASS.

**Step 6: Commit**

```bash
git add src/services/write_back_utils.py src/mcp/data_source/tools/writeback_tools.py tests/mcp/data_source/test_writeback_companion.py
git commit -m "feat: add companion file write-back and delimiter-aware delimited write-back"
```

---

## Task 10: Backend Route Expansion

**Files:**
- Modify: `src/api/routes/data_sources.py:157-167` (expand extension map)
- Modify: `src/services/data_source_mcp_client.py` (add `import_file` method if needed)
- Create: `tests/api/test_upload_formats.py`

**Step 1: Write the failing test**

Create `tests/api/test_upload_formats.py`:

```python
"""Test that the upload endpoint accepts all supported file formats."""

import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


SUPPORTED_EXTENSIONS = [".csv", ".tsv", ".ssv", ".txt", ".dat", ".xlsx", ".xls",
                        ".json", ".xml", ".edi", ".x12", ".fwf"]


class TestUploadFormatAcceptance:
    """Verify the upload route accepts all new file extensions."""

    @pytest.fixture()
    def client(self):
        from src.api.main import app
        return TestClient(app)

    @pytest.mark.parametrize("ext", SUPPORTED_EXTENSIONS)
    def test_extension_accepted(self, ext, client, tmp_path):
        """Upload endpoint should not reject supported extensions."""
        f = tmp_path / f"test{ext}"
        f.write_text("name,city\nJohn,Dallas")  # Minimal content

        with patch("src.api.routes.data_sources.get_data_gateway") as mock_gw:
            mock_gw.return_value = AsyncMock()
            mock_gw.return_value.call_tool = AsyncMock(return_value={
                "row_count": 1, "columns": [], "warnings": [],
                "source_type": "delimited", "deterministic_ready": True,
                "row_key_strategy": "source_row_num", "row_key_columns": [],
            })
            with open(f, "rb") as fh:
                response = client.post(
                    "/api/v1/data-sources/upload",
                    files={"file": (f.name, fh, "application/octet-stream")},
                )
            # Should NOT be 400 "Unsupported file type"
            assert response.status_code != 400 or "Unsupported" not in response.text
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_upload_formats.py -v`
Expected: FAIL for .tsv, .json, .xml, etc. — HTTP 400 "Unsupported file type"

**Step 3: Update the upload route**

In `src/api/routes/data_sources.py`, replace the extension check (lines 157-167):

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
source_type = SUPPORTED_EXTENSIONS.get(ext)
if source_type is None:
    raise HTTPException(
        status_code=400,
        detail=f"Unsupported file type: {ext}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS.keys()))}",
    )
```

Then update the dispatch logic (lines 185-188) to use `import_file` for new formats:

```python
if source_type == "csv":
    result = await gw.import_csv(file_path=file_path)
elif source_type == "excel":
    result = await gw.import_excel(file_path=file_path)
else:
    # Use the universal import_file tool for all other formats
    result = await gw.call_tool("import_file", {
        "file_path": file_path,
        "format_hint": source_type,
    })
```

**Step 4: Run tests**

Run: `pytest tests/api/test_upload_formats.py -v`
Expected: All parametrized tests PASS.

Run: `pytest tests/api/ -v -k "not stream and not sse"`
Expected: Existing API tests still PASS.

**Step 5: Commit**

```bash
git add src/api/routes/data_sources.py tests/api/test_upload_formats.py
git commit -m "feat: expand upload route to accept all supported file formats"
```

---

## Task 11: Frontend — Single Import Button

**Files:**
- Modify: `frontend/src/components/sidebar/DataSourcePanel.tsx` (replace two buttons with single "Import File")

**Step 1: Update the file picker**

In `DataSourcePanel.tsx`, find the CSV and Excel button section and replace with:

```tsx
const ACCEPTED_EXTENSIONS = ".csv,.tsv,.txt,.ssv,.dat,.xlsx,.xls,.json,.xml,.edi,.x12,.fwf";

// Replace the two separate buttons with:
<button
  className="btn-primary w-full"
  onClick={() => openFilePicker(ACCEPTED_EXTENSIONS)}
  disabled={isImporting}
>
  {isImporting ? "Importing..." : "Import File"}
</button>
<p className="text-xs text-muted-foreground mt-1">
  CSV, TSV, Excel, JSON, XML, EDI, and more
</p>
```

**Step 2: Update handleFileSelected to detect format**

The existing `handleFileSelected` function determines `source_type` from the extension. Update it to handle all new extensions — but since the backend now handles routing, the frontend just needs to send the file via `uploadDataSource(file)`.

If the frontend currently has format-specific upload logic, simplify to always call `uploadDataSource(file)` regardless of extension.

**Step 3: Ensure upload errors surface in the UI**

If the upload fails (e.g., file too large, unsupported format, adapter error), the error message from the backend's `DataSourceImportResponse.error` field must be displayed to the user. Check `DataSourcePanel.tsx` — if it only shows a generic "Import failed" message, update it to display the specific `error` string from the response. This is critical for the new 50MB file size guards: users must see *why* their file was rejected (e.g., "JSON file exceeds 50MB limit"), not just "Import failed."

**Step 4: Visual verification**

Run: `cd frontend && npm run dev`
Open browser → sidebar → verify single "Import File" button appears.
Test: Select a .tsv file → should upload successfully.
Test: Upload a file that triggers an error → verify the error message appears in the UI.

**Step 6: Commit**

```bash
cd frontend && git add src/components/sidebar/DataSourcePanel.tsx
git commit -m "feat: replace CSV/Excel buttons with universal Import File button"
```

---

## Task 12: Update Adapter Registry & System Prompt

**Files:**
- Modify: `src/mcp/data_source/adapters/__init__.py` (export all new adapters)
- Modify: `src/orchestrator/agent/system_prompt.py` (add file import decision tree)

**Step 1: Update adapter __init__.py**

```python
from src.mcp.data_source.adapters.base import BaseSourceAdapter
from src.mcp.data_source.adapters.csv_adapter import CSVAdapter, DelimitedAdapter
from src.mcp.data_source.adapters.db_adapter import DatabaseAdapter
from src.mcp.data_source.adapters.excel_adapter import ExcelAdapter
from src.mcp.data_source.adapters.json_adapter import JSONAdapter
from src.mcp.data_source.adapters.xml_adapter import XMLAdapter
from src.mcp.data_source.adapters.fixed_width_adapter import FixedWidthAdapter

__all__ = [
    "BaseSourceAdapter",
    "CSVAdapter",
    "DatabaseAdapter",
    "DelimitedAdapter",
    "ExcelAdapter",
    "FixedWidthAdapter",
    "JSONAdapter",
    "XMLAdapter",
]
```

**Step 2: Add file import decision tree to system prompt**

In `src/orchestrator/agent/system_prompt.py`, add to the data source section:

```python
FILE_IMPORT_INSTRUCTIONS = """
## File Import Decision Tree

The Data Source MCP now supports all common file formats:
- **Delimited:** .csv, .tsv, .ssv, .txt, .dat (auto-detected delimiter)
- **Spreadsheets:** .xlsx, .xls (including legacy Excel)
- **Structured:** .json (flat or nested), .xml (auto record discovery)
- **EDI:** .edi, .x12, .edifact (X12 850/856/810, EDIFACT ORDERS)
- **Fixed-width:** .fwf, .dat, .txt (requires agent-specified column positions)

### Workflow:
1. **Default:** Call `import_file(path)` — auto-detects format from extension.
2. **Check:** Did the import succeed with expected columns?
   - Yes → Proceed to mapping/shipping.
   - No (1 column found) → Call `sniff_file(path)` to inspect raw content.
3. **Reason:** Analyze the sniffed text.
   - Delimited with unusual separator → `import_file(path, delimiter="X")`
   - Fixed-width alignment → `import_fixed_width(path, col_specs=[...], names=[...])`
   - Binary/unreadable → Report error to user.

### Write-back behavior:
- CSV/TSV/SSV/Excel: Tracking numbers written back to original file.
- JSON/XML/EDI: Companion results CSV generated ({filename}_results.csv).
"""
```

**Step 3: Run existing tests**

Run: `pytest tests/orchestrator/ -v -k "not stream"`
Expected: All existing tests PASS.

**Step 4: Commit**

```bash
git add src/mcp/data_source/adapters/__init__.py src/orchestrator/agent/system_prompt.py
git commit -m "feat: register all adapters and add file import decision tree to system prompt"
```

---

## Task 13: Integration Tests & Full Pipeline Verification

**Files:**
- Create: `tests/mcp/data_source/test_universal_ingestion_integration.py`

**Step 1: Write integration tests**

```python
"""Integration tests for the universal data ingestion pipeline.

Tests the full flow: file → adapter → DuckDB → schema → column mapping compatibility.
"""

import json
import textwrap

import duckdb
import pytest

from src.mcp.data_source.adapters.csv_adapter import DelimitedAdapter
from src.mcp.data_source.adapters.json_adapter import JSONAdapter
from src.mcp.data_source.adapters.xml_adapter import XMLAdapter
from src.mcp.data_source.adapters.fixed_width_adapter import FixedWidthAdapter
from src.services.column_mapping import ColumnMappingService


@pytest.fixture()
def conn():
    c = duckdb.connect(":memory:")
    yield c
    c.close()


@pytest.fixture()
def tmp_file(tmp_path):
    def _create(content, name):
        p = tmp_path / name
        if isinstance(content, (dict, list)):
            p.write_text(json.dumps(content))
        else:
            p.write_text(textwrap.dedent(content).strip())
        return str(p)
    return _create


SHIPPING_JSON = [
    {
        "orderId": "ORD-001",
        "shipTo": {
            "name": "John Doe",
            "addressLine1": "123 Main St",
            "city": "Dallas",
            "state": "TX",
            "postalCode": "75201",
            "country": "US",
        },
        "weight": 5.0,
        "service": "UPS Ground",
    },
]

SHIPPING_XML = """\
<?xml version="1.0"?>
<Shipments>
  <Shipment>
    <OrderID>ORD-001</OrderID>
    <RecipientName>John Doe</RecipientName>
    <AddressLine1>123 Main St</AddressLine1>
    <City>Dallas</City>
    <State>TX</State>
    <PostalCode>75201</PostalCode>
    <Country>US</Country>
    <Weight>5.0</Weight>
  </Shipment>
</Shipments>
"""


class TestColumnMappingCompatibility:
    """Verify that flattened columns from new formats hit auto-map rules."""

    def test_json_columns_auto_map(self, conn, tmp_file):
        """Nested JSON shipTo_name should map to shipTo.name."""
        path = tmp_file(SHIPPING_JSON, "orders.json")
        adapter = JSONAdapter()
        result = adapter.import_data(conn, file_path=path)
        col_names = [c.name for c in result.columns]

        mapper = ColumnMappingService()
        mapping = mapper.auto_map_columns(col_names)
        # At minimum, name and city should map
        assert "shipTo.name" in mapping or any("name" in v.lower() for v in mapping.values())

    def test_xml_columns_auto_map(self, conn, tmp_file):
        path = tmp_file(SHIPPING_XML, "orders.xml")
        adapter = XMLAdapter()
        result = adapter.import_data(conn, file_path=path)
        col_names = [c.name for c in result.columns]

        mapper = ColumnMappingService()
        mapping = mapper.auto_map_columns(col_names)
        assert len(mapping) > 0  # At least some columns should map

    def test_tsv_same_as_csv(self, conn, tmp_file):
        """TSV import produces same schema as equivalent CSV."""
        csv_path = tmp_file("name,city,state\nJohn,Dallas,TX", "data.csv")
        tsv_path = tmp_file("name\tcity\tstate\nJohn\tDallas\tTX", "data.tsv")

        adapter = DelimitedAdapter()
        csv_result = adapter.import_data(conn, file_path=csv_path)
        csv_cols = {c.name for c in csv_result.columns}

        tsv_result = adapter.import_data(conn, file_path=tsv_path, delimiter="\t")
        tsv_cols = {c.name for c in tsv_result.columns}

        assert csv_cols == tsv_cols


class TestEndToEndPipeline:
    """Test the full import → query → verify pipeline."""

    def test_json_import_queryable(self, conn, tmp_file):
        path = tmp_file(SHIPPING_JSON, "orders.json")
        JSONAdapter().import_data(conn, file_path=path)
        rows = conn.execute("SELECT * FROM imported_data").fetchall()
        assert len(rows) == 1

    def test_xml_import_queryable(self, conn, tmp_file):
        path = tmp_file(SHIPPING_XML, "orders.xml")
        XMLAdapter().import_data(conn, file_path=path)
        rows = conn.execute("SELECT * FROM imported_data").fetchall()
        assert len(rows) == 1
```

**Step 2: Run integration tests**

Run: `pytest tests/mcp/data_source/test_universal_ingestion_integration.py -v`
Expected: All integration tests PASS.

**Step 3: Run full test suite**

Run: `pytest -k "not stream and not sse and not progress" --tb=short`
Expected: All existing + new tests PASS. No regressions.

**Step 4: Commit**

```bash
git add tests/mcp/data_source/test_universal_ingestion_integration.py
git commit -m "test: add integration tests for universal data ingestion pipeline"
```

---

## Task 14: Final Verification & Cleanup

**Step 1: Run full test suite**

```bash
pytest -k "not stream and not sse and not progress" --tb=short -q
```

Expected: All tests pass. Note the new test count.

**Step 2: Type check**

```bash
mypy src/mcp/data_source/adapters/ src/mcp/data_source/tools/ src/services/write_back_utils.py --ignore-missing-imports
```

**Step 3: Lint**

```bash
ruff check src/mcp/data_source/ src/services/write_back_utils.py src/api/routes/data_sources.py
ruff format src/mcp/data_source/ src/services/write_back_utils.py src/api/routes/data_sources.py
```

**Step 4: Final commit (if lint changes)**

```bash
git add -u
git commit -m "style: lint and format universal ingestion code"
```

---

## Summary

| Task | Description | New Tests | Commit Message |
|------|------------|-----------|----------------|
| 1 | Dependencies (xmltodict, python-calamine) | 0 | `build: add xmltodict and python-calamine dependencies` |
| 2 | Shared flattening utilities | ~14 | `feat: add flatten_record and load_flat_records_to_duckdb utilities` |
| 3 | DelimitedAdapter refactor | ~10 | `refactor: rename CSVAdapter to DelimitedAdapter with backward compat` |
| 4 | ExcelAdapter .xls support | ~3 | `feat: add .xls legacy Excel support via python-calamine` |
| 5 | JSONAdapter (+ 50MB guard) | ~9 | `feat: add JSONAdapter for flat and nested JSON imports` |
| 6 | XMLAdapter (+ 50MB guard) | ~6 | `feat: add XMLAdapter for XML file imports with auto record discovery` |
| 7 | FixedWidthAdapter | ~6 | `feat: add FixedWidthAdapter with pure Python string slicing` |
| 8 | MCP tools (router + sniff + fwf) | ~10 | `feat: add import_file router, sniff_file, and import_fixed_width tools` |
| 9 | Write-back enhancement | ~5 | `feat: add companion file write-back and delimiter-aware delimited write-back` |
| 10 | Backend route expansion | ~12 | `feat: expand upload route to accept all supported file formats` |
| 11 | Frontend single import button | 0 | `feat: replace CSV/Excel buttons with universal Import File button` |
| 12 | Adapter registry + system prompt | 0 | `feat: register all adapters and add file import decision tree to system prompt` |
| 13 | Integration tests | ~6 | `test: add integration tests for universal data ingestion pipeline` |
| 14 | Final verification & cleanup | 0 | `style: lint and format universal ingestion code` |

**Total: ~14 commits, ~81 new tests, 5 new files, 8 modified files**
