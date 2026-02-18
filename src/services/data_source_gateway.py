"""DataSourceGateway protocol — single interface for all data source access.

All external callers (API routes, agent tools, conversation processing)
use this protocol. The MCP-backed implementation is the production default.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DataSourceGateway(Protocol):
    """Protocol for data source access.

    Implementors provide data import, query, schema, and write-back
    operations. The authoritative implementation routes through the
    Data Source MCP server.
    """

    async def import_csv(
        self, file_path: str, delimiter: str = ",", header: bool = True
    ) -> dict[str, Any]:
        """Import CSV file as active data source."""
        ...

    async def import_excel(
        self, file_path: str, sheet: str | None = None, header: bool = True
    ) -> dict[str, Any]:
        """Import Excel sheet as active data source."""
        ...

    async def import_database(
        self,
        connection_string: str,
        query: str,
        schema: str = "public",
        row_key_columns: list[str] | None = None,
    ) -> dict[str, Any]:
        """Import database query results as active data source."""
        ...

    async def import_from_records(
        self, records: list[dict[str, Any]], source_label: str
    ) -> dict[str, Any]:
        """Import flat dicts as active data source."""
        ...

    async def get_source_info(self) -> dict[str, Any] | None:
        """Get metadata about the active data source. None if no source."""
        ...

    async def get_source_info_typed(self) -> Any:
        """Get source info as DataSourceInfo for backward compat.

        Returns data_source_mcp_client.DataSourceInfo if source active, None
        otherwise. Used by conversations.py and system_prompt.py which expect
        typed attributes.
        """
        ...

    async def get_source_signature(self) -> dict[str, Any] | None:
        """Get stable source signature for replay safety checks.

        Returns dict matching DataSourceService.get_source_signature() contract:
        {"source_type": str, "source_ref": str, "schema_fingerprint": str}
        or None if no source is active.
        """
        ...

    async def get_rows_by_filter(
        self,
        where_sql: str | None = None,
        limit: int = 100,
        offset: int = 0,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Get rows matching a parameterized WHERE clause as flat dicts.

        Args:
            where_sql: Parameterized WHERE condition ($1, $2 placeholders),
                or None for all rows. Gateway normalizes None to "1=1".
            limit: Maximum rows to return.
            offset: Number of rows to skip.
            params: Positional parameter values for $N placeholders.
        """
        ...

    async def query_data(self, sql: str) -> dict[str, Any]:
        """Execute a SELECT query against active data source."""
        ...

    async def write_back_single(
        self,
        row_number: int,
        tracking_number: str,
        shipped_at: str | None = None,
    ) -> None:
        """Write tracking number back to source for a single row.

        Args:
            row_number: 1-based row number.
            tracking_number: UPS tracking number.
            shipped_at: ISO8601 timestamp (optional).

        Raises:
            Exception: On write-back failure.
        """
        ...

    async def write_back_batch(
        self, updates: dict[int, dict[str, str]]
    ) -> dict[str, Any]:
        """Write tracking numbers back to source for multiple rows.

        Args:
            updates: {row_number: {"tracking_number": "...", "shipped_at": "..."}}

        Returns:
            Dict with success count, failure count.
        """
        ...

    async def disconnect(self) -> None:
        """Disconnect/clear active data source."""
        ...

    async def get_schema(self) -> dict[str, Any]:
        """Get column schema of active data source."""
        ...

    async def list_sheets(self, file_path: str) -> dict[str, Any]:
        """List sheets in an Excel file."""
        ...

    async def get_commodities_bulk(
        self, order_ids: list[int | str],
    ) -> dict[int | str, list[dict[str, Any]]]:
        """Get commodities grouped by order_id for international shipments.

        Args:
            order_ids: List of order IDs to retrieve commodities for.

        Returns:
            Dict mapping order_id to list of commodity dicts.
            Missing orders are omitted from the result.
        """
        ...

    async def get_column_samples(
        self, max_samples: int = 5
    ) -> dict[str, list[Any]]:
        """Get sample distinct values for each column.

        Args:
            max_samples: Maximum distinct values per column (default 5).

        Returns:
            Dict mapping column names to lists of sample values.
        """
        ...

    async def list_tables(
        self, connection_string: str, schema: str = "public"
    ) -> dict[str, Any]:
        """List tables in a database."""
        ...
