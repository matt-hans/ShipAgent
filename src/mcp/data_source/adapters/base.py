"""Abstract base class for all data source adapters.

Each adapter handles importing data from a specific source type (CSV, Excel, database)
into DuckDB. The adapter pattern allows consistent interface across different sources
while encapsulating source-specific import logic.

Per CONTEXT.md:
- One source at a time (importing replaces previous)
- Ephemeral session model (data lives in memory)
- Import all rows, flag invalid ones (no threshold)
- Silent skip for empty rows
- Best-effort parsing with string fallback
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

from src.mcp.data_source.models import SOURCE_ROW_NUM_COLUMN, ImportResult


class BaseSourceAdapter(ABC):
    """Abstract base class for data source adapters.

    Concrete implementations must provide:
    - source_type: Identifier for this adapter type
    - import_data: Import data into DuckDB and return schema info

    get_metadata() has a default implementation that queries the
    imported_data table. Override in subclasses that need custom metadata.

    Example implementation:
        class CSVAdapter(BaseSourceAdapter):
            @property
            def source_type(self) -> str:
                return "csv"

            def import_data(self, conn, **kwargs) -> ImportResult:
                # CSV-specific import logic
                pass
    """

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Return the adapter's source type identifier.

        Returns:
            Source type string: 'csv', 'excel', 'postgres', 'mysql'
        """
        ...

    @abstractmethod
    def import_data(
        self, conn: "DuckDBPyConnection", **kwargs
    ) -> ImportResult:
        """Import data from the source into DuckDB.

        The implementation should:
        1. Read data from the source (file path, connection string, etc.)
        2. Create or replace the 'imported_data' table in DuckDB
        3. Discover schema with type inference
        4. Handle errors gracefully (flag invalid rows, don't fail)
        5. Return ImportResult with schema and statistics

        Args:
            conn: Active DuckDB connection (in-memory)
            **kwargs: Source-specific arguments:
                - CSV: file_path, delimiter, encoding
                - Excel: file_path, sheet_name
                - Database: connection_string, query

        Returns:
            ImportResult with row_count, columns, warnings, source_type

        Raises:
            FileNotFoundError: If file source doesn't exist
            ConnectionError: If database source is unreachable
        """
        ...

    def get_metadata(self, conn: "DuckDBPyConnection") -> dict:
        """Return metadata about the imported data.

        Default implementation queries the imported_data table for row count
        and column count. Subclasses may override for custom metadata
        (e.g., credentials-safe database connection info).

        Args:
            conn: Active DuckDB connection with imported_data table.

        Returns:
            Dictionary with row_count, column_count, and source_type.
            Returns error dict if no data imported.
        """
        try:
            row_count = conn.execute(
                "SELECT COUNT(*) FROM imported_data"
            ).fetchone()[0]
            columns = conn.execute("DESCRIBE imported_data").fetchall()
            user_columns = [c for c in columns if c[0] != SOURCE_ROW_NUM_COLUMN]
            return {
                "row_count": row_count,
                "column_count": len(user_columns),
                "source_type": self.source_type,
            }
        except Exception:
            return {"error": "No data imported"}
