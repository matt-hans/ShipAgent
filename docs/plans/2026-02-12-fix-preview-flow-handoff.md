# Fix Agent Preview Flow — Development Handoff

> **For Claude:** Read this entire document before making any changes. Follow the fixes in order. Each fix is independent but they all contribute to a cohesive experience.

## Problem Summary

After the SDK orchestration redesign, the agent-driven conversation flow has three categories of bugs that produce a messy, slow, and confusing user experience:

1. **Agent doesn't stop after preview** — The agent generates a redundant text summary of preview data AND continues processing (spinner stays active, more events stream in) after the PreviewCard already renders
2. **Duplicate/stale tool call chips** — Tool call chips duplicate (StreamEvent + AssistantMessage both emit `tool_call`) and accumulate across the entire session, showing old tool calls from previous steps
3. **Performance** — Preview is still slow because `_run_batch_preview()` spawns a brand new UPS MCP process for every preview call (expensive process startup), and the UPS rate API calls are inherently slow (~6-10s each)

## Architecture Context

```
User types command
  → POST /conversations/{id}/messages
  → _process_agent_message() [background task]
    → set_event_emitter(callback)   ← bridges tool events to SSE queue
    → OrchestrationAgent.process_message_stream(content)
      → SDK agent loop (query → receive_response)
        → StreamEvent (content_block_start/delta/stop) → yields SSE events
        → AssistantMessage (TextBlock, ToolUseBlock) → yields SSE events
        → SDK calls tool handler (e.g. batch_preview_tool)
          → _run_batch_preview() → BatchEngine.preview()
          → _enrich_preview_rows() → normalize for frontend
          → _emit_event("preview_ready", result)  ← goes directly to SSE queue
          → return _ok(result) → SDK gets tool result → LLM generates text
        → ResultMessage → break
  → SSE stream sends events to frontend
  → CommandCenter.tsx processes events:
    - agent_message → addMessage() to conversation
    - agent_message_delta → (currently unused in rendering)
    - preview_ready → setPreview() → PreviewCard renders
    - tool_call → ToolCallChip renders (while isProcessing)
    - done → isProcessing = false
```

**Key insight:** The `batch_preview_tool` both (a) emits `preview_ready` to the SSE queue for the PreviewCard, AND (b) returns the full result to the SDK which the LLM uses to generate a text summary. The LLM's text summary is redundant — the PreviewCard already shows the data visually. After the preview, the agent should STOP and wait for user confirmation.

---

## Fix 1: Suppress Agent Text After Preview (Backend)

### Problem
After `batch_preview_tool` returns its result to the SDK, the LLM generates a multi-paragraph text summary of the preview data. This text appears in the chat alongside the PreviewCard, creating redundancy and clutter. The agent also continues thinking and may call additional tools.

### Root Cause
`batch_preview_tool` returns `_ok(result)` with the full preview data as JSON text. The SDK feeds this to the LLM, which then generates a conversational summary. There's no mechanism to tell the SDK "stop after this tool result."

### Fix
Modify `batch_preview_tool` to return a short instruction instead of the full data. The LLM doesn't need the full preview data since the frontend already renders it via the `preview_ready` event.

### File: `src/orchestrator/agent/tools_v2.py`

**Function:** `batch_preview_tool` (line ~406)

Change the return from:
```python
return _ok(result)
```
To:
```python
return _ok({
    "status": "preview_ready",
    "job_id": job_id,
    "total_rows": result.get("total_rows", 0),
    "total_estimated_cost_cents": result.get("total_estimated_cost_cents", 0),
    "rows_with_warnings": rows_with_warnings,
    "message": (
        "Preview card has been displayed to the user. "
        "STOP HERE. Do NOT summarize the preview data — the user can see it in the preview card. "
        "Simply tell the user to review the preview and click Confirm or Cancel."
    ),
})
```

This gives the LLM enough context to reference the preview conversationally ("I've prepared a preview of 22 shipments totaling $XXX — please review and confirm") without dumping all the row-level data into a wall of text.

### File: `src/orchestrator/agent/system_prompt.py`

**Function:** `build_system_prompt` (line ~60)

Strengthen step 9 in the Workflow section. Replace lines 148-149:

```python
9. **Await Confirmation**: After preview, tell the user to review the preview card and click Confirm or Cancel. The frontend handles execution automatically — do NOT call `batch_execute` yourself. If the user says "confirmed" or "go ahead", acknowledge that execution is in progress
```

With:
```python
9. **Await Confirmation**: After calling `batch_preview`, the preview card is automatically displayed to the user. Your ONLY response should be a brief one-sentence message like "I've prepared a preview of X shipments — please review and click Confirm or Cancel." Do NOT list individual shipments, costs, or any preview details — the preview card already shows all of this. Do NOT call any more tools after preview. Do NOT call `batch_execute` — the frontend handles execution via the Confirm button.
```

Also add to Safety Rules (after line 154):
```python
- After calling batch_preview, you must NOT generate a detailed summary of the preview data. The preview card handles this. Just acknowledge it's ready.
- After calling batch_preview, you must NOT call any additional tools. Wait for user confirmation.
```

---

## Fix 2: Fix Duplicate Tool Call Events (Backend)

### Problem
When the SDK agent calls a tool, the `process_message_stream` method emits `tool_call` events from TWO sources:
1. `StreamEvent` with `content_block_start` type `tool_use` (line 289-298)
2. `AssistantMessage` with `ToolUseBlock` (line 326-337)

The dedup logic on line 330 (`if not streamed_text_in_turn`) only suppresses the AssistantMessage path when text was also streamed in the same turn. For tool-only turns (no text before the tool call), both paths emit, creating duplicates.

### File: `src/orchestrator/agent/client.py`

**Function:** `process_message_stream` (line 249)

Replace the dedup tracking to use a set of emitted tool IDs instead of a boolean flag. Every `ToolUseBlock` has a unique `id` attribute that matches the `content_block_start` event's `content_block.id`.

Replace the current implementation (lines 275-356) with:

```python
try:
    await self._client.query(user_input)

    # Track emitted content to prevent duplicates between
    # StreamEvent and AssistantMessage paths
    streamed_text_in_turn = False
    emitted_tool_ids: set[str] = set()
    current_text_parts: list[str] = []

    async for message in self._client.receive_response():
        # --- StreamEvent: real-time deltas (include_partial_messages) ---
        if _HAS_STREAM_EVENT and isinstance(message, StreamEvent):
            event = message.event
            event_type = event.get("type")

            if event_type == "content_block_start":
                cb = event.get("content_block", {})
                if cb.get("type") == "tool_use":
                    tool_id = cb.get("id", "")
                    if tool_id:
                        emitted_tool_ids.add(tool_id)
                    yield {
                        "event": "tool_call",
                        "data": {
                            "tool_name": cb.get("name", "unknown"),
                            "tool_input": cb.get("input", {}),
                        },
                    }
                elif cb.get("type") == "text":
                    current_text_parts = []

            elif event_type == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        streamed_text_in_turn = True
                        current_text_parts.append(text)
                        yield {
                            "event": "agent_message_delta",
                            "data": {"text": text},
                        }

            elif event_type == "content_block_stop":
                # Emit complete text block for history storage
                if current_text_parts:
                    full_text = "".join(current_text_parts)
                    yield {
                        "event": "agent_message",
                        "data": {"text": full_text},
                    }
                    current_text_parts = []

        # --- AssistantMessage: complete turn ---
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    # Skip if already emitted via StreamEvent
                    if block.id in emitted_tool_ids:
                        continue
                    yield {
                        "event": "tool_call",
                        "data": {
                            "tool_name": block.name,
                            "tool_input": block.input,
                        },
                    }
                elif isinstance(block, TextBlock):
                    # Only emit if we didn't stream this text
                    if not streamed_text_in_turn:
                        yield {
                            "event": "agent_message",
                            "data": {"text": block.text},
                        }
            # Reset per-turn tracking
            streamed_text_in_turn = False

        # --- ResultMessage: agent finished ---
        elif isinstance(message, ResultMessage):
            if message.is_error:
                yield {
                    "event": "error",
                    "data": {"message": str(message.result)},
                }
            break

except Exception as e:
    logger.error("process_message_stream error: %s", e)
    yield {
        "event": "error",
        "data": {"message": str(e)},
    }
```

**Note:** Check that `ToolUseBlock` has an `id` attribute. If the SDK's `ToolUseBlock` doesn't expose `id`, fall back to dedup by tool name: track emitted tool names in the current turn and skip duplicates.

---

## Fix 3: Clean Up Tool Call Chip Rendering (Frontend)

### Problem
Tool call chips accumulate across the entire conversation and show stale entries. The current rendering (line 1499-1506) shows the last 3 `tool_call` events from ALL events ever received, creating visual clutter.

### File: `frontend/src/components/CommandCenter.tsx`

### Fix 3a: Only show the CURRENT tool call (not accumulated history)

Replace lines 1499-1506:

```typescript
{/* Agent tool call chips — shown while processing */}
{conv.isProcessing && conv.events
  .filter((e) => e.type === 'tool_call')
  .slice(-3)
  .map((e) => (
    <ToolCallChip key={e.id} event={e} />
  ))
}
```

With:

```typescript
{/* Current tool call chip — only show the latest active tool */}
{conv.isProcessing && !preview && (() => {
  const lastToolCall = [...conv.events].reverse().find((e) => e.type === 'tool_call');
  return lastToolCall ? <ToolCallChip key={lastToolCall.id} event={lastToolCall} /> : null;
})()}
```

Key changes:
- Only show ONE chip (the latest tool call), not 3
- Hide tool chips entirely once `preview` is set (the PreviewCard takes over)
- This prevents stale chips from lingering after the preview renders

### Fix 3b: Improve tool name humanization

In the `ToolCallChip` component (line 1024-1043), the tool names come through as `mcp__orchestrator__batch_preview` because the SDK prefixes them with the MCP server namespace. Update the humanization:

```typescript
function ToolCallChip({ event }: { event: ConversationEvent }) {
  const toolName = (event.data.tool_name as string) || 'tool';
  // Strip MCP namespace prefix and humanize:
  // "mcp__orchestrator__batch_preview" → "Batch Preview"
  const label = toolName
    .replace(/^mcp__\w+__/, '')     // strip "mcp__orchestrator__" prefix
    .replace(/_tool$/, '')           // strip "_tool" suffix
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());

  return (
    <div className="flex gap-3 animate-fade-in">
      <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/10 to-cyan-600/10 border border-cyan-500/20 flex items-center justify-center">
        <GearIcon className="w-3.5 h-3.5 text-cyan-400/60" />
      </div>
      <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-800/50 border border-slate-700/50">
        <span className="w-2 h-2 rounded-full bg-cyan-400/50 animate-pulse" />
        <span className="text-[11px] font-mono text-slate-400">{label}</span>
      </div>
    </div>
  );
}
```

### Fix 3c: Hide typing indicator when preview is shown

Line 1509:
```typescript
{isProcessing && <TypingIndicator />}
```

Change to:
```typescript
{isProcessing && !preview && <TypingIndicator />}
```

This prevents the "..." spinner from showing alongside the PreviewCard.

---

## Fix 4: Suppress Redundant agent_message After Preview (Frontend)

### Problem
Even with Fix 1 (shorter tool return), the agent will still generate a brief text message after the preview. This message appears BELOW the PreviewCard in the chat, which is fine — but if the agent generates something verbose, it's distracting.

### File: `frontend/src/components/CommandCenter.tsx`

### Fix
In the event processing effect (line 1221-1245), when a `preview_ready` event is received, set a flag to suppress the NEXT `agent_message` (which will be the LLM's response to the preview tool result):

```typescript
// Render agent events as conversation messages
const lastProcessedEventRef = React.useRef(0);
const suppressNextMessageRef = React.useRef(false);
React.useEffect(() => {
  const newEvents = conv.events.slice(lastProcessedEventRef.current);
  lastProcessedEventRef.current = conv.events.length;

  for (const event of newEvents) {
    if (event.type === 'agent_message') {
      // Suppress the agent's text summary after preview_ready
      if (suppressNextMessageRef.current) {
        suppressNextMessageRef.current = false;
        continue;
      }
      const text = (event.data.text as string) || '';
      if (text) {
        addMessage({ role: 'system', content: text });
      }
    } else if (event.type === 'preview_ready') {
      const previewData = event.data as unknown as BatchPreview;
      setPreview(previewData);
      setCurrentJobId(previewData.job_id);
      refreshJobList();
      // Suppress the next agent_message (the LLM's summary of preview data)
      suppressNextMessageRef.current = true;
    } else if (event.type === 'error') {
      const msg = (event.data.message as string) || 'Agent error';
      addMessage({
        role: 'system',
        content: `Error: ${msg}`,
        metadata: { action: 'error' },
      });
    }
  }
}, [conv.events, addMessage]);
```

---

## Fix 5: Performance — Reduce UPS MCP Process Startup Overhead (Backend)

### Problem
`_run_batch_preview()` in `tools_v2.py` creates a NEW `UPSMCPClient` (which spawns a new MCP process via stdio) for every single preview call. Process startup adds 3-5 seconds of overhead before any rating even begins.

### File: `src/orchestrator/agent/tools_v2.py`

### Fix
Cache the `UPSMCPClient` instance at module level so it's reused across tool calls. The client is async and handles its own connection lifecycle.

Add a module-level cached client with lazy initialization:

```python
import os

# Cached UPS MCP client — reused across tool calls to avoid process startup overhead
_ups_client: "UPSMCPClient | None" = None
_ups_client_lock = asyncio.Lock()


async def _get_ups_client() -> "UPSMCPClient":
    """Get or create a cached UPSMCPClient instance.

    Reuses the same MCP process across tool calls to avoid
    repeated process startup overhead (~3-5s per spawn).

    Returns:
        Connected UPSMCPClient instance.
    """
    global _ups_client

    if _ups_client is not None:
        return _ups_client

    async with _ups_client_lock:
        # Double-check after acquiring lock
        if _ups_client is not None:
            return _ups_client

        from src.services.ups_mcp_client import UPSMCPClient

        base_url = os.environ.get("UPS_BASE_URL", "https://wwwcie.ups.com")
        environment = "test" if "wwwcie" in base_url else "production"

        client = UPSMCPClient(
            client_id=os.environ.get("UPS_CLIENT_ID", ""),
            client_secret=os.environ.get("UPS_CLIENT_SECRET", ""),
            environment=environment,
            account_number=os.environ.get("UPS_ACCOUNT_NUMBER", ""),
        )
        await client.connect()
        _ups_client = client
        return _ups_client
```

Then update `_run_batch_preview()` to use it:

```python
async def _run_batch_preview(job_id: str) -> dict[str, Any]:
    """Run batch preview via BatchEngine using cached UPS client."""
    from src.services.batch_engine import BatchEngine
    from src.services.ups_payload_builder import build_shipper_from_env

    account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "")
    shipper = build_shipper_from_env()
    ups = await _get_ups_client()

    with get_db_context() as db:
        engine = BatchEngine(
            ups_service=ups,
            db_session=db,
            account_number=account_number,
        )
        svc = JobService(db)
        rows = svc.get_rows(job_id)
        result = await engine.preview(
            job_id=job_id,
            rows=rows,
            shipper=shipper,
        )
    return result
```

Do the same for `batch_execute_tool` — use `_get_ups_client()` instead of creating a new `UPSMCPClient` context manager.

**Important:** Check that `UPSMCPClient` supports being kept alive long-term. If it has a `connect()` method (separate from `__aenter__`), use that. If it only works as an async context manager, you'll need to add a `connect()` method to `UPSMCPClient` that does the same setup as `__aenter__` but doesn't require `async with`.

**File to check:** `src/services/ups_mcp_client.py` — verify it has `connect()` / `disconnect()` methods or add them.
**File to check:** `src/services/mcp_client.py` — the base `MCPClient` that `UPSMCPClient` wraps.

---

## Verification Checklist

After implementing all fixes, verify:

### Unit Tests
```bash
.venv/bin/python -m pytest tests/orchestrator/agent/test_tools_v2.py -v
.venv/bin/python -m pytest tests/orchestrator/agent/test_client_enhanced.py -v
.venv/bin/python -m pytest tests/services/test_agent_session_manager.py -v
```

### Frontend Type Check
```bash
cd frontend && npx tsc --noEmit
```

### E2E Manual Test
1. Start backend: `./scripts/start-backend.sh`
2. Start frontend: `cd frontend && npm run dev`
3. Reconnect Shopify: `curl http://localhost:8000/api/v1/platforms/shopify/env-status`
4. Open `localhost:5173`
5. Type: "Ship all California orders using UPS Ground"

**Expected behavior:**
- Agent shows brief text messages as it works (1-2 sentences each)
- Tool call chips show one at a time, disappearing when done
- PreviewCard appears after rating completes (should be under 60 seconds)
- When PreviewCard renders: no typing indicator, no tool chips, no redundant text summary
- Agent's final message is ONE brief sentence like "Preview ready — please review and confirm"
- Input is disabled while preview is shown
- Click "Confirm & Execute" → ProgressDisplay → CompletionArtifact → Labels

---

## Files Modified Summary

| File | What to Change |
|------|---------------|
| `src/orchestrator/agent/tools_v2.py` | Fix 1: Return short summary from `batch_preview_tool` instead of full data. Fix 5: Cache `UPSMCPClient` at module level. |
| `src/orchestrator/agent/system_prompt.py` | Fix 1: Strengthen post-preview instructions in workflow step 9 and safety rules. |
| `src/orchestrator/agent/client.py` | Fix 2: Dedup tool_call events using tool ID set instead of boolean flag. |
| `frontend/src/components/CommandCenter.tsx` | Fix 3: Show only latest tool chip, hide when preview shown, strip MCP namespace from names, hide typing indicator with preview. Fix 4: Suppress agent_message after preview_ready. |
| `src/services/ups_mcp_client.py` | Fix 5: Ensure `connect()`/`disconnect()` methods exist for long-lived usage (check first). |
| `src/services/mcp_client.py` | Fix 5: Same — verify base client supports long-lived connections. |

**No new files needed.**
