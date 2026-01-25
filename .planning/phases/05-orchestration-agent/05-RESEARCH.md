# Phase 5: Orchestration Agent - Research

**Researched:** 2026-01-25
**Domain:** Claude Agent SDK MCP Orchestration
**Confidence:** HIGH

## Summary

The Orchestration Agent uses the Claude Agent SDK (Python) to spawn and coordinate multiple MCP servers (Data Source MCP and UPS MCP) as child processes communicating via stdio transport. The SDK provides built-in support for MCP server lifecycle management, tool routing via the `mcp__<server>__<tool>` naming convention, and a comprehensive hooks system for pre/post tool validation.

The architecture follows the established pattern: configure MCP servers in `ClaudeAgentOptions`, use `ClaudeSDKClient` for session continuity (required for multi-turn conversations), and implement `PreToolUse`/`PostToolUse` hooks for validation and logging. The SDK handles process spawning, JSON-RPC communication, and tool discovery automatically.

**Primary recommendation:** Use `ClaudeSDKClient` (not `query()`) with `mcp_servers` configuration for stdio transport, `HookMatcher` for validation hooks, and expose orchestrator-native tools via an SDK MCP server created with `create_sdk_mcp_server()`.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `claude-agent-sdk` | 0.8.x+ | Agent orchestration, MCP management | Official Anthropic SDK with built-in MCP support |
| `fastmcp` | 2.x | Data Source MCP server framework | Already used in Phase 2, stable stdio support |
| `@modelcontextprotocol/sdk` | 1.x | UPS MCP server framework | Already used in Phase 3, TypeScript MCP standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `asyncio` | stdlib | Async subprocess and event loop | Process lifecycle management |
| `pydantic` | 2.x | Configuration and message models | Already in use, hook input validation |
| `aiosqlite` | 0.19+ | Async SQLite access | Session state persistence |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `ClaudeSDKClient` | `query()` function | `query()` lacks hooks, custom tools, session continuity |
| SDK MCP server | External process | SDK server runs in-process, simpler for orchestrator tools |
| Manual subprocess | SDK mcp_servers | SDK handles lifecycle, retry, and protocol automatically |

**Installation:**
```bash
pip install claude-agent-sdk pydantic aiosqlite
```

## Architecture Patterns

### Recommended Project Structure
```
src/orchestrator/
├── agent/
│   ├── __init__.py
│   ├── client.py           # ClaudeSDKClient wrapper with lifecycle
│   ├── config.py           # MCP server configurations
│   ├── hooks.py            # PreToolUse/PostToolUse hook implementations
│   └── tools.py            # Orchestrator-native tools (process_command, etc.)
├── mcp/
│   ├── manager.py          # MCP server lifecycle manager
│   └── registry.py         # Tool namespace registry for conflict detection
├── session/
│   ├── context.py          # Session state (active data source, job)
│   └── history.py          # Message history management
└── nl_engine/              # Existing Phase 4 components
```

### Pattern 1: MCP Server Configuration
**What:** Configure multiple MCP servers as stdio child processes in ClaudeAgentOptions
**When to use:** Always - this is the standard pattern for multi-MCP orchestration
**Example:**
```python
# Source: Claude Agent SDK documentation - MCP configuration
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

options = ClaudeAgentOptions(
    mcp_servers={
        "data": {
            "command": "python",
            "args": ["-m", "src.mcp.data_source.server"],
            "env": {
                "PYTHONPATH": str(project_root)
            }
        },
        "ups": {
            "command": "node",
            "args": ["packages/ups-mcp/dist/index.js"],
            "env": {
                "UPS_CLIENT_ID": os.environ["UPS_CLIENT_ID"],
                "UPS_CLIENT_SECRET": os.environ["UPS_CLIENT_SECRET"],
                "UPS_ACCOUNT_NUMBER": os.environ["UPS_ACCOUNT_NUMBER"]
            }
        }
    },
    allowed_tools=[
        "mcp__data__*",  # All data source tools
        "mcp__ups__*"    # All UPS tools
    ]
)
```

### Pattern 2: Hook-Based Validation
**What:** Use PreToolUse hooks for input validation, PostToolUse for logging and error detection
**When to use:** For all tool calls requiring business rule validation
**Example:**
```python
# Source: Claude Agent SDK documentation - Hooks
from claude_agent_sdk import HookMatcher, HookContext
from typing import Any

async def validate_shipping_input(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: HookContext
) -> dict[str, Any]:
    """Pre-tool validation for shipping operations."""
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Validate batch size limits
    if tool_name == "mcp__ups__shipping_create":
        if not tool_input.get("shipper"):
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "Missing required shipper information"
                }
            }

    return {}  # Allow operation

async def log_tool_execution(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: HookContext
) -> dict[str, Any]:
    """Post-tool logging for audit trail."""
    tool_name = input_data.get("tool_name", "")
    tool_response = input_data.get("tool_response")

    # Log execution with timing
    logger.info(f"Tool executed: {tool_name}", extra={
        "tool_use_id": tool_use_id,
        "success": not _is_error_response(tool_response)
    })

    return {}

options = ClaudeAgentOptions(
    hooks={
        "PreToolUse": [
            HookMatcher(matcher="mcp__ups__shipping_", hooks=[validate_shipping_input])
        ],
        "PostToolUse": [
            HookMatcher(hooks=[log_tool_execution])  # All tools
        ]
    }
)
```

### Pattern 3: Orchestrator-Native Tools via SDK MCP Server
**What:** Expose orchestrator tools (process_command, get_job_status, list_tools) as an in-process MCP server
**When to use:** For tools that need access to orchestrator state or NLMappingEngine
**Example:**
```python
# Source: Claude Agent SDK documentation - Custom tools
from claude_agent_sdk import tool, create_sdk_mcp_server
from src.orchestrator.nl_engine.engine import NLMappingEngine

engine = NLMappingEngine()

@tool("process_command", "Parse natural language shipping command", {
    "command": str,
    "source_schema": list  # List of column info dicts
})
async def process_command(args: dict[str, Any]) -> dict[str, Any]:
    """Process NL command using Phase 4 NLMappingEngine."""
    result = await engine.process_command(
        command=args["command"],
        source_schema=args["source_schema"]
    )
    return {
        "content": [{
            "type": "text",
            "text": json.dumps(result.model_dump(), default=str)
        }]
    }

@tool("get_job_status", "Get current job status", {"job_id": str})
async def get_job_status(args: dict[str, Any]) -> dict[str, Any]:
    # Fetch from state database
    ...

orchestrator_server = create_sdk_mcp_server(
    name="orchestrator",
    version="1.0.0",
    tools=[process_command, get_job_status]
)

options = ClaudeAgentOptions(
    mcp_servers={
        "orchestrator": orchestrator_server,
        "data": {...},
        "ups": {...}
    }
)
```

### Pattern 4: Session Context Management with ClaudeSDKClient
**What:** Use ClaudeSDKClient for session continuity across multiple user commands
**When to use:** Always - required for conversation context per CONTEXT.md
**Example:**
```python
# Source: Claude Agent SDK documentation - ClaudeSDKClient
from claude_agent_sdk import ClaudeSDKClient, AssistantMessage, TextBlock, ResultMessage

class OrchestrationAgent:
    def __init__(self, options: ClaudeAgentOptions):
        self.client = ClaudeSDKClient(options)
        self.session_context = SessionContext()

    async def start(self):
        """Start agent and spawn MCP servers."""
        await self.client.connect()
        # MCP servers are automatically spawned by SDK

    async def process_user_command(self, command: str) -> str:
        """Process command with session continuity."""
        # Client maintains conversation history
        await self.client.query(command)

        response_text = ""
        async for message in self.client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_text += block.text
            elif isinstance(message, ResultMessage):
                break

        return response_text

    async def stop(self):
        """Graceful shutdown with timeout."""
        await self.client.disconnect()
```

### Anti-Patterns to Avoid
- **Using `query()` instead of `ClaudeSDKClient`:** `query()` creates new sessions each time, losing conversation context
- **Manual subprocess management:** SDK handles process lifecycle; don't reimplement
- **Global state in MCP servers:** Tools called by different contexts; use session-based state
- **Logging to stdout in MCP servers:** Stdout is reserved for JSON-RPC protocol; use stderr
- **Blocking hooks:** Hooks should be fast; move long operations to background tasks

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MCP server spawning | Custom subprocess manager | `ClaudeAgentOptions.mcp_servers` | SDK handles lifecycle, retry, protocol |
| Tool routing | Namespace parser | SDK auto-routes via `mcp__<server>__<tool>` | Built-in, tested, handles edge cases |
| JSON-RPC protocol | Custom protocol handler | SDK handles all MCP communication | Complex framing, error handling |
| Session continuity | Manual message history | `ClaudeSDKClient` maintains context | SDK manages token limits, compaction |
| Tool permission | Custom permission system | `PreToolUse` hooks with `permissionDecision` | Integrates with SDK permission flow |
| Process restart | Custom watchdog | SDK auto-restarts on crash | Configure retry in options |

**Key insight:** The Claude Agent SDK has mature MCP support. Building custom process management or protocol handling is reinventing tested infrastructure and introduces subtle bugs around process lifecycle, signal handling, and error recovery.

## Common Pitfalls

### Pitfall 1: Stdout Contamination in MCP Servers
**What goes wrong:** MCP server uses `print()` or logging to stdout, corrupting JSON-RPC stream
**Why it happens:** Developers forget stdout is reserved for protocol messages
**How to avoid:** Use `ctx.info()` in FastMCP, `console.error()` in TypeScript MCP, or configure loggers to stderr
**Warning signs:** "Failed to parse JSON" errors, MCP connection drops randomly

### Pitfall 2: Using query() for Multi-Turn Conversations
**What goes wrong:** Each command starts fresh session, Claude forgets context
**Why it happens:** `query()` is simpler API, documentation shows it first
**How to avoid:** Use `ClaudeSDKClient` which maintains session across `query()` calls
**Warning signs:** Claude repeatedly asks for data source, doesn't remember previous commands

### Pitfall 3: Tool Name Conflicts at Startup
**What goes wrong:** Two MCPs register same tool name, routing becomes ambiguous
**Why it happens:** Tool names not properly namespaced during development
**How to avoid:** Detect conflicts at startup, fail fast with clear error
**Warning signs:** Wrong MCP receives tool calls, unexpected behavior

### Pitfall 4: Hook Timeout Under Load
**What goes wrong:** Validation hooks take too long, cause timeouts
**Why it happens:** Hook does expensive validation (database lookup, API call)
**How to avoid:** Keep hooks fast (<1s), increase `timeout` in `HookMatcher` if needed
**Warning signs:** Tool calls fail with timeout errors during busy periods

### Pitfall 5: MCP Server Crash Without Recovery
**What goes wrong:** MCP crashes mid-operation, no retry, operation fails silently
**Why it happens:** Crash recovery not configured, error not surfaced to user
**How to avoid:** SDK auto-restarts MCPs; implement retry in orchestrator for failed operations
**Warning signs:** Intermittent "connection closed" errors, lost tool results

### Pitfall 6: Session State Lost on Agent Restart
**What goes wrong:** Agent restarts, loses active data source and job context
**Why it happens:** Session state only in memory, not persisted
**How to avoid:** Persist session state to SQLite, reload on startup (per CONTEXT.md: process lifetime scope)
**Warning signs:** User must re-import data after any agent restart

## Code Examples

Verified patterns from official sources:

### Complete Orchestrator Setup
```python
# Source: Assembled from Claude Agent SDK documentation
import asyncio
import os
from pathlib import Path
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    HookMatcher,
    tool,
    create_sdk_mcp_server,
    AssistantMessage,
    TextBlock,
    ResultMessage
)
from typing import Any

# Project root for PYTHONPATH
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# --- Hooks ---

async def validate_pre_tool(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any
) -> dict[str, Any]:
    """Validate all tool inputs before execution."""
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Block dangerous operations
    if "shipping_create" in tool_name:
        if not tool_input.get("shipper") or not tool_input.get("shipTo"):
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "Missing required address information"
                }
            }

    return {}  # Allow

async def log_post_tool(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any
) -> dict[str, Any]:
    """Log all tool executions for audit."""
    tool_name = input_data.get("tool_name", "")
    # Log to audit system
    print(f"[AUDIT] Tool executed: {tool_name}", file=sys.stderr)
    return {}

# --- Orchestrator Tools ---

@tool("list_tools", "List all available tools across MCPs", {})
async def list_tools_impl(args: dict[str, Any]) -> dict[str, Any]:
    """Return available tools (populated at runtime)."""
    return {
        "content": [{
            "type": "text",
            "text": "Tools: mcp__data__*, mcp__ups__*, mcp__orchestrator__*"
        }]
    }

# --- Configuration ---

def create_agent_options() -> ClaudeAgentOptions:
    """Create agent configuration with all MCPs and hooks."""

    # Orchestrator tools as SDK MCP server
    orchestrator = create_sdk_mcp_server(
        name="orchestrator",
        tools=[list_tools_impl]
    )

    return ClaudeAgentOptions(
        mcp_servers={
            # In-process orchestrator tools
            "orchestrator": orchestrator,

            # Data Source MCP (Python/FastMCP)
            "data": {
                "command": "python",
                "args": ["-m", "src.mcp.data_source.server"],
                "env": {
                    "PYTHONPATH": str(PROJECT_ROOT)
                }
            },

            # UPS MCP (TypeScript)
            "ups": {
                "command": "node",
                "args": [str(PROJECT_ROOT / "packages/ups-mcp/dist/index.js")],
                "env": {
                    "UPS_CLIENT_ID": os.environ.get("UPS_CLIENT_ID", ""),
                    "UPS_CLIENT_SECRET": os.environ.get("UPS_CLIENT_SECRET", ""),
                    "UPS_ACCOUNT_NUMBER": os.environ.get("UPS_ACCOUNT_NUMBER", ""),
                    "UPS_LABELS_OUTPUT_DIR": str(PROJECT_ROOT / "labels")
                }
            }
        },

        # Allow all tools from configured MCPs
        allowed_tools=[
            "mcp__orchestrator__*",
            "mcp__data__*",
            "mcp__ups__*"
        ],

        # Hooks for validation and logging
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="mcp__ups__", hooks=[validate_pre_tool])
            ],
            "PostToolUse": [
                HookMatcher(hooks=[log_post_tool])
            ]
        },

        # Session settings
        permission_mode="acceptEdits",  # Auto-approve file operations
        max_turns=50,  # Limit conversation length
    )

# --- Agent Class ---

class OrchestrationAgent:
    """Main orchestration agent with MCP coordination."""

    def __init__(self):
        self.options = create_agent_options()
        self.client = ClaudeSDKClient(self.options)

    async def start(self):
        """Start agent and verify MCP connections."""
        await self.client.connect()
        # SDK automatically spawns MCP servers and verifies connections

    async def process_command(self, user_input: str) -> str:
        """Process user command with full context."""
        await self.client.query(user_input)

        response_parts = []
        async for message in self.client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_parts.append(block.text)
            elif isinstance(message, ResultMessage):
                if message.subtype == "error":
                    response_parts.append(f"[Error: {message.result}]")
                break

        return "".join(response_parts)

    async def stop(self):
        """Graceful shutdown."""
        await self.client.disconnect()

# --- Entry Point ---

async def main():
    agent = OrchestrationAgent()
    await agent.start()

    try:
        # Example: process a command
        response = await agent.process_command(
            "Import orders.csv and show me the schema"
        )
        print(response)
    finally:
        await agent.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

### Startup Verification Pattern
```python
# Source: Claude Agent SDK documentation - System init message
async def verify_mcp_connections(client: ClaudeSDKClient) -> dict[str, bool]:
    """Verify all MCP servers connected successfully."""
    await client.query("List available tools")  # Trigger connection

    status = {}
    async for message in client.receive_messages():
        if hasattr(message, "subtype") and message.subtype == "init":
            # Check MCP server status from init message
            mcp_servers = message.data.get("mcp_servers", [])
            for server in mcp_servers:
                status[server["name"]] = server["status"] == "connected"
            break

    return status
```

### Hook with Timeout Configuration
```python
# Source: Claude Agent SDK documentation - HookMatcher
from claude_agent_sdk import HookMatcher

# For hooks that may take longer (e.g., database validation)
slow_validation_matcher = HookMatcher(
    matcher="mcp__ups__shipping_create",
    hooks=[validate_shipping_details],
    timeout=120  # 2 minutes for complex validation
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual subprocess | SDK `mcp_servers` config | Claude Agent SDK 0.7+ | Automatic lifecycle management |
| Custom JSON-RPC | SDK handles protocol | Always | Eliminates protocol bugs |
| `query()` for all cases | `ClaudeSDKClient` for sessions | SDK 0.6+ | Proper conversation continuity |
| External MCP for all tools | SDK MCP server for in-process | SDK 0.7+ | Simpler orchestrator tools |

**Deprecated/outdated:**
- `decision` and `reason` fields in PreToolUse hooks: Use `hookSpecificOutput.permissionDecision` instead
- SSE transport: Prefer HTTP or stdio (SSE deprecated in MCP spec)

## Open Questions

Things that couldn't be fully resolved:

1. **MCP Server Health Check Frequency**
   - What we know: SDK verifies connection at startup; ongoing health via tool call success
   - What's unclear: Exact retry behavior on transient failures
   - Recommendation: Per CONTEXT.md, rely on startup verification and tool call error handling; no periodic health checks

2. **Message History Depth Management**
   - What we know: SDK handles compaction automatically; `PreCompact` hook available
   - What's unclear: Exact token threshold before compaction triggers
   - Recommendation: Per CONTEXT.md, keep 20-50 messages; let SDK manage compaction

3. **Tool Namespace Conflict Detection**
   - What we know: SDK routes by `mcp__<server>__<tool>` pattern
   - What's unclear: Whether SDK fails on duplicate tool names across servers
   - Recommendation: Per CONTEXT.md, implement startup check; fail fast on conflicts

## Sources

### Primary (HIGH confidence)
- [Claude Agent SDK Python Reference](https://platform.claude.com/docs/en/agent-sdk/python) - Full API documentation
- [Claude Agent SDK Hooks Guide](https://platform.claude.com/docs/en/agent-sdk/hooks) - Hook types and patterns
- [Claude Agent SDK MCP Guide](https://platform.claude.com/docs/en/agent-sdk/mcp) - MCP server configuration
- [Claude Agent SDK GitHub](https://github.com/anthropics/claude-agent-sdk-python) - Source repository

### Secondary (MEDIUM confidence)
- [FastMCP Running Server Guide](https://gofastmcp.com/deployment/running-server) - FastMCP transport options
- [MCP Python SDK GitHub](https://github.com/modelcontextprotocol/python-sdk) - MCP protocol reference
- [Python asyncio subprocess docs](https://docs.python.org/3/library/asyncio-subprocess.html) - Process management

### Tertiary (LOW confidence)
- [MCP Tips and Pitfalls](https://nearform.com/digital-community/implementing-model-context-protocol-mcp-tips-tricks-and-pitfalls/) - Community best practices
- Web search results for patterns and anti-patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Claude Agent SDK documentation is comprehensive and authoritative
- Architecture: HIGH - Patterns derived directly from official SDK documentation
- Pitfalls: MEDIUM - Combination of documentation and community sources
- Code examples: HIGH - Based on official SDK examples, adapted for project

**Research date:** 2026-01-25
**Valid until:** 60 days (Claude Agent SDK is actively developed; check for major version changes)
