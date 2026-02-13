# Interactive Shipping Mode Toggle — Design Document

**Date**: 2026-02-13
**Branch**: `claude/zen-bohr`
**Status**: Approved for implementation
**Depends on**: UPS MCP Elicitation v1 (PR in progress on this branch)

## Overview

Add a frontend toggle that enables/disables interactive single-shipment creation
via UPS MCP elicitation. When OFF (default), all shipment operations route through
the batch pipeline. When ON, the agent can also call `create_shipment` directly for
ad-hoc single shipments, handling missing field prompts conversationally.

The batch processing pipeline remains unchanged regardless of toggle state.

## Design Decisions

### Coexistence Model

Both modes coexist — a connected data source stays available for batch commands
while interactive mode enables ad-hoc single-shipment creation alongside it.

**Routing policy (deterministic, not prompt-only):**

| Condition | Route |
|-----------|-------|
| `interactive_shipping=False` | Batch path only. Hook denies `create_shipment`. |
| `interactive_shipping=True` + explicit batch/data-source intent | Batch path. |
| `interactive_shipping=True` + explicit single ad-hoc shipment details | Direct MCP path. |
| `interactive_shipping=True` + multiple shipments implied | Batch path only. |
| `interactive_shipping=True` + ambiguous intent + data source connected | Agent asks one clarifying question. |
| `interactive_shipping=True` + direct create with data source connected | Short confirmation step first. |

### Session-Level Flag (Approach A)

The `interactive_shipping` flag is set at session creation. The system prompt is
built deterministically based on this flag. Toggling mid-conversation resets the
session (same UX as switching data sources).

### Hard Enforcement

When `interactive_shipping=False`, the pre-tool hook **deterministically denies**
`create_shipment` calls. This is not prompt-based gating — the hook blocks the tool
call before it reaches UPS MCP, regardless of what the agent attempts.

### Fork Pinning Strategy

The canonical dependency is a Git URL + immutable commit SHA in `pyproject.toml`:
```
ups-mcp @ git+https://github.com/<authoritative-org>/ups-mcp.git@<sha>
```
The SHA must point to a commit that includes the elicitation/preflight implementation
(`server.py` orchestration + `shipment_validator.py`).

Local dev may override with an editable install from a local path, but that is
documented in dev setup only — never committed to `pyproject.toml`.

Lockfile sync: after updating `pyproject.toml`, run `uv lock && uv sync`.

## Architecture

### Data Flow

```
Header Toggle (React)
    → useAppState.interactiveShipping (localStorage persisted)
    → useConversation.reset() if session exists (race-safe)
    → createConversation({ interactive_shipping: bool })
    → POST /conversations/ (optional body, defaults False)
    → AgentSession.interactive_shipping stored
    → _ensure_agent() includes flag in rebuild hash
    → build_system_prompt(source_info, interactive_shipping)
    → OrchestrationAgent(system_prompt, interactive_shipping)
    → Hook factory captures interactive_shipping per instance
```

### Frontend Changes

**Header (`Header.tsx`)**:
- Right side: `Switch` component (shadcn/ui) with label "Interactive Shipping"
- Accent-colored when ON, muted when OFF
- Disabled during reset-in-flight (`isResettingSession`)

**Chat area context**:
- `interactive_shipping=False` + source connected: current behavior (ActiveSourceBanner)
- `interactive_shipping=True` + source connected: ActiveSourceBanner + badge:
  "Interactive shipping enabled. Describe one shipment or use batch commands."
- `interactive_shipping=True` + no source: placeholder changes to
  "Describe your shipment details for interactive creation"

**Toggle UX guards**:
- If active preview or processing in flight → confirm dialog:
  "Switching mode resets your current session. Continue?"
- Toggle disabled while `reset()` is in flight
- Session generation counter (ref) in `useConversation` — late SSE events from
  old sessions are silently discarded based on generation mismatch

### Backend Changes

**`schemas_conversations.py`**:
- New `CreateConversationRequest(BaseModel)`: `interactive_shipping: bool = False`
- `CreateConversationResponse`: add `interactive_shipping: bool` echo field
- Backward-compatible: existing no-body clients default to `False`

**`agent_session_manager.py`**:
- `AgentSession.__init__()`: `interactive_shipping: bool = False`

**`conversations.py`**:
- `create_conversation()` accepts optional `CreateConversationRequest`
- Stores `interactive_shipping` on session
- `_ensure_agent()` hash: `f"{source_hash}|interactive={session.interactive_shipping}"`
- Passes flag to `build_system_prompt()` and `OrchestrationAgent()`
- Logs `interactive_shipping=%s` in all `agent_timing` markers
- Response echoes effective `interactive_shipping` value

**`system_prompt.py`**:
- `build_system_prompt(source_info, interactive_shipping=False)`
- When `False`: omit "Direct Single-Shipment Commands" and
  "Handling Create Shipment Validation Errors" sections entirely
- When `True`: include both + coexistence routing policy with precedence text:
  direct single-shipment path takes precedence for one-off ad-hoc requests

**`hooks.py`**:
- Hook factory inside `OrchestrationAgent.__init__()` — closure captures
  `self.interactive_shipping`
- When `False` + tool is `create_shipment` → deny:
  "Interactive shipping is disabled. Use batch processing for shipment creation."
- When `True` → existing relaxed structural guard (dict-type check only)

**`ups_mcp_client.py`**:
- Preserve `reason` field from `MALFORMED_REQUEST` in `UPSServiceError.details`
- Include concise diagnostic reason text in error message

**`api.ts` (frontend)**:
- `createConversation()` accepts optional `{ interactive_shipping: boolean }`
- Types updated for response echo field

**`useConversation.ts`**:
- `ensureSession()` accepts `interactive_shipping` parameter
- `sessionGeneration` ref counter, incremented on `reset()`
- Events with stale generation silently discarded

**`useAppState.tsx`**:
- `interactiveShipping: boolean` state, persisted to
  `localStorage` key `shipagent_interactive_shipping`, default `false`

### UPS MCP Repin Procedure

1. Identify authoritative fork URL and latest SHA with elicitation code
2. Update `pyproject.toml` with `ups-mcp @ git+<url>@<sha>`
3. Run `uv lock` to refresh `uv.lock`
4. Run `uv sync` to install into venv
5. Verify `shipment_validator` module exists in installed package
6. Run existing test suite — confirm no regressions
7. Run integration matrix (see below)

## Test Plan

### Unit Tests

| # | File | Assertion |
|---|------|-----------|
| 1 | `test_system_prompt.py` | Prompt contains interactive sections when `True` |
| 2 | `test_system_prompt.py` | Prompt omits interactive sections when `False` |
| 3 | `test_system_prompt.py` | Coexistence routing policy text present when `True` + source |
| 4 | `test_system_prompt.py` | Precedence text: direct path > batch for ad-hoc when `True` |
| 5 | `test_hooks.py` | `create_shipment` denied when `interactive_shipping=False` |
| 6 | `test_hooks.py` | `create_shipment` allowed when `interactive_shipping=True` |
| 7 | `test_conversations.py` | Session stores `interactive_shipping`, defaults `False` |
| 8 | `test_conversations.py` | `_ensure_agent` rebuilds when only flag changes |
| 9 | `test_conversations.py` | Response echoes `interactive_shipping` value |
| 10 | `test_ups_mcp_client.py` | `MALFORMED_REQUEST` preserves `reason` in details/message |

### Behavior-Level Test

| # | File | Assertion |
|---|------|-----------|
| 11 | `test_interactive_mode.py` | With `interactive_shipping=True`: mocked `create_shipment` ToolError with `missing[]` → hook allows (no deny) → `_translate_error()` produces E-2010 with field prompts from `prompt` values → no unhandled exception. Asserts observed runtime behavior, not prompt text. |

### Frontend Tests (Component-Level)

| # | Assertion |
|---|-----------|
| 12 | Toggle persists to localStorage, restores on reload |
| 13 | Toggle ON/OFF triggers `reset()` when session exists |
| 14 | Confirm dialog shown when toggling with active preview |
| 15 | Toggle disabled during reset-in-flight |
| 16 | Placeholder/banner text changes by mode × source-connected state |
| 17 | Late SSE events ignored after session generation increments |

### Integration Matrix (Manual, Post-Repin)

| # | Scenario | Expected |
|---|----------|----------|
| 1 | Toggle OFF + single-shipment request | Hook denies, agent explains batch-only |
| 2 | Toggle ON + single-shipment with missing fields | Preflight returns `missing[]`, agent asks for fields |
| 3 | Toggle ON + data-source batch command | Routes to `ship_command_pipeline` |
| 4 | Ambiguous prompt + data source + toggle ON | Agent asks clarifying question |

## Out of Scope

- MCP-level elicitation form UI (Claude SDK `AskUserQuestion`) — future v2
- Batch path elicitation (rows always fail with E-2010 on missing fields)
- Multi-carrier interactive mode (UPS only for MVP)
- International shipping with customs forms
