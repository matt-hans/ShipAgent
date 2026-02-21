"""Tests for FixedWidthAdapter (pure Python string slicing)."""

import duckdb
import pytest

from src.mcp.data_source.adapters.fixed_width_adapter import (
    FixedWidthAdapter,
    auto_detect_col_specs,
)


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


class TestAutoDetectColSpecs:
    """Tests for the auto_detect_col_specs utility function."""

    def test_basic_three_column_header(self):
        lines = [
            "NAME                CITY           ST\n",
            "John Doe            Dallas         TX\n",
            "Jane Smith          Austin         TX\n",
        ]
        result = auto_detect_col_specs(lines)
        assert result is not None
        specs, names = result
        assert len(specs) == 3
        assert names == ["NAME", "CITY", "ST"]
        # Verify specs are increasing and non-overlapping
        for i in range(len(specs) - 1):
            assert specs[i][1] <= specs[i + 1][0]

    def test_returns_none_for_single_line(self):
        """Cannot auto-detect with only a header and no data lines."""
        result = auto_detect_col_specs(["ONLY ONE LINE\n"])
        assert result is None

    def test_returns_none_for_empty_list(self):
        result = auto_detect_col_specs([])
        assert result is None

    def test_returns_none_when_one_column_in_header(self):
        """A header with one word gives fewer than 2 columns."""
        lines = [
            "NOSPACES\n",
            "12345678\n",
        ]
        result = auto_detect_col_specs(lines)
        assert result is None

    def test_data_with_embedded_spaces(self):
        """Column data containing spaces does not fragment column boundaries.

        The header-word-position algorithm uses only the header line to
        determine column starts, so embedded spaces in data values (like
        'John Doe' in a NAME column) do not cause false splits.
        """
        lines = [
            "NAME                CITY           ST\n",
            "John Doe            Dallas         TX\n",
            "Jane Smith          Austin         TX\n",
        ]
        result = auto_detect_col_specs(lines)
        assert result is not None
        _, names = result
        # Must return exactly the 3 header-word names, not fragments
        assert names == ["NAME", "CITY", "ST"]

    def test_shipments_domestic_style(self):
        """Simulate the shipments_domestic.fwf header structure."""
        lines = [
            "ORDER_NUM RECIPIENT_NAME          COMPANY   \n",
            "ORD-2001  Sarah Mitchell                    \n",
            "ORD-2002  James Thornton          TLG       \n",
        ]
        result = auto_detect_col_specs(lines)
        assert result is not None
        specs, names = result
        assert len(specs) >= 2
        assert "ORDER_NUM" in names
        assert "RECIPIENT_NAME" in names

    def test_names_are_stripped(self):
        """Column names must be stripped of surrounding whitespace."""
        lines = [
            "FIRST  SECOND\n",
            "AAAAA  BBBBBB\n",
            "CCCCC  DDDDDD\n",
        ]
        result = auto_detect_col_specs(lines)
        assert result is not None
        _, names = result
        for name in names:
            assert name == name.strip()
            assert len(name) > 0

    def test_no_empty_names(self):
        """All detected column names must be non-empty strings."""
        lines = [
            "COL1  COL2  COL3\n",
            "AAAA  BBBB  CCCC\n",
            "DDDD  EEEE  FFFF\n",
        ]
        result = auto_detect_col_specs(lines)
        assert result is not None
        _, names = result
        assert all(n for n in names)

    def test_end_of_line_column(self):
        """Last column extends to the end of the longest line."""
        lines = [
            "A   B\n",
            "111 222\n",
        ]
        result = auto_detect_col_specs(lines)
        assert result is not None
        specs, names = result
        assert len(specs) == 2
        assert names[0] == "A"
        assert names[1] == "B"

    def test_rejects_legacy_mainframe_header(self):
        """Header lines with record-tag tokens like 'V2.1' return None."""
        lines = [
            "HDR20260220SHIPAGENT BATCH EXPORT V2.1\n",
            "DTL0001ORD90001MITCHELL        SARAH\n",
            "DTL0002ORD90002THORNTON        JAMES\n",
        ]
        result = auto_detect_col_specs(lines)
        assert result is None

    def test_rejects_non_identifier_column_names(self):
        """Column names containing periods or other non-identifier chars return None."""
        lines = [
            "COL.1 COL.2\n",
            "AAAAA BBBBB\n",
        ]
        result = auto_detect_col_specs(lines)
        assert result is None

    def test_roundtrip_with_adapter(self, tmp_path):
        """Auto-detected specs can be fed directly into FixedWidthAdapter."""
        import duckdb as _duckdb

        content = (
            "ORDER CITY   ST\n"
            "A001  Dallas TX\n"
            "A002  Austin TX\n"
        )
        lines = content.splitlines(keepends=True)
        result = auto_detect_col_specs(lines)
        assert result is not None
        specs, names = result

        fwf_path = tmp_path / "test.fwf"
        fwf_path.write_text(content)

        conn = _duckdb.connect(":memory:")
        adapter = FixedWidthAdapter()
        import_result = adapter.import_data(
            conn,
            file_path=str(fwf_path),
            col_specs=specs,
            names=names,
            header=True,
        )
        assert import_result.row_count == 2
        col_names = [c.name for c in import_result.columns]
        assert "ORDER" in col_names
        assert "CITY" in col_names
        conn.close()
