"""Source info and record import tools for Data Source MCP.

Provides tools for:
- get_source_info: Retrieve metadata about the active data source
- import_records: Import flat dicts as a new data source (for platform orders)
- clear_source: Disconnect/clear the active data source
"""

import hashlib
from typing import Any

from fastmcp import Context


async def get_source_info(ctx: Context) -> dict:
    """Get metadata about the currently active data source.

    Returns:
        Dictionary with active flag, source_type, path, row_count,
        columns with nullable info, and source_signature (schema fingerprint).
    """
    current_source = ctx.request_context.lifespan_context.get("current_source")

    if current_source is None:
        return {"active": False}

    await ctx.info("Retrieving source info")

    # Build signature from schema if available.
    # Mirrors DataSourceService.get_source_signature() format:
    # full SHA-256 hex digest of "name:type:nullable|..." (no truncation).
    db = ctx.request_context.lifespan_context["db"]
    signature = None
    columns = []
    try:
        schema_rows = db.execute("DESCRIBE imported_data").fetchall()
        # col[2] is "YES" or "NO" from DuckDB DESCRIBE — use real nullability,
        # matching schema_tools.get_schema() at line 42 and
        # DataSourceService.get_source_signature() at line 443.
        columns = [
            {"name": col[0], "type": col[1], "nullable": col[2] == "YES"}
            for col in schema_rows
        ]
        # Match DataSourceService fingerprint format exactly:
        # "name:type:nullable_int|name:type:nullable_int|..."
        schema_parts = [
            f"{c['name']}:{c['type']}:{int(c['nullable'])}"
            for c in columns
        ]
        signature = hashlib.sha256(
            "|".join(schema_parts).encode("utf-8")
        ).hexdigest()
    except Exception:
        pass

    return {
        "active": True,
        "source_type": current_source.get("type", "unknown"),
        "path": current_source.get("path"),
        "sheet": current_source.get("sheet"),
        "query": current_source.get("query"),
        "row_count": current_source.get("row_count", 0),
        "columns": columns,
        "signature": signature,
    }


async def import_records(
    records: list[dict[str, Any]],
    source_label: str,
    ctx: Context,
) -> dict:
    """Import a list of flat dictionaries as a data source.

    Replaces any existing source. Used by agent tools to import
    fetched external platform data (e.g., Shopify orders).

    Args:
        records: List of flat dicts to import as rows.
        source_label: Label for the source (e.g., 'shopify').
        ctx: FastMCP context.

    Returns:
        Dictionary with row_count, columns, and source_type.
    """
    db = ctx.request_context.lifespan_context["db"]

    if not records:
        return {"row_count": 0, "source_type": source_label, "columns": []}

    await ctx.info(f"Importing {len(records)} records as '{source_label}' source")

    # Drop existing table
    db.execute("DROP TABLE IF EXISTS imported_data")

    # Build CREATE TABLE from first record's keys
    columns = list(records[0].keys())
    col_defs = ", ".join(f'"{col}" VARCHAR' for col in columns)
    db.execute(f"CREATE TABLE imported_data ({col_defs})")

    # Insert records
    placeholders = ", ".join(["?"] * len(columns))
    col_names = ", ".join(f'"{c}"' for c in columns)
    insert_sql = f"INSERT INTO imported_data ({col_names}) VALUES ({placeholders})"

    for record in records:
        values = [str(record.get(col, "")) if record.get(col) is not None else None for col in columns]
        db.execute(insert_sql, values)

    row_count = db.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]

    # Update current source
    ctx.request_context.lifespan_context["current_source"] = {
        "type": source_label,
        "row_count": row_count,
    }

    await ctx.info(f"Imported {row_count} records with {len(columns)} columns")

    return {
        "row_count": row_count,
        "source_type": source_label,
        "columns": columns,
    }


async def clear_source(ctx: Context) -> dict:
    """Clear the active data source, dropping imported data.

    Mirrors DataSourceService.disconnect() behavior:
    drops imported_data table, clears current_source metadata,
    and resets type_overrides to prevent stale CASTs.

    Returns:
        Status dict.
    """
    db = ctx.request_context.lifespan_context.get("db")
    if db is not None:
        try:
            db.execute("DROP TABLE IF EXISTS imported_data")
        except Exception:
            pass

    ctx.request_context.lifespan_context["current_source"] = None
    # Clear type overrides to prevent stale CASTs leaking to the next source.
    # type_overrides is read by query_tools.get_rows_by_filter() and
    # schema_tools.get_schema() — must be reset on disconnect.
    ctx.request_context.lifespan_context["type_overrides"] = {}
    await ctx.info("Active data source cleared (table + overrides)")
    return {"status": "disconnected"}
