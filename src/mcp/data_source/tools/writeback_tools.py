"""Write-back tools for Data Source MCP.

Provides MCP tools for writing tracking numbers and shipment data
back to the original data source after successful shipment creation.

Per CONTEXT.md Decision 4:
- Immediate write-back after each successful row
- Columns: tracking_number and shipped_at timestamp
- Atomic operations for file sources (temp + rename)
- shipped_at uses ISO8601 format
"""

from datetime import UTC, datetime

from fastmcp import Context

from src.mcp.data_source.models import SOURCE_ROW_NUM_COLUMN
from src.services.write_back_utils import (
    apply_csv_updates_atomic,
    apply_delimited_updates_atomic,
    apply_excel_updates_atomic,
    write_companion_csv,
)


async def write_back(
    row_number: int,
    tracking_number: str,
    ctx: Context,
    shipped_at: str | None = None,
) -> dict:
    """Write tracking number back to the original data source.

    Updates the original data source (CSV, Excel, or database) with
    the tracking number and shipment timestamp for a specific row.

    Args:
        row_number: 1-based row number to update
        tracking_number: UPS tracking number from shipment creation
        shipped_at: ISO8601 timestamp (default: current UTC time)

    Returns:
        Dictionary with:
        - success: True if write-back succeeded
        - source_type: Type of source updated (csv, excel, database)
        - row_number: Row that was updated
        - tracking_number: Tracking number written

    Raises:
        ValueError: If no source is loaded or source type is unsupported

    Example:
        >>> result = await write_back(1, "1Z999AA10123456784", ctx)
        >>> print(result["success"])
        True
    """
    # Get current source from lifespan context
    current_source = ctx.request_context.lifespan_context.get("current_source")

    if current_source is None:
        raise ValueError(
            "No data source loaded. Import a CSV, Excel, or database first."
        )

    # Default shipped_at to current UTC time
    if shipped_at is None:
        shipped_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    source_type = current_source.get("type")

    await ctx.info(
        f"Writing tracking number {tracking_number} to row {row_number} "
        f"in {source_type} source"
    )

    if source_type == "csv":
        await _write_back_csv(
            current_source["path"], row_number, tracking_number, shipped_at, ctx
        )
    elif source_type == "delimited":
        detected_delim = current_source.get("detected_delimiter", ",")
        apply_delimited_updates_atomic(
            file_path=current_source["path"],
            row_updates={
                row_number: {
                    "tracking_number": tracking_number,
                    "shipped_at": shipped_at,
                },
            },
            delimiter=detected_delim,
        )
        await ctx.info(f"Delimited write-back complete for row {row_number}")
    elif source_type in ("json", "xml", "edi", "fixed_width"):
        companion = write_companion_csv(
            source_path=current_source["path"],
            row_number=row_number,
            reference_id=str(row_number),
            tracking_number=tracking_number,
            shipped_at=shipped_at,
        )
        await ctx.info(f"Wrote tracking to companion file: {companion}")
    elif source_type == "excel":
        await _write_back_excel(
            current_source["path"],
            row_number,
            tracking_number,
            shipped_at,
            ctx,
            sheet_name=current_source.get("sheet"),
        )
    elif source_type == "database":
        await _write_back_database(row_number, tracking_number, shipped_at, ctx)
    else:
        raise ValueError(f"Unsupported source type for write-back: {source_type}")

    await ctx.info(f"Successfully wrote tracking number to row {row_number}")

    return {
        "success": True,
        "source_type": source_type,
        "row_number": row_number,
        "tracking_number": tracking_number,
    }


async def _write_back_csv(
    file_path: str,
    row_number: int,
    tracking_number: str,
    shipped_at: str,
    ctx: Context,
) -> None:
    """Write tracking and timestamp columns to a CSV source atomically."""
    apply_csv_updates_atomic(
        file_path=file_path,
        row_updates={
            row_number: {
                "tracking_number": tracking_number,
                "shipped_at": shipped_at,
            },
        },
    )
    await ctx.info(f"CSV write-back complete for row {row_number}")


async def _write_back_excel(
    file_path: str,
    row_number: int,
    tracking_number: str,
    shipped_at: str,
    ctx: Context,
    sheet_name: str | None = None,
) -> None:
    """Write tracking and timestamp columns to an Excel source atomically."""
    apply_excel_updates_atomic(
        file_path=file_path,
        row_updates={
            row_number: {
                "tracking_number": tracking_number,
                "shipped_at": shipped_at,
            },
        },
        sheet_name=sheet_name,
    )
    await ctx.info(f"Excel write-back complete for row {row_number}")


async def _write_back_database(
    row_number: int,
    tracking_number: str,
    shipped_at: str,
    ctx: Context,
) -> None:
    """Write tracking number to database source.

    Uses DuckDB's attached database connection to execute UPDATE.
    Requires _row_number column to be present (added during import).

    Note: For MVP, this assumes the source table has been modified
    to include tracking_number and shipped_at columns, or the UPDATE
    will add them (depending on database support).

    Args:
        row_number: Row number to update (matches _row_number column)
        tracking_number: Tracking number to write
        shipped_at: ISO8601 timestamp
        ctx: MCP context for logging and database access
    """
    db = ctx.request_context.lifespan_context["db"]
    current_source = ctx.request_context.lifespan_context["current_source"]

    # For database sources, we need the table name from the query
    # This is a limitation - we only support simple table references
    # For complex queries, write-back would need to be handled differently
    query = current_source.get("query", "")

    # Extract table name from simple SELECT ... FROM table_name patterns
    # This is a simplification for MVP - complex queries may not work
    table_name = _extract_table_name(query)

    if table_name is None:
        raise ValueError(
            "Cannot determine target table for write-back. "
            "Database write-back requires a simple SELECT ... FROM table_name query."
        )

    await ctx.info(f"Updating database table {table_name} row {row_number}")

    # Use parameterized query to prevent SQL injection
    # Note: DuckDB uses $1, $2 syntax for parameters
    update_sql = f"""
        UPDATE {table_name}
        SET tracking_number = $1, shipped_at = $2
        WHERE {SOURCE_ROW_NUM_COLUMN} = $3
    """

    try:
        db.execute(update_sql, [tracking_number, shipped_at, row_number])
        await ctx.info(f"Database write-back complete for row {row_number}")
    except Exception as e:
        raise ValueError(f"Database write-back failed: {e}") from e


def _extract_table_name(query: str) -> str | None:
    """Extract table name from a simple SELECT query.

    Handles patterns like:
    - SELECT * FROM table_name
    - SELECT * FROM table_name WHERE ...
    - SELECT cols FROM schema.table_name

    Args:
        query: SQL query string

    Returns:
        Table name or None if not extractable
    """
    if not query:
        return None

    # Normalize whitespace
    query = " ".join(query.split())
    query_upper = query.upper()

    # Find FROM keyword
    from_idx = query_upper.find(" FROM ")
    if from_idx == -1:
        return None

    # Extract portion after FROM
    after_from = query[from_idx + 6 :].strip()

    # Get the table name (first token after FROM)
    # Handle schema.table notation
    parts = after_from.split()
    if not parts:
        return None

    table_ref = parts[0]

    # Check if the table reference itself IS a keyword (shouldn't be in valid SQL)
    # Don't check for substring match as "orders" contains "ORDER"
    keywords = {
        "WHERE",
        "ORDER",
        "GROUP",
        "HAVING",
        "LIMIT",
        "OFFSET",
        "JOIN",
        "LEFT",
        "RIGHT",
        "INNER",
        "OUTER",
    }
    if table_ref.upper() in keywords:
        return None

    # Reject subqueries - table reference shouldn't start with parenthesis
    if table_ref.startswith("("):
        return None

    return table_ref
