"""Test Shopify platform client implementation."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.mcp.external_sources.clients.base import PlatformClient
from src.mcp.external_sources.clients.shopify import ShopifyClient
from src.mcp.external_sources.models import (
    ExternalOrder,
    OrderFilters,
    TrackingUpdate,
)


class TestShopifyClientInit:
    """Test ShopifyClient initialization and inheritance."""

    def test_shopify_client_extends_platform_client(self):
        """Test that ShopifyClient is a subclass of PlatformClient."""
        assert issubclass(ShopifyClient, PlatformClient)

    def test_shopify_client_can_instantiate(self):
        """Test that ShopifyClient can be instantiated."""
        client = ShopifyClient()
        assert client is not None

    def test_platform_name_returns_shopify(self):
        """Test that platform_name property returns 'shopify'."""
        client = ShopifyClient()
        assert client.platform_name == "shopify"


class TestShopifyAuthentication:
    """Test Shopify authentication functionality."""

    @pytest.mark.asyncio
    async def test_authenticate_success(self):
        """Test successful authentication with valid credentials."""
        client = ShopifyClient()
        credentials = {
            "store_url": "mystore.myshopify.com",
            "access_token": "shpat_test_token_12345",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "shop": {
                "id": 123456789,
                "name": "My Store",
                "email": "owner@mystore.com",
            }
        }

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            result = await client.authenticate(credentials)

        assert result is True
        assert client._store_url == "mystore.myshopify.com"
        assert client._access_token == "shpat_test_token_12345"

    @pytest.mark.asyncio
    async def test_authenticate_with_https_prefix(self):
        """Test authentication strips https:// prefix from store URL."""
        client = ShopifyClient()
        credentials = {
            "store_url": "https://mystore.myshopify.com",
            "access_token": "shpat_test_token",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"shop": {"id": 123}}

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            result = await client.authenticate(credentials)

        assert result is True
        assert client._store_url == "mystore.myshopify.com"

    @pytest.mark.asyncio
    async def test_authenticate_failure_invalid_token(self):
        """Test authentication failure with invalid token."""
        client = ShopifyClient()
        credentials = {
            "store_url": "mystore.myshopify.com",
            "access_token": "invalid_token",
        }

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"errors": "Unauthorized"}

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            result = await client.authenticate(credentials)

        assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_missing_store_url(self):
        """Test authentication fails with missing store_url."""
        client = ShopifyClient()
        credentials = {"access_token": "shpat_test_token"}

        result = await client.authenticate(credentials)
        assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_missing_access_token(self):
        """Test authentication fails with missing access_token."""
        client = ShopifyClient()
        credentials = {"store_url": "mystore.myshopify.com"}

        result = await client.authenticate(credentials)
        assert result is False


class TestShopifyTestConnection:
    """Test Shopify connection testing functionality."""

    @pytest.mark.asyncio
    async def test_connection_success(self):
        """Test successful connection test."""
        client = ShopifyClient()
        client._store_url = "mystore.myshopify.com"
        client._access_token = "shpat_test_token"
        client._authenticated = True

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"shop": {"id": 123}}

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            result = await client.test_connection()

        assert result is True
        mock_get.assert_called_once()
        # Verify correct URL was called
        call_url = mock_get.call_args[0][0]
        assert "/shop.json" in call_url

    @pytest.mark.asyncio
    async def test_connection_failure_not_authenticated(self):
        """Test connection test fails when not authenticated."""
        client = ShopifyClient()
        result = await client.test_connection()
        assert result is False

    @pytest.mark.asyncio
    async def test_connection_failure_api_error(self):
        """Test connection test fails on API error."""
        client = ShopifyClient()
        client._store_url = "mystore.myshopify.com"
        client._access_token = "shpat_test_token"
        client._authenticated = True

        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            result = await client.test_connection()

        assert result is False


class TestShopifyFetchOrders:
    """Test Shopify order fetching functionality."""

    @pytest.fixture
    def authenticated_client(self):
        """Create an authenticated client for testing."""
        client = ShopifyClient()
        client._store_url = "mystore.myshopify.com"
        client._access_token = "shpat_test_token"
        client._authenticated = True
        return client

    @pytest.fixture
    def sample_shopify_order(self):
        """Sample Shopify order response data."""
        return {
            "id": 450789469,
            "order_number": 1001,
            "created_at": "2026-01-20T10:30:00-05:00",
            "financial_status": "paid",
            "fulfillment_status": None,
            "customer": {
                "first_name": "John",
                "last_name": "Doe",
                "email": "john.doe@example.com",
            },
            "shipping_address": {
                "first_name": "John",
                "last_name": "Doe",
                "company": "Acme Inc",
                "address1": "123 Main St",
                "address2": "Suite 100",
                "city": "San Francisco",
                "province": "California",
                "province_code": "CA",
                "zip": "94102",
                "country_code": "US",
                "phone": "415-555-1234",
            },
            "line_items": [
                {
                    "id": 1,
                    "title": "Widget",
                    "quantity": 2,
                    "price": "29.99",
                    "sku": "WIDGET-001",
                }
            ],
        }

    @pytest.mark.asyncio
    async def test_fetch_orders_success(
        self, authenticated_client, sample_shopify_order
    ):
        """Test successful order fetching."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"orders": [sample_shopify_order]}

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            filters = OrderFilters(status="unfulfilled", limit=50)
            orders = await authenticated_client.fetch_orders(filters)

        assert len(orders) == 1
        order = orders[0]
        assert isinstance(order, ExternalOrder)
        assert order.platform == "shopify"
        assert order.order_id == "450789469"
        assert order.order_number == "1001"
        assert order.customer_name == "John Doe"
        assert order.ship_to_name == "John Doe"
        assert order.ship_to_city == "San Francisco"
        assert order.ship_to_state == "CA"
        assert order.ship_to_postal_code == "94102"

    @pytest.mark.asyncio
    async def test_fetch_orders_with_status_filter(self, authenticated_client):
        """Test order fetching applies status filter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"orders": []}

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            filters = OrderFilters(status="unfulfilled")
            await authenticated_client.fetch_orders(filters)

        # Verify the status filter was passed as query param
        call_url = mock_get.call_args[0][0]
        assert "fulfillment_status=unfulfilled" in call_url or mock_get.call_args[
            1
        ].get("params", {}).get("fulfillment_status") == "unfulfilled"

    @pytest.mark.asyncio
    async def test_fetch_orders_with_date_filter(self, authenticated_client):
        """Test order fetching applies date filters."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"orders": []}

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            filters = OrderFilters(
                date_from="2026-01-01T00:00:00Z",
                date_to="2026-01-31T23:59:59Z",
            )
            await authenticated_client.fetch_orders(filters)

        # Verify date filters were applied
        _, kwargs = mock_get.call_args
        params = kwargs.get("params", {})
        assert "created_at_min" in params or "2026-01-01" in str(mock_get.call_args)

    @pytest.mark.asyncio
    async def test_fetch_orders_with_limit(self, authenticated_client):
        """Test order fetching applies limit."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"orders": []}

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            filters = OrderFilters(limit=25)
            await authenticated_client.fetch_orders(filters)

        # Verify limit was applied
        _, kwargs = mock_get.call_args
        params = kwargs.get("params", {})
        assert params.get("limit") == 25

    @pytest.mark.asyncio
    async def test_fetch_orders_not_authenticated(self):
        """Test fetch_orders returns empty list when not authenticated."""
        client = ShopifyClient()
        filters = OrderFilters()
        orders = await client.fetch_orders(filters)
        assert orders == []

    @pytest.mark.asyncio
    async def test_fetch_orders_api_error(self, authenticated_client):
        """Test fetch_orders returns empty list on API error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"errors": "Internal Server Error"}

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            filters = OrderFilters()
            orders = await authenticated_client.fetch_orders(filters)

        assert orders == []


class TestShopifyGetOrder:
    """Test Shopify single order retrieval functionality."""

    @pytest.fixture
    def authenticated_client(self):
        """Create an authenticated client for testing."""
        client = ShopifyClient()
        client._store_url = "mystore.myshopify.com"
        client._access_token = "shpat_test_token"
        client._authenticated = True
        return client

    @pytest.fixture
    def sample_shopify_order(self):
        """Sample Shopify order response data."""
        return {
            "id": 450789469,
            "order_number": 1001,
            "created_at": "2026-01-20T10:30:00-05:00",
            "financial_status": "paid",
            "fulfillment_status": "fulfilled",
            "customer": {
                "first_name": "Jane",
                "last_name": "Smith",
                "email": "jane.smith@example.com",
            },
            "shipping_address": {
                "first_name": "Jane",
                "last_name": "Smith",
                "company": None,
                "address1": "456 Oak Ave",
                "address2": None,
                "city": "Los Angeles",
                "province": "California",
                "province_code": "CA",
                "zip": "90001",
                "country_code": "US",
                "phone": None,
            },
            "line_items": [],
        }

    @pytest.mark.asyncio
    async def test_get_order_success(
        self, authenticated_client, sample_shopify_order
    ):
        """Test successful single order retrieval."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"order": sample_shopify_order}

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            order = await authenticated_client.get_order("450789469")

        assert order is not None
        assert isinstance(order, ExternalOrder)
        assert order.order_id == "450789469"
        assert order.customer_name == "Jane Smith"
        assert order.ship_to_city == "Los Angeles"

        # Verify correct URL was called
        call_url = mock_get.call_args[0][0]
        assert "/orders/450789469.json" in call_url

    @pytest.mark.asyncio
    async def test_get_order_not_found(self, authenticated_client):
        """Test get_order returns None for non-existent order."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"errors": "Not Found"}

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            order = await authenticated_client.get_order("999999999")

        assert order is None

    @pytest.mark.asyncio
    async def test_get_order_not_authenticated(self):
        """Test get_order returns None when not authenticated."""
        client = ShopifyClient()
        order = await client.get_order("450789469")
        assert order is None


class TestShopifyUpdateTracking:
    """Test Shopify tracking update functionality."""

    @pytest.fixture
    def authenticated_client(self):
        """Create an authenticated client for testing."""
        client = ShopifyClient()
        client._store_url = "mystore.myshopify.com"
        client._access_token = "shpat_test_token"
        client._authenticated = True
        return client

    @pytest.mark.asyncio
    async def test_update_tracking_success(self, authenticated_client):
        """Test successful tracking update via fulfillment creation."""
        # First mock for getting order (to retrieve line_items)
        order_response = MagicMock()
        order_response.status_code = 200
        order_response.json.return_value = {
            "order": {
                "id": 450789469,
                "line_items": [{"id": 1234567890}],
            }
        }

        # Second mock for creating fulfillment
        fulfillment_response = MagicMock()
        fulfillment_response.status_code = 201
        fulfillment_response.json.return_value = {
            "fulfillment": {
                "id": 987654321,
                "tracking_number": "1Z999AA10123456784",
                "tracking_company": "UPS",
            }
        }

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get, \
             patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_get.return_value = order_response
            mock_post.return_value = fulfillment_response

            update = TrackingUpdate(
                order_id="450789469",
                tracking_number="1Z999AA10123456784",
                carrier="UPS",
                tracking_url="https://www.ups.com/track?tracknum=1Z999AA10123456784",
            )
            result = await authenticated_client.update_tracking(update)

        assert result is True

        # Verify fulfillment POST was made
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "/fulfillments.json" in call_url

        # Verify payload contains tracking info
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json", {})
        fulfillment_data = payload.get("fulfillment", {})
        assert fulfillment_data.get("tracking_number") == "1Z999AA10123456784"
        assert fulfillment_data.get("tracking_company") == "UPS"

    @pytest.mark.asyncio
    async def test_update_tracking_failure(self, authenticated_client):
        """Test tracking update failure."""
        order_response = MagicMock()
        order_response.status_code = 200
        order_response.json.return_value = {
            "order": {
                "id": 450789469,
                "line_items": [{"id": 1234567890}],
            }
        }

        fulfillment_response = MagicMock()
        fulfillment_response.status_code = 422
        fulfillment_response.json.return_value = {
            "errors": {"base": ["Order already fulfilled"]}
        }

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get, \
             patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_get.return_value = order_response
            mock_post.return_value = fulfillment_response

            update = TrackingUpdate(
                order_id="450789469",
                tracking_number="1Z999AA10123456784",
                carrier="UPS",
            )
            result = await authenticated_client.update_tracking(update)

        assert result is False

    @pytest.mark.asyncio
    async def test_update_tracking_not_authenticated(self):
        """Test update_tracking returns False when not authenticated."""
        client = ShopifyClient()
        update = TrackingUpdate(
            order_id="450789469",
            tracking_number="1Z999AA10123456784",
            carrier="UPS",
        )
        result = await client.update_tracking(update)
        assert result is False


class TestShopifyGetShopInfo:
    """Test Shopify shop info retrieval functionality."""

    @pytest.fixture
    def authenticated_client(self):
        """Create an authenticated client for testing."""
        client = ShopifyClient()
        client._store_url = "mystore.myshopify.com"
        client._access_token = "shpat_test_token"
        client._authenticated = True
        return client

    @pytest.fixture
    def sample_shop_response(self):
        """Sample Shopify shop response data."""
        return {
            "shop": {
                "id": 123456789,
                "name": "My Test Store",
                "email": "owner@mystore.com",
                "phone": "555-123-4567",
                "address1": "123 Main St",
                "address2": "Suite 100",
                "city": "Los Angeles",
                "province": "California",
                "province_code": "CA",
                "zip": "90001",
                "country": "United States",
                "country_code": "US",
            }
        }

    @pytest.mark.asyncio
    async def test_get_shop_info_success(
        self, authenticated_client, sample_shop_response
    ):
        """Test successful shop info retrieval."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_shop_response

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            shop = await authenticated_client.get_shop_info()

        assert shop is not None
        assert shop["name"] == "My Test Store"
        assert shop["phone"] == "555-123-4567"
        assert shop["address1"] == "123 Main St"
        assert shop["city"] == "Los Angeles"
        assert shop["province_code"] == "CA"
        assert shop["zip"] == "90001"
        assert shop["country_code"] == "US"

    @pytest.mark.asyncio
    async def test_get_shop_info_not_authenticated(self):
        """Test get_shop_info returns None when not authenticated."""
        client = ShopifyClient()
        shop = await client.get_shop_info()
        assert shop is None

    @pytest.mark.asyncio
    async def test_get_shop_info_api_error(self, authenticated_client):
        """Test get_shop_info returns None on API error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"errors": "Internal Server Error"}

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response
            shop = await authenticated_client.get_shop_info()

        assert shop is None

    @pytest.mark.asyncio
    async def test_get_shop_info_request_error(self, authenticated_client):
        """Test get_shop_info returns None on request error."""
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = httpx.RequestError("Connection failed")
            shop = await authenticated_client.get_shop_info()

        assert shop is None


class TestShopifyApiUrl:
    """Test Shopify API URL construction."""

    def test_base_url_format(self):
        """Test that base URL is constructed correctly."""
        client = ShopifyClient()
        client._store_url = "mystore.myshopify.com"
        expected = "https://mystore.myshopify.com/admin/api/2024-01"
        assert client._get_base_url() == expected

    def test_headers_include_access_token(self):
        """Test that headers include access token."""
        client = ShopifyClient()
        client._access_token = "shpat_test_token"
        headers = client._get_headers()
        assert headers.get("X-Shopify-Access-Token") == "shpat_test_token"
        assert headers.get("Content-Type") == "application/json"
