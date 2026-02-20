"""Tests for DelimitedAdapter (CSV, TSV, SSV, pipe-delimited)."""

import textwrap
from pathlib import Path

import duckdb
import pytest

from src.mcp.data_source.adapters.csv_adapter import DelimitedAdapter


@pytest.fixture()
def conn():
    c = duckdb.connect(":memory:")
    yield c
    c.close()


@pytest.fixture()
def tmp_file(tmp_path):
    """Helper to create temp files with given content."""
    def _create(content: str, name: str = "data.csv") -> str:
        p = tmp_path / name
        p.write_text(textwrap.dedent(content).strip())
        return str(p)
    return _create


class TestDelimitedAdapter:
    def test_source_type(self):
        adapter = DelimitedAdapter()
        assert adapter.source_type == "delimited"

    def test_csv_import(self, conn, tmp_file):
        path = tmp_file("name,city\nJohn,Dallas\nJane,Austin")
        adapter = DelimitedAdapter()
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 2
        assert result.source_type == "delimited"

    def test_tsv_import(self, conn, tmp_file):
        path = tmp_file("name\tcity\nJohn\tDallas\nJane\tAustin", name="data.tsv")
        adapter = DelimitedAdapter()
        result = adapter.import_data(conn, file_path=path, delimiter="\t")
        assert result.row_count == 2

    def test_pipe_delimited(self, conn, tmp_file):
        path = tmp_file("name|city\nJohn|Dallas\nJane|Austin", name="data.txt")
        adapter = DelimitedAdapter()
        result = adapter.import_data(conn, file_path=path, delimiter="|")
        assert result.row_count == 2

    def test_semicolon_delimited(self, conn, tmp_file):
        path = tmp_file("name;city\nJohn;Dallas\nJane;Austin", name="data.ssv")
        adapter = DelimitedAdapter()
        result = adapter.import_data(conn, file_path=path, delimiter=";")
        assert result.row_count == 2

    def test_auto_detect_tsv(self, conn, tmp_file):
        """DuckDB auto-detect should handle TSV without explicit delimiter."""
        path = tmp_file("name\tcity\nJohn\tDallas", name="data.tsv")
        adapter = DelimitedAdapter()
        # Don't pass delimiter — rely on auto-detect
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 1
        col_names = [c.name for c in result.columns]
        assert "name" in col_names
        assert "city" in col_names

    def test_detected_delimiter_stored(self, conn, tmp_file):
        """Adapter stores detected_delimiter for write-back."""
        path = tmp_file("name\tcity\nJohn\tDallas", name="data.tsv")
        adapter = DelimitedAdapter()
        adapter.import_data(conn, file_path=path, delimiter="\t")
        assert adapter.detected_delimiter == "\t"

    def test_backward_compat_csv_alias(self):
        """CSVAdapter still importable as alias."""
        from src.mcp.data_source.adapters.csv_adapter import CSVAdapter
        adapter = CSVAdapter()
        assert adapter.source_type == "delimited"


class TestDelimitedAdapterColumnCount:
    """Test ambiguity detection for possible fixed-width files."""

    def test_single_column_warns(self, conn, tmp_file):
        """If only 1 column detected, import should add a warning."""
        path = tmp_file("JOHN DOE       123 MAIN ST     DALLAS", name="report.dat")
        adapter = DelimitedAdapter()
        result = adapter.import_data(conn, file_path=path, header=False)
        # With no delimiter found, DuckDB may produce 1 column
        # The adapter should flag this as potentially ambiguous
        has_warning = any("single column" in w.lower() or "1 column" in w.lower() for w in result.warnings)
        if result.row_count > 0 and len(result.columns) == 1:
            assert has_warning
