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
- Schema/table identifiers validated against SQL injection (CWE-89)
"""

import re
from collections import OrderedDict
from typing import Literal
from urllib.parse import urlparse

from duckdb import DuckDBPyConnection

from ..models import SOURCE_ROW_NUM_COLUMN, ImportResult, SchemaColumn
from .base import BaseSourceAdapter

# Threshold for requiring WHERE clause (per CONTEXT.md)
LARGE_TABLE_THRESHOLD = 10000

# Safe identifier pattern: letters, digits, underscores. Starts with letter or underscore.
_SAFE_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_identifier(name: str, label: str = "identifier") -> str:
    """Validate a SQL identifier against injection (CWE-89).

    Args:
        name: The identifier string to validate.
        label: Human-readable label for error messages.

    Returns:
        The validated identifier string.

    Raises:
        ValueError: If the identifier contains unsafe characters.
    """
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(
            f"Invalid {label}: {name!r}. "
            "Identifiers must contain only letters, digits, and underscores, "
            "and must start with a letter or underscore."
        )
    return name


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

    def _get_key_candidates(
        self,
        conn: DuckDBPyConnection,
        db_type: Literal["postgres", "mysql"],
        schema: str,
        table_name: str,
    ) -> list[tuple[str, list[str]]]:
        """Return deterministic row-key candidates ordered by preference.

        Preference order:
        1. PRIMARY KEY constraints
        2. UNIQUE constraints
        """
        try:
            if db_type == "postgres":
                rows = conn.execute(
                    """
                    SELECT
                        tc.constraint_type,
                        tc.constraint_name,
                        kcu.column_name,
                        kcu.ordinal_position
                    FROM remote_db.information_schema.table_constraints tc
                    JOIN remote_db.information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema = kcu.table_schema
                     AND tc.table_name = kcu.table_name
                    WHERE tc.table_schema = ?
                      AND tc.table_name = ?
                      AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
                    ORDER BY
                      CASE WHEN tc.constraint_type = 'PRIMARY KEY' THEN 0 ELSE 1 END,
                      tc.constraint_name,
                      kcu.ordinal_position
                    """,
                    [schema, table_name],
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT
                        tc.constraint_type,
                        tc.constraint_name,
                        kcu.column_name,
                        kcu.ordinal_position
                    FROM remote_db.information_schema.table_constraints tc
                    JOIN remote_db.information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema = kcu.table_schema
                     AND tc.table_name = kcu.table_name
                    WHERE tc.table_schema = DATABASE()
                      AND tc.table_name = ?
                      AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
                    ORDER BY
                      CASE WHEN tc.constraint_type = 'PRIMARY KEY' THEN 0 ELSE 1 END,
                      tc.constraint_name,
                      kcu.ordinal_position
                    """,
                    [table_name],
                ).fetchall()
        except Exception:
            return []

        grouped: OrderedDict[tuple[str, str], list[str]] = OrderedDict()
        for ctype, cname, col_name, _ordinal in rows:
            key = (str(ctype), str(cname))
            grouped.setdefault(key, []).append(str(col_name))

        candidates: list[tuple[str, list[str]]] = []
        for (ctype, _), cols in grouped.items():
            if cols:
                candidates.append((ctype, cols))
        return candidates

    def _get_query_output_columns(
        self,
        conn: DuckDBPyConnection,
        modified_query: str,
    ) -> list[str]:
        """Return output columns for a query snapshot."""
        try:
            rows = conn.execute(
                f"DESCRIBE SELECT * FROM ({modified_query}) AS sub"
            ).fetchall()
            return [str(r[0]) for r in rows]
        except Exception:
            return []

    @staticmethod
    def _resolve_casefold_columns(
        requested: list[str],
        available: list[str],
    ) -> list[str] | None:
        """Resolve requested columns against available columns case-insensitively."""
        lookup = {c.casefold(): c for c in available}
        resolved: list[str] = []
        for col in requested:
            match = lookup.get(col.casefold())
            if match is None:
                return None
            resolved.append(match)
        return resolved

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
        _validate_identifier(schema, "schema")
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

                key_candidates = self._get_key_candidates(
                    conn=conn,
                    db_type=db_type,
                    schema=schema,
                    table_name=table_name,
                )
                deterministic_candidates = [cols for _, cols in key_candidates]

                result.append(
                    {
                        "name": table_name,
                        "row_count": count,
                        "requires_filter": count is not None
                        and count > LARGE_TABLE_THRESHOLD,
                        "row_key_candidates": deterministic_candidates,
                        "preferred_row_key": (
                            deterministic_candidates[0]
                            if deterministic_candidates
                            else []
                        ),
                        "deterministic_ready": bool(deterministic_candidates),
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
        row_key_columns: list[str] | None = None,
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
        _validate_identifier(schema, "schema")
        db_type = self._detect_db_type(connection_string)

        # Attach database temporarily as read-only
        conn.execute(
            f"ATTACH '{connection_string}' AS remote_db (TYPE {db_type}, READ_ONLY)"
        )

        try:
            # Extract table name from query for validation
            # Simple regex - handles "FROM table" and "FROM schema.table"
            table_match = re.search(
                r"FROM\s+((\w+)\.)?(\w+)",
                query,
                re.IGNORECASE,
            )
            table_schema = schema
            table_name = None
            if table_match:
                table_name = table_match.group(3)
                table_schema = table_match.group(2) or schema

                # Check if large table without filter
                has_where = re.search(r"\bWHERE\b", query, re.IGNORECASE) is not None

                if not has_where:
                    # Check row count
                    try:
                        count_result = conn.execute(
                            f"""
                            SELECT COUNT(*) FROM remote_db.{table_schema}.{table_name}
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
                r"FROM\s+((\w+)\.)?(\w+)(\s|$)",
                f"FROM remote_db.{table_schema}.\\3\\4",
                query,
                flags=re.IGNORECASE,
            )
            query_columns = self._get_query_output_columns(conn, modified_query)

            # Resolve deterministic row-key strategy.
            effective_row_keys: list[str] = []
            row_key_strategy = "none"
            explicit_row_keys = [
                str(c).strip()
                for c in (row_key_columns or [])
                if str(c).strip()
            ]
            if explicit_row_keys:
                if not query_columns:
                    raise ValueError(
                        "Unable to inspect query output columns for row_key_columns "
                        "validation. Provide a simpler SELECT query or omit "
                        "row_key_columns to use auto-detection."
                    )
                resolved = self._resolve_casefold_columns(
                    requested=explicit_row_keys,
                    available=query_columns,
                )
                if resolved is None:
                    raise ValueError(
                        "row_key_columns must exist in query output columns. "
                        f"Requested={explicit_row_keys}; "
                        f"available={sorted(query_columns)}"
                    )
                effective_row_keys = resolved
                row_key_strategy = "explicit"
            elif table_name:
                key_candidates = self._get_key_candidates(
                    conn=conn,
                    db_type=db_type,
                    schema=table_schema,
                    table_name=table_name,
                )
                if key_candidates:
                    key_type, cols = key_candidates[0]
                    if query_columns:
                        resolved = self._resolve_casefold_columns(
                            requested=cols,
                            available=query_columns,
                        )
                        if resolved:
                            effective_row_keys = resolved
                            row_key_strategy = (
                                "auto_pk"
                                if key_type == "PRIMARY KEY"
                                else "auto_unique"
                            )

            deterministic_ready = bool(effective_row_keys)
            if deterministic_ready:
                order_expr = ", ".join(
                    f'sub."{col.replace("\"", "\"\"")}" ASC'
                    for col in effective_row_keys
                )
                row_number_expr = f"ROW_NUMBER() OVER (ORDER BY {order_expr})"
            else:
                row_number_expr = "ROW_NUMBER() OVER ()"

            # Create snapshot table with identity tracking column
            conn.execute(
                f"""
                CREATE OR REPLACE TABLE imported_data AS
                SELECT {row_number_expr} AS {SOURCE_ROW_NUM_COLUMN}, sub.*
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

            warnings: list[str] = []
            if not deterministic_ready:
                warnings.append(
                    "NON_DETERMINISTIC_ROW_ORDER: No PRIMARY KEY/UNIQUE row key "
                    "could be inferred. Shipping determinism guard may block execution. "
                    "Provide row_key_columns on import_database."
                )

            return ImportResult(
                row_count=row_count,
                columns=columns,
                warnings=warnings,
                source_type="database",
                deterministic_ready=deterministic_ready,
                row_key_strategy=row_key_strategy,
                row_key_columns=effective_row_keys,
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
