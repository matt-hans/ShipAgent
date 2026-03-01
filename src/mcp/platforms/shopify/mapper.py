# src/mcp/platforms/shopify/mapper.py
"""Shopify order mapper: raw Shopify API order → flat DuckDB row.

Pure module — no FastMCP, no server, no network dependencies.
Only imports: json, math, and platform_models.compute_canonical_hash.
"""
from __future__ import annotations

import json
import math
from typing import Any

from src.services.platform_models import compute_canonical_hash


class ShopifyMapper:
    """Maps raw Shopify order dicts to flat rows for the external_orders table."""

    MAPPING_VERSION = "1.0"

    def to_flat_row(self, order: dict[str, Any], credential_ref: str) -> dict[str, Any]:
        """Convert a raw Shopify order dict to a flat DuckDB row.

        Args:
            order: Raw order dict from Shopify Admin API.
            credential_ref: Credential profile identifier (e.g., "primary").

        Returns:
            Flat dict matching the external_orders schema.
        """
        shipping = order.get("shipping_address") or {}
        customer = order.get("customer") or {}
        line_items = order.get("line_items") or []
        shipping_lines = order.get("shipping_lines") or []

        # Weight: sum of (grams * quantity) across all line items, integer
        total_weight = sum(
            (item.get("grams") or 0) * (item.get("quantity") or 0)
            for item in line_items
        )

        # Price: convert decimal string to integer cents
        total_price_str = order.get("total_price")
        total_price_cents = None
        if total_price_str is not None:
            total_price_cents = int(round(float(total_price_str) * 100))

        # Item count: sum of quantities
        item_count = sum(item.get("quantity") or 0 for item in line_items)

        # Customer name
        first = customer.get("first_name") or ""
        last = customer.get("last_name") or ""
        customer_name = f"{first} {last}".strip() or None

        # Fulfillment status defaults to "unfulfilled"
        fulfillment_status = order.get("fulfillment_status") or "unfulfilled"

        # Shipping method from first shipping line
        shipping_method = shipping_lines[0].get("title") if shipping_lines else None
        service_code = shipping_lines[0].get("code") if shipping_lines else None

        # Build the flat row (core columns matching external_orders schema)
        row: dict[str, Any] = {
            "platform": "shopify",
            "external_id": str(order.get("id", "")),
            "credential_ref": credential_ref,
            "order_number": str(order.get("order_number", "")),
            "order_status": order.get("financial_status"),
            "payment_status": order.get("financial_status"),
            "fulfillment_status": fulfillment_status,
            "created_at": order.get("created_at"),
            "updated_at": order.get("updated_at"),
            "ship_to_name": shipping.get("name"),
            "ship_to_company": shipping.get("company"),
            "ship_to_address1": shipping.get("address1"),
            "ship_to_address2": shipping.get("address2"),
            "ship_to_city": shipping.get("city"),
            "ship_to_state": shipping.get("province_code"),
            "ship_to_postal": shipping.get("zip"),
            "ship_to_country": shipping.get("country_code"),
            "ship_to_phone": shipping.get("phone"),
            "is_residential": None,  # Shopify doesn't provide this
            "total_weight_grams": total_weight if total_weight > 0 else None,
            "package_count": 1,
            "shipping_method": shipping_method,
            "service_code": service_code,
            "total_price_cents": total_price_cents,
            "currency": order.get("currency", "USD"),
            "customer_name": customer_name,
            "customer_email": customer.get("email"),
            "item_count": item_count if item_count > 0 else None,
            "tags": order.get("tags"),
            "mapping_version": self.MAPPING_VERSION,
        }

        # Compute canonical hash for change detection
        row["canonical_hash"] = compute_canonical_hash(row)

        # Preserve raw JSON for debugging/auditing
        row["raw_json"] = json.dumps(order, default=str)

        # Attrs JSON for non-core fields (note, risk, discount codes, etc.)
        attrs: dict[str, Any] = {}
        if order.get("note"):
            attrs["note"] = order["note"]
        if order.get("discount_codes"):
            attrs["discount_codes"] = order["discount_codes"]
        if order.get("note_attributes"):
            attrs["note_attributes"] = order["note_attributes"]
        if customer.get("tags"):
            attrs["customer_tags"] = customer["tags"]
        if customer.get("orders_count"):
            attrs["customer_order_count"] = customer["orders_count"]
        row["attrs_json"] = json.dumps(attrs, default=str) if attrs else "{}"

        return row
