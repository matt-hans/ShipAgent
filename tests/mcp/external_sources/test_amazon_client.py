"""Test Amazon SP-API client implementation."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.mcp.external_sources.clients.amazon import AmazonClient
from src.mcp.external_sources.clients.base import PlatformClient
from src.mcp.external_sources.models import ExternalOrder, OrderFilters, TrackingUpdate


class TestAmazonClientInit:
    """Test AmazonClient initialization."""

    def test_extends_platform_client(self):
        assert issubclass(AmazonClient, PlatformClient)

    def test_platform_name(self):
        client = AmazonClient()
        assert client.platform_name == "amazon"


class TestFetchOrderItems:
    """Test _fetch_order_items method."""

    @pytest.mark.asyncio
    async def test_fetch_order_items_success(self):
        """Fetches items from SP-API and returns list of item dicts."""
        client = AmazonClient()
        client._authenticated = True
        client._access_token = "test-token"
        client._token_expires_at = 9999999999.0
        client._marketplace_id = "ATVPDKIKX0DER"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "payload": {
                "OrderItems": [
                    {
                        "OrderItemId": "item-1",
                        "Title": "Widget A",
                        "QuantityOrdered": 2,
                        "ItemPrice": {"Amount": "19.99", "CurrencyCode": "USD"},
                        "SellerSKU": "SKU-001",
                        "ASIN": "B00TEST123",
                        "ProductInfo": {"NumberOfItems": "1"},
                    },
                    {
                        "OrderItemId": "item-2",
                        "Title": "Widget B",
                        "QuantityOrdered": 1,
                        "ItemPrice": {"Amount": "9.99", "CurrencyCode": "USD"},
                        "SellerSKU": "SKU-002",
                        "ASIN": "B00TEST456",
                    },
                ]
            }
        }

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            items = await client._fetch_order_items("ORDER-123")

        assert len(items) == 2
        assert items[0]["OrderItemId"] == "item-1"
        assert items[1]["SellerSKU"] == "SKU-002"

    @pytest.mark.asyncio
    async def test_fetch_order_items_not_authenticated(self):
        """Returns empty list when not authenticated."""
        client = AmazonClient()
        client._authenticated = False

        items = await client._fetch_order_items("ORDER-123")
        assert items == []

    @pytest.mark.asyncio
    async def test_fetch_order_items_api_error(self):
        """Returns empty list on API error."""
        client = AmazonClient()
        client._authenticated = True
        client._access_token = "test-token"
        client._token_expires_at = 9999999999.0

        mock_response = MagicMock()
        mock_response.status_code = 429

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            items = await client._fetch_order_items("ORDER-123")

        assert items == []


class TestNormalizeOrderWithItems:
    """Test _normalize_order with item enrichment."""

    def test_normalize_with_items_populates_fields(self):
        """Items are normalized into ExternalOrder.items with enrichment."""
        client = AmazonClient()
        client._marketplace_id = "ATVPDKIKX0DER"

        order = {
            "AmazonOrderId": "111-1234567-1234567",
            "PurchaseDate": "2026-02-28T10:00:00Z",
            "OrderStatus": "Unshipped",
            "OrderTotal": {"Amount": "49.97", "CurrencyCode": "USD"},
            "FulfillmentChannel": "MFN",
            "ShippingAddress": {
                "Name": "Jane Doe",
                "AddressLine1": "123 Main St",
                "City": "Springfield",
                "StateOrRegion": "IL",
                "PostalCode": "62701",
                "CountryCode": "US",
            },
            "BuyerInfo": {"BuyerEmail": "jane@example.com"},
            "ShipmentServiceLevelCategory": "Standard",
            "NumberOfItemsShipped": 0,
            "NumberOfItemsUnshipped": 3,
        }

        items = [
            {
                "OrderItemId": "item-1",
                "Title": "Widget A",
                "QuantityOrdered": 2,
                "ItemPrice": {"Amount": "19.99", "CurrencyCode": "USD"},
                "SellerSKU": "SKU-001",
                "ASIN": "B00TEST123",
                "ItemWeight": {"Value": "200", "Unit": "Grams"},
                "ProductInfo": {"NumberOfItems": "1"},
            },
            {
                "OrderItemId": "item-2",
                "Title": "Widget B",
                "QuantityOrdered": 1,
                "ItemPrice": {"Amount": "9.99", "CurrencyCode": "USD"},
                "SellerSKU": "SKU-002",
                "ASIN": "B00TEST456",
                "ItemWeight": {"Value": "0.5", "Unit": "Pounds"},
            },
        ]

        result = client._normalize_order(order, items)

        assert isinstance(result, ExternalOrder)
        assert result.platform == "amazon"
        assert result.order_id == "111-1234567-1234567"
        assert len(result.items) == 2
        assert result.items[0]["id"] == "item-1"
        assert result.items[0]["sku"] == "SKU-001"
        assert result.items[0]["asin"] == "B00TEST123"
        assert result.items[0]["quantity"] == 2
        assert result.item_count == 3  # 2 + 1
        # Weight: (200g * 2) + (0.5 lb * 453.592 * 1) = 400 + 226.796 = ~626.8
        assert result.total_weight_grams is not None
        assert abs(result.total_weight_grams - 626.796) < 1.0

    def test_normalize_without_items_backward_compatible(self):
        """Passing no items preserves existing behavior."""
        client = AmazonClient()
        client._marketplace_id = "ATVPDKIKX0DER"

        order = {
            "AmazonOrderId": "222-1234567-1234567",
            "PurchaseDate": "2026-02-28T10:00:00Z",
            "OrderStatus": "Shipped",
            "FulfillmentChannel": "AFN",
            "ShippingAddress": {"Name": "Test", "AddressLine1": "456 Elm", "City": "Austin", "StateOrRegion": "TX", "PostalCode": "73301", "CountryCode": "US"},
            "BuyerInfo": {},
            "NumberOfItemsShipped": 2,
            "NumberOfItemsUnshipped": 0,
        }

        result = client._normalize_order(order)
        assert result.items == []
        assert result.item_count == 2  # fallback to shipped + unshipped


class TestFetchOrdersWithItems:
    """Test that fetch_orders calls _fetch_order_items for each order."""

    @pytest.mark.asyncio
    async def test_fetch_orders_populates_items(self):
        """fetch_orders fetches items per-order and enriches ExternalOrder."""
        client = AmazonClient()
        client._authenticated = True
        client._access_token = "test-token"
        client._token_expires_at = 9999999999.0
        client._marketplace_id = "ATVPDKIKX0DER"
        client._sandbox = False

        orders_response = MagicMock()
        orders_response.status_code = 200
        orders_response.json.return_value = {
            "payload": {
                "Orders": [
                    {
                        "AmazonOrderId": "111-0000001-0000001",
                        "PurchaseDate": "2026-02-28T10:00:00Z",
                        "OrderStatus": "Unshipped",
                        "FulfillmentChannel": "MFN",
                        "ShippingAddress": {
                            "Name": "Test User",
                            "AddressLine1": "1 Main St",
                            "City": "NY",
                            "StateOrRegion": "NY",
                            "PostalCode": "10001",
                            "CountryCode": "US",
                        },
                        "BuyerInfo": {},
                    },
                ],
            }
        }

        mock_items = [
            {"OrderItemId": "i-1", "Title": "Gadget", "QuantityOrdered": 1,
             "SellerSKU": "G-001", "ASIN": "B001"},
        ]

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = orders_response
            with patch.object(
                client, "_fetch_order_items", new_callable=AsyncMock
            ) as mock_fetch_items:
                mock_fetch_items.return_value = mock_items
                # Patch asyncio.sleep to avoid real delay
                with patch("src.mcp.external_sources.clients.amazon.asyncio.sleep", new_callable=AsyncMock):
                    orders = await client.fetch_orders(OrderFilters(limit=10))

        assert len(orders) == 1
        assert orders[0].items[0]["id"] == "i-1"
        assert orders[0].items[0]["sku"] == "G-001"
        mock_fetch_items.assert_called_once_with("111-0000001-0000001")


class TestFetchOrdersWithoutItems:
    """Test fetch_orders with include_items=False skips per-order API calls."""

    @pytest.mark.asyncio
    async def test_fetch_orders_skips_items_when_disabled(self):
        """include_items=False skips _fetch_order_items and asyncio.sleep."""
        client = AmazonClient()
        client._authenticated = True
        client._access_token = "test-token"
        client._token_expires_at = 9999999999.0
        client._marketplace_id = "ATVPDKIKX0DER"
        client._sandbox = False

        orders_response = MagicMock()
        orders_response.status_code = 200
        orders_response.json.return_value = {
            "payload": {
                "Orders": [
                    {
                        "AmazonOrderId": "333-0000001-0000001",
                        "PurchaseDate": "2026-02-28T10:00:00Z",
                        "OrderStatus": "Unshipped",
                        "FulfillmentChannel": "MFN",
                        "ShippingAddress": {
                            "Name": "Fast User",
                            "AddressLine1": "99 Speed St",
                            "City": "LA",
                            "StateOrRegion": "CA",
                            "PostalCode": "90001",
                            "CountryCode": "US",
                        },
                        "BuyerInfo": {},
                        "NumberOfItemsUnshipped": 2,
                    },
                ],
            }
        }

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = orders_response
            with patch.object(
                client, "_fetch_order_items", new_callable=AsyncMock
            ) as mock_fetch_items:
                orders = await client.fetch_orders(
                    OrderFilters(limit=10, include_items=False)
                )

        assert len(orders) == 1
        assert orders[0].order_id == "333-0000001-0000001"
        assert orders[0].items == []
        mock_fetch_items.assert_not_called()


class TestGetOrderWithItems:
    """Test that get_order calls _fetch_order_items."""

    @pytest.mark.asyncio
    async def test_get_order_populates_items(self):
        """get_order fetches items and enriches the ExternalOrder."""
        client = AmazonClient()
        client._authenticated = True
        client._access_token = "test-token"
        client._token_expires_at = 9999999999.0
        client._marketplace_id = "ATVPDKIKX0DER"

        order_response = MagicMock()
        order_response.status_code = 200
        order_response.json.return_value = {
            "payload": {
                "AmazonOrderId": "222-0000001-0000001",
                "PurchaseDate": "2026-02-28T10:00:00Z",
                "OrderStatus": "Shipped",
                "FulfillmentChannel": "MFN",
                "ShippingAddress": {
                    "Name": "Test",
                    "AddressLine1": "2 Elm St",
                    "City": "LA",
                    "StateOrRegion": "CA",
                    "PostalCode": "90001",
                    "CountryCode": "US",
                },
                "BuyerInfo": {},
            }
        }

        mock_items = [
            {"OrderItemId": "i-99", "Title": "Thing", "QuantityOrdered": 3,
             "SellerSKU": "T-001", "ASIN": "B099"},
        ]

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = order_response
            with patch.object(
                client, "_fetch_order_items", new_callable=AsyncMock
            ) as mock_fetch_items:
                mock_fetch_items.return_value = mock_items
                order = await client.get_order("222-0000001-0000001")

        assert order is not None
        assert order.items[0]["id"] == "i-99"
        assert order.item_count == 3
        mock_fetch_items.assert_called_once_with("222-0000001-0000001")

class TestUpdateTracking:
    """Test tracking write-back via confirmShipment."""

    @pytest.mark.asyncio
    async def test_update_tracking_with_stored_items(self):
        """Confirms shipment using stored items for orderItems payload."""
        client = AmazonClient()
        client._authenticated = True
        client._access_token = "test-token"
        client._token_expires_at = 9999999999.0
        client._marketplace_id = "ATVPDKIKX0DER"

        # Pre-store items (simulating eager fetch)
        client._order_items_cache = {
            "ORDER-100": [
                {"OrderItemId": "oi-1", "QuantityOrdered": 2},
                {"OrderItemId": "oi-2", "QuantityOrdered": 1},
            ]
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"payload": {}}

        update = TrackingUpdate(
            order_id="ORDER-100",
            tracking_number="1Z999AA10123456784",
            carrier="UPS",
        )

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response
            result = await client.update_tracking(update)

        assert result is True
        # Verify the payload sent
        call_kwargs = mock_post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["marketplaceId"] == "ATVPDKIKX0DER"
        assert body["packageDetail"]["carrierCode"] == "UPS"
        assert body["packageDetail"]["trackingNumber"] == "1Z999AA10123456784"
        assert len(body["packageDetail"]["orderItems"]) == 2

    @pytest.mark.asyncio
    async def test_update_tracking_fallback_fetches_items(self):
        """Falls back to _fetch_order_items when cache misses."""
        client = AmazonClient()
        client._authenticated = True
        client._access_token = "test-token"
        client._token_expires_at = 9999999999.0
        client._marketplace_id = "ATVPDKIKX0DER"
        client._order_items_cache = {}  # empty cache

        mock_items = [{"OrderItemId": "oi-9", "QuantityOrdered": 1}]

        mock_response = MagicMock()
        mock_response.status_code = 200

        update = TrackingUpdate(
            order_id="ORDER-200",
            tracking_number="1Z111BB20123456784",
            carrier="UPS",
        )

        with patch.object(
            client, "_fetch_order_items", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = mock_items
            with patch.object(
                httpx.AsyncClient, "post", new_callable=AsyncMock
            ) as mock_post:
                mock_post.return_value = mock_response
                result = await client.update_tracking(update)

        assert result is True
        mock_fetch.assert_called_once_with("ORDER-200")

    @pytest.mark.asyncio
    async def test_update_tracking_not_authenticated(self):
        """Returns False when not authenticated."""
        client = AmazonClient()
        client._authenticated = False

        update = TrackingUpdate(
            order_id="ORDER-300",
            tracking_number="1Z999CC30123456784",
            carrier="UPS",
        )

        result = await client.update_tracking(update)
        assert result is False


class TestGetShopInfo:
    """Test get_shop_info for seller metadata."""

    @pytest.mark.asyncio
    async def test_get_shop_info_returns_marketplace_data(self):
        """Returns marketplace participation metadata."""
        client = AmazonClient()
        client._authenticated = True
        client._access_token = "test-token"
        client._token_expires_at = 9999999999.0
        client._marketplace_id = "ATVPDKIKX0DER"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "payload": [
                {
                    "marketplace": {
                        "id": "ATVPDKIKX0DER",
                        "name": "Amazon.com",
                        "countryCode": "US",
                    },
                    "participation": {
                        "isParticipating": True,
                    },
                },
            ]
        }

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            result = await client.get_shop_info()

        assert result is not None
        assert result["name"] == "Amazon.com"
        assert result["marketplace_id"] == "ATVPDKIKX0DER"

    @pytest.mark.asyncio
    async def test_get_shop_info_not_authenticated(self):
        """Returns None when not authenticated."""
        client = AmazonClient()
        client._authenticated = False

        result = await client.get_shop_info()
        assert result is None
