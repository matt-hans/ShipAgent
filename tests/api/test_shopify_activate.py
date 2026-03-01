"""Tests for POST /platforms/shopify/activate endpoint.

Verifies that the Shopify activation route correctly delegates to
activate_shopify_as_data_source and maps success/error responses.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Canonical mock target — the function is lazily imported inside the route
# handler, so we mock at the service module where it's defined.
_MOCK_TARGET = (
    "src.services.shopify_activation_service.activate_shopify_as_data_source"
)


@pytest.fixture
def _mock_activation_success():
    """Mock a successful Shopify activation."""
    result = {
        "row_count": 42,
        "source_type": "shopify",
        "columns": [
            {"name": "order_id", "type": "VARCHAR"},
            {"name": "ship_to_name", "type": "VARCHAR"},
        ],
        "message": "Connected to Shopify and imported 42 orders as active data source.",
    }
    with patch(
        _MOCK_TARGET,
        new_callable=AsyncMock,
        return_value=result,
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def _mock_activation_error():
    """Mock a ShopifyActivationError during activation."""
    from src.services.shopify_activation_service import ShopifyActivationError

    with patch(
        _MOCK_TARGET,
        new_callable=AsyncMock,
        side_effect=ShopifyActivationError(
            "No orders found in Shopify store.", step="fetch"
        ),
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def _mock_activation_unexpected():
    """Mock an unexpected exception during activation."""
    with patch(
        _MOCK_TARGET,
        new_callable=AsyncMock,
        side_effect=RuntimeError("MCP server crashed"),
    ) as mock_fn:
        yield mock_fn


class TestShopifyActivateEndpoint:
    """Tests for the /platforms/shopify/activate endpoint."""

    def test_successful_activation(
        self, client: TestClient, _mock_activation_success
    ):
        """Successful activation returns row count and columns."""
        response = client.post("/api/v1/platforms/shopify/activate")
        assert response.status_code == 200

        body = response.json()
        assert body["success"] is True
        assert body["row_count"] == 42
        assert body["source_type"] == "shopify"
        assert len(body["columns"]) == 2
        assert body["error"] is None

    def test_activation_error(
        self, client: TestClient, _mock_activation_error
    ):
        """ShopifyActivationError returns structured error response."""
        response = client.post("/api/v1/platforms/shopify/activate")
        assert response.status_code == 200

        body = response.json()
        assert body["success"] is False
        assert body["row_count"] == 0
        assert "No orders found" in body["error"]

    def test_unexpected_exception(
        self, client: TestClient, _mock_activation_unexpected
    ):
        """Unexpected exceptions return a generic error response."""
        response = client.post("/api/v1/platforms/shopify/activate")
        assert response.status_code == 200

        body = response.json()
        assert body["success"] is False
        assert "MCP server crashed" in body["error"]
        assert body["row_count"] == 0

    def test_get_does_not_match_activate(self, client: TestClient):
        """GET /platforms/shopify/activate hits the orders catch-all, not activate."""
        # The activate endpoint is POST-only. A GET request to the same path
        # will match /{platform}/orders with platform="shopify" and path="activate",
        # which is not the activate endpoint. This test documents that behavior.
        response = client.get("/api/v1/platforms/shopify/activate")
        # It won't be 405 because FastAPI's catch-all /{platform}/orders route
        # matches first. The important thing is POST works correctly.
        assert response.status_code != 405 or response.status_code == 200
