# tests/services/test_platform_session_adapter.py
"""Tests for PlatformSessionAdapter: MCPClient → SessionProtocol bridge.

Unit tests use a mock MCPClient. Integration test spawns a real dummy MCP
server via stdio to verify the full lifecycle.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.services.gateway_provider import PlatformSessionAdapter


class TestPlatformSessionAdapterUnit:
    """Unit tests with mock MCPClient."""

    @pytest.fixture
    def mock_client(self):
        """Build a mock MCPClient with async methods."""
        client = MagicMock()
        client.connect = AsyncMock()
        client.disconnect = AsyncMock()
        client.call_tool = AsyncMock(return_value={"ok": True})
        return client

    @pytest.mark.asyncio
    async def test_lazy_connect_on_first_call(self, mock_client):
        """connect() is called on first call_tool, not on construction."""
        adapter = PlatformSessionAdapter(mock_client)
        mock_client.connect.assert_not_called()

        await adapter.call_tool("platform.health", {})
        mock_client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_called_only_once(self, mock_client):
        """Multiple call_tool invocations reuse the same connection."""
        adapter = PlatformSessionAdapter(mock_client)
        await adapter.call_tool("platform.health", {})
        await adapter.call_tool("orders.list", {})
        mock_client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_tool_delegates_to_client(self, mock_client):
        """Arguments are forwarded to the underlying MCPClient."""
        adapter = PlatformSessionAdapter(mock_client)
        result = await adapter.call_tool("orders.list", {"cursor": "page2"})
        mock_client.call_tool.assert_called_with("orders.list", {"cursor": "page2"})
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_close_calls_disconnect(self, mock_client):
        """close() maps to MCPClient.disconnect()."""
        adapter = PlatformSessionAdapter(mock_client)
        await adapter.call_tool("platform.health", {})
        await adapter.close()
        mock_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_without_connect_is_noop(self, mock_client):
        """close() on never-connected adapter is safe."""
        adapter = PlatformSessionAdapter(mock_client)
        await adapter.close()
        mock_client.disconnect.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_resets_connected_flag(self, mock_client):
        """After close(), next call_tool reconnects."""
        adapter = PlatformSessionAdapter(mock_client)
        await adapter.call_tool("platform.health", {})
        await adapter.close()
        assert mock_client.connect.call_count == 1

        await adapter.call_tool("platform.health", {})
        assert mock_client.connect.call_count == 2


class TestPlatformSessionAdapterIntegration:
    """Integration test: real MCPClient + real dummy MCP server."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_with_dummy_server(self):
        """Spawn dummy MCP server via stdio, run health + auth + orders + close."""
        import os
        import sys
        from mcp import StdioServerParameters
        from src.services.mcp_client import MCPClient

        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "src.mcp.platforms.dummy.server"],
            env={
                "PYTHONPATH": project_root,
                "PATH": os.environ.get("PATH", ""),
            },
        )
        client = MCPClient(params, max_retries=1, base_delay=0.1)
        adapter = PlatformSessionAdapter(client)

        try:
            # Health check (triggers lazy connect)
            health = await adapter.call_tool("platform.health", {})
            assert health["ok"] is True or health["platform_id"] == "dummy"
            assert health["contract_version"] == "1.0"

            # Auth connect (dummy accepts any credential_ref)
            auth = await adapter.call_tool("auth.connect", {"credential_ref": "test"})
            assert auth["ok"] is True

            # Orders list page 1
            page1 = await adapter.call_tool("orders.list", {})
            assert "items" in page1
            assert len(page1["items"]) > 0

            # Orders list page 2
            if page1.get("next_cursor"):
                page2 = await adapter.call_tool(
                    "orders.list", {"cursor": page1["next_cursor"]}
                )
                assert "items" in page2
        finally:
            await adapter.close()
