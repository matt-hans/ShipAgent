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


# Tools will be registered here in subsequent plans using @mcp.tool decorator
# Example:
#   @mcp.tool
#   async def import_csv(file_path: str, ctx: Context) -> dict:
#       db = ctx.lifespan_context.get("db")
#       ...


if __name__ == "__main__":
    # Run server with stdio transport for MCP communication
    mcp.run(transport="stdio")
