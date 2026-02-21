"""Tests for commodity import and query tools."""

import duckdb


class TestCommodityImport:
    """Verify commodity data can be imported as auxiliary table."""

    def setup_method(self):
        """Set up in-memory DuckDB with simulated order data."""
        self.db = duckdb.connect(":memory:")
        self.db.execute("""
            CREATE TABLE imported_data (
                order_id INTEGER, customer_name VARCHAR, ship_to_country VARCHAR
            )
        """)
        self.db.execute("""
            INSERT INTO imported_data VALUES
            (1001, 'Jane Doe', 'CA'),
            (1002, 'Carlos Garcia', 'MX')
        """)

    def teardown_method(self):
        """Close DuckDB connection."""
        self.db.close()

    def test_import_commodities_creates_table(self):
        """Import creates imported_commodities table with correct data."""
        from src.mcp.data_source.tools.commodity_tools import import_commodities_sync

        result = import_commodities_sync(
            self.db,
            [
                {"order_id": 1001, "description": "Coffee", "commodity_code": "090111",
                 "origin_country": "CO", "quantity": 5, "unit_value": "30.00"},
                {"order_id": 1001, "description": "Tea", "commodity_code": "090210",
                 "origin_country": "CN", "quantity": 10, "unit_value": "15.00"},
                {"order_id": 1002, "description": "Laptop", "commodity_code": "847130",
                 "origin_country": "US", "quantity": 1, "unit_value": "999.00"},
            ],
        )
        assert result["row_count"] == 3
        assert result["table_name"] == "imported_commodities"
        tables = [r[0] for r in self.db.execute("SHOW TABLES").fetchall()]
        assert "imported_commodities" in tables

    def test_import_commodities_replaces_previous(self):
        """Re-importing replaces existing commodities, not appends."""
        from src.mcp.data_source.tools.commodity_tools import import_commodities_sync

        import_commodities_sync(self.db, [
            {"order_id": 1, "description": "Old", "commodity_code": "000000",
             "origin_country": "US", "quantity": 1, "unit_value": "1.00"},
        ])
        import_commodities_sync(self.db, [
            {"order_id": 2, "description": "New", "commodity_code": "111111",
             "origin_country": "US", "quantity": 1, "unit_value": "2.00"},
        ])
        count = self.db.execute("SELECT COUNT(*) FROM imported_commodities").fetchone()[0]
        assert count == 1

    def test_description_truncated_to_35_chars(self):
        """Commodity descriptions are truncated to 35 characters."""
        from src.mcp.data_source.tools.commodity_tools import import_commodities_sync

        import_commodities_sync(self.db, [
            {"order_id": 1, "description": "A" * 50, "commodity_code": "000000",
             "origin_country": "US", "quantity": 1, "unit_value": "1.00"},
        ])
        desc = self.db.execute(
            "SELECT description FROM imported_commodities"
        ).fetchone()[0]
        assert len(desc) == 35


class TestGetCommoditiesBulk:
    """Verify bulk commodity retrieval grouped by order_id."""

    def setup_method(self):
        """Set up DuckDB with commodity data."""
        self.db = duckdb.connect(":memory:")
        self.db.execute("""
            CREATE TABLE imported_commodities (
                order_id INTEGER, description VARCHAR, commodity_code VARCHAR,
                origin_country VARCHAR, quantity INTEGER, unit_value VARCHAR,
                unit_of_measure VARCHAR DEFAULT 'PCS'
            )
        """)
        self.db.execute("""
            INSERT INTO imported_commodities VALUES
            (1001, 'Coffee', '090111', 'CO', 5, '30.00', 'PCS'),
            (1001, 'Tea', '090210', 'CN', 10, '15.00', 'PCS'),
            (1002, 'Laptop', '847130', 'US', 1, '999.00', 'PCS')
        """)

    def teardown_method(self):
        """Close DuckDB connection."""
        self.db.close()

    def test_get_commodities_for_single_order(self):
        """Single order returns its commodities grouped."""
        from src.mcp.data_source.tools.commodity_tools import get_commodities_bulk_sync

        result = get_commodities_bulk_sync(self.db, [1001])
        assert 1001 in result
        assert len(result[1001]) == 2
        descs = {c["description"] for c in result[1001]}
        assert descs == {"Coffee", "Tea"}

    def test_get_commodities_for_multiple_orders(self):
        """Multiple orders return correctly grouped results."""
        from src.mcp.data_source.tools.commodity_tools import get_commodities_bulk_sync

        result = get_commodities_bulk_sync(self.db, [1001, 1002])
        assert len(result[1001]) == 2
        assert len(result[1002]) == 1

    def test_missing_order_returns_empty(self):
        """Non-existent order IDs are omitted from result."""
        from src.mcp.data_source.tools.commodity_tools import get_commodities_bulk_sync

        result = get_commodities_bulk_sync(self.db, [9999])
        assert result.get(9999, []) == []

    def test_no_commodities_table_returns_empty(self):
        """Empty DuckDB (no table) returns empty dict."""
        db = duckdb.connect(":memory:")
        from src.mcp.data_source.tools.commodity_tools import get_commodities_bulk_sync

        result = get_commodities_bulk_sync(db, [1001])
        assert result == {}
        db.close()

    def test_empty_order_ids_returns_empty(self):
        """Empty order_ids list returns empty dict."""
        from src.mcp.data_source.tools.commodity_tools import get_commodities_bulk_sync

        result = get_commodities_bulk_sync(self.db, [])
        assert result == {}


class TestGatewaySeam:
    """Verify the full chain: BatchEngine -> DataSourceMCPClient -> MCP tool."""

    def test_data_source_gateway_has_get_commodities_bulk(self):
        """Protocol must define get_commodities_bulk."""
        from src.services.data_source_gateway import DataSourceGateway

        assert hasattr(DataSourceGateway, "get_commodities_bulk")

    def test_data_source_mcp_client_implements_method(self):
        """DataSourceMCPClient must implement get_commodities_bulk."""
        from src.services.data_source_mcp_client import DataSourceMCPClient

        client = DataSourceMCPClient.__new__(DataSourceMCPClient)
        assert hasattr(client, "get_commodities_bulk")
        assert callable(client.get_commodities_bulk)
