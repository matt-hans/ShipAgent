"""Tests for import_file router, sniff_file, and import_fixed_width MCP tools."""

import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import duckdb
import pytest

import src.mcp.data_source.tools.import_tools as _import_mod
from src.mcp.data_source.tools.import_tools import import_file, sniff_file, import_fixed_width


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

    async def test_fixed_width_via_router_raises(self, ctx, tmp_file):
        """import_file for .fwf should tell user to use sniff_file + import_fixed_width."""
        path = tmp_file("data", "report.fwf")
        with pytest.raises(ValueError, match="sniff_file"):
            await import_file(path, ctx)


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
