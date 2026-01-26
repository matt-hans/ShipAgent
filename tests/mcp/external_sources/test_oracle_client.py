"""Test Oracle platform client implementation.

Tests use unittest.mock to mock oracledb connection and cursor
since oracledb may not be installed in the test environment.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp.external_sources.clients.base import PlatformClient
from src.mcp.external_sources.clients.oracle import (
    DEFAULT_TABLE_CONFIG,
    OracleClient,
    OracleDependencyError,
)
from src.mcp.external_sources.models import (
    ExternalOrder,
    OrderFilters,
    TrackingUpdate,
)


class TestOracleClientInterface:
    """Test that OracleClient properly implements PlatformClient interface."""

    def test_extends_platform_client(self):
        """Test that OracleClient extends PlatformClient."""
        assert issubclass(OracleClient, PlatformClient)

    def test_platform_name_property(self):
        """Test that platform_name returns 'oracle'."""
        client = OracleClient()
        assert client.platform_name == "oracle"

    def test_default_table_config(self):
        """Test DEFAULT_TABLE_CONFIG has required keys."""
        assert "orders_table" in DEFAULT_TABLE_CONFIG
        assert "columns" in DEFAULT_TABLE_CONFIG
        assert DEFAULT_TABLE_CONFIG["orders_table"] == "SALES_ORDERS"

        columns = DEFAULT_TABLE_CONFIG["columns"]
        required_columns = [
            "order_id",
            "customer_name",
            "ship_to_name",
            "ship_to_address1",
            "ship_to_city",
            "ship_to_state",
            "ship_to_postal_code",
            "ship_to_country",
            "tracking_number",
            "status",
        ]
        for col in required_columns:
            assert col in columns, f"Missing column mapping: {col}"

    def test_custom_table_config(self):
        """Test that custom table config can be provided."""
        custom_config = {
            "orders_table": "CUSTOM_ORDERS",
            "columns": {
                "order_id": "CUST_ORDER_ID",
                "customer_name": "CUST_NAME",
                "ship_to_name": "RECIPIENT",
                "ship_to_address1": "ADDR1",
                "ship_to_city": "CITY",
                "ship_to_state": "STATE",
                "ship_to_postal_code": "ZIP",
                "ship_to_country": "COUNTRY",
                "tracking_number": "TRACKING",
                "status": "STATUS",
            },
        }
        client = OracleClient(table_config=custom_config)
        assert client._table_config["orders_table"] == "CUSTOM_ORDERS"
        assert client._table_config["columns"]["order_id"] == "CUST_ORDER_ID"


class TestOracleClientAuthentication:
    """Test authentication functionality."""

    @pytest.fixture
    def mock_oracledb(self):
        """Create mock oracledb module."""
        with patch("src.mcp.external_sources.clients.oracle.ORACLEDB_AVAILABLE", True):
            with patch("src.mcp.external_sources.clients.oracle.oracledb") as mock:
                # Create mock connection that supports async context manager
                mock_conn = MagicMock()
                mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
                mock_conn.__aexit__ = AsyncMock(return_value=None)
                mock.connect_async = AsyncMock(return_value=mock_conn)
                yield mock

    @pytest.mark.asyncio
    async def test_authenticate_with_connection_string(self, mock_oracledb):
        """Test authentication using connection string."""
        client = OracleClient()
        credentials = {
            "connection_string": "user/pass@//host:1521/service"
        }

        result = await client.authenticate(credentials)

        assert result is True
        mock_oracledb.connect_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_authenticate_with_individual_params(self, mock_oracledb):
        """Test authentication using individual connection parameters."""
        client = OracleClient()
        credentials = {
            "host": "oracle.example.com",
            "port": 1521,
            "service_name": "ORCL",
            "user": "shipagent",
            "password": "secret123",
        }

        result = await client.authenticate(credentials)

        assert result is True
        mock_oracledb.connect_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_authenticate_missing_credentials(self, mock_oracledb):
        """Test that authentication fails with missing credentials."""
        client = OracleClient()
        credentials = {}

        with pytest.raises(ValueError, match="connection_string.*or.*host"):
            await client.authenticate(credentials)

    @pytest.mark.asyncio
    async def test_authenticate_connection_failure(self, mock_oracledb):
        """Test that authentication returns False on connection failure."""
        mock_oracledb.connect_async.side_effect = Exception("Connection refused")

        client = OracleClient()
        credentials = {"connection_string": "invalid"}

        result = await client.authenticate(credentials)

        assert result is False


class TestOracleClientConnection:
    """Test connection testing functionality."""

    @pytest.fixture
    def connected_client(self):
        """Create a client with mocked connection."""
        client = OracleClient()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone = MagicMock(return_value=(1,))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        client._connection = mock_conn
        return client, mock_cursor

    @pytest.mark.asyncio
    async def test_test_connection_success(self, connected_client):
        """Test that test_connection executes SELECT 1 FROM DUAL."""
        client, mock_cursor = connected_client

        result = await client.test_connection()

        assert result is True
        mock_cursor.execute.assert_called_once_with("SELECT 1 FROM DUAL")

    @pytest.mark.asyncio
    async def test_test_connection_not_connected(self):
        """Test that test_connection returns False when not connected."""
        client = OracleClient()

        result = await client.test_connection()

        assert result is False

    @pytest.mark.asyncio
    async def test_test_connection_query_failure(self, connected_client):
        """Test that test_connection returns False on query failure."""
        client, mock_cursor = connected_client
        mock_cursor.execute.side_effect = Exception("Query failed")

        result = await client.test_connection()

        assert result is False


class TestOracleClientFetchOrders:
    """Test order fetching functionality."""

    @pytest.fixture
    def connected_client_with_data(self):
        """Create a client with mocked connection and sample data."""
        client = OracleClient()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Sample order data matching default column mapping
        sample_rows = [
            (
                "ORD-001",  # ORDER_ID
                "John Doe",  # CUSTOMER_NAME
                "John Doe",  # SHIP_TO_NAME
                "123 Main St",  # SHIP_TO_ADDRESS1
                "Los Angeles",  # SHIP_TO_CITY
                "CA",  # SHIP_TO_STATE
                "90001",  # SHIP_TO_ZIP
                "US",  # SHIP_TO_COUNTRY
                None,  # TRACKING_NUMBER
                "pending",  # ORDER_STATUS
            ),
            (
                "ORD-002",  # ORDER_ID
                "Jane Smith",  # CUSTOMER_NAME
                "Jane Smith",  # SHIP_TO_NAME
                "456 Oak Ave",  # SHIP_TO_ADDRESS1
                "San Francisco",  # SHIP_TO_CITY
                "CA",  # SHIP_TO_STATE
                "94102",  # SHIP_TO_ZIP
                "US",  # SHIP_TO_COUNTRY
                "1Z999",  # TRACKING_NUMBER
                "shipped",  # ORDER_STATUS
            ),
        ]

        mock_cursor.fetchall = MagicMock(return_value=sample_rows)
        mock_cursor.description = [
            ("ORDER_ID",), ("CUSTOMER_NAME",), ("SHIP_TO_NAME",),
            ("SHIP_TO_ADDRESS1",), ("SHIP_TO_CITY",), ("SHIP_TO_STATE",),
            ("SHIP_TO_ZIP",), ("SHIP_TO_COUNTRY",), ("TRACKING_NUMBER",),
            ("ORDER_STATUS",),
        ]
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        client._connection = mock_conn
        return client, mock_cursor

    @pytest.mark.asyncio
    async def test_fetch_orders_basic(self, connected_client_with_data):
        """Test basic order fetching."""
        client, mock_cursor = connected_client_with_data
        filters = OrderFilters()

        orders = await client.fetch_orders(filters)

        assert len(orders) == 2
        assert isinstance(orders[0], ExternalOrder)
        assert orders[0].order_id == "ORD-001"
        assert orders[0].platform == "oracle"
        assert orders[0].customer_name == "John Doe"

    @pytest.mark.asyncio
    async def test_fetch_orders_with_status_filter(self, connected_client_with_data):
        """Test order fetching with status filter."""
        client, mock_cursor = connected_client_with_data
        filters = OrderFilters(status="pending")

        await client.fetch_orders(filters)

        # Verify SQL contains WHERE clause for status
        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        assert "ORDER_STATUS" in sql
        assert "pending" in str(call_args)

    @pytest.mark.asyncio
    async def test_fetch_orders_with_date_filter(self, connected_client_with_data):
        """Test order fetching with date range filter."""
        client, mock_cursor = connected_client_with_data
        filters = OrderFilters(
            date_from="2026-01-01",
            date_to="2026-01-31",
        )

        await client.fetch_orders(filters)

        # Verify SQL contains date filters
        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        assert "CREATED_AT" in sql or "created_at" in sql.lower()

    @pytest.mark.asyncio
    async def test_fetch_orders_with_limit_offset(self, connected_client_with_data):
        """Test order fetching with pagination."""
        client, mock_cursor = connected_client_with_data
        filters = OrderFilters(limit=50, offset=100)

        await client.fetch_orders(filters)

        # Verify SQL contains pagination
        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        # Oracle uses FETCH FIRST ... ROWS or ROWNUM for pagination
        assert "FETCH" in sql or "ROWNUM" in sql or "OFFSET" in sql

    @pytest.mark.asyncio
    async def test_fetch_orders_not_connected(self):
        """Test that fetch_orders raises error when not connected."""
        client = OracleClient()

        with pytest.raises(RuntimeError, match="Not connected"):
            await client.fetch_orders(OrderFilters())


class TestOracleClientGetOrder:
    """Test single order retrieval."""

    @pytest.fixture
    def connected_client_single_order(self):
        """Create a client with mocked connection for single order."""
        client = OracleClient()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        sample_row = (
            "ORD-001",
            "John Doe",
            "John Doe",
            "123 Main St",
            "Los Angeles",
            "CA",
            "90001",
            "US",
            None,
            "pending",
        )

        mock_cursor.fetchone = MagicMock(return_value=sample_row)
        mock_cursor.description = [
            ("ORDER_ID",), ("CUSTOMER_NAME",), ("SHIP_TO_NAME",),
            ("SHIP_TO_ADDRESS1",), ("SHIP_TO_CITY",), ("SHIP_TO_STATE",),
            ("SHIP_TO_ZIP",), ("SHIP_TO_COUNTRY",), ("TRACKING_NUMBER",),
            ("ORDER_STATUS",),
        ]
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        client._connection = mock_conn
        return client, mock_cursor

    @pytest.mark.asyncio
    async def test_get_order_found(self, connected_client_single_order):
        """Test retrieving existing order."""
        client, mock_cursor = connected_client_single_order

        order = await client.get_order("ORD-001")

        assert order is not None
        assert order.order_id == "ORD-001"
        assert order.platform == "oracle"

    @pytest.mark.asyncio
    async def test_get_order_not_found(self, connected_client_single_order):
        """Test retrieving non-existent order."""
        client, mock_cursor = connected_client_single_order
        mock_cursor.fetchone = MagicMock(return_value=None)

        order = await client.get_order("NONEXISTENT")

        assert order is None

    @pytest.mark.asyncio
    async def test_get_order_uses_primary_key(self, connected_client_single_order):
        """Test that get_order queries by primary key."""
        client, mock_cursor = connected_client_single_order

        await client.get_order("ORD-001")

        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        # Should use ORDER_ID (mapped column) in WHERE clause
        assert "ORDER_ID" in sql
        assert "ORD-001" in str(call_args)

    @pytest.mark.asyncio
    async def test_get_order_not_connected(self):
        """Test that get_order raises error when not connected."""
        client = OracleClient()

        with pytest.raises(RuntimeError, match="Not connected"):
            await client.get_order("ORD-001")


class TestOracleClientUpdateTracking:
    """Test tracking update functionality."""

    @pytest.fixture
    def connected_client_for_update(self):
        """Create a client with mocked connection for updates."""
        client = OracleClient()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        mock_cursor.rowcount = 1
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.commit = AsyncMock()
        client._connection = mock_conn
        return client, mock_cursor, mock_conn

    @pytest.mark.asyncio
    async def test_update_tracking_success(self, connected_client_for_update):
        """Test successful tracking update."""
        client, mock_cursor, mock_conn = connected_client_for_update
        update = TrackingUpdate(
            order_id="ORD-001",
            tracking_number="1Z999AA10123456784",
            carrier="UPS",
        )

        result = await client.update_tracking(update)

        assert result is True
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_tracking_uses_correct_columns(self, connected_client_for_update):
        """Test that update uses mapped column names."""
        client, mock_cursor, mock_conn = connected_client_for_update
        update = TrackingUpdate(
            order_id="ORD-001",
            tracking_number="1Z999AA10123456784",
            carrier="UPS",
        )

        await client.update_tracking(update)

        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        # Should use mapped column names
        assert "TRACKING_NUMBER" in sql
        assert "ORDER_ID" in sql

    @pytest.mark.asyncio
    async def test_update_tracking_no_rows_affected(self, connected_client_for_update):
        """Test tracking update when order not found."""
        client, mock_cursor, mock_conn = connected_client_for_update
        mock_cursor.rowcount = 0
        update = TrackingUpdate(
            order_id="NONEXISTENT",
            tracking_number="1Z999",
            carrier="UPS",
        )

        result = await client.update_tracking(update)

        assert result is False

    @pytest.mark.asyncio
    async def test_update_tracking_not_connected(self):
        """Test that update_tracking raises error when not connected."""
        client = OracleClient()
        update = TrackingUpdate(
            order_id="ORD-001",
            tracking_number="1Z999",
            carrier="UPS",
        )

        with pytest.raises(RuntimeError, match="Not connected"):
            await client.update_tracking(update)


class TestOracleClientSQLGeneration:
    """Test SQL query generation."""

    def test_build_select_columns(self):
        """Test that SELECT statement uses correct column mappings."""
        client = OracleClient()
        columns = client._build_select_columns()

        # Should include all mapped columns
        assert "ORDER_ID" in columns
        assert "CUSTOMER_NAME" in columns
        assert "SHIP_TO_ZIP" in columns  # Mapped from ship_to_postal_code

    def test_build_where_clause_empty(self):
        """Test WHERE clause with no filters."""
        client = OracleClient()
        filters = OrderFilters()

        where, params = client._build_where_clause(filters)

        # With no filters, should return minimal clause
        assert "1=1" in where or where == ""

    def test_build_where_clause_with_status(self):
        """Test WHERE clause with status filter."""
        client = OracleClient()
        filters = OrderFilters(status="pending")

        where, params = client._build_where_clause(filters)

        assert "ORDER_STATUS" in where
        assert "pending" in params.values() or "pending" in params

    def test_build_pagination_clause(self):
        """Test pagination clause generation."""
        client = OracleClient()
        filters = OrderFilters(limit=50, offset=100)

        pagination = client._build_pagination_clause(filters)

        # Oracle 12c+ uses OFFSET/FETCH syntax
        assert "OFFSET" in pagination or "ROWNUM" in pagination
        assert "50" in pagination
        assert "100" in pagination


class TestOracleClientDependencyHandling:
    """Test handling of oracledb dependency."""

    @pytest.mark.asyncio
    async def test_oracledb_not_installed_error(self):
        """Test that clear error is raised if oracledb not installed."""
        with patch("src.mcp.external_sources.clients.oracle.ORACLEDB_AVAILABLE", False):
            client = OracleClient()
            with pytest.raises(OracleDependencyError, match="oracledb"):
                await client.authenticate({"connection_string": "test"})


class TestOracleClientRowMapping:
    """Test row data to ExternalOrder mapping."""

    def test_map_row_to_order_complete(self):
        """Test mapping complete row data to ExternalOrder."""
        client = OracleClient()
        row_dict = {
            "ORDER_ID": "ORD-001",
            "CUSTOMER_NAME": "John Doe",
            "SHIP_TO_NAME": "John Doe",
            "SHIP_TO_ADDRESS1": "123 Main St",
            "SHIP_TO_CITY": "Los Angeles",
            "SHIP_TO_STATE": "CA",
            "SHIP_TO_ZIP": "90001",
            "SHIP_TO_COUNTRY": "US",
            "TRACKING_NUMBER": "1Z999",
            "ORDER_STATUS": "shipped",
        }

        order = client._map_row_to_order(row_dict)

        assert order.order_id == "ORD-001"
        assert order.customer_name == "John Doe"
        assert order.ship_to_postal_code == "90001"
        assert order.status == "shipped"
        assert order.platform == "oracle"

    def test_map_row_to_order_with_nulls(self):
        """Test mapping row with null values."""
        client = OracleClient()
        row_dict = {
            "ORDER_ID": "ORD-001",
            "CUSTOMER_NAME": "John Doe",
            "SHIP_TO_NAME": "John Doe",
            "SHIP_TO_ADDRESS1": "123 Main St",
            "SHIP_TO_CITY": "Los Angeles",
            "SHIP_TO_STATE": "CA",
            "SHIP_TO_ZIP": "90001",
            "SHIP_TO_COUNTRY": None,  # Null country
            "TRACKING_NUMBER": None,  # Null tracking
            "ORDER_STATUS": "pending",
        }

        order = client._map_row_to_order(row_dict)

        assert order.ship_to_country == "US"  # Default
        assert order.order_id == "ORD-001"


class TestOracleClientConnectionManagement:
    """Test connection lifecycle management."""

    @pytest.mark.asyncio
    async def test_close_connection(self):
        """Test closing connection."""
        client = OracleClient()
        mock_conn = MagicMock()
        mock_conn.close = AsyncMock()
        client._connection = mock_conn

        await client.close()

        mock_conn.close.assert_called_once()
        assert client._connection is None

    @pytest.mark.asyncio
    async def test_close_when_not_connected(self):
        """Test closing when not connected does not raise."""
        client = OracleClient()

        # Should not raise
        await client.close()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager support."""
        with patch("src.mcp.external_sources.clients.oracle.ORACLEDB_AVAILABLE", True):
            with patch("src.mcp.external_sources.clients.oracle.oracledb") as mock_oracledb:
                mock_conn = MagicMock()
                mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
                mock_conn.__aexit__ = AsyncMock(return_value=None)
                mock_conn.close = AsyncMock()
                mock_oracledb.connect_async = AsyncMock(return_value=mock_conn)

                client = OracleClient()
                async with client as c:
                    await c.authenticate({"connection_string": "test"})
                    assert c._connection is not None

                # Connection should be closed after context exit
                mock_conn.close.assert_called()
