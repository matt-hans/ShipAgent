"""Tests for connect_shopify agent tool."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_connect_shopify_fetches_and_imports():
    """connect_shopify tool should connect platform, fetch orders, import via gateway."""
    with (
        patch("src.orchestrator.agent.tools_v2.get_external_sources_client") as mock_ext,
        patch("src.orchestrator.agent.tools_v2.get_data_gateway") as mock_gw,
        patch.dict("os.environ", {
            "SHOPIFY_ACCESS_TOKEN": "shpat_test",
            "SHOPIFY_STORE_DOMAIN": "test.myshopify.com",
        }),
    ):
        ext_client = AsyncMock()
        ext_client.connect_platform.return_value = {"success": True}
        ext_client.fetch_orders.return_value = {
            "success": True,
            "orders": [{"order_id": "1", "customer_name": "Alice"}],
            "count": 1,
        }
        mock_ext.return_value = ext_client

        gw = AsyncMock()
        gw.import_from_records.return_value = {"row_count": 1}
        mock_gw.return_value = gw

        from src.orchestrator.agent.tools_v2 import connect_shopify_tool

        result = await connect_shopify_tool(
            args={},
            bridge=MagicMock(),
        )

    ext_client.connect_platform.assert_called_once_with(
        platform="shopify",
        credentials={"access_token": "shpat_test"},
        store_url="https://test.myshopify.com",
    )
    ext_client.fetch_orders.assert_called_once_with("shopify", limit=250)
    gw.import_from_records.assert_called_once()
    assert result["isError"] is False
    assert "1" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_connect_shopify_missing_credentials():
    """connect_shopify returns error when env vars not set."""
    with patch.dict("os.environ", {}, clear=True):
        from src.orchestrator.agent.tools_v2 import connect_shopify_tool

        result = await connect_shopify_tool(args={}, bridge=None)

    assert result["isError"] is True
    assert "credentials not configured" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_connect_shopify_connect_failure():
    """connect_shopify returns error when platform connect fails."""
    with (
        patch("src.orchestrator.agent.tools_v2.get_external_sources_client") as mock_ext,
        patch.dict("os.environ", {
            "SHOPIFY_ACCESS_TOKEN": "shpat_test",
            "SHOPIFY_STORE_DOMAIN": "test.myshopify.com",
        }),
    ):
        ext_client = AsyncMock()
        ext_client.connect_platform.return_value = {
            "success": False,
            "error": "Invalid token",
        }
        mock_ext.return_value = ext_client

        from src.orchestrator.agent.tools_v2 import connect_shopify_tool

        result = await connect_shopify_tool(args={}, bridge=None)

    assert result["isError"] is True
    assert "Invalid token" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_connect_shopify_no_orders():
    """connect_shopify returns error when no orders found."""
    with (
        patch("src.orchestrator.agent.tools_v2.get_external_sources_client") as mock_ext,
        patch.dict("os.environ", {
            "SHOPIFY_ACCESS_TOKEN": "shpat_test",
            "SHOPIFY_STORE_DOMAIN": "test.myshopify.com",
        }),
    ):
        ext_client = AsyncMock()
        ext_client.connect_platform.return_value = {"success": True}
        ext_client.fetch_orders.return_value = {
            "success": True,
            "orders": [],
            "count": 0,
        }
        mock_ext.return_value = ext_client

        from src.orchestrator.agent.tools_v2 import connect_shopify_tool

        result = await connect_shopify_tool(args={}, bridge=None)

    assert result["isError"] is True
    assert "No orders found" in result["content"][0]["text"]


def test_connect_shopify_registered_in_definitions():
    """connect_shopify is listed in get_all_tool_definitions()."""
    from src.orchestrator.agent.tools_v2 import get_all_tool_definitions

    defs = get_all_tool_definitions()
    names = [d["name"] for d in defs]
    assert "connect_shopify" in names
