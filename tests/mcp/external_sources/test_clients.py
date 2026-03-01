"""Test platform client interface."""

from abc import ABC

import pytest

from src.mcp.external_sources.clients.base import PlatformClient
from src.mcp.external_sources.models import ExternalOrder, OrderFilters, TrackingUpdate


def test_platform_client_is_abstract():
    """Test that PlatformClient is an abstract base class."""
    assert issubclass(PlatformClient, ABC)

    # Cannot instantiate directly
    with pytest.raises(TypeError):
        PlatformClient()


def test_platform_client_required_methods():
    """Test that PlatformClient defines required abstract methods."""
    required_methods = [
        "platform_name",
        "authenticate",
        "test_connection",
        "fetch_orders",
        "get_order",
        "update_tracking",
    ]

    for method in required_methods:
        assert hasattr(PlatformClient, method)


class MockPlatformClient(PlatformClient):
    """Mock implementation for testing."""

    @property
    def platform_name(self) -> str:
        return "mock"

    async def authenticate(self, credentials: dict) -> bool:
        return True

    async def test_connection(self) -> bool:
        return True

    async def fetch_orders(self, filters: OrderFilters) -> list[ExternalOrder]:
        return []

    async def get_order(self, order_id: str) -> ExternalOrder | None:
        return None

    async def update_tracking(self, update: TrackingUpdate) -> bool:
        return True


def test_concrete_client_can_instantiate():
    """Test that concrete implementation can be instantiated."""
    client = MockPlatformClient()
    assert client.platform_name == "mock"


@pytest.mark.asyncio
async def test_concrete_client_methods():
    """Test that concrete implementation methods work."""
    client = MockPlatformClient()

    assert await client.authenticate({}) is True
    assert await client.test_connection() is True
    assert await client.fetch_orders(OrderFilters()) == []
    assert await client.get_order("123") is None
    assert await client.update_tracking(
        TrackingUpdate(order_id="123", tracking_number="1Z999")
    ) is True


class TestExternalOrderExpansion:
    """Verify new optional fields on ExternalOrder."""

    def _make_minimal_order(self, **kwargs):
        """Build a minimal valid ExternalOrder with overrides."""
        defaults = {
            "platform": "shopify",
            "order_id": "123",
            "status": "open",
            "created_at": "2026-01-01",
            "customer_name": "Test",
            "ship_to_name": "Test",
            "ship_to_address1": "123 Main St",
            "ship_to_city": "New York",
            "ship_to_state": "NY",
            "ship_to_postal_code": "10001",
        }
        defaults.update(kwargs)
        return ExternalOrder(**defaults)

    def test_new_fields_default_to_none(self):
        """New optional fields default to None."""
        order = self._make_minimal_order()
        assert order.customer_tags is None
        assert order.order_note is None
        assert order.risk_level is None
        assert order.shipping_rate_code is None
        assert order.line_item_types is None
        assert order.discount_codes is None
        assert order.customer_order_count is None
        assert order.customer_total_spent is None
        assert order.custom_attributes == {}

    def test_custom_attributes_populated(self):
        """custom_attributes accepts arbitrary dict."""
        order = self._make_minimal_order(
            custom_attributes={"gift_message": "Happy Birthday", "priority": "high"},
        )
        assert order.custom_attributes["gift_message"] == "Happy Birthday"

    def test_backward_compat_without_new_fields(self):
        """ExternalOrder constructed without new fields still works."""
        order = self._make_minimal_order(platform="woocommerce", order_id="456")
        assert order.customer_tags is None
        assert order.order_note is None
        assert order.custom_attributes == {}
