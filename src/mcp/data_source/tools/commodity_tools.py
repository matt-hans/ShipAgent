"""Commodity import and query tools for international shipping.

Manages the `imported_commodities` auxiliary table alongside the
primary `imported_data` table. Follows the same ephemeral session
model — import replaces previous commodities data.
"""

from collections import defaultdict
from typing import Any

from fastmcp import Context


COMMODITIES_TABLE = "imported_commodities"

# Required columns for commodity data
COMMODITY_COLUMNS = [
    ("order_id", "INTEGER"),
    ("description", "VARCHAR"),
    ("commodity_code", "VARCHAR"),
    ("origin_country", "VARCHAR(2)"),
    ("quantity", "INTEGER"),
    ("unit_value", "VARCHAR"),
    ("unit_of_measure", "VARCHAR DEFAULT 'PCS'"),
]


def import_commodities_sync(
    db: Any,
    commodities: list[dict],
) -> dict:
    """Import commodity data into the imported_commodities table.

    Replaces any existing commodity data (same ephemeral model as
    imported_data). Links to orders via order_id.

    Args:
        db: DuckDB connection.
        commodities: List of commodity dicts, each with order_id,
            description, commodity_code, origin_country, quantity,
            unit_value, and optional unit_of_measure.

    Returns:
        Dict with row_count and table_name.
    """
    col_defs = ", ".join(f"{name} {dtype}" for name, dtype in COMMODITY_COLUMNS)
    db.execute(f"CREATE OR REPLACE TABLE {COMMODITIES_TABLE} ({col_defs})")

    for comm in commodities:
        db.execute(
            f"""INSERT INTO {COMMODITIES_TABLE}
            (order_id, description, commodity_code, origin_country, quantity, unit_value, unit_of_measure)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                comm["order_id"],
                str(comm["description"])[:35],
                str(comm.get("commodity_code", "")),
                str(comm.get("origin_country", "")).upper(),
                int(comm.get("quantity", 1)),
                str(comm.get("unit_value", "0")),
                str(comm.get("unit_of_measure", "PCS")).upper(),
            ],
        )

    count = db.execute(f"SELECT COUNT(*) FROM {COMMODITIES_TABLE}").fetchone()[0]
    return {"row_count": count, "table_name": COMMODITIES_TABLE}


def get_commodities_bulk_sync(
    db: Any,
    order_ids: list[int | str],
) -> dict[int | str, list[dict]]:
    """Get commodities for multiple orders, grouped by order_id.

    Args:
        db: DuckDB connection.
        order_ids: List of order IDs to look up.

    Returns:
        Dict mapping order_id to list of commodity dicts.
        Missing orders are omitted from the result.
    """
    # Check if commodities table exists
    try:
        tables = [r[0] for r in db.execute("SHOW TABLES").fetchall()]
    except Exception:
        return {}

    if COMMODITIES_TABLE not in tables:
        return {}

    if not order_ids:
        return {}

    placeholders = ", ".join("?" for _ in order_ids)
    rows = db.execute(
        f"SELECT * FROM {COMMODITIES_TABLE} WHERE order_id IN ({placeholders})",
        order_ids,
    ).fetchall()

    # Get column names
    schema = db.execute(f"DESCRIBE {COMMODITIES_TABLE}").fetchall()
    columns = [col[0] for col in schema]

    result: dict[int | str, list[dict]] = defaultdict(list)
    for row in rows:
        row_dict = dict(zip(columns, row))
        oid = row_dict.pop("order_id")
        result[oid].append(row_dict)

    return dict(result)


async def import_commodities(
    commodities: list[dict],
    ctx: Context,
) -> dict:
    """MCP tool: Import commodity data for international shipments.

    Each commodity must have an order_id matching the primary imported_data.
    Replaces any previously imported commodities.

    Args:
        commodities: List of commodity dicts with order_id, description,
            commodity_code, origin_country, quantity, unit_value.
        ctx: FastMCP context with lifespan resources.

    Returns:
        Dict with row_count and table_name.
    """
    db = ctx.request_context.lifespan_context["db"]
    await ctx.info(f"Importing {len(commodities)} commodities")
    result = import_commodities_sync(db, commodities)

    # Track auxiliary table in session state
    ctx.request_context.lifespan_context["commodities_loaded"] = True

    await ctx.info(f"Imported {result['row_count']} commodities")
    return result


async def get_commodities_bulk(
    order_ids: list[int | str],
    ctx: Context,
) -> dict:
    """MCP tool: Get commodities for multiple orders.

    Args:
        order_ids: List of order IDs to retrieve commodities for.
        ctx: FastMCP context with lifespan resources.

    Returns:
        Dict mapping order_id to list of commodity dicts.
    """
    db = ctx.request_context.lifespan_context["db"]
    await ctx.info(f"Fetching commodities for {len(order_ids)} orders")
    result = get_commodities_bulk_sync(db, order_ids)
    await ctx.info(f"Found commodities for {len(result)} orders")
    return result
