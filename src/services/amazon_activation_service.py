"""Shared Amazon activation service.

Encapsulates the full Amazon-as-data-source activation flow so both
agent tool (connect_amazon) and REST route (POST /platforms/amazon/activate)
use identical deterministic logic.
"""

from __future__ import annotations

import logging
from typing import Any

from src.services.gateway_provider import get_data_gateway, get_external_sources_client
from src.services.runtime_credentials import resolve_amazon_credentials

logger = logging.getLogger(__name__)


class AmazonActivationError(Exception):
    """Raised when any step of Amazon activation fails."""

    def __init__(self, message: str, step: str = "unknown") -> None:
        self.step = step
        super().__init__(message)


def _prepare_amazon_import_rows(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize imported Amazon rows into deterministic column coverage."""
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


async def activate_amazon_as_data_source() -> dict[str, Any]:
    """Activate Amazon as the active data source.

    Flow: resolve credentials -> connect platform -> fetch orders -> normalize -> import.
    """
    amazon_creds = resolve_amazon_credentials()
    if amazon_creds is None:
        raise AmazonActivationError(
            "Amazon credentials not configured. Save Amazon credentials in Settings "
            "or set AMAZON_SP_API_CLIENT_ID, AMAZON_SP_API_CLIENT_SECRET, and "
            "AMAZON_SP_API_REFRESH_TOKEN.",
            step="credentials",
        )
    creds = {
        "client_id": amazon_creds.client_id,
        "client_secret": amazon_creds.client_secret,
        "refresh_token": amazon_creds.refresh_token,
        "marketplace_id": amazon_creds.marketplace_id,
        "sandbox": amazon_creds.sandbox,
    }

    try:
        ext = await get_external_sources_client()
    except Exception as exc:
        raise AmazonActivationError(
            f"Failed to initialize External Sources gateway: {exc}",
            step="gateway",
        ) from exc

    connect_result = await ext.connect_platform(
        platform="amazon",
        credentials=creds,
        store_url=None,
    )
    if not connect_result.get("success"):
        raise AmazonActivationError(
            f"Failed to connect to Amazon: {connect_result.get('error', 'Unknown error')}",
            step="connect",
        )

    orders_result = await ext.fetch_orders("amazon", limit=250, include_items=False)
    if not orders_result.get("success"):
        raise AmazonActivationError(
            f"Failed to fetch Amazon orders: {orders_result.get('error', 'Unknown error')}",
            step="fetch",
        )

    orders = orders_result.get("orders", [])
    if not orders:
        raise AmazonActivationError(
            "No orders found in Amazon account.",
            step="fetch",
        )

    flat_orders = _prepare_amazon_import_rows(orders)

    gw = await get_data_gateway()
    import_result = await gw.import_from_records(flat_orders, "amazon")

    row_count = import_result.get("row_count", len(flat_orders))
    columns = import_result.get("columns", [])

    logger.info("Amazon activated as data source: %d orders imported", row_count)

    return {
        "row_count": row_count,
        "source_type": "amazon",
        "columns": columns,
        "message": (
            f"Connected to Amazon and imported {row_count} orders "
            "as active data source."
        ),
    }
