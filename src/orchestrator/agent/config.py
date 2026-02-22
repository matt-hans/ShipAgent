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

Credential resolution:
    UPS credentials are resolved via runtime_credentials adapter (DB priority,
    env var fallback). Direct env var reads for UPS_CLIENT_ID/UPS_CLIENT_SECRET
    should not occur outside runtime_credentials.py.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from src.services.connection_types import UPSCredentials

logger = logging.getLogger(__name__)

from src.services.ups_specs import ensure_ups_specs_dir  # noqa: E402

# Project root is parent of src/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
VENV_PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python3")


def _get_python_command() -> str:
    """Return the preferred Python interpreter for MCP subprocesses.

    Honors MCP_PYTHON_PATH when explicitly configured.
    Prioritizes the project virtual environment to ensure all MCP
    subprocesses use the same dependency set as the backend.
    Falls back to the current interpreter when .venv Python is missing.
    """
    override = os.environ.get("MCP_PYTHON_PATH", "").strip()
    if override:
        return override
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



def get_ups_mcp_config(
    credentials: "UPSCredentials | None" = None,
) -> MCPServerConfig | None:
    """Get configuration for the UPS MCP server.

    The UPS MCP runs as a Python module from the local ups-mcp fork
    (installed as editable package in .venv) with stdio transport.

    When credentials are provided (from DB or runtime_credentials adapter),
    they are used directly. Otherwise falls back to env vars for backward
    compatibility during migration.

    Args:
        credentials: Typed UPS credentials from runtime_credentials adapter.
            When None, falls back to env vars (deprecated path).

    Returns:
        MCPServerConfig, or None if no credentials are available.
    """
    if credentials is not None:
        client_id = credentials.client_id
        client_secret = credentials.client_secret
        environment = credentials.environment
    else:
        # Legacy env var fallback — will be removed after full migration
        client_id = os.environ.get("UPS_CLIENT_ID", "")
        client_secret = os.environ.get("UPS_CLIENT_SECRET", "")
        base_url = os.environ.get("UPS_BASE_URL", "https://wwwcie.ups.com")
        environment = "test" if "wwwcie" in base_url else "production"

    if not client_id or not client_secret:
        logger.warning(
            "No UPS credentials available. UPS MCP server will not be started. "
            "Configure UPS in Settings to enable shipping operations."
        )
        return None

    specs_dir = ensure_ups_specs_dir()

    # Security note (F-10, CWE-214): UPS credentials are passed as env vars
    # to the subprocess. This is an accepted risk — the MCP subprocess is a
    # trusted internal child process, not a user-facing container.
    # Mitigations: Docker --pid=private isolates /proc, single-user model
    # means no cross-user process enumeration, and credentials are
    # short-lived tokens resolved from the DB at session creation time.
    return MCPServerConfig(
        command=_get_python_command(),
        args=["-m", "ups_mcp"],
        env={
            "CLIENT_ID": client_id,
            "CLIENT_SECRET": client_secret,
            "ENVIRONMENT": environment,
            "UPS_ACCOUNT_NUMBER": os.environ.get("UPS_ACCOUNT_NUMBER", ""),
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


def create_mcp_servers_config(
    ups_credentials: "UPSCredentials | None" = None,
) -> dict[str, MCPServerConfig]:
    """Create MCP server configurations for ClaudeAgentOptions.

    Returns a dictionary mapping server names to their configurations,
    suitable for passing to ClaudeAgentOptions.mcp_servers.

    Args:
        ups_credentials: Typed UPS credentials. When None, UPS MCP config
            falls back to env vars or may be omitted entirely.

    Returns:
        Dict with server configurations. UPS key is omitted if no credentials.
    """
    configs: dict[str, MCPServerConfig] = {
        "data": get_data_mcp_config(),
        "external": get_external_sources_mcp_config(),
    }
    ups_config = get_ups_mcp_config(credentials=ups_credentials)
    if ups_config is not None:
        configs["ups"] = ups_config
    return configs
