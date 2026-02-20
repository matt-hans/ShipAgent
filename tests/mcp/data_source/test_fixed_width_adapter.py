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

    def test_col_specs_required(self, conn, fwf_file):
        path = fwf_file(SAMPLE_FWF)
        adapter = FixedWidthAdapter()
        with pytest.raises(ValueError, match="col_specs required"):
            adapter.import_data(conn, file_path=path)

    def test_metadata_after_import(self, conn, fwf_file):
        path = fwf_file(SAMPLE_FWF)
        adapter = FixedWidthAdapter()
        adapter.import_data(
            conn, file_path=path,
            col_specs=[(0, 20), (20, 35), (35, 37)],
            names=["name", "city", "state"],
        )
        meta = adapter.get_metadata(conn)
        assert meta["row_count"] == 3
        assert meta["source_type"] == "fixed_width"

    def test_metadata_before_import(self, conn):
        adapter = FixedWidthAdapter()
        meta = adapter.get_metadata(conn)
        assert "error" in meta
