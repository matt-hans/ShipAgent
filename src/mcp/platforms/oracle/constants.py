# src/mcp/platforms/oracle/constants.py
"""Oracle platform constants and configuration.

All Oracle-specific limits, defaults, and identifiers live here.
Import everywhere — never scatter magic numbers.
"""

PLATFORM_ID = "oracle"
CONTRACT_VERSION = "1.0"
SERVER_VERSION = "1.0.0"

# Oracle paging uses SQL OFFSET/FETCH (12c+ syntax)
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

# Paging strategy: offset-based (not cursor-based)
PAGING_STRATEGY = "offset"
OVERLAP_SECONDS = 600  # 10 minutes for watermark overlap

# Oracle DB connection pooling limits
RATE_LIMIT_PER_SECOND = 20
MAX_CONCURRENCY = 10

# Supported tool names
SUPPORTED_TOOLS = [
    "orders.list",
    "orders.get",
    "tracking.write_back",
]
