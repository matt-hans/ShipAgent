"""Data query tools for Data Source MCP."""

from typing import Any

from fastmcp import Context

from ..models import QueryResult, RowData
from ..utils import compute_row_checksum


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

    # Get column names
    schema = db.execute("DESCRIBE imported_data").fetchall()
    columns = [col[0] for col in schema]

    # Build SELECT with type casts for overrides
    select_parts = []
    for col in columns:
        if col in type_overrides:
            select_parts.append(f'CAST("{col}" AS {type_overrides[col]}) AS "{col}"')
        else:
            select_parts.append(f'"{col}"')

    select_clause = ", ".join(select_parts)

    # DuckDB uses 0-based OFFSET
    result = db.execute(f"""
        SELECT {select_clause} FROM imported_data
        LIMIT 1 OFFSET {row_number - 1}
    """).fetchone()

    if result is None:
        raise ValueError(f"Row {row_number} not found. Data may have fewer rows.")

    row_dict = dict(zip(columns, result))
    checksum = compute_row_checksum(row_dict)

    return RowData(
        row_number=row_number,
        data=row_dict,
        checksum=checksum
    ).model_dump()


async def get_rows_by_filter(
    where_clause: str,
    ctx: Context,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Get rows matching a SQL WHERE clause.

    Args:
        where_clause: SQL WHERE condition (without 'WHERE' keyword)
            Example: "state = 'CA' AND weight > 5"
        limit: Maximum rows to return (default: 100, max: 1000)
        offset: Number of rows to skip (for pagination)

    Returns:
        QueryResult with matching rows and checksums.

    Example:
        >>> result = await get_rows_by_filter("state = 'CA'", ctx, limit=50)
        >>> print(result["total_count"])
        150
    """
    db = ctx.request_context.lifespan_context["db"]
    type_overrides = ctx.request_context.lifespan_context.get("type_overrides", {})

    # Enforce limits
    limit = min(limit, 1000)
    if limit < 1:
        limit = 100

    await ctx.info(f"Querying rows with filter: {where_clause}")

    # Get column names
    schema = db.execute("DESCRIBE imported_data").fetchall()
    columns = [col[0] for col in schema]

    # Build SELECT with type casts
    select_parts = []
    for col in columns:
        if col in type_overrides:
            select_parts.append(f'CAST("{col}" AS {type_overrides[col]}) AS "{col}"')
        else:
            select_parts.append(f'"{col}"')

    select_clause = ", ".join(select_parts)

    # Get total count first
    total_count = db.execute(f"""
        SELECT COUNT(*) FROM imported_data
        WHERE {where_clause}
    """).fetchone()[0]

    # Get rows with ROW_NUMBER for consistent numbering
    results = db.execute(f"""
        WITH numbered AS (
            SELECT ROW_NUMBER() OVER () as _row_num, {select_clause}
            FROM imported_data
            WHERE {where_clause}
        )
        SELECT * FROM numbered
        LIMIT {limit} OFFSET {offset}
    """).fetchall()

    # Process results
    rows = []
    for row in results:
        row_num = row[0]
        row_data = dict(zip(columns, row[1:]))  # Skip _row_num
        checksum = compute_row_checksum(row_data)
        rows.append(RowData(
            row_number=row_num,
            data=row_data,
            checksum=checksum
        ).model_dump())

    await ctx.info(f"Found {total_count} matching rows, returning {len(rows)}")

    return QueryResult(
        rows=rows,
        total_count=total_count
    ).model_dump()


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

    # Security: Only allow SELECT
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith("SELECT"):
        raise ValueError("Only SELECT queries are allowed")

    # Block dangerous keywords
    dangerous = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "TRUNCATE"]
    for keyword in dangerous:
        if keyword in sql_upper:
            raise ValueError(f"Query contains forbidden keyword: {keyword}")

    await ctx.info(f"Executing query: {sql[:100]}...")

    results = db.execute(sql).fetchall()
    columns = [desc[0] for desc in db.description]

    return {
        "columns": columns,
        "rows": [dict(zip(columns, row)) for row in results],
        "row_count": len(results),
    }
