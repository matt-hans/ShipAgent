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

    # --- Tests for the space-fraction gap detection algorithm ---

    def test_narrow_numeric_columns_no_bleeding(self):
        """Narrow numeric columns narrower than their header word don't bleed.

        Core regression test for the original bug: WT_LBS header is 6 chars
        wide but '32.5' data is only 4 chars.  Old algorithm bled 2 chars
        of LEN data into WT_LBS.  New algorithm detects the gap at positions
        154-155 and ends WT_LBS there.
        """
        lines = [
            "WT_LBS LEN WID HGT\n",
            "  2.3  12   8   6\n",
            "  0.8   0   0   0\n",
            " 32.5  24  18  16\n",
            "  4.2  16  12   8\n",
            "  1.1  10   7   3\n",
        ]
        result = auto_detect_col_specs(lines)
        assert result is not None
        specs, names = result
        assert names == ["WT_LBS", "LEN", "WID", "HGT"]
        data_lines = [ln.rstrip("\n\r") for ln in lines[1:] if ln.strip()]
        # Extract WT_LBS values: must be numeric strings, no trailing digits from LEN
        wt_idx = names.index("WT_LBS")
        wt_s, wt_e = specs[wt_idx]
        wt_values = [dl[wt_s:wt_e].strip() for dl in data_lines]
        assert all(v.replace(".", "").isdigit() for v in wt_values), (
            f"WT_LBS values contain non-numeric chars: {wt_values}"
        )
        assert "32.5" in wt_values, "Expected 32.5 in WT_LBS column"

    def test_multi_word_service_values_stay_together(self):
        """Multi-word service codes like '3 Day Select' don't get split.

        The internal space inside 'Next Day Air' (at the 5th char position)
        must NOT be misidentified as a column separator.
        """
        lines = [
            "WT_LBS SERVICE          PKG_TYPE\n",
            "   2.3 Ground           Customer Supplied\n",
            "   0.8 Next Day Air     UPS Letter\n",
            "  32.5 Ground           Customer Supplied\n",
            "   6.8 3 Day Select     Customer Supplied\n",
            "   4.2 2nd Day Air      Customer Supplied\n",
            "   1.1 Ground           Customer Supplied\n",
            "   0.5 Ground           UPS Letter\n",
            "   8.4 2nd Day Air      Customer Supplied\n",
            "   3.6 Ground           Customer Supplied\n",
            "  22.0 Next Day Air     Customer Supplied\n",
        ]
        result = auto_detect_col_specs(lines)
        assert result is not None
        specs, names = result
        assert "SERVICE" in names
        svc_idx = names.index("SERVICE")
        svc_s, svc_e = specs[svc_idx]
        data_lines = [ln.rstrip("\n\r") for ln in lines[1:] if ln.strip()]
        svc_values = [dl[svc_s:svc_e].strip() for dl in data_lines]
        assert "Next Day Air" in svc_values, (
            f"Expected 'Next Day Air' in SERVICE column; got: {svc_values}"
        )
        assert "3 Day Select" in svc_values, (
            f"Expected '3 Day Select' in SERVICE column; got: {svc_values}"
        )

    def test_domestic_fwf_file(self, tmp_path):
        """Full-file test against shipments_domestic.fwf.

        Verifies that all 17 columns are correctly detected and critical
        shipping fields (WT_LBS, LEN, WID, HGT, SERVICE, PKG_TYPE) contain
        the expected values without bleeding.
        """
        import duckdb as _duckdb
        from pathlib import Path

        fwf_path = Path("test_data/shipments_domestic.fwf")
        if not fwf_path.exists():
            import pytest
            pytest.skip("test_data/shipments_domestic.fwf not found")

        with open(fwf_path, encoding="utf-8") as f:
            lines = f.readlines()

        result = auto_detect_col_specs(lines)
        assert result is not None, "auto_detect_col_specs returned None for domestic FWF"
        specs, names = result
        assert len(names) == 17, f"Expected 17 columns, got {len(names)}: {names}"

        expected_names = [
            "ORDER_NUM", "RECIPIENT_NAME", "COMPANY", "PHONE",
            "ADDRESS_LINE_1", "ADDRESS_LINE_2", "CITY", "ST", "ZIP",
            "WT_LBS", "LEN", "WID", "HGT", "SERVICE",
            "PKG_TYPE", "DESCRIPTION", "VALUE",
        ]
        assert names == expected_names, f"Column names mismatch: {names}"

        data_lines = [ln.rstrip("\n\r") for ln in lines[1:] if ln.strip()]

        # WT_LBS: verify row 6 (ORD-2006, 32.5 lbs) extracts exactly '32.5'
        wt_idx = names.index("WT_LBS")
        wt_s, wt_e = specs[wt_idx]
        row6_wt = data_lines[5][wt_s:wt_e].strip()
        assert row6_wt == "32.5", (
            f"WT_LBS for row 6 expected '32.5', got {row6_wt!r}"
        )

        # LEN: verify row 6 (24 inches) extracts exactly '24'
        len_idx = names.index("LEN")
        len_s, len_e = specs[len_idx]
        row6_len = data_lines[5][len_s:len_e].strip()
        assert row6_len == "24", (
            f"LEN for row 6 expected '24', got {row6_len!r}"
        )

        # WID: verify row 6 (18 inches)
        wid_idx = names.index("WID")
        wid_s, wid_e = specs[wid_idx]
        row6_wid = data_lines[5][wid_s:wid_e].strip()
        assert row6_wid == "18", (
            f"WID for row 6 expected '18', got {row6_wid!r}"
        )

        # HGT: verify row 6 (16 inches)
        hgt_idx = names.index("HGT")
        hgt_s, hgt_e = specs[hgt_idx]
        row6_hgt = data_lines[5][hgt_s:hgt_e].strip()
        assert row6_hgt == "16", (
            f"HGT for row 6 expected '16', got {row6_hgt!r}"
        )

        # SERVICE: row 2 is 'Next Day Air', row 7 is '3 Day Select'
        svc_idx = names.index("SERVICE")
        svc_s, svc_e = specs[svc_idx]
        row2_svc = data_lines[1][svc_s:svc_e].strip()
        assert row2_svc == "Next Day Air", (
            f"SERVICE row 2 expected 'Next Day Air', got {row2_svc!r}"
        )
        row7_svc = data_lines[6][svc_s:svc_e].strip()
        assert row7_svc == "3 Day Select", (
            f"SERVICE row 7 expected '3 Day Select', got {row7_svc!r}"
        )

        # PKG_TYPE: 'Customer Supplied' must not be truncated
        pkg_idx = names.index("PKG_TYPE")
        pkg_s, pkg_e = specs[pkg_idx]
        row1_pkg = data_lines[0][pkg_s:pkg_e].strip()
        assert row1_pkg == "Customer Supplied", (
            f"PKG_TYPE row 1 expected 'Customer Supplied', got {row1_pkg!r}"
        )

        # Round-trip: import via adapter and verify row count
        conn = _duckdb.connect(":memory:")
        adapter = FixedWidthAdapter()
        import_result = adapter.import_data(
            conn, file_path=str(fwf_path),
            col_specs=specs, names=names, header=True,
        )
        assert import_result.row_count == 20, (
            f"Expected 20 rows, got {import_result.row_count}"
        )
        conn.close()

    def test_boolean_column_before_header_word(self):
        """1-char Y/N column whose data sits just before the header word.

        In inventory-style files, HAZMAT data 'N'/'Y' appears 1 position
        before the HAZMAT header word begins.  The algorithm extends the
        range start left to the header word start.
        """
        lines = [
            "SKU     HAZMAT FRAGILE\n",
            "WH-001  N      Y\n",
            "WH-002  Y      N\n",
            "WH-003  N      N\n",
            "WH-004  Y      Y\n",
            "WH-005  N      N\n",
            "WH-006  N      Y\n",
            "WH-007  Y      N\n",
            "WH-008  N      N\n",
            "WH-009  N      Y\n",
            "WH-010  Y      N\n",
        ]
        result = auto_detect_col_specs(lines)
        assert result is not None
        specs, names = result
        assert "HAZMAT" in names
        assert "FRAGILE" in names
        data_lines = [ln.rstrip("\n\r") for ln in lines[1:] if ln.strip()]
        haz_idx = names.index("HAZMAT")
        haz_s, haz_e = specs[haz_idx]
        haz_values = [dl[haz_s:haz_e].strip() for dl in data_lines]
        assert set(haz_values) <= {"N", "Y"}, (
            f"HAZMAT values should be N/Y only, got: {haz_values}"
        )

    def test_numeric_columns_get_numeric_duckdb_types(self):
        """FWF numeric columns must become DOUBLE/BIGINT, not VARCHAR.

        Regression test for the core bug: all FWF values were strings,
        causing DuckDB to assign VARCHAR to numeric columns, which broke
        SQL comparisons like WHERE WT_LBS > 20.
        """
        import duckdb as _duckdb
        from pathlib import Path

        fwf_path = Path("test_data/shipments_domestic.fwf")
        if not fwf_path.exists():
            import pytest
            pytest.skip("test_data/shipments_domestic.fwf not found")

        with open(fwf_path, encoding="utf-8") as f:
            lines = f.readlines()

        specs, names = auto_detect_col_specs(lines)
        conn = _duckdb.connect(":memory:")
        adapter = FixedWidthAdapter()
        adapter.import_data(conn, str(fwf_path), col_specs=specs, names=names, header=True)

        schema = conn.execute("DESCRIBE imported_data").fetchall()
        type_map = {col[0]: col[1] for col in schema}

        # Numeric columns must not be VARCHAR
        assert type_map["WT_LBS"] == "DOUBLE", f"WT_LBS should be DOUBLE, got {type_map['WT_LBS']}"
        assert type_map["LEN"] == "BIGINT", f"LEN should be BIGINT, got {type_map['LEN']}"
        assert type_map["WID"] == "BIGINT", f"WID should be BIGINT, got {type_map['WID']}"
        assert type_map["HGT"] == "BIGINT", f"HGT should be BIGINT, got {type_map['HGT']}"
        assert type_map["VALUE"] == "DOUBLE", f"VALUE should be DOUBLE, got {type_map['VALUE']}"

        # Text columns must remain VARCHAR
        assert type_map["RECIPIENT_NAME"] == "VARCHAR"
        assert type_map["CITY"] == "VARCHAR"
        assert type_map["SERVICE"] == "VARCHAR"

        # Numeric comparisons must work without CAST
        rows = conn.execute("SELECT COUNT(*) FROM imported_data WHERE WT_LBS > 20").fetchone()
        assert rows[0] > 0, "No rows found with WT_LBS > 20 — numeric comparison broken"
        conn.close()

    def test_uses_all_data_lines_not_just_first_five(self):
        """Space-fraction analysis uses ALL data lines, not just first 5.

        Old algorithm only sampled lines[1:6].  New algorithm uses all data
        lines so edge-case rows beyond row 5 influence column boundary detection.
        """
        # File with 12 data rows; row 11 is the only one with a longer value
        # in the last column.
        lines = [
            "CODE VALUE\n",
            "A001  1.1\n",
            "A002  2.2\n",
            "A003  3.3\n",
            "A004  4.4\n",
            "A005  5.5\n",
            "A006  6.6\n",
            "A007  7.7\n",
            "A008  8.8\n",
            "A009  9.9\n",
            "A010 10.0\n",
            "A011 11.1\n",
            "A012 12.2\n",
        ]
        result = auto_detect_col_specs(lines)
        assert result is not None
        specs, names = result
        assert "CODE" in names
        assert "VALUE" in names
        # All 12 rows must be importable with detected specs
        data_lines = [ln.rstrip("\n\r") for ln in lines[1:] if ln.strip()]
        assert len(data_lines) == 12
        val_idx = names.index("VALUE")
        val_s, val_e = specs[val_idx]
        last_val = data_lines[-1][val_s:val_e].strip()
        assert last_val == "12.2", (
            f"Last VALUE row expected '12.2', got {last_val!r}"
        )
