"""Test EDI adapter for Data Source MCP."""

from pathlib import Path
import tempfile

import duckdb
import pytest

from src.mcp.data_source.adapters.edi_adapter import EDIAdapter
from src.mcp.data_source.models import ImportResult


@pytest.fixture
def sample_x12_850():
    """Create temporary X12 850 file."""
    content = """ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *260126*1200*U*00401*000000001*0*P*>~
GS*PO*SENDER*RECEIVER*20260126*1200*1*X*004010~
ST*850*0001~
BEG*00*NE*PO-12345**20260126~
N1*ST*John Doe*92*SHIP001~
N3*123 Main Street~
N4*Springfield*IL*62701*US~
PO1*1*5*EA*15.00**UP*012345678901*VP*SKU-001~
CTT*1~
SE*8*0001~
GE*1*1~
IEA*1*000000001~"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".edi", delete=False) as f:
        f.write(content)
        return f.name


@pytest.fixture
def sample_edifact_orders():
    """Create temporary EDIFACT ORDERS file."""
    content = """UNB+UNOC:3+SENDER+RECEIVER+260126:1200+1'
UNH+1+ORDERS:D:96A:UN'
BGM+220+ORDER-001+9'
NAD+ST+++Jane Smith+456 Oak Ave+Chicago+IL+60601+US'
LIN+1++PROD-100:VP'
QTY+21:3'
UNS+S'
UNT+7+1'
UNZ+1+1'"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".edi", delete=False) as f:
        f.write(content)
        return f.name


@pytest.fixture
def duckdb_conn():
    """Create in-memory DuckDB connection."""
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


def test_edi_adapter_source_type():
    """Test EDIAdapter returns correct source type."""
    adapter = EDIAdapter()
    assert adapter.source_type == "edi"


def test_import_x12_850(sample_x12_850, duckdb_conn):
    """Test importing X12 850 file."""
    adapter = EDIAdapter()
    result = adapter.import_data(duckdb_conn, file_path=sample_x12_850)

    assert isinstance(result, ImportResult)
    assert result.source_type == "edi"
    assert result.row_count == 1  # 1 order

    # Verify data loaded into DuckDB
    rows = duckdb_conn.execute("SELECT * FROM imported_data").fetchall()
    assert len(rows) == 1

    # Verify normalized columns
    columns = duckdb_conn.execute("DESCRIBE imported_data").fetchall()
    col_names = [c[0] for c in columns]
    assert "po_number" in col_names
    assert "recipient_name" in col_names
    assert "city" in col_names


def test_import_edifact_orders(sample_edifact_orders, duckdb_conn):
    """Test importing EDIFACT ORDERS file."""
    adapter = EDIAdapter()
    result = adapter.import_data(duckdb_conn, file_path=sample_edifact_orders)

    assert isinstance(result, ImportResult)
    assert result.source_type == "edi"
    assert result.row_count == 1

    # Verify PO number parsed correctly
    po = duckdb_conn.execute(
        "SELECT po_number FROM imported_data"
    ).fetchone()[0]
    assert po == "ORDER-001"


def test_import_file_not_found(duckdb_conn):
    """Test error handling for missing file."""
    adapter = EDIAdapter()
    with pytest.raises(FileNotFoundError, match="EDI file not found"):
        adapter.import_data(duckdb_conn, file_path="/nonexistent/file.edi")


def test_import_invalid_content(duckdb_conn):
    """Test error handling for invalid EDI content."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".edi", delete=False) as f:
        f.write("This is not EDI content")
        invalid_path = f.name

    adapter = EDIAdapter()
    with pytest.raises(ValueError, match="Unsupported EDI format"):
        adapter.import_data(duckdb_conn, file_path=invalid_path)


def test_get_metadata(sample_x12_850, duckdb_conn):
    """Test get_metadata returns correct info after import."""
    adapter = EDIAdapter()

    # Before import
    metadata = adapter.get_metadata(duckdb_conn)
    assert "error" in metadata

    # After import
    adapter.import_data(duckdb_conn, file_path=sample_x12_850)
    metadata = adapter.get_metadata(duckdb_conn)

    assert metadata["row_count"] == 1
    assert metadata["source_type"] == "edi"
