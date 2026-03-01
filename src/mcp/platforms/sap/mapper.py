# src/mcp/platforms/sap/mapper.py
"""SAP order mapper: raw SAP OData order -> flat DuckDB row.

Pure module -- no FastMCP, no server, no network dependencies.
Only imports: json, re, datetime, and platform_models.compute_canonical_hash.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from src.services.platform_models import compute_canonical_hash


class SapMapper:
    """Maps raw SAP OData order dicts to flat rows for the external_orders table.

    Class name is SapMapper (not SAPMapper) because PlatformActivationService
    constructs the mapper class name as ``platform_id.capitalize() + "Mapper"``
    which yields "SapMapper".
    """

    MAPPING_VERSION = "1.0"

    def to_flat_row(self, order: dict[str, Any], credential_ref: str) -> dict[str, Any]:
        """Convert a raw SAP OData order dict to a flat DuckDB row.

        Args:
            order: Raw order dict from SAP OData SalesOrderSet.
            credential_ref: Credential profile identifier (e.g., "primary").

        Returns:
            Flat dict matching the external_orders schema.
        """
        # Extract nested items from SAP to_Item navigation property
        to_item = order.get("to_Item", {})
        items: list[dict[str, Any]] = []
        if isinstance(to_item, dict):
            items = to_item.get("results", [])
        elif isinstance(to_item, list):
            items = to_item

        # Weight: sum of NetWeight across all items (SAP stores in KG, convert to grams)
        total_weight_grams = 0
        for item in items:
            net_weight = item.get("NetWeight") or item.get("net_weight") or 0
            try:
                weight_kg = float(net_weight)
                quantity = int(item.get("OrderQuantity", 0) or item.get("order_quantity", 0) or 0)
                total_weight_grams += int(weight_kg * 1000) * max(quantity, 1)
            except (ValueError, TypeError):
                pass

        # Price: NetAmount is typically in the order currency, convert to cents
        total_price_cents: int | None = None
        net_amount = order.get("NetAmount") or order.get("TotalNetAmount")
        if net_amount is not None:
            try:
                total_price_cents = int(round(float(net_amount) * 100))
            except (ValueError, TypeError):
                pass

        # Item count: sum of OrderQuantity across all items
        item_count = 0
        for item in items:
            try:
                qty = int(item.get("OrderQuantity", 0) or item.get("order_quantity", 0) or 0)
                item_count += qty
            except (ValueError, TypeError):
                pass

        # Parse SAP dates
        created_at = self._parse_sap_date(order.get("CreationDate", ""))
        updated_at = self._parse_sap_date(
            order.get("LastChangeDate", "") or order.get("CreationDate", "")
        )

        # Fulfillment status from OverallDeliveryStatus
        delivery_status = order.get("OverallDeliveryStatus", "")
        fulfillment_status = self._map_delivery_status(delivery_status)

        # Customer name: SoldToParty name or CustomerName
        customer_name = (
            order.get("CustomerName")
            or order.get("SoldToPartyName")
            or order.get("SoldToParty")
        )

        # Build the flat row (core columns matching external_orders schema)
        row: dict[str, Any] = {
            "platform": "sap",
            "external_id": str(order.get("SalesOrder", "")),
            "credential_ref": credential_ref,
            "order_number": str(order.get("SalesOrder", "")),
            "order_status": order.get("OverallSDProcessStatus"),
            "payment_status": order.get("OverallBillingStatus"),
            "fulfillment_status": fulfillment_status,
            "created_at": created_at or None,
            "updated_at": updated_at or None,
            "ship_to_name": order.get("ShipToName") or order.get("ShipToParty"),
            "ship_to_company": order.get("ShipToCompany"),
            "ship_to_address1": order.get("ShipToStreet"),
            "ship_to_address2": order.get("ShipToStreet2"),
            "ship_to_city": order.get("ShipToCity"),
            "ship_to_state": order.get("ShipToRegion"),
            "ship_to_postal": order.get("ShipToPostalCode"),
            "ship_to_country": order.get("ShipToCountry", "US"),
            "ship_to_phone": order.get("ShipToPhone"),
            "is_residential": None,  # SAP doesn't provide this
            "total_weight_grams": total_weight_grams if total_weight_grams > 0 else None,
            "package_count": 1,
            "shipping_method": order.get("ShippingCondition"),
            "service_code": order.get("ShippingType"),
            "total_price_cents": total_price_cents,
            "currency": order.get("TransactionCurrency", "USD"),
            "customer_name": customer_name,
            "customer_email": order.get("CustomerEmail"),
            "item_count": item_count if item_count > 0 else None,
            "tags": order.get("SalesOrderType"),
            "mapping_version": self.MAPPING_VERSION,
        }

        # Compute canonical hash for change detection
        row["canonical_hash"] = compute_canonical_hash(row)

        # Preserve raw JSON for debugging/auditing
        row["raw_json"] = json.dumps(order, default=str)

        # Attrs JSON for non-core fields
        attrs: dict[str, Any] = {}
        if order.get("SalesOrderType"):
            attrs["sales_order_type"] = order["SalesOrderType"]
        if order.get("SalesOrganization"):
            attrs["sales_organization"] = order["SalesOrganization"]
        if order.get("DistributionChannel"):
            attrs["distribution_channel"] = order["DistributionChannel"]
        if order.get("Division"):
            attrs["division"] = order["Division"]
        if order.get("IncotermsClassification"):
            attrs["incoterms"] = order["IncotermsClassification"]
        if order.get("PurchaseOrderByCustomer"):
            attrs["customer_po"] = order["PurchaseOrderByCustomer"]
        row["attrs_json"] = json.dumps(attrs, default=str) if attrs else "{}"

        return row

    @staticmethod
    def _parse_sap_date(sap_date: str) -> str:
        """Parse SAP OData date format to ISO format.

        SAP returns dates as /Date(milliseconds)/ format.

        Args:
            sap_date: Date string in SAP format.

        Returns:
            ISO 8601 formatted date string, or empty string on failure.
        """
        if not sap_date:
            return ""

        # Match /Date(milliseconds)/ pattern
        match = re.match(r"/Date\((\d+)\)/", sap_date)
        if not match:
            # Already ISO or other format -- return as-is
            return sap_date

        try:
            milliseconds = int(match.group(1))
            dt = datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
            return dt.isoformat()
        except (ValueError, OSError):
            return ""

    @staticmethod
    def _map_delivery_status(status: str) -> str:
        """Map SAP OverallDeliveryStatus to normalized fulfillment status.

        Args:
            status: SAP delivery status code.

        Returns:
            Normalized fulfillment status string.
        """
        status_map = {
            "": "unfulfilled",
            "A": "unfulfilled",      # Not yet processed
            "B": "partial",          # Partially delivered
            "C": "fulfilled",        # Fully delivered
        }
        return status_map.get(status, "unfulfilled")
