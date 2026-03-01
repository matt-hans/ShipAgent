"""Test WooCommerce platform client.

Tests WooCommerceClient for:
- Authentication with site_url, consumer_key, consumer_secret
- Connection testing via WooCommerce REST API
- Order fetching with filters
- Single order retrieval
- Tracking update (requires Shipment Tracking plugin)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp.external_sources.clients.woocommerce import (
    WooCommerceAPIError,
    WooCommerceAuthError,
    WooCommerceClient,
)
from src.mcp.external_sources.models import (
    ExternalOrder,
    OrderFilters,
    TrackingUpdate,
)

# Sample WooCommerce API responses for mocking
SAMPLE_WC_ORDER = {
    "id": 1234,
    "number": "1234",
    "status": "processing",
    "date_created": "2026-01-15T10:30:00",
    "billing": {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john.doe@example.com",
        "phone": "555-123-4567",
    },
    "shipping": {
        "first_name": "John",
        "last_name": "Doe",
        "company": "ACME Corp",
        "address_1": "123 Main Street",
        "address_2": "Apt 4B",
        "city": "Los Angeles",
        "state": "CA",
        "postcode": "90210",
        "country": "US",
    },
    "line_items": [
        {
            "id": 5678,
            "name": "Test Product",
            "quantity": 2,
            "total": "49.98",
            "sku": "TEST-001",
        }
    ],
}

SAMPLE_WC_SYSTEM_STATUS = {
    "environment": {
        "home_url": "https://example.com",
        "site_url": "https://example.com",
        "wc_version": "8.5.0",
    }
}


@pytest.fixture
def wc_credentials():
    """WooCommerce test credentials."""
    return {
        "site_url": "https://example.com",
        "consumer_key": "ck_test_key_123",
        "consumer_secret": "cs_test_secret_456",
    }


@pytest.fixture
def wc_client():
    """Create WooCommerceClient instance."""
    return WooCommerceClient()


class TestWooCommerceClientProperties:
    """Test WooCommerceClient basic properties."""

    def test_platform_name(self, wc_client):
        """Test platform_name returns 'woocommerce'."""
        assert wc_client.platform_name == "woocommerce"

    def test_initial_state(self, wc_client):
        """Test client starts unauthenticated."""
        assert wc_client._authenticated is False
        assert wc_client._site_url is None
        assert wc_client._consumer_key is None
        assert wc_client._consumer_secret is None


class TestWooCommerceAuthentication:
    """Test WooCommerce authentication."""

    @pytest.mark.asyncio
    async def test_authenticate_success(self, wc_client, wc_credentials):
        """Test successful authentication stores credentials."""
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            return_value=SAMPLE_WC_SYSTEM_STATUS,
        ):
            result = await wc_client.authenticate(wc_credentials)

            assert result is True
            assert wc_client._authenticated is True
            assert wc_client._site_url == "https://example.com"
            assert wc_client._consumer_key == "ck_test_key_123"
            assert wc_client._consumer_secret == "cs_test_secret_456"

    @pytest.mark.asyncio
    async def test_authenticate_missing_site_url(self, wc_client):
        """Test authentication fails with missing site_url."""
        credentials = {
            "consumer_key": "ck_test",
            "consumer_secret": "cs_test",
        }
        with pytest.raises(WooCommerceAuthError) as exc_info:
            await wc_client.authenticate(credentials)

        assert "site_url" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_authenticate_missing_consumer_key(self, wc_client):
        """Test authentication fails with missing consumer_key."""
        credentials = {
            "site_url": "https://example.com",
            "consumer_secret": "cs_test",
        }
        with pytest.raises(WooCommerceAuthError) as exc_info:
            await wc_client.authenticate(credentials)

        assert "consumer_key" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_authenticate_missing_consumer_secret(self, wc_client):
        """Test authentication fails with missing consumer_secret."""
        credentials = {
            "site_url": "https://example.com",
            "consumer_key": "ck_test",
        }
        with pytest.raises(WooCommerceAuthError) as exc_info:
            await wc_client.authenticate(credentials)

        assert "consumer_secret" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_authenticate_api_error(self, wc_client, wc_credentials):
        """Test authentication fails when API returns error."""
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=WooCommerceAPIError("401 Unauthorized"),
        ):
            with pytest.raises(WooCommerceAuthError) as exc_info:
                await wc_client.authenticate(wc_credentials)

            assert "Failed to authenticate" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_authenticate_normalizes_site_url(self, wc_client):
        """Test authentication normalizes site_url (removes trailing slash)."""
        credentials = {
            "site_url": "https://example.com/",
            "consumer_key": "ck_test",
            "consumer_secret": "cs_test",
        }
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            return_value=SAMPLE_WC_SYSTEM_STATUS,
        ):
            await wc_client.authenticate(credentials)

            assert wc_client._site_url == "https://example.com"


class TestWooCommerceConnection:
    """Test WooCommerce connection testing."""

    @pytest.mark.asyncio
    async def test_test_connection_success(self, wc_client, wc_credentials):
        """Test connection test passes with valid credentials."""
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            return_value=SAMPLE_WC_SYSTEM_STATUS,
        ):
            await wc_client.authenticate(wc_credentials)
            result = await wc_client.test_connection()

            assert result is True

    @pytest.mark.asyncio
    async def test_test_connection_not_authenticated(self, wc_client):
        """Test connection test fails when not authenticated."""
        result = await wc_client.test_connection()
        assert result is False

    @pytest.mark.asyncio
    async def test_test_connection_api_failure(self, wc_client, wc_credentials):
        """Test connection test fails on API error."""
        # First authenticate successfully
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            return_value=SAMPLE_WC_SYSTEM_STATUS,
        ):
            await wc_client.authenticate(wc_credentials)

        # Then fail on test_connection
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=WooCommerceAPIError("Connection failed"),
        ):
            result = await wc_client.test_connection()
            assert result is False


class TestWooCommerceFetchOrders:
    """Test WooCommerce order fetching."""

    @pytest.mark.asyncio
    async def test_fetch_orders_basic(self, wc_client, wc_credentials):
        """Test fetching orders returns normalized ExternalOrder list."""
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=[
                SAMPLE_WC_SYSTEM_STATUS,  # authenticate
                [SAMPLE_WC_ORDER],  # fetch_orders
            ],
        ):
            await wc_client.authenticate(wc_credentials)
            orders = await wc_client.fetch_orders(OrderFilters())

            assert len(orders) == 1
            order = orders[0]
            assert isinstance(order, ExternalOrder)
            assert order.platform == "woocommerce"
            assert order.order_id == "1234"
            assert order.order_number == "1234"
            assert order.status == "processing"
            assert order.customer_name == "John Doe"
            assert order.customer_email == "john.doe@example.com"
            assert order.ship_to_name == "John Doe"
            assert order.ship_to_company == "ACME Corp"
            assert order.ship_to_address1 == "123 Main Street"
            assert order.ship_to_address2 == "Apt 4B"
            assert order.ship_to_city == "Los Angeles"
            assert order.ship_to_state == "CA"
            assert order.ship_to_postal_code == "90210"
            assert order.ship_to_country == "US"
            assert order.ship_to_phone == "555-123-4567"
            assert len(order.items) == 1
            assert order.items[0]["name"] == "Test Product"

    @pytest.mark.asyncio
    async def test_fetch_orders_with_status_filter(self, wc_client, wc_credentials):
        """Test fetch_orders passes status filter to API."""
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=[
                SAMPLE_WC_SYSTEM_STATUS,
                [SAMPLE_WC_ORDER],
            ],
        ) as mock_request:
            await wc_client.authenticate(wc_credentials)
            await wc_client.fetch_orders(OrderFilters(status="processing"))

            # Check the second call (fetch_orders)
            call_args = mock_request.call_args_list[1]
            assert call_args[1]["params"]["status"] == "processing"

    @pytest.mark.asyncio
    async def test_fetch_orders_with_date_filters(self, wc_client, wc_credentials):
        """Test fetch_orders passes date filters to API."""
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=[
                SAMPLE_WC_SYSTEM_STATUS,
                [],
            ],
        ) as mock_request:
            await wc_client.authenticate(wc_credentials)
            await wc_client.fetch_orders(
                OrderFilters(
                    date_from="2026-01-01T00:00:00",
                    date_to="2026-01-31T23:59:59",
                )
            )

            call_args = mock_request.call_args_list[1]
            assert call_args[1]["params"]["after"] == "2026-01-01T00:00:00"
            assert call_args[1]["params"]["before"] == "2026-01-31T23:59:59"

    @pytest.mark.asyncio
    async def test_fetch_orders_with_pagination(self, wc_client, wc_credentials):
        """Test fetch_orders passes limit and offset to API."""
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=[
                SAMPLE_WC_SYSTEM_STATUS,
                [],
            ],
        ) as mock_request:
            await wc_client.authenticate(wc_credentials)
            await wc_client.fetch_orders(OrderFilters(limit=50, offset=100))

            call_args = mock_request.call_args_list[1]
            assert call_args[1]["params"]["per_page"] == 50
            assert call_args[1]["params"]["offset"] == 100

    @pytest.mark.asyncio
    async def test_fetch_orders_not_authenticated(self, wc_client):
        """Test fetch_orders raises error when not authenticated."""
        with pytest.raises(WooCommerceAuthError) as exc_info:
            await wc_client.fetch_orders(OrderFilters())

        assert "Not authenticated" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_orders_empty_response(self, wc_client, wc_credentials):
        """Test fetch_orders handles empty response."""
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=[
                SAMPLE_WC_SYSTEM_STATUS,
                [],
            ],
        ):
            await wc_client.authenticate(wc_credentials)
            orders = await wc_client.fetch_orders(OrderFilters())

            assert orders == []


class TestWooCommerceGetOrder:
    """Test WooCommerce single order retrieval."""

    @pytest.mark.asyncio
    async def test_get_order_found(self, wc_client, wc_credentials):
        """Test get_order returns ExternalOrder when found."""
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=[
                SAMPLE_WC_SYSTEM_STATUS,
                SAMPLE_WC_ORDER,
            ],
        ):
            await wc_client.authenticate(wc_credentials)
            order = await wc_client.get_order("1234")

            assert order is not None
            assert isinstance(order, ExternalOrder)
            assert order.order_id == "1234"

    @pytest.mark.asyncio
    async def test_get_order_not_found(self, wc_client, wc_credentials):
        """Test get_order returns None when order not found."""
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=[
                SAMPLE_WC_SYSTEM_STATUS,
                WooCommerceAPIError("404 Not Found"),
            ],
        ):
            await wc_client.authenticate(wc_credentials)
            order = await wc_client.get_order("9999")

            assert order is None

    @pytest.mark.asyncio
    async def test_get_order_not_authenticated(self, wc_client):
        """Test get_order raises error when not authenticated."""
        with pytest.raises(WooCommerceAuthError) as exc_info:
            await wc_client.get_order("1234")

        assert "Not authenticated" in str(exc_info.value)


class TestWooCommerceUpdateTracking:
    """Test WooCommerce tracking update."""

    @pytest.mark.asyncio
    async def test_update_tracking_success(self, wc_client, wc_credentials):
        """Test update_tracking returns True on success."""
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=[
                SAMPLE_WC_SYSTEM_STATUS,
                {"id": 1234, "meta_data": []},  # Updated order response
            ],
        ):
            await wc_client.authenticate(wc_credentials)
            update = TrackingUpdate(
                order_id="1234",
                tracking_number="1Z999AA10123456784",
                carrier="UPS",
                tracking_url="https://ups.com/track?num=1Z999AA10123456784",
            )
            result = await wc_client.update_tracking(update)

            assert result is True

    @pytest.mark.asyncio
    async def test_update_tracking_uses_metadata(self, wc_client, wc_credentials):
        """Test update_tracking sends tracking via meta_data."""
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=[
                SAMPLE_WC_SYSTEM_STATUS,
                {"id": 1234, "meta_data": []},
            ],
        ) as mock_request:
            await wc_client.authenticate(wc_credentials)
            update = TrackingUpdate(
                order_id="1234",
                tracking_number="1Z999AA10123456784",
                carrier="UPS",
            )
            await wc_client.update_tracking(update)

            # Check the PUT request data
            call_args = mock_request.call_args_list[1]
            assert call_args[1]["method"] == "PUT"
            json_data = call_args[1]["json"]
            assert "meta_data" in json_data
            meta = json_data["meta_data"]
            tracking_meta = {m["key"]: m["value"] for m in meta}
            assert tracking_meta["_tracking_number"] == "1Z999AA10123456784"
            assert tracking_meta["_tracking_provider"] == "UPS"

    @pytest.mark.asyncio
    async def test_update_tracking_failure(self, wc_client, wc_credentials):
        """Test update_tracking returns False on API error."""
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=[
                SAMPLE_WC_SYSTEM_STATUS,
                WooCommerceAPIError("500 Internal Server Error"),
            ],
        ):
            await wc_client.authenticate(wc_credentials)
            update = TrackingUpdate(
                order_id="1234",
                tracking_number="1Z999AA10123456784",
                carrier="UPS",
            )
            result = await wc_client.update_tracking(update)

            assert result is False

    @pytest.mark.asyncio
    async def test_update_tracking_not_authenticated(self, wc_client):
        """Test update_tracking raises error when not authenticated."""
        update = TrackingUpdate(
            order_id="1234",
            tracking_number="1Z999AA10123456784",
            carrier="UPS",
        )
        with pytest.raises(WooCommerceAuthError) as exc_info:
            await wc_client.update_tracking(update)

        assert "Not authenticated" in str(exc_info.value)


class TestWooCommerceOrderNormalization:
    """Test WooCommerce order data normalization."""

    @pytest.mark.asyncio
    async def test_normalize_order_handles_missing_shipping(self, wc_client, wc_credentials):
        """Test order normalization handles missing shipping fields."""
        order_data = {
            "id": 9999,
            "number": "9999",
            "status": "pending",
            "date_created": "2026-01-20T14:00:00",
            "billing": {
                "first_name": "Jane",
                "last_name": "Smith",
                "email": "jane@example.com",
            },
            "shipping": {
                "first_name": "",
                "last_name": "",
                "address_1": "456 Oak Ave",
                "city": "Chicago",
                "state": "IL",
                "postcode": "60601",
                "country": "US",
            },
            "line_items": [],
        }

        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=[
                SAMPLE_WC_SYSTEM_STATUS,
                order_data,
            ],
        ):
            await wc_client.authenticate(wc_credentials)
            order = await wc_client.get_order("9999")

            # Should fall back to billing name
            assert order.ship_to_name == "Jane Smith"
            assert order.ship_to_company is None
            assert order.ship_to_address2 is None

    @pytest.mark.asyncio
    async def test_normalize_order_preserves_raw_data(self, wc_client, wc_credentials):
        """Test that raw WooCommerce data is preserved."""
        with patch.object(
            wc_client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=[
                SAMPLE_WC_SYSTEM_STATUS,
                SAMPLE_WC_ORDER,
            ],
        ):
            await wc_client.authenticate(wc_credentials)
            order = await wc_client.get_order("1234")

            assert order.raw_data is not None
            assert order.raw_data["id"] == 1234


class TestWooCommerceHTTPClient:
    """Test WooCommerce HTTP client functionality."""

    @pytest.mark.asyncio
    async def test_make_request_uses_basic_auth(self, wc_client, wc_credentials):
        """Test that requests use HTTP Basic Auth."""

        # Create a mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_WC_SYSTEM_STATUS
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            await wc_client.authenticate(wc_credentials)

            # Verify AsyncClient was called with auth
            call_args = mock_client_class.call_args
            auth = call_args[1]["auth"]
            assert auth == ("ck_test_key_123", "cs_test_secret_456")
