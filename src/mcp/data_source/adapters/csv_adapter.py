"""Delimited file adapter for importing CSV, TSV, SSV, and other delimited files via DuckDB.

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
from src.mcp.data_source.models import SOURCE_ROW_NUM_COLUMN, ImportResult, SchemaColumn
from src.mcp.data_source.utils import parse_date_with_warnings


class DelimitedAdapter(BaseSourceAdapter):
    """Adapter for importing delimited files (CSV, TSV, SSV, pipe, etc.) via DuckDB.

    Uses DuckDB's read_csv function with auto-detection for:
    - Column types (integer, float, varchar, date, etc.)
    - Delimiter detection (comma, tab, pipe, etc.)
    - Header row detection

    Empty rows are silently skipped by DuckDB's null_padding option.
    Mixed-type columns default to VARCHAR per ignore_errors=true.

    Example:
        >>> adapter = DelimitedAdapter()
        >>> result = adapter.import_data(conn, file_path="/path/to/orders.csv")
        >>> print(result.row_count, result.columns)
    """

    def __init__(self):
        """Initialize adapter with detected_delimiter tracking."""
        self.detected_delimiter: str | None = None

    @property
    def source_type(self) -> str:
        """Return the adapter's source type identifier.

        Returns:
            'delimited' - identifies this as a delimited file adapter
        """
        return "delimited"

    def import_data(
        self,
        conn: "DuckDBPyConnection",
        file_path: str,
        delimiter: str | None = None,
        quotechar: str | None = None,
        header: bool = True,
    ) -> ImportResult:
        """Import delimited file into DuckDB.

        Creates or replaces the 'imported_data' table with file contents.
        Uses full file scan for type inference to handle mixed types correctly.

        Args:
            conn: DuckDB connection (in-memory)
            file_path: Absolute path to the delimited file
            delimiter: Column delimiter (None for auto-detect, default)
            quotechar: Quote character (default None — DuckDB auto-detects)
            header: Whether first row contains headers (default True)

        Returns:
            ImportResult with discovered schema, row count, and warnings

        Raises:
            FileNotFoundError: If the file doesn't exist
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
        # Escape single quotes for SQL injection prevention
        safe_path = file_path.replace("'", "''")

        # Build optional read_csv clauses
        extra_clauses = ""
        if delimiter:
            safe_delim = delimiter.replace("'", "''")
            extra_clauses += f", delim = '{safe_delim}'"
        if quotechar:
            safe_quote = quotechar.replace("'", "''")
            extra_clauses += f", quote = '{safe_quote}'"

        conn.execute(f"""
            CREATE OR REPLACE TABLE _raw_import AS
            SELECT * FROM read_csv(
                '{safe_path}',
                auto_detect = true,
                sample_size = -1,
                ignore_errors = true,
                null_padding = true,
                header = {str(header).lower()}
                {extra_clauses}
            )
        """)

        # Capture the actual delimiter used by DuckDB. When the user
        # provided one explicitly we trust it; otherwise query sniff_csv
        # to discover what DuckDB auto-detected (could be tab, pipe, etc.).
        if delimiter:
            self.detected_delimiter = delimiter
        else:
            try:
                sniff_row = conn.execute(
                    f"SELECT Delimiter FROM sniff_csv('{safe_path}')"
                ).fetchone()
                self.detected_delimiter = sniff_row[0] if sniff_row else ","
            except Exception:
                # sniff_csv may not be available in all DuckDB versions
                self.detected_delimiter = ","

        # Get column names to build the "all NULL" filter
        raw_columns = conn.execute("DESCRIBE _raw_import").fetchall()
        col_names = [col[0] for col in raw_columns]

        # Filter out rows where ALL columns are NULL (empty rows)
        # Per CONTEXT.md: "silent skip for empty rows"
        # Assign _source_row_num BEFORE filtering so original row positions
        # are preserved — write-back depends on these matching the source file.
        null_checks = " AND ".join([f'"{col}" IS NULL' for col in col_names])
        select_cols = ", ".join([f'"{col}"' for col in col_names])
        conn.execute(f"""
            CREATE OR REPLACE TABLE imported_data AS
            SELECT {SOURCE_ROW_NUM_COLUMN}, {select_cols}
            FROM (
                SELECT ROW_NUMBER() OVER () AS {SOURCE_ROW_NUM_COLUMN}, {select_cols}
                FROM _raw_import
            ) AS numbered
            WHERE NOT ({null_checks})
        """)

        # Clean up temporary table
        conn.execute("DROP TABLE IF EXISTS _raw_import")

        # Get schema from DuckDB DESCRIBE
        schema_rows = conn.execute("DESCRIBE imported_data").fetchall()
        columns = []
        warnings: list[str] = []

        for col_name, col_type, nullable, key, default, extra in schema_rows:
            # Hide internal identity column from user-facing schema
            if col_name == SOURCE_ROW_NUM_COLUMN:
                continue
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

        # Single-column ambiguity warning for possible fixed-width files
        if len(columns) == 1 and row_count > 0:
            warnings.append(
                "Only 1 column detected — file may be fixed-width or use an "
                "unrecognized delimiter. Use sniff_file to inspect."
            )

        return ImportResult(
            row_count=row_count,
            columns=columns,
            warnings=warnings,
            source_type="delimited",
        )

    def get_metadata(self, conn: "DuckDBPyConnection") -> dict:
        """Get metadata about the imported delimited file.

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
            # Exclude internal _source_row_num from user-facing count
            user_columns = [c for c in columns if c[0] != SOURCE_ROW_NUM_COLUMN]
            return {
                "row_count": row_count,
                "column_count": len(user_columns),
                "source_type": "delimited",
            }
        except Exception:
            return {"error": "No data imported"}


# Backward compatibility alias
CSVAdapter = DelimitedAdapter
