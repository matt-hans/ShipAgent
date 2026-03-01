"""Source info and record import tools for Data Source MCP.

Provides tools for:
- get_source_info: Retrieve metadata about the active data source
- import_records: Import flat dicts as a new data source (for platform orders)
- activate_external_orders_source: Activate external_orders as the queryable source
- clear_source: Disconnect/clear the active data source
"""

import hashlib
import logging
from typing import Any

from fastmcp import Context

from src.mcp.data_source.models import SOURCE_ROW_NUM_COLUMN

logger = logging.getLogger(__name__)


def _activate_external_orders_view(db: Any) -> dict[str, Any] | None:
    """Create an imported_data VIEW over external_orders and return source metadata.

    Checks whether external_orders has rows. If so, drops any existing
    imported_data TABLE or VIEW and creates a VIEW that maps external_orders
    to the imported_data interface (with a synthetic _source_row_num column).

    This allows all existing query tools (get_rows_by_filter, get_schema,
    get_column_samples, etc.) to work against platform order data without
    modification.

    Args:
        db: DuckDB connection from lifespan context.

    Returns:
        current_source dict if external_orders has data, None otherwise.
    """
    try:
        result = db.execute(
            "SELECT COUNT(*) FROM external_orders"
        ).fetchone()
        row_count = int(result[0]) if result else 0
    except (Exception, TypeError, ValueError):
        return None

    if row_count <= 0:
        return None

    # Drop any prior imported_data object (TABLE or VIEW) to avoid conflicts
    try:
        db.execute("DROP VIEW IF EXISTS imported_data")
    except Exception:
        pass
    try:
        db.execute("DROP TABLE IF EXISTS imported_data")
    except Exception:
        pass

    # Create VIEW with synthetic _source_row_num for row identity
    db.execute(f"""
        CREATE VIEW imported_data AS
        SELECT
            ROW_NUMBER() OVER (
                ORDER BY platform, external_id, credential_ref
            ) AS {SOURCE_ROW_NUM_COLUMN},
            *
        FROM external_orders
    """)

    logger.info(
        "Activated external_orders as imported_data VIEW (%d rows)", row_count
    )

    return {
        "type": "external_orders",
        "row_count": row_count,
        "deterministic_ready": True,
        "row_key_strategy": "composite_pk",
        "row_key_columns": ["platform", "external_id", "credential_ref"],
    }


async def get_source_info(ctx: Context) -> dict:
    """Get metadata about the currently active data source.

    When no file-based source is active, auto-detects platform orders
    in the external_orders table and activates them as the queryable source.

    Returns:
        Dictionary with active flag, source_type, path, row_count,
        columns with nullable info, and source_signature (schema fingerprint).
    """
    current_source = ctx.request_context.lifespan_context.get("current_source")

    # Auto-detect: if no source is active, check external_orders for data
    if current_source is None:
        db = ctx.request_context.lifespan_context["db"]
        ext_source = _activate_external_orders_view(db)
        if ext_source is not None:
            ctx.request_context.lifespan_context["current_source"] = ext_source
            current_source = ext_source

    if current_source is None:
        return {"active": False}

    await ctx.info("Retrieving source info")

    # Build signature from schema if available as:
    # full SHA-256 hex digest of "name:type:nullable|..." (no truncation).
    db = ctx.request_context.lifespan_context["db"]
    signature = None
    columns = []
    try:
        schema_rows = db.execute("DESCRIBE imported_data").fetchall()
        # col[2] is "YES" or "NO" from DuckDB DESCRIBE — use real nullability.
        columns = [
            {"name": col[0], "type": col[1], "nullable": col[2] == "YES"}
            for col in schema_rows
        ]
        # Fingerprint format:
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
        "deterministic_ready": current_source.get("deterministic_ready", True),
        "row_key_strategy": current_source.get("row_key_strategy", "source_row_num"),
        "row_key_columns": current_source.get("row_key_columns", []),
    }


async def activate_external_orders_source(ctx: Context) -> dict:
    """Activate the external_orders table as the queryable data source.

    Creates a VIEW named imported_data over the external_orders table,
    enabling all existing data tools (get_source_info, fetch_rows,
    get_schema, etc.) to query platform order data.

    Called by the PlatformActivationService after upserting orders.

    Returns:
        Dict with status, row_count, and source_type.
    """
    db = ctx.request_context.lifespan_context["db"]
    ext_source = _activate_external_orders_view(db)

    if ext_source is None:
        return {
            "status": "no_data",
            "message": "external_orders table has no rows",
        }

    ctx.request_context.lifespan_context["current_source"] = ext_source
    ctx.request_context.lifespan_context["type_overrides"] = {}

    await ctx.info(
        f"Activated external_orders as data source ({ext_source['row_count']} rows)"
    )

    return {
        "status": "activated",
        "row_count": ext_source["row_count"],
        "source_type": "external_orders",
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

    # Drop existing VIEW (from external_orders activation) or TABLE
    db.execute("DROP VIEW IF EXISTS imported_data")
    db.execute("DROP TABLE IF EXISTS imported_data")

    # Build CREATE TABLE from first record's keys
    # Include _source_row_num as identity column for row tracking (matching CSV adapter)
    from src.mcp.data_source.models import SOURCE_ROW_NUM_COLUMN
    columns = list(records[0].keys())
    col_defs = ", ".join(f'"{col}" VARCHAR' for col in columns)
    db.execute(f"CREATE TABLE imported_data ({SOURCE_ROW_NUM_COLUMN} INTEGER, {col_defs})")

    # Insert records with sequential row numbers
    placeholders = ", ".join(["?"] * (len(columns) + 1))  # +1 for _source_row_num
    col_names = ", ".join(f'"{c}"' for c in columns)
    insert_sql = f"INSERT INTO imported_data ({SOURCE_ROW_NUM_COLUMN}, {col_names}) VALUES ({placeholders})"

    for idx, record in enumerate(records, start=1):
        values = [idx] + [str(record.get(col, "")) if record.get(col) is not None else None for col in columns]
        db.execute(insert_sql, values)

    row_count = db.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]

    # Update current source
    ctx.request_context.lifespan_context["current_source"] = {
        "type": source_label,
        "row_count": row_count,
        "deterministic_ready": True,
        "row_key_strategy": "source_row_num",
        "row_key_columns": [SOURCE_ROW_NUM_COLUMN],
    }

    await ctx.info(f"Imported {row_count} records with {len(columns)} columns")

    return {
        "row_count": row_count,
        "source_type": source_label,
        "columns": columns,
    }


async def clear_source(ctx: Context) -> dict:
    """Clear the active data source, dropping imported data.

    Drops imported_data table, clears current_source metadata,
    and resets type_overrides to prevent stale CASTs.

    Returns:
        Status dict.
    """
    db = ctx.request_context.lifespan_context.get("db")
    if db is not None:
        try:
            db.execute("DROP VIEW IF EXISTS imported_data")
        except Exception:
            pass
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
