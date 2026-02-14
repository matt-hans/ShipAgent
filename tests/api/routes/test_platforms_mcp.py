"""Tests that platform routes use gateway_provider and hit real HTTP endpoints.

Uses TestClient (FastAPI) with patched gateway to verify actual route wiring,
not just mock attribute checks.
"""

import pytest
from unittest.mock import AsyncMock, patch


class TestPlatformRoutesUseGateway:
    """Verify routes delegate to gateway_provider, not local client."""

    def test_platform_state_manager_removed(self):
        """PlatformStateManager and local _ext_client must not exist."""
        import src.api.routes.platforms as platforms_mod

        assert not hasattr(platforms_mod, "PlatformStateManager"), \
            "PlatformStateManager should be removed — routes must use gateway_provider"
        assert not hasattr(platforms_mod, "_ext_client"), \
            "No local singleton — gateway_provider owns the client"
        assert not hasattr(platforms_mod, "_state_manager"), \
            "No _state_manager — gateway_provider owns the client"

    @patch("src.api.routes.platforms.get_external_sources_client")
    @pytest.mark.asyncio
    async def test_connect_route_calls_gateway(self, mock_get):
        """POST /platforms/{platform}/connect hits gateway, not local client."""
        from fastapi.testclient import TestClient
        from src.api.main import app

        mock_client = AsyncMock()
        mock_client.connect_platform = AsyncMock(return_value={
            "success": True, "platform": "shopify", "status": "connected"
        })
        mock_get.return_value = mock_client

        client = TestClient(app)
        response = client.post(
            "/api/v1/platforms/shopify/connect",
            json={
                "credentials": {"access_token": "shpat_xxx"},
                "store_url": "test.myshopify.com",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        mock_client.connect_platform.assert_called_once()

    @patch("src.api.routes.platforms.get_external_sources_client")
    @pytest.mark.asyncio
    async def test_disconnect_route_calls_gateway(self, mock_get):
        """POST /platforms/{platform}/disconnect hits gateway, not local client."""
        from fastapi.testclient import TestClient
        from src.api.main import app

        mock_client = AsyncMock()
        mock_client.disconnect_platform = AsyncMock(return_value={
            "success": True, "platform": "shopify", "status": "disconnected"
        })
        mock_get.return_value = mock_client

        client = TestClient(app)
        response = client.post("/api/v1/platforms/shopify/disconnect")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disconnected"
        mock_client.disconnect_platform.assert_called_once_with("shopify")

    @patch("src.api.routes.platforms.get_external_sources_client")
    @pytest.mark.asyncio
    async def test_list_connections_calls_gateway(self, mock_get):
        """GET /platforms/connections hits gateway."""
        from fastapi.testclient import TestClient
        from src.api.main import app

        mock_client = AsyncMock()
        mock_client.list_connections = AsyncMock(return_value={
            "connections": [], "count": 0
        })
        mock_get.return_value = mock_client

        client = TestClient(app)
        response = client.get("/api/v1/platforms/connections")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0

    @patch("src.api.routes.platforms.get_external_sources_client")
    @pytest.mark.asyncio
    async def test_list_orders_calls_gateway(self, mock_get):
        """GET /platforms/{platform}/orders hits gateway."""
        from fastapi.testclient import TestClient
        from src.api.main import app

        mock_client = AsyncMock()
        mock_client.fetch_orders = AsyncMock(return_value={
            "success": True,
            "platform": "shopify",
            "orders": [{
                "order_id": "1",
                "platform": "shopify",
                "status": "unfulfilled",
                "created_at": "2026-01-01T00:00:00Z",
                "customer_name": "Alice Smith",
                "ship_to_name": "Alice Smith",
                "ship_to_address1": "123 Main St",
                "ship_to_city": "Springfield",
                "ship_to_state": "IL",
                "ship_to_postal_code": "62701",
            }],
            "count": 1,
        })
        mock_get.return_value = mock_client

        client = TestClient(app)
        response = client.get("/api/v1/platforms/shopify/orders")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
