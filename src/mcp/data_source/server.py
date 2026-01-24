"""FastMCP server for Data Source MCP.

Provides a Model Context Protocol server for data source operations including:
- CSV/Excel file imports
- PostgreSQL/MySQL database snapshots
- Schema discovery and type inference
- Row checksum computation for integrity

The server uses DuckDB as the in-memory analytics engine for unified SQL
access across all source types.

Per RESEARCH.md:
- Use FastMCP v2 (stable) with lifespan context
- DuckDB in-memory connection shared across tools
- NEVER use print() - use ctx.info() for logging

Per CONTEXT.md:
- One source at a time (import replaces previous)
- Ephemeral session model (data gone when session ends)
"""

from contextlib import asynccontextmanager
from typing import Any

import duckdb
from fastmcp import FastMCP


@asynccontextmanager
async def lifespan(app: Any):
    """Initialize DuckDB connection and session state.

    Resources yielded are available to all tools via ctx.lifespan_context:
    - db: DuckDB connection for SQL operations
    - current_source: Metadata about currently loaded source (or None)
    - type_overrides: Per-column type overrides from user

    The connection is closed when the server shuts down.
    """
    # Create in-memory DuckDB connection
    conn = duckdb.connect(":memory:")

    # Install extensions for database connectivity
    # These are loaded lazily when first used
    conn.execute("INSTALL postgres; INSTALL mysql;")
    conn.execute("LOAD postgres; LOAD mysql;")

    yield {
        "db": conn,
        "current_source": None,  # Track active source metadata
        "type_overrides": {},  # Per-column type overrides
    }

    # Cleanup on shutdown
    conn.close()


# Create the FastMCP server instance
# Name: "DataSource" - identifies this server in MCP discovery
# lifespan: Manages DuckDB connection lifecycle
mcp = FastMCP("DataSource", lifespan=lifespan)


# Import and register tools
from src.mcp.data_source.tools.checksum_tools import (
    compute_checksums,
    verify_checksum,
)
from src.mcp.data_source.tools.import_tools import (
    import_csv,
    import_database,
    import_excel,
    list_sheets,
    list_tables,
)
from src.mcp.data_source.tools.query_tools import (
    get_row,
    get_rows_by_filter,
    query_data,
)
from src.mcp.data_source.tools.schema_tools import (
    get_schema,
    override_column_type,
)

# Register as MCP tools using decorator pattern
mcp.tool()(compute_checksums)
mcp.tool()(import_csv)
mcp.tool()(import_database)
mcp.tool()(import_excel)
mcp.tool()(list_sheets)
mcp.tool()(list_tables)
mcp.tool()(get_row)
mcp.tool()(get_rows_by_filter)
mcp.tool()(query_data)
mcp.tool()(get_schema)
mcp.tool()(override_column_type)
mcp.tool()(verify_checksum)


if __name__ == "__main__":
    # Run server with stdio transport for MCP communication
    mcp.run(transport="stdio")
