# Claude SDK Orchestration Redesign

**Date:** 2026-02-12
**Status:** Design Complete, Pending Implementation
**Priority:** P0 — Core Architecture Fix

## Problem Statement

The Claude Agent SDK (`OrchestrationAgent`) was built as the intended orchestration layer but is completely bypassed in the actual command flow. The REST endpoint (`commands.py:85`) calls `CommandProcessor` directly, which in turn makes raw `Anthropic()` API calls for intent parsing (`intent_parser.py:207`) and filter generation (`filter_generator.py:280`), bypassing the SDK's agent loop, hooks, system prompt, MCP tool routing, and conversation management.

**Evidence of the bypass:**

```
commands.py:85    →  CommandProcessor(db_session_factory=...)
commands.py:86    →  processor.process(job_id, command)
                        ↓
intent_parser.py:207  →  client = Anthropic()         # raw API, not SDK
filter_generator.py:280 → client = Anthropic()         # raw API, not SDK
                        ↓
command_processor.py:1102 → engine.preview(...)         # direct service call
```

**Meanwhile, the OrchestrationAgent sits fully built but unused:**
- `client.py` — ClaudeSDKClient with MCP servers, hooks, allowed tools
- `tools.py` — 7 in-process tools (process_command, batch_preview, batch_execute, etc.)
- `hooks.py` — Pre/post validation (shipping input, void, data query)
- `config.py` — MCP server configs (data, external, ups)

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Refactor scope | Full agentic redesign | The Claude SDK agent loop becomes the brain, replacing hardcoded step sequences |
| Frontend communication | SSE conversation stream | Real-time agent reasoning visible to user, enables conversational UX |
| Autonomy boundary | Agent decides, user confirms | Agent orchestrates full flow, batch execution gated by user approval |
| LLM calls | Agent reasons natively | No separate Anthropic() calls — the agent IS Claude, one invocation replaces two |
| Session model | Per-conversation agent | One OrchestrationAgent per session, MCP servers persist for session duration |

## Architecture

### High-Level Flow

**Current (broken):**
```
POST /commands/  →  CommandProcessor  →  parse_intent(Anthropic())
                                     →  generate_filter(Anthropic())
                                     →  BatchEngine.preview()
Frontend polls job status.
OrchestrationAgent sits unused.
```

**New (agent-driven):**
```
POST /conversations/{id}/messages
    → AgentSessionManager retrieves/creates OrchestrationAgent for session
    → User message piped into agent's conversation loop
    → Agent reasons natively about intent + filter (no extra LLM calls)
    → Agent calls deterministic tools: fetch_rows, batch_preview, etc.
    → Agent's output streams to frontend via SSE in real-time
    → User sees agent "thinking", tool calls, results as live conversation
    → Agent presents preview → user confirms in chat → agent calls batch_execute
    → Completion artifact streams back
```

**Key shift:** The REST endpoint no longer orchestrates — it just pipes messages between the frontend and the Claude SDK agent loop. The agent loop IS the orchestrator. All shipping domain knowledge lives in the agent's system prompt. All data/UPS operations are deterministic tools.

### Component Architecture

#### New Components

| Component | File | Purpose |
|-----------|------|---------|
| System Prompt Builder | `src/orchestrator/agent/system_prompt.py` | Builds agent's system prompt dynamically. Merges shipping domain knowledge with current data source schema. Schema refreshed per message. |
| Deterministic Tools | `src/orchestrator/agent/tools_v2.py` | Clean SDK tools — pure data/UPS operations, no LLM-in-a-tool pattern. |
| Agent Session Manager | `src/services/agent_session_manager.py` | Per-conversation OrchestrationAgent lifecycle. Creates on first message, caches by session ID, tears down on disconnect. |
| Conversation Route | `src/api/routes/conversations.py` | SSE endpoint replacing `commands.py`. Accepts messages, pipes to agent, streams responses back. |

#### Modified Components

| Component | File | Change |
|-----------|------|--------|
| OrchestrationAgent | `src/orchestrator/agent/client.py` | Add system_prompt config, streaming output, conversation history management. Becomes the actual command path. |
| App Factory | `src/api/main.py` | Register conversations router, session manager lifespan events. |
| API Client | `frontend/src/lib/api.ts` | Add conversation SSE client methods. |
| App State | `frontend/src/hooks/useAppState.tsx` | Switch from job-polling to SSE conversation state. |
| Command Center | `frontend/src/components/CommandCenter.tsx` | Render SSE agent events (thinking, tool calls, previews, completions). |

#### Deprecated (kept, no longer in hot path)

| Component | File | Replaced By |
|-----------|------|-------------|
| CommandProcessor | `src/services/command_processor.py` | Agent's native reasoning + tool calls |
| Intent Parser | `src/orchestrator/nl_engine/intent_parser.py` | Agent's system prompt + native reasoning |
| Filter Generator | `src/orchestrator/nl_engine/filter_generator.py` | Agent's system prompt + native reasoning |
| Commands Route | `src/api/routes/commands.py` | `conversations.py` |

#### Untouched

- `BatchEngine` — deterministic preview/execute engine
- `UPSService` — wraps ToolManager for batch path
- `UPS MCP` (external stdio) — agent's interactive UPS access
- `Data Source MCP` (external stdio) — file import operations
- All database models, job state machine, audit logging
- `hooks.py` — pre/post validation hooks wire into new agent

### Tool Architecture

All tools are **deterministic only**. No tool calls the LLM internally — the agent IS the LLM.

#### Data Source Tools (in-process SDK MCP: `data`)

| Tool | Purpose | Inputs | Returns |
|------|---------|--------|---------|
| `get_source_info` | Active source metadata | none | `{type, row_count, columns}` |
| `get_schema` | Column names, types, samples | none | `[{name, type, nullable, samples}]` |
| `fetch_rows` | SQL WHERE against active source | `where_clause`, `limit` | `{rows: [...], count}` |
| `validate_filter_syntax` | sqlglot syntax check | `where_clause` | `{valid, error?}` |

#### UPS Tools (external stdio MCP: `ups` — unchanged)

| Tool | Purpose |
|------|---------|
| `rate_shipment` | Get cost estimate |
| `create_shipment` | Create shipment + label |
| `void_shipment` | Cancel shipment |
| `validate_address` | Validate/correct address |
| `track_package` | Track delivery status |
| `recover_label` | Recover lost label |
| `get_time_in_transit` | Delivery timeframe |

#### Job Management Tools (in-process SDK MCP: `jobs`)

| Tool | Purpose | Inputs |
|------|---------|--------|
| `create_job` | Create job record in DB | `command`, `name` |
| `add_job_rows` | Create JobRows from data with column mapping | `job_id`, `rows`, `service_code` |
| `batch_preview` | Rate all rows via UPSService | `job_id` |
| `batch_execute` | Execute shipments (requires `approved=true`) | `job_id`, `approved` |
| `get_job_status` | Check job state and progress | `job_id` |

#### Platform Tools (in-process SDK MCP: `platforms`)

| Tool | Purpose | Inputs |
|------|---------|--------|
| `get_shopify_orders` | Fetch orders from Shopify | `status_filter`, `limit` |
| `get_platform_status` | Check connected platforms | none |

### System Prompt Design

The agent's system prompt unifies domain knowledge from `intent_parser.py` and `filter_generator.py` into a single coherent prompt. Built dynamically by `system_prompt.py`.

```
IDENTITY:
  You are ShipAgent, a shipping operations assistant. You process natural
  language shipping commands by reasoning about intent, generating SQL
  filters, and orchestrating batch operations through your available tools.

CORE PRINCIPLE:
  You are a Configuration Engine, not a Data Pipe. You interpret intent
  and decide what tools to call. You NEVER touch row data directly.
  Deterministic tools handle all data operations.

AVAILABLE SERVICES (UPS):
  - Ground (03): ground, gdns, standard, economy
  - Next Day Air (01): overnight, next day, 1-day, next day air, nda
  - 2nd Day Air (02): 2-day, two day, 2day, second day, 2nd day air
  - 3 Day Select (12): 3-day, three day, 3day, third day, 3 day select
  - Next Day Air Saver (13): next day saver, nda saver, overnight saver

CURRENT DATA SOURCE:
  Type: {source_type}  |  Rows: {row_count}
  Columns:
  {dynamic schema with types and sample values — injected per message}

FILTER GENERATION RULES:
  1. ONLY use column names from CURRENT DATA SOURCE schema
  2. Person name disambiguation:
     - Generic name reference → customer_name = 'X' OR ship_to_name = 'X'
     - "placed by" / "bought by" → customer_name only
     - "shipping to" / "deliver to" → ship_to_name only
  3. Status handling:
     - "status" is composite (e.g., "paid/unfulfilled") → use LIKE
     - "financial_status" is standalone → use =
     - "fulfillment_status" is standalone → use =
  4. Date handling:
     - "today" → column = '{current_date}'
     - Temporal filter + multiple date columns → ASK user which column
  5. State abbreviations: California='CA', Texas='TX', etc.
  6. Tags: comma-separated string → tags LIKE '%VIP%'
  7. Weight: total_weight_grams in grams (1 lb = 453.592g)

WORKFLOW:
  1. Parse user's NL command → determine action, service, filter
  2. Call get_schema if you need column info for filter grounding
  3. Call validate_filter_syntax to check your SQL WHERE clause
  4. Call fetch_rows with the SQL WHERE clause
  5. Call create_job → add_job_rows → batch_preview
  6. Present preview summary to user, ask for confirmation
  7. On "yes" → call batch_execute with approved=true
  8. On "no" → offer to adjust parameters and re-preview

RULES:
  - NEVER execute shipments without explicit user confirmation
  - ALWAYS show preview with cost estimates before proposing execution
  - If a filter is ambiguous, ASK the user before proceeding
  - If no data source is connected, tell user to connect one first
  - For Shopify source: call get_shopify_orders, then create job from results
  - Default service code is Ground (03) if user doesn't specify
```

### SSE Conversation Stream

#### Backend Events

| Event Type | Payload | When |
|------------|---------|------|
| `agent_thinking` | `{text: "Parsing intent..."}` | Agent reasoning before tool calls |
| `tool_call` | `{tool, args}` | Agent invokes a tool |
| `tool_result` | `{tool, result}` | Tool returns data |
| `agent_message` | `{text: "Found 15 CA orders..."}` | Agent's conversational response |
| `preview_ready` | `{job_id, preview_data}` | Preview available for user review |
| `confirmation_needed` | `{prompt}` | Agent requests user approval |
| `execution_progress` | `{row, total, status}` | Per-row batch execution progress |
| `completion` | `{job_id, stats, labels}` | Batch complete |
| `error` | `{code, message}` | Error occurred |

#### Frontend Rendering

| Event | Component |
|-------|-----------|
| `agent_thinking` | TypingIndicator with reasoning text |
| `tool_call` | Collapsible tool call chip |
| `tool_result` | Data summary (e.g., "15 rows matched") |
| `agent_message` | Chat bubble (left-aligned, agent) |
| `preview_ready` | PreviewCard (existing component) |
| `confirmation_needed` | Confirm/Cancel buttons in chat |
| `execution_progress` | ProgressDisplay (existing component) |
| `completion` | CompletionArtifact (existing component) |
| `error` | Error message in chat |

#### Conversation Flow Example

```
[user_message]       "Ship California orders via Ground"
[agent_thinking]     "Parsing: action=ship, service=Ground (03), filter=California..."
[tool_call]          get_schema()
[tool_result]        {columns: [{name: "ship_to_state", type: "string"}, ...]}
[tool_call]          validate_filter_syntax({where: "ship_to_state = 'CA'"})
[tool_result]        {valid: true}
[tool_call]          fetch_rows({where: "ship_to_state = 'CA'", limit: 10000})
[tool_result]        {count: 15, rows: [...]}
[tool_call]          create_job({command: "Ship CA orders via Ground"})
[tool_result]        {job_id: "abc-123"}
[tool_call]          add_job_rows({job_id: "abc-123", rows: [...], service_code: "03"})
[tool_result]        {rows_created: 15}
[tool_call]          batch_preview({job_id: "abc-123"})
[tool_result]        {total_cost_cents: 23450, rows: [...]}
[preview_ready]      {job_id: "abc-123", preview_data: {...}}
[agent_message]      "Found 15 California orders. Estimated shipping cost: $234.50
                      via UPS Ground. Would you like to proceed?"
[confirmation_needed] {prompt: "Confirm shipment?"}

[user_message]       "Yes, ship them"
[tool_call]          batch_execute({job_id: "abc-123", approved: true})
[execution_progress] {row: 1, total: 15, status: "shipping"}
  ...
[execution_progress] {row: 15, total: 15, status: "complete"}
[completion]         {job_id: "abc-123", successful: 15, failed: 0}
[agent_message]      "All 15 shipments created successfully! Click 'View Labels'
                      to download your shipping labels."
```

### API Endpoints

#### New Endpoints

| Route | Method | Purpose |
|-------|--------|---------|
| `/conversations/` | POST | Create new conversation session |
| `/conversations/{id}/messages` | POST | Send user message to agent |
| `/conversations/{id}/stream` | GET | SSE stream of agent events |
| `/conversations/{id}` | DELETE | End conversation, teardown agent |

#### Kept Endpoints (unchanged)

| Route | Method | Purpose |
|-------|--------|---------|
| `/jobs/` | GET | List all jobs |
| `/jobs/{id}` | GET | Get job details |
| `/jobs/{id}/labels/merged` | GET | Download merged labels |
| `/jobs/{id}/labels/{tracking}` | GET | Download individual label |
| `/jobs/{id}/logs` | GET | Get audit logs |
| `/saved-sources` | * | All saved source operations |
| `/platforms/shopify/env-status` | GET | Shopify connection check |

#### Deprecated Endpoints

| Route | Method | Replaced By |
|-------|--------|-------------|
| `/commands/` | POST | `/conversations/{id}/messages` |
| `/jobs/{id}/preview` | GET | Agent streams preview via SSE |
| `/jobs/{id}/preview/confirm` | POST | User confirms via chat message |
| `/jobs/{id}/progress/stream` | GET | Progress streams via conversation SSE |

## Migration Strategy

### Implementation Order

| Step | Task | Risk | Dependencies |
|------|------|------|-------------|
| 1 | Build `system_prompt.py` | Zero — new file | None |
| 2 | Build `tools_v2.py` (deterministic SDK tools) | Zero — new file | None |
| 3 | Build `agent_session_manager.py` | Zero — new file | None |
| 4 | Enhance `OrchestrationAgent` in `client.py` | Low — existing file | Steps 1-3 |
| 5 | Build `conversations.py` route | Zero — new file | Step 4 |
| 6 | Wire into `main.py` | Low — add router | Step 5 |
| 7 | Frontend: SSE conversation hook + CommandCenter | Medium — UI changes | Step 6 |
| 8 | Integration test: full end-to-end flow | Validation | Step 7 |
| 9 | Deprecate old path | Low — no deletion | Step 8 |

### What Gets Wrapped (not rewritten)

| Existing Service | New Tool Wrapper |
|-----------------|-----------------|
| `DataSourceService.get_rows_by_filter()` | `fetch_rows` tool |
| `DataSourceService.get_source_info()` | `get_source_info` tool |
| `column_mapping.auto_map_columns()` | Part of `add_job_rows` tool |
| `BatchEngine.preview()` | `batch_preview` tool |
| `BatchEngine.execute()` | `batch_execute` tool |
| `JobService.create_job()` | `create_job` tool |
| Shopify client `fetch_orders()` | `get_shopify_orders` tool |

### Rollback Plan

The old path (`commands.py` → `CommandProcessor`) is deprecated but not deleted. If the new path has issues:

1. Re-enable `commands.py` route in `main.py`
2. Frontend falls back to `POST /commands/` + job polling
3. No data loss — all job/row records are in SQLite regardless of path

## Testing Strategy

| Test Type | Scope |
|-----------|-------|
| Unit tests | Each tool in `tools_v2.py` independently |
| Unit tests | `system_prompt.py` prompt generation |
| Unit tests | `agent_session_manager.py` lifecycle |
| Integration tests | Agent + tools end-to-end (mock UPS) |
| Frontend tests | SSE event rendering in CommandCenter |
| E2E test | Full user command → preview → confirm → execute |

## Success Criteria

- [ ] `POST /conversations/{id}/messages` handles NL shipping commands end-to-end
- [ ] Agent reasons about intent and filters natively (zero raw `Anthropic()` calls in hot path)
- [ ] All 7 UPS MCP tools accessible to agent via stdio
- [ ] Preview displayed before any execution
- [ ] User confirmation required before batch_execute
- [ ] SSE stream delivers real-time agent events to frontend
- [ ] Per-row execution progress streams via SSE
- [ ] Existing job/label/audit endpoints continue working
- [ ] Hooks (pre/post tool validation) fire for all tool calls
- [ ] Conversation context persists across messages within a session
- [ ] Old `POST /commands/` path still works (deprecated but functional)
