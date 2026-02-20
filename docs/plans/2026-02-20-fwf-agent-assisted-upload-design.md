# FWF Agent-Assisted Upload Design

**Date:** 2026-02-20
**Status:** Approved
**Scope:** ~30 lines across 5 files

## Problem

Fixed-width (.fwf) files require explicit column specifications (name, start, width) that cannot be auto-detected. The current upload route rejects .fwf files with a 400 error telling users to "use the chat." This is a dead-end UX — the user selected a file, got an error, and must navigate to a different UI surface.

## Approach: Agent-Assisted Hybrid

Instead of rejecting the file, the backend saves it to disk and returns a `pending_agent_setup` status. The frontend detects this status and auto-injects a user message into the chat, which the agent handles using existing `sniff_file` + `import_fixed_width` MCP tools. No new UI components, no new tools, no new adapters.

This respects the agent-first architecture: the agent is the sole orchestrator of column setup. The sidebar simply routes the file to the agent's conversation loop.

## Changes

### 1. Backend: Upload Route (`src/api/routes/data_sources.py`)

Replace the .fwf `HTTPException` with:
- Save file to `uploads/` directory (same as other file types)
- Return `DataSourceImportResponse` with `status='pending_agent_setup'`, `file_path` set, zero rows/columns

### 2. Backend Schema (`src/api/schemas.py`)

Add `file_path: str | None = None` to `DataSourceImportResponse`. Status values become `'connected' | 'error' | 'pending_agent_setup'`.

### 3. Frontend Types (`frontend/src/types/api.ts`)

Add `file_path?: string` to `DataSourceImportResponse`. Update `status` union type.

### 4. Frontend State Bridge (`frontend/src/hooks/useAppState.tsx`)

Add `pendingChatMessage: string | null` + `setPendingChatMessage` to AppState. This bridges the sidebar (DataSourcePanel) to the chat (CommandCenter) without threading `sendMessage` through props.

### 5. Frontend Sidebar (`frontend/src/components/sidebar/DataSourcePanel.tsx`)

In `handleFileSelected`: detect `pending_agent_setup` status, call `setPendingChatMessage(...)` with a message like "I uploaded {filename} as a fixed-width file. Please help me define the column layout."

### 6. Frontend Chat (`frontend/src/components/CommandCenter.tsx`)

Add `useEffect` that watches `pendingChatMessage`. When set, auto-submits it via `conv.sendMessage()`, then clears the pending state. The message appears as a user message in the chat.

## Agent Workflow (No Changes Needed)

The agent already has the tools:
1. `sniff_file` — reads raw lines so the agent can inspect column alignment
2. `import_fixed_width` — imports with explicit `col_specs` (list of `{name, start, width}`)

The agent will see the user's message, call `sniff_file` on the uploaded path, inspect the alignment, ask the user to confirm/adjust columns, then call `import_fixed_width`.

## Non-Goals

- No visual column ruler UI (violates agent-first architecture)
- No auto-detection heuristics for column boundaries
- No changes to MCP tools or adapters
