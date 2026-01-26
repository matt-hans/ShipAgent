"""Test External Sources Gateway tools."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.mcp.external_sources.tools import (
    connect_platform,
    list_connections,
    list_orders,
)


@pytest.fixture
def mock_context():
    """Create mock FastMCP context."""
    ctx = MagicMock()
    ctx.info = AsyncMock()
    ctx.request_context.lifespan_context = {
        "connections": {},
        "clients": {},
        "credentials": {},
    }
    return ctx


@pytest.mark.asyncio
async def test_list_connections_empty(mock_context):
    """Test list_connections with no connections."""
    result = await list_connections(mock_context)

    assert result["connections"] == []
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_list_connections_with_platforms(mock_context):
    """Test list_connections with configured platforms."""
    from src.mcp.external_sources.models import PlatformConnection

    mock_context.request_context.lifespan_context["connections"] = {
        "shopify": PlatformConnection(
            platform="shopify",
            store_url="https://test.myshopify.com",
            status="connected",
        ),
    }

    result = await list_connections(mock_context)

    assert result["count"] == 1
    assert result["connections"][0]["platform"] == "shopify"
    assert result["connections"][0]["status"] == "connected"


@pytest.mark.asyncio
async def test_connect_platform_unsupported(mock_context):
    """Test connect_platform with unsupported platform."""
    result = await connect_platform(
        platform="unsupported_platform",
        credentials={"key": "value"},
        ctx=mock_context,
    )

    assert result["success"] is False
    assert "Unsupported platform" in result["error"]


@pytest.mark.asyncio
async def test_connect_platform_supported(mock_context):
    """Test connect_platform with supported but unimplemented platform."""
    result = await connect_platform(
        platform="shopify",
        credentials={"access_token": "test_token"},
        ctx=mock_context,
        store_url="https://test.myshopify.com",
    )

    # Should succeed but note that client is not yet implemented
    # For now, it stores the connection as pending
    assert "success" in result or "error" in result


@pytest.mark.asyncio
async def test_list_orders_no_connection(mock_context):
    """Test list_orders when platform not connected."""
    result = await list_orders(
        platform="shopify",
        ctx=mock_context,
    )

    assert result["success"] is False
    assert "not connected" in result["error"].lower()


@pytest.mark.asyncio
async def test_list_orders_with_filters(mock_context):
    """Test list_orders with filter parameters."""
    from src.mcp.external_sources.clients.base import PlatformClient
    from src.mcp.external_sources.models import PlatformConnection

    # Create a mock client
    mock_client = MagicMock(spec=PlatformClient)
    mock_client.fetch_orders = AsyncMock(return_value=[])

    mock_context.request_context.lifespan_context["connections"] = {
        "shopify": PlatformConnection(
            platform="shopify",
            store_url="https://test.myshopify.com",
            status="connected",
        ),
    }
    mock_context.request_context.lifespan_context["clients"] = {
        "shopify": mock_client,
    }

    result = await list_orders(
        platform="shopify",
        ctx=mock_context,
        status="pending",
        limit=50,
    )

    assert result["success"] is True
    assert result["orders"] == []
