"""Tests for ExternalSourcesMCPClient.

Verifies the process-global MCP client correctly delegates to
the underlying MCPClient for each platform operation.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.external_sources_mcp_client import ExternalSourcesMCPClient


@pytest.fixture
def client_with_mock_mcp():
    """Create ExternalSourcesMCPClient with a mocked MCPClient."""
    client = ExternalSourcesMCPClient.__new__(ExternalSourcesMCPClient)
    client._mcp = MagicMock()
    client._mcp.call_tool = AsyncMock()
    client._mcp.is_connected = True
    return client


@pytest.mark.asyncio
async def test_connect_calls_mcp_tool(client_with_mock_mcp):
    """connect_platform should call MCP connect_platform tool."""
    client_with_mock_mcp._mcp.call_tool.return_value = {
        "success": True,
        "platform": "shopify",
        "status": "connected",
    }

    result = await client_with_mock_mcp.connect_platform(
        platform="shopify",
        credentials={"access_token": "test"},
        store_url="https://test.myshopify.com",
    )

    assert result["success"] is True
    client_with_mock_mcp._mcp.call_tool.assert_called_once_with(
        "connect_platform",
        {
            "platform": "shopify",
            "credentials": {"access_token": "test"},
            "store_url": "https://test.myshopify.com",
        },
    )


@pytest.mark.asyncio
async def test_disconnect_platform(client_with_mock_mcp):
    """disconnect_platform should call MCP disconnect_platform tool."""
    client_with_mock_mcp._mcp.call_tool.return_value = {
        "success": True,
        "platform": "shopify",
        "status": "disconnected",
    }

    result = await client_with_mock_mcp.disconnect_platform("shopify")
    assert result["success"] is True
    client_with_mock_mcp._mcp.call_tool.assert_called_once_with(
        "disconnect_platform", {"platform": "shopify"}
    )


@pytest.mark.asyncio
async def test_list_connections(client_with_mock_mcp):
    """list_connections should call MCP list_connections tool."""
    client_with_mock_mcp._mcp.call_tool.return_value = {
        "connections": [],
        "count": 0,
    }

    result = await client_with_mock_mcp.list_connections()
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_fetch_orders(client_with_mock_mcp):
    """fetch_orders should call MCP list_orders tool."""
    client_with_mock_mcp._mcp.call_tool.return_value = {
        "success": True,
        "orders": [{"order_id": "1"}],
        "count": 1,
    }

    result = await client_with_mock_mcp.fetch_orders("shopify")
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_fetch_orders_with_status(client_with_mock_mcp):
    """fetch_orders should pass status filter."""
    client_with_mock_mcp._mcp.call_tool.return_value = {
        "success": True, "orders": [], "count": 0,
    }

    await client_with_mock_mcp.fetch_orders("shopify", status="pending", limit=50)
    client_with_mock_mcp._mcp.call_tool.assert_called_once_with(
        "list_orders",
        {"platform": "shopify", "limit": 50, "status": "pending"},
    )


@pytest.mark.asyncio
async def test_get_order(client_with_mock_mcp):
    """get_order should call MCP get_order tool."""
    client_with_mock_mcp._mcp.call_tool.return_value = {
        "success": True,
        "order": {"order_id": "123"},
    }

    result = await client_with_mock_mcp.get_order("shopify", "123")
    assert result["order"]["order_id"] == "123"


@pytest.mark.asyncio
async def test_update_tracking(client_with_mock_mcp):
    """update_tracking should call MCP update_tracking tool."""
    client_with_mock_mcp._mcp.call_tool.return_value = {"success": True}

    result = await client_with_mock_mcp.update_tracking(
        "shopify", "123", "1Z999AA1", "UPS"
    )
    assert result["success"] is True
    client_with_mock_mcp._mcp.call_tool.assert_called_once_with(
        "update_tracking",
        {
            "platform": "shopify",
            "order_id": "123",
            "tracking_number": "1Z999AA1",
            "carrier": "UPS",
        },
    )
