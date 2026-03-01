# tests/mcp/platforms/oracle/test_server.py
"""Tests for Oracle platform MCP server contract compliance.

Since Oracle requires a real database, oracledb is mocked throughout.
Tests call exported handler functions directly -- no FastMCP internal introspection.
Follows the pattern from tests/mcp/platforms/dummy/test_vertical_slice.py::TestDummyServerContract.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestOracleServerContract:
    """Verify the Oracle MCP server implements the required tool contract."""

    @pytest.mark.asyncio
    async def test_server_exposes_required_tools(self):
        """Verify tool registration via the public list_tools() MCP method."""
        from src.mcp.platforms.oracle.server import mcp

        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        required = {
            "platform.health",
            "platform.capabilities",
            "auth.connect",
            "auth.disconnect",
            "orders.list",
            "orders.get",
            "tracking.write_back",
        }
        assert required.issubset(tool_names), f"Missing tools: {required - tool_names}"

    @pytest.mark.asyncio
    async def test_health_returns_required_shape(self):
        """Health response must match contract shape when disconnected."""
        from src.mcp.platforms.oracle.server import health

        result = await health()
        # Required fields per contract
        assert "ok" in result
        assert "platform_id" in result
        assert result["platform_id"] == "oracle"
        assert "server_version" in result
        assert "contract_version" in result
        assert result["contract_version"] == "1.0"
        assert "api_reachable" in result
        assert "auth_valid" in result
        # Disconnected state
        assert result["ok"] is False
        assert result["api_reachable"] is False
        assert result["auth_valid"] is False

    @pytest.mark.asyncio
    async def test_capabilities_returns_required_shape(self):
        """Capabilities response must match contract shape."""
        from src.mcp.platforms.oracle.server import capabilities

        result = await capabilities()
        assert "supports" in result
        assert "limits" in result
        assert "paging" in result
        assert "contract_version" in result
        assert result["contract_version"] == "1.0"
        assert "orders.list" in result["supports"]
        # Verify paging contract fields
        assert "default_page_size" in result["paging"]
        assert "max_page_size" in result["paging"]
        assert "overlap_seconds" in result["paging"]
        # Oracle uses offset paging
        assert result["paging"]["strategy"] == "offset"

    @pytest.mark.asyncio
    async def test_health_and_capabilities_contract_versions_match(self):
        """Contract version must be consistent across tools."""
        from src.mcp.platforms.oracle.server import health, capabilities

        h = await health()
        c = await capabilities()
        assert h["contract_version"] == c["contract_version"]

    @pytest.mark.asyncio
    async def test_auth_connect_disconnect_cycle(self):
        """auth.connect and auth.disconnect cycle works with mocked OracleClient."""
        import src.mcp.platforms.oracle.server as server_module
        from src.mcp.platforms.oracle.client import OracleClient

        # Save original state
        original_client = server_module._client
        original_creds = server_module._credentials

        try:
            # Mock OracleClient.test_connection to succeed without real DB
            with patch.object(
                OracleClient, "test_connection",
                new_callable=AsyncMock,
                return_value={"host": "localhost", "service_name": "ORCL", "user": "testuser"},
            ), patch.object(
                OracleClient, "_check_oracledb",
                return_value=None,
            ):
                # Connect
                connect_result = await server_module.auth_connect(
                    credential_ref="test",
                    host="localhost",
                    port=1521,
                    service_name="ORCL",
                    user="testuser",
                    password="testpass",
                )
                assert connect_result["connected"] is True
                assert connect_result["auth_valid"] is True
                assert connect_result["account_id"] == "localhost:1521/ORCL"
                assert server_module._client is not None

                # Disconnect
                disconnect_result = await server_module.auth_disconnect()
                assert disconnect_result["disconnected"] is True
                assert server_module._client is None
        finally:
            # Restore original state
            server_module._client = original_client
            server_module._credentials = original_creds

    @pytest.mark.asyncio
    async def test_orders_list_not_connected(self):
        """orders.list returns AUTH_REQUIRED when not connected."""
        import src.mcp.platforms.oracle.server as server_module

        # Ensure disconnected state
        original_client = server_module._client
        server_module._client = None
        try:
            result = await server_module.orders_list()
            assert "error_code" in result
            assert result["error_code"] == "AUTH_REQUIRED"
        finally:
            server_module._client = original_client

    @pytest.mark.asyncio
    async def test_orders_get_not_connected(self):
        """orders.get returns AUTH_REQUIRED when not connected."""
        import src.mcp.platforms.oracle.server as server_module

        original_client = server_module._client
        server_module._client = None
        try:
            result = await server_module.orders_get(order_id="12345")
            assert "error_code" in result
            assert result["error_code"] == "AUTH_REQUIRED"
        finally:
            server_module._client = original_client

    @pytest.mark.asyncio
    async def test_tracking_write_back_not_connected(self):
        """tracking.write_back returns AUTH_REQUIRED when not connected."""
        import src.mcp.platforms.oracle.server as server_module

        original_client = server_module._client
        server_module._client = None
        try:
            result = await server_module.tracking_write_back(
                order_id="12345",
                tracking_numbers=["1Z999AA10123456784"],
            )
            assert "error_code" in result
            assert result["error_code"] == "AUTH_REQUIRED"
        finally:
            server_module._client = original_client

    @pytest.mark.asyncio
    async def test_orders_list_invalid_cursor(self):
        """orders.list with non-integer cursor returns INVALID_ARGUMENT."""
        import src.mcp.platforms.oracle.server as server_module

        # Set a mock client so we get past the not-connected check
        original_client = server_module._client
        server_module._client = MagicMock()
        try:
            result = await server_module.orders_list(cursor="not_a_number")
            assert "error_code" in result
            assert result["error_code"] == "INVALID_ARGUMENT"
        finally:
            server_module._client = original_client


class TestOracleMapper:
    """Verify the OracleMapper produces correct flat rows."""

    @pytest.fixture
    def mapper(self):
        """Create an OracleMapper instance."""
        from src.mcp.platforms.oracle.mapper import OracleMapper
        return OracleMapper()

    @pytest.fixture
    def sample_order(self):
        """Create a sample Oracle order row dict with uppercase keys."""
        return {
            "ORDER_ID": "ORD-001",
            "ORDER_NUMBER": "1001",
            "ORDER_STATUS": "open",
            "PAYMENT_STATUS": "paid",
            "FULFILLMENT_STATUS": None,
            "CREATED_DATE": "2026-02-20T10:00:00",
            "UPDATED_DATE": "2026-02-20T12:00:00",
            "SHIP_TO_NAME": "Alice Test",
            "SHIP_TO_COMPANY": "Test Corp",
            "SHIP_TO_ADDRESS1": "100 First St",
            "SHIP_TO_ADDRESS2": "Suite 200",
            "SHIP_TO_CITY": "Austin",
            "SHIP_TO_STATE": "TX",
            "SHIP_TO_POSTAL": "78701",
            "SHIP_TO_COUNTRY": "US",
            "SHIP_TO_PHONE": "5125551234",
            "TOTAL_AMOUNT": "25.00",
            "CURRENCY_CODE": "USD",
            "CUSTOMER_NAME": "Alice Test",
            "CUSTOMER_EMAIL": "alice@test.com",
            "TOTAL_WEIGHT_GRAMS": 500,
            "ITEM_COUNT": 2,
            "TAGS": "priority",
        }

    def test_platform_is_oracle(self, mapper, sample_order):
        """Platform must be 'oracle'."""
        row = mapper.to_flat_row(sample_order, "test")
        assert row["platform"] == "oracle"

    def test_external_id_is_string(self, mapper, sample_order):
        """External ID must be a string."""
        row = mapper.to_flat_row(sample_order, "test")
        assert row["external_id"] == "ORD-001"
        assert isinstance(row["external_id"], str)

    def test_canonical_hash_is_sha256(self, mapper, sample_order):
        """Canonical hash must be 64-char hex (SHA-256)."""
        row = mapper.to_flat_row(sample_order, "test")
        assert len(row["canonical_hash"]) == 64

    def test_canonical_hash_deterministic(self, mapper, sample_order):
        """Same input must produce same hash."""
        row1 = mapper.to_flat_row(sample_order, "test")
        row2 = mapper.to_flat_row(sample_order, "test")
        assert row1["canonical_hash"] == row2["canonical_hash"]

    def test_weight_calculation(self, mapper, sample_order):
        """Weight must be extracted from TOTAL_WEIGHT_GRAMS."""
        row = mapper.to_flat_row(sample_order, "test")
        assert row["total_weight_grams"] == 500

    def test_price_in_cents(self, mapper, sample_order):
        """Price must be converted from decimal to integer cents."""
        row = mapper.to_flat_row(sample_order, "test")
        assert row["total_price_cents"] == 2500

    def test_mapping_version(self, mapper, sample_order):
        """Mapping version must be set."""
        row = mapper.to_flat_row(sample_order, "test")
        assert row["mapping_version"] == "1.0"

    def test_credential_ref_preserved(self, mapper, sample_order):
        """Credential ref must be passed through."""
        row = mapper.to_flat_row(sample_order, "primary")
        assert row["credential_ref"] == "primary"

    def test_fulfillment_status_defaults_to_unfulfilled(self, mapper, sample_order):
        """None fulfillment_status defaults to 'unfulfilled'."""
        row = mapper.to_flat_row(sample_order, "test")
        assert row["fulfillment_status"] == "unfulfilled"

    def test_country_defaults_to_us(self, mapper):
        """Missing country defaults to 'US'."""
        order = {"ORDER_ID": "X1"}
        row = mapper.to_flat_row(order, "test")
        assert row["ship_to_country"] == "US"

    def test_attrs_json_includes_notes(self, mapper):
        """Attrs JSON captures NOTES field."""
        order = {"ORDER_ID": "X1", "NOTES": "Fragile items"}
        row = mapper.to_flat_row(order, "test")
        import json
        attrs = json.loads(row["attrs_json"])
        assert attrs["notes"] == "Fragile items"

    def test_raw_json_preserved(self, mapper, sample_order):
        """Raw JSON must contain the original order data."""
        row = mapper.to_flat_row(sample_order, "test")
        import json
        raw = json.loads(row["raw_json"])
        assert raw["ORDER_ID"] == "ORD-001"


class TestOracleClient:
    """Verify OracleClient behavior with mocked oracledb."""

    def test_identifier_validation_rejects_injection(self):
        """Client init must reject unsafe table names."""
        from src.mcp.platforms.oracle.client import _quote_identifier

        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _quote_identifier("DROP TABLE; --")

        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _quote_identifier("")

        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _quote_identifier("123_starts_with_number")

    def test_identifier_validation_accepts_valid(self):
        """Client init must accept valid Oracle identifiers."""
        from src.mcp.platforms.oracle.client import _quote_identifier

        assert _quote_identifier("SALES_ORDERS") == '"SALES_ORDERS"'
        assert _quote_identifier("my_table") == '"my_table"'
        assert _quote_identifier("_leading_underscore") == '"_leading_underscore"'

    def test_client_init_validates_table_names(self):
        """Client constructor must validate table identifiers."""
        from src.mcp.platforms.oracle.models import OracleCredentials
        from src.mcp.platforms.oracle.client import OracleClient

        # Valid table names work
        creds = OracleCredentials(
            host="localhost", port=1521, service_name="ORCL",
            user="test", password="pass",
            orders_table="SALES_ORDERS",
            tracking_table="SHIPMENT_TRACKING",
        )
        client = OracleClient(creds)
        assert client is not None

        # Invalid table name raises
        bad_creds = OracleCredentials(
            host="localhost", port=1521, service_name="ORCL",
            user="test", password="pass",
            orders_table="DROP TABLE;--",
            tracking_table="SHIPMENT_TRACKING",
        )
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            OracleClient(bad_creds)


class TestOracleCredentials:
    """Verify OracleCredentials model."""

    def test_dsn_property(self):
        """DSN must be host:port/service_name."""
        from src.mcp.platforms.oracle.models import OracleCredentials

        creds = OracleCredentials(
            host="oracle.example.com",
            port=1521,
            service_name="ORCL",
            user="shipagent",
            password="secret",
        )
        assert creds.dsn == "oracle.example.com:1521/ORCL"

    def test_default_table_names(self):
        """Default table names must be set."""
        from src.mcp.platforms.oracle.models import OracleCredentials

        creds = OracleCredentials(
            host="localhost", port=1521, service_name="ORCL",
            user="test", password="pass",
        )
        assert creds.orders_table == "SALES_ORDERS"
        assert creds.tracking_table == "SHIPMENT_TRACKING"

    def test_custom_table_names(self):
        """Custom table names must override defaults."""
        from src.mcp.platforms.oracle.models import OracleCredentials

        creds = OracleCredentials(
            host="localhost", port=1521, service_name="ORCL",
            user="test", password="pass",
            orders_table="MY_ORDERS",
            tracking_table="MY_TRACKING",
        )
        assert creds.orders_table == "MY_ORDERS"
        assert creds.tracking_table == "MY_TRACKING"
