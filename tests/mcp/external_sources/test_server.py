"""Test External Sources Gateway MCP server."""


from src.mcp.external_sources.models import OrderFilters, PlatformConnection
from src.mcp.external_sources.server import mcp


def test_mcp_server_exists():
    """Test that MCP server is properly configured."""
    assert mcp is not None
    assert mcp.name == "ExternalSources"


def test_platform_connection_model():
    """Test PlatformConnection model."""
    conn = PlatformConnection(
        platform="shopify",
        store_url="https://mystore.myshopify.com",
        status="connected",
    )
    assert conn.platform == "shopify"
    assert conn.status == "connected"


def test_order_filters_model():
    """Test OrderFilters model."""
    filters = OrderFilters(
        status="pending",
        date_from="2026-01-01",
        limit=50,
    )
    assert filters.status == "pending"
    assert filters.limit == 50
