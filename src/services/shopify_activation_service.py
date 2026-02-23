"""Shared Shopify activation service.

Encapsulates the full Shopify-as-data-source activation flow so both
the agent tool (connect_shopify) and the REST API endpoint
(POST /platforms/shopify/activate) use identical logic.
"""

import logging
from typing import Any

from src.services.gateway_provider import (
    get_data_gateway,
    get_external_sources_client,
)
from src.services.runtime_credentials import resolve_shopify_credentials

logger = logging.getLogger(__name__)


class ShopifyActivationError(Exception):
    """Raised when any step of Shopify activation fails."""

    def __init__(self, message: str, step: str = "unknown") -> None:
        self.step = step
        super().__init__(message)


def _prepare_shopify_import_rows(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize Shopify rows for deterministic import schema.

    Preserves optional keys (including None values) and unions keys across all
    rows so schema coverage does not depend on the first record.
    """
    filtered_rows: list[dict[str, Any]] = []
    all_keys: set[str] = set()

    for order in orders:
        row = {
            key: value
            for key, value in order.items()
            if key not in ("items", "raw_data")
        }
        filtered_rows.append(row)
        all_keys.update(row.keys())

    ordered_keys = sorted(all_keys)
    normalized_rows = [{key: row.get(key) for key in ordered_keys} for row in filtered_rows]
    normalized_rows.sort(
        key=lambda row: (
            str(row.get("order_id", "")),
            str(row.get("order_number", "")),
        )
    )
    return normalized_rows


async def activate_shopify_as_data_source() -> dict[str, Any]:
    """Activate Shopify as the active data source.

    Performs the full flow: resolve credentials → connect platform →
    fetch orders → normalize → import into Data Source MCP.

    Returns:
        Dict with keys: row_count, source_type, columns, message.

    Raises:
        ShopifyActivationError: On any failure step.
    """
    # 1. Resolve credentials
    shopify_creds = resolve_shopify_credentials()
    if shopify_creds is None:
        raise ShopifyActivationError(
            "Shopify credentials not configured. "
            "Connect Shopify in Settings or set SHOPIFY_ACCESS_TOKEN "
            "and SHOPIFY_STORE_DOMAIN environment variables.",
            step="credentials",
        )
    access_token = shopify_creds.access_token
    store_domain = shopify_creds.store_domain

    # 2. Connect External Sources MCP
    try:
        ext = await get_external_sources_client()
    except Exception as exc:
        raise ShopifyActivationError(
            f"Failed to initialize External Sources gateway: {exc}",
            step="gateway",
        ) from exc

    # 3. Connect to Shopify platform
    connect_result = await ext.connect_platform(
        platform="shopify",
        credentials={"access_token": access_token},
        store_url=f"https://{store_domain}",
    )
    if not connect_result.get("success"):
        raise ShopifyActivationError(
            f"Failed to connect to Shopify: "
            f"{connect_result.get('error', 'Unknown error')}",
            step="connect",
        )

    # 4. Fetch orders
    orders_result = await ext.fetch_orders("shopify", limit=250)
    if not orders_result.get("success"):
        raise ShopifyActivationError(
            f"Failed to fetch Shopify orders: "
            f"{orders_result.get('error', 'Unknown error')}",
            step="fetch",
        )

    orders = orders_result.get("orders", [])
    if not orders:
        raise ShopifyActivationError(
            "No orders found in Shopify store.",
            step="fetch",
        )

    # 5. Normalize rows
    flat_orders = _prepare_shopify_import_rows(orders)

    # 6. Import via Data Source MCP gateway
    gw = await get_data_gateway()
    import_result = await gw.import_from_records(flat_orders, "shopify")

    row_count = import_result.get("row_count", len(flat_orders))
    columns = import_result.get("columns", [])

    logger.info(
        "Shopify activated as data source: %d orders imported",
        row_count,
    )

    return {
        "row_count": row_count,
        "source_type": "shopify",
        "columns": columns,
        "message": (
            f"Connected to Shopify and imported {row_count} orders "
            f"as active data source."
        ),
    }
