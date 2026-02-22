"""Data query tools for Data Source MCP."""

import re
from typing import Any

from fastmcp import Context

from ..models import SOURCE_ROW_NUM_COLUMN, QueryResult, RowData
from ..utils import compute_row_checksum

# Regex for valid SQL type identifiers used in CAST expressions.
# Allows types like VARCHAR, DOUBLE, DECIMAL(10,2), TIMESTAMP WITH TIME ZONE.
_VALID_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_ ]*(\(\d+([, ]\d+)*\))?$")

# Regex patterns for stripping SQL comments before keyword checks.
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")


def _safe_cast_expression(col: str, type_str: str) -> str:
    """Build a safe CAST expression with type validation.

    Args:
        col: Column name (will be double-quoted).
        type_str: SQL type string to validate.

    Returns:
        SQL CAST expression string.

    Raises:
        ValueError: If type_str contains invalid characters.
    """
    normalized = type_str.strip().upper()
    if not _VALID_TYPE_RE.match(normalized):
        raise ValueError(
            f"Invalid type override '{type_str}' for column '{col}'. "
            "Only standard SQL type identifiers are allowed."
        )
    return f'CAST("{col}" AS {normalized}) AS "{col}"'


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL block and line comments to prevent keyword bypass.

    Args:
        sql: Raw SQL string.

    Returns:
        SQL with all comments removed.
    """
    result = _BLOCK_COMMENT_RE.sub(" ", sql)
    result = _LINE_COMMENT_RE.sub(" ", result)
    return result


async def get_row(row_number: int, ctx: Context) -> dict:
    """Get a single row by its 1-based row number.

    Args:
        row_number: 1-based row number (1 = first data row)

    Returns:
        Dictionary with row data and checksum.

    Example:
        >>> result = await get_row(1, ctx)
        >>> print(result["data"])
        {"order_id": 1001, "customer": "John Doe", ...}
    """
    db = ctx.request_context.lifespan_context["db"]
    type_overrides = ctx.request_context.lifespan_context.get("type_overrides", {})

    if row_number < 1:
        raise ValueError("Row number must be >= 1")

    await ctx.info(f"Fetching row {row_number}")

    # Get column names, excluding internal identity column
    schema = db.execute("DESCRIBE imported_data").fetchall()
    columns = [col[0] for col in schema if col[0] != SOURCE_ROW_NUM_COLUMN]

    # Build SELECT with type casts for overrides
    select_parts = []
    for col in columns:
        if col in type_overrides:
            select_parts.append(_safe_cast_expression(col, type_overrides[col]))
        else:
            select_parts.append(f'"{col}"')

    select_clause = ", ".join(select_parts)

    # Look up by identity column (parameterized)
    result = db.execute(
        f"""
        SELECT {select_clause} FROM imported_data
        WHERE {SOURCE_ROW_NUM_COLUMN} = $1
    """,
        [row_number],
    ).fetchone()

    if result is None:
        raise ValueError(f"Row {row_number} not found. Data may have fewer rows.")

    row_dict = dict(zip(columns, result, strict=False))
    checksum = compute_row_checksum(row_dict)

    return RowData(row_number=row_number, data=row_dict, checksum=checksum).model_dump()


async def get_rows_by_filter(
    where_sql: str,
    ctx: Context,
    limit: int = 100,
    offset: int = 0,
    params: list[Any] | None = None,
) -> dict:
    """Get rows matching a parameterized SQL WHERE clause.

    Args:
        where_sql: Parameterized WHERE condition (without 'WHERE' keyword).
            Uses $1, $2, ... placeholders for values.
            Example: '"state" = $1 AND "weight" > $2'
        limit: Maximum rows to return (default: 100, max: 1000).
        offset: Number of rows to skip (for pagination).
        params: Positional parameter values for $N placeholders.
            Pass None or [] for queries without parameters (e.g., IS NULL).

    Returns:
        QueryResult with matching rows and checksums.

    Example:
        >>> result = await get_rows_by_filter('"state" = $1', ctx, params=["CA"])
        >>> print(result["total_count"])
        150
    """
    db = ctx.request_context.lifespan_context["db"]
    type_overrides = ctx.request_context.lifespan_context.get("type_overrides", {})

    # ALWAYS parameterized — normalize None to empty list
    query_params = params if params is not None else []

    # Enforce limits
    limit = min(limit, 1000)
    if limit < 1:
        limit = 100

    await ctx.info(f"Querying rows with filter: {where_sql}")

    # Get column names, excluding internal identity column
    schema = db.execute("DESCRIBE imported_data").fetchall()
    columns = [col[0] for col in schema if col[0] != SOURCE_ROW_NUM_COLUMN]

    # Build SELECT with type casts
    select_parts = []
    for col in columns:
        if col in type_overrides:
            select_parts.append(_safe_cast_expression(col, type_overrides[col]))
        else:
            select_parts.append(f'"{col}"')

    select_clause = ", ".join(select_parts)

    # Get total count first — parameterized
    total_count = db.execute(
        f"SELECT COUNT(*) FROM imported_data WHERE {where_sql}",
        query_params,
    ).fetchone()[0]

    # Use persisted identity column for stable row identity across filters
    results = db.execute(
        f"""
        SELECT {SOURCE_ROW_NUM_COLUMN}, {select_clause}
        FROM imported_data
        WHERE {where_sql}
        ORDER BY {SOURCE_ROW_NUM_COLUMN}
        LIMIT {limit} OFFSET {offset}
    """,
        query_params,
    ).fetchall()

    # Process results — identity column is the first column
    rows = []
    for row in results:
        row_num = row[0]
        row_data = dict(zip(columns, row[1:], strict=False))
        checksum = compute_row_checksum(row_data)
        rows.append(
            RowData(row_number=row_num, data=row_data, checksum=checksum).model_dump()
        )

    await ctx.info(f"Found {total_count} matching rows, returning {len(rows)}")

    return QueryResult(rows=rows, total_count=total_count).model_dump()


async def query_data(
    sql: str,
    ctx: Context,
) -> dict:
    """Execute a custom SQL query against imported data.

    The query runs against 'imported_data' table. Only SELECT queries allowed.

    Args:
        sql: SQL SELECT query (must start with SELECT)

    Returns:
        Dictionary with columns and rows.

    Example:
        >>> result = await query_data("SELECT state, COUNT(*) as cnt FROM imported_data GROUP BY state", ctx)
    """
    db = ctx.request_context.lifespan_context["db"]

    # Security: Only allow SELECT — strip comments first to prevent bypass
    stripped = _strip_sql_comments(sql)
    sql_upper = stripped.strip().upper()
    if not sql_upper.startswith("SELECT"):
        raise ValueError("Only SELECT queries are allowed")

    # Reject stacked queries (semicolons)
    if ";" in sql_upper:
        raise ValueError("Multiple statements are not allowed")

    # Block dangerous keywords (DML, DDL, and DuckDB-specific functions).
    # Uses word-boundary matching to avoid false positives on table/column
    # names like "imported_data" matching "IMPORT".
    dangerous = [
        "DROP",
        "DELETE",
        "INSERT",
        "UPDATE",
        "ALTER",
        "CREATE",
        "TRUNCATE",
        "COPY",
        "ATTACH",
        "DETACH",
        "EXPORT",
        "IMPORT",
        "LOAD",
        "INSTALL",
        "CALL",
        "PRAGMA",
        "SET",
        "EXECUTE",
        "READ_CSV",
        "READ_PARQUET",
        "READ_JSON",
        "GLOB",
    ]
    for keyword in dangerous:
        if re.search(rf"\b{keyword}\b", sql_upper):
            raise ValueError(f"Query contains forbidden keyword: {keyword}")

    await ctx.info(f"Executing query: {sql[:100]}...")

    results = db.execute(sql).fetchall()
    columns = [desc[0] for desc in db.description]

    return {
        "columns": columns,
        "rows": [dict(zip(columns, row, strict=False)) for row in results],
        "row_count": len(results),
    }
