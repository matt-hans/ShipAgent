# src/mcp/platforms/shopify/constants.py
"""Shopify API constants and configuration."""

API_VERSION = "2024-01"
PLATFORM_ID = "shopify"
CONTRACT_VERSION = "1.0"
SERVER_VERSION = "1.0.0"

# Shopify hard limits
MAX_PAGE_SIZE = 250
DEFAULT_PAGE_SIZE = 50

# Paging strategy
PAGING_STRATEGY = "cursor"
OVERLAP_SECONDS = 300  # 5 minutes for watermark overlap

# Rate limits (Shopify: 2 req/sec for REST, burst 40)
RATE_LIMIT_PER_SECOND = 2
MAX_CONCURRENCY = 3

# Supported tool names
SUPPORTED_TOOLS = [
    "orders.list",
    "orders.get",
    "tracking.write_back",
]
