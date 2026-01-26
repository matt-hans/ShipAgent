"""WooCommerce platform client.

Implements PlatformClient interface for WooCommerce REST API v3.
Supports order fetching, single order retrieval, and tracking updates.

Authentication uses WooCommerce consumer key/secret via HTTP Basic Auth.
Tracking updates require the "WooCommerce Shipment Tracking" plugin or
fall back to order meta_data.

API Reference: https://woocommerce.github.io/woocommerce-rest-api-docs/
"""

import logging
from typing import Any

import httpx

from src.mcp.external_sources.clients.base import PlatformClient
from src.mcp.external_sources.models import (
    ExternalOrder,
    OrderFilters,
    TrackingUpdate,
)

logger = logging.getLogger(__name__)


class WooCommerceAuthError(Exception):
    """Raised when WooCommerce authentication fails."""

    pass


class WooCommerceAPIError(Exception):
    """Raised when WooCommerce API returns an error."""

    pass


class WooCommerceClient(PlatformClient):
    """WooCommerce platform client using REST API v3.

    Implements order fetching and tracking updates for WooCommerce stores.

    Example usage:
        client = WooCommerceClient()
        await client.authenticate({
            "site_url": "https://mystore.com",
            "consumer_key": "ck_...",
            "consumer_secret": "cs_...",
        })
        orders = await client.fetch_orders(OrderFilters(status="processing"))
    """

    # WooCommerce REST API v3 base path
    API_VERSION = "wc/v3"

    def __init__(self) -> None:
        """Initialize WooCommerce client in unauthenticated state."""
        self._site_url: str | None = None
        self._consumer_key: str | None = None
        self._consumer_secret: str | None = None
        self._authenticated: bool = False

    @property
    def platform_name(self) -> str:
        """Return the platform identifier.

        Returns:
            'woocommerce'
        """
        return "woocommerce"

    async def authenticate(self, credentials: dict) -> bool:
        """Authenticate with WooCommerce using consumer key/secret.

        Args:
            credentials: Dictionary containing:
                - site_url: WooCommerce store URL
                - consumer_key: WooCommerce REST API consumer key
                - consumer_secret: WooCommerce REST API consumer secret

        Returns:
            True if authentication successful

        Raises:
            WooCommerceAuthError: If credentials missing or invalid
        """
        # Validate required credentials
        if "site_url" not in credentials:
            raise WooCommerceAuthError("Missing required credential: site_url")
        if "consumer_key" not in credentials:
            raise WooCommerceAuthError("Missing required credential: consumer_key")
        if "consumer_secret" not in credentials:
            raise WooCommerceAuthError("Missing required credential: consumer_secret")

        # Normalize site URL (remove trailing slash)
        site_url = credentials["site_url"].rstrip("/")
        consumer_key = credentials["consumer_key"]
        consumer_secret = credentials["consumer_secret"]

        # Store credentials temporarily to test connection
        self._site_url = site_url
        self._consumer_key = consumer_key
        self._consumer_secret = consumer_secret

        # Verify credentials by calling system status endpoint
        try:
            await self._make_request(
                method="GET",
                endpoint="system_status",
            )
            self._authenticated = True
            logger.info(f"WooCommerce authenticated: {site_url}")
            return True

        except WooCommerceAPIError as e:
            # Reset credentials on failure
            self._site_url = None
            self._consumer_key = None
            self._consumer_secret = None
            self._authenticated = False
            raise WooCommerceAuthError(f"Failed to authenticate with WooCommerce: {e}")

    async def test_connection(self) -> bool:
        """Test that the connection to WooCommerce is valid.

        Returns:
            True if connection is healthy, False otherwise
        """
        if not self._authenticated:
            return False

        try:
            await self._make_request(
                method="GET",
                endpoint="system_status",
            )
            return True
        except WooCommerceAPIError:
            return False

    async def fetch_orders(self, filters: OrderFilters) -> list[ExternalOrder]:
        """Fetch orders from WooCommerce with optional filters.

        Args:
            filters: Order filtering criteria including:
                - status: Order status (processing, completed, etc.)
                - date_from: Start date (ISO format)
                - date_to: End date (ISO format)
                - limit: Max orders to fetch (per_page)
                - offset: Pagination offset

        Returns:
            List of orders in normalized ExternalOrder format

        Raises:
            WooCommerceAuthError: If not authenticated
        """
        self._require_auth()

        # Build query parameters
        params: dict[str, Any] = {}

        if filters.status:
            params["status"] = filters.status

        if filters.date_from:
            params["after"] = filters.date_from

        if filters.date_to:
            params["before"] = filters.date_to

        params["per_page"] = filters.limit
        params["offset"] = filters.offset

        # Fetch orders from API
        response = await self._make_request(
            method="GET",
            endpoint="orders",
            params=params,
        )

        # Normalize each order
        orders = []
        for order_data in response:
            normalized = self._normalize_order(order_data)
            orders.append(normalized)

        logger.info(f"Fetched {len(orders)} orders from WooCommerce")
        return orders

    async def get_order(self, order_id: str) -> ExternalOrder | None:
        """Get a single order by ID.

        Args:
            order_id: WooCommerce order ID

        Returns:
            ExternalOrder if found, None if not found

        Raises:
            WooCommerceAuthError: If not authenticated
        """
        self._require_auth()

        try:
            response = await self._make_request(
                method="GET",
                endpoint=f"orders/{order_id}",
            )
            return self._normalize_order(response)
        except WooCommerceAPIError as e:
            if "404" in str(e):
                return None
            raise

    async def update_tracking(self, update: TrackingUpdate) -> bool:
        """Write tracking information back to WooCommerce.

        Updates order meta_data with tracking information. This is compatible
        with the WooCommerce Shipment Tracking plugin which uses these meta keys:
        - _tracking_number
        - _tracking_provider
        - _tracking_link

        Args:
            update: Tracking information including order_id, tracking_number,
                    carrier, and optional tracking_url

        Returns:
            True if update successful, False otherwise

        Raises:
            WooCommerceAuthError: If not authenticated
        """
        self._require_auth()

        # Build meta_data for tracking (compatible with Shipment Tracking plugin)
        meta_data = [
            {"key": "_tracking_number", "value": update.tracking_number},
            {"key": "_tracking_provider", "value": update.carrier},
        ]

        if update.tracking_url:
            meta_data.append({"key": "_tracking_link", "value": update.tracking_url})

        # Update order with tracking meta_data
        try:
            await self._make_request(
                method="PUT",
                endpoint=f"orders/{update.order_id}",
                json={"meta_data": meta_data},
            )
            logger.info(
                f"Updated tracking for WooCommerce order {update.order_id}: "
                f"{update.carrier} {update.tracking_number}"
            )
            return True

        except WooCommerceAPIError as e:
            logger.error(f"Failed to update tracking for order {update.order_id}: {e}")
            return False

    def _require_auth(self) -> None:
        """Verify client is authenticated.

        Raises:
            WooCommerceAuthError: If not authenticated
        """
        if not self._authenticated:
            raise WooCommerceAuthError("Not authenticated. Call authenticate() first.")

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Make authenticated request to WooCommerce REST API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (e.g., 'orders', 'orders/123')
            params: Query parameters
            json: JSON body data

        Returns:
            Parsed JSON response

        Raises:
            WooCommerceAPIError: If API returns error
        """
        url = f"{self._site_url}/wp-json/{self.API_VERSION}/{endpoint}"

        async with httpx.AsyncClient(
            auth=(self._consumer_key, self._consumer_secret),
            timeout=30.0,
        ) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json,
                )
                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                raise WooCommerceAPIError(
                    f"{e.response.status_code} {e.response.reason_phrase}"
                )
            except httpx.RequestError as e:
                raise WooCommerceAPIError(f"Request failed: {e}")

    def _normalize_order(self, order_data: dict[str, Any]) -> ExternalOrder:
        """Convert WooCommerce order to normalized ExternalOrder.

        Args:
            order_data: Raw WooCommerce order data

        Returns:
            Normalized ExternalOrder instance
        """
        billing = order_data.get("billing", {})
        shipping = order_data.get("shipping", {})

        # Determine recipient name (prefer shipping, fall back to billing)
        ship_first = shipping.get("first_name", "").strip()
        ship_last = shipping.get("last_name", "").strip()

        if ship_first or ship_last:
            ship_to_name = f"{ship_first} {ship_last}".strip()
        else:
            # Fall back to billing name
            bill_first = billing.get("first_name", "").strip()
            bill_last = billing.get("last_name", "").strip()
            ship_to_name = f"{bill_first} {bill_last}".strip()

        # Customer name from billing
        customer_name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()

        # Normalize line items
        items = []
        for item in order_data.get("line_items", []):
            items.append({
                "id": str(item.get("id", "")),
                "name": item.get("name", ""),
                "quantity": item.get("quantity", 1),
                "total": item.get("total", "0"),
                "sku": item.get("sku", ""),
            })

        return ExternalOrder(
            platform=self.platform_name,
            order_id=str(order_data["id"]),
            order_number=str(order_data.get("number", order_data["id"])),
            status=order_data.get("status", "unknown"),
            created_at=order_data.get("date_created", ""),
            customer_name=customer_name,
            customer_email=billing.get("email"),
            ship_to_name=ship_to_name,
            ship_to_company=shipping.get("company") or None,
            ship_to_address1=shipping.get("address_1", ""),
            ship_to_address2=shipping.get("address_2") or None,
            ship_to_city=shipping.get("city", ""),
            ship_to_state=shipping.get("state", ""),
            ship_to_postal_code=shipping.get("postcode", ""),
            ship_to_country=shipping.get("country", "US"),
            ship_to_phone=billing.get("phone") or None,
            items=items,
            raw_data=order_data,
        )
