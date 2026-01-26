"""MCP server configuration for the Orchestration Agent.

This module defines how MCP servers are spawned as child processes via stdio.
The configurations are used by ClaudeAgentOptions when initializing the agent.

Configuration includes:
    - Data MCP: Python-based server for data source operations
    - UPS MCP: Node.js-based server for UPS shipping API integration
    - Shopify MCP: Node.js-based server for Shopify order retrieval (via npx)
    - External Sources MCP: Python-based unified gateway for external platforms

Environment Variables:
    UPS_CLIENT_ID: UPS API client ID (required for UPS MCP)
    UPS_CLIENT_SECRET: UPS API client secret (required for UPS MCP)
    UPS_ACCOUNT_NUMBER: UPS shipper account number (required for UPS MCP)
    UPS_LABELS_OUTPUT_DIR: Directory for label output (defaults to PROJECT_ROOT/labels)
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


def get_ups_mcp_config() -> MCPServerConfig:
    """Get configuration for the UPS MCP server.

    The UPS MCP runs as a Node.js application with stdio transport.
    UPS credentials are passed through environment variables.

    Warnings are logged to stderr if required credentials are missing,
    but configuration proceeds (the MCP will fail with a clear error).

    Returns:
        MCPServerConfig with Node command and dist path

    Environment Variables:
        UPS_CLIENT_ID: Required - UPS API client ID
        UPS_CLIENT_SECRET: Required - UPS API client secret
        UPS_ACCOUNT_NUMBER: Required - UPS shipper account number
        UPS_LABELS_OUTPUT_DIR: Optional - defaults to PROJECT_ROOT/labels
    """
    # Check for required UPS credentials and warn if missing
    required_vars = ["UPS_CLIENT_ID", "UPS_CLIENT_SECRET", "UPS_ACCOUNT_NUMBER"]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]

    if missing_vars:
        print(
            f"[config] WARNING: Missing UPS credentials: {', '.join(missing_vars)}. "
            "UPS MCP will fail on startup.",
            file=sys.stderr,
        )

    # Build environment for UPS MCP child process
    # Pass through UPS credentials from current environment
    env: dict[str, str] = {}

    if client_id := os.environ.get("UPS_CLIENT_ID"):
        env["UPS_CLIENT_ID"] = client_id

    if client_secret := os.environ.get("UPS_CLIENT_SECRET"):
        env["UPS_CLIENT_SECRET"] = client_secret

    if account_number := os.environ.get("UPS_ACCOUNT_NUMBER"):
        env["UPS_ACCOUNT_NUMBER"] = account_number

    # Labels output directory: use env var or default to PROJECT_ROOT/labels
    labels_dir = os.environ.get("UPS_LABELS_OUTPUT_DIR", str(PROJECT_ROOT / "labels"))
    env["UPS_LABELS_OUTPUT_DIR"] = labels_dir

    return MCPServerConfig(
        command="node",
        args=[str(PROJECT_ROOT / "packages" / "ups-mcp" / "dist" / "index.js")],
        env=env,
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
        Dict with "data", "ups", "shopify", and "external" server configurations

    Example:
        >>> config = create_mcp_servers_config()
        >>> print(config["data"]["command"])
        "python3"
        >>> print(config["ups"]["command"])
        "node"
        >>> print(config["shopify"]["command"])
        "npx"
        >>> print(config["external"]["command"])
        "python3"
    """
    return {
        "data": get_data_mcp_config(),
        "ups": get_ups_mcp_config(),
        "shopify": get_shopify_mcp_config(),
        "external": get_external_sources_mcp_config(),
    }
