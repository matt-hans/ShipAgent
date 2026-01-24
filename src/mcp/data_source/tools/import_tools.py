"""Import tools for Data Source MCP.

Provides MCP tools for importing data from various sources (CSV, Excel, databases).
Each tool uses the appropriate adapter to load data into DuckDB and returns
the discovered schema with any warnings.

Per CONTEXT.md:
- One source at a time (import replaces previous)
- User can import a CSV and see discovered schema
- Ambiguous dates generate warnings
"""

from fastmcp import Context

from src.mcp.data_source.adapters.csv_adapter import CSVAdapter


async def import_csv(
    file_path: str,
    ctx: Context,
    delimiter: str = ",",
    header: bool = True,
) -> dict:
    """Import CSV file and discover schema.

    Imports a CSV file into DuckDB using auto-detection for types.
    Returns the discovered schema along with any warnings about
    ambiguous dates or mixed-type columns.

    Args:
        file_path: Absolute path to the CSV file
        delimiter: Column delimiter (default: comma)
        header: Whether first row contains headers (default: True)

    Returns:
        Dictionary with:
        - row_count: Number of rows imported
        - columns: List of column metadata (name, type, nullable, warnings)
        - warnings: Import-level warnings
        - source_type: 'csv'

    Example:
        >>> result = await import_csv("/path/to/orders.csv", ctx)
        >>> print(result["row_count"])
        150
        >>> print(result["columns"][0])
        {"name": "order_id", "type": "INTEGER", "nullable": false, "warnings": []}
    """
    # Access DuckDB connection from lifespan context
    # CRITICAL: Use ctx.request_context.lifespan_context per FastMCP v2 pattern
    db = ctx.request_context.lifespan_context["db"]

    await ctx.info(f"Importing CSV from {file_path}")

    adapter = CSVAdapter()
    result = adapter.import_data(
        conn=db,
        file_path=file_path,
        delimiter=delimiter,
        header=header,
    )

    # Update current source tracking for session state
    ctx.request_context.lifespan_context["current_source"] = {
        "type": "csv",
        "path": file_path,
        "row_count": result.row_count,
    }

    await ctx.info(
        f"Imported {result.row_count} rows with {len(result.columns)} columns"
    )

    return result.model_dump()
