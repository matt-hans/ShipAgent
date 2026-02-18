"""Data source and platform tool handlers.

Handles source metadata, schema inspection, row fetching, filter
resolution, platform status, and Shopify connection.
"""

import hashlib
import json
import logging
import os
from typing import Any



from src.orchestrator.agent.intent_detection import (
    is_confirmation_response,
    is_shipping_request,
)
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
    ResolvedFilterSpec,
)
from src.services.decision_audit_service import DecisionAuditService

logger = logging.getLogger(__name__)


def _determinism_mode() -> str:
    """Return determinism enforcement mode ('warn' or 'enforce')."""
    raw = os.environ.get("DETERMINISM_ENFORCEMENT_MODE", "warn").strip().lower()
    return "enforce" if raw == "enforce" else "warn"


def _validate_allowed_args(
    tool_name: str,
    args: dict[str, Any],
    allowed: set[str],
) -> dict[str, Any] | None:
    """Warn or deny unknown args based on DETERMINISM_ENFORCEMENT_MODE."""
    unknown = sorted(k for k in args.keys() if k not in allowed)
    if not unknown:
        return None
    mode = _determinism_mode()
    logger.warning(
        "metric=tool_unknown_args_total tool=%s unknown_keys=%s mode=%s",
        tool_name,
        unknown,
        mode,
    )
    if mode == "enforce":
        return _err(
            f"Unexpected argument(s) for {tool_name}: {', '.join(unknown)}. "
            "Remove unknown keys and retry."
        )
    return None


def _build_source_signature(
    source_info: dict[str, Any],
    schema_signature: str,
) -> dict[str, str]:
    """Construct a stable source signature payload from source info."""
    return {
        "source_type": str(source_info.get("source_type", "")),
        "source_ref": str(source_info.get("path") or source_info.get("query") or ""),
        "schema_fingerprint": str(schema_signature),
    }


def _audit_event(
    phase: str,
    event_name: str,
    payload: dict[str, Any],
    *,
    actor: str = "tool",
    tool_name: str | None = None,
) -> None:
    """Emit best-effort decision audit event in current run context."""
    DecisionAuditService.log_event_from_context(
        phase=phase,
        event_name=event_name,
        actor=actor,
        tool_name=tool_name,
        payload=payload,
    )


def _determinism_guard_error(source_info: dict[str, Any]) -> str | None:
    """Return a deterministic guard error for shipping if source isn't stable."""
    deterministic_ready = bool(source_info.get("deterministic_ready", True))
    if deterministic_ready:
        return None
    strategy = str(source_info.get("row_key_strategy", "none"))
    return (
        "Shipping determinism guard: active source does not have stable row ordering "
        f"(row_key_strategy={strategy}). Re-import with row_key_columns or use a "
        "source with PRIMARY KEY/UNIQUE constraints."
    )

def _command_for_filter_cache(bridge: EventEmitterBridge) -> str | None:
    """Select a stable command string to bind with cached resolved specs.

    Confirmation turns ("yes", "proceed") should not overwrite command context
    with non-semantic text.
    """
    last_msg = bridge.last_user_message
    if isinstance(last_msg, str):
        trimmed = last_msg.strip()
        if trimmed:
            if is_confirmation_response(trimmed):
                if (
                    isinstance(bridge.last_shipping_command, str)
                    and bridge.last_shipping_command.strip()
                ):
                    return bridge.last_shipping_command.strip()
                if (
                    isinstance(bridge.last_resolved_filter_command, str)
                    and bridge.last_resolved_filter_command.strip()
                ):
                    return bridge.last_resolved_filter_command.strip()
            return trimmed
    if (
        isinstance(bridge.last_resolved_filter_command, str)
        and bridge.last_resolved_filter_command.strip()
    ):
        return bridge.last_resolved_filter_command.strip()
    return None


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
        Tool response with fetch_id, total_count, returned_count, and sample rows.
    """
    unknown = _validate_allowed_args(
        "fetch_rows",
        args,
        {"filter_spec", "all_rows", "limit", "include_rows"},
    )
    if unknown is not None:
        return unknown

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

    # Deterministic routing: shipping commands should use the execution
    # pipeline, not exploratory fetch_rows flows.
    if bridge is not None and (
        is_shipping_request(bridge.last_user_message)
        or (
            is_confirmation_response(bridge.last_user_message)
            and bool(bridge.last_shipping_command)
        )
    ):
        return _err(
            "fetch_rows is for exploratory data inspection. For shipping commands, "
            "use ship_command_pipeline with a resolved filter_spec."
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
        total_count = 0
        used_count_endpoint = False
        get_rows_with_count = getattr(gw, "get_rows_with_count", None)
        if callable(get_rows_with_count):
            result = await get_rows_with_count(
                where_sql=where_sql,
                limit=limit,
                params=params,
            )
            if isinstance(result, dict):
                result_rows = result.get("rows")
                if isinstance(result_rows, list):
                    rows = result_rows
                    total_count = int(result.get("total_count", len(rows)))
                    used_count_endpoint = True

        if not used_count_endpoint:
            rows = await gw.get_rows_by_filter(
                where_sql=where_sql,
                limit=limit,
                params=params,
            )
            total_count = len(rows)

        fetch_id = _store_fetched_rows(rows, bridge=bridge)
        payload: dict[str, Any] = {
            "fetch_id": fetch_id,
            "row_count": total_count,
            "total_count": total_count,
            "returned_count": len(rows),
            "sample_rows": rows[:2],
            "message": (
                "Exploration-only result set. "
                "Use total_count for cardinality; returned_count reflects the page size. "
                "For shipment execution, use ship_command_pipeline."
            ),
        }
        if include_rows:
            payload["rows"] = rows
        return _ok(payload)
    except Exception as e:
        logger.error("fetch_rows_tool failed: %s", e)
        return _err(f"Failed to fetch rows: {e}")


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
    unknown = _validate_allowed_args(
        "resolve_filter_intent",
        args,
        {"intent"},
    )
    if unknown is not None:
        return unknown

    from src.orchestrator.filter_resolver import resolve_filter_intent

    intent_raw = args.get("intent")
    if not intent_raw:
        return _err("intent is required.")
    intent_hash = hashlib.sha256(
        json.dumps(intent_raw, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    _audit_event(
        "intent",
        "resolve_filter_intent.requested",
        {
            "intent_hash": intent_hash,
            "intent_keys": sorted(intent_raw.keys()) if isinstance(intent_raw, dict) else [],
        },
        tool_name="resolve_filter_intent",
    )

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
    source_signature = _build_source_signature(source_info, schema_signature)
    _audit_event(
        "resolution",
        "resolve_filter_intent.source_signature",
        {"source_signature": source_signature},
        tool_name="resolve_filter_intent",
    )

    # Shipping paths must use deterministic sources.
    if bridge is not None and is_shipping_request(bridge.last_user_message):
        guard_error = _determinism_guard_error(source_info)
        if guard_error:
            logger.warning(
                "metric=determinism_guard_blocked_total tool=resolve_filter_intent",
            )
            return _err(guard_error)

    # Parse intent
    try:
        intent = FilterIntent(**intent_raw)
    except Exception as e:
        return _err(f"Invalid FilterIntent structure: {e}")

    # Resolve — pass session confirmations for Tier B bypass
    session_confirmations = (
        bridge.confirmed_resolutions if bridge is not None else None
    )
    try:
        resolved = resolve_filter_intent(
            intent=intent,
            schema_columns=schema_columns,
            column_types=column_types,
            schema_signature=schema_signature,
            session_confirmations=session_confirmations,
            source_signature=source_signature,
        )
    except FilterCompilationError as e:
        _audit_event(
            "error",
            "resolve_filter_intent.failed",
            {"code": e.code.value, "message": e.message},
            tool_name="resolve_filter_intent",
        )
        return _err(f"[{e.code.value}] {e.message}")
    except Exception as e:
        logger.error("resolve_filter_intent_tool failed: %s", e)
        _audit_event(
            "error",
            "resolve_filter_intent.failed",
            {"message": str(e)},
            tool_name="resolve_filter_intent",
        )
        return _err(f"Filter resolution failed: {e}")

    resolved_payload = resolved.model_dump()
    if bridge is not None:
        if resolved.status.value == "RESOLVED":
            bridge.last_resolved_filter_spec = resolved_payload
            bridge.last_resolved_filter_command = _command_for_filter_cache(bridge)
            bridge.last_resolved_filter_schema_signature = (
                schema_signature if isinstance(schema_signature, str) and schema_signature else None
            )
        else:
            bridge.last_resolved_filter_spec = None
            bridge.last_resolved_filter_command = None
            bridge.last_resolved_filter_schema_signature = None

    _audit_event(
        "resolution",
        "resolve_filter_intent.completed",
        {
            "intent_hash": intent_hash,
            "status": resolved.status.value,
            "pending_confirmation_count": len(resolved.pending_confirmations or []),
            "unresolved_count": len(resolved.unresolved_terms or []),
            "schema_signature": schema_signature,
            "source_fingerprint": resolved.source_fingerprint,
            "compiler_version": resolved.compiler_version,
            "mapping_version": resolved.mapping_version,
            "normalizer_version": resolved.normalizer_version,
        },
        tool_name="resolve_filter_intent",
    )
    return _ok(resolved_payload)


async def confirm_filter_interpretation_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Confirm a Tier-B filter interpretation and re-resolve to RESOLVED.

    After resolve_filter_intent returns NEEDS_CONFIRMATION, the agent
    presents the pending_confirmations to the user. Once confirmed, the
    agent calls this tool with the resolution_token and the original
    intent. This tool:
    1. Validates the token is genuine NEEDS_CONFIRMATION.
    2. Stores the confirmed spec in session cache (bridge.confirmed_resolutions).
    3. Re-resolves the intent with confirmations to produce a RESOLVED token.

    Args:
        args: Dict with 'resolution_token' (str) and 'intent' (FilterIntent dict).
        bridge: Event emitter bridge (required for confirmation cache).

    Returns:
        Tool response with the re-resolved RESOLVED spec.
    """
    unknown = _validate_allowed_args(
        "confirm_filter_interpretation",
        args,
        {"resolution_token", "intent"},
    )
    if unknown is not None:
        return unknown

    from src.orchestrator.filter_resolver import (
        _validate_resolution_token,
        resolve_filter_intent,
    )

    resolution_token = args.get("resolution_token")
    intent_raw = args.get("intent")

    if not resolution_token:
        return _err("resolution_token is required.")
    if not intent_raw:
        return _err("intent is required (same FilterIntent used for resolve_filter_intent).")
    if bridge is None:
        return _err("Internal error: bridge not available for confirmation caching.")
    _audit_event(
        "resolution",
        "confirm_filter_interpretation.requested",
        {
            "token_present": bool(resolution_token),
            "intent_keys": sorted(intent_raw.keys()) if isinstance(intent_raw, dict) else [],
        },
        tool_name="confirm_filter_interpretation",
    )

    # Get schema context
    gw = await get_data_gateway()
    source_info = await gw.get_source_info()
    if source_info is None:
        return _err("No data source connected.")

    columns = source_info.get("columns", [])
    schema_columns = {col["name"] for col in columns}
    column_types = {col["name"]: col["type"] for col in columns}
    schema_signature = source_info.get("signature", "")
    source_signature = _build_source_signature(source_info, schema_signature)

    guard_error = _determinism_guard_error(source_info)
    if guard_error:
        logger.warning(
            "metric=determinism_guard_blocked_total tool=confirm_filter_interpretation",
        )
        return _err(guard_error)

    # Validate the token is genuine and NEEDS_CONFIRMATION
    token_payload = _validate_resolution_token(resolution_token, schema_signature)
    if token_payload is None:
        _audit_event(
            "error",
            "confirm_filter_interpretation.invalid_token",
            {"reason": "token_invalid_or_expired"},
            tool_name="confirm_filter_interpretation",
        )
        return _err(
            "Invalid or expired resolution token. "
            "Re-run resolve_filter_intent to get a fresh token."
        )
    token_status = token_payload.get("resolution_status", "")
    if token_status != "NEEDS_CONFIRMATION":
        _audit_event(
            "error",
            "confirm_filter_interpretation.invalid_status",
            {"token_status": token_status},
            tool_name="confirm_filter_interpretation",
        )
        return _err(
            f"Token has status '{token_status}', not 'NEEDS_CONFIRMATION'. "
            "Only NEEDS_CONFIRMATION tokens can be confirmed."
        )

    # Parse intent
    try:
        intent = FilterIntent(**intent_raw)
    except Exception as e:
        return _err(f"Invalid FilterIntent structure: {e}")

    # Re-resolve the same intent without confirmations to reproduce the
    # exact spec that was used to generate the original token.
    try:
        initial_spec = resolve_filter_intent(
            intent=intent,
            schema_columns=schema_columns,
            column_types=column_types,
            schema_signature=schema_signature,
            session_confirmations=None,
            source_signature=source_signature,
        )
    except FilterCompilationError as e:
        return _err(f"[{e.code.value}] {e.message}")
    except Exception as e:
        logger.error("confirm_filter_interpretation re-resolve failed: %s", e)
        return _err(f"Re-resolution failed: {e}")

    # Enforce token/intent binding: the token's resolved_spec_hash must
    # match the hash of the spec produced by resolving THIS intent.
    # This prevents using a NORTHEAST token to confirm BUSINESS_RECIPIENT.
    fresh_spec_hash = hashlib.sha256(
        initial_spec.root.model_dump_json().encode()
    ).hexdigest()
    token_spec_hash = token_payload.get("resolved_spec_hash", "")
    if fresh_spec_hash != token_spec_hash:
        _audit_event(
            "error",
            "confirm_filter_interpretation.token_intent_mismatch",
            {},
            tool_name="confirm_filter_interpretation",
        )
        return _err(
            "Token/intent mismatch: the resolution token was generated for "
            "a different FilterIntent. Pass the same intent that produced "
            "the NEEDS_CONFIRMATION token."
        )

    # Validate canonical dict version
    from src.services.filter_constants import CANONICAL_DICT_VERSION
    token_dict_version = token_payload.get("canonical_dict_version", "")
    if token_dict_version != CANONICAL_DICT_VERSION:
        _audit_event(
            "error",
            "confirm_filter_interpretation.dict_version_mismatch",
            {
                "token_dict_version": token_dict_version,
                "expected_dict_version": CANONICAL_DICT_VERSION,
            },
            tool_name="confirm_filter_interpretation",
        )
        return _err(
            f"Dict version mismatch: token was generated with "
            f"'{token_dict_version}' but current version is "
            f"'{CANONICAL_DICT_VERSION}'. Re-run resolve_filter_intent."
        )

    # Store confirmed spec in session cache keyed by the original token
    bridge.confirmed_resolutions[resolution_token] = initial_spec

    # Re-resolve with the confirmations now in place
    try:
        resolved = resolve_filter_intent(
            intent=intent,
            schema_columns=schema_columns,
            column_types=column_types,
            schema_signature=schema_signature,
            session_confirmations=bridge.confirmed_resolutions,
            source_signature=source_signature,
        )
    except FilterCompilationError as e:
        return _err(f"[{e.code.value}] {e.message}")
    except Exception as e:
        logger.error("confirm_filter_interpretation_tool failed: %s", e)
        return _err(f"Confirmation re-resolution failed: {e}")

    if resolved.status.value != "RESOLVED":
        _audit_event(
            "error",
            "confirm_filter_interpretation.unresolved_after_confirm",
            {"status": resolved.status.value},
            tool_name="confirm_filter_interpretation",
        )
        return _err(
            f"Re-resolution produced status '{resolved.status.value}' instead of "
            "'RESOLVED'. There may be additional unresolved terms."
        )

    resolved_payload = resolved.model_dump()
    bridge.last_resolved_filter_spec = resolved_payload
    bridge.last_resolved_filter_command = _command_for_filter_cache(bridge)
    bridge.last_resolved_filter_schema_signature = (
        schema_signature if isinstance(schema_signature, str) and schema_signature else None
    )
    _audit_event(
        "resolution",
        "confirm_filter_interpretation.completed",
        {
            "status": resolved.status.value,
            "schema_signature": schema_signature,
            "source_fingerprint": resolved.source_fingerprint,
        },
        tool_name="confirm_filter_interpretation",
    )

    return _ok(resolved_payload)


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

    # Deterministic import order: stable by order_id, then order_number.
    flat_orders.sort(
        key=lambda row: (
            str(row.get("order_id", "")),
            str(row.get("order_number", "")),
        ),
    )

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
