"""Amazon SP-API client implementation.

Implements the PlatformClient interface for Amazon Selling Partner API.
Supports OAuth token refresh, order retrieval, and normalized order mapping.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from src.mcp.external_sources.clients.base import PlatformClient
from src.mcp.external_sources.models import ExternalOrder, OrderFilters, TrackingUpdate


class AmazonClient(PlatformClient):
    """Amazon Selling Partner API client for order access."""

    LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
    DEFAULT_MARKETPLACE_ID = "ATVPDKIKX0DER"

    BASE_URLS = {
        "na": "https://sellingpartnerapi-na.amazon.com",
        "eu": "https://sellingpartnerapi-eu.amazon.com",
        "fe": "https://sellingpartnerapi-fe.amazon.com",
    }
    SANDBOX_BASE_URLS = {
        "na": "https://sandbox.sellingpartnerapi-na.amazon.com",
        "eu": "https://sandbox.sellingpartnerapi-eu.amazon.com",
        "fe": "https://sandbox.sellingpartnerapi-fe.amazon.com",
    }

    def __init__(self) -> None:
        self._client_id: str | None = None
        self._client_secret: str | None = None
        self._refresh_token: str | None = None
        self._marketplace_id: str = self.DEFAULT_MARKETPLACE_ID
        self._sandbox: bool = False
        self._authenticated: bool = False

        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    @property
    def platform_name(self) -> str:
        return "amazon"

    @staticmethod
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def _region_for_marketplace(marketplace_id: str) -> str:
        na_marketplaces = {"ATVPDKIKX0DER", "A2EUQ1WTGCTBG2", "A1AM78C64UM0Y8", "A2Q3Y263D00KMC"}
        fe_marketplaces = {"A1VC38T7YXB528", "A39IBJ37TRP1C6", "A19VAU5U5O7RUS", "A21TJRUUN4KGV"}
        if marketplace_id in na_marketplaces:
            return "na"
        if marketplace_id in fe_marketplaces:
            return "fe"
        return "eu"

    def _base_url(self) -> str:
        region = self._region_for_marketplace(self._marketplace_id)
        urls = self.SANDBOX_BASE_URLS if self._sandbox else self.BASE_URLS
        return urls.get(region, urls["na"])

    async def _refresh_access_token(self) -> bool:
        if not self._client_id or not self._client_secret or not self._refresh_token:
            return False

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    self.LWA_TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self._refresh_token,
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                )
            if response.status_code != 200:
                return False

            payload = response.json()
            token = payload.get("access_token")
            if not token:
                return False

            expires_in = int(payload.get("expires_in") or 3600)
            self._access_token = token
            self._token_expires_at = time.time() + expires_in
            return True
        except Exception:
            return False

    async def _get_access_token(self) -> str | None:
        if self._access_token and time.time() < (self._token_expires_at - 120):
            return self._access_token
        ok = await self._refresh_access_token()
        return self._access_token if ok else None

    async def _fetch_order_items(self, order_id: str) -> list[dict[str, Any]]:
        """Fetch order items from SP-API getOrderItems endpoint.

        Args:
            order_id: Amazon order ID.

        Returns:
            List of raw order item dicts from SP-API. Empty on failure.
        """
        if not self._authenticated:
            return []

        token = await self._get_access_token()
        if not token:
            return []

        headers = {
            "x-amz-access-token": token,
            "content-type": "application/json",
        }

        all_items: list[dict[str, Any]] = []
        next_token: str | None = None

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                while True:
                    params: dict[str, str] = {}
                    if next_token:
                        params["NextToken"] = next_token

                    response = await client.get(
                        f"{self._base_url()}/orders/v0/orders/{order_id}/orderItems",
                        headers=headers,
                        params=params,
                    )

                    if response.status_code != 200:
                        break

                    payload = response.json().get("payload", {})
                    items = payload.get("OrderItems", [])
                    all_items.extend(items)

                    next_token = payload.get("NextToken")
                    if not next_token:
                        break
        except Exception:
            return []

        return all_items

    async def authenticate(self, credentials: dict) -> bool:
        self._client_id = str(credentials.get("client_id", "")).strip() or None
        self._client_secret = str(credentials.get("client_secret", "")).strip() or None
        self._refresh_token = str(credentials.get("refresh_token", "")).strip() or None

        marketplace = str(credentials.get("marketplace_id", "")).strip()
        self._marketplace_id = marketplace or self.DEFAULT_MARKETPLACE_ID
        self._sandbox = self._to_bool(credentials.get("sandbox", False))

        if not self._client_id or not self._client_secret or not self._refresh_token:
            self._authenticated = False
            return False

        self._authenticated = await self.test_connection()
        return self._authenticated

    async def test_connection(self) -> bool:
        token = await self._get_access_token()
        if not token:
            return False

        headers = {
            "x-amz-access-token": token,
            "content-type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                if self._sandbox:
                    response = await client.get(
                        f"{self._base_url()}/orders/v0/orders",
                        headers=headers,
                        params={
                            "MarketplaceIds": self._marketplace_id,
                            "CreatedAfter": "TEST_CASE_200",
                            "MaxResultsPerPage": 1,
                        },
                    )
                else:
                    response = await client.get(
                        f"{self._base_url()}/sellers/v1/marketplaceParticipations",
                        headers=headers,
                    )
            return response.status_code == 200
        except Exception:
            return False

    async def fetch_orders(self, filters: OrderFilters) -> list[ExternalOrder]:
        if not self._authenticated:
            return []

        token = await self._get_access_token()
        if not token:
            return []

        headers = {
            "x-amz-access-token": token,
            "content-type": "application/json",
        }

        normalized_orders: list[ExternalOrder] = []
        next_token: str | None = None
        max_results = max(1, min(int(filters.limit or 100), 250))

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                while len(normalized_orders) < max_results:
                    params: dict[str, Any]
                    if next_token:
                        params = {"NextToken": next_token}
                    else:
                        params = {
                            "MarketplaceIds": self._marketplace_id,
                            "MaxResultsPerPage": min(100, max_results),
                        }
                        if filters.date_from:
                            params["CreatedAfter"] = filters.date_from
                        elif self._sandbox:
                            params["CreatedAfter"] = "TEST_CASE_200"

                    response = await client.get(
                        f"{self._base_url()}/orders/v0/orders",
                        headers=headers,
                        params=params,
                    )

                    if response.status_code != 200:
                        break

                    payload = response.json().get("payload", {})
                    orders = payload.get("Orders", [])
                    if not orders:
                        break

                    for order in orders:
                        if filters.status and str(order.get("OrderStatus", "")).lower() != str(filters.status).lower():
                            continue
                        order_id = str(order.get("AmazonOrderId", ""))
                        items = await self._fetch_order_items(order_id)
                        normalized_orders.append(self._normalize_order(order, items))
                        if len(normalized_orders) >= max_results:
                            break
                        # Rate limit: 1 req/sec for getOrderItems
                        await asyncio.sleep(1.0)

                    next_token = payload.get("NextToken")
                    if not next_token:
                        break
        except Exception:
            return []

        if filters.offset:
            return normalized_orders[filters.offset:filters.offset + filters.limit]
        return normalized_orders[:filters.limit]

    async def get_order(self, order_id: str) -> ExternalOrder | None:
        if not self._authenticated:
            return None

        token = await self._get_access_token()
        if not token:
            return None

        headers = {
            "x-amz-access-token": token,
            "content-type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(
                    f"{self._base_url()}/orders/v0/orders/{order_id}",
                    headers=headers,
                )
            if response.status_code != 200:
                return None
            payload = response.json().get("payload")
            if not isinstance(payload, dict):
                return None
            order_id = str(payload.get("AmazonOrderId", ""))
            items = await self._fetch_order_items(order_id)
            return self._normalize_order(payload, items)
        except Exception:
            return None

    async def update_tracking(self, update: TrackingUpdate) -> bool:
        """Tracking write-back is not yet implemented in compatibility mode."""
        return False

    # Weight unit conversion factors to grams
    _WEIGHT_TO_GRAMS: dict[str, float] = {
        "grams": 1.0,
        "g": 1.0,
        "kilograms": 1000.0,
        "kg": 1000.0,
        "ounces": 28.3495,
        "oz": 28.3495,
        "pounds": 453.592,
        "lb": 453.592,
        "lbs": 453.592,
    }

    def _normalize_order(
        self, order: dict[str, Any], items: list[dict[str, Any]] | None = None
    ) -> ExternalOrder:
        """Normalize an Amazon order into ExternalOrder format.

        Args:
            order: Raw order dict from SP-API.
            items: Optional list of order item dicts for enrichment.

        Returns:
            Normalized ExternalOrder.
        """
        shipping = order.get("ShippingAddress") or {}
        buyer = order.get("BuyerInfo") or {}
        order_total = order.get("OrderTotal") or {}

        fulfillment_channel = str(order.get("FulfillmentChannel") or "")
        fulfillment_status = "fulfilled" if fulfillment_channel == "AFN" else "unfulfilled"

        status = str(order.get("OrderStatus") or fulfillment_status)
        created_at = str(order.get("PurchaseDate") or "")

        # Normalize line items when available
        normalized_items: list[dict[str, Any]] = []
        total_weight_grams: float | None = None
        item_count: int | None = None

        if items:
            weight_sum = 0.0
            has_weight = False
            qty_sum = 0

            for item in items:
                qty = int(item.get("QuantityOrdered") or 1)
                qty_sum += qty
                price_info = item.get("ItemPrice") or {}

                normalized_items.append({
                    "id": str(item.get("OrderItemId", "")),
                    "title": item.get("Title", ""),
                    "quantity": qty,
                    "price": str(price_info.get("Amount", "0.00")),
                    "sku": item.get("SellerSKU", ""),
                    "asin": item.get("ASIN", ""),
                })

                # Weight conversion
                weight_info = item.get("ItemWeight") or {}
                weight_val = weight_info.get("Value")
                weight_unit = str(weight_info.get("Unit", "")).lower().strip()
                if weight_val is not None and weight_unit:
                    try:
                        factor = self._WEIGHT_TO_GRAMS.get(weight_unit, 1.0)
                        weight_sum += float(weight_val) * factor * qty
                        has_weight = True
                    except (ValueError, TypeError):
                        pass

            item_count = qty_sum if qty_sum > 0 else None
            total_weight_grams = weight_sum if has_weight else None
        else:
            # Fallback: approximate item count from order-level fields
            shipped = order.get("NumberOfItemsShipped") or 0
            unshipped = order.get("NumberOfItemsUnshipped") or 0
            item_count = (shipped + unshipped) or None

        return ExternalOrder(
            platform="amazon",
            order_id=str(order.get("AmazonOrderId") or ""),
            order_number=str(order.get("AmazonOrderId") or ""),
            status=status,
            created_at=created_at,
            customer_name=str(
                buyer.get("BuyerName")
                or shipping.get("Name")
                or "Amazon Customer"
            ),
            customer_email=buyer.get("BuyerEmail"),
            ship_to_name=str(shipping.get("Name") or "Amazon Customer"),
            ship_to_company=None,
            ship_to_address1=str(shipping.get("AddressLine1") or ""),
            ship_to_address2=shipping.get("AddressLine2"),
            ship_to_city=str(shipping.get("City") or ""),
            ship_to_state=str(shipping.get("StateOrRegion") or ""),
            ship_to_postal_code=str(shipping.get("PostalCode") or ""),
            ship_to_country=str(shipping.get("CountryCode") or "US"),
            ship_to_phone=shipping.get("Phone"),
            total_price=str(order_total.get("Amount")) if order_total.get("Amount") is not None else None,
            financial_status=order.get("PaymentMethod"),
            fulfillment_status=fulfillment_status,
            tags=None,
            total_weight_grams=total_weight_grams,
            shipping_method=order.get("ShipmentServiceLevelCategory"),
            item_count=item_count,
            customer_tags=None,
            customer_order_count=None,
            customer_total_spent=None,
            order_note=None,
            risk_level=None,
            shipping_rate_code=None,
            line_item_types=None,
            discount_codes=None,
            custom_attributes={
                "marketplace_id": order.get("MarketplaceId"),
                "is_prime": order.get("IsPrime"),
                "is_business_order": order.get("IsBusinessOrder"),
                "earliest_ship_date": order.get("EarliestShipDate"),
                "latest_ship_date": order.get("LatestShipDate"),
            },
            items=normalized_items,
            raw_data=order,
        )
