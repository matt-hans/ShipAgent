"""Orchestration Agent package for ShipAgent.

This package contains the Orchestration Agent that uses the Claude Agent SDK
to coordinate MCP servers for natural language shipment processing.

Architecture:
    The agent spawns MCP servers as child processes via stdio transport:
    - Data MCP: Data source operations (CSV, Excel, database imports)
    - UPS MCP: UPS shipping operations (create, void, rate, track)

    The Claude Agent SDK manages the LLM interactions and tool execution,
    while this package provides configuration and orchestration logic.

Modules:
    config: MCP server configuration for ClaudeAgentOptions

Exports:
    PROJECT_ROOT: Path to project root directory
    MCPServerConfig: TypedDict for MCP server spawn configuration
    get_data_mcp_config: Returns Data MCP configuration
    get_ups_mcp_config: Returns UPS MCP configuration
    create_mcp_servers_config: Returns combined MCP server configurations
"""

from src.orchestrator.agent.config import (
    PROJECT_ROOT,
    MCPServerConfig,
    get_data_mcp_config,
    get_ups_mcp_config,
    create_mcp_servers_config,
)

__all__ = [
    "PROJECT_ROOT",
    "MCPServerConfig",
    "get_data_mcp_config",
    "get_ups_mcp_config",
    "create_mcp_servers_config",
]
