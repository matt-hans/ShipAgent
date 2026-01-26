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
