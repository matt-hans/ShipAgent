# src/mcp/platforms/amazon/constants.py
"""Amazon SP-API constants and configuration."""

API_VERSION = "2022-05-01"  # Amazon SP-API Orders version
PLATFORM_ID = "amazon"
CONTRACT_VERSION = "1.0"
SERVER_VERSION = "1.0.0"

# Amazon hard limits
MAX_PAGE_SIZE = 100  # SP-API Orders limit
DEFAULT_PAGE_SIZE = 50

# Paging strategy
PAGING_STRATEGY = "cursor"  # NextToken-based
OVERLAP_SECONDS = 300

# Rate limits (Amazon SP-API: 1 request/sec burst for getOrders)
RATE_LIMIT_PER_SECOND = 1
MAX_CONCURRENCY = 2

# LWA (Login with Amazon) endpoint
LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"

# SP-API base URLs by region
BASE_URLS = {
    "na": "https://sellingpartnerapi-na.amazon.com",
    "eu": "https://sellingpartnerapi-eu.amazon.com",
    "fe": "https://sellingpartnerapi-fe.amazon.com",
}

SANDBOX_BASE_URLS = {
    "na": "https://sandbox.sellingpartnerapi-na.amazon.com",
    "eu": "https://sandbox.sellingpartnerapi-eu.amazon.com",
    "fe": "https://sandbox.sellingpartnerapi-fe.amazon.com",
}

# Token refresh buffer (seconds before expiry to refresh)
TOKEN_REFRESH_BUFFER_SECONDS = 300  # 5 minutes

# Supported tool names
SUPPORTED_TOOLS = [
    "orders.list",
    "orders.get",
    "tracking.write_back",
]
