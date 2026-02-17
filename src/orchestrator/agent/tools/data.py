"""Data source and platform tool handlers.

Handles source metadata, schema inspection, row fetching, filter
resolution, platform status, and Shopify connection.
"""

import logging
import os
from typing import Any

import sqlglot

from src.orchestrator.agent.tools.core import (
    EventEmitterBridge,
    _err,
    _ok,
    _store_fetched_rows,
    get_data_gateway,
    get_external_sources_client,
)
from src.orchestrator.models.filter_spec import (
    FilterCompilationError,
    FilterIntent,
)

logger = logging.getLogger(__name__)


async def get_source_info_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Get metadata about the currently connected data source.

    Args:
        args: Empty dict (no arguments needed).

    Returns:
        Tool response with source_type, file_path, row_count, column count.
    """
    gw = await get_data_gateway()
    info = await gw.get_source_info()
    if info is None:
        return _err(
            "No data source connected. Ask the user to connect a CSV, Excel, or database source."
        )

    return _ok(
        {
            "source_type": info.get("source_type"),
            "file_path": info.get("path"),
            "row_count": info.get("row_count", 0),
            "column_count": len(info.get("columns", [])),
        }
    )


async def get_schema_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Get the column schema of the currently connected data source.

    Args:
        args: Empty dict (no arguments needed).

    Returns:
        Tool response with list of column definitions.
    """
    gw = await get_data_gateway()
    info = await gw.get_source_info()
    if info is None:
        return _err("No data source connected.")

    columns = [
        {"name": col["name"], "type": col["type"], "nullable": col.get("nullable", True)}
        for col in info.get("columns", [])
    ]
    return _ok({"columns": columns})


async def fetch_rows_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Fetch rows from the connected data source using a compiled FilterSpec.

    Accepts exactly one of filter_spec or all_rows=true. Rejects where_clause.

    Args:
        args: Dict with 'filter_spec' (dict) or 'all_rows' (bool), optional 'limit' (int).
        bridge: Optional event emitter bridge for row caching.

    Returns:
        Tool response with fetch_id, row count, and sample rows.
    """
    from src.orchestrator.filter_compiler import compile_filter_spec
    from src.orchestrator.models.filter_spec import (
        FilterCompilationError,
        ResolvedFilterSpec,
    )

    # Hard cutover: reject legacy where_clause
    if "where_clause" in args:
        return _err(
            "where_clause is not accepted. Use resolve_filter_intent "
            "to create a filter_spec."
        )

    filter_spec_raw = args.get("filter_spec")
    all_rows = bool(args.get("all_rows", False))

    # Exactly one of filter_spec or all_rows must be provided
    if filter_spec_raw and all_rows:
        return _err(
            "Conflicting arguments: provide filter_spec OR all_rows=true, not both."
        )
    if not filter_spec_raw and not all_rows:
        return _err(
            "Either filter_spec or all_rows=true is required. "
            "Use resolve_filter_intent to create a filter, or set "
            "all_rows=true to fetch everything."
        )

    limit = args.get("limit", 250)
    include_rows = bool(args.get("include_rows", False))

    gw = await get_data_gateway()

    if filter_spec_raw:
        # Compile FilterSpec → parameterized SQL
        source_info = await gw.get_source_info()
        if source_info is None:
            return _err("No data source connected.")

        columns = source_info.get("columns", [])
        schema_columns = {col["name"] for col in columns}
        column_types = {col["name"]: col["type"] for col in columns}
        schema_signature = source_info.get("signature", "")

        try:
            spec = ResolvedFilterSpec(**filter_spec_raw)
        except Exception as e:
            return _err(f"Invalid filter_spec structure: {e}")

        try:
            compiled = compile_filter_spec(
                spec=spec,
                schema_columns=schema_columns,
                column_types=column_types,
                runtime_schema_signature=schema_signature,
            )
        except FilterCompilationError as e:
            return _err(f"[{e.code.value}] {e.message}")
        except Exception as e:
            logger.error("fetch_rows_tool compile failed: %s", e)
            return _err(f"Filter compilation failed: {e}")

        where_sql = compiled.where_sql
        params = compiled.params
    else:
        # all_rows path
        where_sql = "1=1"
        params = []

    try:
        rows = await gw.get_rows_by_filter(
            where_sql=where_sql, limit=limit, params=params,
        )
        fetch_id = _store_fetched_rows(rows, bridge=bridge)
        payload: dict[str, Any] = {
            "fetch_id": fetch_id,
            "row_count": len(rows),
            "sample_rows": rows[:2],
            "message": "Use fetch_id with add_rows_to_job. Avoid passing full rows through the model.",
        }
        if include_rows:
            payload["rows"] = rows
        return _ok(payload)
    except Exception as e:
        logger.error("fetch_rows_tool failed: %s", e)
        return _err(f"Failed to fetch rows: {e}")


async def validate_filter_syntax_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Validate SQL WHERE clause syntax using sqlglot.

    Args:
        args: Dict with 'where_clause' (str).

    Returns:
        Tool response with valid=True/False and optional error message.
    """
    where_clause = args.get("where_clause", "")
    try:
        sqlglot.parse(f"SELECT * FROM t WHERE {where_clause}")
        return _ok({"valid": True, "where_clause": where_clause})
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError) as e:
        return _ok({"valid": False, "error": str(e), "where_clause": where_clause})


async def resolve_filter_intent_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Resolve a structured FilterIntent into a concrete FilterSpec.

    Takes a FilterIntent JSON from the LLM, resolves semantic references
    (regions, business predicates) against the active data source schema,
    and returns a ResolvedFilterSpec with status and explanation.

    Args:
        args: Dict with 'intent' (FilterIntent JSON dict).
        bridge: Optional event emitter bridge.

    Returns:
        Tool response with resolved spec, status, explanation, and optional
        confirmation/clarification data.
    """
    from src.orchestrator.filter_resolver import resolve_filter_intent

    intent_raw = args.get("intent")
    if not intent_raw:
        return _err("intent is required.")

    # Get schema from gateway
    gw = await get_data_gateway()
    source_info = await gw.get_source_info()
    if source_info is None:
        return _err(
            "No data source connected. Connect a CSV, Excel, or database "
            "source before resolving filters."
        )

    # Extract schema columns and types
    columns = source_info.get("columns", [])
    schema_columns = {col["name"] for col in columns}
    column_types = {col["name"]: col["type"] for col in columns}
    schema_signature = source_info.get("signature", "")

    # Parse intent
    try:
        intent = FilterIntent(**intent_raw)
    except Exception as e:
        return _err(f"Invalid FilterIntent structure: {e}")

    # Resolve
    try:
        resolved = resolve_filter_intent(
            intent=intent,
            schema_columns=schema_columns,
            column_types=column_types,
            schema_signature=schema_signature,
        )
    except FilterCompilationError as e:
        return _err(f"[{e.code.value}] {e.message}")
    except Exception as e:
        logger.error("resolve_filter_intent_tool failed: %s", e)
        return _err(f"Filter resolution failed: {e}")

    return _ok(resolved.model_dump())


async def get_platform_status_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Check which external platforms are connected.

    Args:
        args: Empty dict (no arguments needed).

    Returns:
        Tool response with platform connection statuses.
    """
    platforms: dict[str, Any] = {}

    try:
        gw = await get_data_gateway()
        source_info = await gw.get_source_info()
        if source_info:
            platforms["data_source"] = {
                "connected": True,
                "source_type": source_info.get("source_type"),
                "label": source_info.get("path"),
                "row_count": source_info.get("row_count", 0),
                "column_count": len(source_info.get("columns", [])),
            }
            if source_info.get("source_type") == "shopify":
                store_domain = os.environ.get("SHOPIFY_STORE_DOMAIN", "")
                store_name = store_domain.replace(".myshopify.com", "")
                platforms["shopify"] = {
                    "connected": True,
                    "shop_name": store_name,
                    "store_domain": store_domain,
                }
            else:
                access_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
                store_domain = os.environ.get("SHOPIFY_STORE_DOMAIN")
                platforms["shopify"] = {
                    "connected": False,
                    "configured": bool(access_token and store_domain),
                    "note": "Shopify credentials found but another source is active",
                }
        else:
            platforms["data_source"] = {"connected": False}
            access_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
            store_domain = os.environ.get("SHOPIFY_STORE_DOMAIN")
            platforms["shopify"] = {
                "connected": False,
                "configured": bool(access_token and store_domain),
            }
    except Exception:
        platforms["data_source"] = {"connected": False}
        platforms["shopify"] = {"connected": False}

    return _ok({"platforms": platforms})


async def connect_shopify_tool(
    args: dict[str, Any],
    bridge: "EventEmitterBridge | None" = None,
) -> dict[str, Any]:
    """Connect to Shopify and import orders as active data source.

    Reads SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN from env.
    Calls ExternalSourcesMCPClient to connect + fetch, then
    DataSourceGateway to import records.

    Args:
        args: Empty dict (credentials read from env).
        bridge: Optional event emitter bridge.

    Returns:
        MCP tool response dict.
    """
    access_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    store_domain = os.environ.get("SHOPIFY_STORE_DOMAIN")

    if not access_token or not store_domain:
        return _err(
            "Shopify credentials not configured. Set SHOPIFY_ACCESS_TOKEN "
            "and SHOPIFY_STORE_DOMAIN environment variables."
        )

    ext = await get_external_sources_client()

    # Connect
    connect_result = await ext.connect_platform(
        platform="shopify",
        credentials={"access_token": access_token},
        store_url=f"https://{store_domain}",
    )
    if not connect_result.get("success"):
        return _err(
            f"Failed to connect to Shopify: "
            f"{connect_result.get('error', 'Unknown error')}"
        )

    # Fetch orders
    orders_result = await ext.fetch_orders("shopify", limit=250)
    if not orders_result.get("success"):
        return _err(
            f"Failed to fetch Shopify orders: "
            f"{orders_result.get('error', 'Unknown error')}"
        )

    orders = orders_result.get("orders", [])
    if not orders:
        return _err("No orders found in Shopify store.")

    # Flatten orders for import (exclude nested objects)
    flat_orders = []
    for o in orders:
        flat = {
            k: v
            for k, v in o.items()
            if k not in ("items", "raw_data") and v is not None
        }
        flat_orders.append(flat)

    # Import via gateway
    gw = await get_data_gateway()
    import_result = await gw.import_from_records(flat_orders, "shopify")

    count = import_result.get("row_count", len(flat_orders))
    return _ok({
        "message": (
            f"Connected to Shopify and imported {count} orders "
            f"as active data source."
        ),
        "platform": "shopify",
        "orders_imported": count,
    })
