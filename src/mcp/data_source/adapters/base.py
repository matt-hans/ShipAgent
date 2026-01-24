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

from src.mcp.data_source.models import ImportResult


class BaseSourceAdapter(ABC):
    """Abstract base class for data source adapters.

    Concrete implementations must provide:
    - source_type: Identifier for this adapter type
    - import_data: Import data into DuckDB and return schema info
    - get_metadata: Return source-specific metadata

    Example implementation:
        class CSVAdapter(BaseSourceAdapter):
            @property
            def source_type(self) -> str:
                return "csv"

            def import_data(self, conn, **kwargs) -> ImportResult:
                # CSV-specific import logic
                pass

            def get_metadata(self, conn) -> dict:
                return {"file_path": self._file_path}
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

    @abstractmethod
    def get_metadata(self, conn: "DuckDBPyConnection") -> dict:
        """Return source-specific metadata.

        Used to track what source is currently loaded for job creation.
        The metadata should contain enough information to identify the
        source but NOT sensitive data (like credentials).

        Args:
            conn: Active DuckDB connection

        Returns:
            Dictionary with source-specific metadata:
                - CSV: {"file_path": str, "import_time": str}
                - Excel: {"file_path": str, "sheet_name": str}
                - Database: {"source": "postgres", "table": str, "row_count": int}
        """
        ...
