"""FastAPI routes for external platform integrations.

Provides REST API endpoints for managing connections to external platforms
(Shopify, WooCommerce, SAP, Oracle) and fetching/updating orders.

These routes orchestrate calls to the External Sources Gateway MCP server
via the OrchestrationAgent using the Claude Agent SDK.

Architecture:
    Frontend -> FastAPI -> OrchestrationAgent -> External Sources MCP -> Platform APIs
"""

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.mcp.external_sources.models import (
    ConnectionStatus,
    ExternalOrder,
    PlatformConnection,
    PlatformType,
)

router = APIRouter(prefix="/platforms", tags=["platforms"])


# === Request/Response Schemas ===


class ConnectPlatformRequest(BaseModel):
    """Request body for connecting to a platform."""

    credentials: dict[str, Any] = Field(..., description="Platform-specific credentials")
    store_url: str | None = Field(None, description="Store/instance URL")


class ConnectPlatformResponse(BaseModel):
    """Response from platform connection attempt."""

    success: bool
    platform: str
    status: str
    message: str | None = None
    error: str | None = None


class ListConnectionsResponse(BaseModel):
    """Response listing all platform connections."""

    connections: list[PlatformConnection]
    count: int


class ListOrdersResponse(BaseModel):
    """Response listing orders from a platform."""

    success: bool
    platform: str
    orders: list[ExternalOrder]
    count: int
    total: int | None = None
    error: str | None = None


class GetOrderResponse(BaseModel):
    """Response for single order fetch."""

    success: bool
    platform: str
    order: ExternalOrder | None = None
    order_id: str | None = None
    error: str | None = None


class TrackingUpdateRequest(BaseModel):
    """Request body for updating tracking information."""

    tracking_number: str = Field(..., description="Carrier tracking number")
    carrier: str = Field(default="UPS", description="Carrier name")


class TrackingUpdateResponse(BaseModel):
    """Response from tracking update."""

    success: bool
    platform: str
    order_id: str
    tracking_number: str | None = None
    carrier: str | None = None
    error: str | None = None


class TestConnectionResponse(BaseModel):
    """Response from connection test."""

    success: bool
    platform: str
    status: str


# === Platform State Manager ===
# Manages connections and clients with thread-safe operations


class PlatformStateManager:
    """Thread-safe manager for platform connections and clients.

    Uses the actual platform clients (imported from external_sources.clients)
    to perform operations. Credentials are stored securely in memory.
    """

    def __init__(self) -> None:
        """Initialize the state manager."""
        self._lock = asyncio.Lock()
        self._connections: dict[str, PlatformConnection] = {}
        self._clients: dict[str, Any] = {}
        self._credentials: dict[str, dict[str, Any]] = {}

    async def list_connections(self) -> list[PlatformConnection]:
        """Get all current connections."""
        async with self._lock:
            return list(self._connections.values())

    async def get_connection(self, platform: str) -> PlatformConnection | None:
        """Get connection for a specific platform."""
        async with self._lock:
            return self._connections.get(platform)

    async def get_client(self, platform: str) -> Any | None:
        """Get client for a specific platform."""
        async with self._lock:
            return self._clients.get(platform)

    async def connect(
        self,
        platform: str,
        credentials: dict[str, Any],
        store_url: str | None = None,
    ) -> tuple[bool, str | None]:
        """Connect to a platform.

        Args:
            platform: Platform identifier.
            credentials: Platform-specific credentials.
            store_url: Store/instance URL.

        Returns:
            Tuple of (success, error_message).
        """
        async with self._lock:
            try:
                client: Any = None

                if platform == "shopify":
                    from src.mcp.external_sources.clients.shopify import ShopifyClient

                    client = ShopifyClient()
                    if not store_url:
                        return False, "store_url is required for Shopify"
                    creds = {**credentials, "store_url": store_url}
                    success = await client.authenticate(creds)

                elif platform == "woocommerce":
                    from src.mcp.external_sources.clients.woocommerce import (
                        WooCommerceClient,
                    )

                    client = WooCommerceClient()
                    if not store_url:
                        return False, "store_url (site_url) is required for WooCommerce"
                    creds = {**credentials, "site_url": store_url}
                    success = await client.authenticate(creds)

                elif platform == "sap":
                    from src.mcp.external_sources.clients.sap import SAPClient

                    client = SAPClient()
                    success = await client.authenticate(credentials)

                elif platform == "oracle":
                    from src.mcp.external_sources.clients.oracle import (
                        OracleClient,
                        OracleDependencyError,
                    )

                    try:
                        client = OracleClient()
                        success = await client.authenticate(credentials)
                    except OracleDependencyError as e:
                        return False, str(e)
                else:
                    return False, f"Unknown platform: {platform}"

                if success and client is not None:
                    # Store state
                    self._connections[platform] = PlatformConnection(
                        platform=platform,
                        store_url=store_url,
                        status=ConnectionStatus.CONNECTED.value,
                        last_connected=datetime.now().isoformat(),
                        error_message=None,
                    )
                    self._clients[platform] = client
                    self._credentials[platform] = credentials
                    return True, None
                else:
                    return False, "Authentication failed"

            except Exception as e:
                return False, str(e)

    async def disconnect(self, platform: str) -> bool:
        """Disconnect from a platform."""
        async with self._lock:
            client = self._clients.pop(platform, None)
            self._connections.pop(platform, None)
            self._credentials.pop(platform, None)

            if client is not None and hasattr(client, "close"):
                try:
                    await client.close()
                except Exception:
                    pass

            return True

    async def test_connection(self, platform: str) -> bool:
        """Test if a connection is still valid."""
        async with self._lock:
            client = self._clients.get(platform)
            if client is None:
                return False

            try:
                return await client.test_connection()
            except Exception:
                return False


# Global state manager instance
_state_manager = PlatformStateManager()


# === Routes ===


@router.get("/connections", response_model=ListConnectionsResponse)
async def list_connections() -> ListConnectionsResponse:
    """List all configured platform connections.

    Returns status of each connected platform including
    connection health and last sync time.

    Returns:
        List of platform connections with their status.
    """
    connections = await _state_manager.list_connections()
    return ListConnectionsResponse(
        connections=connections,
        count=len(connections),
    )


@router.post("/{platform}/connect", response_model=ConnectPlatformResponse)
async def connect_platform(
    platform: str,
    request: ConnectPlatformRequest,
) -> ConnectPlatformResponse:
    """Connect to an external platform.

    Authenticates with the platform using the provided credentials
    and stores the connection for reuse.

    Args:
        platform: Platform identifier (shopify, woocommerce, sap, oracle).
        request: Connection credentials and store URL.

    Returns:
        Connection result with status.
    """
    # Validate platform
    valid_platforms = {p.value for p in PlatformType}
    if platform not in valid_platforms:
        return ConnectPlatformResponse(
            success=False,
            platform=platform,
            status="error",
            error=f"Unsupported platform: {platform}. "
            f"Supported: {', '.join(sorted(valid_platforms))}",
        )

    success, error = await _state_manager.connect(
        platform=platform,
        credentials=request.credentials,
        store_url=request.store_url,
    )

    if success:
        return ConnectPlatformResponse(
            success=True,
            platform=platform,
            status="connected",
            message=f"Successfully connected to {platform}",
        )
    else:
        return ConnectPlatformResponse(
            success=False,
            platform=platform,
            status="error",
            error=error or "Connection failed",
        )


@router.post("/{platform}/disconnect", response_model=dict)
async def disconnect_platform(platform: str) -> dict:
    """Disconnect from an external platform.

    Closes the connection and removes stored credentials.

    Args:
        platform: Platform identifier.

    Returns:
        Success status.
    """
    await _state_manager.disconnect(platform)
    return {"success": True, "platform": platform}


@router.get("/{platform}/test", response_model=TestConnectionResponse)
async def test_connection(platform: str) -> TestConnectionResponse:
    """Test connection to a platform.

    Verifies that the stored credentials are still valid
    by making a health check call to the platform.

    Args:
        platform: Platform identifier.

    Returns:
        Connection test result.
    """
    connection = await _state_manager.get_connection(platform)
    if connection is None:
        return TestConnectionResponse(
            success=False,
            platform=platform,
            status="disconnected",
        )

    is_healthy = await _state_manager.test_connection(platform)
    return TestConnectionResponse(
        success=is_healthy,
        platform=platform,
        status="connected" if is_healthy else "error",
    )


@router.get("/{platform}/orders", response_model=ListOrdersResponse)
async def list_orders(
    platform: str,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> ListOrdersResponse:
    """List orders from a connected platform.

    Fetches orders from the specified platform with optional filtering.

    Args:
        platform: Platform identifier.
        status: Filter by order status.
        date_from: Start date (ISO format).
        date_to: End date (ISO format).
        limit: Maximum orders to return (default 100).
        offset: Pagination offset.

    Returns:
        List of orders in normalized format.
    """
    client = await _state_manager.get_client(platform)
    if client is None:
        return ListOrdersResponse(
            success=False,
            platform=platform,
            orders=[],
            count=0,
            error=f"Platform {platform} not connected. Connect first.",
        )

    from src.mcp.external_sources.models import OrderFilters

    filters = OrderFilters(
        status=status,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )

    try:
        orders = await client.fetch_orders(filters)
        return ListOrdersResponse(
            success=True,
            platform=platform,
            orders=orders,
            count=len(orders),
        )
    except Exception as e:
        return ListOrdersResponse(
            success=False,
            platform=platform,
            orders=[],
            count=0,
            error=str(e),
        )


@router.get("/{platform}/orders/{order_id}", response_model=GetOrderResponse)
async def get_order(platform: str, order_id: str) -> GetOrderResponse:
    """Get a single order by ID from a connected platform.

    Args:
        platform: Platform identifier.
        order_id: Platform-specific order identifier.

    Returns:
        Order details if found.
    """
    client = await _state_manager.get_client(platform)
    if client is None:
        return GetOrderResponse(
            success=False,
            platform=platform,
            order_id=order_id,
            error=f"Platform {platform} not connected. Connect first.",
        )

    try:
        order = await client.get_order(order_id)
        if order is None:
            return GetOrderResponse(
                success=False,
                platform=platform,
                order_id=order_id,
                error=f"Order {order_id} not found",
            )
        return GetOrderResponse(
            success=True,
            platform=platform,
            order=order,
        )
    except Exception as e:
        return GetOrderResponse(
            success=False,
            platform=platform,
            order_id=order_id,
            error=str(e),
        )


@router.put("/{platform}/orders/{order_id}/tracking", response_model=TrackingUpdateResponse)
async def update_tracking(
    platform: str,
    order_id: str,
    request: TrackingUpdateRequest,
) -> TrackingUpdateResponse:
    """Update tracking information for an order.

    Writes tracking number and carrier back to the source platform.

    Args:
        platform: Platform identifier.
        order_id: Platform-specific order identifier.
        request: Tracking information.

    Returns:
        Update result.
    """
    client = await _state_manager.get_client(platform)
    if client is None:
        return TrackingUpdateResponse(
            success=False,
            platform=platform,
            order_id=order_id,
            error=f"Platform {platform} not connected. Connect first.",
        )

    from src.mcp.external_sources.models import TrackingUpdate

    update = TrackingUpdate(
        order_id=order_id,
        tracking_number=request.tracking_number,
        carrier=request.carrier,
        tracking_url=None,
    )

    try:
        success = await client.update_tracking(update)
        if success:
            return TrackingUpdateResponse(
                success=True,
                platform=platform,
                order_id=order_id,
                tracking_number=request.tracking_number,
                carrier=request.carrier,
            )
        else:
            return TrackingUpdateResponse(
                success=False,
                platform=platform,
                order_id=order_id,
                error="Platform rejected tracking update",
            )
    except Exception as e:
        return TrackingUpdateResponse(
            success=False,
            platform=platform,
            order_id=order_id,
            error=str(e),
        )
