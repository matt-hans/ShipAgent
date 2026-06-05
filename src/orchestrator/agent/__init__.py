"""Orchestration Agent package for ShipAgent.

This package provides the Claude Agent SDK-based orchestration layer that
coordinates multiple MCP servers (Data Source, UPS) via stdio transport.

Main Entry Points:
    OrchestrationAgent: Main agent class with lifecycle management
    create_agent: Factory to create and start an agent

Configuration:
    create_mcp_servers_config: Get MCP server configurations
    create_hook_matchers: Get hook configurations

Architecture:
    The agent spawns MCP servers as child processes via stdio transport:
    - Data MCP: Data source operations (CSV, Excel, database imports)
    - UPS MCP: UPS shipping operations (create, void, rate, track)

    The Claude Agent SDK manages the LLM interactions and tool execution,
    while this package provides configuration and orchestration logic.

Modules:
    config: MCP server configuration for ClaudeAgentOptions
    tools/: Deterministic SDK tools split by concern (core, data, pipeline, interactive)
    hooks: PreToolUse and PostToolUse hook implementations
    client: Main OrchestrationAgent class
    system_prompt: Unified system prompt builder

Exports:
    Client:
        OrchestrationAgent: Main agent class
        create_agent: Factory function to create started agent

    Configuration:
        PROJECT_ROOT: Path to project root directory
        MCPServerConfig: TypedDict for MCP server spawn configuration
        get_data_mcp_config: Returns Data MCP configuration
        create_mcp_servers_config: Returns combined MCP server configurations

    Hooks:
        validate_pre_tool: Generic pre-validation entry point
        validate_shipping_input: UPS shipping tool validation
        validate_data_query: Data query warnings
        log_post_tool: Audit logging for all tool executions
        detect_error_response: Error detection in tool responses
        create_hook_matchers: Factory for ClaudeAgentOptions hooks configuration
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    # Main entry points
    "OrchestrationAgent",
    "create_agent",
    # Configuration
    "PROJECT_ROOT",
    "MCPServerConfig",
    "get_data_mcp_config",
    "create_mcp_servers_config",
    # Hooks
    "validate_pre_tool",
    "validate_shipping_input",
    "validate_data_query",
    "log_post_tool",
    "detect_error_response",
    "create_hook_matchers",
]

_EXPORT_MODULES = {
    "OrchestrationAgent": "src.orchestrator.agent.client",
    "create_agent": "src.orchestrator.agent.client",
    "PROJECT_ROOT": "src.orchestrator.agent.config",
    "MCPServerConfig": "src.orchestrator.agent.config",
    "get_data_mcp_config": "src.orchestrator.agent.config",
    "create_mcp_servers_config": "src.orchestrator.agent.config",
    "validate_pre_tool": "src.orchestrator.agent.hooks",
    "validate_shipping_input": "src.orchestrator.agent.hooks",
    "validate_data_query": "src.orchestrator.agent.hooks",
    "log_post_tool": "src.orchestrator.agent.hooks",
    "detect_error_response": "src.orchestrator.agent.hooks",
    "create_hook_matchers": "src.orchestrator.agent.hooks",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
