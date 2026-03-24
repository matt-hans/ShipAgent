# Angular Module Federation Frontend Rebuild — Design Spec

**Date:** 2026-03-24
**Status:** Approved
**Approach:** Foundation First, Remotes in Waves (Approach C)

## Motivation

ShipAgent is moving to a multi-team development model. The current React frontend is a single-team monolith (~12.5k lines, 50 components, 8 hooks, 40+ API functions). The rebuild replaces it with an Angular Module Federation architecture that provides team-ownership boundaries, independent development workflows, and a shared contract layer — while maintaining 100% feature parity.

## Technology Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Framework | Angular 19 | Target framework for multi-team model |
| Monorepo | Nx with Module Federation | Built-in MF generators, affected builds, dependency graph, caching |
| Module boundaries | Natural React splits: Chat, Sidebar, Settings, Domain + Shared | Maps to existing feature verticals |
| State management | NgRx SignalStore | Cross-team contracts with signal simplicity; feature stores per remote |
| SSE streaming | Hybrid — generic shared service + domain mapping in remotes | Reusable plumbing in shared, domain logic in owning remote |
| Component library | Spartan UI (Angular shadcn port) + Tailwind v4 + OKLCH design system | Closest 1:1 match to current shadcn/ui approach |
| Tauri integration | Shell-only — bootstrap + port discovery; remotes are Tauri-agnostic | Only shell needs Tauri; keeps remotes portable |
| Testing | Jest + Angular Testing Library via Nx | Nx first-class support, same philosophy as React Testing Library |
| Deployment | Unified build (all remotes built together, single artifact) | Team-ownership benefits without infrastructure overhead; split later |

## 1. Nx Workspace Structure

```
shipagent-frontend/
├── apps/
│   ├── shell/                    # Host app — layout, Tauri bootstrap, routing
│   ├── chat-remote/              # Remote: CommandCenter, SSE, Preview, Progress, Domain Cards
│   ├── sidebar-remote/           # Remote: DataSource, JobHistory, ChatSessions
│   ├── settings-remote/          # Remote: Onboarding, Connections, AddressBook, Commands
│   └── domain-remote/            # Remote: Pickup, Tracking, Locator, Paperless, LandedCost cards
├── libs/
│   ├── shared/
│   │   ├── state/                # NgRx SignalStore — shared stores
│   │   ├── api/                  # HttpClient-based API service (40+ endpoints)
│   │   ├── sse/                  # Generic SseService — EventSource lifecycle, reconnect, parse
│   │   ├── types/                # All TypeScript interfaces/enums
│   │   ├── ui/                   # Spartan UI primitives + design tokens + icons + pipes + directives
│   │   └── tauri/                # Tauri detection + port signal (shell-only consumer)
│   └── testing/                  # Shared mocks, fixtures, test hosts
├── nx.json
├── module-federation.manifest.json
└── tailwind.config.ts            # Shared Tailwind config (OKLCH tokens, fonts, custom classes)
```

### Rules

- **No remote-to-remote imports.** All cross-remote communication goes through shared state stores.
- **Remotes import from `@shipagent/shared-*` only.** Never from another remote's source.
- **Shell owns layout** (Header, sidebar container, main area, flyout slots). Remotes own content.
- **Tailwind config** shared at workspace root — all projects use the same design tokens.

## 2. Shared State Architecture (NgRx SignalStore)

The current React `useAppState` (25+ fields in one context) splits into 8 focused feature stores:

```
libs/shared/state/
├── app.store.ts           # UI state: sidebarCollapsed, settingsFlyoutOpen, isProcessing, isToggleLocked
├── conversation.store.ts  # Active conversation: sessionId, messages[], isStreaming, pendingMessage, interactiveShipping, warningPreference
├── job.store.ts           # Jobs: activeJob, jobListVersion (refresh trigger)
├── data-source.store.ts   # Data source: dataSource, activeSourceType, activeSourceInfo, writeBackEnabled, cachedLocalConfig
├── settings.store.ts      # Settings: appSettings singleton, credentialStatus, onboardingCompleted
├── contacts.store.ts      # Address book: contacts[]
├── commands.store.ts      # Custom commands: customCommands[]
├── platforms.store.ts     # External platforms: per-platform connection state, providerConnectionsVersion
└── index.ts               # Public API — re-exports all stores
```

### Cross-Remote Data Flow

| Store | Written by | Read by |
|-------|-----------|---------|
| `conversation` | Chat remote (SSE events) | Sidebar remote (session list refresh) |
| `job` | Chat remote (preview/execute) | Sidebar remote (job list), Shell (active job) |
| `data-source` | Sidebar remote (upload/connect) | Chat remote (schema in prompts), Shell (status badge) |
| `settings` | Settings remote (onboarding, credentials) | Shell (onboarding gate), Chat (agent model) |
| `contacts` | Settings remote (CRUD) | Chat remote (@handle expansion) |
| `commands` | Settings remote (CRUD) | Chat remote (/command expansion) |
| `platforms` | Settings remote + Sidebar remote | Chat remote (platform status), Sidebar (connection indicator) |
| `app` | Shell (layout toggles) | All remotes (UI flags) |

### Persistence

- `warningPreference` → `localStorage` key `shipagent_warning_preference`
- `interactiveShipping` → `localStorage` key `shipagent_interactive_shipping`
- `writeBackEnabled` → `localStorage` key `shipagent_write_back`
- Hydrated on store init, synced on change via NgRx effects.

### Cross-Remote Pattern

Remote A dispatches to its store → store signals update → Remote B reads via `computed()` signals. No direct events between remotes, no event bus. The store IS the bus.

## 3. SSE Streaming Architecture

Three SSE streams with different lifecycles and event types, split into generic plumbing (shared) and domain mapping (chat remote).

### Generic SseService (shared lib)

```
libs/shared/sse/
├── sse.service.ts          # EventSource lifecycle, reconnect with exponential backoff, JSON parse, cleanup
├── sse.models.ts           # RawSseEvent, SseConnectionState, SseConfig
└── index.ts
```

- `connect(url: string)` → returns `Observable<RawSseEvent>` + connection state signal
- Handles reconnect with exponential backoff
- Keepalive ping handling
- Cleanup on `disconnect()` — no leaked EventSource connections

### Domain SSE Services (chat remote)

```
apps/chat-remote/src/services/
├── conversation-sse.service.ts   # Maps raw SSE → conversation store updates
└── job-progress-sse.service.ts   # Maps raw SSE → job progress signals
```

**ConversationSseService** consumes `/conversations/{id}/stream`:
- `agent_message` → append to `conversation.store` messages
- `preview_ready` → set preview in `conversation.store`, increment `job.store.jobListVersion`
- `preview_partial` → skip (stability)
- Domain events (`pickup_preview`, `location_result`, `landed_cost_result`, `tracking_result`, `paperless_result`, `paperless_upload_prompt`, `contact_saved`) → domain card messages in `conversation.store`
- `error` → error message in `conversation.store`
- `done` → clear streaming flag, increment `chatSessionsVersion`
- **Mutex pattern** for session creation (prevents concurrent `createConversation` calls)
- **Generation guard** (rejects stale events after session reset)
- **Mode tracking** (detects interactive↔batch mismatch, tears down + recreates session)

**JobProgressSseService** consumes `/jobs/{id}/progress/stream`:
- Maps: `batch_started`, `row_started`, `row_completed`, `row_failed`, `batch_completed`, `batch_failed`
- Updates local progress signals (total, processed, successful, failed, costCents, rowFailures)
- Fires completion/failure callbacks → updates `job.store`

### Cross-Remote SSE Flow

1. Chat remote receives `preview_ready` via SSE
2. `ConversationSseService` dispatches to `conversation.store` AND increments `job.store.jobListVersion`
3. Sidebar remote's job list component has `effect()` watching `job.store.jobListVersion` → triggers re-fetch

## 4. Component Mapping (React → Angular)

### Shell App

| React | Angular | Notes |
|-------|---------|-------|
| `App.tsx` | `app.component.ts` | Root — OnboardingWizard gate, layout scaffold |
| `layout/Header.tsx` | `header.component.ts` | Logo + interactive shipping toggle |
| `layout/Sidebar.tsx` | `sidebar-shell.component.ts` | Collapsible container — loads sidebar-remote |
| UpdateChecker (in App) | `update-checker.component.ts` | Tauri updater plugin |

### Chat Remote

| React | Angular | Notes |
|-------|---------|-------|
| `CommandCenter.tsx` (1000 lines) | `chat-container`, `message-list`, `event-processor.service`, `chat-actions.service` | Decomposed from monolith |
| `command-center/messages.tsx` | `system-message.component`, `user-message.component`, `typing-indicator.component` | Direct port |
| `command-center/PreviewCard.tsx` (1256 lines) | `batch-preview.component`, `interactive-preview.component`, `preview-actions.component` | Split batch vs interactive |
| `command-center/ProgressDisplay.tsx` | `progress-display.component` | Direct port |
| `command-center/CompletionArtifact.tsx` | `completion-artifact.component` | Direct port |
| `chat/RichChatInput.tsx` | `rich-chat-input.component` | Mirror div + token highlighting |
| `chat/ChatTimeline.tsx` | `chat-timeline.component` | IntersectionObserver minimap |
| `lib/expandTokens.ts` | `token-expansion.service` (shared lib or chat service) | /command + @handle expansion |

### Sidebar Remote

| React | Angular | Notes |
|-------|---------|-------|
| `sidebar/DataSourcePanel.tsx` (732 lines) | `data-source-panel`, `local-source.component`, `platform-source.component` | Split by source type |
| `sidebar/JobHistoryPanel.tsx` | `job-history-panel.component` | Direct port |
| `sidebar/ChatSessionsPanel.tsx` | `chat-sessions-panel.component` | Direct port |
| `RecentSourcesModal.tsx` | `recent-sources-modal.component` | Dialog via Spartan UI |
| `ChatHistoryFlyout.tsx` | `chat-history-flyout.component` | Direct port |

### Settings Remote

| React | Angular | Notes |
|-------|---------|-------|
| `settings/OnboardingWizard.tsx` | `onboarding-wizard.component` + step components | 3-step flow |
| `settings/SettingsFlyout.tsx` | `settings-flyout.component` | Accordion layout |
| `settings/ConnectionsSection.tsx` | `connections-section.component` | Provider cards |
| `settings/ProviderCard.tsx` | `provider-card.component` + per-platform form components | Generic + forms |
| `settings/AddressBookSection.tsx` | `address-book-section.component` | Contact CRUD |
| `settings/CustomCommandsSection.tsx` | `custom-commands-section.component` | Command CRUD |
| `settings/ShipmentBehaviourSection.tsx` | `shipment-behaviour-section.component` | Model, concurrency, defaults |

### Domain Remote

| React | Angular | Notes |
|-------|---------|-------|
| `PickupPreviewCard.tsx` | `pickup-preview.component` | Confirm/cancel actions |
| `PickupCompletionCard.tsx` | `pickup-completion.component` | Direct port |
| `LocationCard.tsx` | `location-card.component` | Direct port |
| `LandedCostCard.tsx` | `landed-cost-card.component` | Direct port |
| `PaperlessCard.tsx` | `paperless-card.component` | Direct port |
| `PaperlessUploadCard.tsx` | `paperless-upload.component` | File upload form |
| `TrackingCard.tsx` | `tracking-card.component` | Activity timeline |
| `ContactCard.tsx` | `contact-card.component` | Direct port |
| `JobDetailPanel.tsx` | `job-detail-panel.component` | Expanded job view |
| `LabelPreview.tsx` | `label-preview.component` | ng2-pdf-viewer replaces react-pdf |

### Notable Decompositions

- **`CommandCenter.tsx`** (1000 lines) → container + message list + event processor service + actions service
- **`PreviewCard.tsx`** (1256 lines) → batch preview + interactive preview + shared actions
- **`DataSourcePanel.tsx`** (732 lines) → panel container + local source + platform source

## 5. Shared UI Library & Design System

### Spartan UI Primitives (replacing shadcn/ui)

| shadcn/ui (React) | Spartan UI (Angular) | Package |
|---|---|---|
| Button | `hlm-button` | `@spartan-ng/ui-button-helm` |
| Input | `hlm-input` | `@spartan-ng/ui-input-helm` |
| Switch | `hlm-switch` | `@spartan-ng/ui-switch-helm` |
| Dialog | `hlm-dialog` | `@spartan-ng/ui-dialog-helm` |
| ScrollArea | `hlm-scroll-area` | `@spartan-ng/ui-scrollarea-helm` |
| Progress | `hlm-progress` | `@spartan-ng/ui-progress-helm` |
| Tooltip | `hlm-tooltip` | `@spartan-ng/ui-tooltip-helm` |
| Card | Custom (`card-premium` class) | Existing CSS |
| Alert | Custom (badge/alert classes) | Existing CSS |

### Shared UI Library Structure

```
libs/shared/ui/
├── styles/
│   ├── tokens.css              # OKLCH color variables (ported from index.css)
│   ├── typography.css          # DM Sans, Instrument Serif, JetBrains Mono
│   ├── components.css          # card-premium, btn-primary, badge-*, card-domain-*
│   └── animations.css          # typing-indicator, scan-line, progress-bar
├── components/
│   ├── icons/                  # SVG icon components (50+ icons, OnPush)
│   ├── brand-icons/            # Platform logos (Shopify, Amazon, etc.)
│   ├── copy-button/            # Hover-reveal clipboard button
│   └── status-badge/           # Reusable status badge (success/warning/error/info/neutral)
├── pipes/
│   ├── format-currency.pipe.ts # Intl.NumberFormat USD from cents
│   └── relative-time.pipe.ts   # "5m ago", "2h ago"
├── directives/
│   └── intersection-observer.directive.ts  # For ChatTimeline minimap
└── index.ts
```

### What Ports Directly

- All OKLCH color variables (CSS custom properties)
- All custom CSS classes (`card-premium`, `btn-primary`, `badge-*`, `card-domain-*`, `message-system`, etc.)
- Tailwind v4 config at workspace root
- Domain colors (shipping/green 145, pickup/purple 300, locator/teal 185, paperless/amber 85, landed-cost/indigo 265, tracking/blue 230)
- Typography (DM Sans, Instrument Serif, JetBrains Mono)

### What Changes

- `cn()` utility (clsx + tailwind-merge) → same function, Angular import
- React inline SVG components → Angular SVG components with `ChangeDetectionStrategy.OnPush`
- `react-pdf` → `ng2-pdf-viewer` (same pdfjs-dist under the hood)
- `react-markdown` → `ngx-markdown` (same remark-gfm plugin)

### Visual Parity Goal

The Angular app must be pixel-identical to the React app. Same colors, fonts, spacing, animations. The CSS is the source of truth and transfers wholesale.

## 6. API Client & Error Handling

```
libs/shared/api/
├── api.service.ts              # Central HttpClient service — all 40+ endpoints
├── api.models.ts               # Request/response interfaces (if not in types lib)
├── api.interceptors.ts         # Error interceptor (ApiError mapping), auth header (X-API-Key)
├── api-url.token.ts            # InjectionToken<string> for base URL
└── index.ts
```

### Base URL Resolution

1. Shell bootstrap calls `initSidecar()` (Tauri) or reads environment
2. Shell provides resolved base URL via `InjectionToken<string>` (`API_BASE_URL`)
3. `ApiService` injects the token — all requests use it
4. Module Federation shares the token across remotes (provided in shell, consumed everywhere)

```typescript
// Shell provides:
{ provide: API_BASE_URL, useFactory: () => {
    const port = (window as any).__SHIPAGENT_PORT__;
    return port ? `http://127.0.0.1:${port}/api/v1` : '/api/v1';
}}
```

### Error Handling

| React | Angular |
|-------|---------|
| `ApiError` class (statusCode, errorResponse, message) | Same `ApiError` class in shared types |
| try/catch per call | `HttpInterceptor` catches globally, maps to `ApiError` |
| Per-component error display | Store-level error signals + component-level error templates |

### Endpoint Grouping

Single `ApiService` class with methods organized by domain:
- `conversations.*` — create, send, stream, delete, list, history, rename, export
- `jobs.*` — list, get, confirm, cancel, delete, skipRows, progress, labels (merged, zip)
- `dataSources.*` — import, upload, disconnect, status
- `savedSources.*` — list, reconnect, delete, bulkDelete
- `platforms.*` — connect, disconnect, envStatus, orders, connections
- `settings.*` — get, patch, putCredential, credentialStatus, completeOnboarding
- `contacts.*` — list, create, update, delete, search
- `commands.*` — list, create, update, delete

## 7. Routing & Module Federation Wiring

The current React app has no router — everything is visible simultaneously (sidebar, chat, settings flyout). The Angular shell mirrors this with component-based loading, not route-based.

### Shell Layout

```typescript
@Component({
  template: `
    <app-header />
    <div class="app-body">
      <app-sidebar-shell [collapsed]="sidebarCollapsed()">
        <sidebar-remote *ngComponentOutlet="sidebarComponent" />
      </app-sidebar-shell>
      <main class="main-content">
        <chat-remote *ngComponentOutlet="chatComponent" />
      </main>
    </div>
    <settings-remote *ngIf="settingsFlyoutOpen()" />
    <app-onboarding-gate />
  `
})
```

### Remote Exposure (Components, Not Routes)

| Remote | Exposes | Loaded by |
|--------|---------|-----------|
| `chat-remote` | `ChatContainerComponent` | Shell main area (always visible) |
| `sidebar-remote` | `SidebarContentComponent` | Shell sidebar slot (always visible) |
| `settings-remote` | `SettingsFlyoutComponent`, `OnboardingWizardComponent` | Shell overlay (conditional) |
| `domain-remote` | `DomainCardRegistryService` | Chat remote (renders domain cards by type) |

### Domain Card Registry Pattern

The domain remote provides a registry service for dynamic card resolution:

```typescript
@Injectable()
export class DomainCardRegistryService {
  resolve(cardType: string): Type<any> | null {
    const registry: Record<string, Type<any>> = {
      'pickup_preview': PickupPreviewComponent,
      'pickup_completion': PickupCompletionComponent,
      'location_result': LocationCardComponent,
      'landed_cost_result': LandedCostCardComponent,
      'tracking_result': TrackingCardComponent,
      'paperless_result': PaperlessCardComponent,
      'paperless_upload': PaperlessUploadComponent,
      'contact_saved': ContactCardComponent,
    };
    return registry[cardType] ?? null;
  }
}
```

Chat remote uses: `<ng-container *ngComponentOutlet="domainRegistry.resolve(message.metadata.action)" />`

This keeps the chat remote decoupled from domain card implementations.

## 8. Testing Strategy

### Per-Project Test Configuration

| Project | Tests |
|---------|-------|
| `shell` | Bootstrap, layout, Tauri init, onboarding gate |
| `chat-remote` | Chat container, SSE services, previews, progress, message rendering |
| `sidebar-remote` | DataSource panel, JobHistory, ChatSessions |
| `settings-remote` | Onboarding wizard, Connections CRUD, AddressBook, Commands |
| `domain-remote` | All domain cards, registry service |
| `shared-state` | All 8 stores (isolation + cross-store interactions) |
| `shared-api` | ApiService endpoints, error interceptor, auth header |
| `shared-sse` | SseService lifecycle, reconnect backoff, JSON parse |
| `shared-ui` | Pipes, directives, icon components |

### Shared Testing Library

```
libs/testing/
├── mocks/
│   ├── api.service.mock.ts       # Spy object for ApiService (all methods)
│   ├── sse.service.mock.ts       # Mock EventSource + controllable event emission
│   ├── store.mocks.ts            # Pre-populated store states per feature
│   └── tauri.mock.ts             # window.__TAURI__ mock
├── fixtures/
│   ├── job.fixtures.ts           # Sample Job, JobRow, BatchPreview
│   ├── conversation.fixtures.ts  # Sample messages, SSE events, domain card data
│   ├── settings.fixtures.ts      # AppSettings, CredentialStatus
│   └── platform.fixtures.ts      # PlatformConnection per provider
└── utils/
    └── test-host.component.ts    # Generic test host for projected content
```

### Parity Verification

Each remote's tests verify the same user-visible behaviors as the React components they replace:
- Same UI states rendered for the same data
- Same user actions trigger the same API calls
- Same SSE events produce the same visual output
- Same error conditions show the same error messages

### CI Optimization

```bash
npx nx test shell                    # Shell only
npx nx test chat-remote              # Chat remote only
npx nx run-many -t test              # All projects
npx nx affected -t test              # Only changed projects
```

`nx affected` ensures that when Team Chat changes chat-remote, only chat-remote + shell tests run — not settings or sidebar.

## Execution Plan

### Phase 1: Foundation

- Nx workspace scaffold with Module Federation configuration
- Shell app (layout, Header, sidebar container, Tauri bootstrap, onboarding gate)
- All 6 shared libraries (state, api, sse, types, ui, tauri)
- 8 NgRx SignalStores with localStorage persistence
- SseService (generic) + ApiService (all 40+ endpoints)
- Spartan UI setup + OKLCH design token port + all custom CSS classes
- Icon components (50+), brand icons, pipes, directives
- Shared testing library (mocks, fixtures, test host)

### Phase 2: Parallel Remotes

Built in parallel against shared contracts:
- **Chat remote** — ChatContainer, message components, ConversationSseService, JobProgressSseService, batch/interactive previews, ProgressDisplay, CompletionArtifact, RichChatInput, ChatTimeline
- **Sidebar remote** — DataSourcePanel (local + platform), JobHistoryPanel, ChatSessionsPanel, RecentSourcesModal, ChatHistoryFlyout
- **Settings remote** — OnboardingWizard, SettingsFlyout, ConnectionsSection, ProviderCards, AddressBookSection, CustomCommandsSection, ShipmentBehaviourSection
- **Domain remote** — All 8 domain card components + DomainCardRegistryService + JobDetailPanel + LabelPreview

### Phase 3: Integration

- Cross-remote integration testing (SSE → store → UI across remotes)
- Tauri desktop packaging (swap React dist → Angular dist)
- Docker build configuration update
- Parity verification against React app
- Switchover (update Tauri, Docker, CI to build Angular)

## Dependencies

### Angular Packages
- `@angular/core` ^19.x, `@angular/cli` ^19.x
- `@nx/angular`, `@nx/js`, `@nx/workspace`
- `@angular-architects/native-federation` (Nx MF plugin)
- `@ngrx/signals` (SignalStore)

### UI & Styling
- `@spartan-ng/ui-*-helm` (button, input, switch, dialog, scroll-area, progress, tooltip)
- `@spartan-ng/brain` (headless primitives under Spartan)
- `tailwindcss` ^4.x, `tailwind-merge`, `clsx`

### Content Rendering
- `ng2-pdf-viewer` (replaces react-pdf)
- `ngx-markdown` + `remark-gfm` (replaces react-markdown)

### Desktop
- `@tauri-apps/api` ^2.x, `@tauri-apps/plugin-shell`, `@tauri-apps/plugin-updater`

### Testing
- `jest`, `@testing-library/angular`, `jest-preset-angular`

## Constraints

- **100% feature parity** with React frontend — no features dropped, no features added.
- **Pixel-identical** visual output — same OKLCH colors, fonts, spacing, animations.
- **Same backend API** — no backend changes required. All `/api/v1/*` endpoints unchanged.
- **Same Tauri integration** — swap `dist/` folder, no Rust changes needed.
- **No hybrid state** — pure Angular. React app stays as-is until switchover.
