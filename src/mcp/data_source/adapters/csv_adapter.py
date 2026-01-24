"""CSV adapter for importing CSV files via DuckDB.

Uses DuckDB's read_csv with auto-detection for schema discovery.
Handles mixed types by defaulting to VARCHAR, and detects date format ambiguity.

Per CONTEXT.md:
- Import all rows, flag invalid ones (no threshold)
- Silent skip for empty rows
- Best-effort parsing with string fallback
- Default to US date format when ambiguous
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

from src.mcp.data_source.adapters.base import BaseSourceAdapter
from src.mcp.data_source.models import ImportResult, SchemaColumn
from src.mcp.data_source.utils import parse_date_with_warnings


class CSVAdapter(BaseSourceAdapter):
    """Adapter for importing CSV files via DuckDB.

    Uses DuckDB's read_csv function with auto-detection for:
    - Column types (integer, float, varchar, date, etc.)
    - Delimiter detection (comma, tab, pipe, etc.)
    - Header row detection

    Empty rows are silently skipped by DuckDB's null_padding option.
    Mixed-type columns default to VARCHAR per ignore_errors=true.

    Example:
        >>> adapter = CSVAdapter()
        >>> result = adapter.import_data(conn, file_path="/path/to/orders.csv")
        >>> print(result.row_count, result.columns)
    """

    @property
    def source_type(self) -> str:
        """Return the adapter's source type identifier.

        Returns:
            'csv' - identifies this as a CSV file adapter
        """
        return "csv"

    def import_data(
        self,
        conn: "DuckDBPyConnection",
        file_path: str,
        delimiter: str = ",",
        header: bool = True,
    ) -> ImportResult:
        """Import CSV file into DuckDB.

        Creates or replaces the 'imported_data' table with CSV contents.
        Uses full file scan for type inference to handle mixed types correctly.

        Args:
            conn: DuckDB connection (in-memory)
            file_path: Absolute path to the CSV file
            delimiter: Column delimiter (default comma)
            header: Whether first row contains headers (default True)

        Returns:
            ImportResult with discovered schema, row count, and warnings

        Raises:
            FileNotFoundError: If the CSV file doesn't exist
        """
        # Validate file exists before attempting import
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        # Import with auto-detection and full file scan for type inference
        # Per RESEARCH.md:
        # - sample_size=-1: Scan entire file for accurate type detection
        # - ignore_errors=true: Mixed types become VARCHAR instead of failing
        # - null_padding=true: Handle rows with fewer columns gracefully
        conn.execute(f"""
            CREATE OR REPLACE TABLE imported_data AS
            SELECT * FROM read_csv(
                '{file_path}',
                auto_detect = true,
                sample_size = -1,
                ignore_errors = true,
                null_padding = true,
                delim = '{delimiter}',
                header = {str(header).lower()}
            )
        """)

        # Get schema from DuckDB DESCRIBE
        schema_rows = conn.execute("DESCRIBE imported_data").fetchall()
        columns = []
        warnings: list[str] = []

        for col_name, col_type, nullable, key, default, extra in schema_rows:
            col_warnings: list[str] = []

            # Check for date columns that might have ambiguity
            if "DATE" in col_type.upper() or "TIMESTAMP" in col_type.upper():
                # Sample a value to check for US/EU ambiguity
                sample = conn.execute(f"""
                    SELECT "{col_name}" FROM imported_data
                    WHERE "{col_name}" IS NOT NULL LIMIT 1
                """).fetchone()

                if sample:
                    date_result = parse_date_with_warnings(str(sample[0]))
                    for w in date_result.get("warnings", []):
                        if isinstance(w, dict):
                            col_warnings.append(w.get("message", str(w)))
                        else:
                            col_warnings.append(str(w))

            columns.append(
                SchemaColumn(
                    name=col_name,
                    type=col_type,
                    nullable=(nullable == "YES"),
                    warnings=col_warnings,
                )
            )
            warnings.extend(col_warnings)

        # Get row count (DuckDB already skips truly empty rows with null_padding)
        row_count = conn.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]

        return ImportResult(
            row_count=row_count,
            columns=columns,
            warnings=warnings,
            source_type="csv",
        )

    def get_metadata(self, conn: "DuckDBPyConnection") -> dict:
        """Get metadata about the imported CSV.

        Returns information about the currently loaded data for job tracking.

        Args:
            conn: DuckDB connection with imported_data table

        Returns:
            Dictionary with row_count, column_count, and source_type.
            Returns error dict if no data imported.
        """
        try:
            row_count = conn.execute(
                "SELECT COUNT(*) FROM imported_data"
            ).fetchone()[0]
            columns = conn.execute("DESCRIBE imported_data").fetchall()
            return {
                "row_count": row_count,
                "column_count": len(columns),
                "source_type": "csv",
            }
        except Exception:
            return {"error": "No data imported"}
