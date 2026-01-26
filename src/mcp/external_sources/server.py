"""FastMCP server for External Sources Gateway.

Provides unified access to external platform MCP servers
(Shopify, WooCommerce, SAP, Oracle) through a consistent interface.

The server manages:
- Platform connections and credentials (securely stored)
- Client instances for each platform
- Order fetching with filtering
- Tracking number write-back
"""

from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP


@asynccontextmanager
async def lifespan(app: Any):
    """Initialize session state for platform connections.

    Resources yielded are available to all tools via ctx.lifespan_context:
    - connections: Dict of PlatformConnection objects by platform name
    - clients: Dict of PlatformClient instances by platform name
    - credentials: Dict of credentials by platform name (NEVER logged!)
    """
    yield {
        "connections": {},  # platform -> PlatformConnection
        "clients": {},  # platform -> PlatformClient instance
        "credentials": {},  # platform -> credentials dict (NEVER LOG!)
    }


# Create the FastMCP server instance
mcp = FastMCP(name="ExternalSources", lifespan=lifespan)


# Import and register tools
from src.mcp.external_sources.tools import (
    connect_platform,
    get_order,
    list_connections,
    list_orders,
    update_tracking,
)

# Register as MCP tools using decorator pattern
mcp.tool()(list_connections)
mcp.tool()(connect_platform)
mcp.tool()(list_orders)
mcp.tool()(get_order)
mcp.tool()(update_tracking)


if __name__ == "__main__":
    # Run server with stdio transport for MCP communication
    mcp.run(transport="stdio")
