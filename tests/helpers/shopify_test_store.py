"""Shopify test store utilities for integration testing.

Provides helpers for creating, managing, and cleaning up test orders
in a Shopify development/test store.
"""

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ShopifyTestStore:
    """Helper for managing test data in a Shopify store.

    Uses the Shopify CLI to create and manage test orders,
    enabling integration testing of the Shopify → Shipment pipeline.

    Attributes:
        access_token: Shopify Admin API access token
        store_domain: Store domain (e.g., mystore.myshopify.com)
    """

    access_token: str
    store_domain: str
    _created_order_ids: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        """Validate credentials."""
        if not self.access_token:
            raise ValueError("access_token is required")
        if not self.store_domain:
            raise ValueError("store_domain is required")

    @property
    def created_order_ids(self) -> list[str]:
        """Get list of order IDs created by this test session."""
        return list(self._created_order_ids)

    async def create_test_order(
        self,
        line_items: list[dict[str, Any]],
        shipping_address: dict[str, str],
        customer_email: str = "test@example.com",
    ) -> str:
        """Create a test order in Shopify.

        Args:
            line_items: List of line items with title, quantity, price
            shipping_address: Shipping address dictionary
            customer_email: Customer email for the order

        Returns:
            Created order ID

        Example:
            order_id = await store.create_test_order(
                line_items=[{"title": "Test Product", "quantity": 1, "price": "10.00"}],
                shipping_address={
                    "first_name": "Test",
                    "last_name": "Customer",
                    "address1": "123 Test St",
                    "city": "Los Angeles",
                    "province": "CA",
                    "zip": "90001",
                    "country": "US",
                },
            )
        """
        # Build order payload
        order_data = {
            "order": {
                "email": customer_email,
                "fulfillment_status": "unfulfilled",
                "send_receipt": False,
                "send_fulfillment_receipt": False,
                "line_items": [
                    {
                        "title": item.get("title", "Test Product"),
                        "quantity": item.get("quantity", 1),
                        "price": item.get("price", "10.00"),
                    }
                    for item in line_items
                ],
                "shipping_address": shipping_address,
            }
        }

        # Use curl to create order via Admin API
        result = subprocess.run(
            [
                "curl",
                "-s",
                "-X", "POST",
                f"https://{self.store_domain}/admin/api/2024-01/orders.json",
                "-H", f"X-Shopify-Access-Token: {self.access_token}",
                "-H", "Content-Type: application/json",
                "-d", json.dumps(order_data),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to create order: {result.stderr}")

        response = json.loads(result.stdout)
        if "errors" in response:
            raise RuntimeError(f"Shopify API error: {response['errors']}")

        order_id = str(response["order"]["id"])
        self._created_order_ids.append(order_id)
        return order_id

    async def get_order(self, order_id: str) -> dict[str, Any]:
        """Get order details from Shopify.

        Args:
            order_id: Shopify order ID

        Returns:
            Order data dictionary
        """
        result = subprocess.run(
            [
                "curl",
                "-s",
                f"https://{self.store_domain}/admin/api/2024-01/orders/{order_id}.json",
                "-H", f"X-Shopify-Access-Token: {self.access_token}",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to get order: {result.stderr}")

        response = json.loads(result.stdout)
        return response.get("order", {})

    async def delete_order(self, order_id: str) -> None:
        """Delete an order from Shopify.

        Args:
            order_id: Shopify order ID to delete
        """
        # First cancel the order
        subprocess.run(
            [
                "curl",
                "-s",
                "-X", "POST",
                f"https://{self.store_domain}/admin/api/2024-01/orders/{order_id}/cancel.json",
                "-H", f"X-Shopify-Access-Token: {self.access_token}",
            ],
            capture_output=True,
        )

        # Then delete it
        subprocess.run(
            [
                "curl",
                "-s",
                "-X", "DELETE",
                f"https://{self.store_domain}/admin/api/2024-01/orders/{order_id}.json",
                "-H", f"X-Shopify-Access-Token: {self.access_token}",
            ],
            capture_output=True,
        )

        if order_id in self._created_order_ids:
            self._created_order_ids.remove(order_id)

    async def cleanup_test_orders(self) -> None:
        """Delete all orders created by this test session."""
        for order_id in list(self._created_order_ids):
            try:
                await self.delete_order(order_id)
            except Exception:
                pass  # Best effort cleanup
        self._created_order_ids.clear()
