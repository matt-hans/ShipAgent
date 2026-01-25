---
phase: 05-orchestration-agent
plan: 04
subsystem: agent-client
tags: [orchestration-agent, claude-agent-sdk, mcp-coordination, lifecycle-management]

dependency-graph:
  requires:
    - 05-01 (MCP Server Configuration)
    - 05-02 (Hook System)
    - 05-03 (Orchestrator-Native Tools)
  provides:
    - OrchestrationAgent class with lifecycle management
    - create_agent() factory function
    - Async context manager support
  affects:
    - 05-05 (Integration Tests) will test OrchestrationAgent

tech-stack:
  added:
    - claude-agent-sdk==0.1.22
  patterns:
    - ClaudeSDKClient for agent lifecycle
    - McpStdioServerConfig for MCP process spawning
    - HookMatcher for hook registration
    - Async context manager for resource cleanup

key-files:
  created:
    - src/orchestrator/agent/client.py
  modified:
    - src/orchestrator/agent/__init__.py

decisions:
  - name: "ClaudeSDKClient for session continuity"
    rationale: "SDK client maintains conversation context across multiple commands within session"
    alternatives: ["Single-shot query() calls", "Custom session management"]
  - name: "Eager MCP spawn at startup"
    rationale: "Per CONTEXT.md Decision 1: spawn on connect(), not first tool use"
    alternatives: ["Lazy spawn on first tool call"]
  - name: "5s graceful shutdown timeout"
    rationale: "Per CONTEXT.md Decision 1: allow MCPs to clean up before force kill"
    alternatives: ["Immediate kill", "Configurable timeout"]

metrics:
  duration: "4 minutes"
  completed: "2026-01-25"
---

# Phase 5 Plan 04: Agent Client Summary

**One-liner:** OrchestrationAgent class using ClaudeSDKClient to coordinate MCPs (orchestrator, data, ups) with HookMatcher-based validation and async context manager lifecycle management.

## What Was Built

### 1. OrchestrationAgent Class

Main agent class with full lifecycle management:

```python
class OrchestrationAgent:
    """Main orchestration agent coordinating MCPs via Claude Agent SDK."""

    def __init__(self, max_turns: int = 50, permission_mode: str = "acceptEdits"):
        # Creates ClaudeAgentOptions with MCP servers and hooks

    async def start(self) -> None:
        # Spawns MCP servers via ClaudeSDKClient.connect()

    async def process_command(self, user_input: str) -> str:
        # Sends query, receives response via SDK streaming

    async def stop(self, timeout: float = 5.0) -> None:
        # Graceful shutdown with timeout per CONTEXT.md Decision 1

    @property
    def is_started(self) -> bool:
        # Check if agent is running
```

### 2. MCP Server Configuration

Three MCP servers configured in ClaudeAgentOptions:

```python
mcp_servers={
    # In-process orchestrator tools (SDK MCP server)
    "orchestrator": create_sdk_mcp_server(...),

    # External Python MCP (stdio child process)
    "data": McpStdioServerConfig(
        type="stdio",
        command="python3",
        args=["-m", "src.mcp.data_source.server"],
        env={"PYTHONPATH": PROJECT_ROOT},
    ),

    # External TypeScript MCP (stdio child process)
    "ups": McpStdioServerConfig(
        type="stdio",
        command="node",
        args=["packages/ups-mcp/dist/index.js"],
        env={...UPS credentials...},
    ),
}
```

### 3. Hook Registration

Hooks registered via HookMatcher dataclass:

```python
hooks={
    "PreToolUse": [
        HookMatcher(matcher="mcp__ups__shipping", hooks=[validate_shipping_input]),
        HookMatcher(matcher=None, hooks=[validate_pre_tool]),  # All tools
    ],
    "PostToolUse": [
        HookMatcher(matcher=None, hooks=[log_post_tool, detect_error_response]),
    ],
}
```

### 4. Async Context Manager Support

Clean resource management via async context manager:

```python
async with OrchestrationAgent() as agent:
    response = await agent.process_command("Import orders.csv")
    print(response)
# Agent automatically stopped on exit
```

### 5. Factory Function

Convenience factory to create started agent:

```python
async def create_agent() -> OrchestrationAgent:
    """Factory function to create and start an OrchestrationAgent."""
    agent = OrchestrationAgent()
    await agent.start()
    return agent
```

## Package Exports

**From `src.orchestrator.agent`:**

```python
from src.orchestrator.agent import (
    # Main entry points
    OrchestrationAgent,
    create_agent,

    # Configuration
    create_mcp_servers_config,
    create_hook_matchers,
    get_orchestrator_tools,
)
```

## Verification Results

All verification checks passed:

1. **OrchestrationAgent implements start/stop/process_command:** PASS
2. **ClaudeAgentOptions configured with all MCP servers:** PASS (orchestrator, data, ups)
3. **Hooks properly registered with HookMatcher:** PASS (PreToolUse, PostToolUse)
4. **Context manager support:** PASS (__aenter__/__aexit__)
5. **All exports importable from src.orchestrator.agent:** PASS

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `355c5cb` | feat | Create OrchestrationAgent class with Claude SDK |
| `33158c4` | chore | Update agent package exports with OrchestrationAgent |

## Files Created/Modified

| File | Type | Description |
|------|------|-------------|
| `src/orchestrator/agent/client.py` | Created | OrchestrationAgent class (279 lines) |
| `src/orchestrator/agent/__init__.py` | Modified | Added OrchestrationAgent and create_agent exports |

## Deviations from Plan

### SDK Installation

**[Rule 3 - Blocking]** The `claude-agent-sdk` package was not installed. Installed via `uv pip install claude-agent-sdk==0.1.22`.

### API Adjustments

Minor adjustments made to match actual SDK API vs plan assumptions:

1. **ResultMessage.is_error** - Used `message.is_error` instead of `message.subtype == "error"`
2. **McpStdioServerConfig** - SDK uses TypedDict format with explicit `type: "stdio"` field
3. **SdkMcpTool** - Used dataclass constructor instead of tuple format

None of these required architectural changes - just API surface adaptation.

## Issues Encountered

None.

## Next Phase Readiness

Plan 05-04 provides the main OrchestrationAgent for Plan 05-05 (Integration Tests):

- **Provides to Plan 05-05:** `OrchestrationAgent` and `create_agent()` for testing
- **Key Links Verified:**
  - `client.py` -> `src/orchestrator/agent/config.py` (MCP server configuration)
  - `client.py` -> `src/orchestrator/agent/hooks.py` (Hook functions)
  - `client.py` -> `src/orchestrator/agent/tools.py` (Orchestrator tools)

---
*Phase: 05-orchestration-agent*
*Completed: 2026-01-25*
