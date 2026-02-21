"""Test EDI adapter for Data Source MCP."""

from pathlib import Path
import tempfile

import duckdb
import pytest

from src.mcp.data_source.adapters.edi_adapter import EDIAdapter
from src.mcp.data_source.models import ImportResult, SOURCE_ROW_NUM_COLUMN


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
def sample_x12_856_with_suite():
    """Create temporary X12 856 file with address_line2 (Suite number)."""
    content = """ISA*00*          *00*          *ZZ*WAREHOUSE01    *ZZ*RETAILER01     *260220*1400*U*00401*000000002*0*P*>~
GS*SH*WAREHOUSE01*RETAILER01*20260220*1400*2*X*004010~
ST*856*0001~
BSN*00*ASN-60001*20260220*1400~
HL*1**S~
N1*ST*James Thornton~
N3*350 Fifth Ave*Suite 4120~
N4*New York*NY*10118*US~
HL*2*1*O~
PRF*PO-50002~
HL*3*2*I~
SN1*1*1*EA~
LIN*1*VP*DOC-100~
SE*14*0001~
GE*1*2~
IEA*1*000000002~"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".x12", delete=False) as f:
        f.write(content)
        return f.name


@pytest.fixture
def sample_x12_856_no_suite():
    """Create temporary X12 856 file without address_line2."""
    content = """ISA*00*          *00*          *ZZ*WAREHOUSE01    *ZZ*RETAILER01     *260220*1400*U*00401*000000003*0*P*>~
GS*SH*WAREHOUSE01*RETAILER01*20260220*1400*3*X*004010~
ST*856*0001~
BSN*00*ASN-60002*20260220*1400~
HL*1**S~
N1*ST*Sarah Mitchell~
N3*4820 Riverside Dr~
N4*Austin*TX*78746*US~
HL*2*1*O~
PRF*PO-50001~
HL*3*2*I~
SN1*1*2*EA~
LIN*1*VP*SKN-001~
SE*13*0001~
GE*1*3~
IEA*1*000000003~"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".x12", delete=False) as f:
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


# --- Regression tests for Bug 1 & 2: _source_row_num standard column ---

def test_source_row_num_column_exists_in_duckdb(sample_x12_850, duckdb_conn):
    """Regression: EDI adapter must use _source_row_num BIGINT, not row_number INTEGER.

    All other adapters use SOURCE_ROW_NUM_COLUMN (_source_row_num) for row
    tracking. EDI was using 'row_number INTEGER' which broke downstream
    write-back and filtering that rely on _source_row_num.
    """
    adapter = EDIAdapter()
    adapter.import_data(duckdb_conn, file_path=sample_x12_850)

    columns = duckdb_conn.execute("DESCRIBE imported_data").fetchall()
    col_dict = {row[0]: row[1] for row in columns}

    # _source_row_num must be present in the DuckDB table
    assert SOURCE_ROW_NUM_COLUMN in col_dict, (
        f"DuckDB table must contain '{SOURCE_ROW_NUM_COLUMN}' column for row tracking"
    )
    assert col_dict[SOURCE_ROW_NUM_COLUMN] == "BIGINT"

    # 'row_number' must NOT be present (was the old wrong column name)
    assert "row_number" not in col_dict, (
        "Legacy 'row_number' column must not exist — use '_source_row_num' instead"
    )


def test_source_row_num_values_correct(sample_x12_850, duckdb_conn):
    """Regression: _source_row_num must be 1-based and match row order."""
    adapter = EDIAdapter()
    adapter.import_data(duckdb_conn, file_path=sample_x12_850)

    row_nums = duckdb_conn.execute(
        f"SELECT {SOURCE_ROW_NUM_COLUMN} FROM imported_data ORDER BY {SOURCE_ROW_NUM_COLUMN}"
    ).fetchall()
    assert row_nums == [(1,)], "Single order should have _source_row_num = 1"


def test_source_row_num_not_in_schema_columns(sample_x12_850, duckdb_conn):
    """Regression: _source_row_num must be filtered from the user-facing schema.

    All other adapters exclude _source_row_num from ImportResult.columns so it
    doesn't appear in the agent's schema view. EDI was returning all columns.
    """
    adapter = EDIAdapter()
    result = adapter.import_data(duckdb_conn, file_path=sample_x12_850)

    schema_col_names = [c.name for c in result.columns]
    assert SOURCE_ROW_NUM_COLUMN not in schema_col_names, (
        f"'{SOURCE_ROW_NUM_COLUMN}' is an internal column and must not appear in schema output"
    )
    # Business columns must still be present
    assert "po_number" in schema_col_names
    assert "recipient_name" in schema_col_names


# --- Regression test for Bug 5: X12 856 address_line2 ---

def test_x12_856_address_line2_captured(sample_x12_856_with_suite, duckdb_conn):
    """Regression: X12 856 parser must capture address_line2 from N3 element[1].

    N3*350 Fifth Ave*Suite 4120~ has two elements. The parser was only taking
    elements[0] (address_line1), silently dropping 'Suite 4120'.
    """
    adapter = EDIAdapter()
    result = adapter.import_data(duckdb_conn, file_path=sample_x12_856_with_suite)

    assert result.row_count == 1

    row = duckdb_conn.execute(
        "SELECT address_line1, address_line2 FROM imported_data"
    ).fetchone()
    address_line1, address_line2 = row

    assert address_line1 == "350 Fifth Ave"
    assert address_line2 == "Suite 4120", (
        "address_line2 from N3 segment second element must be captured"
    )


def test_x12_856_address_line2_none_when_absent(sample_x12_856_no_suite, duckdb_conn):
    """X12 856 address_line2 must be None when N3 has only one element."""
    adapter = EDIAdapter()
    result = adapter.import_data(duckdb_conn, file_path=sample_x12_856_no_suite)

    assert result.row_count == 1

    row = duckdb_conn.execute(
        "SELECT address_line1, address_line2 FROM imported_data"
    ).fetchone()
    address_line1, address_line2 = row

    assert address_line1 == "4820 Riverside Dr"
    assert address_line2 is None


# --- Regression test for Bug 6: EDIAdapter in adapters package __init__ ---

def test_edi_adapter_importable_from_adapters_package():
    """Regression: EDIAdapter must be importable from the adapters package."""
    from src.mcp.data_source.adapters import EDIAdapter as EDIAdapterFromPkg
    assert EDIAdapterFromPkg is not None
    adapter = EDIAdapterFromPkg()
    assert adapter.source_type == "edi"
