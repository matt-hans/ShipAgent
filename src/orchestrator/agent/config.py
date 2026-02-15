"""MCP server configuration for the Orchestration Agent.

This module defines how MCP servers are spawned as child processes via stdio.
The configurations are used by ClaudeAgentOptions when initializing the agent.

Configuration includes:
    - Data MCP: Python-based server for data source operations
    - External Sources MCP: Python-based unified gateway for external platforms
    - UPS MCP: UPS API server for shipping, rating, tracking, address validation
      (local fork, run as Python module via .venv)

Hybrid UPS architecture:
    - Interactive path: Agent calls UPS MCP tools directly for ad-hoc operations
      (rate checks, address validation, tracking, label recovery, transit times)
    - Batch path: BatchEngine uses UPSMCPClient (programmatic MCP over stdio)
      for deterministic high-volume execution with per-row state tracking

Environment Variables:
    UPS_CLIENT_ID: UPS OAuth client ID (required for UPS MCP)
    UPS_CLIENT_SECRET: UPS OAuth client secret (required for UPS MCP)
    UPS_BASE_URL: UPS API base URL — used to derive environment (test vs production)
"""

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
from typing import TypedDict

from src.services.ups_specs import ensure_ups_specs_dir

# Project root is parent of src/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
VENV_PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python3")


def _get_python_command() -> str:
    """Return the preferred Python interpreter for MCP subprocesses.

    Prioritizes the project virtual environment to ensure all MCP
    subprocesses use the same dependency set as the backend.
    Falls back to the current interpreter when .venv Python is missing.
    """
    if os.path.exists(VENV_PYTHON):
        return VENV_PYTHON
    return sys.executable


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
        command=_get_python_command(),
        args=["-m", "src.mcp.data_source.server"],
        env={
            "PYTHONPATH": str(PROJECT_ROOT),
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
    specs_dir = ensure_ups_specs_dir()

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
    return MCPServerConfig(
        command=_get_python_command(),
        args=["-m", "ups_mcp"],
        env={
            "CLIENT_ID": client_id or "",
            "CLIENT_SECRET": client_secret or "",
            "ENVIRONMENT": environment,
            "UPS_MCP_SPECS_DIR": specs_dir,
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
        command=_get_python_command(),
        args=["-m", "src.mcp.external_sources.server"],
        env={
            "PYTHONPATH": str(PROJECT_ROOT),
            "PATH": os.environ.get("PATH", ""),
        },
    )


def create_mcp_servers_config() -> dict[str, MCPServerConfig]:
    """Create MCP server configurations for ClaudeAgentOptions.

    Returns a dictionary mapping server names to their configurations,
    suitable for passing to ClaudeAgentOptions.mcp_servers.

    Returns:
        Dict with "data", "external", and "ups" server configurations.

    Example:
        >>> config = create_mcp_servers_config()
        >>> print(config["data"]["command"])
        "python3"
        >>> print(config["ups"]["args"])
        ["-m", "ups_mcp"]
    """
    return {
        "data": get_data_mcp_config(),
        "external": get_external_sources_mcp_config(),
        "ups": get_ups_mcp_config(),
    }
