"""Oracle platform client implementation.

Connects to Oracle databases to fetch order data and update tracking information.
Uses oracledb library in thin mode (no Oracle client installation required).

Example usage:
    client = OracleClient()
    await client.authenticate({
        "host": "oracle.example.com",
        "port": 1521,
        "service_name": "ORCL",
        "user": "shipagent",
        "password": "secret"
    })
    orders = await client.fetch_orders(OrderFilters(status="pending"))
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.mcp.external_sources.clients.base import PlatformClient
from src.mcp.external_sources.models import (
    ExternalOrder,
    OrderFilters,
    TrackingUpdate,
)

# Handle optional oracledb dependency
ORACLEDB_AVAILABLE = False
try:
    import oracledb

    ORACLEDB_AVAILABLE = True
except ImportError:
    oracledb = None  # type: ignore[assignment]

if TYPE_CHECKING:
    import oracledb


class OracleDependencyError(Exception):
    """Raised when oracledb library is not installed."""

    def __init__(self) -> None:
        """Initialize with installation instructions."""
        super().__init__(
            "oracledb library is not installed. "
            "Install it with: pip install oracledb"
        )


# Default table and column configuration
DEFAULT_TABLE_CONFIG: dict[str, Any] = {
    "orders_table": "SALES_ORDERS",
    "columns": {
        "order_id": "ORDER_ID",
        "customer_name": "CUSTOMER_NAME",
        "ship_to_name": "SHIP_TO_NAME",
        "ship_to_address1": "SHIP_TO_ADDRESS1",
        "ship_to_city": "SHIP_TO_CITY",
        "ship_to_state": "SHIP_TO_STATE",
        "ship_to_postal_code": "SHIP_TO_ZIP",
        "ship_to_country": "SHIP_TO_COUNTRY",
        "tracking_number": "TRACKING_NUMBER",
        "status": "ORDER_STATUS",
        "created_at": "CREATED_AT",
    },
}


class OracleClient(PlatformClient):
    """Oracle database platform client.

    Fetches orders from Oracle database tables and updates tracking information.
    Uses oracledb thin mode for connectivity (no Oracle client required).

    Attributes:
        _connection: Active Oracle database connection
        _table_config: Column and table mapping configuration

    Example:
        client = OracleClient(table_config={
            "orders_table": "MY_ORDERS",
            "columns": {"order_id": "ID", ...}
        })
    """

    def __init__(self, table_config: dict[str, Any] | None = None) -> None:
        """Initialize Oracle client.

        Args:
            table_config: Optional custom table/column mapping configuration.
                         If not provided, DEFAULT_TABLE_CONFIG is used.
        """
        self._connection: Any = None
        self._table_config = table_config or DEFAULT_TABLE_CONFIG.copy()
        # Ensure columns dict exists with defaults
        if "columns" not in self._table_config:
            self._table_config["columns"] = DEFAULT_TABLE_CONFIG["columns"].copy()

    @property
    def platform_name(self) -> str:
        """Return the platform identifier.

        Returns:
            'oracle' as the platform name.
        """
        return "oracle"

    def _check_oracledb_available(self) -> None:
        """Check if oracledb is available, raise error if not.

        Raises:
            OracleDependencyError: If oracledb is not installed.
        """
        if not ORACLEDB_AVAILABLE:
            raise OracleDependencyError()

    def _check_connected(self) -> None:
        """Check if client is connected, raise error if not.

        Raises:
            RuntimeError: If not connected to database.
        """
        if self._connection is None:
            raise RuntimeError("Not connected to Oracle database")

    async def authenticate(self, credentials: dict) -> bool:
        """Authenticate with Oracle database.

        Supports two credential formats:
        1. Connection string: {"connection_string": "user/pass@//host:port/service"}
        2. Individual params: {"host", "port", "service_name", "user", "password"}

        Args:
            credentials: Connection credentials dictionary.

        Returns:
            True if connection successful, False otherwise.

        Raises:
            ValueError: If required credentials are missing.
            OracleDependencyError: If oracledb is not installed.
        """
        self._check_oracledb_available()

        # Validate credentials
        if "connection_string" not in credentials and "host" not in credentials:
            raise ValueError(
                "Credentials must include 'connection_string' or "
                "'host', 'port', 'service_name', 'user', 'password'"
            )

        try:
            if "connection_string" in credentials:
                # Use connection string directly
                self._connection = await oracledb.connect_async(
                    credentials["connection_string"]
                )
            else:
                # Build DSN from individual parameters
                host = credentials["host"]
                port = credentials.get("port", 1521)
                service_name = credentials["service_name"]
                user = credentials["user"]
                password = credentials["password"]

                dsn = f"{host}:{port}/{service_name}"
                self._connection = await oracledb.connect_async(
                    user=user,
                    password=password,
                    dsn=dsn,
                )

            return True

        except Exception:
            self._connection = None
            return False

    async def test_connection(self) -> bool:
        """Test that the connection is still valid.

        Executes SELECT 1 FROM DUAL to verify connectivity.

        Returns:
            True if connection is healthy, False otherwise.
        """
        if self._connection is None:
            return False

        try:
            async with self._connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM DUAL")
                result = cursor.fetchone()
                return result is not None and result[0] == 1
        except Exception:
            return False

    async def fetch_orders(self, filters: OrderFilters) -> list[ExternalOrder]:
        """Fetch orders from the configured Oracle table.

        Args:
            filters: Order filtering criteria (status, date range, pagination).

        Returns:
            List of orders in normalized ExternalOrder format.

        Raises:
            RuntimeError: If not connected to database.
        """
        self._check_connected()

        columns = self._build_select_columns()
        table = self._table_config["orders_table"]
        where_clause, params = self._build_where_clause(filters)
        pagination = self._build_pagination_clause(filters)

        sql = f"SELECT {columns} FROM {table}"
        if where_clause:
            sql += f" WHERE {where_clause}"
        sql += f" ORDER BY {self._get_column('order_id')}"
        sql += pagination

        async with self._connection.cursor() as cursor:
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            rows = cursor.fetchall()
            column_names = [desc[0] for desc in cursor.description]

            orders = []
            for row in rows:
                row_dict = dict(zip(column_names, row))
                orders.append(self._map_row_to_order(row_dict))

            return orders

    async def get_order(self, order_id: str) -> ExternalOrder | None:
        """Get a single order by ID.

        Args:
            order_id: The order identifier (primary key).

        Returns:
            ExternalOrder if found, None otherwise.

        Raises:
            RuntimeError: If not connected to database.
        """
        self._check_connected()

        columns = self._build_select_columns()
        table = self._table_config["orders_table"]
        id_column = self._get_column("order_id")

        sql = f"SELECT {columns} FROM {table} WHERE {id_column} = :order_id"

        async with self._connection.cursor() as cursor:
            cursor.execute(sql, {"order_id": order_id})
            row = cursor.fetchone()

            if row is None:
                return None

            column_names = [desc[0] for desc in cursor.description]
            row_dict = dict(zip(column_names, row))
            return self._map_row_to_order(row_dict)

    async def update_tracking(self, update: TrackingUpdate) -> bool:
        """Write tracking information back to the platform.

        Updates the tracking_number column for the specified order.

        Args:
            update: Tracking number and carrier information.

        Returns:
            True if update successful (row affected), False if order not found.

        Raises:
            RuntimeError: If not connected to database.
        """
        self._check_connected()

        table = self._table_config["orders_table"]
        tracking_column = self._get_column("tracking_number")
        id_column = self._get_column("order_id")

        sql = f"""
            UPDATE {table}
            SET {tracking_column} = :tracking_number
            WHERE {id_column} = :order_id
        """

        async with self._connection.cursor() as cursor:
            cursor.execute(
                sql,
                {
                    "tracking_number": update.tracking_number,
                    "order_id": update.order_id,
                },
            )

            if cursor.rowcount == 0:
                return False

            await self._connection.commit()
            return True

    async def close(self) -> None:
        """Close the database connection.

        Safe to call even if not connected.
        """
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def __aenter__(self) -> "OracleClient":
        """Enter async context manager.

        Returns:
            Self for use in async with block.
        """
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context manager, closing connection.

        Args:
            exc_type: Exception type if raised.
            exc_val: Exception value if raised.
            exc_tb: Exception traceback if raised.
        """
        await self.close()

    def _get_column(self, logical_name: str) -> str:
        """Get the mapped column name for a logical field.

        Args:
            logical_name: The logical field name (e.g., 'order_id').

        Returns:
            The mapped database column name (e.g., 'ORDER_ID').
        """
        return self._table_config["columns"].get(
            logical_name, logical_name.upper()
        )

    def _build_select_columns(self) -> str:
        """Build the SELECT column list from configuration.

        Returns:
            Comma-separated list of column names.
        """
        columns = self._table_config["columns"]
        return ", ".join(columns.values())

    def _build_where_clause(
        self, filters: OrderFilters
    ) -> tuple[str, dict[str, Any]]:
        """Build WHERE clause from filters.

        Args:
            filters: The order filters to apply.

        Returns:
            Tuple of (where_clause_string, parameters_dict).
        """
        conditions = []
        params: dict[str, Any] = {}

        if filters.status:
            status_col = self._get_column("status")
            conditions.append(f"{status_col} = :status")
            params["status"] = filters.status

        if filters.date_from:
            created_col = self._get_column("created_at")
            conditions.append(f"{created_col} >= TO_DATE(:date_from, 'YYYY-MM-DD')")
            params["date_from"] = filters.date_from

        if filters.date_to:
            created_col = self._get_column("created_at")
            conditions.append(f"{created_col} <= TO_DATE(:date_to, 'YYYY-MM-DD')")
            params["date_to"] = filters.date_to

        if conditions:
            return " AND ".join(conditions), params

        return "1=1", params

    def _build_pagination_clause(self, filters: OrderFilters) -> str:
        """Build pagination clause (Oracle 12c+ syntax).

        Args:
            filters: Filters containing limit and offset.

        Returns:
            OFFSET/FETCH clause string.
        """
        parts = []

        if filters.offset > 0:
            parts.append(f" OFFSET {filters.offset} ROWS")
        else:
            parts.append(" OFFSET 0 ROWS")

        parts.append(f" FETCH FIRST {filters.limit} ROWS ONLY")

        return "".join(parts)

    def _map_row_to_order(self, row_dict: dict[str, Any]) -> ExternalOrder:
        """Map a database row to ExternalOrder model.

        Args:
            row_dict: Dictionary with column names as keys.

        Returns:
            Normalized ExternalOrder instance.
        """
        columns = self._table_config["columns"]

        # Helper to get value with fallback
        def get_val(logical: str, default: Any = None) -> Any:
            col_name = columns.get(logical, logical.upper())
            return row_dict.get(col_name, default)

        return ExternalOrder(
            platform=self.platform_name,
            order_id=str(get_val("order_id", "")),
            order_number=str(get_val("order_id", "")),  # Use order_id as order_number
            status=str(get_val("status", "unknown")),
            created_at=self._format_datetime(get_val("created_at")),
            customer_name=str(get_val("customer_name", "")),
            customer_email=None,  # Not in default config
            ship_to_name=str(get_val("ship_to_name", "")),
            ship_to_company=None,  # Not in default config
            ship_to_address1=str(get_val("ship_to_address1", "")),
            ship_to_address2=None,  # Not in default config
            ship_to_city=str(get_val("ship_to_city", "")),
            ship_to_state=str(get_val("ship_to_state", "")),
            ship_to_postal_code=str(get_val("ship_to_postal_code", "")),
            ship_to_country=str(get_val("ship_to_country") or "US"),
            ship_to_phone=None,  # Not in default config
            items=[],  # Not fetching items in this implementation
            raw_data=row_dict,
        )

    def _format_datetime(self, value: Any) -> str:
        """Format datetime value to ISO format string.

        Args:
            value: Datetime value (may be None or datetime).

        Returns:
            ISO format datetime string.
        """
        if value is None:
            return datetime.now().isoformat()
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)
