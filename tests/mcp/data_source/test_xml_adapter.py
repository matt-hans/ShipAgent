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
