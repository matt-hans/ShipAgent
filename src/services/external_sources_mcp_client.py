"""Process-global async MCP client for External Sources Gateway.

Provides a singleton interface for connecting to and interacting with
external platforms (Shopify, WooCommerce, SAP, Oracle) via the External
Sources MCP server over stdio.

Mirrors the UPSMCPClient pattern: one process-global instance, long-lived
stdio connection, cached across requests.
"""

import logging
import os
import sys
from typing import Any

from mcp import StdioServerParameters

from src.services.mcp_client import MCPClient

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_VENV_PYTHON = os.path.join(_PROJECT_ROOT, ".venv", "bin", "python3")


def _get_python_command() -> str:
    """Return the preferred Python interpreter for MCP subprocesses.

    Prioritizes the project virtual environment to ensure all MCP
    subprocesses use the same dependency set as the backend.
    Falls back to the current interpreter when .venv Python is missing
    (e.g. in worktrees or CI environments).
    """
    if os.path.exists(_VENV_PYTHON):
        return _VENV_PYTHON
    return sys.executable


class ExternalSourcesMCPClient:
    """Process-global async MCP client for external platform operations.

    Wraps the generic MCPClient with External Sources MCP-specific
    methods. Designed as a singleton — one instance shared by API routes
    and agent tools.

    Attributes:
        _mcp: Underlying generic MCPClient instance.
    """

    def __init__(self) -> None:
        """Initialize External Sources MCP client."""
        self._mcp = MCPClient(
            server_params=self._build_server_params(),
            max_retries=2,
            base_delay=0.5,
        )

    def _build_server_params(self) -> StdioServerParameters:
        """Build StdioServerParameters for the External Sources MCP server.

        Returns:
            Configured StdioServerParameters.
        """
        return StdioServerParameters(
            command=_get_python_command(),
            args=["-m", "src.mcp.external_sources.server"],
            env={
                "PYTHONPATH": _PROJECT_ROOT,
                "PATH": os.environ.get("PATH", ""),
            },
        )

    async def connect(self) -> None:
        """Connect to External Sources MCP server if not already connected."""
        if self._mcp.is_connected:
            return
        await self._mcp.connect()
        logger.info("External Sources MCP client connected")

    async def disconnect(self) -> None:
        """Disconnect from External Sources MCP server."""
        await self._mcp.disconnect()

    @property
    def is_connected(self) -> bool:
        """Whether the MCP session is connected."""
        return self._mcp.is_connected

    async def connect_platform(
        self,
        platform: str,
        credentials: dict[str, Any],
        store_url: str | None = None,
    ) -> dict[str, Any]:
        """Connect to a platform via MCP gateway.

        Args:
            platform: Platform identifier (shopify, woocommerce, sap, oracle).
            credentials: Platform-specific credentials.
            store_url: Store/instance URL.

        Returns:
            Dict with success, platform, status.
        """
        return await self._mcp.call_tool(
            "connect_platform",
            {
                "platform": platform,
                "credentials": credentials,
                "store_url": store_url,
            },
        )

    async def disconnect_platform(self, platform: str) -> dict[str, Any]:
        """Disconnect a platform via MCP gateway.

        Args:
            platform: Platform identifier.

        Returns:
            Dict with success status.
        """
        return await self._mcp.call_tool(
            "disconnect_platform", {"platform": platform}
        )

    async def list_connections(self) -> dict[str, Any]:
        """List all platform connections.

        Returns:
            Dict with connections list and count.
        """
        return await self._mcp.call_tool("list_connections", {})

    async def fetch_orders(
        self,
        platform: str,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Fetch orders from a connected platform.

        Args:
            platform: Platform identifier.
            status: Optional order status filter.
            limit: Max orders to return.

        Returns:
            Dict with orders list and count.
        """
        args: dict[str, Any] = {"platform": platform, "limit": limit}
        if status:
            args["status"] = status
        return await self._mcp.call_tool("list_orders", args)

    async def get_order(
        self, platform: str, order_id: str
    ) -> dict[str, Any]:
        """Get a single order by ID.

        Args:
            platform: Platform identifier.
            order_id: Platform order ID.

        Returns:
            Dict with order data.
        """
        return await self._mcp.call_tool(
            "get_order", {"platform": platform, "order_id": order_id}
        )

    async def get_shop_info(self, platform: str) -> dict[str, Any]:
        """Get shop/store metadata from a connected platform.

        Args:
            platform: Platform identifier (e.g., 'shopify').

        Returns:
            Dict with success, platform, and shop metadata.
        """
        return await self._mcp.call_tool(
            "get_shop_info", {"platform": platform}
        )

    async def update_tracking(
        self,
        platform: str,
        order_id: str,
        tracking_number: str,
        carrier: str = "UPS",
    ) -> dict[str, Any]:
        """Update tracking info for an order.

        Args:
            platform: Platform identifier.
            order_id: Platform order ID.
            tracking_number: Carrier tracking number.
            carrier: Carrier name.

        Returns:
            Dict with success status.
        """
        return await self._mcp.call_tool(
            "update_tracking",
            {
                "platform": platform,
                "order_id": order_id,
                "tracking_number": tracking_number,
                "carrier": carrier,
            },
        )
