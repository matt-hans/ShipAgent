"""Platform client implementations."""

from src.mcp.external_sources.clients.base import PlatformClient
from src.mcp.external_sources.clients.oracle import (
    OracleClient,
    OracleDependencyError,
    DEFAULT_TABLE_CONFIG,
)
from src.mcp.external_sources.clients.sap import SAPClient
from src.mcp.external_sources.clients.shopify import ShopifyClient
from src.mcp.external_sources.clients.woocommerce import (
    WooCommerceClient,
    WooCommerceAuthError,
    WooCommerceAPIError,
)

__all__ = [
    "PlatformClient",
    "OracleClient",
    "OracleDependencyError",
    "DEFAULT_TABLE_CONFIG",
    "SAPClient",
    "ShopifyClient",
    "WooCommerceClient",
    "WooCommerceAuthError",
    "WooCommerceAPIError",
]
