"""MCP tools for External Sources Gateway.

Provides unified interface for connecting to and fetching
data from external platforms (Shopify, WooCommerce, SAP, Oracle).
"""

from fastmcp import Context

from src.mcp.external_sources.models import (
    OrderFilters,
    PlatformConnection,
    PlatformType,
)

SUPPORTED_PLATFORMS = {p.value for p in PlatformType}


def _get_lifespan_context(ctx: Context) -> dict:
    """Get the lifespan context from the request context.

    Args:
        ctx: FastMCP context

    Returns:
        Lifespan context dictionary

    Raises:
        RuntimeError: If request context not available
    """
    if ctx.request_context is None:
        raise RuntimeError("Request context not available")
    return ctx.request_context.lifespan_context


async def list_connections(ctx: Context) -> dict:
    """List all configured platform connections.

    Returns status of each connected platform including
    connection health and last sync time.

    Returns:
        Dictionary with:
        - connections: List of PlatformConnection objects
        - count: Number of configured connections

    Example:
        >>> result = await list_connections(ctx)
        >>> print(result["connections"])
        [{"platform": "shopify", "status": "connected", ...}]
    """
    lifespan_ctx = _get_lifespan_context(ctx)
    connections = lifespan_ctx.get("connections", {})

    await ctx.info(f"Listing {len(connections)} platform connections")

    return {
        "connections": [c.model_dump() for c in connections.values()],
        "count": len(connections),
    }


async def connect_platform(
    platform: str,
    credentials: dict,
    ctx: Context,
    store_url: str | None = None,
) -> dict:
    """Connect to an external platform.

    Authenticates with the platform and stores connection for reuse.

    Args:
        platform: Platform identifier (shopify, woocommerce, sap, oracle)
        credentials: Platform-specific credentials
            - shopify: {"access_token": str}
            - woocommerce: {"consumer_key": str, "consumer_secret": str}
            - sap: {"username": str, "password": str, "client": str}
            - oracle: {"username": str, "password": str} or OCI config
        store_url: Store/instance URL (required for most platforms)

    Returns:
        Dictionary with:
        - success: True if connected successfully
        - platform: Platform identifier
        - status: Connection status
        - error: Error message if failed

    Example:
        >>> result = await connect_platform(
        ...     "shopify",
        ...     {"access_token": "shpat_xxx"},
        ...     ctx,
        ...     store_url="https://store.myshopify.com"
        ... )
        >>> print(result["success"])
        True
    """
    await ctx.info(f"Connecting to platform: {platform}")

    # Validate platform is supported
    if platform not in SUPPORTED_PLATFORMS:
        return {
            "success": False,
            "platform": platform,
            "error": f"Unsupported platform: {platform}. "
            f"Supported: {', '.join(sorted(SUPPORTED_PLATFORMS))}",
        }

    # Store connection as pending (actual client not yet implemented)
    connection = PlatformConnection(
        platform=platform,
        store_url=store_url,
        status="pending",  # Will be "connected" when client is implemented
        last_connected=None,
        error_message=None,
    )

    lifespan_ctx = _get_lifespan_context(ctx)
    connections = lifespan_ctx.get("connections", {})
    connections[platform] = connection
    lifespan_ctx["connections"] = connections

    # Store credentials securely (not logged!)
    creds = lifespan_ctx.get("credentials", {})
    creds[platform] = credentials
    lifespan_ctx["credentials"] = creds

    await ctx.info(f"Platform {platform} connection stored (pending client implementation)")

    return {
        "success": True,
        "platform": platform,
        "status": "pending",
        "message": "Connection stored. Platform client not yet implemented.",
    }


async def list_orders(
    platform: str,
    ctx: Context,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List orders from a connected platform.

    Fetches orders from the specified platform with optional filtering.

    Args:
        platform: Platform identifier (shopify, woocommerce, sap, oracle)
        status: Filter by order status (pending, shipped, etc.)
        limit: Maximum number of orders to return (default: 100)
        offset: Number of orders to skip (for pagination)

    Returns:
        Dictionary with:
        - success: True if operation succeeded
        - orders: List of ExternalOrder objects
        - count: Number of orders returned
        - total: Total matching orders (if known)
        - error: Error message if failed

    Example:
        >>> result = await list_orders("shopify", ctx, status="pending", limit=50)
        >>> print(result["count"])
        25
    """
    await ctx.info(f"Fetching orders from {platform}")

    lifespan_ctx = _get_lifespan_context(ctx)
    connections = lifespan_ctx.get("connections", {})
    clients = lifespan_ctx.get("clients", {})

    # Check if platform is connected
    if platform not in connections:
        return {
            "success": False,
            "platform": platform,
            "error": f"Platform {platform} not connected. Use connect_platform first.",
        }

    # Check if client exists
    client = clients.get(platform)
    if client is None:
        return {
            "success": False,
            "platform": platform,
            "error": f"Platform {platform} client not available. Client implementation pending.",
        }

    # Build filters
    filters = OrderFilters(
        status=status,
        date_from=None,
        date_to=None,
        limit=limit,
        offset=offset,
    )

    # Fetch orders through client
    try:
        orders = await client.fetch_orders(filters)
        await ctx.info(f"Retrieved {len(orders)} orders from {platform}")

        return {
            "success": True,
            "platform": platform,
            "orders": [o.model_dump() if hasattr(o, "model_dump") else o for o in orders],
            "count": len(orders),
        }
    except Exception as e:
        return {
            "success": False,
            "platform": platform,
            "error": str(e),
        }


async def get_order(
    platform: str,
    order_id: str,
    ctx: Context,
) -> dict:
    """Get a single order by ID from a connected platform.

    Args:
        platform: Platform identifier (shopify, woocommerce, sap, oracle)
        order_id: Platform-specific order identifier

    Returns:
        Dictionary with:
        - success: True if order found
        - order: ExternalOrder object
        - error: Error message if failed

    Example:
        >>> result = await get_order("shopify", "ORD-12345", ctx)
        >>> print(result["order"]["customer_name"])
        "John Doe"
    """
    await ctx.info(f"Getting order {order_id} from {platform}")

    lifespan_ctx = _get_lifespan_context(ctx)
    connections = lifespan_ctx.get("connections", {})
    clients = lifespan_ctx.get("clients", {})

    # Check if platform is connected
    if platform not in connections:
        return {
            "success": False,
            "platform": platform,
            "order_id": order_id,
            "error": f"Platform {platform} not connected. Use connect_platform first.",
        }

    # Check if client exists
    client = clients.get(platform)
    if client is None:
        return {
            "success": False,
            "platform": platform,
            "order_id": order_id,
            "error": f"Platform {platform} client not available. Client implementation pending.",
        }

    # Fetch order through client
    try:
        order = await client.get_order(order_id)
        if order is None:
            return {
                "success": False,
                "platform": platform,
                "order_id": order_id,
                "error": f"Order {order_id} not found",
            }

        await ctx.info(f"Retrieved order {order_id} from {platform}")

        return {
            "success": True,
            "platform": platform,
            "order": order.model_dump() if hasattr(order, "model_dump") else order,
        }
    except Exception as e:
        return {
            "success": False,
            "platform": platform,
            "order_id": order_id,
            "error": str(e),
        }


async def update_tracking(
    platform: str,
    order_id: str,
    tracking_number: str,
    ctx: Context,
    carrier: str = "UPS",
) -> dict:
    """Update tracking information for an order.

    Writes tracking number and carrier back to the source platform.

    Args:
        platform: Platform identifier (shopify, woocommerce, sap, oracle)
        order_id: Platform-specific order identifier
        tracking_number: Tracking number from carrier
        carrier: Carrier name (default: UPS)

    Returns:
        Dictionary with:
        - success: True if update succeeded
        - platform: Platform identifier
        - order_id: Order identifier
        - error: Error message if failed

    Example:
        >>> result = await update_tracking(
        ...     "shopify", "ORD-12345", "1Z999AA10123456784", ctx
        ... )
        >>> print(result["success"])
        True
    """
    await ctx.info(f"Updating tracking for order {order_id} on {platform}")

    lifespan_ctx = _get_lifespan_context(ctx)
    connections = lifespan_ctx.get("connections", {})
    clients = lifespan_ctx.get("clients", {})

    # Check if platform is connected
    if platform not in connections:
        return {
            "success": False,
            "platform": platform,
            "order_id": order_id,
            "error": f"Platform {platform} not connected. Use connect_platform first.",
        }

    # Check if client exists
    client = clients.get(platform)
    if client is None:
        return {
            "success": False,
            "platform": platform,
            "order_id": order_id,
            "error": f"Platform {platform} client not available. Client implementation pending.",
        }

    # Build tracking update
    from src.mcp.external_sources.models import TrackingUpdate

    update = TrackingUpdate(
        order_id=order_id,
        tracking_number=tracking_number,
        carrier=carrier,
        tracking_url=None,
    )

    # Update through client
    try:
        success = await client.update_tracking(update)
        if success:
            await ctx.info(f"Tracking updated for order {order_id}")
            return {
                "success": True,
                "platform": platform,
                "order_id": order_id,
                "tracking_number": tracking_number,
                "carrier": carrier,
            }
        else:
            return {
                "success": False,
                "platform": platform,
                "order_id": order_id,
                "error": "Platform rejected tracking update",
            }
    except Exception as e:
        return {
            "success": False,
            "platform": platform,
            "order_id": order_id,
            "error": str(e),
        }
