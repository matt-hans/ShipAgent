# tests/mcp/platforms/shopify/test_server.py
"""Tests for Shopify platform MCP server contract compliance.

Tests call exported handler functions directly — no FastMCP internal introspection.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestShopifyServerContract:
    """Verify the Shopify MCP server implements the required tool contract."""

    @pytest.mark.asyncio
    async def test_server_exposes_required_tools(self):
        """Verify tool registration via the public list_tools() MCP method."""
        from src.mcp.platforms.shopify.server import mcp
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        required = {"platform.health", "platform.capabilities", "auth.connect",
                     "auth.disconnect", "orders.list", "orders.get", "tracking.write_back"}
        assert required.issubset(tool_names), f"Missing tools: {required - tool_names}"

    @pytest.mark.asyncio
    async def test_health_returns_required_shape(self):
        """Call the handler function directly and verify response shape."""
        from src.mcp.platforms.shopify.server import health
        result = await health()
        # Required fields per contract
        assert "ok" in result
        assert "platform_id" in result
        assert result["platform_id"] == "shopify"
        assert "server_version" in result
        assert "contract_version" in result
        assert result["contract_version"] == "1.0"
        assert "api_reachable" in result
        assert "auth_valid" in result

    @pytest.mark.asyncio
    async def test_capabilities_returns_required_shape(self):
        """Call the handler function directly and verify response shape."""
        from src.mcp.platforms.shopify.server import capabilities
        result = await capabilities()
        assert "supports" in result
        assert "limits" in result
        assert "paging" in result
        assert "contract_version" in result
        assert "orders.list" in result["supports"]
        # Verify paging contract fields
        assert "default_page_size" in result["paging"]
        assert "max_page_size" in result["paging"]
        assert "overlap_seconds" in result["paging"]

    @pytest.mark.asyncio
    async def test_health_and_capabilities_contract_versions_match(self):
        """Contract version must be consistent across tools."""
        from src.mcp.platforms.shopify.server import health, capabilities
        h = await health()
        c = await capabilities()
        assert h["contract_version"] == c["contract_version"]
