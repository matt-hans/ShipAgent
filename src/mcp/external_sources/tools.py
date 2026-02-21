"""MCP tools for External Sources Gateway.

Provides unified interface for connecting to and fetching
data from external platforms (Shopify, WooCommerce, SAP, Oracle).
"""

from datetime import UTC, datetime

from fastmcp import Context

from src.mcp.external_sources.models import (
    OrderFilters,
    PlatformConnection,
    PlatformType,
)

SUPPORTED_PLATFORMS = {p.value for p in PlatformType}

# Maps platform name to the credential key expected for the store/instance URL.
# Shopify: "store_url", WooCommerce: "site_url", SAP: "base_url", Oracle: none.
_URL_KEY_MAP = {
    "shopify": "store_url",
    "woocommerce": "site_url",
    "sap": "base_url",
}


def _create_platform_client(platform: str):
    """Create platform client instance based on platform type.

    All platform clients use no-arg constructors. Credentials
    (including store URLs) are passed separately to authenticate().

    Args:
        platform: Platform identifier.

    Returns:
        Platform client instance (unauthenticated).

    Raises:
        ValueError: If platform is unsupported.
    """
    if platform == "shopify":
        from src.mcp.external_sources.clients.shopify import ShopifyClient
        return ShopifyClient()
    elif platform == "woocommerce":
        from src.mcp.external_sources.clients.woocommerce import WooCommerceClient
        return WooCommerceClient()
    elif platform == "sap":
        from src.mcp.external_sources.clients.sap import SAPClient
        return SAPClient()
    elif platform == "oracle":
        from src.mcp.external_sources.clients.oracle import OracleClient
        return OracleClient()
    else:
        raise ValueError(f"No client implementation for platform: {platform}")


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

    if platform not in SUPPORTED_PLATFORMS:
        return {
            "success": False,
            "platform": platform,
            "error": f"Unsupported platform: {platform}. "
            f"Supported: {', '.join(sorted(SUPPORTED_PLATFORMS))}",
        }

    lifespan_ctx = _get_lifespan_context(ctx)

    # Store credentials securely (not logged!)
    creds = lifespan_ctx.get("credentials", {})
    creds[platform] = credentials
    lifespan_ctx["credentials"] = creds

    # Instantiate and authenticate.
    # All clients use no-arg __init__. store_url is mapped to the
    # platform-specific credential key for authenticate().
    try:
        client = _create_platform_client(platform)
        auth_creds = dict(credentials)
        url_key = _URL_KEY_MAP.get(platform)
        if store_url and url_key:
            auth_creds.setdefault(url_key, store_url)
        auth_ok = await client.authenticate(auth_creds)
        if not auth_ok:
            raise ValueError(
                f"Authentication returned False for {platform}. "
                "Check credentials and try again."
            )
    except Exception as e:
        connection = PlatformConnection(
            platform=platform,
            store_url=store_url,
            status="error",
            last_connected=None,
            error_message=str(e),
        )
        connections = lifespan_ctx.get("connections", {})
        connections[platform] = connection
        lifespan_ctx["connections"] = connections
        return {
            "success": False,
            "platform": platform,
            "status": "error",
            "error": str(e),
        }

    # Store authenticated client and connection
    clients = lifespan_ctx.get("clients", {})
    clients[platform] = client
    lifespan_ctx["clients"] = clients

    now = datetime.now(UTC).isoformat()
    connection = PlatformConnection(
        platform=platform,
        store_url=store_url,
        status="connected",
        last_connected=now,
        error_message=None,
    )
    connections = lifespan_ctx.get("connections", {})
    connections[platform] = connection
    lifespan_ctx["connections"] = connections

    await ctx.info(f"Platform {platform} connected successfully")

    return {
        "success": True,
        "platform": platform,
        "status": "connected",
    }


async def disconnect_platform(platform: str, ctx: Context) -> dict:
    """Disconnect from a platform, removing client and connection state.

    Pops the client, connection, and credentials from lifespan context.
    Calls client.close() if the method exists.

    Args:
        platform: Platform identifier to disconnect.

    Returns:
        Dict with success status.
    """
    lifespan_ctx = _get_lifespan_context(ctx)
    clients = lifespan_ctx.get("clients", {})
    connections = lifespan_ctx.get("connections", {})
    credentials = lifespan_ctx.get("credentials", {})

    client = clients.pop(platform, None)
    connections.pop(platform, None)
    credentials.pop(platform, None)

    if client is not None and hasattr(client, "close"):
        try:
            await client.close()
        except Exception:
            pass

    await ctx.info(f"Platform {platform} disconnected")
    return {"success": True, "platform": platform, "status": "disconnected"}


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


async def validate_credentials(
    platform: str,
    credentials: dict,
    ctx: Context,
    store_url: str | None = None,
) -> dict:
    """Validate platform credentials without mutating shared state.

    Creates a temporary client, authenticates, and optionally fetches
    shop metadata. Does NOT store credentials, clients, or connections
    in lifespan context — purely read-only.

    Args:
        platform: Platform identifier (e.g., 'shopify').
        credentials: Platform-specific credentials.
        store_url: Store/instance URL.

    Returns:
        Dictionary with:
        - valid: True if credentials authenticated successfully
        - platform: Platform identifier
        - shop: Shop metadata dict (if available, Shopify only)
        - error: Error message if validation failed
    """
    await ctx.info(f"Validating credentials for {platform} (read-only)")

    if platform not in SUPPORTED_PLATFORMS:
        return {
            "valid": False,
            "platform": platform,
            "error": f"Unsupported platform: {platform}.",
        }

    client = None
    try:
        client = _create_platform_client(platform)
        auth_creds = dict(credentials)
        url_key = _URL_KEY_MAP.get(platform)
        if store_url and url_key:
            auth_creds.setdefault(url_key, store_url)
        auth_ok = await client.authenticate(auth_creds)
        if not auth_ok:
            return {
                "valid": False,
                "platform": platform,
                "error": "Authentication failed — check credentials.",
            }

        # Best-effort shop metadata (Shopify only)
        shop = None
        if hasattr(client, "get_shop_info"):
            try:
                shop = await client.get_shop_info()
            except Exception:
                pass

        return {"valid": True, "platform": platform, "shop": shop}
    except Exception as e:
        return {"valid": False, "platform": platform, "error": str(e)}
    finally:
        if client is not None and hasattr(client, "close"):
            try:
                await client.close()
            except Exception:
                pass


async def get_shop_info(platform: str, ctx: Context) -> dict:
    """Get shop/store metadata from a connected platform.

    Returns store details such as name, address, and contact info.
    Currently supported for Shopify only.

    Args:
        platform: Platform identifier (e.g., 'shopify').

    Returns:
        Dictionary with:
        - success: True if shop info retrieved
        - shop: Shop metadata dict (name, address, etc.)
        - error: Error message if failed
    """
    await ctx.info(f"Getting shop info from {platform}")

    lifespan_ctx = _get_lifespan_context(ctx)
    clients = lifespan_ctx.get("clients", {})

    client = clients.get(platform)
    if client is None:
        return {
            "success": False,
            "platform": platform,
            "error": f"Platform {platform} not connected.",
        }

    if not hasattr(client, "get_shop_info"):
        return {
            "success": False,
            "platform": platform,
            "error": f"get_shop_info not supported for {platform}.",
        }

    try:
        shop = await client.get_shop_info()
        if shop is None:
            return {
                "success": False,
                "platform": platform,
                "error": "Failed to retrieve shop info.",
            }
        return {"success": True, "platform": platform, "shop": shop}
    except Exception as e:
        return {"success": False, "platform": platform, "error": str(e)}


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
