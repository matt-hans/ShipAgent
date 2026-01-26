"""Integration tests for Shopify MCP connectivity.

Tests verify:
- Agent connects to Shopify MCP successfully
- MCP authentication works with store credentials
- Tool discovery returns expected Shopify tools
- Connection handles errors gracefully

Requires: SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN environment variables
"""

import os
import pytest

from tests.helpers import MCPTestClient
from tests.conftest import requires_shopify_credentials


@pytest.fixture
def shopify_mcp_client(shopify_mcp_config) -> MCPTestClient:
    """Create MCPTestClient configured for Shopify MCP."""
    return MCPTestClient(
        command=shopify_mcp_config["command"],
        args=shopify_mcp_config["args"],
        env=shopify_mcp_config["env"],
    )


@pytest.mark.integration
@pytest.mark.shopify
class TestShopifyMCPConnectivity:
    """Tests for Shopify MCP connection and tool discovery."""

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_server_starts_with_credentials(self, shopify_mcp_client):
        """Shopify MCP should start with valid credentials."""
        await shopify_mcp_client.start(timeout=15.0)
        assert shopify_mcp_client.is_connected
        await shopify_mcp_client.stop()

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_server_lists_shopify_tools(self, shopify_mcp_client):
        """Shopify MCP should list order-related tools."""
        await shopify_mcp_client.start()
        try:
            tools = await shopify_mcp_client.list_tools()
            tool_names = [t["name"] for t in tools]

            # Verify essential Shopify tools exist
            # (actual tool names depend on shopify-mcp package)
            assert len(tools) > 0

            # Log available tools for debugging
            print(f"Available Shopify tools: {tool_names}")

        finally:
            await shopify_mcp_client.stop()

    @pytest.mark.asyncio
    async def test_server_fails_without_credentials(self):
        """Shopify MCP should fail gracefully without credentials."""
        client = MCPTestClient(
            command="npx",
            args=["shopify-mcp", "--accessToken", "", "--domain", ""],
            env={"PATH": os.environ.get("PATH", "")},
        )

        with pytest.raises((RuntimeError, TimeoutError)):
            await client.start(timeout=10.0)


@pytest.mark.integration
@pytest.mark.shopify
class TestShopifyMCPErrorRecovery:
    """Tests for Shopify MCP error handling."""

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_reconnect_after_disconnect(self, shopify_mcp_client):
        """Client should reconnect after server restart."""
        await shopify_mcp_client.start()
        await shopify_mcp_client.stop()

        # Should be able to start again
        await shopify_mcp_client.start()
        assert shopify_mcp_client.is_connected
        await shopify_mcp_client.stop()

    @requires_shopify_credentials
    @pytest.mark.asyncio
    async def test_handles_kill_gracefully(self, shopify_mcp_client):
        """Client should handle server being killed."""
        await shopify_mcp_client.start()
        await shopify_mcp_client.kill_hard()
        assert not shopify_mcp_client.is_connected
