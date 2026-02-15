"""Database adapter for Data Source MCP.

Provides import capabilities for PostgreSQL and MySQL databases using DuckDB's
native extension system. Implements snapshot semantics - data is copied once
and the connection is not maintained.

Per CONTEXT.md:
- Snapshot on import: query runs once, results cached locally
- Connection string is NOT stored after import
- Large tables (>10k rows) require WHERE clause for protection

Security:
- Connection strings are NEVER logged
- Database attached as read-only
- Connection detached immediately after operation
"""

import re
from typing import Literal
from urllib.parse import urlparse

from duckdb import DuckDBPyConnection

from .base import BaseSourceAdapter
from ..models import SOURCE_ROW_NUM_COLUMN, ImportResult, SchemaColumn


# Threshold for requiring WHERE clause (per CONTEXT.md)
LARGE_TABLE_THRESHOLD = 10000


class DatabaseAdapter(BaseSourceAdapter):
    """Adapter for importing from PostgreSQL and MySQL databases via DuckDB.

    Uses DuckDB's postgres and mysql extensions to attach remote databases
    temporarily and import query results as local snapshots.

    Example:
        adapter = DatabaseAdapter()
        result = adapter.import_data(
            conn=duckdb_connection,
            connection_string="postgresql://user:pass@host/db",
            query="SELECT * FROM orders WHERE created_at > '2026-01-01'"
        )
    """

    @property
    def source_type(self) -> str:
        """Return the adapter's source type identifier.

        Returns:
            Source type string: 'database'
        """
        return "database"

    def _detect_db_type(self, connection_string: str) -> Literal["postgres", "mysql"]:
        """Detect database type from connection string.

        Args:
            connection_string: Database connection URL

        Returns:
            "postgres" or "mysql"

        Raises:
            ValueError: If database type not supported
        """
        parsed = urlparse(connection_string)
        scheme = parsed.scheme.lower()

        if scheme in ("postgresql", "postgres"):
            return "postgres"
        elif scheme == "mysql":
            return "mysql"
        else:
            raise ValueError(
                f"Unsupported database type: {scheme}. "
                "Supported: postgresql://, postgres://, mysql://"
            )

    def list_tables(
        self,
        conn: DuckDBPyConnection,
        connection_string: str,
        schema: str = "public",
    ) -> list[dict]:
        """List tables in the remote database.

        Args:
            conn: DuckDB connection
            connection_string: Database connection URL
            schema: Schema to list tables from (default: public for Postgres)

        Returns:
            List of dicts with table name and row count estimate
        """
        db_type = self._detect_db_type(connection_string)

        # Attach database temporarily as read-only
        conn.execute(
            f"ATTACH '{connection_string}' AS remote_db (TYPE {db_type}, READ_ONLY)"
        )

        try:
            if db_type == "postgres":
                # Get tables from information_schema
                tables = conn.execute(
                    f"""
                    SELECT table_name
                    FROM remote_db.information_schema.tables
                    WHERE table_schema = '{schema}'
                    AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """
                ).fetchall()
            else:  # mysql
                # MySQL uses different metadata queries
                tables = conn.execute(
                    """
                    SELECT table_name
                    FROM remote_db.information_schema.tables
                    WHERE table_schema = DATABASE()
                    AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """
                ).fetchall()

            result = []
            for (table_name,) in tables:
                # Get approximate row count
                try:
                    count = conn.execute(
                        f"""
                        SELECT COUNT(*) FROM remote_db.{schema}.{table_name}
                    """
                    ).fetchone()[0]
                except Exception:
                    count = None

                result.append(
                    {
                        "name": table_name,
                        "row_count": count,
                        "requires_filter": count is not None
                        and count > LARGE_TABLE_THRESHOLD,
                    }
                )

            return result

        finally:
            # Always detach to avoid storing connection
            conn.execute("DETACH remote_db")

    def import_data(
        self,
        conn: DuckDBPyConnection,
        connection_string: str,
        query: str,
        schema: str = "public",
    ) -> ImportResult:
        """Import data from database using a query.

        Per CONTEXT.md: Snapshot on import - query runs once, results cached locally.
        Connection string is NOT stored after import.

        Args:
            conn: DuckDB connection
            connection_string: Database connection URL
            query: SQL query to execute (must include WHERE for large tables)
            schema: Schema name (default: public)

        Returns:
            ImportResult with schema and row count

        Raises:
            ValueError: If query targets large table without WHERE clause
        """
        db_type = self._detect_db_type(connection_string)

        # Attach database temporarily as read-only
        conn.execute(
            f"ATTACH '{connection_string}' AS remote_db (TYPE {db_type}, READ_ONLY)"
        )

        try:
            # Extract table name from query for validation
            # Simple regex - handles "FROM table" and "FROM schema.table"
            table_match = re.search(r"FROM\s+(\w+\.)?(\w+)", query, re.IGNORECASE)
            if table_match:
                table_name = table_match.group(2)

                # Check if large table without filter
                has_where = re.search(r"\bWHERE\b", query, re.IGNORECASE) is not None

                if not has_where:
                    # Check row count
                    try:
                        count_result = conn.execute(
                            f"""
                            SELECT COUNT(*) FROM remote_db.{schema}.{table_name}
                        """
                        ).fetchone()
                        row_count = count_result[0] if count_result else 0

                        if row_count > LARGE_TABLE_THRESHOLD:
                            raise ValueError(
                                f"Table '{table_name}' has {row_count:,} rows. "
                                f"Add a WHERE clause to filter "
                                f"(tables > {LARGE_TABLE_THRESHOLD:,} rows require filters). "
                                f"Example: SELECT * FROM {table_name} WHERE created_at > '2026-01-01'"
                            )
                    except Exception as e:
                        if "rows" in str(e):
                            raise  # Re-raise our validation error
                        # Ignore other errors (table might not exist yet in query)

            # Rewrite query to use remote_db prefix
            # Add remote_db.schema. prefix to table references
            modified_query = re.sub(
                r"FROM\s+(\w+)(\s|$)",
                f"FROM remote_db.{schema}.\\1\\2",
                query,
                flags=re.IGNORECASE,
            )

            # Create snapshot table with identity tracking column
            conn.execute(
                f"""
                CREATE OR REPLACE TABLE imported_data AS
                SELECT ROW_NUMBER() OVER () AS {SOURCE_ROW_NUM_COLUMN}, sub.*
                FROM ({modified_query}) AS sub
            """
            )

            # Get schema
            schema_rows = conn.execute("DESCRIBE imported_data").fetchall()
            columns = [
                SchemaColumn(
                    name=col[0],
                    type=col[1],
                    nullable=col[2] == "YES",
                    warnings=[],
                )
                for col in schema_rows
                if col[0] != SOURCE_ROW_NUM_COLUMN  # Hide internal identity column
            ]

            # Get row count
            row_count = conn.execute(
                "SELECT COUNT(*) FROM imported_data"
            ).fetchone()[0]

            return ImportResult(
                row_count=row_count,
                columns=columns,
                warnings=[],
                source_type="database",
            )

        finally:
            # Always detach - connection string is NOT stored
            conn.execute("DETACH remote_db")

    def get_metadata(self, conn: DuckDBPyConnection) -> dict:
        """Get metadata about imported database data.

        Args:
            conn: Active DuckDB connection

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
                "source_type": "database",
            }
        except Exception:
            return {"error": "No data imported"}
