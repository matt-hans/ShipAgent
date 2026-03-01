# src/mcp/platforms/sap/constants.py
"""SAP OData platform constants and configuration."""

PLATFORM_ID = "sap"
CONTRACT_VERSION = "1.0"
SERVER_VERSION = "1.0.0"

# SAP OData page limits
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50

# Paging strategy: SAP OData uses $skip/$top (offset-based)
PAGING_STRATEGY = "offset"
OVERLAP_SECONDS = 600  # 10 minutes for SAP replication lag

# Rate limits (SAP OData: ~10 req/sec typical)
RATE_LIMIT_PER_SECOND = 10
MAX_CONCURRENCY = 5

# Supported tool names
SUPPORTED_TOOLS = [
    "orders.list",
    "orders.get",
    "tracking.write_back",
]
