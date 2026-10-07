"""Legacy file-entry tools apply the existing canonical source path boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import duckdb
import pytest
from openpyxl import Workbook

from src.mcp.data_source.tools import import_tools


@pytest.mark.parametrize("tool", ["import_csv", "import_excel", "list_sheets"])
@pytest.mark.parametrize("symlink", [False, True])
async def test_legacy_import_denies_outside_root_before_opening(
    tool, symlink, tmp_path, monkeypatch
):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / ("outside.csv" if tool == "import_csv" else "outside.xlsx")
    if tool == "import_csv":
        outside.write_text("value\nHARMLESS-OUTSIDE-CANARY\n")
    else:
        workbook = Workbook()
        workbook.active.append(["HARMLESS-OUTSIDE-CANARY"])
        workbook.save(outside)
        workbook.close()
    supplied = outside
    if symlink:
        supplied = allowed / outside.name
        supplied.symlink_to(outside)
    monkeypatch.setattr(import_tools, "_ALLOWED_ROOTS", [allowed])
    adapter_name = "CSVAdapter" if tool == "import_csv" else "ExcelAdapter"
    adapter = Mock(wraps=getattr(import_tools, adapter_name))
    monkeypatch.setattr(import_tools, adapter_name, adapter)
    db = duckdb.connect(":memory:")
    ctx = SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context={"db": db, "current_source": None}
        ),
        info=AsyncMock(),
    )
    try:
        with pytest.raises(PermissionError, match="outside allowed"):
            await getattr(import_tools, tool)(file_path=str(supplied), ctx=ctx)
        adapter.assert_not_called()
        assert db.execute("SHOW TABLES").fetchall() == []
    finally:
        db.close()
