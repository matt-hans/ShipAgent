# src/mcp/platforms/dummy/mapper.py
"""Pure mapper for DummyPlatform orders -> flat DuckDB rows.

No FastMCP or server imports allowed (see mapper purity tests).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from src.services.platform_models import compute_canonical_hash


class DummyMapper:
    """Maps dummy order dicts to flat external_orders rows."""

    MAPPING_VERSION = "1.0"

    def to_flat_row(self, order: dict, credential_ref: str) -> dict:
        """Convert a dummy platform order to a flat DuckDB row."""
        addr = order.get("shipping_address") or {}

        total_weight_grams = sum(
            item.get("grams", 0) * item.get("quantity", 1)
            for item in order.get("line_items", [])
        )
        total_price_cents = int(round(float(order.get("total_price", "0")) * 100))
        item_count = sum(
            item.get("quantity", 1) for item in order.get("line_items", [])
        )

        row = {
            "platform": "dummy",
            "external_id": str(order["id"]),
            "credential_ref": credential_ref,
            "order_number": str(order.get("order_number", "")),
            "order_status": order.get("status", "open"),
            "payment_status": order.get("payment_status", "paid"),
            "fulfillment_status": order.get("fulfillment_status") or "unfulfilled",
            "created_at": order.get("created_at"),
            "updated_at": order.get("updated_at"),
            "ship_to_name": addr.get("name"),
            "ship_to_company": addr.get("company"),
            "ship_to_address1": addr.get("address1"),
            "ship_to_address2": addr.get("address2"),
            "ship_to_city": addr.get("city"),
            "ship_to_state": addr.get("state"),
            "ship_to_postal": addr.get("zip"),
            "ship_to_country": addr.get("country_code", "US"),
            "ship_to_phone": addr.get("phone"),
            "is_residential": True,
            "total_weight_grams": total_weight_grams,
            "package_count": 1,
            "shipping_method": None,
            "service_code": None,
            "total_price_cents": total_price_cents,
            "currency": order.get("currency", "USD"),
            "customer_name": order.get("customer_name"),
            "customer_email": order.get("customer_email"),
            "item_count": item_count,
            "tags": order.get("tags"),
            "mapping_version": self.MAPPING_VERSION,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "sync_run_id": None,
            "attrs_json": json.dumps({"source": "dummy"}),
            "raw_json": json.dumps(order),
        }

        row["canonical_hash"] = compute_canonical_hash(row)
        return row
