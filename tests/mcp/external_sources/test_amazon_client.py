"""Test Amazon SP-API client implementation."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.mcp.external_sources.clients.amazon import AmazonClient
from src.mcp.external_sources.clients.base import PlatformClient
from src.mcp.external_sources.models import ExternalOrder, OrderFilters


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
