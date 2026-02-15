"""Tests for connect_platform and disconnect_platform MCP tools.

Verifies real client instantiation, authentication, and lifespan
context management.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.mcp.external_sources.tools import (
    connect_platform,
    disconnect_platform,
    get_shop_info,
)


@pytest.fixture
def mock_ctx():
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "connections": {},
        "clients": {},
        "credentials": {},
    }
    ctx.info = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_connect_shopify_instantiates_client(mock_ctx):
    """connect_platform should authenticate and store a real client."""
    with patch(
        "src.mcp.external_sources.tools._create_platform_client"
    ) as mock_create:
        mock_client = AsyncMock()
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_create.return_value = mock_client

        result = await connect_platform(
            platform="shopify",
            credentials={"access_token": "shpat_test"},
            ctx=mock_ctx,
            store_url="https://test.myshopify.com",
        )

    assert result["success"] is True
    assert result["status"] == "connected"
    assert mock_ctx.request_context.lifespan_context["clients"]["shopify"] is mock_client


@pytest.mark.asyncio
async def test_connect_platform_auth_failure(mock_ctx):
    """connect_platform should return error on auth failure."""
    with patch(
        "src.mcp.external_sources.tools._create_platform_client"
    ) as mock_create:
        mock_client = AsyncMock()
        mock_client.authenticate = AsyncMock(side_effect=Exception("Invalid token"))
        mock_create.return_value = mock_client

        result = await connect_platform(
            platform="shopify",
            credentials={"access_token": "bad"},
            ctx=mock_ctx,
            store_url="https://test.myshopify.com",
        )

    assert result["success"] is False
    assert "Invalid token" in result["error"]
    assert "shopify" not in mock_ctx.request_context.lifespan_context["clients"]


@pytest.mark.asyncio
async def test_connect_platform_auth_returns_false(mock_ctx):
    """connect_platform should return error when authenticate returns False."""
    with patch(
        "src.mcp.external_sources.tools._create_platform_client"
    ) as mock_create:
        mock_client = AsyncMock()
        mock_client.authenticate = AsyncMock(return_value=False)
        mock_create.return_value = mock_client

        result = await connect_platform(
            platform="shopify",
            credentials={"access_token": "bad"},
            ctx=mock_ctx,
            store_url="https://test.myshopify.com",
        )

    assert result["success"] is False
    assert "shopify" not in mock_ctx.request_context.lifespan_context["clients"]


@pytest.mark.asyncio
async def test_connect_woocommerce_maps_site_url(mock_ctx):
    """connect_platform should map store_url to site_url for WooCommerce."""
    with patch(
        "src.mcp.external_sources.tools._create_platform_client"
    ) as mock_create:
        mock_client = AsyncMock()
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_create.return_value = mock_client

        await connect_platform(
            platform="woocommerce",
            credentials={"consumer_key": "ck_test", "consumer_secret": "cs_test"},
            ctx=mock_ctx,
            store_url="https://shop.example.com",
        )

    # Verify site_url was passed to authenticate
    call_args = mock_client.authenticate.call_args[0][0]
    assert call_args["site_url"] == "https://shop.example.com"


@pytest.mark.asyncio
async def test_connect_unsupported_platform(mock_ctx):
    """connect_platform should reject unsupported platforms."""
    result = await connect_platform(
        platform="fedex",
        credentials={},
        ctx=mock_ctx,
    )

    assert result["success"] is False
    assert "Unsupported platform" in result["error"]


@pytest.mark.asyncio
async def test_disconnect_platform_removes_state(mock_ctx):
    """disconnect_platform should remove client, connection, and credentials."""
    mock_client = AsyncMock()
    mock_client.close = AsyncMock()
    mock_ctx.request_context.lifespan_context["clients"]["shopify"] = mock_client
    mock_ctx.request_context.lifespan_context["connections"]["shopify"] = "conn"
    mock_ctx.request_context.lifespan_context["credentials"]["shopify"] = "cred"

    result = await disconnect_platform(platform="shopify", ctx=mock_ctx)

    assert result["success"] is True
    assert result["status"] == "disconnected"
    assert "shopify" not in mock_ctx.request_context.lifespan_context["clients"]
    assert "shopify" not in mock_ctx.request_context.lifespan_context["connections"]
    assert "shopify" not in mock_ctx.request_context.lifespan_context["credentials"]
    mock_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_disconnect_platform_no_close_method(mock_ctx):
    """disconnect_platform should handle clients without close()."""
    mock_client = MagicMock(spec=[])  # No close attribute
    mock_ctx.request_context.lifespan_context["clients"]["shopify"] = mock_client

    result = await disconnect_platform(platform="shopify", ctx=mock_ctx)

    assert result["success"] is True


# -- get_shop_info tests --


@pytest.mark.asyncio
async def test_get_shop_info_returns_shop_data(mock_ctx):
    """get_shop_info should return shop metadata from connected client."""
    mock_client = AsyncMock()
    mock_client.get_shop_info = AsyncMock(return_value={
        "name": "Test Store",
        "address1": "123 Main St",
        "city": "Springfield",
        "province_code": "IL",
        "zip": "62701",
        "country_code": "US",
    })
    mock_ctx.request_context.lifespan_context["clients"]["shopify"] = mock_client

    result = await get_shop_info(platform="shopify", ctx=mock_ctx)

    assert result["success"] is True
    assert result["shop"]["name"] == "Test Store"
    mock_client.get_shop_info.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_shop_info_not_connected(mock_ctx):
    """get_shop_info should return error if platform not connected."""
    result = await get_shop_info(platform="shopify", ctx=mock_ctx)

    assert result["success"] is False
    assert "not connected" in result["error"]


@pytest.mark.asyncio
async def test_get_shop_info_unsupported_platform(mock_ctx):
    """get_shop_info should return error for platforms without get_shop_info."""
    mock_client = MagicMock(spec=[])  # No get_shop_info
    mock_ctx.request_context.lifespan_context["clients"]["woocommerce"] = mock_client

    result = await get_shop_info(platform="woocommerce", ctx=mock_ctx)

    assert result["success"] is False
    assert "not supported" in result["error"]


@pytest.mark.asyncio
async def test_get_shop_info_returns_none(mock_ctx):
    """get_shop_info should handle None response from client."""
    mock_client = AsyncMock()
    mock_client.get_shop_info = AsyncMock(return_value=None)
    mock_ctx.request_context.lifespan_context["clients"]["shopify"] = mock_client

    result = await get_shop_info(platform="shopify", ctx=mock_ctx)

    assert result["success"] is False
    assert "Failed to retrieve" in result["error"]
