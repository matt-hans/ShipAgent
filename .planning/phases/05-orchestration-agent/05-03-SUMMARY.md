---
phase: 05-orchestration-agent
plan: 03
subsystem: orchestrator-tools
tags: [orchestration-agent, mcp-tools, nl-engine, job-service, tool-discovery]

dependency-graph:
  requires:
    - 04-07 (NLMappingEngine)
    - 01-02 (JobService)
  provides:
    - process_command_tool for NL command processing
    - get_job_status_tool for job state queries
    - list_tools_tool for tool discovery
    - get_orchestrator_tools() for SDK MCP registration
  affects:
    - 05-04 (SDK MCP Server) will use get_orchestrator_tools()

tech-stack:
  added: []
  patterns:
    - Singleton pattern for NLMappingEngine instance
    - MCP tool response format with content blocks
    - Sync context manager within async tool for JobService

key-files:
  created:
    - src/orchestrator/agent/tools.py
  modified:
    - src/orchestrator/agent/__init__.py

decisions:
  - name: "Singleton NLMappingEngine instance"
    rationale: "Avoid recreating engine for each command, reuse Jinja environment"
    alternatives: ["Create per-call", "Dependency injection"]
  - name: "Sync get_db_context in async tool"
    rationale: "JobService uses sync Session; async wrapper would add complexity without benefit"
    alternatives: ["Rewrite JobService as async", "Use run_in_executor"]
  - name: "Hard-coded tool list in list_tools"
    rationale: "Simple static list; dynamic discovery adds complexity for MVP"
    alternatives: ["Query MCPs for tool lists", "Tool registry pattern"]

metrics:
  duration: "3 minutes"
  completed: "2026-01-25"
---

# Phase 5 Plan 03: Orchestrator-Native Tools Summary

**One-liner:** Three orchestrator-native MCP tools wrapping Phase 4 NLMappingEngine (process_command), Phase 1 JobService (get_job_status), and tool discovery (list_tools) with MCP-compliant response format.

## What Was Built

### 1. process_command Tool

Wraps the Phase 4 NLMappingEngine to process natural language shipping commands:

```python
async def process_command_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Process a natural language shipping command."""
    # Args: command, source_schema, example_row, user_mappings
    engine = _get_engine()  # Singleton
    result = await engine.process_command(...)
    return {
        "content": [{
            "type": "text",
            "text": json.dumps(result.model_dump(mode="json"), indent=2)
        }]
    }
```

**Input Schema:**
- `command` (str): Natural language command like "Ship California orders via Ground"
- `source_schema` (list): Column info dicts with 'name' and 'type'
- `example_row` (dict, optional): Example row for template validation
- `user_mappings` (list, optional): User-confirmed field mappings

### 2. get_job_status Tool

Queries Phase 1 JobService for job state:

```python
async def get_job_status_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Get the status of a shipping job."""
    with get_db_context() as session:
        job_service = JobService(session)
        job = job_service.get_job(job_id)
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "job_id": str(job.id),
                    "status": job.status,
                    "total_rows": job.total_rows,
                    ...
                }, indent=2)
            }]
        }
```

**Error Handling:**
- Returns `isError: True` with error message for missing jobs
- Gracefully handles database connection errors

### 3. list_tools Tool

Enumerates all available tools across namespaces:

```python
async def list_tools_tool(args: dict[str, Any]) -> dict[str, Any]:
    """List all available tools across MCPs and orchestrator."""
    tools = {
        "orchestrator": [...],  # 3 tools
        "data": [...],          # 12 tools
        "ups": [...],           # 6 tools
    }
    # Optional namespace filter
```

**Tool Counts:**
- `orchestrator`: process_command, get_job_status, list_tools (3)
- `data`: import_csv, import_excel, import_database, list_sheets, list_tables, get_schema, override_column_type, get_row, get_rows_by_filter, query_data, compute_checksums, verify_checksum (12)
- `ups`: rating_quote, rating_shop, shipping_create, shipping_void, shipping_get_label, address_validate (6)

### 4. SDK Registration Function

Provides tool definitions for SDK MCP server registration:

```python
def get_orchestrator_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "process_command",
            "description": "Process a natural language shipping command into structured intent and templates",
            "schema": PROCESS_COMMAND_SCHEMA,
            "function": process_command_tool,
        },
        # ... get_job_status, list_tools
    ]
```

## Package Exports

**From `src.orchestrator.agent`:**

```python
from src.orchestrator.agent import (
    # Tools
    process_command_tool,
    get_job_status_tool,
    list_tools_tool,
    get_orchestrator_tools,
    # Schemas
    PROCESS_COMMAND_SCHEMA,
    GET_JOB_STATUS_SCHEMA,
    LIST_TOOLS_SCHEMA,
)
```

## Verification Results

All verification checks passed:

1. **process_command_tool:** Wraps NLMappingEngine, returns MCP format
2. **get_job_status_tool:** Queries JobService, handles missing jobs gracefully
3. **list_tools_tool:** Returns categorized tool listing (3 namespaces, 21 total tools)
4. **get_orchestrator_tools:** Returns proper format for SDK registration
5. **All responses:** Follow MCP content block format with `{"content": [{"type": "text", "text": ...}]}`

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `e643236` | feat | Create process_command tool wrapping NLMappingEngine |
| `b7ecd16` | feat | Add get_job_status tool for job state queries |
| `ef7f096` | feat | Add list_tools tool and export all orchestrator tools |

## Files Created/Modified

| File | Type | Description |
|------|------|-------------|
| `src/orchestrator/agent/tools.py` | Created | Orchestrator-native tools (265 lines) |
| `src/orchestrator/agent/__init__.py` | Modified | Added tool exports |

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

Plan 05-03 provides the orchestrator-native tools for Plan 05-04 (SDK MCP Server):

- **Provides to Plan 05-04:** `get_orchestrator_tools()` returns list of tool definitions
- **Key Links Verified:**
  - `tools.py` -> `src/orchestrator/nl_engine/engine.py` (NLMappingEngine import)
  - `tools.py` -> `src/services/job_service.py` (JobService import)
  - `tools.py` -> `src/db/connection.py` (get_db_context import)

---
*Phase: 05-orchestration-agent*
*Completed: 2026-01-25*
