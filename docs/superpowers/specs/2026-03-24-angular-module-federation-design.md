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
| Monorepo | Nx with Native Federation (`@angular-architects/native-federation`) | ES module-based (esbuild-compatible), affected builds, dependency graph, caching |
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
- Hydrated on store init, synced on change via SignalStore `withHooks({ onInit })` + Angular `effect()` functions. A custom `withLocalStorage()` SignalStore feature encapsulates the hydrate-on-init + sync-on-change pattern for reuse across stores.

### Cross-Tab/Window Synchronization

The `withLocalStorage()` feature must include a `window.addEventListener('storage', ...)` listener to sync state across tabs/windows. When a user changes a setting (e.g., `interactiveShipping`) in one Tauri window or browser tab, the `storage` event fires in all other windows. The listener parses the new value, compares against the current signal value, and updates the store if changed — keeping all instances in sync without polling. This is critical for the Tauri desktop app which may spawn multiple WebView windows, and for the dev workflow where multiple browser tabs are common.

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

### SSE Lifecycle & Remote Teardown

In React, `useEffect` cleanup functions close SSE connections when a component unmounts. In Angular, this responsibility falls on `OnDestroy`. **Critical requirement:** `ConversationSseService` and `JobProgressSseService` must be provided at the Chat Remote's component level (not `providedIn: 'root'`), so their lifecycle is tied to the Chat Remote's component tree. When the Chat Remote is destroyed/unloaded via Module Federation, Angular destroys these services and triggers their `ngOnDestroy()` hooks, which must call `SseService.disconnect()`. Without this, "ghost" SSE connections would continue receiving events and dispatching to the shared store from an unmounted remote. The `SseService.disconnect()` method must explicitly call `eventSource.close()` and unsubscribe all active observables.

### Domain SSE Services (chat remote)

```
apps/chat-remote/src/services/
├── conversation-sse.service.ts     # Maps raw SSE → conversation store updates
├── conversation-session.service.ts # Session lifecycle: mutex, generation guard, mode tracking
├── job-progress-sse.service.ts     # Maps raw SSE → job progress signals
├── command-autocomplete.service.ts # /command token autocomplete (port of useCommandAutocomplete)
├── contact-autocomplete.service.ts # @handle token autocomplete (port of useContactAutocomplete)
└── token-highlighter.service.ts    # Text segment parsing for mirror-div highlighting (port of useTokenHighlighter)
```

**ConversationSseService** consumes `/conversations/{id}/stream`:
- `agent_message` → append to `conversation.store` messages
- `preview_ready` → set preview in `conversation.store`, increment `job.store.jobListVersion`
- `preview_partial` → skip (stability)
- Domain events (`pickup_preview`, `location_result`, `landed_cost_result`, `tracking_result`, `paperless_result`, `paperless_upload_prompt`, `contact_saved`) → domain card messages in `conversation.store`
- `error` → error message in `conversation.store`
- `done` → clear streaming flag, increment `chatSessionsVersion`

**ConversationSessionService** (chat remote) manages session lifecycle — the most complex piece of frontend logic, ported from `useConversation.ts` (349 lines):
- `ensureSession()` — creates a conversation session if none exists, with a **mutex** (Promise-based lock) to prevent concurrent `createConversation` API calls from race conditions
- **Generation guard** — an epoch counter that increments on session reset; stale SSE events from a previous session generation are rejected before they reach the store
- **Mode tracking** — detects mismatch between current `interactiveShipping` flag and the mode the session was created with; on mismatch, tears down the old session (close SSE, delete session) and creates a new one with the correct mode
- `loadSession(sessionId, mode)` — restores a persisted session: sets session ID, loads message history from API, reconnects SSE stream
- `startNewChat()` — closes SSE stream for current session without deleting it (preserves history), clears local state
- `reset()` — full teardown: close SSE, delete session via API, clear all conversation state

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
| `layout/Header.tsx` | `header.component.ts` | Logo (ShipAgentLogo) + interactive shipping toggle |
| `ui/ShipAgentLogo.tsx` | `shipagent-logo.component` (shared UI) | Branded SVG logo |
| `layout/Sidebar.tsx` | `sidebar-shell.component.ts` | Collapsible container — loads sidebar-remote |
| UpdateChecker (in App) | `update-checker.component.ts` | Tauri updater plugin |

### Chat Remote

| React | Angular | Notes |
|-------|---------|-------|
| `CommandCenter.tsx` (1000 lines) | `chat-container`, `message-list`, `event-processor.service`, `chat-actions.service` | Decomposed from monolith |
| `command-center/messages.tsx` | `system-message.component`, `user-message.component`, `typing-indicator.component`, `active-source-banner.component`, `interactive-mode-banner.component`, `welcome-message.component` | All 6 sub-components from messages.tsx |
| `command-center/ToolCallChip.tsx` | `tool-call-chip.component` | Animated chip for active tool calls |
| `command-center/PreviewCard.tsx` (1256 lines) | `batch-preview.component`, `interactive-preview.component`, `preview-actions.component` | Split batch vs interactive |
| `command-center/ProgressDisplay.tsx` | `progress-display.component` | Direct port |
| `command-center/CompletionArtifact.tsx` | `completion-artifact.component` | Direct port |
| `chat/RichChatInput.tsx` | `rich-chat-input.component` + `mirrorSync` directive | Mirror div via reusable directive (see below) |
| `lib/expandTokens.ts` | `token-expansion.service` (shared lib or chat service) | /command + @handle expansion |
| `hooks/useCommandAutocomplete.ts` | `command-autocomplete.service.ts` | Token autocomplete for /commands |
| `hooks/useContactAutocomplete.ts` | `contact-autocomplete.service.ts` | Token autocomplete for @handles |
| `hooks/useTokenHighlighter.ts` | `token-highlighter.service.ts` | Mirror-div text segment parsing |

### Sidebar Remote

| React | Angular | Notes |
|-------|---------|-------|
| `sidebar/DataSourcePanel.tsx` (732 lines) | `data-source-panel`, `local-source.component`, `platform-source.component` | Split by source type |
| `sidebar/dataSourceMappers.ts` | `data-source-mappers.service.ts` | Column → ColumnMetadata conversion utility |
| `sidebar/JobHistoryPanel.tsx` | `job-history-panel.component` | Direct port |
| `sidebar/ChatSessionsPanel.tsx` | `chat-sessions-panel.component` | Direct port |
| `RecentSourcesModal.tsx` | `recent-sources-modal.component` | Dialog via Spartan UI |
| `ChatHistoryFlyout.tsx` | `chat-history-flyout.component` | Direct port |
| `hooks/useExternalSources.ts` (475 lines) | `platforms.service.ts` in settings remote | Complex behavioral logic: connect, disconnect, test, fetchOrders, checkShopifyEnv, checkAmazonEnv |

### Settings Remote

| React | Angular | Notes |
|-------|---------|-------|
| `settings/OnboardingWizard.tsx` | `onboarding-wizard.component` + step components | 3-step flow |
| `settings/SettingsFlyout.tsx` | `settings-flyout.component` | Accordion layout |
| `settings/ConnectionsSection.tsx` | `connections-section.component` | Provider cards |
| `settings/ProviderCard.tsx` | `provider-card.component` | Generic platform card |
| `settings/AnthropicKeyForm.tsx` | `anthropic-key-form.component` | API key input (onboarding + connections) |
| `settings/ShopifyConnectForm.tsx` | `shopify-connect-form.component` | Shopify credential form |
| `settings/AmazonConnectForm.tsx` | `amazon-connect-form.component` | Amazon SP-API credential form |
| `settings/UPSConnectForm.tsx` | `ups-connect-form.component` | UPS credential form |
| `settings/AddressBookSection.tsx` | `address-book-section.component` | Contact CRUD |
| `settings/ContactForm.tsx` | `contact-form.component` | Contact add/edit modal form |
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
- **`messages.tsx`** → 6 separate components; `CopyButton` (currently inline) extracted to `libs/shared/ui/components/copy-button/`
- **`useExternalSources.ts`** (475 lines) → `platforms.service.ts` (behavioral logic) + `platforms.store.ts` (state)

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
│   ├── icons/                  # Custom SVG icon components (50+ from icons.tsx, OnPush)
│   ├── brand-icons/            # Platform logos: Shopify, Amazon, WooCommerce, DataSource, ShipAgent
│   ├── shipagent-logo/         # ShipAgentLogo branded SVG (used in Header)
│   ├── copy-button/            # Hover-reveal clipboard button (extracted from messages.tsx)
│   └── status-badge/           # Reusable status badge (success/warning/error/info/neutral)
├── pipes/
│   ├── format-currency.pipe.ts # Intl.NumberFormat USD from cents (port of formatCurrency)
│   ├── relative-time.pipe.ts   # "5m ago", "2h ago" (port of formatRelativeTime)
│   └── time-ago.pipe.ts        # ISO string → relative time (port of formatTimeAgo)
├── directives/
│   └── mirror-sync.directive.ts    # Textarea↔div scroll/text sync for rich input overlays
└── index.ts
```

### Mirror Sync Directive

The `RichChatInput` uses a "mirror div" technique — a hidden `<div>` overlaid on a `<textarea>` to render token highlighting while the user types in the textarea. This requires perfect synchronization of scroll offsets and text wrapping between the two elements. Rather than embedding this logic in the component, extract it into a reusable `MirrorSyncDirective` in the shared UI library:

```typescript
@Directive({ selector: '[appMirrorSync]' })
export class MirrorSyncDirective implements AfterViewInit, OnDestroy {
  @Input() mirrorTarget!: HTMLElement; // The div to sync with
  // Syncs scrollTop, scrollLeft, and dimensions on input/scroll/resize events
}
```

This keeps `rich-chat-input.component` focused on its template and autocomplete logic, and makes the mirror technique reusable if a "Rich Command Editor" is needed in the Settings remote later.

### What Ports Directly

- All OKLCH color variables (CSS custom properties)
- All custom CSS classes (`card-premium`, `btn-primary`, `badge-*`, `card-domain-*`, `message-system`, etc.)
- Tailwind v4 config at workspace root
- Domain colors (shipping/green 145, pickup/purple 300, locator/teal 185, paperless/amber 85, landed-cost/indigo 265, tracking/blue 230)
- Typography (DM Sans, Instrument Serif, JetBrains Mono)

### What Changes

- `cn()` utility (clsx + tailwind-merge) → same function, Angular import
- React inline SVG components (`icons.tsx`, `brand-icons.tsx`) → Angular SVG components with `ChangeDetectionStrategy.OnPush`
- `lucide-react` icons (Package, X, Plus, ChevronDown, etc.) → `lucide-angular` (same icon set, Angular bindings)
- `react-pdf` → `ng2-pdf-viewer` (same pdfjs-dist under the hood)
- `react-markdown` → `ngx-markdown` (same remark-gfm plugin)

### Icon Inventory

Two icon sources must be ported:
1. **Custom SVG icons** (`ui/icons.tsx`) — 50+ inline SVG components. Port to Angular OnPush components in `libs/shared/ui/components/icons/`. Generate a manifest during Phase 1 to verify completeness.
2. **Lucide icons** — used in `messages.tsx`, `Header.tsx`, `ContactForm.tsx`, `SettingsFlyout.tsx`, and others. Replace with `lucide-angular` package (same icon names, Angular bindings).

### CSS Encapsulation Strategy

Angular's default `ViewEncapsulation.Emulated` scopes CSS to individual components, which can break Tailwind's global utility class reach and the industrial design system classes (`card-premium`, `btn-primary`, `badge-*`, `card-domain-*`). The strategy:

1. **Global styles stay global.** All files in `libs/shared/ui/styles/` (tokens.css, typography.css, components.css, animations.css) are imported at the shell level as global stylesheets. They are NOT component-scoped.
2. **Spartan UI wrapper components** that are purely thin wrappers around primitives use `encapsulation: ViewEncapsulation.None` to ensure Tailwind utilities and global classes apply predictably to their internal DOM.
3. **Business components** (chat container, preview cards, domain cards) keep the default `ViewEncapsulation.Emulated` for isolation — their styles are Tailwind utilities applied via `class` bindings, which work regardless of encapsulation mode.
4. **Rule of thumb:** If a component's template uses `card-premium`, `badge-*`, or any global CSS class from `components.css`, that component must either use `ViewEncapsulation.None` or ensure the global styles are imported at the application level (which they are by default via the shell).

### Visual Parity Goal

The Angular app must be pixel-identical to the React app. Same colors, fonts, spacing, animations. The CSS is the source of truth and transfers wholesale. Do not "Angular-ize" the CSS — the React `index.css` with its `@theme` blocks is already well-structured and ports directly as global styles.

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

Global `window.__SHIPAGENT_PORT__` variables are un-Angular. Instead, the port is resolved in the shell and provided as a typed `Signal`-based `InjectionToken`:

1. Shell `main.ts` calls `initSidecar()` (Tauri) or reads environment, resolves port
2. Shell provides the resolved base URL via `InjectionToken<Signal<string>>` (`API_BASE_URL`)
3. `ApiService` injects the signal — reads `apiBaseUrl()` on each request
4. Module Federation shares the token across remotes (provided in shell, consumed everywhere)

```typescript
// libs/shared/api/api-url.token.ts
export const API_BASE_URL = new InjectionToken<Signal<string>>('API_BASE_URL');

// Shell main.ts bootstrap:
const port = await resolveSidecarPort(); // Tauri invoke or env fallback
const baseUrl = signal(port ? `http://127.0.0.1:${port}/api/v1` : '/api/v1');

bootstrapApplication(AppComponent, {
  providers: [
    { provide: API_BASE_URL, useValue: baseUrl },
    // ...
  ]
});

// ApiService consumes:
@Injectable({ providedIn: 'root' })
export class ApiService {
  private baseUrl = inject(API_BASE_URL);
  // All requests use: `${this.baseUrl()}/conversations/...`
}
```

This eliminates global window variables and makes the base URL reactive — if the port were to change (unlikely but possible in future multi-sidecar scenarios), all API calls update automatically.

### Error Handling

| React | Angular |
|-------|---------|
| `ApiError` class (statusCode, errorResponse, message) | Same `ApiError` class in shared types |
| try/catch per call | `HttpInterceptor` catches globally, maps to `ApiError` |
| Per-component error display | Store-level error signals + component-level error templates |

### Endpoint Grouping

Single `ApiService` class with methods organized by domain (~55 endpoints total):
- `conversations.*` — create, send, stream, delete, list, history, rename, export, saveArtifact
- `jobs.*` — list, get, confirm, cancel, delete, skipRows, progress, labels (merged URL, zip)
- `dataSources.*` — import, upload, disconnect, status
- `savedSources.*` — list, reconnect, delete, bulkDelete
- `platforms.*` — connect, disconnect, envStatus, orders, connections, activateShopify, activateAmazon, testConnection
- `connections.*` — list, get, save, delete, validate, disconnect (provider connection CRUD)
- `settings.*` — get, patch, putCredential, credentialStatus, completeOnboarding
- `contacts.*` — list, create, update, delete, search, getByHandle
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

### Domain Card Component-Level Providers

Domain cards that require card-specific logic (e.g., Landed Cost calculation formatting, Tracking timeline parsing, Paperless file upload state) must use **component-level `providers: [...]`** rather than module-level or root-level providers. This ensures:

1. **Memory isolation** — The Landed Cost card's formatting service is instantiated only when a `landed_cost_result` event renders the card, and destroyed when the card leaves the DOM. It doesn't bloat the Chat Remote's memory footprint when not in use.
2. **Instance scoping** — Multiple instances of the same card type (e.g., two tracking cards in one conversation) each get their own service instance, preventing state leakage between cards.

```typescript
@Component({
  selector: 'app-landed-cost-card',
  providers: [LandedCostFormatterService], // Scoped to this card instance
  template: `...`
})
export class LandedCostCardComponent { ... }
```

### Remote Dependency Injection Context

With Native Federation, dynamically loaded remote components need proper DI context. The approach:

1. **All shared services are provided in shared libs** (`providedIn: 'root'`). Since the unified build shares a single Angular platform, all remotes share the shell's injector tree. Shared stores, `ApiService`, and `SseService` are singletons across the entire app.
2. **Remote-scoped services** (e.g., `ConversationSseService`, `JobProgressSseService`) are provided in the remote's root component using `providers: [...]`. This creates a child injector scoped to that remote's component tree.
3. **Domain card components** loaded via `ngComponentOutlet` inherit the chat remote's injector (since they're rendered inside the chat container's template). They can inject shared services directly.
4. **Each remote exposes a bootstrap function** that returns both the component and any required providers, so the shell can create the proper injector context:

```typescript
// Remote entry exposes:
export const remoteEntry = {
  component: ChatContainerComponent,
  providers: [ConversationSseService, ConversationSessionService, JobProgressSseService]
};

// Shell loads and renders with providers:
const entry = await loadRemoteModule(...);
// Use createNgModule() or Injector.create() to scope remote providers
```

This ensures remote-scoped services don't leak into other remotes while shared services remain globally available.

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
- **Chat remote** — ChatContainer, message components (6), ToolCallChip, ConversationSseService, ConversationSessionService, JobProgressSseService, batch/interactive previews, ProgressDisplay, CompletionArtifact, RichChatInput, autocomplete services (command + contact), token highlighter service
- **Sidebar remote** — DataSourcePanel (local + platform), dataSourceMappers, JobHistoryPanel, ChatSessionsPanel, RecentSourcesModal, ChatHistoryFlyout
- **Settings remote** — OnboardingWizard, SettingsFlyout, ConnectionsSection, ProviderCard, platform form components (Anthropic, Shopify, Amazon, UPS), AddressBookSection, ContactForm, CustomCommandsSection, ShipmentBehaviourSection, PlatformsService
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
- `@angular-architects/native-federation` (ES module-based federation, works with Angular CLI's esbuild builder — NOT the older webpack-based `@angular-architects/module-federation`). See [Shared Dependency Pinning](#shared-dependency-pinning-native-federation--tauri) for critical Tauri compatibility notes.
- `@ngrx/signals` (SignalStore)

### UI & Styling
- `@spartan-ng/ui-*-helm` (button, input, switch, dialog, scroll-area, progress, tooltip)
- `@spartan-ng/brain` (headless primitives under Spartan)
- `lucide-angular` (replaces `lucide-react` — same icon set, Angular bindings for Package, X, Plus, etc.)
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

## Shared Dependency Pinning (Native Federation + Tauri)

Native Federation relies on the browser's native Import Maps to share dependencies between the shell and remotes. Since Tauri uses a custom protocol (`tauri://` or `https://tauri.localhost`), the `federation.config.js` must explicitly pin shared dependencies to ensure version alignment:

```javascript
// federation.config.js (shell)
const { withNativeFederation, share } = require('@angular-architects/native-federation/config');

module.exports = withNativeFederation({
  shared: share({
    '@angular/core': { singleton: true, strictVersion: true, requiredVersion: '19.x.x' },
    '@angular/common': { singleton: true, strictVersion: true, requiredVersion: '19.x.x' },
    '@angular/common/http': { singleton: true, strictVersion: true },
    '@ngrx/signals': { singleton: true, strictVersion: true },
    'rxjs': { singleton: true, strictVersion: true },
  })
});
```

**Why this matters:** If the shell loads `@angular/core@19.1.0` and a remote bundles `@angular/core@19.2.0`, Angular throws a "Multiple instances of Angular detected" runtime error. With `strictVersion: true` + `singleton: true`, Native Federation will reject the remote at load time with a clear error rather than producing cryptic runtime failures. The unified build approach (all remotes built together) mitigates this in practice, but the config must enforce it for when independent builds are eventually enabled.

**Tauri protocol note:** Verify during Phase 1 that Native Federation's import map resolution works correctly under `tauri://localhost` or `https://tauri.localhost`. If import map URLs are relative, they resolve against the Tauri protocol origin. If absolute (e.g., `http://localhost:4200`), they will fail in production. The shell's federation config must use **relative paths** for all remote entries.

## Rollback Strategy

The React frontend is preserved intact on its current branch. If the Angular app has critical bugs post-switchover:

1. Tauri config and Docker build reference a `FRONTEND_DIST` path — revert to the React `dist/` folder in one CI run.
2. The React `frontend/` directory is not deleted until the Angular app has been stable in production for a defined period.
3. A git tag (`pre-angular-switchover`) is created immediately before the switchover commit for fast revert.

## Accessibility

- Spartan UI's built-in ARIA attributes and keyboard navigation are the baseline for primitive components (dialogs, tooltips, switches, etc.).
- Custom components must preserve the same accessibility characteristics as their React counterparts: semantic HTML elements (`<button>`, `<input>`, `<label>`), `:focus-visible` ring styling, keyboard navigation for `RichChatInput` autocomplete (arrow keys, Enter, Escape).
- Domain cards and preview cards must be navigable via keyboard (confirm/cancel/refine actions reachable via Tab + Enter).
- Verification: each remote's test suite includes at minimum one keyboard-navigation test per interactive component.

## Performance

- **No explicit bundle size target** — but the Angular shell's initial load must not regress beyond the current React app's load time on desktop.
- Phase 3 integration includes a bundle size comparison (React vs Angular) using `source-map-explorer` or `nx build --stats-json`.
- Lazy loading: domain remote and settings remote are loaded on demand (settings on flyout open, domain cards on first SSE domain event). Chat and sidebar load eagerly since they're always visible.
