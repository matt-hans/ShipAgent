"""Test CSV import functionality.

Tests CSVAdapter and the import_csv MCP tool for:
- Basic CSV import with schema discovery
- Mixed-type column handling (defaults to VARCHAR)
- Empty row skipping
- File not found error handling
"""

import tempfile

import duckdb
import pytest

from src.mcp.data_source.adapters.csv_adapter import CSVAdapter
from src.mcp.data_source.models import ImportResult


@pytest.fixture
def sample_csv():
    """Create a temporary CSV file for testing.

    Contains:
    - 5 data rows (4 valid, 1 empty)
    - Mixed date formats to test parsing
    - Variety of data types (int, string, date, float, state codes)
    """
    content = """order_id,customer_name,ship_date,weight,state
1001,John Doe,2026-01-15,5.5,CA
1002,Jane Smith,01/20/2026,3.2,NY
1003,Bob Wilson,2026-01-25,7.8,TX
,,,,
1004,Alice Brown,2026-01-30,2.1,FL"""

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False
    ) as f:
        f.write(content)
        return f.name


@pytest.fixture
def duckdb_conn():
    """Create in-memory DuckDB connection for testing."""
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


def test_csv_import_basic(sample_csv, duckdb_conn):
    """Test basic CSV import with schema discovery.

    Verifies:
    - ImportResult is returned with correct structure
    - Row count is 4 (empty row skipped)
    - All 5 columns discovered
    - Source type is 'csv'
    """
    adapter = CSVAdapter()
    result = adapter.import_data(duckdb_conn, sample_csv)

    assert isinstance(result, ImportResult)
    assert result.row_count == 4  # Empty row skipped
    assert result.source_type == "csv"
    assert len(result.columns) == 5

    # Check column names
    col_names = [c.name for c in result.columns]
    assert "order_id" in col_names
    assert "customer_name" in col_names
    assert "ship_date" in col_names
    assert "weight" in col_names
    assert "state" in col_names


def test_csv_import_file_not_found(duckdb_conn):
    """Test error handling for missing file.

    Should raise FileNotFoundError with clear message.
    """
    adapter = CSVAdapter()
    with pytest.raises(FileNotFoundError) as exc_info:
        adapter.import_data(duckdb_conn, "/nonexistent/file.csv")

    assert "CSV file not found" in str(exc_info.value)


def test_csv_mixed_types(duckdb_conn):
    """Test that mixed-type columns default to VARCHAR.

    When a column has inconsistent types (numbers and strings),
    DuckDB with ignore_errors=true defaults to VARCHAR.
    """
    content = """id,value
1,100
2,abc
3,200"""

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False
    ) as f:
        f.write(content)
        csv_path = f.name

    adapter = CSVAdapter()
    result = adapter.import_data(duckdb_conn, csv_path)

    # The 'value' column should be VARCHAR due to mixed types
    value_col = next(c for c in result.columns if c.name == "value")
    assert "VARCHAR" in value_col.type.upper()


def test_csv_adapter_source_type():
    """Test that CSVAdapter returns correct source_type."""
    adapter = CSVAdapter()
    assert adapter.source_type == "csv"


def test_csv_get_metadata(sample_csv, duckdb_conn):
    """Test get_metadata returns correct info after import."""
    adapter = CSVAdapter()

    # Before import, should return error
    metadata = adapter.get_metadata(duckdb_conn)
    assert "error" in metadata

    # After import, should return stats
    adapter.import_data(duckdb_conn, sample_csv)
    metadata = adapter.get_metadata(duckdb_conn)

    assert metadata["row_count"] == 4
    assert metadata["column_count"] == 5
    assert metadata["source_type"] == "csv"


def test_csv_custom_delimiter(duckdb_conn):
    """Test CSV import with custom delimiter (pipe)."""
    content = """id|name|value
1|Alice|100
2|Bob|200"""

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False
    ) as f:
        f.write(content)
        csv_path = f.name

    adapter = CSVAdapter()
    result = adapter.import_data(duckdb_conn, csv_path, delimiter="|")

    assert result.row_count == 2
    assert len(result.columns) == 3
    col_names = [c.name for c in result.columns]
    assert "id" in col_names
    assert "name" in col_names
    assert "value" in col_names


def test_csv_no_header(duckdb_conn):
    """Test CSV import without header row."""
    content = """1,Alice,100
2,Bob,200
3,Charlie,300"""

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False
    ) as f:
        f.write(content)
        csv_path = f.name

    adapter = CSVAdapter()
    result = adapter.import_data(duckdb_conn, csv_path, header=False)

    # Should have 3 rows and auto-generated column names
    assert result.row_count == 3
    assert len(result.columns) == 3
