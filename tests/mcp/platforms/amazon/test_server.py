# tests/mcp/platforms/amazon/test_server.py
"""Amazon platform MCP server contract compliance tests.

Tests all 7 required contract tools exist and return the expected shapes.
Since Amazon makes real HTTP calls, we mock httpx at the transport
layer and only verify contract compliance, not actual API behaviour.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Sample Amazon order data
# ---------------------------------------------------------------------------

SAMPLE_ORDER = {
    "AmazonOrderId": "111-2222222-3333333",
    "OrderStatus": "Unshipped",
    "PaymentMethod": "Other",
    "FulfillmentChannel": "MFN",
    "PurchaseDate": "2026-02-20T10:00:00Z",
    "LastUpdateDate": "2026-02-20T10:05:00Z",
    "ShippingAddress": {
        "Name": "Jane Doe",
        "AddressLine1": "123 Main St",
        "AddressLine2": "Suite 4",
        "City": "Austin",
        "StateOrRegion": "TX",
        "PostalCode": "78701",
        "CountryCode": "US",
        "Phone": "512-555-0100",
    },
    "OrderTotal": {"Amount": "49.99", "CurrencyCode": "USD"},
    "BuyerInfo": {"BuyerEmail": "jane@example.com", "BuyerName": "Jane Doe"},
    "NumberOfItemsShipped": 0,
    "NumberOfItemsUnshipped": 3,
    "ShipmentServiceLevelCategory": "Standard",
    "EarliestShipDate": "2026-02-21T00:00:00Z",
    "LatestShipDate": "2026-02-23T00:00:00Z",
    "IsBusinessOrder": False,
    "IsPrime": True,
    "MarketplaceId": "ATVPDKIKX0DER",
}

SAMPLE_ORDER_2 = {
    "AmazonOrderId": "111-4444444-5555555",
    "OrderStatus": "Shipped",
    "PaymentMethod": "Other",
    "FulfillmentChannel": "AFN",
    "PurchaseDate": "2026-02-21T10:00:00Z",
    "LastUpdateDate": "2026-02-21T10:05:00Z",
    "ShippingAddress": {
        "Name": "Bob Smith",
        "AddressLine1": "200 Second Ave",
        "City": "Dallas",
        "StateOrRegion": "TX",
        "PostalCode": "75201",
        "CountryCode": "US",
    },
    "OrderTotal": {"Amount": "29.99", "CurrencyCode": "USD"},
    "BuyerInfo": {"BuyerEmail": "bob@example.com", "BuyerName": "Bob Smith"},
    "NumberOfItemsShipped": 2,
    "NumberOfItemsUnshipped": 0,
    "ShipmentServiceLevelCategory": "Expedited",
    "IsBusinessOrder": True,
    "IsPrime": False,
    "MarketplaceId": "ATVPDKIKX0DER",
}


# ---------------------------------------------------------------------------
# Contract compliance tests
# ---------------------------------------------------------------------------


class TestAmazonServerContract:
    """Verify the Amazon MCP server implements the required tool contract."""

    @pytest.mark.asyncio
    async def test_server_exposes_required_tools(self):
        """Verify tool registration via the public list_tools() MCP method."""
        from src.mcp.platforms.amazon.server import mcp

        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        required = {
            "platform.health",
            "platform.capabilities",
            "auth.connect",
            "auth.disconnect",
            "orders.list",
            "orders.get",
            "tracking.write_back",
        }
        assert required.issubset(tool_names), f"Missing tools: {required - tool_names}"

    @pytest.mark.asyncio
    async def test_health_not_connected_returns_required_shape(self):
        """Health response must match contract shape when not connected."""
        import src.mcp.platforms.amazon.server as srv

        # Ensure disconnected state
        srv._client = None
        srv._credentials = None

        result = await srv.health()
        assert result["ok"] is False
        assert result["platform_id"] == "amazon"
        assert result["contract_version"] == "1.0"
        assert "api_reachable" in result
        assert "auth_valid" in result
        assert result["auth_valid"] is False

    @pytest.mark.asyncio
    async def test_health_connected_returns_ok(self):
        """Health response returns ok=True when connected and API is reachable."""
        import src.mcp.platforms.amazon.server as srv
        from src.mcp.platforms.amazon.client import AmazonClient
        from src.mcp.platforms.amazon.models import AmazonCredentials

        creds = AmazonCredentials(
            client_id="test_id",
            client_secret="test_secret",
            refresh_token="test_refresh",
        )
        client = AmazonClient(creds)
        client.test_connection = AsyncMock(return_value={"payload": []})

        srv._client = client
        srv._credentials = creds
        try:
            result = await srv.health()
            assert result["ok"] is True
            assert result["api_reachable"] is True
            assert result["auth_valid"] is True
        finally:
            srv._client = None
            srv._credentials = None

    @pytest.mark.asyncio
    async def test_capabilities_returns_required_shape(self):
        """Capabilities response must match contract shape."""
        from src.mcp.platforms.amazon.server import capabilities

        result = await capabilities()
        assert result["platform_id"] == "amazon"
        assert result["contract_version"] == "1.0"
        assert "supports" in result
        assert "limits" in result
        assert "paging" in result
        assert "orders.list" in result["supports"]
        assert result["paging"]["strategy"] == "cursor"

    @pytest.mark.asyncio
    async def test_auth_connect_success(self):
        """auth.connect returns connected=True on successful connection."""
        import src.mcp.platforms.amazon.server as srv

        srv._client = None
        srv._credentials = None

        with patch.object(
            srv,
            "_client",
            None,
        ):
            with patch(
                "src.mcp.platforms.amazon.client.AmazonClient.test_connection",
                new_callable=AsyncMock,
                return_value={"payload": []},
            ), patch(
                "src.mcp.platforms.amazon.client.AmazonClient._get_access_token",
                new_callable=AsyncMock,
                return_value="mock_token",
            ):
                result = await srv.auth_connect(
                    credential_ref="test",
                    client_id="test_id",
                    client_secret="test_secret",
                    refresh_token="test_refresh",
                    marketplace_id="ATVPDKIKX0DER",
                )

                assert result["connected"] is True
                assert result["auth_valid"] is True
                assert result["account_id"] == "ATVPDKIKX0DER"

        # Cleanup
        srv._client = None
        srv._credentials = None

    @pytest.mark.asyncio
    async def test_auth_disconnect(self):
        """auth.disconnect clears state and returns disconnected=True."""
        import src.mcp.platforms.amazon.server as srv

        srv._client = MagicMock()
        srv._credentials = MagicMock()

        result = await srv.auth_disconnect()
        assert result["disconnected"] is True
        assert srv._client is None
        assert srv._credentials is None

    @pytest.mark.asyncio
    async def test_orders_list_not_connected(self):
        """orders.list returns AUTH_REQUIRED when not connected."""
        import src.mcp.platforms.amazon.server as srv

        srv._client = None
        result = await srv.orders_list()
        assert result["error_code"] == "AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_orders_list_returns_contract_shape(self):
        """orders.list returns items, next_cursor, and watermark."""
        import src.mcp.platforms.amazon.server as srv
        from src.mcp.platforms.amazon.client import AmazonClient
        from src.mcp.platforms.amazon.models import AmazonCredentials

        creds = AmazonCredentials(
            client_id="test_id",
            client_secret="test_secret",
            refresh_token="test_refresh",
        )
        client = AmazonClient(creds)
        client.fetch_orders_page = AsyncMock(return_value={
            "items": [SAMPLE_ORDER, SAMPLE_ORDER_2],
            "next_cursor": "abc123NextToken",
            "watermark": "2026-02-21T10:05:00Z",
        })

        srv._client = client
        srv._credentials = creds
        try:
            result = await srv.orders_list()
            assert "items" in result
            assert "next_cursor" in result
            assert "watermark" in result
            assert len(result["items"]) == 2
        finally:
            srv._client = None
            srv._credentials = None

    @pytest.mark.asyncio
    async def test_orders_get_not_connected(self):
        """orders.get returns AUTH_REQUIRED when not connected."""
        import src.mcp.platforms.amazon.server as srv

        srv._client = None
        result = await srv.orders_get(order_id="111-2222222-3333333")
        assert result["error_code"] == "AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_orders_get_returns_order(self):
        """orders.get returns an order dict on success."""
        import src.mcp.platforms.amazon.server as srv
        from src.mcp.platforms.amazon.client import AmazonClient
        from src.mcp.platforms.amazon.models import AmazonCredentials

        creds = AmazonCredentials(
            client_id="test_id",
            client_secret="test_secret",
            refresh_token="test_refresh",
        )
        client = AmazonClient(creds)
        client.get_order = AsyncMock(return_value=SAMPLE_ORDER)

        srv._client = client
        srv._credentials = creds
        try:
            result = await srv.orders_get(order_id="111-2222222-3333333")
            assert "order" in result
            assert result["order"]["AmazonOrderId"] == "111-2222222-3333333"
        finally:
            srv._client = None
            srv._credentials = None

    @pytest.mark.asyncio
    async def test_orders_get_not_found(self):
        """orders.get returns NOT_FOUND for unknown ID."""
        import src.mcp.platforms.amazon.server as srv
        from src.mcp.platforms.amazon.client import AmazonClient
        from src.mcp.platforms.amazon.models import AmazonCredentials

        creds = AmazonCredentials(
            client_id="test_id",
            client_secret="test_secret",
            refresh_token="test_refresh",
        )
        client = AmazonClient(creds)
        client.get_order = AsyncMock(return_value=None)

        srv._client = client
        srv._credentials = creds
        try:
            result = await srv.orders_get(order_id="999-0000000-0000000")
            assert result["error_code"] == "NOT_FOUND"
        finally:
            srv._client = None
            srv._credentials = None

    @pytest.mark.asyncio
    async def test_tracking_write_back_not_connected(self):
        """tracking.write_back returns AUTH_REQUIRED when not connected."""
        import src.mcp.platforms.amazon.server as srv

        srv._client = None
        result = await srv.tracking_write_back(
            order_id="111-2222222-3333333",
            tracking_numbers=["1Z999AA10123456784"],
        )
        assert result["error_code"] == "AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_tracking_write_back_success(self):
        """tracking.write_back returns success on update."""
        import src.mcp.platforms.amazon.server as srv
        from src.mcp.platforms.amazon.client import AmazonClient
        from src.mcp.platforms.amazon.models import AmazonCredentials

        creds = AmazonCredentials(
            client_id="test_id",
            client_secret="test_secret",
            refresh_token="test_refresh",
        )
        client = AmazonClient(creds)
        client.write_back_tracking = AsyncMock(return_value={"success": True})

        srv._client = client
        srv._credentials = creds
        try:
            result = await srv.tracking_write_back(
                order_id="111-2222222-3333333",
                tracking_numbers=["1Z999AA10123456784"],
                carrier="UPS",
            )
            assert result["success"] is True
        finally:
            srv._client = None
            srv._credentials = None

    @pytest.mark.asyncio
    async def test_contract_versions_match(self):
        """Contract version must be consistent across health and capabilities."""
        import src.mcp.platforms.amazon.server as srv

        # Ensure disconnected state for health (still returns contract version)
        srv._client = None
        srv._credentials = None

        h = await srv.health()
        c = await srv.capabilities()
        assert h["contract_version"] == c["contract_version"]
