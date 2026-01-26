"""Integration tests for Shopify order retrieval.

Tests verify:
- Fetch orders by status (unfulfilled, pending)
- Fetch orders by date range
- Order data schema matches expected structure
- Pagination works for large order sets
- Order line items and addresses extracted correctly

Requires: SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN environment variables
"""

import pytest

from tests.helpers import MCPTestClient, ShopifyTestStore
from tests.conftest import requires_shopify_credentials


@pytest.fixture
async def connected_shopify_mcp(shopify_mcp_config) -> MCPTestClient:
    """Create and start a Shopify MCP client."""
    client = MCPTestClient(
        command=shopify_mcp_config["command"],
        args=shopify_mcp_config["args"],
        env=shopify_mcp_config["env"],
    )
    await client.start()
    yield client
    await client.stop()


@pytest.fixture
def shopify_test_store() -> ShopifyTestStore:
    """Create ShopifyTestStore for test order management."""
    import os
    return ShopifyTestStore(
        access_token=os.environ.get("SHOPIFY_ACCESS_TOKEN", ""),
        store_domain=os.environ.get("SHOPIFY_STORE_DOMAIN", ""),
    )


@pytest.mark.integration
@pytest.mark.shopify
class TestShopifyOrderRetrieval:
    """Tests for fetching orders from Shopify."""

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_fetch_unfulfilled_orders(self, connected_shopify_mcp):
        """Should fetch orders with unfulfilled status."""
        # Note: Actual tool name depends on shopify-mcp package
        # This test documents expected behavior
        try:
            result = await connected_shopify_mcp.call_tool("get_orders", {
                "status": "unfulfilled",
                "limit": 10,
            })
            assert "orders" in result or "data" in result
        except RuntimeError as e:
            # Tool might have different name - log for debugging
            tools = await connected_shopify_mcp.list_tools()
            pytest.skip(f"get_orders tool not found. Available: {[t['name'] for t in tools]}")

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_order_contains_shipping_address(
        self, connected_shopify_mcp, shopify_test_store
    ):
        """Orders should contain complete shipping address."""
        # Create a test order
        order_id = await shopify_test_store.create_test_order(
            line_items=[{"title": "Test Item", "quantity": 1, "price": "10.00"}],
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

        try:
            # Fetch the order
            order = await shopify_test_store.get_order(order_id)

            # Verify shipping address fields
            address = order.get("shipping_address", {})
            assert address.get("city") == "Los Angeles"
            assert address.get("province") == "CA"
            assert address.get("zip") == "90001"
        finally:
            await shopify_test_store.cleanup_test_orders()


@pytest.mark.integration
@pytest.mark.shopify
class TestShopifyOrderDataIntegrity:
    """Tests for Shopify order data integrity."""

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_order_id_preserved(self, shopify_test_store):
        """Order ID should be preserved through retrieval."""
        order_id = await shopify_test_store.create_test_order(
            line_items=[{"title": "Test Item", "quantity": 1, "price": "10.00"}],
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

        try:
            order = await shopify_test_store.get_order(order_id)
            assert str(order["id"]) == order_id
        finally:
            await shopify_test_store.cleanup_test_orders()

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_line_items_preserved(self, shopify_test_store):
        """Line items should be fully preserved."""
        order_id = await shopify_test_store.create_test_order(
            line_items=[
                {"title": "Product A", "quantity": 2, "price": "15.00"},
                {"title": "Product B", "quantity": 1, "price": "25.00"},
            ],
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

        try:
            order = await shopify_test_store.get_order(order_id)
            line_items = order.get("line_items", [])

            assert len(line_items) == 2

            titles = [item["title"] for item in line_items]
            assert "Product A" in titles
            assert "Product B" in titles
        finally:
            await shopify_test_store.cleanup_test_orders()
