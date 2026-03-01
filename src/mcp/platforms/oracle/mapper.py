# src/mcp/platforms/oracle/mapper.py
"""Oracle order mapper: raw Oracle SQL row dict -> flat DuckDB row.

Pure module -- no FastMCP, no server, no network dependencies.
Only imports: json, and platform_models.compute_canonical_hash.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.services.platform_models import compute_canonical_hash


class OracleMapper:
    """Maps raw Oracle order row dicts to flat rows for the external_orders table.

    Class name MUST be OracleMapper because PlatformActivationService does
    `platform_id.capitalize() + "Mapper"` to resolve the mapper class.
    """

    MAPPING_VERSION = "1.0"

    def to_flat_row(self, order: dict[str, Any], credential_ref: str) -> dict[str, Any]:
        """Convert a raw Oracle order row dict to a flat DuckDB row.

        Oracle orders typically have uppercase column names from the database:
        ORDER_ID, ORDER_NUMBER, ORDER_STATUS, SHIP_TO_NAME, SHIP_TO_ADDRESS1,
        SHIP_TO_CITY, SHIP_TO_STATE, SHIP_TO_POSTAL, SHIP_TO_COUNTRY,
        TOTAL_AMOUNT, CURRENCY_CODE, CUSTOMER_NAME, CUSTOMER_EMAIL,
        CREATED_DATE, UPDATED_DATE, etc.

        Args:
            order: Raw order dict from Oracle SQL query (uppercase keys).
            credential_ref: Credential profile identifier (e.g., "primary").

        Returns:
            Flat dict matching the external_orders schema.
        """
        # Price: convert decimal to integer cents
        total_amount = order.get("TOTAL_AMOUNT")
        total_price_cents = None
        if total_amount is not None:
            try:
                total_price_cents = int(round(float(total_amount) * 100))
            except (ValueError, TypeError):
                total_price_cents = None

        # Weight: Oracle may store as decimal pounds or grams
        weight = order.get("TOTAL_WEIGHT_GRAMS") or order.get("WEIGHT")
        total_weight_grams = None
        if weight is not None:
            try:
                total_weight_grams = int(round(float(weight)))
            except (ValueError, TypeError):
                total_weight_grams = None

        # Item count
        item_count = order.get("ITEM_COUNT") or order.get("LINE_COUNT")
        if item_count is not None:
            try:
                item_count = int(item_count)
            except (ValueError, TypeError):
                item_count = None

        # Fulfillment status defaults to "unfulfilled"
        fulfillment_status = order.get("FULFILLMENT_STATUS") or "unfulfilled"

        # Build the flat row (core columns matching external_orders schema)
        row: dict[str, Any] = {
            "platform": "oracle",
            "external_id": str(order.get("ORDER_ID", "")),
            "credential_ref": credential_ref,
            "order_number": str(order.get("ORDER_NUMBER") or order.get("ORDER_ID", "")),
            "order_status": order.get("ORDER_STATUS"),
            "payment_status": order.get("PAYMENT_STATUS"),
            "fulfillment_status": fulfillment_status,
            "created_at": self._format_datetime(order.get("CREATED_DATE")),
            "updated_at": self._format_datetime(order.get("UPDATED_DATE")),
            "ship_to_name": order.get("SHIP_TO_NAME"),
            "ship_to_company": order.get("SHIP_TO_COMPANY"),
            "ship_to_address1": order.get("SHIP_TO_ADDRESS1"),
            "ship_to_address2": order.get("SHIP_TO_ADDRESS2"),
            "ship_to_city": order.get("SHIP_TO_CITY"),
            "ship_to_state": order.get("SHIP_TO_STATE"),
            "ship_to_postal": order.get("SHIP_TO_POSTAL"),
            "ship_to_country": order.get("SHIP_TO_COUNTRY") or "US",
            "ship_to_phone": order.get("SHIP_TO_PHONE"),
            "is_residential": None,  # Oracle doesn't typically provide this
            "total_weight_grams": total_weight_grams,
            "package_count": 1,
            "shipping_method": order.get("SHIPPING_METHOD"),
            "service_code": order.get("SERVICE_CODE"),
            "total_price_cents": total_price_cents,
            "currency": order.get("CURRENCY_CODE") or "USD",
            "customer_name": order.get("CUSTOMER_NAME"),
            "customer_email": order.get("CUSTOMER_EMAIL"),
            "item_count": item_count,
            "tags": order.get("TAGS"),
            "mapping_version": self.MAPPING_VERSION,
        }

        # Compute canonical hash for change detection
        row["canonical_hash"] = compute_canonical_hash(row)

        # Preserve raw JSON for debugging/auditing
        row["raw_json"] = json.dumps(order, default=str)

        # Attrs JSON for non-core fields (notes, priority, warehouse, etc.)
        attrs: dict[str, Any] = {}
        if order.get("NOTES"):
            attrs["notes"] = order["NOTES"]
        if order.get("PRIORITY"):
            attrs["priority"] = order["PRIORITY"]
        if order.get("WAREHOUSE_ID"):
            attrs["warehouse_id"] = order["WAREHOUSE_ID"]
        if order.get("SHIP_METHOD_CODE"):
            attrs["ship_method_code"] = order["SHIP_METHOD_CODE"]
        if order.get("DEPARTMENT"):
            attrs["department"] = order["DEPARTMENT"]
        row["attrs_json"] = json.dumps(attrs, default=str) if attrs else "{}"

        return row

    @staticmethod
    def _format_datetime(value: Any) -> str | None:
        """Format a datetime value to ISO format string.

        Args:
            value: Datetime value (may be None, datetime, or string).

        Returns:
            ISO format datetime string, or None if value is None.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)
