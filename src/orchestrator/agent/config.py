"""MCP server configuration for the Orchestration Agent.

This module defines how MCP servers are spawned as child processes via stdio.
The configurations are used by ClaudeAgentOptions when initializing the agent.

Configuration includes:
    - Data MCP: Python-based server for data source operations
    - UPS MCP: Node.js-based server for UPS shipping API integration

Environment Variables:
    UPS_CLIENT_ID: UPS API client ID (required for UPS MCP)
    UPS_CLIENT_SECRET: UPS API client secret (required for UPS MCP)
    UPS_ACCOUNT_NUMBER: UPS shipper account number (required for UPS MCP)
    UPS_LABELS_OUTPUT_DIR: Directory for label output (defaults to PROJECT_ROOT/labels)
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


def create_mcp_servers_config() -> dict[str, MCPServerConfig]:
    """Create MCP server configurations for ClaudeAgentOptions.

    Returns a dictionary mapping server names to their configurations,
    suitable for passing to ClaudeAgentOptions.mcp_servers.

    Returns:
        Dict with "data" and "ups" server configurations

    Example:
        >>> config = create_mcp_servers_config()
        >>> print(config["data"]["command"])
        "python3"
        >>> print(config["ups"]["command"])
        "node"
    """
    return {
        "data": get_data_mcp_config(),
        "ups": get_ups_mcp_config(),
    }
