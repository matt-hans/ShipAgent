---
phase: 06-batch-execution
plan: 06
subsystem: batch-execution
tags: [batch, orchestrator, tools, mcp, preview, execute, mode, recovery]

dependency-graph:
  requires: ["06-03", "06-04", "06-05"]
  provides: ["batch_preview_tool", "batch_execute_tool", "batch_set_mode_tool", "batch_resume_tool"]
  affects: ["06-07"]

tech-stack:
  added: []
  patterns: ["mcp-tool-pattern", "mode-manager-singleton", "callable-injection"]

key-files:
  created:
    - tests/orchestrator/agent/test_batch_tools.py
    - tests/orchestrator/agent/conftest.py
  modified:
    - src/orchestrator/agent/tools.py
    - src/services/job_service.py

decisions:
  - id: "06-06-01"
    title: "Callable injection for MCP calls"
    choice: "Pass data_mcp_call and ups_mcp_call as tool arguments"
    rationale: "Decouples tools from MCP transport, enables unit testing with mocks"
  - id: "06-06-02"
    title: "Mode manager singleton"
    choice: "Module-level _mode_manager with getter function"
    rationale: "Session-level mode persists across tool calls, consistent with _engine pattern"
  - id: "06-06-03"
    title: "SDK mock in conftest"
    choice: "Mock claude_agent_sdk at import time in tests/orchestrator/agent/conftest.py"
    rationale: "Allows testing agent tools without SDK installation"

metrics:
  duration: "11 minutes"
  completed: "2026-01-25"
  tasks: 3
  tests-added: 30
  total-tests: 111
---

# Phase 6 Plan 6: Batch Orchestration Tools Summary

**One-liner:** Four orchestrator tools exposing batch preview, execute, mode switching, and recovery to Claude via MCP-compatible interface.

## What Was Built

### Batch Preview Tool (BATCH-02)

```python
async def batch_preview_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Generate batch preview with cost estimates."""
```

**Features:**
- Creates PreviewGenerator with injected MCP calls
- Generates BatchPreview with first 20 rows detailed
- Returns JSON-serialized preview via MCP content block
- Validates required fields (job_id, mapping_template)

### Batch Execute Tool (BATCH-03)

```python
async def batch_execute_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Execute batch shipments with mode support."""
```

**Features:**
- Checks execution mode via SessionModeManager
- Requires approval in CONFIRM mode
- Locks mode during execution
- Creates BatchExecutor with injected MCP calls
- Returns BatchResult as JSON

### Batch Set Mode Tool (BATCH-04)

```python
async def batch_set_mode_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Set execution mode (confirm/auto) for session."""
```

**Features:**
- Parses mode string to ExecutionMode enum
- Case-insensitive mode parsing
- Returns error if mode locked during execution

### Batch Resume Tool (BATCH-06)

```python
async def batch_resume_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Check for and handle interrupted jobs."""
```

**Features:**
- Queries for jobs in 'running' state (crash indicator)
- Returns recovery prompt with options
- Handles resume/restart/cancel choices
- Uses reset_job_for_restart for restart choice

### JobService Extension

Added `reset_job_for_restart` method:
```python
def reset_job_for_restart(self, job_id: str) -> Job:
    """Reset job and all rows to pending for restart."""
```

### Tool Schemas

```python
BATCH_PREVIEW_SCHEMA = {
    "job_id": {"type": "string", "description": "UUID of the job"},
    "filter_clause": {"type": "string", "description": "SQL WHERE clause"},
    "mapping_template": {"type": "string", "description": "Jinja2 template"},
    "shipper_info": {"type": "object", "description": "Shipper address"},
}

BATCH_EXECUTE_SCHEMA = {
    "job_id": {"type": "string", "description": "UUID of the job"},
    "mapping_template": {"type": "string", "description": "Jinja2 template"},
    "shipper_info": {"type": "object", "description": "Shipper address"},
    "approved": {"type": "boolean", "description": "Preview approved"},
    "source_name": {"type": "string", "description": "Data source name"},
}

BATCH_SET_MODE_SCHEMA = {
    "mode": {"type": "string", "description": "confirm or auto"},
}

BATCH_RESUME_SCHEMA = {
    "choice": {"type": "string", "description": "resume, restart, or cancel"},
    "job_id": {"type": "string", "description": "Job ID for recovery"},
}
```

### Unit Tests (30 tests)

Test coverage for all tools:

**TestBatchPreviewTool (6 tests):**
- Returns MCP format
- Returns BatchPreview as JSON
- Requires job_id
- Requires mapping_template
- Requires MCP calls
- Schema validation

**TestBatchExecuteTool (7 tests):**
- CONFIRM mode requires approval
- CONFIRM mode with approval succeeds
- AUTO mode no approval needed
- Mode locked during execution
- Requires job_id
- Requires mapping_template
- Schema validation

**TestBatchSetModeTool (6 tests):**
- Set mode confirm
- Set mode auto
- Invalid mode error
- Case insensitive
- Locked mode error
- Schema validation

**TestBatchResumeTool (8 tests):**
- No interrupted jobs
- Shows interrupted jobs
- Resume choice
- Restart choice
- Cancel choice
- Choice requires job_id
- Invalid choice error
- Schema validation

**TestMCPResponseFormat (3 tests):**
- Preview content array
- Set mode content array
- Error has isError flag

## Key Links

| From | To | Via | Pattern |
|------|-----|-----|---------|
| tools.py | PreviewGenerator | Callable injection | `PreviewGenerator(data_mcp_call, ups_mcp_call)` |
| tools.py | BatchExecutor | Callable injection | `BatchExecutor(..., data_mcp_call, ups_mcp_call)` |
| tools.py | SessionModeManager | Singleton | `_get_mode_manager()` |
| tools.py | JobService | DB context | `get_db_context()` |
| tools.py | batch/__init__.py | Imports | `from src.orchestrator.batch import ...` |

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

| Check | Status |
|-------|--------|
| All four batch tools import successfully | PASSED |
| batch_preview_tool returns BatchPreview as JSON | PASSED |
| batch_execute_tool respects mode and approval | PASSED |
| batch_set_mode_tool changes session mode | PASSED |
| batch_resume_tool handles recovery flow | PASSED |
| Tools registered in get_orchestrator_tools() | PASSED |
| list_tools includes batch tools | PASSED |
| All unit tests pass | PASSED (30/30) |

## Next Phase Readiness

**Blockers:** None

**Ready for:**
- 06-07: Integration Tests (end-to-end batch flow testing)

## Commits

| Hash | Type | Description |
|------|------|-------------|
| c43fc83 | feat | Add batch tools to orchestrator |
| f4312ff | test | Add unit tests for batch tools |
| 3389cad | chore | Update __all__ exports for batch tools |
