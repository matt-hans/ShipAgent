"""Tests for import_file router, sniff_file, and import_fixed_width MCP tools."""

import json
from unittest.mock import AsyncMock

import duckdb
import pytest

import src.mcp.data_source.tools.import_tools as _import_mod
from src.mcp.data_source.tools.import_tools import (
    import_file,
    import_fixed_width,
    sniff_file,
)


@pytest.fixture(autouse=True)
def _allow_tmp(tmp_path, monkeypatch):
    """Add pytest tmp_path to allowed roots so path validation passes."""
    patched = list(_import_mod._ALLOWED_ROOTS) + [tmp_path.resolve()]
    monkeypatch.setattr(_import_mod, "_ALLOWED_ROOTS", patched)


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

    async def test_xlsx_by_extension(self, ctx, tmp_path):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["name", "city"])
        ws.append(["John", "Dallas"])
        xlsx_path = str(tmp_path / "orders.xlsx")
        wb.save(xlsx_path)
        result = await import_file(xlsx_path, ctx)
        assert result["row_count"] == 1
        assert result["source_type"] == "excel"

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

    async def test_fixed_width_auto_detect_success(self, ctx, tmp_file):
        """import_file for .fwf auto-detects column boundaries from header."""
        content = (
            "NAME                CITY           ST\n"
            "John Doe            Dallas         TX\n"
            "Jane Smith          Austin         TX\n"
        )
        path = tmp_file(content, "report.fwf")
        result = await import_file(path, ctx)
        assert result["row_count"] == 2
        assert result["source_type"] == "fixed_width"
        col_names = [c["name"] for c in result["columns"]]
        assert "NAME" in col_names
        assert "CITY" in col_names
        assert "ST" in col_names

    async def test_fixed_width_no_header_returns_preview(self, ctx, tmp_file):
        """import_file for .fwf without a detectable header returns a structured
        preview dict instead of raising, so the agent can call import_fixed_width.
        """
        # Single-line file: auto_detect_col_specs requires at least 2 lines
        path = tmp_file("data without header\n", "report.fwf")
        result = await import_file(path, ctx)
        assert result["status"] == "needs_column_specs"
        assert result["file_path"] == path
        assert "preview_lines" in result
        assert isinstance(result["preview_lines"], list)
        assert "message" in result

    async def test_fixed_width_legacy_mainframe_returns_preview(self, ctx, tmp_file):
        """Legacy mainframe HDR/DTL/TRL files return a structured preview response.

        The HDR line 'HDR20260220SHIPAGENT BATCH EXPORT V2.1' contains 'V2.1'
        (period in column name), so auto-detection correctly returns None.
        The tool must return preview data rather than raising so the agent can
        inspect the file layout and call import_fixed_width with explicit specs.
        """
        mainframe_content = (
            "HDR20260220SHIPAGENT BATCH EXPORT V2.1\n"
            "DTL0001ORD90001MITCHELL        SARAH           4820 RIVERSIDE DR\n"
            "DTL0002ORD90002THORNTON        JAMES           350 FIFTH AVE\n"
            "TRL00200000002RECORDS EXPORTED SUCCESSFULLY\n"
        )
        path = tmp_file(mainframe_content, "legacy.fwf")
        result = await import_file(path, ctx)

        assert result["status"] == "needs_column_specs", (
            f"Expected status='needs_column_specs', got: {result}"
        )
        assert result["file_path"] == path
        assert result["line_count"] == 4
        assert len(result["preview_lines"]) == 4
        # Preview must contain the actual file content for agent inspection
        assert "HDR20260220SHIPAGENT" in result["preview_lines"][0]
        assert "DTL0001" in result["preview_lines"][1]
        assert "TRL" in result["preview_lines"][3]
        # Message must guide the agent toward import_fixed_width
        assert "import_fixed_width" in result["message"]
        # current_source must NOT be updated (import did not complete)
        assert ctx.request_context.lifespan_context["current_source"] is None

    async def test_fixed_width_current_source_updated(self, ctx, tmp_file):
        """import_file for .fwf updates current_source after auto-detection."""
        content = (
            "ORDER CITY  \n"
            "A001  Dallas\n"
            "A002  Austin\n"
        )
        path = tmp_file(content, "report.fwf")
        await import_file(path, ctx)
        source = ctx.request_context.lifespan_context["current_source"]
        assert source["type"] == "fixed_width"
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

    async def test_file_not_found(self, ctx, tmp_path):
        nonexistent = str(tmp_path / "nonexistent.txt")
        with pytest.raises(FileNotFoundError):
            await sniff_file(nonexistent, ctx)


class TestPathTraversalProtection:
    """Verify that path validation blocks access to sensitive files."""

    async def test_sniff_blocks_outside_allowed(self, ctx, monkeypatch):
        """sniff_file must reject paths outside allowed roots."""
        # Reset allowed roots to only the project root (no tmp)
        monkeypatch.setattr(_import_mod, "_ALLOWED_ROOTS", [_import_mod._PROJECT_ROOT])
        with pytest.raises(PermissionError, match="outside allowed"):
            await sniff_file("/etc/passwd", ctx)

    async def test_sniff_blocks_env_file(self, ctx, tmp_file):
        """sniff_file must reject .env files even within allowed dirs."""
        path = tmp_file("SECRET=abc", ".env")
        with pytest.raises(PermissionError, match="sensitive"):
            await sniff_file(path, ctx)

    async def test_sniff_blocks_git_dir(self, ctx, tmp_path):
        """sniff_file must reject paths inside .git directories."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        target = git_dir / "config"
        target.write_text("[core]")
        with pytest.raises(PermissionError, match="restricted"):
            await sniff_file(str(target), ctx)

    async def test_import_file_blocks_outside(self, ctx, monkeypatch):
        """import_file must also validate paths."""
        monkeypatch.setattr(_import_mod, "_ALLOWED_ROOTS", [_import_mod._PROJECT_ROOT])
        with pytest.raises(PermissionError, match="outside allowed"):
            await import_file("/etc/passwd", ctx)


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

    async def test_current_source_updated(self, ctx, tmp_file):
        content = "John Doe            Dallas"
        path = tmp_file(content, "report.fwf")
        await import_fixed_width(path, ctx, col_specs=[(0, 20), (20, 26)])
        source = ctx.request_context.lifespan_context["current_source"]
        assert source["type"] == "fixed_width"
        assert source["path"] == path
