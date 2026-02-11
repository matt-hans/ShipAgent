"""MCP server configuration for the Orchestration Agent.

This module defines how MCP servers are spawned as child processes via stdio.
The configurations are used by ClaudeAgentOptions when initializing the agent.

Configuration includes:
    - Data MCP: Python-based server for data source operations
    - Shopify MCP: Node.js-based server for Shopify order retrieval (via npx)
    - External Sources MCP: Python-based unified gateway for external platforms

Note: UPS integration is now a direct Python import (UPSService) rather than
a subprocess MCP server. See src/services/ups_service.py.

Environment Variables:
    SHOPIFY_ACCESS_TOKEN: Admin API access token from custom app (required for Shopify MCP)
    SHOPIFY_STORE_DOMAIN: Store domain e.g. mystore.myshopify.com (required for Shopify MCP)
"""

import os
import sys
from pathlib import Path
from typing import TypedDict

# Project root is parent of src/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class MCPServerConfig(TypedDict):
    """Configuration for spawning an MCP server as a child process.

    Attributes:
        command: Executable to run (e.g., "python3" or "node")
        args: Command line arguments passed to the executable
        env: Environment variables for the child process
    """

    command: str
    args: list[str]
    env: dict[str, str]


def get_data_mcp_config() -> MCPServerConfig:
    """Get configuration for the Data Source MCP server.

    The Data MCP runs as a Python module using FastMCP with stdio transport.
    PYTHONPATH is set to PROJECT_ROOT to enable proper module imports.

    Returns:
        MCPServerConfig with Python command and module path
    """
    return MCPServerConfig(
        command="python3",
        args=["-m", "src.mcp.data_source.server"],
        env={"PYTHONPATH": str(PROJECT_ROOT)},
    )


def get_shopify_mcp_config() -> MCPServerConfig:
    """Get configuration for the Shopify MCP server.

    The Shopify MCP runs via npx with stdio transport.
    Credentials are passed as command line arguments.

    Warnings are logged to stderr if required credentials are missing,
    but configuration proceeds (the MCP will fail with a clear error).

    Returns:
        MCPServerConfig with npx command and shopify-mcp args

    Environment Variables:
        SHOPIFY_ACCESS_TOKEN: Required - Admin API access token from custom app
        SHOPIFY_STORE_DOMAIN: Required - Store domain (e.g., mystore.myshopify.com)
    """
    access_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    store_domain = os.environ.get("SHOPIFY_STORE_DOMAIN")

    # Check for required credentials and warn if missing
    missing_vars = []
    if not access_token:
        missing_vars.append("SHOPIFY_ACCESS_TOKEN")
    if not store_domain:
        missing_vars.append("SHOPIFY_STORE_DOMAIN")

    if missing_vars:
        print(
            f"[config] WARNING: Missing Shopify credentials: {', '.join(missing_vars)}. "
            "Shopify MCP will fail on startup.",
            file=sys.stderr,
        )

    return MCPServerConfig(
        command="npx",
        args=[
            "shopify-mcp",
            "--accessToken",
            access_token or "",
            "--domain",
            store_domain or "",
        ],
        env={
            "PATH": os.environ.get("PATH", ""),
        },
    )


def get_external_sources_mcp_config() -> MCPServerConfig:
    """Get configuration for the External Sources Gateway MCP server.

    The External Sources MCP runs as a Python module using FastMCP with stdio transport.
    PYTHONPATH is set to PROJECT_ROOT to enable proper module imports.

    This MCP provides unified access to external platforms:
    - Shopify (Admin API)
    - WooCommerce (REST API)
    - SAP (OData)
    - Oracle (Database)

    Returns:
        MCPServerConfig with Python command and module path
    """
    return MCPServerConfig(
        command="python3",
        args=["-m", "src.mcp.external_sources.server"],
        env={"PYTHONPATH": str(PROJECT_ROOT)},
    )


def create_mcp_servers_config() -> dict[str, MCPServerConfig]:
    """Create MCP server configurations for ClaudeAgentOptions.

    Returns a dictionary mapping server names to their configurations,
    suitable for passing to ClaudeAgentOptions.mcp_servers.

    Returns:
        Dict with "data", "shopify", and "external" server configurations.
        Note: UPS is now a direct Python import, not a subprocess MCP.

    Example:
        >>> config = create_mcp_servers_config()
        >>> print(config["data"]["command"])
        "python3"
        >>> print(config["shopify"]["command"])
        "npx"
        >>> print(config["external"]["command"])
        "python3"
    """
    return {
        "data": get_data_mcp_config(),
        "shopify": get_shopify_mcp_config(),
        "external": get_external_sources_mcp_config(),
    }
