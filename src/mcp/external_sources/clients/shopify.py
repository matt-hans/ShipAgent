"""Shopify platform client implementation.

Implements the PlatformClient interface for Shopify Admin API (2024-01 version).
Handles authentication, order fetching, and tracking updates via fulfillments.
"""

import httpx

from src.mcp.external_sources.clients.base import PlatformClient
from src.mcp.external_sources.models import (
    ExternalOrder,
    OrderFilters,
    TrackingUpdate,
)


class ShopifyClient(PlatformClient):
    """Shopify Admin API client for order management.

    Connects to Shopify stores via the Admin API to:
    - Fetch orders with filtering by status, date range
    - Retrieve individual orders by ID
    - Create fulfillments with tracking information

    Example:
        client = ShopifyClient()
        await client.authenticate({
            "store_url": "mystore.myshopify.com",
            "access_token": "shpat_xxxx"
        })
        orders = await client.fetch_orders(OrderFilters(status="unfulfilled"))
    """

    # Shopify Admin API version
    API_VERSION = "2024-01"

    def __init__(self) -> None:
        """Initialize ShopifyClient with empty credentials."""
        self._store_url: str | None = None
        self._access_token: str | None = None
        self._authenticated: bool = False

    @property
    def platform_name(self) -> str:
        """Return the platform identifier.

        Returns:
            'shopify' as the platform name
        """
        return "shopify"

    def _get_base_url(self) -> str:
        """Construct the Shopify Admin API base URL.

        Returns:
            Full base URL for API requests
        """
        return f"https://{self._store_url}/admin/api/{self.API_VERSION}"

    def _get_headers(self) -> dict[str, str]:
        """Construct HTTP headers for API requests.

        Returns:
            Headers dict with access token and content type
        """
        return {
            "X-Shopify-Access-Token": self._access_token or "",
            "Content-Type": "application/json",
        }

    async def authenticate(self, credentials: dict) -> bool:
        """Authenticate with Shopify Admin API.

        Args:
            credentials: Must contain:
                - store_url: Shopify store URL (e.g., 'mystore.myshopify.com')
                - access_token: Admin API access token (starts with 'shpat_')

        Returns:
            True if authentication successful, False otherwise
        """
        store_url = credentials.get("store_url")
        access_token = credentials.get("access_token")

        if not store_url or not access_token:
            return False

        # Normalize store URL (strip https:// and trailing slashes)
        store_url = store_url.replace("https://", "").replace("http://", "")
        store_url = store_url.rstrip("/")

        self._store_url = store_url
        self._access_token = access_token

        # Verify credentials by calling shop endpoint
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self._get_base_url()}/shop.json",
                    headers=self._get_headers(),
                )
                if response.status_code == 200:
                    self._authenticated = True
                    return True
                else:
                    self._authenticated = False
                    return False
        except httpx.RequestError:
            self._authenticated = False
            return False

    async def test_connection(self) -> bool:
        """Test that the connection is still valid.

        Returns:
            True if connection is healthy, False otherwise
        """
        if not self._authenticated:
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self._get_base_url()}/shop.json",
                    headers=self._get_headers(),
                )
                return response.status_code == 200
        except httpx.RequestError:
            return False

    async def get_shop_info(self) -> dict | None:
        """Fetch shop details for shipper information.

        Retrieves store details from Shopify's shop.json endpoint.
        Used to populate shipper information for shipments.

        Returns:
            Dict containing shop details if successful:
                - name: Store name
                - email: Store email
                - phone: Store phone number
                - address1: Street address
                - address2: Optional second address line
                - city: City
                - province: Full province/state name
                - province_code: Province/state code (e.g., "CA")
                - zip: Postal code
                - country: Full country name
                - country_code: Country code (e.g., "US")
            None if request fails or not authenticated.

        Example:
            shop = await client.get_shop_info()
            if shop:
                shipper = build_shipper(shop)
        """
        if not self._authenticated:
            return None

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self._get_base_url()}/shop.json",
                    headers=self._get_headers(),
                )
                if response.status_code != 200:
                    return None

                data = response.json()
                return data.get("shop")
        except httpx.RequestError:
            return None

    async def fetch_orders(self, filters: OrderFilters) -> list[ExternalOrder]:
        """Fetch orders from Shopify with filters.

        Args:
            filters: Order filtering criteria including:
                - status: Maps to fulfillment_status (unfulfilled, fulfilled, etc.)
                - date_from: Minimum created_at timestamp
                - date_to: Maximum created_at timestamp
                - limit: Maximum orders to return (default 100, max 250 for Shopify)

        Returns:
            List of orders in normalized ExternalOrder format
        """
        if not self._authenticated:
            return []

        params: dict[str, str | int] = {
            "limit": min(filters.limit, 250),  # Shopify max is 250
        }

        if filters.status:
            params["fulfillment_status"] = filters.status

        if filters.date_from:
            params["created_at_min"] = filters.date_from

        if filters.date_to:
            params["created_at_max"] = filters.date_to

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self._get_base_url()}/orders.json",
                    headers=self._get_headers(),
                    params=params,
                )
                if response.status_code != 200:
                    return []

                data = response.json()
                orders_data = data.get("orders", [])
                return [self._normalize_order(order) for order in orders_data]
        except httpx.RequestError:
            return []

    async def get_order(self, order_id: str) -> ExternalOrder | None:
        """Get a single order by ID.

        Args:
            order_id: Shopify order ID (numeric string)

        Returns:
            Order if found, None otherwise
        """
        if not self._authenticated:
            return None

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self._get_base_url()}/orders/{order_id}.json",
                    headers=self._get_headers(),
                )
                if response.status_code != 200:
                    return None

                data = response.json()
                order_data = data.get("order")
                if order_data:
                    return self._normalize_order(order_data)
                return None
        except httpx.RequestError:
            return None

    async def update_tracking(self, update: TrackingUpdate) -> bool:
        """Create or update a fulfillment with tracking information.

        Shopify requires creating a fulfillment to add tracking to an order.
        If the order is already fulfilled, updates the existing fulfillment's
        tracking info instead of creating a duplicate.

        Args:
            update: Tracking update containing:
                - order_id: Shopify order ID
                - tracking_number: Carrier tracking number
                - carrier: Carrier name (e.g., 'UPS')
                - tracking_url: Optional tracking URL

        Returns:
            True if fulfillment created/updated successfully, False otherwise
        """
        if not self._authenticated:
            return False

        try:
            async with httpx.AsyncClient() as client:
                order_response = await client.get(
                    f"{self._get_base_url()}/orders/{update.order_id}.json",
                    headers=self._get_headers(),
                )
                if order_response.status_code != 200:
                    return False

                order_data = order_response.json().get("order", {})

                # Idempotency guard: if already fulfilled, update tracking
                # on the existing fulfillment instead of creating a duplicate.
                if order_data.get("fulfillment_status") == "fulfilled":
                    return await self._update_existing_fulfillment_tracking(
                        client, order_data, update
                    )

                line_items = order_data.get("line_items", [])

                # Build fulfillment payload
                fulfillment_payload = {
                    "fulfillment": {
                        "tracking_number": update.tracking_number,
                        "tracking_company": update.carrier,
                        "notify_customer": True,
                        "line_items": [
                            {"id": item["id"]} for item in line_items
                        ],
                    }
                }

                if update.tracking_url:
                    fulfillment_payload["fulfillment"]["tracking_url"] = (
                        update.tracking_url
                    )

                # Create the fulfillment
                fulfillment_response = await client.post(
                    f"{self._get_base_url()}/orders/{update.order_id}/fulfillments.json",
                    headers=self._get_headers(),
                    json=fulfillment_payload,
                )

                return fulfillment_response.status_code in (200, 201)
        except httpx.RequestError:
            return False

    async def _update_existing_fulfillment_tracking(
        self,
        client: httpx.AsyncClient,
        order_data: dict,
        update: TrackingUpdate,
    ) -> bool:
        """Update tracking on an existing fulfillment (idempotency path).

        Called when order is already fulfilled to prevent duplicate
        fulfillment records on retries/reruns.

        Args:
            client: Active httpx client
            order_data: Shopify order data dict
            update: Tracking update with new tracking info

        Returns:
            True if tracking updated successfully, False otherwise
        """
        fulfillments = order_data.get("fulfillments", [])
        if not fulfillments:
            return False

        fulfillment_id = fulfillments[0].get("id")
        if not fulfillment_id:
            return False
        tracking_payload = {
            "fulfillment": {
                "tracking_number": update.tracking_number,
                "tracking_company": update.carrier,
                "notify_customer": False,
            }
        }
        if update.tracking_url:
            tracking_payload["fulfillment"]["tracking_url"] = update.tracking_url

        resp = await client.put(
            f"{self._get_base_url()}/orders/{update.order_id}"
            f"/fulfillments/{fulfillment_id}.json",
            headers=self._get_headers(),
            json=tracking_payload,
        )
        return resp.status_code == 200

    def _normalize_order(self, shopify_order: dict) -> ExternalOrder:
        """Convert Shopify order format to normalized ExternalOrder.

        Args:
            shopify_order: Raw Shopify order data from API

        Returns:
            Normalized ExternalOrder object
        """
        shipping_address = shopify_order.get("shipping_address") or {}
        customer = shopify_order.get("customer") or {}

        # Build customer name from first/last
        customer_first = customer.get("first_name", "")
        customer_last = customer.get("last_name", "")
        customer_name = f"{customer_first} {customer_last}".strip() or "Unknown"

        # Build ship-to name from shipping address
        ship_first = shipping_address.get("first_name", "")
        ship_last = shipping_address.get("last_name", "")
        ship_to_name = f"{ship_first} {ship_last}".strip() or customer_name

        # Determine order status
        fulfillment_status = shopify_order.get("fulfillment_status") or "unfulfilled"
        financial_status = shopify_order.get("financial_status", "pending")
        status = f"{financial_status}/{fulfillment_status}"

        # Normalize line items
        raw_line_items = shopify_order.get("line_items", [])
        line_items = []
        for item in raw_line_items:
            line_items.append({
                "id": str(item.get("id", "")),
                "title": item.get("title", ""),
                "quantity": item.get("quantity", 1),
                "price": item.get("price", "0.00"),
                "sku": item.get("sku", ""),
            })

        # Extract tags (Shopify returns comma-separated string)
        tags = shopify_order.get("tags") or None

        # Compute total weight from line items (Shopify stores grams per item)
        total_weight_grams = sum(
            (item.get("grams", 0) or 0) * item.get("quantity", 1)
            for item in raw_line_items
        ) or None

        # Extract shipping method from first shipping line
        shipping_lines = shopify_order.get("shipping_lines", [])
        shipping_method = shipping_lines[0].get("title") if shipping_lines else None

        # Compute item count
        item_count = sum(
            item.get("quantity", 1)
            for item in raw_line_items
        ) or None

        return ExternalOrder(
            platform="shopify",
            order_id=str(shopify_order.get("id", "")),
            order_number=str(shopify_order.get("order_number", "")),
            status=status,
            created_at=shopify_order.get("created_at", ""),
            customer_name=customer_name,
            customer_email=customer.get("email"),
            ship_to_name=ship_to_name,
            ship_to_company=shipping_address.get("company"),
            ship_to_address1=shipping_address.get("address1", ""),
            ship_to_address2=shipping_address.get("address2"),
            ship_to_city=shipping_address.get("city", ""),
            ship_to_state=shipping_address.get("province_code", ""),
            ship_to_postal_code=shipping_address.get("zip", ""),
            ship_to_country=shipping_address.get("country_code", "US"),
            ship_to_phone=shipping_address.get("phone"),
            total_price=shopify_order.get("total_price"),
            financial_status=financial_status,
            fulfillment_status=fulfillment_status,
            tags=tags,
            total_weight_grams=total_weight_grams,
            shipping_method=shipping_method,
            item_count=item_count,
            items=line_items,
            raw_data=shopify_order,
        )
