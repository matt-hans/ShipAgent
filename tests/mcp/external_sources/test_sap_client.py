"""Test SAP platform client implementation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from src.mcp.external_sources.clients.sap import SAPClient
from src.mcp.external_sources.models import (
    ExternalOrder,
    OrderFilters,
    TrackingUpdate,
)


@pytest.fixture
def sap_credentials():
    """Valid SAP credentials for testing."""
    return {
        "base_url": "https://sap.example.com/sap/opu/odata/sap/API_SALES_ORDER_SRV",
        "username": "testuser",
        "password": "testpass",
        "client": "100",
    }


@pytest.fixture
def sap_client():
    """Create a SAPClient instance for testing."""
    return SAPClient()


@pytest.fixture
def sample_sap_order():
    """Sample SAP sales order response."""
    return {
        "d": {
            "SalesOrder": "0000001234",
            "SalesOrderType": "OR",
            "SoldToParty": "CUST001",
            "CustomerName": "John Smith",
            "CustomerEmail": "john@example.com",
            "CreationDate": "/Date(1706227200000)/",
            "OverallSDProcessStatus": "A",
            "ShipToName": "John Smith",
            "ShipToStreet": "123 Main St",
            "ShipToStreet2": "Apt 4",
            "ShipToCity": "Springfield",
            "ShipToRegion": "IL",
            "ShipToPostalCode": "62701",
            "ShipToCountry": "US",
            "ShipToPhone": "555-1234",
            "to_Item": {
                "results": [
                    {
                        "Material": "MAT001",
                        "OrderQuantity": "2",
                        "NetAmount": "50.00",
                    }
                ]
            },
        }
    }


@pytest.fixture
def sample_sap_orders_list():
    """Sample SAP orders list response."""
    return {
        "d": {
            "results": [
                {
                    "SalesOrder": "0000001234",
                    "SalesOrderType": "OR",
                    "SoldToParty": "CUST001",
                    "CustomerName": "John Smith",
                    "CustomerEmail": "john@example.com",
                    "CreationDate": "/Date(1706227200000)/",
                    "OverallSDProcessStatus": "A",
                    "ShipToName": "John Smith",
                    "ShipToStreet": "123 Main St",
                    "ShipToStreet2": None,
                    "ShipToCity": "Springfield",
                    "ShipToRegion": "IL",
                    "ShipToPostalCode": "62701",
                    "ShipToCountry": "US",
                    "ShipToPhone": "555-1234",
                    "to_Item": {"results": []},
                },
                {
                    "SalesOrder": "0000001235",
                    "SalesOrderType": "OR",
                    "SoldToParty": "CUST002",
                    "CustomerName": "Jane Doe",
                    "CustomerEmail": "jane@example.com",
                    "CreationDate": "/Date(1706313600000)/",
                    "OverallSDProcessStatus": "B",
                    "ShipToName": "Jane Doe",
                    "ShipToStreet": "456 Oak Ave",
                    "ShipToStreet2": None,
                    "ShipToCity": "Chicago",
                    "ShipToRegion": "IL",
                    "ShipToPostalCode": "60601",
                    "ShipToCountry": "US",
                    "ShipToPhone": None,
                    "to_Item": {"results": []},
                },
            ]
        }
    }


class TestSAPClientProperties:
    """Test SAPClient basic properties."""

    def test_platform_name(self, sap_client):
        """Test that platform_name returns 'sap'."""
        assert sap_client.platform_name == "sap"

    def test_initial_state(self, sap_client):
        """Test client initial state before authentication."""
        assert sap_client._client is None
        assert sap_client._base_url is None
        assert sap_client._authenticated is False


class TestSAPClientAuthentication:
    """Test SAPClient authentication."""

    @pytest.mark.asyncio
    async def test_authenticate_success(self, sap_client, sap_credentials):
        """Test successful authentication with valid credentials."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '<?xml version="1.0"?><edmx:Edmx />'

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

            # Patch the client creation in authenticate
            with patch.object(sap_client, "_create_client") as mock_create:
                mock_create.return_value = mock_client
                result = await sap_client.authenticate(sap_credentials)

        assert result is True
        assert sap_client._authenticated is True
        assert sap_client._base_url == sap_credentials["base_url"]

    @pytest.mark.asyncio
    async def test_authenticate_missing_credentials(self, sap_client):
        """Test authentication fails with missing credentials."""
        incomplete_creds = {"base_url": "https://sap.example.com"}

        with pytest.raises(ValueError, match="Missing required credentials"):
            await sap_client.authenticate(incomplete_creds)

    @pytest.mark.asyncio
    async def test_authenticate_connection_failure(self, sap_client, sap_credentials):
        """Test authentication fails when connection fails."""
        with patch.object(sap_client, "_create_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_create.return_value = mock_client

            result = await sap_client.authenticate(sap_credentials)

        assert result is False
        assert sap_client._authenticated is False

    @pytest.mark.asyncio
    async def test_authenticate_invalid_credentials(self, sap_client, sap_credentials):
        """Test authentication fails with invalid credentials (401)."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch.object(sap_client, "_create_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_create.return_value = mock_client

            result = await sap_client.authenticate(sap_credentials)

        assert result is False
        assert sap_client._authenticated is False


class TestSAPClientTestConnection:
    """Test SAPClient test_connection method."""

    @pytest.mark.asyncio
    async def test_connection_success(self, sap_client, sap_credentials):
        """Test successful connection test."""
        # First authenticate
        sap_client._authenticated = True
        sap_client._base_url = sap_credentials["base_url"]

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        sap_client._client = mock_client

        result = await sap_client.test_connection()

        assert result is True
        mock_client.get.assert_called_once_with("/$metadata")

    @pytest.mark.asyncio
    async def test_connection_not_authenticated(self, sap_client):
        """Test connection test fails when not authenticated."""
        result = await sap_client.test_connection()
        assert result is False

    @pytest.mark.asyncio
    async def test_connection_failure(self, sap_client, sap_credentials):
        """Test connection test fails when server unreachable."""
        sap_client._authenticated = True
        sap_client._base_url = sap_credentials["base_url"]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))
        sap_client._client = mock_client

        result = await sap_client.test_connection()

        assert result is False


class TestSAPClientFetchOrders:
    """Test SAPClient fetch_orders method."""

    @pytest.mark.asyncio
    async def test_fetch_orders_success(
        self, sap_client, sap_credentials, sample_sap_orders_list
    ):
        """Test successful order fetch."""
        sap_client._authenticated = True
        sap_client._base_url = sap_credentials["base_url"]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_sap_orders_list

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        sap_client._client = mock_client

        filters = OrderFilters(limit=10, offset=0)
        orders = await sap_client.fetch_orders(filters)

        assert len(orders) == 2
        assert all(isinstance(o, ExternalOrder) for o in orders)
        assert orders[0].order_id == "0000001234"
        assert orders[0].platform == "sap"
        assert orders[1].order_id == "0000001235"

    @pytest.mark.asyncio
    async def test_fetch_orders_with_filters(self, sap_client, sap_credentials):
        """Test order fetch with date and status filters."""
        sap_client._authenticated = True
        sap_client._base_url = sap_credentials["base_url"]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"d": {"results": []}}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        sap_client._client = mock_client

        filters = OrderFilters(
            status="A",
            date_from="2024-01-01",
            date_to="2024-01-31",
            limit=50,
            offset=10,
        )
        await sap_client.fetch_orders(filters)

        # Verify OData query parameters were used
        call_args = mock_client.get.call_args
        assert call_args is not None
        url = call_args[0][0]
        params = call_args[1].get("params", {})

        assert "/SalesOrderSet" in url
        assert params.get("$format") == "json"
        assert params.get("$top") == 50
        assert params.get("$skip") == 10
        # Filter should include status and date conditions
        assert "$filter" in params

    @pytest.mark.asyncio
    async def test_fetch_orders_not_authenticated(self, sap_client):
        """Test fetch_orders fails when not authenticated."""
        filters = OrderFilters()

        with pytest.raises(RuntimeError, match="Not authenticated"):
            await sap_client.fetch_orders(filters)


class TestSAPClientGetOrder:
    """Test SAPClient get_order method."""

    @pytest.mark.asyncio
    async def test_get_order_success(
        self, sap_client, sap_credentials, sample_sap_order
    ):
        """Test successful single order fetch."""
        sap_client._authenticated = True
        sap_client._base_url = sap_credentials["base_url"]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_sap_order

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        sap_client._client = mock_client

        order = await sap_client.get_order("0000001234")

        assert order is not None
        assert order.order_id == "0000001234"
        assert order.platform == "sap"
        assert order.customer_name == "John Smith"
        assert order.ship_to_city == "Springfield"

        # Verify correct OData URL was called
        call_args = mock_client.get.call_args
        url = call_args[0][0]
        assert "/SalesOrderSet('0000001234')" in url

    @pytest.mark.asyncio
    async def test_get_order_not_found(self, sap_client, sap_credentials):
        """Test get_order returns None for non-existent order."""
        sap_client._authenticated = True
        sap_client._base_url = sap_credentials["base_url"]

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        sap_client._client = mock_client

        order = await sap_client.get_order("9999999999")

        assert order is None

    @pytest.mark.asyncio
    async def test_get_order_not_authenticated(self, sap_client):
        """Test get_order fails when not authenticated."""
        with pytest.raises(RuntimeError, match="Not authenticated"):
            await sap_client.get_order("0000001234")


class TestSAPClientUpdateTracking:
    """Test SAPClient update_tracking method."""

    @pytest.mark.asyncio
    async def test_update_tracking_success(self, sap_client, sap_credentials):
        """Test successful tracking update with CSRF token."""
        sap_client._authenticated = True
        sap_client._base_url = sap_credentials["base_url"]

        # Mock CSRF token fetch
        csrf_response = MagicMock()
        csrf_response.status_code = 200
        csrf_response.headers = {"x-csrf-token": "test-csrf-token"}

        # Mock PATCH response
        patch_response = MagicMock()
        patch_response.status_code = 204

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=csrf_response)
        mock_client.patch = AsyncMock(return_value=patch_response)
        sap_client._client = mock_client

        update = TrackingUpdate(
            order_id="0000001234",
            tracking_number="1Z999AA10123456784",
            carrier="UPS",
            tracking_url="https://ups.com/track/1Z999AA10123456784",
        )

        result = await sap_client.update_tracking(update)

        assert result is True

        # Verify CSRF token was fetched
        get_calls = mock_client.get.call_args_list
        assert any("x-csrf-token" in str(call) for call in get_calls) or len(get_calls) > 0

        # Verify PATCH was called with tracking data
        mock_client.patch.assert_called_once()
        patch_call = mock_client.patch.call_args
        assert "DeliverySet" in patch_call[0][0]

    @pytest.mark.asyncio
    async def test_update_tracking_csrf_failure(self, sap_client, sap_credentials):
        """Test tracking update fails when CSRF token fetch fails."""
        sap_client._authenticated = True
        sap_client._base_url = sap_credentials["base_url"]

        # Mock CSRF token fetch failure
        csrf_response = MagicMock()
        csrf_response.status_code = 403

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=csrf_response)
        sap_client._client = mock_client

        update = TrackingUpdate(
            order_id="0000001234",
            tracking_number="1Z999AA10123456784",
            carrier="UPS",
        )

        result = await sap_client.update_tracking(update)

        assert result is False

    @pytest.mark.asyncio
    async def test_update_tracking_not_authenticated(self, sap_client):
        """Test update_tracking fails when not authenticated."""
        update = TrackingUpdate(
            order_id="0000001234",
            tracking_number="1Z999AA10123456784",
            carrier="UPS",
        )

        with pytest.raises(RuntimeError, match="Not authenticated"):
            await sap_client.update_tracking(update)


class TestSAPClientODataHelpers:
    """Test SAP OData helper methods."""

    def test_parse_sap_date(self, sap_client):
        """Test parsing SAP OData date format."""
        # SAP OData date format: /Date(milliseconds)/
        sap_date = "/Date(1706227200000)/"
        result = sap_client._parse_sap_date(sap_date)
        assert result == "2024-01-26T00:00:00+00:00"

    def test_parse_sap_date_invalid(self, sap_client):
        """Test parsing invalid date returns empty string."""
        result = sap_client._parse_sap_date("invalid")
        assert result == ""

    def test_build_odata_filter(self, sap_client):
        """Test OData filter construction."""
        filters = OrderFilters(
            status="A",
            date_from="2024-01-01",
            date_to="2024-01-31",
        )
        result = sap_client._build_odata_filter(filters)

        assert "OverallSDProcessStatus eq 'A'" in result
        assert "CreationDate ge datetime" in result
        assert "CreationDate le datetime" in result

    def test_build_odata_filter_empty(self, sap_client):
        """Test OData filter with no filters returns empty string."""
        filters = OrderFilters()
        result = sap_client._build_odata_filter(filters)
        assert result == ""


class TestSAPClientCleanup:
    """Test SAPClient cleanup and resource management."""

    @pytest.mark.asyncio
    async def test_close(self, sap_client):
        """Test client cleanup."""
        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()
        sap_client._client = mock_client
        sap_client._authenticated = True

        await sap_client.close()

        mock_client.aclose.assert_called_once()
        assert sap_client._client is None
        assert sap_client._authenticated is False

    @pytest.mark.asyncio
    async def test_context_manager(self, sap_client, sap_credentials):
        """Test client can be used as async context manager."""
        with patch.object(sap_client, "authenticate", new_callable=AsyncMock) as mock_auth:
            with patch.object(sap_client, "close", new_callable=AsyncMock) as mock_close:
                mock_auth.return_value = True

                async with sap_client as client:
                    await client.authenticate(sap_credentials)
                    assert client is sap_client

                mock_close.assert_called_once()
