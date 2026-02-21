"""Integration tests for the universal data ingestion pipeline.

Tests the full flow: file → adapter → DuckDB → schema → column mapping compatibility.
"""

import json
import textwrap

import duckdb
import pytest

from src.mcp.data_source.adapters.csv_adapter import DelimitedAdapter
from src.mcp.data_source.adapters.fixed_width_adapter import FixedWidthAdapter
from src.mcp.data_source.adapters.json_adapter import JSONAdapter
from src.mcp.data_source.adapters.xml_adapter import XMLAdapter
from src.services.column_mapping import auto_map_columns


@pytest.fixture()
def conn():
    """Create a fresh in-memory DuckDB connection."""
    c = duckdb.connect(":memory:")
    yield c
    c.close()


@pytest.fixture()
def tmp_file(tmp_path):
    """Helper to write content to a temp file and return its path."""
    def _create(content, name):
        p = tmp_path / name
        if isinstance(content, (dict, list)):
            p.write_text(json.dumps(content))
        else:
            p.write_text(textwrap.dedent(content).strip())
        return str(p)
    return _create


SHIPPING_JSON = [
    {
        "orderId": "ORD-001",
        "shipTo": {
            "name": "John Doe",
            "addressLine1": "123 Main St",
            "city": "Dallas",
            "state": "TX",
            "postalCode": "75201",
            "country": "US",
        },
        "weight": 5.0,
        "service": "UPS Ground",
    },
]

SHIPPING_XML = """\
<?xml version="1.0"?>
<Shipments>
  <Shipment>
    <OrderID>ORD-001</OrderID>
    <RecipientName>John Doe</RecipientName>
    <AddressLine1>123 Main St</AddressLine1>
    <City>Dallas</City>
    <State>TX</State>
    <PostalCode>75201</PostalCode>
    <Country>US</Country>
    <Weight>5.0</Weight>
  </Shipment>
  <Shipment>
    <OrderID>ORD-002</OrderID>
    <RecipientName>Jane Smith</RecipientName>
    <AddressLine1>456 Oak Ave</AddressLine1>
    <City>Houston</City>
    <State>TX</State>
    <PostalCode>77001</PostalCode>
    <Country>US</Country>
    <Weight>3.0</Weight>
  </Shipment>
</Shipments>
"""


class TestColumnMappingCompatibility:
    """Verify that flattened columns from new formats hit auto-map rules."""

    def test_json_columns_auto_map(self, conn, tmp_file):
        """Nested JSON shipTo_name should map to shipTo.name."""
        path = tmp_file(SHIPPING_JSON, "orders.json")
        adapter = JSONAdapter()
        result = adapter.import_data(conn, file_path=path)
        col_names = [c.name for c in result.columns]

        mapping = auto_map_columns(col_names)
        # shipTo_name → tokens {shipto, name} → matches shipTo.name rule
        assert "shipTo.name" in mapping
        assert "shipTo.city" in mapping

    def test_xml_columns_auto_map(self, conn, tmp_file):
        """XML element names should map to UPS fields."""
        path = tmp_file(SHIPPING_XML, "orders.xml")
        adapter = XMLAdapter()
        result = adapter.import_data(conn, file_path=path)
        col_names = [c.name for c in result.columns]

        mapping = auto_map_columns(col_names)
        # City → tokens {city} → matches shipTo.city rule
        assert "shipTo.city" in mapping
        assert len(mapping) >= 3  # At least city, state, postal

    def test_tsv_same_schema_as_csv(self, conn, tmp_file):
        """TSV import produces same column set as equivalent CSV."""
        csv_path = tmp_file("name,city,state\nJohn,Dallas,TX", "data.csv")
        tsv_path = tmp_file("name\tcity\tstate\nJohn\tDallas\tTX", "data.tsv")

        adapter = DelimitedAdapter()
        csv_result = adapter.import_data(conn, file_path=csv_path)
        csv_cols = {c.name for c in csv_result.columns}

        # Need a fresh connection for the second import (same table name)
        conn2 = duckdb.connect(":memory:")
        try:
            tsv_result = adapter.import_data(conn2, file_path=tsv_path, delimiter="\t")
            tsv_cols = {c.name for c in tsv_result.columns}
        finally:
            conn2.close()

        assert csv_cols == tsv_cols

    def test_fixed_width_columns_auto_map(self, conn, tmp_file):
        """Fixed-width columns with shipping names should auto-map."""
        content = (
            "John Doe       Dallas         TX75201\n"
            "Jane Smith     Houston        TX77001\n"
        )
        path = tmp_file(content, "data.fwf")
        adapter = FixedWidthAdapter()
        result = adapter.import_data(
            conn,
            file_path=path,
            col_specs=[(0, 15), (15, 30), (30, 32), (32, 37)],
            names=["name", "city", "state", "postal_code"],
            header=False,
        )
        col_names = [c.name for c in result.columns]

        mapping = auto_map_columns(col_names)
        assert "shipTo.name" in mapping
        assert "shipTo.city" in mapping
        assert "shipTo.postalCode" in mapping


class TestEndToEndPipeline:
    """Test the full import → query → verify pipeline."""

    def test_json_import_queryable(self, conn, tmp_file):
        """JSON data should be queryable via SQL after import."""
        path = tmp_file(SHIPPING_JSON, "orders.json")
        JSONAdapter().import_data(conn, file_path=path)
        rows = conn.execute("SELECT * FROM imported_data").fetchall()
        assert len(rows) == 1

    def test_xml_import_queryable(self, conn, tmp_file):
        """XML data should be queryable via SQL after import."""
        path = tmp_file(SHIPPING_XML, "orders.xml")
        XMLAdapter().import_data(conn, file_path=path)
        rows = conn.execute("SELECT * FROM imported_data").fetchall()
        assert len(rows) == 2

    def test_json_source_row_num_in_table(self, conn, tmp_file):
        """JSON import should include _source_row_num in the DuckDB table."""
        path = tmp_file(SHIPPING_JSON, "orders.json")
        JSONAdapter().import_data(conn, file_path=path)

        # _source_row_num is in the table but excluded from ImportResult.columns
        row = conn.execute(
            "SELECT _source_row_num FROM imported_data"
        ).fetchone()
        assert row is not None
        assert row[0] == 1

    def test_xml_source_row_num_in_table(self, conn, tmp_file):
        """XML import should include _source_row_num in the DuckDB table."""
        path = tmp_file(SHIPPING_XML, "orders.xml")
        XMLAdapter().import_data(conn, file_path=path)

        rows = conn.execute(
            "SELECT _source_row_num FROM imported_data ORDER BY _source_row_num"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == 1
        assert rows[1][0] == 2

    def test_multi_row_json_queryable(self, conn, tmp_file):
        """Multiple JSON records should all be queryable."""
        records = [
            {"name": "Alice", "city": "Austin", "state": "TX"},
            {"name": "Bob", "city": "Boston", "state": "MA"},
            {"name": "Carol", "city": "Chicago", "state": "IL"},
        ]
        path = tmp_file(records, "multi.json")
        result = JSONAdapter().import_data(conn, file_path=path)
        assert result.row_count == 3

        rows = conn.execute(
            "SELECT name FROM imported_data ORDER BY name"
        ).fetchall()
        assert [r[0] for r in rows] == ["Alice", "Bob", "Carol"]

    def test_delimited_pipe_import_queryable(self, conn, tmp_file):
        """Pipe-delimited file should import and be queryable."""
        content = "name|city|state\nJohn|Dallas|TX\nJane|Houston|TX"
        path = tmp_file(content, "data.txt")
        adapter = DelimitedAdapter()
        result = adapter.import_data(conn, file_path=path, delimiter="|")
        assert result.row_count == 2

        rows = conn.execute(
            "SELECT city FROM imported_data ORDER BY city"
        ).fetchall()
        assert [r[0] for r in rows] == ["Dallas", "Houston"]
