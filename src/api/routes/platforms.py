"""FastAPI routes for external platform integrations.

Provides REST API endpoints for managing connections to external platforms
(Shopify, WooCommerce, SAP, Oracle) and fetching/updating orders.

All routes are thin HTTP-to-MCP adapters delegating to the
ExternalSourcesMCPClient via gateway_provider. No direct platform
client imports or local state management.
"""

import os
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.mcp.external_sources.models import (
    ExternalOrder,
    PlatformConnection,
    PlatformType,
)
from src.services.gateway_provider import get_external_sources_client

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


class ShopifyEnvStatusResponse(BaseModel):
    """Response from Shopify environment status check.

    Indicates whether Shopify credentials are configured in environment
    variables and whether they are valid against the Shopify API.
    """

    configured: bool = Field(
        ..., description="True if both SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN are set"
    )
    valid: bool = Field(..., description="True if credentials validated against Shopify API")
    store_url: str | None = Field(None, description="Store URL from environment")
    store_name: str | None = Field(None, description="Shop name from Shopify API")
    error: str | None = Field(None, description="Error message if validation failed")


# === Routes ===


@router.get("/connections", response_model=ListConnectionsResponse)
async def list_connections() -> ListConnectionsResponse:
    """List all configured platform connections.

    Returns:
        List of platform connections with their status.
    """
    ext = await get_external_sources_client()
    result = await ext.list_connections()
    raw_connections = result.get("connections", [])

    # Convert dicts to PlatformConnection if needed
    connections = []
    for c in raw_connections:
        if isinstance(c, dict):
            connections.append(PlatformConnection(**c))
        else:
            connections.append(c)

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

    Args:
        platform: Platform identifier (shopify, woocommerce, sap, oracle).
        request: Connection credentials and store URL.

    Returns:
        Connection result with status.
    """
    valid_platforms = {p.value for p in PlatformType}
    if platform not in valid_platforms:
        return ConnectPlatformResponse(
            success=False,
            platform=platform,
            status="error",
            error=f"Unsupported platform: {platform}. "
            f"Supported: {', '.join(sorted(valid_platforms))}",
        )

    ext = await get_external_sources_client()
    result = await ext.connect_platform(
        platform=platform,
        credentials=request.credentials,
        store_url=request.store_url,
    )

    if result.get("success"):
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
            error=result.get("error", "Connection failed"),
        )


@router.post("/{platform}/disconnect", response_model=dict)
async def disconnect_platform(platform: str) -> dict:
    """Disconnect from an external platform.

    Args:
        platform: Platform identifier.

    Returns:
        Success status.
    """
    ext = await get_external_sources_client()
    result = await ext.disconnect_platform(platform)
    return {
        "success": result.get("success", True),
        "platform": platform,
        "status": result.get("status", "disconnected"),
    }


@router.get("/{platform}/test", response_model=TestConnectionResponse)
async def test_connection(platform: str) -> TestConnectionResponse:
    """Test connection to a platform.

    Checks if the platform appears in the active connections list.

    Args:
        platform: Platform identifier.

    Returns:
        Connection test result.
    """
    ext = await get_external_sources_client()
    result = await ext.list_connections()
    connections = result.get("connections", [])

    for conn in connections:
        conn_platform = conn.get("platform") if isinstance(conn, dict) else getattr(conn, "platform", None)
        conn_status = conn.get("status") if isinstance(conn, dict) else getattr(conn, "status", None)
        if conn_platform == platform and conn_status == "connected":
            return TestConnectionResponse(
                success=True,
                platform=platform,
                status="connected",
            )

    return TestConnectionResponse(
        success=False,
        platform=platform,
        status="disconnected",
    )


@router.get("/shopify/env-status", response_model=ShopifyEnvStatusResponse)
async def get_shopify_env_status() -> ShopifyEnvStatusResponse:
    """Check Shopify credentials via runtime_credentials adapter.

    Resolves Shopify credentials (DB priority, env fallback) and validates
    via the gateway's read-only validate_credentials tool. Does NOT mutate
    shared connection state.

    Returns:
        Status indicating whether credentials are configured and valid.
    """
    from src.services.runtime_credentials import resolve_shopify_credentials

    shopify_creds = resolve_shopify_credentials()
    if shopify_creds is None:
        return ShopifyEnvStatusResponse(
            configured=False,
            valid=False,
            store_url=None,
            store_name=None,
            error="No Shopify credentials configured. Connect Shopify in Settings.",
        )

    access_token = shopify_creds.access_token
    store_domain = shopify_creds.store_domain

    try:
        ext = await get_external_sources_client()
        result = await ext.validate_credentials(
            platform="shopify",
            credentials={"access_token": access_token},
            store_url=store_domain,
        )

        if not result.get("valid"):
            return ShopifyEnvStatusResponse(
                configured=True,
                valid=False,
                store_url=store_domain,
                store_name=None,
                error=result.get("error", "Authentication failed - check credentials"),
            )

        # validate_credentials returns shop metadata inline
        shop = result.get("shop") or {}
        store_name = shop.get("name") if isinstance(shop, dict) else None

        return ShopifyEnvStatusResponse(
            configured=True,
            valid=True,
            store_url=store_domain,
            store_name=store_name,
            error=None,
        )

    except Exception as e:
        return ShopifyEnvStatusResponse(
            configured=True,
            valid=False,
            store_url=store_domain,
            store_name=None,
            error=str(e),
        )


@router.get("/{platform}/orders", response_model=ListOrdersResponse)
async def list_orders(
    platform: str,
    status: str | None = None,
    limit: int = 100,
) -> ListOrdersResponse:
    """List orders from a connected platform.

    Args:
        platform: Platform identifier.
        status: Filter by order status.
        limit: Maximum orders to return (default 100).

    Returns:
        List of orders in normalized format.
    """
    ext = await get_external_sources_client()
    result = await ext.fetch_orders(platform, status=status, limit=limit)

    if not result.get("success", True):
        return ListOrdersResponse(
            success=False,
            platform=platform,
            orders=[],
            count=0,
            error=result.get("error", "Failed to fetch orders"),
        )

    raw_orders = result.get("orders", [])
    orders = []
    for o in raw_orders:
        if isinstance(o, dict):
            try:
                orders.append(ExternalOrder(**o))
            except Exception:
                orders.append(o)
        else:
            orders.append(o)

    return ListOrdersResponse(
        success=True,
        platform=platform,
        orders=orders,
        count=len(orders),
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
    ext = await get_external_sources_client()
    result = await ext.get_order(platform, order_id)

    if not result.get("success", False):
        return GetOrderResponse(
            success=False,
            platform=platform,
            order_id=order_id,
            error=result.get("error", f"Order {order_id} not found"),
        )

    raw_order = result.get("order")
    order = None
    if raw_order is not None:
        if isinstance(raw_order, dict):
            try:
                order = ExternalOrder(**raw_order)
            except Exception:
                pass
        else:
            order = raw_order

    return GetOrderResponse(
        success=True,
        platform=platform,
        order=order,
    )


@router.put("/{platform}/orders/{order_id}/tracking", response_model=TrackingUpdateResponse)
async def update_tracking(
    platform: str,
    order_id: str,
    request: TrackingUpdateRequest,
) -> TrackingUpdateResponse:
    """Update tracking information for an order.

    Args:
        platform: Platform identifier.
        order_id: Platform-specific order identifier.
        request: Tracking information.

    Returns:
        Update result.
    """
    ext = await get_external_sources_client()
    result = await ext.update_tracking(
        platform=platform,
        order_id=order_id,
        tracking_number=request.tracking_number,
        carrier=request.carrier,
    )

    if result.get("success"):
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
            error=result.get("error", "Platform rejected tracking update"),
        )
