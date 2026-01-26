"""FastMCP server for External Sources Gateway.

Provides unified access to external platform MCP servers
(Shopify, WooCommerce, SAP, Oracle) through a consistent interface.
"""

from fastmcp import FastMCP

mcp = FastMCP(name="ExternalSources")


# Tools will be added in Task 2.3
