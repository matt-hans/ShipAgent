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
