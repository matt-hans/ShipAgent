# src/mcp/platforms/woocommerce/constants.py
"""WooCommerce API constants and configuration."""

API_VERSION = "wc/v3"
PLATFORM_ID = "woocommerce"
CONTRACT_VERSION = "1.0"
SERVER_VERSION = "1.0.0"

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50

PAGING_STRATEGY = "offset"
OVERLAP_SECONDS = 300

RATE_LIMIT_PER_SECOND = 5
MAX_CONCURRENCY = 5

SUPPORTED_TOOLS = [
    "orders.list",
    "orders.get",
    "tracking.write_back",
]
