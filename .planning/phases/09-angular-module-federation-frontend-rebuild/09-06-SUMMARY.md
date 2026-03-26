---
phase: 09
plan: 06
subsystem: sidebar-remote
tags: [angular, module-federation, sidebar, data-source, job-history, chat-sessions]
dependency_graph:
  requires: ["09-04"]
  provides: ["sidebar-remote federation component"]
  affects: ["shell-app sidebar slot"]
tech_stack:
  added: []
  patterns:
    - "NgRx SignalStore effect() pattern for version-based re-fetch"
    - "Angular 21 @if/@for control flow in all templates"
    - "OnPush + standalone components throughout"
    - "firstValueFrom() for one-shot Observable to Promise"
    - "output() + input() signals for component communication"
key_files:
  created:
    - shipagent-frontend/apps/sidebar-remote/src/app/remote-entry.ts
    - shipagent-frontend/apps/sidebar-remote/src/app/sidebar-content/sidebar-content.component.ts
    - shipagent-frontend/apps/sidebar-remote/src/app/data-source-panel/data-source-panel.component.ts
    - shipagent-frontend/apps/sidebar-remote/src/app/data-source-panel/local-source.component.ts
    - shipagent-frontend/apps/sidebar-remote/src/app/data-source-panel/platform-source.component.ts
    - shipagent-frontend/apps/sidebar-remote/src/app/data-source-panel/data-source-mappers.service.ts
    - shipagent-frontend/apps/sidebar-remote/src/app/recent-sources-modal/recent-sources-modal.component.ts
    - shipagent-frontend/apps/sidebar-remote/src/app/job-history-panel/job-history-panel.component.ts
    - shipagent-frontend/apps/sidebar-remote/src/app/chat-sessions-panel/chat-sessions-panel.component.ts
    - shipagent-frontend/apps/sidebar-remote/src/app/chat-history-flyout/chat-history-flyout.component.ts
  modified:
    - shipagent-frontend/apps/sidebar-remote/src/app/remote-entry.ts
decisions:
  - "Split DataSourcePanel into 3 components (panel + local + platform) for separation of concerns"
  - "effect() watching store version signals for reactive re-fetches across panels"
  - "Platform icon selectors are sa-brand-* not sa-icon-* — corrected during dev"
  - "TimeAgoPipe name is 'timeAgo' not 'saTimeAgo' — corrected in recent-sources-modal"
  - "ChatHistoryFlyoutComponent uses OnChanges input() signals pattern for lifecycle-driven load"
metrics:
  duration: "~420s"
  completed: "2026-03-25"
  tasks: 2
  files: 10
---

# Phase 9 Plan 06: Sidebar Remote Summary

Complete sidebar remote with full feature parity to React sidebar components — data source management (local file upload + platform connections), job history browsing with auto-refresh, and chat session management grouped by date.

## What Was Built

### Task 1: Sidebar Content Container and Data Source Panel

**SidebarContentComponent** (`sidebar-content/sidebar-content.component.ts`)
Root container exposing three tabbed panels (Data / Jobs / Chats) via Native Federation as `./SidebarContent`. Uses `signal<ActiveTab>` for tab state; renders panels with `@if` control flow. Imports `JobHistoryPanelComponent` and `ChatSessionsPanelComponent`.

**DataSourcePanelComponent** (`data-source-panel/data-source-panel.component.ts`)
Main panel container showing connected source status (local file with row/column counts), cached reconnect card, and write-back toggle. Hydrates backend source status on `ngOnInit()`. Disconnect and reconnect handlers update `DataSourceStore`.

**LocalSourceComponent** (`data-source-panel/local-source.component.ts`)
File upload dropzone (CSV/Excel/JSON/XML/EDI/fixed-width) and database connection form. Uses `viewChild` for hidden file input, dispatches to `apiService.uploadDataSource()`. Fixed-width files route to chat via `conversationStore.setPendingMessage()`. DB connections via `apiService.importDataSource()`.

**PlatformSourceComponent** (`data-source-panel/platform-source.component.ts`)
Shopify and Amazon platform cards. Reads availability from `PlatformsStore.connections()`. Switch handlers call `apiService.connectPlatform()` and update `DataSourceStore`.

**DataSourceMappersService** (`data-source-panel/data-source-mappers.service.ts`)
Injectable service porting `dataSourceMappers.ts` — `mapSchemaColumns()` converts `SourceColumn[]` to `ColumnMetadata[]`, `extractFileName()` extracts display name from paths.

**RecentSourcesModalComponent** (`recent-sources-modal/recent-sources-modal.component.ts`)
Full-screen modal with search, type filter (all/csv/excel/json/xml/fixed_width/edi/database), per-source reconnect and delete, bulk delete, DB connection string input. Uses `effect()` to reload when `open` input becomes true.

### Task 2: Job History Panel, Chat Sessions Panel, Chat History Flyout

**JobHistoryPanelComponent** (`job-history-panel/job-history-panel.component.ts`)
Displays last 20 jobs sorted newest first. Uses `effect()` watching `jobStore.jobListVersion()` to trigger re-fetches whenever the job list changes. Shows `StatusBadgeComponent` with derived 'partial' status (completed + some failed rows). Search by command text and filter by status. Reprint labels (opens merged PDF URL) and delete per job. Clicking a job calls `jobStore.setActiveJob()`.

**ChatSessionsPanelComponent** (`chat-sessions-panel/chat-sessions-panel.component.ts`)
Lists sessions grouped by Today / Yesterday / Previous 7 Days / Older (matching React groupByDate logic exactly). Uses `effect()` watching `conversationStore.chatSessionsVersion()` for refresh after SSE `done` events. Load session (fetches messages, updates conversation store), new chat (calls `conversationStore.reset()`), export (browser download), delete (removes from list and resets store if active), bulk clear with two-click confirmation, inline rename on double-click.

**ChatHistoryFlyoutComponent** (`chat-history-flyout/chat-history-flyout.component.ts`)
Overlay flyout showing full read-only message history for a selected session. `open` and `sessionId` inputs drive `ngOnChanges`-triggered message loading. Export button triggers browser download of conversation JSON.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed incorrect brand icon selectors in PlatformSourceComponent**
- **Found during:** Task 1 build
- **Issue:** Template used `sa-icon-shopify` and `sa-icon-amazon` but brand icons use `sa-brand-*` selectors
- **Fix:** Changed all four occurrences to `sa-brand-shopify` and `sa-brand-amazon`
- **Files modified:** `platform-source.component.ts`
- **Commit:** bf4ee06

**2. [Rule 1 - Bug] Fixed incorrect TimeAgoPipe name in RecentSourcesModalComponent**
- **Found during:** Task 1 review
- **Issue:** Template used `| saTimeAgo` but pipe name is `timeAgo`
- **Fix:** Changed `| saTimeAgo` to `| timeAgo`
- **Files modified:** `recent-sources-modal.component.ts`
- **Commit:** bf4ee06

**3. [Rule 1 - Bug] Removed unused DatabaseIconComponent import in LocalSourceComponent**
- **Found during:** Task 1 build warning
- **Issue:** `DatabaseIconComponent` was imported but not used in template
- **Fix:** Removed from import statement and component imports array
- **Files modified:** `local-source.component.ts`
- **Commit:** bf4ee06

**4. [Rule 1 - Bug] Removed unused type imports causing TS6196 errors**
- **Found during:** Task 1/2 build
- **Issue:** `JobStatus`, `OnInit`, `SessionContext` were imported but never used
- **Fix:** Removed each unused import
- **Files modified:** `job-history-panel.component.ts`, `recent-sources-modal.component.ts`, `chat-sessions-panel.component.ts`
- **Commit:** bf4ee06

### Notes on Partial Pre-existing Work

The `job-history-panel`, `chat-sessions-panel`, and `chat-history-flyout` components were found to exist on disk from a previous Plan 08 executor session. This executor's files matched the implementation requirements exactly, so no re-implementation was needed. The Task 1 commit (bf4ee06) captured all Task 1 work; Task 2 files were already committed in a prior session.

## Verification

- `nx build sidebar-remote` passes cleanly (only pre-existing budget warning from nx-welcome.ts)
- `SidebarContentComponent` exposed via Native Federation as `./SidebarContent`
- DataSource panel handles file upload (CSV/Excel/JSON/XML/EDI/fixed-width), database connections, Shopify/Amazon platform switching, write-back toggle, reconnect
- JobHistoryPanel uses `effect()` watching `jobStore.jobListVersion()` — confirmed in component constructor
- ChatSessionsPanel groups by Today/Yesterday/Previous 7 Days/Older — confirmed matching React logic
- ChatHistoryFlyout shows read-only history with export
- All cross-remote communication via shared stores (no direct imports between remotes)

## Self-Check: PASSED

- `shipagent-frontend/apps/sidebar-remote/src/app/sidebar-content/sidebar-content.component.ts` — EXISTS
- `shipagent-frontend/apps/sidebar-remote/src/app/data-source-panel/data-source-panel.component.ts` — EXISTS
- `shipagent-frontend/apps/sidebar-remote/src/app/job-history-panel/job-history-panel.component.ts` — EXISTS
- `shipagent-frontend/apps/sidebar-remote/src/app/chat-sessions-panel/chat-sessions-panel.component.ts` — EXISTS
- `shipagent-frontend/apps/sidebar-remote/src/app/chat-history-flyout/chat-history-flyout.component.ts` — EXISTS
- Build commit bf4ee06 — EXISTS in git log
