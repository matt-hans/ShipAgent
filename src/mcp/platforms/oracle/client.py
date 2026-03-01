# src/mcp/platforms/oracle/client.py
"""Oracle database client for the standalone platform MCP server.

Extracted from src/mcp/external_sources/clients/oracle.py.
Handles authentication, order fetching with offset pagination, and tracking write-back.
Uses oracledb thin mode (no Oracle client installation required).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.mcp.platforms.oracle.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from src.mcp.platforms.oracle.models import OracleCredentials
from src.services.platform_models import PlatformError, PlatformErrorCode

logger = logging.getLogger(__name__)

# Safe SQL identifier pattern -- alphanumeric + underscore, max 128 chars (CWE-89).
_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,127}$")

# Handle optional oracledb dependency
ORACLEDB_AVAILABLE = False
try:
    import oracledb

    ORACLEDB_AVAILABLE = True
except ImportError:
    oracledb = None  # type: ignore[assignment]

if TYPE_CHECKING:
    import oracledb


def _quote_identifier(name: str) -> str:
    """Quote an Oracle SQL identifier safely (CWE-89).

    Validates the identifier against _SAFE_IDENT pattern, then wraps it in
    double quotes to prevent SQL injection via table or column names.

    Args:
        name: Raw identifier name (table name or column name).

    Returns:
        Double-quoted safe identifier string.

    Raises:
        ValueError: If the name does not match the safe identifier pattern.
    """
    if not _SAFE_IDENT.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return f'"{name}"'


class OracleClient:
    """Oracle database client with offset-based pagination.

    Provides methods for connection testing, order fetching, single-order
    retrieval, and tracking write-back. All SQL queries use parameterized
    bindings and validated identifiers (CWE-89 prevention).
    """

    def __init__(self, credentials: OracleCredentials) -> None:
        """Initialize Oracle client with credentials.

        Validates table identifiers at init time for defense-in-depth.

        Args:
            credentials: Oracle connection credentials.

        Raises:
            ValueError: If table names fail identifier validation.
        """
        self._credentials = credentials
        self._connection: Any = None

        # Validate table identifiers at init time (CWE-89 defense-in-depth)
        _quote_identifier(credentials.orders_table)
        _quote_identifier(credentials.tracking_table)

    async def test_connection(self) -> dict[str, Any]:
        """Test connection by executing SELECT 1 FROM DUAL.

        Returns:
            Dict with connection info on success.

        Raises:
            PlatformError: On connection failure.
        """
        self._check_oracledb()

        try:
            conn = await self._get_connection()
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1 FROM DUAL")
                row = await cursor.fetchone()
                if row is None or row[0] != 1:
                    raise PlatformError(
                        error_code=PlatformErrorCode.UPSTREAM_ERROR,
                        message="Oracle health check returned unexpected result",
                    )
            return {
                "host": self._credentials.host,
                "service_name": self._credentials.service_name,
                "user": self._credentials.user,
            }
        except PlatformError:
            raise
        except Exception as e:
            raise PlatformError(
                error_code=PlatformErrorCode.TRANSIENT,
                message=f"Oracle connection test failed: {e}",
            )

    async def fetch_orders(
        self,
        offset: int = 0,
        since: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """Fetch a page of orders using SQL OFFSET/FETCH pagination.

        Args:
            offset: Row offset for pagination (0-based).
            since: ISO datetime -- only fetch orders updated after this time.
            page_size: Number of orders per page (default 50, max 200).

        Returns:
            Dict with "items", "next_cursor" (next offset as string or None),
            and "watermark" keys matching the platform contract.

        Raises:
            PlatformError: On database errors.
        """
        page_size = min(page_size, MAX_PAGE_SIZE)
        if offset < 0:
            offset = 0

        table = _quote_identifier(self._credentials.orders_table)
        params: dict[str, Any] = {}

        where_clause = "1=1"
        if since:
            where_clause = '"UPDATED_DATE" >= TO_TIMESTAMP(:since, \'YYYY-MM-DD"T"HH24:MI:SS\')'
            # Strip timezone suffix for Oracle TO_TIMESTAMP compatibility
            params["since"] = since.replace("Z", "").split("+")[0]

        # Fetch page_size + 1 to detect if there are more rows
        fetch_count = page_size + 1
        sql = (
            f"SELECT * FROM {table} "
            f"WHERE {where_clause} "
            f'ORDER BY "UPDATED_DATE" ASC NULLS LAST '
            f"OFFSET :offset ROWS FETCH FIRST :fetch_count ROWS ONLY"
        )
        params["offset"] = offset
        params["fetch_count"] = fetch_count

        try:
            conn = await self._get_connection()
            async with conn.cursor() as cursor:
                await cursor.execute(sql, params)
                rows = await cursor.fetchall()
                column_names = [desc[0] for desc in cursor.description]

            items = []
            for row in rows[:page_size]:
                items.append(dict(zip(column_names, row, strict=False)))

            # Determine next cursor (next offset) and watermark
            has_more = len(rows) > page_size
            next_cursor = str(offset + page_size) if has_more else None

            watermark = None
            if items:
                last_updated = items[-1].get("UPDATED_DATE")
                if last_updated is not None:
                    watermark = self._format_datetime(last_updated)

            return {
                "items": items,
                "next_cursor": next_cursor,
                "watermark": watermark,
            }
        except PlatformError:
            raise
        except Exception as e:
            raise PlatformError(
                error_code=PlatformErrorCode.UPSTREAM_ERROR,
                message=f"Oracle order fetch failed: {e}",
            )

    async def get_order(self, order_id: str) -> dict[str, Any] | None:
        """Fetch a single order by ORDER_ID.

        Args:
            order_id: The order identifier (primary key value).

        Returns:
            Order dict or None if not found.

        Raises:
            PlatformError: On database errors.
        """
        table = _quote_identifier(self._credentials.orders_table)
        sql = f'SELECT * FROM {table} WHERE "ORDER_ID" = :order_id'

        try:
            conn = await self._get_connection()
            async with conn.cursor() as cursor:
                await cursor.execute(sql, {"order_id": order_id})
                row = await cursor.fetchone()
                if row is None:
                    return None
                column_names = [desc[0] for desc in cursor.description]
                return dict(zip(column_names, row, strict=False))
        except Exception as e:
            raise PlatformError(
                error_code=PlatformErrorCode.UPSTREAM_ERROR,
                message=f"Oracle error fetching order {order_id}: {e}",
            )

    async def update_tracking(
        self,
        order_id: str,
        tracking_numbers: list[str],
        carrier: str = "UPS",
        tracking_url: str | None = None,
    ) -> dict[str, Any]:
        """Write tracking information back to Oracle.

        Updates the tracking table with the provided tracking details.
        Uses parameterized queries exclusively (CWE-89 prevention).

        Args:
            order_id: The order ID to update.
            tracking_numbers: List of tracking numbers.
            carrier: Carrier name (default: "UPS").
            tracking_url: Optional tracking URL.

        Returns:
            Dict with "success" key.

        Raises:
            PlatformError: On database errors.
        """
        tracking_table = _quote_identifier(self._credentials.tracking_table)
        tracking_number = tracking_numbers[0] if tracking_numbers else ""

        # MERGE to handle insert-or-update (idempotent write-back)
        sql = (
            f"MERGE INTO {tracking_table} t "
            f'USING (SELECT :order_id AS "ORDER_ID" FROM DUAL) s '
            f'ON (t."ORDER_ID" = s."ORDER_ID") '
            f"WHEN MATCHED THEN UPDATE SET "
            f'  t."TRACKING_NUMBER" = :tracking_number, '
            f'  t."CARRIER" = :carrier, '
            f'  t."TRACKING_URL" = :tracking_url, '
            f'  t."UPDATED_DATE" = SYSTIMESTAMP '
            f"WHEN NOT MATCHED THEN INSERT "
            f'  ("ORDER_ID", "TRACKING_NUMBER", "CARRIER", "TRACKING_URL", "UPDATED_DATE") '
            f"VALUES (:order_id, :tracking_number, :carrier, :tracking_url, SYSTIMESTAMP)"
        )

        params = {
            "order_id": order_id,
            "tracking_number": tracking_number,
            "carrier": carrier,
            "tracking_url": tracking_url,
        }

        try:
            conn = await self._get_connection()
            async with conn.cursor() as cursor:
                await cursor.execute(sql, params)
            await conn.commit()
            return {"success": True}
        except Exception as e:
            raise PlatformError(
                error_code=PlatformErrorCode.UPSTREAM_ERROR,
                message=f"Oracle tracking write-back failed for order {order_id}: {e}",
            )

    async def close(self) -> None:
        """Close the database connection.

        Safe to call even if not connected.
        """
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception:
                logger.warning("Error closing Oracle connection", exc_info=True)
            finally:
                self._connection = None

    def _check_oracledb(self) -> None:
        """Check if oracledb is available, raise PlatformError if not.

        Raises:
            PlatformError: If oracledb is not installed.
        """
        if not ORACLEDB_AVAILABLE:
            raise PlatformError(
                error_code=PlatformErrorCode.PERMANENT,
                message=(
                    "oracledb library is not installed. "
                    "Install it with: pip install oracledb"
                ),
            )

    async def _get_connection(self) -> Any:
        """Get or create the database connection.

        Returns:
            Active oracledb async connection.

        Raises:
            PlatformError: On connection failure.
        """
        if self._connection is not None:
            return self._connection

        self._check_oracledb()

        try:
            self._connection = await oracledb.connect_async(
                user=self._credentials.user,
                password=self._credentials.password,
                dsn=self._credentials.dsn,
            )
            return self._connection
        except Exception as e:
            self._connection = None
            raise PlatformError(
                error_code=PlatformErrorCode.AUTH_EXPIRED,
                message=f"Oracle connection failed: {e}",
            )

    @staticmethod
    def _format_datetime(value: Any) -> str:
        """Format a datetime value to ISO format string.

        Args:
            value: Datetime value (may be None, datetime, or string).

        Returns:
            ISO format datetime string.
        """
        if value is None:
            return datetime.now().isoformat()
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)
