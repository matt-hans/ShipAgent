"""Service for managing local data source connections (CSV, Excel, Database).

Uses direct adapter imports (not MCP stdio) for efficiency.
Maintains an in-memory DuckDB connection with imported data.
Singleton pattern — one active data source at a time.

Example:
    svc = DataSourceService.get_instance()
    result = await svc.import_csv("/path/to/orders.csv")
    rows = await svc.get_rows_by_filter("state = 'CA'")
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger(__name__)


class SchemaColumnInfo:
    """Lightweight column schema info (avoids importing from data_source package).

    Attributes:
        name: Column name.
        type: Column type string.
        nullable: Whether column allows nulls.
    """

    def __init__(self, name: str, type: str, nullable: bool = True) -> None:
        """Initialize SchemaColumnInfo.

        Args:
            name: Column name.
            type: Column type string.
            nullable: Whether column allows nulls.
        """
        self.name = name
        self.type = type
        self.nullable = nullable


class DataSourceInfo:
    """Metadata about the currently connected data source.

    Attributes:
        source_type: 'csv', 'excel', or 'database'
        file_path: Path to the source file (if file-based)
        columns: List of column schema info
        row_count: Number of imported rows
    """

    def __init__(
        self,
        source_type: str,
        file_path: str | None,
        columns: list[SchemaColumnInfo],
        row_count: int,
    ) -> None:
        """Initialize DataSourceInfo.

        Args:
            source_type: Type of data source ('csv', 'excel', 'database').
            file_path: Path to the source file, or None for database.
            columns: List of discovered column schemas.
            row_count: Number of rows imported.
        """
        self.source_type = source_type
        self.file_path = file_path
        self.columns = columns
        self.row_count = row_count


class DataSourceService:
    """Manages local data source connections.

    Singleton service that maintains an in-memory DuckDB connection
    with the currently imported data. Supports CSV, Excel, and database sources.
    """

    _instance: "DataSourceService | None" = None

    def __init__(self) -> None:
        """Initialize with no active connection."""
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._source_info: DataSourceInfo | None = None
        self._original_file_path: str | None = None

    @classmethod
    def get_instance(cls) -> "DataSourceService":
        """Get or create the singleton instance.

        Returns:
            The singleton DataSourceService instance.
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton for testing."""
        if cls._instance is not None:
            cls._instance.disconnect()
            cls._instance = None

    def _ensure_connection(self) -> duckdb.DuckDBPyConnection:
        """Create a fresh DuckDB connection, replacing any existing one.

        Returns:
            A new in-memory DuckDB connection.
        """
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = duckdb.connect(":memory:")
        return self._conn

    @staticmethod
    def _to_schema_info(adapter_columns: list) -> list[SchemaColumnInfo]:
        """Convert adapter SchemaColumn objects to our lightweight SchemaColumnInfo.

        Args:
            adapter_columns: List of SchemaColumn from adapter ImportResult.

        Returns:
            List of SchemaColumnInfo.
        """
        return [
            SchemaColumnInfo(name=col.name, type=col.type, nullable=col.nullable)
            for col in adapter_columns
        ]

    async def import_csv(
        self, file_path: str, delimiter: str = ","
    ) -> dict[str, Any]:
        """Import a CSV file into the active DuckDB connection.

        Args:
            file_path: Absolute path to the CSV file.
            delimiter: Column delimiter (default: comma).

        Returns:
            Dict with row_count, columns, warnings, and source_type.

        Raises:
            FileNotFoundError: If file does not exist.
        """
        # Lazy import to avoid EDI adapter chain
        from src.mcp.data_source.adapters.csv_adapter import CSVAdapter

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        conn = self._ensure_connection()
        adapter = CSVAdapter()
        result = adapter.import_data(
            conn, file_path=str(path.resolve()), delimiter=delimiter
        )

        self._source_info = DataSourceInfo(
            source_type="csv",
            file_path=str(path.resolve()),
            columns=self._to_schema_info(result.columns),
            row_count=result.row_count,
        )
        self._original_file_path = str(path.resolve())

        logger.info(
            "Imported CSV %s: %d rows, %d columns",
            path.name,
            result.row_count,
            len(result.columns),
        )

        self._auto_save_csv(str(path.resolve()), result.row_count, len(result.columns))

        return result

    async def import_excel(
        self, file_path: str, sheet: str | None = None
    ) -> dict[str, Any]:
        """Import an Excel file into the active DuckDB connection.

        Args:
            file_path: Absolute path to the Excel file.
            sheet: Sheet name (default: first sheet).

        Returns:
            Dict with row_count, columns, warnings, and source_type.

        Raises:
            FileNotFoundError: If file does not exist.
        """
        from src.mcp.data_source.adapters.excel_adapter import ExcelAdapter

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Excel file not found: {file_path}")

        conn = self._ensure_connection()
        adapter = ExcelAdapter()
        result = adapter.import_data(
            conn, file_path=str(path.resolve()), sheet=sheet
        )

        self._source_info = DataSourceInfo(
            source_type="excel",
            file_path=str(path.resolve()),
            columns=self._to_schema_info(result.columns),
            row_count=result.row_count,
        )
        self._original_file_path = str(path.resolve())

        logger.info(
            "Imported Excel %s: %d rows, %d columns",
            path.name,
            result.row_count,
            len(result.columns),
        )

        self._auto_save_excel(str(path.resolve()), sheet, result.row_count, len(result.columns))

        return result

    async def import_database(
        self, connection_string: str, query: str
    ) -> dict[str, Any]:
        """Import data from a database via DuckDB's extension system.

        Args:
            connection_string: Database connection URL.
            query: SQL query to execute.

        Returns:
            Dict with row_count, columns, warnings, and source_type.
        """
        from src.mcp.data_source.adapters.db_adapter import DatabaseAdapter

        conn = self._ensure_connection()
        adapter = DatabaseAdapter()
        result = adapter.import_data(
            conn, connection_string=connection_string, query=query
        )

        self._source_info = DataSourceInfo(
            source_type="database",
            file_path=None,
            columns=self._to_schema_info(result.columns),
            row_count=result.row_count,
        )
        self._original_file_path = None

        logger.info(
            "Imported database query: %d rows, %d columns",
            result.row_count,
            len(result.columns),
        )

        self._auto_save_database(connection_string, query, result.row_count, len(result.columns))

        return result

    def import_from_records(
        self,
        records: list[dict[str, Any]],
        source_type: str = "platform",
        source_label: str | None = None,
    ) -> DataSourceInfo:
        """Import data from a list of dicts into the active DuckDB connection.

        Used for platform sources (e.g. Shopify orders) where data arrives
        as structured records rather than files.

        Args:
            records: List of row dictionaries.
            source_type: Source type label (e.g. 'shopify').
            source_label: Human-readable label (e.g. store name).

        Returns:
            DataSourceInfo for the imported data.

        Raises:
            ValueError: If records list is empty.
        """
        if not records:
            raise ValueError("No records to import")

        conn = self._ensure_connection()

        # Get column names from the first record
        col_names = list(records[0].keys())

        # Build CREATE TABLE with all VARCHAR columns (DuckDB will auto-cast)
        col_defs = ", ".join(f'"{c}" VARCHAR' for c in col_names)
        conn.execute(f"CREATE TABLE imported_data ({col_defs})")

        # Insert rows using parameterized queries
        placeholders = ", ".join("?" for _ in col_names)
        insert_sql = f"INSERT INTO imported_data VALUES ({placeholders})"
        for record in records:
            values = [str(record.get(c, "")) if record.get(c) is not None else None for c in col_names]
            conn.execute(insert_sql, values)

        # Build schema info from DuckDB table metadata
        result = conn.execute("DESCRIBE imported_data")
        columns: list[SchemaColumnInfo] = []
        for row in result.fetchall():
            columns.append(SchemaColumnInfo(name=row[0], type=row[1], nullable=True))

        self._source_info = DataSourceInfo(
            source_type=source_type,
            file_path=source_label,
            columns=columns,
            row_count=len(records),
        )

        logger.info(
            "Imported %d records from %s (%s): %d columns",
            len(records),
            source_type,
            source_label or "unknown",
            len(columns),
        )

        return self._source_info

    async def get_schema(self) -> list[SchemaColumnInfo]:
        """Get the schema of the currently imported data.

        Returns:
            List of SchemaColumnInfo objects.

        Raises:
            RuntimeError: If no data source is connected.
        """
        if self._source_info is None:
            raise RuntimeError("No data source connected")
        return self._source_info.columns

    async def get_rows_by_filter(
        self, where_clause: str | None = None, limit: int = 250
    ) -> list[dict[str, Any]]:
        """Fetch rows from imported data, optionally filtered by SQL WHERE clause.

        Args:
            where_clause: SQL WHERE clause (without 'WHERE' keyword). None for all rows.
            limit: Maximum number of rows to return.

        Returns:
            List of row dictionaries.

        Raises:
            RuntimeError: If no data source is connected.
        """
        if self._conn is None or self._source_info is None:
            raise RuntimeError("No data source connected")

        query = "SELECT *, rowid + 1 AS _row_number FROM imported_data"
        if where_clause and where_clause.strip() and where_clause.strip() not in ("1=1", "TRUE"):
            query += f" WHERE {where_clause}"
        query += f" LIMIT {limit}"

        try:
            result = self._conn.execute(query)
            columns = [desc[0] for desc in result.description]
            rows = []
            for row_tuple in result.fetchall():
                row_dict = dict(zip(columns, row_tuple))
                rows.append(row_dict)
            return rows
        except Exception as e:
            logger.error("Filter query failed: %s — query: %s", e, query)
            raise

    async def get_all_rows(self, limit: int = 10000) -> list[dict[str, Any]]:
        """Fetch all rows from imported data with row numbers.

        Args:
            limit: Maximum number of rows to return.

        Returns:
            List of row dictionaries with _row_number.

        Raises:
            RuntimeError: If no data source is connected.
        """
        return await self.get_rows_by_filter(where_clause=None, limit=limit)

    def get_source_info(self) -> DataSourceInfo | None:
        """Get info about the currently connected data source.

        Returns:
            DataSourceInfo if connected, None otherwise.
        """
        return self._source_info

    def disconnect(self) -> None:
        """Disconnect and clear the active data source."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._source_info = None
        self._original_file_path = None
        logger.info("Data source disconnected")

    def compute_checksum(self, row_data: dict[str, Any]) -> str:
        """Compute SHA-256 checksum for a data row.

        Args:
            row_data: Dictionary of column name to value.

        Returns:
            Hex-encoded SHA-256 checksum.
        """
        canonical = json.dumps(row_data, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def write_back(
        self, row_number: int, tracking_number: str
    ) -> dict[str, Any]:
        """Write tracking number back to the source file.

        Currently supports CSV write-back. Excel write-back is planned.

        Args:
            row_number: 1-indexed row number in the source.
            tracking_number: UPS tracking number to write.

        Returns:
            Dict with status and details.
        """
        if self._source_info is None:
            return {"status": "error", "message": "No data source connected"}

        if self._source_info.source_type == "csv" and self._original_file_path:
            return self._write_back_csv(row_number, tracking_number)

        return {
            "status": "skipped",
            "message": f"Write-back not supported for {self._source_info.source_type}",
        }

    def _auto_save_csv(
        self, file_path: str, row_count: int, column_count: int
    ) -> None:
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

    def _auto_save_excel(
        self, file_path: str, sheet_name: str | None, row_count: int, column_count: int
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

    def _auto_save_database(
        self, connection_string: str, query: str, row_count: int, column_count: int
    ) -> None:
        """Persist database source display metadata for future reconnection.

        Extracts host/port/db_name from the connection string. Credentials
        are never stored.

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

    def _write_back_csv(
        self, row_number: int, tracking_number: str
    ) -> dict[str, Any]:
        """Write tracking number to CSV source file.

        Adds or updates a 'tracking_number' column in the source CSV.

        Args:
            row_number: 1-indexed row number.
            tracking_number: Tracking number to write.

        Returns:
            Dict with status and file path.
        """
        import csv

        file_path = self._original_file_path
        if not file_path:
            return {"status": "error", "message": "Original file path not available"}

        try:
            # Read existing CSV
            with open(file_path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)

            if not rows:
                return {"status": "error", "message": "CSV file is empty"}

            headers = rows[0]

            # Add tracking_number column if not present
            if "tracking_number" not in headers:
                headers.append("tracking_number")
                for i in range(1, len(rows)):
                    rows[i].append("")

            tracking_col_idx = headers.index("tracking_number")

            # Update the specific row (row_number is 1-indexed, rows[0] is header)
            if row_number < 1 or row_number >= len(rows):
                return {
                    "status": "error",
                    "message": f"Row {row_number} out of range (1-{len(rows)-1})",
                }

            rows[row_number][tracking_col_idx] = tracking_number

            # Write back
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerows(rows)

            return {
                "status": "success",
                "file_path": file_path,
                "row_number": row_number,
                "tracking_number": tracking_number,
            }

        except Exception as e:
            logger.error("CSV write-back failed: %s", e)
            return {"status": "error", "message": str(e)}
