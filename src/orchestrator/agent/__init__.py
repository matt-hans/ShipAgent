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
"""

# Exports populated after config.py is created (Task 2)
