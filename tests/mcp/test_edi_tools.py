"""Test EDI MCP tools."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from src.mcp.data_source.tools import edi_tools, import_tools
from src.mcp.data_source.tools.edi_tools import import_edi


@pytest.fixture(autouse=True)
def allowed_test_files(tmp_path, monkeypatch):
    monkeypatch.setattr(import_tools, "_ALLOWED_ROOTS", [tmp_path])


@pytest.fixture
def sample_x12_file(tmp_path):
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

    path = tmp_path / "synthetic.edi"
    path.write_text(content)
    return str(path)


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
    yield ctx
    conn.close()


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
async def test_import_edi_file_not_found(mock_context, tmp_path):
    """Test import_edi with non-existent file."""
    with pytest.raises(FileNotFoundError, match="EDI file not found"):
        await import_edi(str(tmp_path / "nonexistent.edi"), mock_context)


@pytest.mark.asyncio
async def test_import_edi_invalid_format(mock_context, tmp_path):
    """Test import_edi with invalid EDI content."""
    invalid_path = tmp_path / "invalid.edi"
    invalid_path.write_text("This is not valid EDI content")

    with pytest.raises(ValueError, match="Unsupported EDI format"):
        await import_edi(str(invalid_path), mock_context)


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


@pytest.mark.parametrize("kind", ["outside", "traversal", "symlink", "sensitive_name", "sensitive_dir"])
@pytest.mark.asyncio
async def test_direct_edi_denies_forbidden_paths_before_read_or_log(
    kind, sample_x12_file, mock_context, tmp_path, monkeypatch
):
    allowed = tmp_path / "uploads"
    allowed.mkdir()
    outside = Path(sample_x12_file)
    supplied = outside
    if kind == "traversal":
        supplied = allowed / ".." / outside.name
    elif kind == "symlink":
        supplied = allowed / "escape.edi"
        supplied.symlink_to(outside)
    elif kind in {"sensitive_name", "sensitive_dir"}:
        supplied = allowed / (".env" if kind == "sensitive_name" else ".ssh/orders.edi")
        supplied.parent.mkdir(parents=True, exist_ok=True)
        supplied.write_bytes(outside.read_bytes())
    monkeypatch.setattr(import_tools, "_ALLOWED_ROOTS", [allowed])
    adapter = Mock(wraps=edi_tools.EDIAdapter)
    monkeypatch.setattr(edi_tools, "EDIAdapter", adapter)
    with pytest.raises(PermissionError):
        await import_edi(str(supplied), mock_context)
    adapter.assert_not_called()
    mock_context.info.assert_not_awaited()
    assert mock_context.request_context.lifespan_context["current_source"] is None
