"""Tests that platform routes use gateway_provider and hit real HTTP endpoints.

Uses TestClient (FastAPI) with patched gateway to verify actual route wiring,
not just mock attribute checks.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest


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


class TestShopifyEnvStatusUsesGateway:
    """Verify env-status route validates credentials without mutating state."""

    @patch("src.api.routes.platforms.get_external_sources_client")
    @pytest.mark.asyncio
    async def test_env_status_uses_validate_credentials(self, mock_get):
        """GET /platforms/shopify/env-status should call validate_credentials (read-only)."""
        from fastapi.testclient import TestClient

        from src.api.main import app

        mock_client = AsyncMock()
        mock_client.validate_credentials = AsyncMock(return_value={
            "valid": True,
            "platform": "shopify",
            "shop": {"name": "My Test Store"},
        })
        mock_get.return_value = mock_client

        with patch.dict(os.environ, {
            "SHOPIFY_ACCESS_TOKEN": "shpat_test",
            "SHOPIFY_STORE_DOMAIN": "test.myshopify.com",
        }):
            client = TestClient(app)
            response = client.get("/api/v1/platforms/shopify/env-status")

        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["valid"] is True
        assert data["store_name"] == "My Test Store"
        mock_client.validate_credentials.assert_awaited_once()
        # Ensure connect_platform was NOT called (no state mutation)
        mock_client.connect_platform.assert_not_awaited()

    @patch("src.api.routes.platforms.get_external_sources_client")
    @pytest.mark.asyncio
    async def test_env_status_handles_validation_failure(self, mock_get):
        """env-status should return valid=False when credentials are invalid."""
        from fastapi.testclient import TestClient

        from src.api.main import app

        mock_client = AsyncMock()
        mock_client.validate_credentials = AsyncMock(return_value={
            "valid": False,
            "platform": "shopify",
            "error": "Authentication failed — check credentials.",
        })
        mock_get.return_value = mock_client

        with patch.dict(os.environ, {
            "SHOPIFY_ACCESS_TOKEN": "shpat_bad",
            "SHOPIFY_STORE_DOMAIN": "test.myshopify.com",
        }):
            client = TestClient(app)
            response = client.get("/api/v1/platforms/shopify/env-status")

        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["valid"] is False
        assert "Authentication failed" in data["error"]

    @patch("src.api.routes.platforms.get_external_sources_client")
    @pytest.mark.asyncio
    async def test_env_status_no_shop_metadata(self, mock_get):
        """env-status should handle missing shop metadata gracefully."""
        from fastapi.testclient import TestClient

        from src.api.main import app

        mock_client = AsyncMock()
        mock_client.validate_credentials = AsyncMock(return_value={
            "valid": True,
            "platform": "shopify",
            "shop": None,
        })
        mock_get.return_value = mock_client

        with patch.dict(os.environ, {
            "SHOPIFY_ACCESS_TOKEN": "shpat_test",
            "SHOPIFY_STORE_DOMAIN": "test.myshopify.com",
        }):
            client = TestClient(app)
            response = client.get("/api/v1/platforms/shopify/env-status")

        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["valid"] is True
        assert data["store_name"] is None  # Graceful degradation

    def test_env_status_without_credentials(self):
        """env-status should return configured=False when env vars are missing."""
        from fastapi.testclient import TestClient

        from src.api.main import app

        with patch(
            "src.services.runtime_credentials.resolve_shopify_credentials",
            return_value=None,
        ):
            client = TestClient(app)
            response = client.get("/api/v1/platforms/shopify/env-status")

        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is False


class TestAmazonActivationRoute:
    """Verify Amazon compatibility activation endpoint wiring."""

    @patch("src.services.amazon_activation_service.activate_amazon_as_data_source")
    def test_amazon_activate_route_success(self, mock_activate):
        """POST /platforms/amazon/activate returns normalized success payload."""
        from fastapi.testclient import TestClient

        from src.api.main import app

        mock_activate.return_value = {
            "row_count": 7,
            "source_type": "amazon",
            "columns": [{"name": "order_id", "type": "VARCHAR"}],
        }

        client = TestClient(app)
        response = client.post("/api/v1/platforms/amazon/activate")

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["row_count"] == 7
        assert payload["source_type"] == "amazon"

    @patch("src.services.amazon_activation_service.activate_amazon_as_data_source")
    def test_amazon_activate_route_failure(self, mock_activate):
        """POST /platforms/amazon/activate surfaces activation failure cleanly."""
        from fastapi.testclient import TestClient

        from src.api.main import app

        mock_activate.side_effect = Exception("amazon auth failed")

        client = TestClient(app)
        response = client.post("/api/v1/platforms/amazon/activate")

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is False
        assert "amazon auth failed" in payload["error"].lower()


class TestAmazonEnvStatus:
    """Tests for GET /platforms/amazon/env-status."""

    @patch("src.api.routes.platforms.resolve_amazon_credentials")
    def test_env_status_not_configured(self, mock_resolve):
        """Returns configured=False when no credentials found."""
        from fastapi.testclient import TestClient

        from src.api.main import app

        mock_resolve.return_value = None

        client = TestClient(app)
        response = client.get("/api/v1/platforms/amazon/env-status")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is False
        assert data["valid"] is False

    @patch("src.api.routes.platforms.get_external_sources_client")
    @patch("src.api.routes.platforms.resolve_amazon_credentials")
    @pytest.mark.asyncio
    async def test_env_status_configured_and_valid(self, mock_resolve, mock_get_ext):
        """Returns configured=True, valid=True when credentials work."""
        from fastapi.testclient import TestClient

        from src.api.main import app
        from src.services.connection_types import AmazonSPAPICredentials

        mock_resolve.return_value = AmazonSPAPICredentials(
            client_id="test-id",
            client_secret="test-secret",
            refresh_token="test-token",
            marketplace_id="ATVPDKIKX0DER",
            sandbox=False,
        )

        mock_ext = AsyncMock()
        mock_ext.validate_credentials = AsyncMock(return_value={
            "valid": True,
            "platform": "amazon",
            "shop": {"name": "Amazon.com", "marketplace_id": "ATVPDKIKX0DER"},
        })
        mock_get_ext.return_value = mock_ext

        client = TestClient(app)
        response = client.get("/api/v1/platforms/amazon/env-status")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["valid"] is True
        assert data["seller_name"] == "Amazon.com"
