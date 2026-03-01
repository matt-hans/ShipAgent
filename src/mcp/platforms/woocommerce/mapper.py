# src/mcp/platforms/woocommerce/mapper.py
"""WooCommerce order mapper: raw WooCommerce API order -> flat DuckDB row.

Pure module -- no FastMCP, no server, no network dependencies.
Only imports: json and platform_models.compute_canonical_hash.
"""
from __future__ import annotations

import json
from typing import Any

from src.services.platform_models import compute_canonical_hash


class WoocommerceMapper:
    """Maps raw WooCommerce order dicts to flat rows for the external_orders table.

    Class name uses lowercase 'c' after 'Woo' because the dynamic mapper
    loader in PlatformActivationService does ``platform_id.capitalize() + "Mapper"``
    which yields ``WoocommerceMapper`` for platform_id ``"woocommerce"``.
    """

    MAPPING_VERSION = "1.0"

    def to_flat_row(self, order: dict[str, Any], credential_ref: str) -> dict[str, Any]:
        """Convert a raw WooCommerce order dict to a flat DuckDB row.

        Args:
            order: Raw order dict from WooCommerce REST API v3.
            credential_ref: Credential profile identifier (e.g., "primary").

        Returns:
            Flat dict matching the external_orders schema.
        """
        billing = order.get("billing") or {}
        shipping = order.get("shipping") or {}
        line_items = order.get("line_items") or []

        # Weight: WooCommerce stores weight per product, sum all (grams * quantity)
        total_weight = 0
        for item in line_items:
            w = item.get("weight")
            qty = item.get("quantity") or 1
            if w:
                try:
                    total_weight += int(float(w) * qty)
                except (ValueError, TypeError):
                    pass

        # Price: convert decimal string to integer cents
        total_str = order.get("total")
        total_price_cents = None
        if total_str is not None:
            try:
                total_price_cents = int(round(float(total_str) * 100))
            except (ValueError, TypeError):
                pass

        item_count = sum(item.get("quantity") or 0 for item in line_items)

        # Customer name from billing
        customer_name = (
            f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
            or None
        )

        # Ship-to name from shipping (fall back to billing)
        ship_first = shipping.get("first_name", "").strip()
        ship_last = shipping.get("last_name", "").strip()
        ship_to_name = f"{ship_first} {ship_last}".strip()
        if not ship_to_name:
            ship_to_name = customer_name

        # Shipping method from shipping_lines
        shipping_lines = order.get("shipping_lines") or []
        shipping_method = shipping_lines[0].get("method_title") if shipping_lines else None
        service_code = shipping_lines[0].get("method_id") if shipping_lines else None

        # Build the flat row (core columns matching external_orders schema)
        row: dict[str, Any] = {
            "platform": "woocommerce",
            "external_id": str(order.get("id", "")),
            "credential_ref": credential_ref,
            "order_number": str(order.get("number", order.get("id", ""))),
            "order_status": order.get("status"),
            "payment_status": order.get("status"),
            "fulfillment_status": order.get("status"),
            "created_at": order.get("date_created"),
            "updated_at": order.get("date_modified"),
            "ship_to_name": ship_to_name,
            "ship_to_company": shipping.get("company") or None,
            "ship_to_address1": shipping.get("address_1"),
            "ship_to_address2": shipping.get("address_2") or None,
            "ship_to_city": shipping.get("city"),
            "ship_to_state": shipping.get("state"),
            "ship_to_postal": shipping.get("postcode"),
            "ship_to_country": shipping.get("country", "US"),
            "ship_to_phone": billing.get("phone") or None,
            "is_residential": None,  # WooCommerce doesn't provide this
            "total_weight_grams": total_weight if total_weight > 0 else None,
            "package_count": 1,
            "shipping_method": shipping_method,
            "service_code": service_code,
            "total_price_cents": total_price_cents,
            "currency": order.get("currency", "USD"),
            "customer_name": customer_name,
            "customer_email": billing.get("email"),
            "item_count": item_count if item_count > 0 else None,
            "tags": None,  # WooCommerce doesn't have a top-level tags field
            "mapping_version": self.MAPPING_VERSION,
        }

        # Compute canonical hash for change detection
        row["canonical_hash"] = compute_canonical_hash(row)

        # Preserve raw JSON for debugging/auditing
        row["raw_json"] = json.dumps(order, default=str)

        # Attrs JSON for non-core fields (customer note, coupons, etc.)
        attrs: dict[str, Any] = {}
        if order.get("customer_note"):
            attrs["customer_note"] = order["customer_note"]
        if order.get("coupon_lines"):
            attrs["coupon_lines"] = order["coupon_lines"]
        row["attrs_json"] = json.dumps(attrs, default=str) if attrs else "{}"

        return row
