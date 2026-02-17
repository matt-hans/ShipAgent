"""MCP-backed implementation of DataSourceGateway.

Routes all data source operations through the Data Source MCP server
via a process-global, long-lived stdio connection.
"""

import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from mcp import StdioServerParameters

from src.services.mcp_client import MCPClient
from src.services.mapping_cache import invalidate as invalidate_mapping_cache


# -- Gateway-local DTOs (no dependency on legacy DataSourceService) -----------


@dataclass
class SchemaColumnInfo:
    """Column metadata returned by the data source gateway."""

    name: str
    type: str = "VARCHAR"
    nullable: bool = True


@dataclass
class DataSourceInfo:
    """Data source metadata returned by the data source gateway."""

    source_type: str
    file_path: str | None = None
    columns: list[SchemaColumnInfo] = field(default_factory=list)
    row_count: int = 0
    signature: str | None = None

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_VENV_PYTHON = os.path.join(_PROJECT_ROOT, ".venv", "bin", "python3")


def _get_python_command() -> str:
    """Return the preferred Python interpreter for MCP subprocesses.

    Honors MCP_PYTHON_PATH when explicitly configured.
    Prioritizes the project virtual environment to ensure all MCP
    subprocesses use the same dependency set as the backend.
    Falls back to the current interpreter when .venv Python is missing
    (e.g. in worktrees or CI environments).
    """
    override = os.environ.get("MCP_PYTHON_PATH", "").strip()
    if override:
        return override
    if os.path.exists(_VENV_PYTHON):
        return _VENV_PYTHON
    return sys.executable


class DataSourceMCPClient:
    """MCP-backed DataSourceGateway implementation.

    Process-global singleton. All data access routes through the
    Data Source MCP server over stdio.

    Attributes:
        _mcp: Underlying generic MCPClient instance.
    """

    def __init__(self) -> None:
        """Initialize Data Source MCP client."""
        self._mcp = MCPClient(
            server_params=self._build_server_params(),
            max_retries=1,
            base_delay=0.5,
        )

    def _build_server_params(self) -> StdioServerParameters:
        """Build StdioServerParameters for the Data Source MCP server.

        Returns:
            Configured StdioServerParameters.
        """
        return StdioServerParameters(
            command=_get_python_command(),
            args=["-m", "src.mcp.data_source.server"],
            env={
                "PYTHONPATH": _PROJECT_ROOT,
                "PATH": os.environ.get("PATH", ""),
            },
        )

    async def connect(self) -> None:
        """Connect to Data Source MCP server if not already connected."""
        if self._mcp.is_connected:
            return
        await self._mcp.connect()
        logger.info("Data Source MCP client connected")

    async def disconnect_mcp(self) -> None:
        """Disconnect from Data Source MCP server."""
        await self._mcp.disconnect()

    @property
    def is_connected(self) -> bool:
        """Whether the MCP session is connected."""
        return self._mcp.is_connected

    async def _ensure_connected(self) -> None:
        """Ensure MCP connection is active before making calls."""
        if not self._mcp.is_connected:
            await self.connect()

    @staticmethod
    def _is_transport_error(error: Exception) -> bool:
        """Classify transport/session failures that warrant reconnect."""
        name = type(error).__name__
        if name in {"ClosedResourceError", "BrokenResourceError", "EndOfStream"}:
            return True
        text = str(error).lower()
        patterns = (
            "broken pipe",
            "connection reset",
            "closed resource",
            "broken resource",
            "end of stream",
            "session not initialized",
            "transport",
            "connection closed",
        )
        return any(p in text for p in patterns)

    async def _call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Call MCP tool with one reconnect retry on transport failures."""
        await self._ensure_connected()
        try:
            return await self._mcp.call_tool(name, args)
        except Exception as e:
            if not self._is_transport_error(e):
                raise
            logger.warning(
                "Data Source MCP transport failure during '%s', reconnecting once: %s [%s]",
                name,
                e,
                type(e).__name__,
            )
            await self.disconnect_mcp()
            await self.connect()
            return await self._mcp.call_tool(name, args)

    # -- Import operations -------------------------------------------------

    async def import_csv(
        self, file_path: str, delimiter: str = ",", header: bool = True
    ) -> dict[str, Any]:
        """Import CSV file as active data source.

        Auto-saves source metadata for future reconnection on success.
        """
        result = await self._call_tool("import_csv", {
            "file_path": file_path, "delimiter": delimiter, "header": header,
        })
        invalidate_mapping_cache()
        self._auto_save_csv(
            file_path, result.get("row_count", 0), len(result.get("columns", []))
        )
        return result

    async def import_excel(
        self, file_path: str, sheet: str | None = None, header: bool = True
    ) -> dict[str, Any]:
        """Import Excel sheet as active data source.

        Auto-saves source metadata for future reconnection on success.
        """
        args: dict[str, Any] = {"file_path": file_path, "header": header}
        if sheet:
            args["sheet"] = sheet
        result = await self._call_tool("import_excel", args)
        invalidate_mapping_cache()
        self._auto_save_excel(
            file_path, sheet, result.get("row_count", 0), len(result.get("columns", []))
        )
        return result

    async def import_database(
        self, connection_string: str, query: str, schema: str = "public"
    ) -> dict[str, Any]:
        """Import database query results as active data source.

        Auto-saves source display metadata (no credentials) for future reconnection.
        """
        result = await self._call_tool("import_database", {
            "connection_string": connection_string,
            "query": query,
            "schema": schema,
        })
        invalidate_mapping_cache()
        self._auto_save_database(
            connection_string, query,
            result.get("row_count", 0), len(result.get("columns", [])),
        )
        return result

    async def import_from_records(
        self, records: list[dict[str, Any]], source_label: str
    ) -> dict[str, Any]:
        """Import flat dicts as active data source."""
        result = await self._call_tool("import_records", {
            "records": records,
            "source_label": source_label,
        })
        invalidate_mapping_cache()
        return result

    # -- Query operations --------------------------------------------------

    async def get_source_info(self) -> dict[str, Any] | None:
        """Get metadata about the active data source.

        Returns None if no source is active.
        """
        result = await self._call_tool("get_source_info", {})
        if not result.get("active", False):
            return None
        return result

    async def get_source_info_typed(self) -> DataSourceInfo | None:
        """Get source info as a DataSourceInfo object.

        conversations.py and system_prompt.py expect DataSourceInfo with typed
        attributes. This method converts the gateway dict to that format.

        Returns:
            DataSourceInfo if source active, None otherwise.
        """
        info = await self.get_source_info()
        if info is None:
            return None

        columns = [
            SchemaColumnInfo(
                name=col.get("name", ""),
                type=col.get("type", "VARCHAR"),
                nullable=col.get("nullable", True),
            )
            for col in info.get("columns", [])
        ]
        return DataSourceInfo(
            source_type=info.get("source_type", "unknown"),
            file_path=info.get("path"),
            columns=columns,
            row_count=info.get("row_count", 0),
            signature=info.get("signature"),
        )

    async def get_source_signature(self) -> dict[str, Any] | None:
        """Get stable source signature matching DataSourceService contract.

        Returns:
            {"source_type": str, "source_ref": str, "schema_fingerprint": str}
            or None if no source is active.
        """
        info = await self.get_source_info()
        if info is None:
            return None
        return {
            "source_type": info.get("source_type", "unknown"),
            "source_ref": info.get("path") or info.get("query") or "",
            "schema_fingerprint": info.get("signature", ""),
        }

    async def get_schema(self) -> dict[str, Any]:
        """Get column schema of active data source."""
        return await self._call_tool("get_schema", {})

    async def get_rows_by_filter(
        self,
        where_sql: str | None = None,
        limit: int = 100,
        offset: int = 0,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Get rows matching a parameterized WHERE clause.

        Backward-compatible helper that returns only normalized rows.
        For authoritative cardinality, use get_rows_with_count().
        """
        result = await self.get_rows_with_count(
            where_sql=where_sql,
            limit=limit,
            offset=offset,
            params=params,
        )
        return result["rows"]

    async def get_rows_with_count(
        self,
        where_sql: str | None = None,
        limit: int = 100,
        offset: int = 0,
        params: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Get normalized rows and authoritative total_count for a filter.

        Args:
            where_sql: Parameterized WHERE condition ($1, $2, ... placeholders).
            limit: Maximum rows to return.
            offset: Number of rows to skip.
            params: Positional parameter values for $N placeholders.

        MCP returns {rows:[{row_number, data, checksum}]}.
        This method normalizes to flat dicts with _row_number and _checksum.
        """
        effective_sql = where_sql
        # Normalize None/empty to "1=1" so the MCP tool's
        # "WHERE {where_sql}" template doesn't break.
        effective_sql = effective_sql if effective_sql and effective_sql.strip() else "1=1"
        query_params = params if params is not None else []
        tool_args: dict[str, Any] = {
            "where_sql": effective_sql,
            "limit": limit,
            "offset": offset,
        }
        if query_params:
            tool_args["params"] = query_params
        result = await self._call_tool("get_rows_by_filter", tool_args)
        raw_rows = result.get("rows", [])
        return {
            "rows": self._normalize_rows(raw_rows),
            "total_count": int(result.get("total_count", len(raw_rows))),
        }

    async def get_column_samples(self, max_samples: int = 5) -> dict[str, list[Any]]:
        """Get sample distinct values for each column.

        Args:
            max_samples: Maximum distinct values per column (default 5).

        Returns:
            Dict mapping column names to lists of sample values.
        """
        return await self._call_tool(
            "get_column_samples", {"max_samples": max_samples}
        )

    async def query_data(self, sql: str) -> dict[str, Any]:
        """Execute a SELECT query against active data source."""
        return await self._call_tool("query_data", {"sql": sql})

    # -- Write-back --------------------------------------------------------

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
            Exception: On MCP tool call failure.
        """
        await self._call_tool("write_back", {
            "row_number": row_number,
            "tracking_number": tracking_number,
            "shipped_at": shipped_at,
        })

    async def write_back_batch(
        self, updates: dict[int, dict[str, str]]
    ) -> dict[str, Any]:
        """Write tracking numbers back to source for multiple rows.

        Iterates over individual write_back MCP tool calls.
        Atomicity tradeoff: individual rows are atomic, batch is not.

        Args:
            updates: {row_number: {"tracking_number": "...", "shipped_at": "..."}}

        Returns:
            Dict with success_count, failure_count, errors.
        """
        success_count = 0
        failure_count = 0
        errors: list[dict[str, Any]] = []

        for row_number, data in updates.items():
            try:
                await self._call_tool("write_back", {
                    "row_number": row_number,
                    "tracking_number": data["tracking_number"],
                    "shipped_at": data.get("shipped_at"),
                })
                success_count += 1
            except Exception as e:
                failure_count += 1
                errors.append({"row_number": row_number, "error": str(e)})

        return {
            "success_count": success_count,
            "failure_count": failure_count,
            "errors": errors,
        }

    # -- Commodity operations -----------------------------------------------

    async def get_commodities_bulk(
        self, order_ids: list[int | str],
    ) -> dict[int | str, list[dict[str, Any]]]:
        """Get commodities for multiple orders via MCP tool.

        Args:
            order_ids: List of order IDs to retrieve commodities for.

        Returns:
            Dict mapping order_id to list of commodity dicts.
        """
        result = await self._call_tool("get_commodities_bulk", {
            "order_ids": order_ids,
        })
        if not result:
            return {}
        # MCP returns dict with string keys; normalize to match input type
        normalized: dict[int | str, list[dict[str, Any]]] = {}
        for k, v in result.items():
            try:
                normalized[int(k) if order_ids and isinstance(order_ids[0], int) else k] = v
            except (ValueError, TypeError):
                normalized[k] = v
        return normalized

    # -- Data source lifecycle ---------------------------------------------

    async def disconnect(self) -> None:
        """Clear active data source (not the MCP connection).

        Calls the clear_source MCP tool which drops the imported_data table
        and clears the current_source metadata. Mirrors the existing
        DataSourceService.disconnect() behavior.
        """
        await self._call_tool("clear_source", {})
        invalidate_mapping_cache()

    async def list_sheets(self, file_path: str) -> dict[str, Any]:
        """List sheets in an Excel file."""
        return await self._call_tool("list_sheets", {"file_path": file_path})

    async def list_tables(
        self, connection_string: str, schema: str = "public"
    ) -> dict[str, Any]:
        """List tables in a database."""
        return await self._call_tool("list_tables", {
            "connection_string": connection_string, "schema": schema,
        })

    # -- Internal helpers --------------------------------------------------

    @staticmethod
    def _normalize_rows(
        raw_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Normalize MCP row format to flat dicts.

        Input:  [{row_number: 1, data: {col: val}, checksum: "abc"}, ...]
        Output: [{col: val, _row_number: 1, _checksum: "abc"}, ...]
        """
        normalized = []
        for row in raw_rows:
            flat = dict(row.get("data", {}))
            flat["_row_number"] = row.get("row_number")
            flat["_checksum"] = row.get("checksum")
            normalized.append(flat)
        return normalized

    # -- Auto-save hooks (best-effort persistence) -------------------------

    @staticmethod
    def _auto_save_csv(file_path: str, row_count: int, column_count: int) -> None:
        """Persist CSV source metadata for future reconnection.

        Args:
            file_path: Absolute path to CSV file.
            row_count: Number of rows imported.
            column_count: Number of columns discovered.
        """
        try:
            from src.db.connection import get_db_context
            from src.services.saved_data_source_service import SavedDataSourceService

            with get_db_context() as db:
                SavedDataSourceService.save_or_update_csv(
                    db, file_path, row_count, column_count
                )
        except Exception as e:
            logger.warning("Auto-save CSV source failed (non-critical): %s", e)

    @staticmethod
    def _auto_save_excel(
        file_path: str, sheet_name: str | None, row_count: int, column_count: int
    ) -> None:
        """Persist Excel source metadata for future reconnection.

        Args:
            file_path: Absolute path to Excel file.
            sheet_name: Sheet name (None for default).
            row_count: Number of rows imported.
            column_count: Number of columns discovered.
        """
        try:
            from src.db.connection import get_db_context
            from src.services.saved_data_source_service import SavedDataSourceService

            with get_db_context() as db:
                SavedDataSourceService.save_or_update_excel(
                    db, file_path, sheet_name, row_count, column_count
                )
        except Exception as e:
            logger.warning("Auto-save Excel source failed (non-critical): %s", e)

    @staticmethod
    def _auto_save_database(
        connection_string: str, query: str, row_count: int, column_count: int
    ) -> None:
        """Persist database source display metadata for future reconnection.

        Credentials are never stored — only host/port/db_name for display.

        Args:
            connection_string: Database connection URL.
            query: SQL query used for import.
            row_count: Number of rows imported.
            column_count: Number of columns discovered.
        """
        try:
            from src.db.connection import get_db_context
            from src.services.saved_data_source_service import (
                SavedDataSourceService,
                parse_db_connection_string,
            )

            parsed = parse_db_connection_string(connection_string)
            with get_db_context() as db:
                SavedDataSourceService.save_or_update_database(
                    db,
                    host=parsed["host"],
                    port=parsed["port"],
                    db_name=parsed["db_name"],
                    query=query,
                    row_count=row_count,
                    column_count=column_count,
                )
        except Exception as e:
            logger.warning("Auto-save database source failed (non-critical): %s", e)
