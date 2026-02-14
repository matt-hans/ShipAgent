"""MCP-backed implementation of DataSourceGateway.

Routes all data source operations through the Data Source MCP server
via a process-global, long-lived stdio connection.
"""

import logging
import os
from typing import Any

from mcp import StdioServerParameters

from src.services.mcp_client import MCPClient

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_VENV_PYTHON = os.path.join(_PROJECT_ROOT, ".venv", "bin", "python3")


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
            command=_VENV_PYTHON,
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

    # -- Import operations -------------------------------------------------

    async def import_csv(
        self, file_path: str, delimiter: str = ",", header: bool = True
    ) -> dict[str, Any]:
        """Import CSV file as active data source."""
        await self._ensure_connected()
        return await self._mcp.call_tool("import_csv", {
            "file_path": file_path, "delimiter": delimiter, "header": header,
        })

    async def import_excel(
        self, file_path: str, sheet: str | None = None, header: bool = True
    ) -> dict[str, Any]:
        """Import Excel sheet as active data source."""
        await self._ensure_connected()
        args: dict[str, Any] = {"file_path": file_path, "header": header}
        if sheet:
            args["sheet"] = sheet
        return await self._mcp.call_tool("import_excel", args)

    async def import_database(
        self, connection_string: str, query: str, schema: str = "public"
    ) -> dict[str, Any]:
        """Import database query results as active data source."""
        await self._ensure_connected()
        return await self._mcp.call_tool("import_database", {
            "connection_string": connection_string,
            "query": query,
            "schema": schema,
        })

    async def import_from_records(
        self, records: list[dict[str, Any]], source_label: str
    ) -> dict[str, Any]:
        """Import flat dicts as active data source."""
        await self._ensure_connected()
        return await self._mcp.call_tool("import_records", {
            "records": records,
            "source_label": source_label,
        })

    # -- Query operations --------------------------------------------------

    async def get_source_info(self) -> dict[str, Any] | None:
        """Get metadata about the active data source.

        Returns None if no source is active.
        """
        await self._ensure_connected()
        result = await self._mcp.call_tool("get_source_info", {})
        if not result.get("active", False):
            return None
        return result

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
        await self._ensure_connected()
        return await self._mcp.call_tool("get_schema", {})

    async def get_rows_by_filter(
        self, where_clause: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Get rows matching a WHERE clause, normalized to flat dicts.

        MCP tool requires a non-None where_clause string for its SQL
        template. Gateway normalizes None to "1=1" (all rows).

        MCP returns {rows:[{row_number, data, checksum}]}.
        This method normalizes to flat dicts with _row_number and _checksum.
        """
        await self._ensure_connected()
        # Normalize None/empty to "1=1" so the MCP tool's
        # "WHERE {where_clause}" template doesn't break.
        effective_clause = where_clause if where_clause and where_clause.strip() else "1=1"
        result = await self._mcp.call_tool("get_rows_by_filter", {
            "where_clause": effective_clause,
            "limit": limit,
            "offset": offset,
        })
        return self._normalize_rows(result.get("rows", []))

    async def query_data(self, sql: str) -> dict[str, Any]:
        """Execute a SELECT query against active data source."""
        await self._ensure_connected()
        return await self._mcp.call_tool("query_data", {"sql": sql})

    # -- Write-back --------------------------------------------------------

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
        await self._ensure_connected()
        success_count = 0
        failure_count = 0
        errors: list[dict[str, Any]] = []

        for row_number, data in updates.items():
            try:
                await self._mcp.call_tool("write_back", {
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

    # -- Data source lifecycle ---------------------------------------------

    async def disconnect(self) -> None:
        """Clear active data source (not the MCP connection).

        Calls the clear_source MCP tool which drops the imported_data table
        and clears the current_source metadata. Mirrors the existing
        DataSourceService.disconnect() behavior.
        """
        await self._ensure_connected()
        await self._mcp.call_tool("clear_source", {})

    async def list_sheets(self, file_path: str) -> dict[str, Any]:
        """List sheets in an Excel file."""
        await self._ensure_connected()
        return await self._mcp.call_tool("list_sheets", {"file_path": file_path})

    async def list_tables(
        self, connection_string: str, schema: str = "public"
    ) -> dict[str, Any]:
        """List tables in a database."""
        await self._ensure_connected()
        return await self._mcp.call_tool("list_tables", {
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
