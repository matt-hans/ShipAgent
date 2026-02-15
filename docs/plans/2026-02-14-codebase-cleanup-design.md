# Codebase Cleanup & MCP-First Unification Design

**Date:** 2026-02-14
**Scope:** Full cleanup — architecture unification, dead code removal, module decomposition
**Approach:** Top-down (architecture first, then modules, then cleanup)

## Problem Statement

The codebase has path divergence between its documented MCP-first architecture and runtime behavior. External platform integration runs through direct API/service code while the MCP gateway path is partially stubbed. Connection state is split across three independent in-memory stores. Data source access has three parallel layers. Large modules (1500+ lines) increase regression risk. Frontend has 16+ duplicated icon components and utility functions.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| External Sources MCP | Wire gateway as authoritative | Aligns with MCP-first architecture claim |
| Data source authority | MCP data source via DataSourceGateway | Single authoritative path, eliminates parallel stacks |
| Shopify auto-import | Move to agent tool | Explicit, observable, no hidden side effects |
| Execution order | Top-down | Avoids double-refactoring modules |
| MCP client sharing | Process-global singleton | Prevents split-brain state from multiple stdio processes |

---

## Phase 1A: Wire External Sources MCP Gateway

### Changes

1. **New: `src/services/external_sources_mcp_client.py`**
   - Process-global async MCP client (singleton, long-lived)
   - Built on `MCPClient` from `src/services/mcp_client.py`
   - Methods: `connect()`, `disconnect()`, `list_connections()`, `fetch_orders()`, `get_order()`, `update_tracking()`
   - Single stdio connection to External Sources MCP server, cached/reused across requests
   - Mirrors UPS cache pattern in `tools_v2.py:285`

2. **`src/mcp/external_sources/tools.py` — `connect_platform()`**
   - Replace "pending" stub with actual client instantiation
   - Import platform client class based on platform type
   - Call `await client.authenticate(credentials)`
   - Store authenticated client in `lifespan_context["clients"][platform]`
   - Set connection status to `"connected"`
   - Logic mirrors working code in `platforms.py:154-230`

3. **`src/api/routes/platforms.py`**
   - Replace `PlatformStateManager` with thin adapter calling shared `ExternalSourcesMCPClient`
   - Routes become pure HTTP-to-MCP translation
   - No direct platform client imports or lifecycle management

4. **Agent tools (`tools_v2.py`)**
   - Add platform-related tools that call shared `ExternalSourcesMCPClient`
   - Agent does NOT get direct `"external"` MCP server in its server list
   - All agent platform access goes through shared process-global client

5. **Delete stale config**
   - Remove `get_shopify_mcp_config()` from `config.py`
   - Remove 4 associated tests from `test_config.py`
   - Remove `"shopify"` key from `create_mcp_servers_config()`
   - Keep `get_external_sources_mcp_config()` (now used by shared client)

### State Model After

```
ExternalSourcesMCPClient (process-global singleton)
    └─ single stdio connection
        └─ External Sources MCP Server (single instance)
            └─ Platform Clients (Shopify, WooCommerce, SAP, Oracle)
```

No competing in-memory stores. One truth source.

---

## Phase 1B: DataSourceGateway (MCP Data Source Authoritative)

### Changes

1. **New: `src/services/data_source_gateway.py`**
   - Protocol/interface class `DataSourceGateway`
   - Methods:
     - `import_csv()`, `import_excel()`, `import_database()`, `import_from_records()`
     - `get_source_info()`, `get_source_signature()`
     - `get_rows_by_filter()`, `query_data()`
     - `write_back_batch()` (client-side batching over single MCP `write_back` tool, documented atomicity tradeoff)
     - `disconnect()`

2. **New: `src/services/data_source_mcp_client.py`**
   - Implementation of `DataSourceGateway` using process-global MCP client
   - Built on `MCPClient`, singleton/long-lived pattern
   - Row shape normalization: converts `{rows:[{row_number,data,checksum}]}` → flat row dicts centrally

3. **Extend MCP data source tool surface**
   - Add `get_source_info` tool (exposes current source metadata)
   - Add `import_records` tool (for importing fetched external platform data)
   - Evaluate batch `write_back` tool or document gateway-level batching

4. **`src/api/routes/data_sources.py`**
   - Replace `DataSourceService.get_instance()` with `DataSourceGateway`
   - Routes unchanged externally

5. **`src/orchestrator/agent/tools_v2.py`**
   - Replace direct `DataSourceService.get_instance()` in `get_schema_tool()`, `fetch_rows_tool()`, `ship_command_pipeline()` with `DataSourceGateway`

6. **Remove `mcp__data__*` from agent runtime**
   - Remove data MCP server from agent's MCP server list in `client.py:196`
   - Remove `mcp__data__*` from allowed tools in `client.py:212`
   - Agent accesses data exclusively through SDK tools backed by gateway

7. **`src/api/routes/conversations.py`**
   - Replace `DataSourceService.get_instance()` source checks with `DataSourceGateway.get_source_info()`
   - Remove `_try_auto_import_shopify()` (moved to agent tool in Phase 2)
   - Remove all direct `DataSourceService` and `ShopifyClient` imports

8. **`DataSourceService` retained only inside MCP data source server**
   - Becomes the server's internal implementation detail
   - No external callers

---

## Phase 2: Auto-Import Migration + Dead Code Removal

### Changes

1. **New agent tool: `connect_shopify`**
   - In `tools_v2.py` (or future `tools/platform.py` after Phase 3 split)
   - Calls `ExternalSourcesMCPClient.connect()` + `ExternalSourcesMCPClient.fetch_orders()`
   - Imports via `DataSourceGateway.import_from_records()`
   - Observable as tool call in chat UI (ToolCallChip)

2. **Update agent system prompt** (`system_prompt.py`)
   - Add instruction: when no data source is active and Shopify env vars detected, call `connect_shopify` tool before processing shipping commands

3. **Delete from `conversations.py`**
   - `_try_auto_import_shopify()` function
   - All `ShopifyClient` imports
   - Auto-import flag logic

4. **Delete stale config**
   - `get_shopify_mcp_config()` (if not already deleted in Phase 1A)
   - Associated tests

5. **Delete `PlatformStateManager`** from `platforms.py`
   - Replaced by `ExternalSourcesMCPClient` in Phase 1A

6. **Delete `frontend/src/assets/react.svg`**
   - Orphaned, no references in codebase

7. **Standardize frontend platform hook usage**
   - Wire `panels.tsx` to use `useExternalSources.connect()/disconnect()/test()` exclusively
   - Remove direct `connectPlatform`/`disconnectPlatform` API imports from `panels.tsx`
   - Single frontend path for all platform actions

---

## Phase 3: Module Decomposition + Frontend Consolidation

### 3A: Frontend Icon + Utility Consolidation

1. **New: `frontend/src/components/ui/icons.tsx`**
   - Generic UI icons: SearchIcon, TrashIcon, PrinterIcon, DownloadIcon, CheckIcon, XIcon, ChevronDownIcon, EditIcon, MapPinIcon, etc.
   - Delete local copies from presentation.tsx, panels.tsx, JobDetailPanel.tsx, LabelPreview.tsx, RecentSourcesModal.tsx

2. **New: `frontend/src/components/ui/brand-icons.tsx`**
   - Platform brand glyphs: Shopify, WooCommerce, SAP, Oracle
   - Separate from generic icons to avoid overloading primitives file

3. **Extract `formatTimeAgo` → `frontend/src/lib/utils.ts`**
   - Single definition, imported by panels.tsx and RecentSourcesModal.tsx
   - Delete local copies

4. **Delete `frontend/src/assets/react.svg`** (if not already done in Phase 2)

### 3B: Frontend Module Splits

5. **Split `presentation.tsx` (1412 lines)**
   - `command-center/PreviewCard.tsx` — shipment preview with expandable rows
   - `command-center/ProgressDisplay.tsx` — live batch execution progress
   - `command-center/CompletionArtifact.tsx` — completed batch card
   - `command-center/ToolCallChip.tsx` — agent tool call chips
   - `command-center/messages.tsx` — ActiveSourceBanner, WelcomeMessage, message helpers
   - `command-center/presentation.tsx` — **temporary** re-export barrel (document removal target)

6. **Split `panels.tsx` (965 lines)**
   - `sidebar/DataSourcePanel.tsx` — data source switching, upload, DB connection
   - `sidebar/JobHistoryPanel.tsx` — job list, search, filters, delete
   - `sidebar/panels.tsx` — **temporary** re-export barrel (document removal target)

### 3C: Backend Module Split

7. **First: `orchestrator/agent/tools/core.py`**
   - Shared internals: `EventEmitterBridge`, `_bind_bridge`, `_ok/_err`, UPS client cache
   - Must be extracted first to prevent circular imports

8. **Split tool handlers**
   - `orchestrator/agent/tools/pipeline.py` — `ship_command_pipeline`, `preview_batch`, `execute_batch`
   - `orchestrator/agent/tools/data.py` — `get_schema_tool`, `fetch_rows_tool`, data source tools
   - `orchestrator/agent/tools/interactive.py` — interactive shipping tools
   - Each module exports tool handlers only

9. **`orchestrator/agent/tools/__init__.py`**
   - Owns `get_all_tool_definitions()` as single canonical registration entrypoint
   - `tools_v2.py` becomes temporary re-export barrel with removal target

### 3D: Regression Gates

10. **Before and after each split, run:**
    - Conversation flow tests
    - Preview/confirm/execute tests
    - Sidebar source switching/history tests
    - Interactive shipping tests
    - Full `pytest -k "not stream and not sse"` suite

---

## Files Created

| File | Purpose |
|------|---------|
| `src/services/external_sources_mcp_client.py` | Process-global External Sources MCP client |
| `src/services/data_source_gateway.py` | DataSourceGateway protocol/interface |
| `src/services/data_source_mcp_client.py` | Gateway implementation via MCP client |
| `frontend/src/components/ui/icons.tsx` | Shared generic UI icon library |
| `frontend/src/components/ui/brand-icons.tsx` | Platform brand icon library |
| `frontend/src/components/command-center/PreviewCard.tsx` | Preview card component |
| `frontend/src/components/command-center/ProgressDisplay.tsx` | Progress display component |
| `frontend/src/components/command-center/CompletionArtifact.tsx` | Completion artifact component |
| `frontend/src/components/command-center/ToolCallChip.tsx` | Tool call chip component |
| `frontend/src/components/command-center/messages.tsx` | Message rendering helpers |
| `frontend/src/components/sidebar/DataSourcePanel.tsx` | Data source panel component |
| `frontend/src/components/sidebar/JobHistoryPanel.tsx` | Job history panel component |
| `src/orchestrator/agent/tools/core.py` | Shared tool internals |
| `src/orchestrator/agent/tools/pipeline.py` | Pipeline tool handlers |
| `src/orchestrator/agent/tools/data.py` | Data tool handlers |
| `src/orchestrator/agent/tools/interactive.py` | Interactive tool handlers |
| `src/orchestrator/agent/tools/__init__.py` | Tool registration entrypoint |

## Files Deleted

| File | Reason |
|------|--------|
| `frontend/src/assets/react.svg` | Orphaned, no references |

## Files Significantly Modified

| File | Change |
|------|--------|
| `src/mcp/external_sources/tools.py` | Complete `connect_platform` client instantiation |
| `src/api/routes/platforms.py` | Replace PlatformStateManager with MCP client adapter |
| `src/api/routes/data_sources.py` | Replace DataSourceService with DataSourceGateway |
| `src/api/routes/conversations.py` | Remove auto-import, use gateway for source checks |
| `src/orchestrator/agent/client.py` | Remove mcp__data__* from agent, keep external excluded |
| `src/orchestrator/agent/config.py` | Remove shopify MCP config |
| `src/orchestrator/agent/tools_v2.py` | Add connect_shopify, use gateway, then split |
| `src/orchestrator/agent/system_prompt.py` | Add Shopify auto-connect instruction |
| `src/mcp/data_source/server.py` | Add get_source_info + import_records tools |
| `frontend/src/components/sidebar/panels.tsx` | Use useExternalSources hook, then split |
| `frontend/src/components/command-center/presentation.tsx` | Extract icons, then split |
| `frontend/src/hooks/useExternalSources.ts` | Become authoritative frontend platform hook |
| `frontend/src/lib/utils.ts` | Add formatTimeAgo |

## Risk Mitigation

- **Process-global singleton MCP clients** prevent split-brain state
- **DataSourceGateway interface** allows fallback to direct DataSourceService during parity testing
- **Temporary barrel re-exports** prevent import breakage during module splits
- **Regression gates** before/after each phase ensure no behavior change
- **Top-down order** means architecture is stable before modules are split
