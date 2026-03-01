# src/mcp/platforms/amazon/mapper.py
"""Amazon order mapper: raw SP-API order -> flat DuckDB row.

Pure module — no FastMCP, no server, no network dependencies.
Only imports: json, typing, and platform_models.compute_canonical_hash.
"""
from __future__ import annotations

import json
from typing import Any

from src.services.platform_models import compute_canonical_hash


class AmazonMapper:
    """Maps raw Amazon SP-API order dicts to flat rows for the external_orders table."""

    MAPPING_VERSION = "1.0"

    def to_flat_row(self, order: dict[str, Any], credential_ref: str) -> dict[str, Any]:
        """Convert a raw Amazon SP-API order dict to a flat DuckDB row.

        Args:
            order: Raw order dict from Amazon SP-API.
            credential_ref: Credential profile identifier (e.g., "primary").

        Returns:
            Flat dict matching the external_orders schema.
        """
        shipping = order.get("ShippingAddress") or {}
        buyer_info = order.get("BuyerInfo") or {}
        order_total = order.get("OrderTotal") or {}

        # Fulfillment channel: AFN = Amazon Fulfilled, MFN = Merchant Fulfilled
        fulfillment_channel = order.get("FulfillmentChannel", "")
        if fulfillment_channel == "AFN":
            fulfillment_status = "amazon_fulfilled"
        else:
            fulfillment_status = "unfulfilled"

        # Price: convert decimal string to integer cents
        total_amount_str = order_total.get("Amount")
        total_price_cents = None
        if total_amount_str is not None:
            total_price_cents = int(round(float(total_amount_str) * 100))

        # Item count: shipped + unshipped
        items_shipped = order.get("NumberOfItemsShipped") or 0
        items_unshipped = order.get("NumberOfItemsUnshipped") or 0
        item_count = items_shipped + items_unshipped

        # Build the flat row (core columns matching external_orders schema)
        row: dict[str, Any] = {
            "platform": "amazon",
            "external_id": str(order.get("AmazonOrderId", "")),
            "credential_ref": credential_ref,
            "order_number": str(order.get("AmazonOrderId", "")),
            "order_status": order.get("OrderStatus"),
            "payment_status": order.get("PaymentMethod"),
            "fulfillment_status": fulfillment_status,
            "created_at": order.get("PurchaseDate"),
            "updated_at": order.get("LastUpdateDate"),
            "ship_to_name": shipping.get("Name"),
            "ship_to_company": None,  # Amazon doesn't provide company
            "ship_to_address1": shipping.get("AddressLine1"),
            "ship_to_address2": shipping.get("AddressLine2"),
            "ship_to_city": shipping.get("City"),
            "ship_to_state": shipping.get("StateOrRegion"),
            "ship_to_postal": shipping.get("PostalCode"),
            "ship_to_country": shipping.get("CountryCode", "US"),
            "ship_to_phone": shipping.get("Phone"),
            "is_residential": None,  # Amazon doesn't provide this
            "total_weight_grams": None,  # Not in order-level response
            "package_count": 1,
            "shipping_method": order.get("ShipmentServiceLevelCategory"),
            "service_code": None,  # Amazon doesn't expose a service code
            "total_price_cents": total_price_cents,
            "currency": order_total.get("CurrencyCode", "USD"),
            "customer_name": buyer_info.get("BuyerName"),
            "customer_email": buyer_info.get("BuyerEmail"),
            "item_count": item_count if item_count > 0 else None,
            "tags": None,  # Amazon doesn't have order tags
            "mapping_version": self.MAPPING_VERSION,
        }

        # Compute canonical hash for change detection
        row["canonical_hash"] = compute_canonical_hash(row)

        # Preserve raw JSON for debugging/auditing
        row["raw_json"] = json.dumps(order, default=str)

        # Attrs JSON for non-core fields
        attrs: dict[str, Any] = {}
        if order.get("EarliestShipDate"):
            attrs["earliest_ship_date"] = order["EarliestShipDate"]
        if order.get("LatestShipDate"):
            attrs["latest_ship_date"] = order["LatestShipDate"]
        if order.get("IsBusinessOrder") is not None:
            attrs["is_business_order"] = order["IsBusinessOrder"]
        if order.get("IsPrime") is not None:
            attrs["is_prime"] = order["IsPrime"]
        if order.get("MarketplaceId"):
            attrs["marketplace_id"] = order["MarketplaceId"]
        row["attrs_json"] = json.dumps(attrs, default=str) if attrs else "{}"

        return row
