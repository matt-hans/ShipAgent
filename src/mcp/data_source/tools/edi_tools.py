"""EDI import tools for Data Source MCP.

Provides MCP tools for importing X12 and EDIFACT EDI files.
Automatically detects format and transaction type.
"""

from fastmcp import Context

from src.mcp.data_source.adapters.edi_adapter import EDIAdapter


async def import_edi(file_path: str, ctx: Context) -> dict:
    """Import EDI file and discover schema.

    Imports an EDI file (X12 or EDIFACT format) into DuckDB.
    Automatically detects the format from file content and
    normalizes to a common shipping-relevant schema.

    Supported formats:
    - X12: 850 (Purchase Order), 856 (ASN), 810 (Invoice)
    - EDIFACT: ORDERS, DESADV, INVOIC

    Args:
        file_path: Absolute path to the EDI file

    Returns:
        Dictionary with:
        - row_count: Number of orders imported
        - columns: List of column metadata (name, type, nullable, warnings)
        - warnings: Import-level warnings
        - source_type: 'edi'

    Example:
        >>> result = await import_edi("/path/to/orders.edi", ctx)
        >>> print(result["row_count"])
        5
        >>> print(result["columns"][0])
        {"name": "po_number", "type": "VARCHAR", "nullable": true, "warnings": []}
    """
    # Access DuckDB connection from lifespan context
    # CRITICAL: Use ctx.request_context.lifespan_context per FastMCP v2 pattern
    db = ctx.request_context.lifespan_context["db"]

    await ctx.info(f"Importing EDI from {file_path}")

    adapter = EDIAdapter()
    result = adapter.import_data(conn=db, file_path=file_path)

    # Update current source tracking for session state
    ctx.request_context.lifespan_context["current_source"] = {
        "type": "edi",
        "path": file_path,
        "row_count": result.row_count,
    }

    await ctx.info(
        f"Imported {result.row_count} orders with {len(result.columns)} columns"
    )

    return result.model_dump()
