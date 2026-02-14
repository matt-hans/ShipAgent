"""Tests for connect_platform and disconnect_platform MCP tools.

Verifies real client instantiation, authentication, and lifespan
context management.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.mcp.external_sources.tools import connect_platform, disconnect_platform


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
