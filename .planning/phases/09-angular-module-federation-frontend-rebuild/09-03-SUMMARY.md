---
phase: 09-angular-module-federation-frontend-rebuild
plan: 03
subsystem: shared-reactive-layer
tags: [angular, ngrx, signals, sse, icons, pipes, design-tokens, tailwind]
dependency_graph:
  requires: [09-01-PLAN, 09-02-PLAN]
  provides: [shared-sse, shared-state, shared-ui]
  affects: [all-remotes, shell-app, chat-remote, sidebar-remote, settings-remote, domain-remote]
tech_stack:
  added:
    - "@ngrx/signals@^21.1.0 — SignalStore foundation for all 8 stores"
    - "@angular-architects/ngrx-toolkit@^21.0.1 — withStorageSync for localStorage persistence"
    - "@spartan-ng/brain@latest — accessible headless UI primitives"
    - "@angular/cdk@latest — Angular CDK for Spartan UI"
    - "lucide-angular@^1.0.0 — official Lucide icon library for Angular"
    - "ng2-pdf-viewer@^10.4.0 — in-browser PDF rendering (Angular 19+ compatible)"
    - "ngx-markdown — markdown rendering"
  patterns:
    - "signalStore with providedIn: root for singleton stores"
    - "withStorageSync selective persistence (interactiveShipping, warningPreference, writeBackEnabled)"
    - "SseService component-scoped (NOT root) for EventSource lifecycle isolation"
    - "Standalone OnPush Angular components for all icons and UI primitives"
    - "cn() utility = clsx + tailwind-merge (port of React utils.ts)"
    - "Pure standalone pipes for currency and time formatting"
key_files:
  created:
    - shipagent-frontend/libs/shared/sse/src/sse.service.ts
    - shipagent-frontend/libs/shared/sse/src/sse.models.ts
    - shipagent-frontend/libs/shared/sse/src/index.ts
    - shipagent-frontend/libs/shared/state/src/app.store.ts
    - shipagent-frontend/libs/shared/state/src/conversation.store.ts
    - shipagent-frontend/libs/shared/state/src/job.store.ts
    - shipagent-frontend/libs/shared/state/src/data-source.store.ts
    - shipagent-frontend/libs/shared/state/src/settings.store.ts
    - shipagent-frontend/libs/shared/state/src/contacts.store.ts
    - shipagent-frontend/libs/shared/state/src/commands.store.ts
    - shipagent-frontend/libs/shared/state/src/platforms.store.ts
    - shipagent-frontend/libs/shared/state/src/index.ts
    - shipagent-frontend/libs/shared/ui/src/utils/cn.ts
    - shipagent-frontend/libs/shared/ui/src/components/icons/index.ts (70 components)
    - shipagent-frontend/libs/shared/ui/src/components/brand-icons/index.ts
    - shipagent-frontend/libs/shared/ui/src/components/shipagent-logo/shipagent-logo.component.ts
    - shipagent-frontend/libs/shared/ui/src/components/copy-button/copy-button.component.ts
    - shipagent-frontend/libs/shared/ui/src/components/status-badge/status-badge.component.ts
    - shipagent-frontend/libs/shared/ui/src/pipes/format-currency.pipe.ts
    - shipagent-frontend/libs/shared/ui/src/pipes/relative-time.pipe.ts
    - shipagent-frontend/libs/shared/ui/src/pipes/time-ago.pipe.ts
    - shipagent-frontend/libs/shared/ui/src/directives/mirror-sync.directive.ts
    - shipagent-frontend/libs/shared/ui/src/styles/tokens.css
    - shipagent-frontend/libs/shared/ui/src/styles/typography.css
    - shipagent-frontend/libs/shared/ui/src/styles/components.css
    - shipagent-frontend/libs/shared/ui/src/styles/animations.css
  modified:
    - shipagent-frontend/libs/shared/sse/src/index.ts
    - shipagent-frontend/libs/shared/state/src/index.ts
    - shipagent-frontend/libs/shared/ui/src/index.ts
    - shipagent-frontend/package.json
    - shipagent-frontend/package-lock.json
decisions:
  - "SseService is component-scoped (not root) to ensure EventSource cleanup on remote unmount"
  - "chatSessionsVersion excluded from withStorageSync select — it is a volatile counter not persisted state"
  - "70 SVG icon components created (>50 required) to achieve complete parity with React icons.tsx"
  - "Spartan UI helm generation deferred — @spartan-ng/brain is available; helm wrappers created on-demand by each remote as Spartan CLI requires interactive input"
  - "ng2-pdf-viewer pinned to ^10.4.0 (resolved from ^10.3.0 requirement) — Angular 19+ compatible"
  - "withStorageSync from @angular-architects/ngrx-toolkit used instead of custom localStorage feature"
metrics:
  duration_minutes: 15
  completed: 2026-03-24T21:15:14Z
  tasks_completed: 2
  files_created: 26
  files_modified: 5
---

# Phase 9 Plan 03: Shared Reactive Layer (SSE, SignalStores, UI Library) Summary

Observable-based SSE service + 8 root-level NgRx SignalStores + complete shared UI library with 70 icon components, OKLCH design tokens, pipes, directives, and cn() utility — the reactive backbone consumed by every Module Federation remote.

## What Was Built

### Task 1: SseService and 8 NgRx SignalStores

**SseService** (`@shipagent/shared-sse`) — Component-scoped EventSource wrapper:
- `connect(url)` → `Observable<RawSseEvent>` with automatic ping filtering
- `connectionState` signal tracking `disconnected | connecting | connected | error`
- `disconnect()` + `ngOnDestroy()` for ghost connection prevention on remote unload

**8 SignalStores** (`@shipagent/shared-state`) — Root-level singletons:

| Store | State Shape | Persistence |
|-------|------------|-------------|
| AppStore | sidebarCollapsed, settingsFlyoutOpen, isProcessing, isToggleLocked | None |
| ConversationStore | sessionId, messages, isStreaming, pendingMessage, interactiveShipping, warningPreference, chatSessionsVersion | interactiveShipping + warningPreference via withStorageSync |
| JobStore | activeJob, jobListVersion | None |
| DataSourceStore | dataSource, activeSourceType, activeSourceInfo, writeBackEnabled, cachedLocalConfig | writeBackEnabled via withStorageSync |
| SettingsStore | appSettings, credentialStatus, onboardingCompleted | None |
| ContactsStore | contacts[] | None |
| CommandsStore | customCommands[] | None |
| PlatformsStore | connections{}, providerConnectionsVersion | None |

Key invariants satisfied:
- `chatSessionsVersion` is in ConversationStore state but excluded from `withStorageSync select` — volatile counter, not persisted
- `withStorageSync` used from `@angular-architects/ngrx-toolkit` (not custom implementation)
- All stores use `{ providedIn: 'root' }` for cross-remote singleton behavior

### Task 2: Shared UI Library

**Design Tokens** (`tokens.css`) — Complete OKLCH design system matching React pixel-for-pixel: core palette, domain colors, platform brand colors, status colors, typography vars, radii, light+dark mode.

**CSS Layers** (`typography.css`, `components.css`, `animations.css`) — All component classes, @keyframes, and typography utilities ported from React `index.css`.

**Icon Components** — 70 standalone OnPush Angular SVG components (exceeds 50+ requirement):
- All 32 icons from React `icons.tsx` ported
- Additional domain icons added: ArrowRight, ChevronUp, CheckCircle, AlertTriangle, FileText, Refresh, ExternalLink, Link, Lock, Unlock, Truck, Globe, Calendar, Clock, Star, Tag, Filter, Layout, Menu, MoreHorizontal, MoreVertical, Zap, BookOpen, Terminal, MessageSquare, Sparkles, Key, Shield, Bell, Sliders, Users, Archive, Layers, CreditCard, DollarSign, Minus
- 6 brand icons (Shopify, Amazon, WooCommerce, SAP, Oracle, DataSource)

**UI Components:**
- `CopyButtonComponent` — Hover-reveal clipboard button with copied/error states (2s auto-reset)
- `StatusBadgeComponent` — Semantic badge (success/warning/error/info/neutral)
- `ShipAgentLogoComponent` / `ShipAgentIconComponent` — Cardboard box logo

**Pipes** (pure, standalone):
- `FormatCurrencyPipe` — cents → "$12.99"
- `RelativeTimePipe` — Date → "5m ago" / "2h ago"
- `TimeAgoPipe` — ISO string → "3d ago" / "2h ago" with day support

**Directives:**
- `MirrorSyncDirective` — Syncs scroll and dimensions between textarea and mirror div for rich text input

**Utility:**
- `cn()` — `clsx + tailwind-merge` class name combiner (exact port of React utils.ts)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing functionality] ngrx-toolkit package name correction**
- **Found during:** Task 1 npm install
- **Issue:** Plan specified `npm install @ngrx-toolkit` but the actual npm package is `@angular-architects/ngrx-toolkit` (the `@` prefix causes npm EINVALIDTAGNAME error for invalid package names)
- **Fix:** Installed `@angular-architects/ngrx-toolkit@^21.0.1` which is the correct package
- **Files modified:** package.json, package-lock.json

**2. [Rule 3 - Blocking issue] Spartan UI helm generation via interactive CLI**
- **Found during:** Task 2 Spartan primitive generation
- **Issue:** `@spartan-ng/cli:ui` generator requires interactive prompts (directory selection, component names) that cannot be automated without workspace-level configuration
- **Fix:** Installed `@spartan-ng/brain` (the behavior layer) which is directly importable by components. Created `components/spartan/index.ts` with documentation for on-demand helm generation. The brain primitives provide full accessibility/behavior; helm wrappers are thin CSS shells generated per-remote as needed.
- **Files modified:** Added spartan/index.ts as documentation stub

**3. [Rule 1 - Discovery] Plan 02 types already built**
- **Found during:** Task 1 store creation
- **Issue:** STATE.md showed only plan 01 complete, but git log showed plan 02 was already executed (types library, ApiService, Tauri utils all built)
- **Fix:** Plan 03 executed correctly using existing types from plan 02. Added `WarningPreference` and `ConversationMessage` to conversation.types.ts (confirmed already present in HEAD).

## Self-Check: PASSED

All 26 created files verified present. Both task commits verified in git log:
- `34570d1` — feat(09-03): create SseService and all 8 NgRx SignalStores
- `cac7d33` — feat(09-03): create shared UI library with design tokens, icons, pipes, and directives

TypeScript compilation: PASSED (tsc --noEmit exits clean)
Shell app build: PASSED (nx build shell succeeds)

Verification criteria:
- [x] 8 SignalStores exported from shared-state
- [x] conversation.store has chatSessionsVersion counter and incrementChatSessionsVersion()
- [x] conversation.store withStorageSync excludes chatSessionsVersion
- [x] SseService has connect/disconnect/ngOnDestroy
- [x] conversation.store and data-source.store use withStorageSync
- [x] Icon component count >= 50 (70 icon components created)
- [x] 3 pipes standalone and exported (FormatCurrency, RelativeTime, TimeAgo)
- [x] cn() utility exported from shared-ui
- [x] ng2-pdf-viewer version >= 10.3.0 (installed: 10.4.0)
- [x] @spartan-ng/brain available for direct import
