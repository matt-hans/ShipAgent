"""Test EDI MCP tools."""

import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.mcp.data_source.tools.edi_tools import import_edi


@pytest.fixture
def sample_x12_file():
    """Create temporary X12 850 file."""
    content = """ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *260126*1200*U*00401*000000001*0*P*>~
GS*PO*SENDER*RECEIVER*20260126*1200*1*X*004010~
ST*850*0001~
BEG*00*NE*PO-TEST**20260126~
N1*ST*Test User~
N3*100 Test St~
N4*TestCity*TS*12345*US~
PO1*1*1*EA*10.00**VP*TEST-SKU~
CTT*1~
SE*8*0001~
GE*1*1~
IEA*1*000000001~"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".edi", delete=False) as f:
        f.write(content)
        return f.name


@pytest.fixture
def mock_context():
    """Create mock FastMCP context."""
    import duckdb

    ctx = MagicMock()
    ctx.info = AsyncMock()

    # Create real DuckDB connection for testing
    conn = duckdb.connect(":memory:")
    ctx.request_context.lifespan_context = {
        "db": conn,
        "current_source": None,
    }
    return ctx


@pytest.mark.asyncio
async def test_import_edi_x12(sample_x12_file, mock_context):
    """Test import_edi tool with X12 file."""
    result = await import_edi(sample_x12_file, mock_context)

    assert result["source_type"] == "edi"
    assert result["row_count"] == 1
    assert len(result["columns"]) > 0

    # Verify context was updated
    assert mock_context.request_context.lifespan_context["current_source"]["type"] == "edi"


@pytest.mark.asyncio
async def test_import_edi_logs_info(sample_x12_file, mock_context):
    """Test that import_edi logs import progress."""
    await import_edi(sample_x12_file, mock_context)

    # Should have logged import start and completion
    assert mock_context.info.call_count >= 2


@pytest.mark.asyncio
async def test_import_edi_file_not_found(mock_context):
    """Test import_edi with non-existent file."""
    with pytest.raises(FileNotFoundError, match="EDI file not found"):
        await import_edi("/nonexistent/file.edi", mock_context)


@pytest.mark.asyncio
async def test_import_edi_invalid_format(mock_context):
    """Test import_edi with invalid EDI content."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".edi", delete=False) as f:
        f.write("This is not valid EDI content")
        invalid_path = f.name

    with pytest.raises(ValueError, match="Unsupported EDI format"):
        await import_edi(invalid_path, mock_context)


# --- Regression tests for Bug 3: missing context metadata in import_edi ---

@pytest.mark.asyncio
async def test_import_edi_sets_complete_context_metadata(sample_x12_file, mock_context):
    """Regression: import_edi must set deterministic_ready, row_key_strategy, row_key_columns.

    Previously import_edi only set {type, path, row_count} in current_source.
    All other adapters (CSV, Excel, fixed_width) set the full deterministic
    metadata so the agent knows it can use _source_row_num for row addressing.
    """
    await import_edi(sample_x12_file, mock_context)

    current_source = mock_context.request_context.lifespan_context["current_source"]

    assert current_source["type"] == "edi"
    assert current_source["path"] == sample_x12_file
    assert current_source["row_count"] == 1

    # These fields were missing before the fix
    assert "deterministic_ready" in current_source, (
        "current_source must contain 'deterministic_ready'"
    )
    assert current_source["deterministic_ready"] is True

    assert "row_key_strategy" in current_source, (
        "current_source must contain 'row_key_strategy'"
    )
    assert current_source["row_key_strategy"] == "source_row_num"

    assert "row_key_columns" in current_source, (
        "current_source must contain 'row_key_columns'"
    )
    assert current_source["row_key_columns"] == ["_source_row_num"]


@pytest.mark.asyncio
async def test_import_edi_schema_excludes_source_row_num(sample_x12_file, mock_context):
    """Regression: import_edi result columns must not expose _source_row_num."""
    result = await import_edi(sample_x12_file, mock_context)

    col_names = [c["name"] for c in result["columns"]]
    assert "_source_row_num" not in col_names, (
        "_source_row_num is internal and must not appear in the schema returned by import_edi"
    )
    # Business columns must still be present
    assert "po_number" in col_names
