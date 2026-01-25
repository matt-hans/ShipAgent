---
phase: 05-orchestration-agent
plan: 01
subsystem: agent-config
tags: [orchestration-agent, mcp-config, claude-agent-sdk, stdio, child-process]

dependency-graph:
  requires:
    - 02-01 (Data MCP server)
    - 03-01 (UPS MCP server)
  provides:
    - MCPServerConfig TypedDict for spawn configuration
    - PROJECT_ROOT path constant
    - get_data_mcp_config() for Data MCP
    - get_ups_mcp_config() for UPS MCP
    - create_mcp_servers_config() combining both
  affects:
    - 05-02 (Claude SDK Client) will use create_mcp_servers_config()
    - 05-04 (Agent Tools) will use MCP server configs

tech-stack:
  added: []
  patterns:
    - TypedDict for strongly-typed configuration
    - pathlib.Path for cross-platform path handling
    - Environment variable pass-through for credentials

key-files:
  created:
    - src/orchestrator/agent/__init__.py
    - src/orchestrator/agent/config.py
  modified: []

decisions:
  - name: "python3 as Data MCP command"
    rationale: "Explicit python3 ensures Python 3 interpreter on all systems"
    alternatives: ["python", "sys.executable"]
  - name: "Warn but don't fail on missing UPS credentials"
    rationale: "Let MCP fail with clear error rather than config-time failure"
    alternatives: ["Raise exception immediately", "Require credentials"]
  - name: "TypedDict for MCPServerConfig"
    rationale: "Strong typing without runtime overhead, compatible with dict-based APIs"
    alternatives: ["Pydantic model", "dataclass", "plain dict"]

metrics:
  duration: "5 minutes"
  completed: "2026-01-25"
---

# Phase 5 Plan 01: MCP Server Configuration Summary

**One-liner:** Agent configuration module with MCPServerConfig TypedDict defining spawn commands for Data MCP (Python/FastMCP) and UPS MCP (Node.js) as stdio child processes.

## What Was Built

### 1. Agent Package Structure (`src/orchestrator/agent/`)

Created new agent subpackage under orchestrator:

```
src/orchestrator/agent/
  __init__.py   # Package exports
  config.py     # MCP server configurations
```

### 2. MCPServerConfig TypedDict (`config.py`)

Strongly-typed configuration for MCP server spawning:

```python
class MCPServerConfig(TypedDict):
    command: str         # "python3" or "node"
    args: list[str]      # Command arguments
    env: dict[str, str]  # Environment variables
```

### 3. Data MCP Configuration

```python
def get_data_mcp_config() -> MCPServerConfig:
    return MCPServerConfig(
        command="python3",
        args=["-m", "src.mcp.data_source.server"],
        env={"PYTHONPATH": str(PROJECT_ROOT)},
    )
```

- Runs FastMCP server as Python module
- PYTHONPATH set for proper imports
- Stdio transport for MCP communication

### 4. UPS MCP Configuration

```python
def get_ups_mcp_config() -> MCPServerConfig:
    return MCPServerConfig(
        command="node",
        args=[str(PROJECT_ROOT / "packages/ups-mcp/dist/index.js")],
        env={
            "UPS_CLIENT_ID": ...,
            "UPS_CLIENT_SECRET": ...,
            "UPS_ACCOUNT_NUMBER": ...,
            "UPS_LABELS_OUTPUT_DIR": ...,
        },
    )
```

- Runs compiled TypeScript MCP as Node.js
- UPS credentials passed through from environment
- Labels output directory defaults to PROJECT_ROOT/labels
- Warns to stderr if credentials missing (doesn't fail)

### 5. Combined Configuration

```python
def create_mcp_servers_config() -> dict[str, MCPServerConfig]:
    return {
        "data": get_data_mcp_config(),
        "ups": get_ups_mcp_config(),
    }
```

Ready for use with ClaudeAgentOptions.mcp_servers in Plan 02.

## Package Exports

**From `src.orchestrator.agent`:**

```python
from src.orchestrator.agent import (
    PROJECT_ROOT,
    MCPServerConfig,
    get_data_mcp_config,
    get_ups_mcp_config,
    create_mcp_servers_config,
)
```

## Verification Results

All verification checks passed:

1. **Agent package importable:** `from src.orchestrator.agent import create_mcp_servers_config`
2. **Data MCP config correct:** Points to `src.mcp.data_source.server` module
3. **UPS MCP config correct:** Points to `packages/ups-mcp/dist/index.js`
4. **Environment variables configured:** PYTHONPATH, UPS credentials pass-through
5. **All tests pass:** 388 passed, 31 skipped (no regressions)

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `29b2d59` | chore | Create agent package structure |
| `ccff007` | feat | Create MCP server configuration module |
| `f140398` | feat | Export MCP configuration from agent package |

## Files Created/Modified

| File | Type | Description |
|------|------|-------------|
| `src/orchestrator/agent/__init__.py` | Created | Agent package with exports (40 lines) |
| `src/orchestrator/agent/config.py` | Created | MCP server configurations (129 lines) |

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

Plan 05-01 establishes the foundation for Claude Agent SDK integration:

- **Provides to Plan 05-02:** `create_mcp_servers_config()` returns dict for `ClaudeAgentOptions.mcp_servers`
- **Key Links Verified:**
  - `config.py` -> `src/mcp/data_source/server.py` (module path in args)
  - `config.py` -> `packages/ups-mcp/dist/index.js` (node path in args)

---
*Phase: 05-orchestration-agent*
*Completed: 2026-01-25*
