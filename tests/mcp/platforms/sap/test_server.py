# tests/mcp/platforms/sap/test_server.py
"""Tests for SAP platform MCP server contract compliance.

Since SAP requires real OData calls, the httpx client is mocked.
Tests call exported handler functions directly -- no FastMCP internal introspection.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import httpx


class TestSapServerContract:
    """Verify the SAP MCP server implements the required tool contract."""

    @pytest.mark.asyncio
    async def test_server_exposes_required_tools(self):
        """Verify tool registration via the public list_tools() MCP method."""
        from src.mcp.platforms.sap.server import mcp
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        required = {
            "platform.health", "platform.capabilities", "auth.connect",
            "auth.disconnect", "orders.list", "orders.get", "tracking.write_back",
        }
        assert required.issubset(tool_names), f"Missing tools: {required - tool_names}"

    @pytest.mark.asyncio
    async def test_health_returns_required_shape_when_disconnected(self):
        """Health response must match contract shape even when not connected."""
        from src.mcp.platforms.sap.server import health
        result = await health()
        # Required fields per contract
        assert "ok" in result
        assert "platform_id" in result
        assert result["platform_id"] == "sap"
        assert "server_version" in result
        assert "contract_version" in result
        assert result["contract_version"] == "1.0"
        assert "api_reachable" in result
        assert "auth_valid" in result
        # Not connected, so ok should be False
        assert result["ok"] is False
        assert result["last_error"] is not None

    @pytest.mark.asyncio
    async def test_capabilities_returns_required_shape(self):
        """Capabilities response must match contract shape."""
        from src.mcp.platforms.sap.server import capabilities
        result = await capabilities()
        assert "supports" in result
        assert "limits" in result
        assert "paging" in result
        assert "contract_version" in result
        assert result["contract_version"] == "1.0"
        assert "orders.list" in result["supports"]
        # Verify paging contract fields
        assert "default_page_size" in result["paging"]
        assert "max_page_size" in result["paging"]
        assert "overlap_seconds" in result["paging"]
        # SAP uses offset-based paging
        assert result["paging"]["strategy"] == "offset"

    @pytest.mark.asyncio
    async def test_health_and_capabilities_contract_versions_match(self):
        """Contract version must be consistent across tools."""
        from src.mcp.platforms.sap.server import health, capabilities
        h = await health()
        c = await capabilities()
        assert h["contract_version"] == c["contract_version"]

    @pytest.mark.asyncio
    async def test_auth_connect_disconnect_cycle(self):
        """auth.connect and auth.disconnect cycle works with mocked SAP API."""
        import src.mcp.platforms.sap.server as sap_server

        # Save original state
        orig_client = sap_server._client
        orig_creds = sap_server._credentials

        try:
            # Reset state
            sap_server._client = None
            sap_server._credentials = None

            # Mock the httpx.AsyncClient to simulate a successful connection
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()

            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)

            with patch("httpx.AsyncClient", return_value=mock_client_instance):
                connect_result = await sap_server.auth_connect(
                    credential_ref="test",
                    base_url="https://sap.example.com/sap/opu/odata/sap/API_SALES_ORDER_SRV",
                    username="testuser",
                    password="testpass",
                    sap_client="100",
                )
                assert connect_result["connected"] is True
                assert connect_result["auth_valid"] is True
                assert sap_server._client is not None

            # Disconnect
            disconnect_result = await sap_server.auth_disconnect()
            assert disconnect_result["disconnected"] is True
            assert sap_server._client is None
            assert sap_server._credentials is None
        finally:
            # Restore original state
            sap_server._client = orig_client
            sap_server._credentials = orig_creds

    @pytest.mark.asyncio
    async def test_orders_list_not_connected(self):
        """orders.list returns auth required error when not connected."""
        import src.mcp.platforms.sap.server as sap_server

        orig_client = sap_server._client
        try:
            sap_server._client = None
            result = await sap_server.orders_list()
            assert result["error_code"] == "AUTH_REQUIRED"
        finally:
            sap_server._client = orig_client

    @pytest.mark.asyncio
    async def test_orders_get_not_connected(self):
        """orders.get returns auth required error when not connected."""
        import src.mcp.platforms.sap.server as sap_server

        orig_client = sap_server._client
        try:
            sap_server._client = None
            result = await sap_server.orders_get(order_id="12345")
            assert result["error_code"] == "AUTH_REQUIRED"
        finally:
            sap_server._client = orig_client

    @pytest.mark.asyncio
    async def test_tracking_write_back_not_connected(self):
        """tracking.write_back returns auth required error when not connected."""
        import src.mcp.platforms.sap.server as sap_server

        orig_client = sap_server._client
        try:
            sap_server._client = None
            result = await sap_server.tracking_write_back(
                order_id="12345",
                tracking_numbers=["1Z999AA10123456784"],
            )
            assert result["error_code"] == "AUTH_REQUIRED"
        finally:
            sap_server._client = orig_client


class TestSapServerWithMockedClient:
    """Test SAP server tool handlers with a mocked SapClient."""

    @pytest.fixture(autouse=True)
    def _setup_teardown(self):
        """Save and restore module-level state around each test."""
        import src.mcp.platforms.sap.server as sap_server
        orig_client = sap_server._client
        orig_creds = sap_server._credentials
        yield
        sap_server._client = orig_client
        sap_server._credentials = orig_creds

    def _inject_mock_client(self) -> AsyncMock:
        """Create and inject a mock SapClient into the server module."""
        import src.mcp.platforms.sap.server as sap_server
        mock_client = AsyncMock()
        sap_server._client = mock_client
        sap_server._credentials = MagicMock()
        return mock_client

    @pytest.mark.asyncio
    async def test_health_with_connected_client(self):
        """Health returns ok=True when client is connected and healthy."""
        mock_client = self._inject_mock_client()
        mock_client.test_connection = AsyncMock(
            return_value={"status": "ok", "base_url": "https://sap.example.com"}
        )

        from src.mcp.platforms.sap.server import health
        result = await health()
        assert result["ok"] is True
        assert result["api_reachable"] is True
        assert result["auth_valid"] is True

    @pytest.mark.asyncio
    async def test_orders_list_returns_contract_shape(self):
        """orders.list returns items, next_cursor, watermark."""
        mock_client = self._inject_mock_client()
        mock_client.fetch_orders = AsyncMock(return_value={
            "items": [
                {"SalesOrder": "1001", "CreationDate": "/Date(1709136000000)/"},
            ],
            "next_cursor": "50",
            "watermark": "2024-02-28T16:00:00+00:00",
        })

        from src.mcp.platforms.sap.server import orders_list
        result = await orders_list()
        assert "items" in result
        assert "next_cursor" in result
        assert "watermark" in result
        assert len(result["items"]) == 1

    @pytest.mark.asyncio
    async def test_orders_list_passes_cursor_as_offset(self):
        """orders.list converts string cursor to integer offset."""
        mock_client = self._inject_mock_client()
        mock_client.fetch_orders = AsyncMock(return_value={
            "items": [],
            "next_cursor": None,
            "watermark": None,
        })

        from src.mcp.platforms.sap.server import orders_list
        await orders_list(cursor="100")
        mock_client.fetch_orders.assert_called_once_with(
            offset=100,
            since=None,
            page_size=50,
        )

    @pytest.mark.asyncio
    async def test_orders_get_returns_order(self):
        """orders.get returns order dict on success."""
        mock_client = self._inject_mock_client()
        mock_client.get_order = AsyncMock(return_value={
            "SalesOrder": "1001",
            "SalesOrderType": "OR",
        })

        from src.mcp.platforms.sap.server import orders_get
        result = await orders_get(order_id="1001")
        assert "order" in result
        assert result["order"]["SalesOrder"] == "1001"

    @pytest.mark.asyncio
    async def test_orders_get_not_found(self):
        """orders.get returns NOT_FOUND error for unknown ID."""
        mock_client = self._inject_mock_client()
        mock_client.get_order = AsyncMock(return_value=None)

        from src.mcp.platforms.sap.server import orders_get
        result = await orders_get(order_id="NONEXISTENT")
        assert result["error_code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_tracking_write_back_success(self):
        """tracking.write_back returns success on successful update."""
        mock_client = self._inject_mock_client()
        mock_client.update_tracking = AsyncMock(return_value={"success": True})

        from src.mcp.platforms.sap.server import tracking_write_back
        result = await tracking_write_back(
            order_id="1001",
            tracking_numbers=["1Z999AA10123456784"],
        )
        assert result["success"] is True
