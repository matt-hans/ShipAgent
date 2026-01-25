"""Orchestration Agent package for ShipAgent.

This package provides the Claude Agent SDK-based orchestration layer that
coordinates multiple MCP servers (Data Source, UPS) via stdio transport.

Main Entry Points:
    OrchestrationAgent: Main agent class with lifecycle management
    create_agent: Factory to create and start an agent

Configuration:
    create_mcp_servers_config: Get MCP server configurations
    create_hook_matchers: Get hook configurations

Per CONTEXT.md:
- MCPs spawn eagerly at startup
- Session persists for process lifetime
- Graceful shutdown with 5s timeout

Architecture:
    The agent spawns MCP servers as child processes via stdio transport:
    - Data MCP: Data source operations (CSV, Excel, database imports)
    - UPS MCP: UPS shipping operations (create, void, rate, track)

    The Claude Agent SDK manages the LLM interactions and tool execution,
    while this package provides configuration and orchestration logic.

Modules:
    config: MCP server configuration for ClaudeAgentOptions
    tools: Orchestrator-native tools for the SDK MCP server
    hooks: PreToolUse and PostToolUse hook implementations
    client: Main OrchestrationAgent class

Exports:
    Client:
        OrchestrationAgent: Main agent class
        create_agent: Factory function to create started agent

    Configuration:
        PROJECT_ROOT: Path to project root directory
        MCPServerConfig: TypedDict for MCP server spawn configuration
        get_data_mcp_config: Returns Data MCP configuration
        get_ups_mcp_config: Returns UPS MCP configuration
        create_mcp_servers_config: Returns combined MCP server configurations

    Tools:
        process_command_tool: Process NL shipping commands
        get_job_status_tool: Query job state
        list_tools_tool: List available tools
        get_orchestrator_tools: Get all tool definitions for SDK registration

    Hooks:
        validate_pre_tool: Generic pre-validation entry point
        validate_shipping_input: UPS shipping tool validation
        validate_data_query: Data query warnings
        log_post_tool: Audit logging for all tool executions
        detect_error_response: Error detection in tool responses
        create_hook_matchers: Factory for ClaudeAgentOptions hooks configuration
"""

from src.orchestrator.agent.config import (
    PROJECT_ROOT,
    MCPServerConfig,
    get_data_mcp_config,
    get_ups_mcp_config,
    create_mcp_servers_config,
)

from src.orchestrator.agent.tools import (
    GET_JOB_STATUS_SCHEMA,
    LIST_TOOLS_SCHEMA,
    PROCESS_COMMAND_SCHEMA,
    get_job_status_tool,
    get_orchestrator_tools,
    list_tools_tool,
    process_command_tool,
)

from src.orchestrator.agent.hooks import (
    create_hook_matchers,
    detect_error_response,
    log_post_tool,
    validate_data_query,
    validate_pre_tool,
    validate_shipping_input,
)

# Client
from src.orchestrator.agent.client import (
    OrchestrationAgent,
    create_agent,
)

__all__ = [
    # Main entry points
    "OrchestrationAgent",
    "create_agent",
    # Configuration
    "PROJECT_ROOT",
    "MCPServerConfig",
    "get_data_mcp_config",
    "get_ups_mcp_config",
    "create_mcp_servers_config",
    # Tools
    "process_command_tool",
    "get_job_status_tool",
    "list_tools_tool",
    "get_orchestrator_tools",
    "PROCESS_COMMAND_SCHEMA",
    "GET_JOB_STATUS_SCHEMA",
    "LIST_TOOLS_SCHEMA",
    # Hooks
    "validate_pre_tool",
    "validate_shipping_input",
    "validate_data_query",
    "log_post_tool",
    "detect_error_response",
    "create_hook_matchers",
]
