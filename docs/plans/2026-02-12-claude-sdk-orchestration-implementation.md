# Claude SDK Orchestration Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the Claude Agent SDK the primary orchestration path, replacing the bypassed CommandProcessor with an agent-driven SSE conversation flow.

**Architecture:** The REST layer becomes a thin pipe between the frontend and the Claude SDK agent loop. The agent reasons natively about intent/filters (no separate Anthropic() calls), invokes deterministic tools for data/UPS operations, and streams events to the frontend via SSE. Per-conversation agent sessions persist MCP servers for the session duration.

**Tech Stack:** Python 3.12+, FastAPI, Claude Agent SDK (`claude_agent_sdk`), SSE (`sse-starlette`), React, TypeScript, Tailwind CSS

**Design doc:** `docs/plans/2026-02-12-claude-sdk-orchestration-redesign-design.md`

**Worktree:** `.worktrees/sdk-orchestration` on branch `feature/sdk-orchestration-redesign`

**Baseline:** 908 tests passing, 2 pre-existing failures (zipstream), EDI collection errors excluded

---

## Task 1: Build System Prompt Builder

**Files:**
- Create: `src/orchestrator/agent/system_prompt.py`
- Test: `tests/orchestrator/agent/test_system_prompt.py`

This module dynamically builds the agent's system prompt by merging shipping domain knowledge (service codes, filter rules, workflow) with the current data source schema. The schema is injected per-message so the agent always has accurate column info.

**Step 1: Write the test file**

Create `tests/orchestrator/agent/test_system_prompt.py` with tests for:
- `build_system_prompt()` returns a string containing "ShipAgent" identity
- `build_system_prompt()` includes UPS service code table (Ground=03, Next Day Air=01, etc.)
- `build_system_prompt()` includes filter generation rules (person name disambiguation, status handling, date handling)
- `build_system_prompt(source_info=...)` includes dynamic schema with column names, types, and sample values
- `build_system_prompt()` without source_info includes "No data source connected" message
- `build_system_prompt()` includes workflow steps (1-8)
- `build_system_prompt()` includes safety rules (never execute without confirmation)

Key test signatures:
```python
def test_prompt_contains_identity():
def test_prompt_contains_service_codes():
def test_prompt_contains_filter_rules():
def test_prompt_includes_source_schema():
def test_prompt_without_source_shows_no_connection():
def test_prompt_contains_workflow():
def test_prompt_contains_safety_rules():
```

**Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/orchestrator/agent/test_system_prompt.py -v
```
Expected: FAIL — `ImportError: cannot import name 'build_system_prompt'`

**Step 3: Implement `system_prompt.py`**

Create `src/orchestrator/agent/system_prompt.py` with:
- `build_system_prompt(source_info: DataSourceInfo | None = None) -> str`
- Imports `SERVICE_ALIASES`, `ServiceCode` from `src.orchestrator.models.intent`
- Imports `DataSourceInfo` from `src.services.data_source_service`
- Uses `datetime.now()` for current date injection
- Includes ALL filter rules from the existing `filter_generator.py` system prompt (person name handling, status handling, date handling, state abbreviations, tag matching, weight conversion)
- Includes ALL service aliases from `intent_parser.py`
- Includes the 8-step workflow from the design doc
- Includes safety rules (never execute without confirmation, always preview first)

**Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/orchestrator/agent/test_system_prompt.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
git add src/orchestrator/agent/system_prompt.py tests/orchestrator/agent/test_system_prompt.py
git commit -m "feat: add system prompt builder for SDK orchestration agent"
```

---

## Task 2: Build Deterministic SDK Tools (tools_v2.py)

**Files:**
- Create: `src/orchestrator/agent/tools_v2.py`
- Test: `tests/orchestrator/agent/test_tools_v2.py`

Clean deterministic-only tools for the SDK agent. No tool calls the LLM internally. Each tool wraps existing services with thin SDK-compatible interfaces.

**Step 1: Write the test file**

Create `tests/orchestrator/agent/test_tools_v2.py` with tests for each tool function.

Tools to implement and test:
1. `get_source_info_tool(args)` — wraps `DataSourceService.get_source_info()`
2. `get_schema_tool(args)` — wraps `DataSourceService.get_schema()`
3. `fetch_rows_tool(args)` — wraps `DataSourceService.get_rows_by_filter(where_clause, limit)`
4. `validate_filter_syntax_tool(args)` — wraps `sqlglot.parse()` for SQL validation
5. `create_job_tool(args)` — wraps `JobService.create_job(name, command)`
6. `add_job_rows_tool(args)` — creates JobRows from filtered data with column mapping
7. `batch_preview_tool(args)` — wraps `BatchEngine.preview()`
8. `batch_execute_tool(args)` — wraps `BatchEngine.execute()` with `approved` gate
9. `get_job_status_tool(args)` — wraps `JobService.get_job_summary()`
10. `get_shopify_orders_tool(args)` — wraps Shopify client `fetch_orders()`
11. `get_platform_status_tool(args)` — checks connected platforms

Each test should:
- Mock the underlying service (DataSourceService, JobService, BatchEngine, etc.)
- Verify the tool returns `{"content": [{"type": "text", "text": ...}]}` format
- Verify error cases return `{"isError": True, ...}`

Also test `get_all_tool_definitions()` returns the complete list of tool defs.

Key test signatures:
```python
@pytest.mark.asyncio
async def test_get_source_info_returns_metadata():
@pytest.mark.asyncio
async def test_get_source_info_no_connection_returns_error():
@pytest.mark.asyncio
async def test_fetch_rows_with_valid_filter():
@pytest.mark.asyncio
async def test_validate_filter_syntax_valid():
@pytest.mark.asyncio
async def test_validate_filter_syntax_invalid():
@pytest.mark.asyncio
async def test_create_job_returns_job_id():
@pytest.mark.asyncio
async def test_batch_execute_requires_approval():
def test_get_all_tool_definitions_count():
```

**Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/orchestrator/agent/test_tools_v2.py -v
```
Expected: FAIL — import errors

**Step 3: Implement `tools_v2.py`**

Create `src/orchestrator/agent/tools_v2.py` with:

Each tool is an `async def` that takes `args: dict[str, Any]` and returns `dict[str, Any]` in MCP tool response format.

Key implementation details:
- `validate_filter_syntax_tool` uses `sqlglot.parse()` — deterministic, no LLM
- `add_job_rows_tool` imports and uses `auto_map_columns()`, `apply_mapping()` from `column_mapping.py`
- `batch_execute_tool` checks `args.get("approved", False)` and returns error if not approved
- `create_job_tool` uses `JobService.create_job()` inside `get_db_context()`
- All tools handle exceptions and return `{"isError": True, "content": [...]}`

Also implement `get_all_tool_definitions() -> list[dict]` that returns tool name, description, input_schema, and handler function for each tool.

**Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/orchestrator/agent/test_tools_v2.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools_v2.py tests/orchestrator/agent/test_tools_v2.py
git commit -m "feat: add deterministic SDK tools for agent orchestration"
```

---

## Task 3: Build Agent Session Manager

**Files:**
- Create: `src/services/agent_session_manager.py`
- Test: `tests/services/test_agent_session_manager.py`

Manages per-conversation OrchestrationAgent lifecycle. Creates agent on first message, caches by session ID, tears down on disconnect.

**Step 1: Write the test file**

Create `tests/services/test_agent_session_manager.py` with tests for:
- `get_or_create_session(session_id)` creates a new session on first call
- `get_or_create_session(session_id)` returns same session on subsequent calls
- `remove_session(session_id)` removes the session
- `remove_session(session_id)` is idempotent (no error if not found)
- `list_sessions()` returns all active session IDs
- Session stores conversation history (list of messages)
- `add_message(session_id, role, content)` appends to history
- `get_history(session_id)` returns conversation messages

All tests should mock `OrchestrationAgent` to avoid spawning real MCP servers.

Key test signatures:
```python
def test_create_new_session():
def test_get_existing_session():
def test_remove_session():
def test_remove_nonexistent_session():
def test_list_sessions():
def test_add_message():
def test_get_history():
```

**Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/services/test_agent_session_manager.py -v
```
Expected: FAIL — import errors

**Step 3: Implement `agent_session_manager.py`**

Create `src/services/agent_session_manager.py` with:

```python
class AgentSession:
    """A single conversation session with an agent."""
    session_id: str
    history: list[dict]  # [{role, content, timestamp}]
    created_at: datetime

class AgentSessionManager:
    """Manages per-conversation agent sessions."""
    _sessions: dict[str, AgentSession]

    def get_or_create_session(self, session_id: str) -> AgentSession
    def remove_session(self, session_id: str) -> None
    def list_sessions(self) -> list[str]
    def add_message(self, session_id: str, role: str, content: str) -> None
    def get_history(self, session_id: str) -> list[dict]
```

Note: The actual OrchestrationAgent is NOT created here yet — it will be wired in Task 4. This task focuses on session state management. The agent integration comes when we enhance `client.py`.

**Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/services/test_agent_session_manager.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
git add src/services/agent_session_manager.py tests/services/test_agent_session_manager.py
git commit -m "feat: add agent session manager for per-conversation lifecycle"
```

---

## Task 4: Enhance OrchestrationAgent with System Prompt + Streaming

**Files:**
- Modify: `src/orchestrator/agent/client.py`
- Test: `tests/orchestrator/agent/test_client_enhanced.py`

Enhance the existing OrchestrationAgent to use the new system prompt, tools_v2 tools, and support streaming output for SSE.

**Step 1: Write the test file**

Create `tests/orchestrator/agent/test_client_enhanced.py` with tests for:
- `OrchestrationAgent` constructor accepts `system_prompt` parameter
- `OrchestrationAgent._create_options()` includes system_prompt in options
- `OrchestrationAgent._create_options()` includes tools_v2 tools in orchestrator MCP server
- `process_message(user_input, history)` accepts conversation history
- `process_message_stream(user_input, history)` yields events (thinking, tool_call, tool_result, message)

Tests should mock `ClaudeSDKClient` to avoid real API calls.

Key test signatures:
```python
def test_constructor_accepts_system_prompt():
def test_options_include_system_prompt():
def test_options_include_v2_tools():
@pytest.mark.asyncio
async def test_process_message_with_history():
```

**Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/orchestrator/agent/test_client_enhanced.py -v
```
Expected: FAIL

**Step 3: Modify `client.py`**

Changes to `src/orchestrator/agent/client.py`:

1. Add `system_prompt` parameter to `__init__`:
   ```python
   def __init__(self, system_prompt: str | None = None, max_turns: int = 50, ...):
       self._system_prompt = system_prompt
   ```

2. In `_create_options()`, pass `system_prompt` to `ClaudeAgentOptions`:
   ```python
   return ClaudeAgentOptions(
       system_prompt=self._system_prompt,
       ...
   )
   ```

3. Replace `_create_orchestrator_mcp_server()` to use `tools_v2.get_all_tool_definitions()` instead of the old `get_orchestrator_tools()`.

4. Add `process_message()` method that accepts conversation history:
   ```python
   async def process_message(self, user_input: str, history: list[dict] | None = None) -> str:
   ```

5. Add `process_message_stream()` async generator that yields SSE-compatible event dicts:
   ```python
   async def process_message_stream(self, user_input: str, history: list[dict] | None = None):
       # Yields: {"event": "agent_thinking", "data": {...}}
       #         {"event": "tool_call", "data": {...}}
       #         {"event": "tool_result", "data": {...}}
       #         {"event": "agent_message", "data": {...}}
   ```

**Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/orchestrator/agent/test_client_enhanced.py -v
```
Expected: All PASS

**Step 5: Run existing client tests to check for regressions**

```bash
python3 -m pytest tests/orchestrator/agent/test_client.py -v
```
Expected: All PASS (no regressions)

**Step 6: Commit**

```bash
git add src/orchestrator/agent/client.py tests/orchestrator/agent/test_client_enhanced.py
git commit -m "feat: enhance OrchestrationAgent with system prompt and streaming"
```

---

## Task 5: Build Conversations SSE Route

**Files:**
- Create: `src/api/routes/conversations.py`
- Create: `src/api/schemas_conversations.py` (Pydantic models for conversation API)
- Test: `tests/api/test_conversations.py`

SSE endpoint that replaces `commands.py`. Accepts user messages, pipes them to the agent session, and streams agent events back.

**Step 1: Write the test file**

Create `tests/api/test_conversations.py` with tests using FastAPI `TestClient`:

- `POST /conversations/` creates a new conversation session, returns `{session_id}`
- `POST /conversations/{id}/messages` with `{"content": "Ship CA orders"}` returns 202
- `GET /conversations/{id}/stream` returns SSE content type
- `DELETE /conversations/{id}` removes the session, returns 204
- `POST /conversations/{nonexistent}/messages` returns 404
- Test that messages are added to session history

Key test signatures:
```python
def test_create_conversation():
def test_send_message():
def test_stream_endpoint_exists():
def test_delete_conversation():
def test_send_to_nonexistent_returns_404():
def test_message_stored_in_history():
```

Note: Full SSE streaming test is complex — test that the endpoint exists and returns correct content type. Full integration testing is Task 8.

**Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/api/test_conversations.py -v
```
Expected: FAIL — import errors

**Step 3: Create conversation Pydantic schemas**

Create `src/api/schemas_conversations.py`:

```python
class CreateConversationResponse(BaseModel):
    session_id: str

class SendMessageRequest(BaseModel):
    content: str

class SendMessageResponse(BaseModel):
    status: str  # "accepted"
    session_id: str
```

**Step 4: Implement `conversations.py` route**

Create `src/api/routes/conversations.py`:

```python
router = APIRouter(prefix="/conversations", tags=["conversations"])

# Module-level session manager instance
_session_manager = AgentSessionManager()

@router.post("/", response_model=CreateConversationResponse, status_code=201)
async def create_conversation() -> CreateConversationResponse:
    """Create a new conversation session."""
    session_id = str(uuid4())
    _session_manager.get_or_create_session(session_id)
    return CreateConversationResponse(session_id=session_id)

@router.post("/{session_id}/messages", status_code=202)
async def send_message(
    session_id: str,
    payload: SendMessageRequest,
    background_tasks: BackgroundTasks,
) -> SendMessageResponse:
    """Send a user message to the conversation agent."""
    session = _session_manager.get_or_create_session(session_id)
    _session_manager.add_message(session_id, "user", payload.content)
    # Background: process via agent, push events to session's event queue
    background_tasks.add_task(_process_agent_message, session_id, payload.content)
    return SendMessageResponse(status="accepted", session_id=session_id)

@router.get("/{session_id}/stream")
async def stream_events(session_id: str):
    """SSE stream of agent events for this conversation."""
    # Returns EventSourceResponse that reads from session's event queue
    ...

@router.delete("/{session_id}", status_code=204)
async def delete_conversation(session_id: str) -> None:
    """End conversation and teardown agent."""
    _session_manager.remove_session(session_id)
```

The `_process_agent_message` function:
1. Builds system prompt with current data source schema
2. Gets/creates the agent for this session
3. Calls `agent.process_message_stream()`
4. Pushes each event to the session's asyncio.Queue
5. Frontend reads events via `GET /stream` SSE endpoint

**Step 5: Run tests to verify they pass**

```bash
python3 -m pytest tests/api/test_conversations.py -v
```
Expected: All PASS

**Step 6: Commit**

```bash
git add src/api/routes/conversations.py src/api/schemas_conversations.py tests/api/test_conversations.py
git commit -m "feat: add SSE conversation route for agent-driven command flow"
```

---

## Task 6: Wire Conversations Router into Main App

**Files:**
- Modify: `src/api/main.py`
- Test: Verify with existing test suite + manual check

**Step 1: Add import and router registration**

In `src/api/main.py`:
1. Add import: `from src.api.routes import conversations`
2. Add router: `app.include_router(conversations.router, prefix="/api/v1")`

Place after the existing router registrations (line ~89).

**Step 2: Run tests to verify no regressions**

```bash
python3 -m pytest tests/api/ -v -q --ignore=tests/api/test_labels.py -k "not stream and not sse"
```
Expected: All PASS

**Step 3: Verify endpoint registration**

```bash
python3 -c "
from src.api.main import app
routes = [r.path for r in app.routes if hasattr(r, 'path')]
conv_routes = [r for r in routes if 'conversation' in r]
print('Conversation routes:', conv_routes)
assert len(conv_routes) >= 3, f'Expected >= 3 conversation routes, got {len(conv_routes)}'
print('OK: Conversation routes registered')
"
```

**Step 4: Commit**

```bash
git add src/api/main.py
git commit -m "feat: register conversations router in main app"
```

---

## Task 7: Frontend — Add Conversation API Client

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/types/api.ts`

Add the frontend API methods and types for the new conversation endpoints.

**Step 1: Add conversation types to `api.ts` (types file)**

Add to `frontend/src/types/api.ts`:

```typescript
// === Conversation Types ===

/** Agent event types streamed via SSE. */
export type AgentEventType =
  | 'agent_thinking'
  | 'tool_call'
  | 'tool_result'
  | 'agent_message'
  | 'preview_ready'
  | 'confirmation_needed'
  | 'execution_progress'
  | 'completion'
  | 'error';

/** Base agent event. */
export interface AgentEvent {
  event: AgentEventType;
  data: Record<string, unknown>;
}

/** Create conversation response. */
export interface CreateConversationResponse {
  session_id: string;
}

/** Send message response. */
export interface SendMessageResponse {
  status: string;
  session_id: string;
}
```

**Step 2: Add conversation API methods to `api.ts` (client file)**

Add to `frontend/src/lib/api.ts`:

```typescript
// === Conversation API ===

import type {
  CreateConversationResponse,
  SendMessageResponse,
  AgentEvent,
} from '@/types/api';

/**
 * Create a new conversation session.
 */
export async function createConversation(): Promise<CreateConversationResponse> {
  const response = await fetch(`${API_BASE}/conversations/`, {
    method: 'POST',
  });
  return parseResponse<CreateConversationResponse>(response);
}

/**
 * Send a user message to the conversation agent.
 */
export async function sendConversationMessage(
  sessionId: string,
  content: string
): Promise<SendMessageResponse> {
  const response = await fetch(`${API_BASE}/conversations/${sessionId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  return parseResponse<SendMessageResponse>(response);
}

/**
 * Get the SSE stream URL for a conversation.
 */
export function getConversationStreamUrl(sessionId: string): string {
  return `${API_BASE}/conversations/${sessionId}/stream`;
}

/**
 * End a conversation session.
 */
export async function deleteConversation(sessionId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/conversations/${sessionId}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    await parseResponse(response);
  }
}
```

**Step 3: Type check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: No errors

**Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/types/api.ts
git commit -m "feat: add conversation API client and types for frontend"
```

---

## Task 8: Frontend — Add useConversation Hook

**Files:**
- Create: `frontend/src/hooks/useConversation.ts`

Custom hook that manages the conversation lifecycle: creates session, sends messages, listens to SSE stream, and maintains event history.

**Step 1: Implement the hook**

Create `frontend/src/hooks/useConversation.ts`:

```typescript
import { useState, useRef, useCallback, useEffect } from 'react';
import {
  createConversation,
  sendConversationMessage,
  getConversationStreamUrl,
  deleteConversation,
} from '@/lib/api';
import type { AgentEvent } from '@/types/api';

interface ConversationEvent {
  id: string;
  type: AgentEvent['event'];
  data: Record<string, unknown>;
  timestamp: Date;
}

interface UseConversationReturn {
  sessionId: string | null;
  events: ConversationEvent[];
  isConnected: boolean;
  isProcessing: boolean;
  sendMessage: (content: string) => Promise<void>;
  reset: () => Promise<void>;
}

export function useConversation(): UseConversationReturn {
  // State: sessionId, events[], isConnected, isProcessing
  // EventSource ref for SSE
  // On mount: create conversation, connect SSE
  // sendMessage: POST to /messages, set isProcessing
  // SSE events: parse and append to events[]
  // reset: close EventSource, delete conversation, create new one
}
```

**Step 2: Type check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/hooks/useConversation.ts
git commit -m "feat: add useConversation hook for SSE agent communication"
```

---

## Task 9: Frontend — Update CommandCenter for Conversation Mode

**Files:**
- Modify: `frontend/src/components/CommandCenter.tsx`
- Modify: `frontend/src/hooks/useAppState.tsx`

Update the CommandCenter to use the new conversation hook for agent-driven flow while keeping backward compatibility with the old polling flow (controlled by a feature flag or detection of conversation endpoint availability).

**Step 1: Add conversation session state to useAppState**

In `frontend/src/hooks/useAppState.tsx`, add:
- `conversationSessionId: string | null` to AppState
- `setConversationSessionId: (id: string | null) => void`

**Step 2: Update CommandCenter to use useConversation**

In `frontend/src/components/CommandCenter.tsx`:

1. Import `useConversation` hook
2. Add conversation event renderer that maps events to existing components:
   - `agent_thinking` → TypingIndicator with text
   - `agent_message` → system message bubble
   - `preview_ready` → existing PreviewCard
   - `confirmation_needed` → Confirm/Cancel buttons
   - `execution_progress` → existing ProgressDisplay
   - `completion` → existing CompletionArtifact
   - `error` → error message
3. The submit handler switches between old path (`submitCommand`) and new path (`sendConversationMessage`) based on whether a conversation session exists
4. Add "thinking" states for tool calls (collapsible chips showing tool name)

**Step 3: Type check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: No errors

**Step 4: Build check**

```bash
cd frontend && npm run build
```
Expected: Build succeeds

**Step 5: Commit**

```bash
git add frontend/src/components/CommandCenter.tsx frontend/src/hooks/useAppState.tsx
git commit -m "feat: update CommandCenter for agent-driven conversation flow"
```

---

## Task 10: Integration Test — Full End-to-End Flow

**Files:**
- Create: `tests/integration/test_conversation_flow.py`

End-to-end test that verifies the full conversation flow works with mocked external services.

**Step 1: Write integration test**

Create `tests/integration/test_conversation_flow.py`:

Tests:
1. Create conversation session
2. Send message, verify 202 response
3. Verify session has message in history
4. Verify agent events are generated (mock the Claude SDK client)
5. Delete conversation, verify cleanup

Key test signatures:
```python
@pytest.mark.asyncio
async def test_full_conversation_flow():
    """Create session → send message → verify events → cleanup."""

def test_conversation_crud():
    """Create, list, delete conversation sessions."""

def test_conversation_not_found():
    """Send to nonexistent session returns 404."""
```

**Step 2: Run integration tests**

```bash
python3 -m pytest tests/integration/test_conversation_flow.py -v
```
Expected: All PASS

**Step 3: Run full test suite to check for regressions**

```bash
python3 -m pytest -q --ignore=tests/integration/mcp --ignore=tests/mcp/test_edi_adapter.py --ignore=tests/mcp/test_edi_tools.py --ignore=tests/mcp/test_edifact_parser.py -k "not test_stream_endpoint_exists and not stream and not sse"
```
Expected: 908+ passed (new tests added), 2 pre-existing failures

**Step 4: Commit**

```bash
git add tests/integration/test_conversation_flow.py
git commit -m "test: add integration tests for conversation flow"
```

---

## Task 11: Deprecate Old Command Path

**Files:**
- Modify: `src/api/routes/commands.py`
- Modify: `src/services/command_processor.py`
- Modify: `src/orchestrator/nl_engine/intent_parser.py`
- Modify: `src/orchestrator/nl_engine/filter_generator.py`

Mark the old path as deprecated. Do NOT delete — keep it functional as a fallback.

**Step 1: Add deprecation notices**

Add deprecation docstrings and logging to:
- `commands.py`: Add `Deprecated: Use /conversations/ endpoint instead` to module docstring and route docstrings
- `command_processor.py`: Add deprecation notice to class docstring
- `intent_parser.py`: Add deprecation notice to `parse_intent()` docstring
- `filter_generator.py`: Add deprecation notice to `generate_filter()` docstring

**Step 2: Add deprecation warning header to REST response**

In `commands.py` `submit_command()`, add a response header:
```python
response.headers["Deprecation"] = "true"
response.headers["Link"] = '</api/v1/conversations/>; rel="successor-version"'
```

**Step 3: Run tests — no breakage**

```bash
python3 -m pytest tests/api/test_commands.py -v
```
Expected: All PASS

**Step 4: Commit**

```bash
git add src/api/routes/commands.py src/services/command_processor.py src/orchestrator/nl_engine/intent_parser.py src/orchestrator/nl_engine/filter_generator.py
git commit -m "docs: mark old command path as deprecated in favor of conversations"
```

---

## Task 12: Update CLAUDE.md with New Architecture

**Files:**
- Modify: `CLAUDE.md`

Update the project documentation to reflect the new architecture.

**Step 1: Update sections**

- Add new API endpoints (conversations) to the API table
- Update the system component diagram to show Agent-driven flow
- Update the data flow description
- Note the deprecated endpoints
- Add `conversations.py`, `system_prompt.py`, `tools_v2.py`, `agent_session_manager.py` to source structure
- Update architecture description to reflect "agent-driven SSE conversation flow"

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for SDK orchestration redesign"
```

---

## Execution Notes

### Test commands for the full suite:

```bash
# Backend tests (excluding known issues)
python3 -m pytest -q --ignore=tests/integration/mcp --ignore=tests/mcp/test_edi_adapter.py --ignore=tests/mcp/test_edi_tools.py --ignore=tests/mcp/test_edifact_parser.py -k "not test_stream_endpoint_exists and not stream and not sse"

# Frontend type check
cd frontend && npx tsc --noEmit

# Frontend build
cd frontend && npm run build
```

### Key imports reference:

```python
# System prompt
from src.orchestrator.agent.system_prompt import build_system_prompt

# Tools v2
from src.orchestrator.agent.tools_v2 import get_all_tool_definitions

# Session manager
from src.services.agent_session_manager import AgentSessionManager, AgentSession

# Data source
from src.services.data_source_service import DataSourceService, DataSourceInfo

# Job service
from src.services.job_service import JobService
from src.db.connection import get_db_context

# Column mapping
from src.services.column_mapping import auto_map_columns, apply_mapping, validate_mapping, translate_service_name

# Batch engine
from src.services.batch_engine import BatchEngine
from src.services.ups_service import UPSService
from src.services.ups_payload_builder import build_shipper_from_env

# Models
from src.orchestrator.models.intent import SERVICE_ALIASES, ServiceCode, CODE_TO_SERVICE
from src.orchestrator.models.filter import ColumnInfo

# SQL validation
import sqlglot
```

### Files NOT to modify:

- `src/services/batch_engine.py` — wrapped, not modified
- `src/services/ups_service.py` — wrapped, not modified
- `src/services/column_mapping.py` — imported, not modified
- `src/services/job_service.py` — imported, not modified
- `src/orchestrator/agent/hooks.py` — reused as-is
- `src/orchestrator/agent/config.py` — reused as-is
- All database models — untouched
- All existing frontend components (PreviewCard, ProgressDisplay, CompletionArtifact) — reused
