"""MCP server configuration for the Orchestration Agent.

This module defines how MCP servers are spawned as child processes via stdio.
The configurations are used by ClaudeAgentOptions when initializing the agent.

Configuration includes:
    - Data MCP: Python-based server for data source operations
    - Shopify MCP: Node.js-based server for Shopify order retrieval (via npx)
    - External Sources MCP: Python-based unified gateway for external platforms
    - UPS MCP: UPS API server for shipping, rating, tracking, address validation
      (local fork, run as Python module via .venv)

Hybrid UPS architecture:
    - Interactive path: Agent calls UPS MCP tools directly for ad-hoc operations
      (rate checks, address validation, tracking, label recovery, transit times)
    - Batch path: BatchEngine uses UPSMCPClient (programmatic MCP over stdio)
      for deterministic high-volume execution with per-row state tracking

Environment Variables:
    SHOPIFY_ACCESS_TOKEN: Admin API access token from custom app (required for Shopify MCP)
    SHOPIFY_STORE_DOMAIN: Store domain e.g. mystore.myshopify.com (required for Shopify MCP)
    UPS_CLIENT_ID: UPS OAuth client ID (required for UPS MCP)
    UPS_CLIENT_SECRET: UPS OAuth client secret (required for UPS MCP)
    UPS_BASE_URL: UPS API base URL — used to derive environment (test vs production)
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)
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
        logger.warning(
            "Missing Shopify credentials: %s. Shopify MCP will fail on startup.",
            ", ".join(missing_vars),
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


def get_ups_mcp_config() -> MCPServerConfig:
    """Get configuration for the UPS MCP server.

    The UPS MCP runs as a Python module from the local ups-mcp fork
    (installed as editable package in .venv) with stdio transport.
    It provides 7 tools: track_package, validate_address, rate_shipment,
    create_shipment, void_shipment, recover_label, get_time_in_transit.

    This gives the agent interactive access to UPS operations. The deterministic
    batch path (BatchEngine + UPSMCPClient) uses the same local fork for
    high-volume execution with per-row state tracking.

    Returns:
        MCPServerConfig with venv Python command to run ups-mcp module

    Environment Variables:
        UPS_CLIENT_ID: Required - UPS OAuth client ID
        UPS_CLIENT_SECRET: Required - UPS OAuth client secret
        UPS_BASE_URL: Optional - determines test vs production environment
            (defaults to test if URL contains 'wwwcie', otherwise production)
    """
    client_id = os.environ.get("UPS_CLIENT_ID")
    client_secret = os.environ.get("UPS_CLIENT_SECRET")
    base_url = os.environ.get("UPS_BASE_URL", "https://wwwcie.ups.com")

    # Derive environment from base URL
    environment = "test" if "wwwcie" in base_url else "production"

    # Check for required credentials and warn if missing
    missing_vars = []
    if not client_id:
        missing_vars.append("UPS_CLIENT_ID")
    if not client_secret:
        missing_vars.append("UPS_CLIENT_SECRET")

    if missing_vars:
        logger.warning(
            "Missing UPS credentials: %s. UPS MCP will fail on startup.",
            ", ".join(missing_vars),
        )

    # Use the venv Python to run the local ups-mcp fork as a module
    venv_python = str(PROJECT_ROOT / ".venv" / "bin" / "python3")

    return MCPServerConfig(
        command=venv_python,
        args=["-m", "ups_mcp"],
        env={
            "CLIENT_ID": client_id or "",
            "CLIENT_SECRET": client_secret or "",
            "ENVIRONMENT": environment,
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
        Dict with "data", "shopify", "external", and "ups" server configurations.

    Example:
        >>> config = create_mcp_servers_config()
        >>> print(config["data"]["command"])
        "python3"
        >>> print(config["shopify"]["command"])
        "npx"
        >>> print(config["ups"]["args"])
        ["-m", "ups_mcp"]
    """
    return {
        "data": get_data_mcp_config(),
        "shopify": get_shopify_mcp_config(),
        "external": get_external_sources_mcp_config(),
        "ups": get_ups_mcp_config(),
    }
