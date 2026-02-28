# src/mcp/platforms/amazon/server.py
"""Amazon Seller Central standalone platform MCP server.

Implements the federated platform contract with 7 required tools:
platform.health, platform.capabilities, auth.connect, auth.disconnect,
orders.list, orders.get, tracking.write_back.

Runs as a stdio subprocess, managed by PlatformGateway.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.mcp.platforms.amazon.client import AmazonClient
from src.mcp.platforms.amazon.constants import (
    CONTRACT_VERSION,
    DEFAULT_PAGE_SIZE,
    MAX_CONCURRENCY,
    MAX_PAGE_SIZE,
    OVERLAP_SECONDS,
    PAGING_STRATEGY,
    PLATFORM_ID,
    RATE_LIMIT_PER_SECOND,
    SERVER_VERSION,
    SUPPORTED_TOOLS,
)
from src.mcp.platforms.amazon.models import AmazonCredentials
from src.services.platform_models import PlatformError, PlatformErrorCode

logger = logging.getLogger(__name__)

# Server-level state (process-scoped, one client per server process)
_client: AmazonClient | None = None
_credentials: AmazonCredentials | None = None

mcp = FastMCP("amazon-platform")


# --- Contract tools ---


@mcp.tool(name="platform.health")
async def health() -> dict[str, Any]:
    """Check platform health: API reachability and auth validity."""
    result: dict[str, Any] = {
        "ok": False,
        "platform_id": PLATFORM_ID,
        "server_version": SERVER_VERSION,
        "contract_version": CONTRACT_VERSION,
        "api_reachable": False,
        "auth_valid": False,
        "time_utc": datetime.now(timezone.utc).isoformat(),
    }

    if _client is None:
        result["last_error"] = "Not connected — call auth.connect first"
        return result

    try:
        await _client.test_connection()
        result["ok"] = True
        result["api_reachable"] = True
        result["auth_valid"] = True
    except PlatformError as e:
        result["last_error"] = e.message
        if e.error_code == PlatformErrorCode.AUTH_EXPIRED:
            result["api_reachable"] = True  # API reached, auth failed
    except Exception as e:
        result["last_error"] = str(e)

    return result


@mcp.tool(name="platform.capabilities")
async def capabilities() -> dict[str, Any]:
    """Return capability manifest for this platform."""
    return {
        "platform_id": PLATFORM_ID,
        "contract_version": CONTRACT_VERSION,
        "supports": SUPPORTED_TOOLS,
        "limits": {
            "rate_limit_per_second": RATE_LIMIT_PER_SECOND,
            "max_concurrency": MAX_CONCURRENCY,
        },
        "paging": {
            "strategy": PAGING_STRATEGY,
            "default_page_size": DEFAULT_PAGE_SIZE,
            "max_page_size": MAX_PAGE_SIZE,
            "overlap_seconds": OVERLAP_SECONDS,
        },
    }


@mcp.tool(name="auth.connect")
async def auth_connect(
    credential_ref: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    marketplace_id: str = "ATVPDKIKX0DER",
) -> dict[str, Any]:
    """Connect to Amazon Seller Central with SP-API credentials.

    Args:
        credential_ref: Profile identifier (e.g., "primary").
        client_id: LWA application client ID.
        client_secret: LWA application client secret.
        refresh_token: LWA refresh token for the seller.
        marketplace_id: Amazon marketplace ID (default: US - ATVPDKIKX0DER).
    """
    global _client, _credentials

    creds = AmazonCredentials(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        marketplace_id=marketplace_id,
    )
    client = AmazonClient(creds)

    try:
        await client.test_connection()
        _client = client
        _credentials = creds

        return {
            "connected": True,
            "auth_valid": True,
            "account_id": marketplace_id,
            "account_label": f"Amazon Marketplace {marketplace_id}",
        }
    except PlatformError as e:
        return {
            "connected": False,
            "auth_valid": False,
            "error": e.message,
        }


@mcp.tool(name="auth.disconnect")
async def auth_disconnect() -> dict[str, Any]:
    """Disconnect from Amazon Seller Central."""
    global _client, _credentials
    _client = None
    _credentials = None
    return {"disconnected": True}


@mcp.tool(name="orders.list")
async def orders_list(
    cursor: str | None = None,
    since: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """Fetch a page of orders with optional NextToken-based pagination.

    Args:
        cursor: NextToken from previous response (for pagination).
        since: ISO datetime — only fetch orders created after this time.
        page_size: Number of orders per page (default 50, max 100).
    """
    if _client is None:
        return _not_connected_error()

    try:
        result = await _client.fetch_orders_page(
            cursor=cursor,
            since=since,
            page_size=page_size,
        )
        return result
    except PlatformError as e:
        return e.to_dict()


@mcp.tool(name="orders.get")
async def orders_get(order_id: str) -> dict[str, Any]:
    """Fetch a single order by ID.

    Args:
        order_id: The Amazon order ID.
    """
    if _client is None:
        return _not_connected_error()

    try:
        order = await _client.get_order(order_id)
        if order is None:
            return {
                "error_code": PlatformErrorCode.NOT_FOUND.value,
                "message": f"Order {order_id} not found",
            }
        return {"order": order}
    except PlatformError as e:
        return e.to_dict()


@mcp.tool(name="tracking.write_back")
async def tracking_write_back(
    order_id: str,
    tracking_numbers: list[str],
    carrier: str = "UPS",
    tracking_url: str | None = None,
) -> dict[str, Any]:
    """Write tracking information back to Amazon.

    Creates a fulfillment feed submission with tracking details.

    Args:
        order_id: The Amazon order ID to update.
        tracking_numbers: List of tracking numbers.
        carrier: Carrier name (default: "UPS").
        tracking_url: Optional tracking URL.
    """
    if _client is None:
        return _not_connected_error()

    try:
        result = await _client.write_back_tracking(
            order_id=order_id,
            tracking_numbers=tracking_numbers,
            carrier=carrier,
            tracking_url=tracking_url,
        )
        return result
    except PlatformError as e:
        return e.to_dict()


def _not_connected_error() -> dict[str, Any]:
    """Standard error response when not connected."""
    return {
        "error_code": PlatformErrorCode.AUTH_REQUIRED.value,
        "message": "Not connected — call auth.connect first",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
