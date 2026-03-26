---
phase: 09-angular-module-federation-frontend-rebuild
plan: 04
subsystem: shell-application
tags: [angular, native-federation, shell, layout, remote-loading, onboarding, tauri]
dependency_graph:
  requires: [09-01-PLAN, 09-02-PLAN, 09-03-PLAN]
  provides: [shell-app, remote-loader, shell-layout, onboarding-gate, update-checker]
  affects: [all-remotes, chat-remote, sidebar-remote, settings-remote, domain-remote]
tech_stack:
  added:
    - "NgComponentOutlet directive — dynamic remote component rendering in shell layout"
    - "RemoteLoaderService — wraps loadRemoteModule for all 4 remotes with RemoteEntry interface"
  patterns:
    - "Bootstrap resolves Tauri sidecar port before Angular bootstrapApplication"
    - "API_BASE_URL provided at bootstrap time as Signal<string> InjectionToken"
    - "Zone.js with event coalescing (NOT zoneless) per research recommendation"
    - "Remote loading: lazy Injector.create with parent: this.injector for provider scoping"
    - "NgZone.run() wraps async signal updates after Promise resolves"
    - "requestAnimationFrame poll watches settingsFlyoutOpen() for lazy settings load"
    - "Function() constructor for dynamic import of unavailable Tauri modules"
key_files:
  created:
    - shipagent-frontend/apps/shell/src/app/remote-loader.service.ts
    - shipagent-frontend/apps/shell/src/app/header/header.component.ts
    - shipagent-frontend/apps/shell/src/app/sidebar-shell/sidebar-shell.component.ts
    - shipagent-frontend/apps/shell/src/app/onboarding-gate/onboarding-gate.component.ts
    - shipagent-frontend/apps/shell/src/app/update-checker/update-checker.component.ts
    - shipagent-frontend/apps/shell/src/setup-jest.ts
  modified:
    - shipagent-frontend/apps/shell/src/bootstrap.ts
    - shipagent-frontend/apps/shell/src/app/app.config.ts
    - shipagent-frontend/apps/shell/src/app/app.component.ts
    - shipagent-frontend/libs/shared/tauri/src/port-resolver.ts
    - shipagent-frontend/libs/shared/ui/src/components/brand-icons/index.ts
decisions:
  - "Zone.js (not zoneless) used in app.config.ts — provideZoneChangeDetection with eventCoalescing:true per research recommendation for shell stability"
  - "requestAnimationFrame polling for settings flyout lazy load — avoids effect() injection context requirement; settings opens rarely so polling overhead is negligible"
  - "NgZone.run() wraps async signal updates — ensures Angular's Zone.js is notified of signal changes after Promise resolution (OnPush components need this)"
  - "Function() constructor for @tauri-apps/plugin-updater dynamic import — package not installed in dev; bypasses TS static analysis without requiring the package at compile time"
  - "RemoteEntry interface with optional providers[] — allows remotes to scope their providers to a child Injector while remaining backwards compatible when providers are absent"
metrics:
  duration_minutes: 6
  completed: 2026-03-24T21:28:35Z
  tasks_completed: 2
  files_created: 6
  files_modified: 5
---

# Phase 9 Plan 04: Shell Application Summary

Shell application with Tauri-aware bootstrap (API_BASE_URL resolution), layout scaffold (header + collapsible sidebar + main + settings flyout), Native Federation remote loading, onboarding gate, and Tauri auto-update checker — the application entry point that hosts all 4 remotes.

## What Was Built

### Task 1: Bootstrap, App Config, and Remote Loader Service

**bootstrap.ts** — Async bootstrap resolving Tauri sidecar port before Angular starts:
- Calls `resolveSidecarPort()` from `@shipagent/shared-tauri`
- Provides `API_BASE_URL` as `Signal<string>` with resolved URL (or `/api/v1` fallback)
- Spreads `appConfig.providers` and appends the API_BASE_URL token

**app.config.ts** — Minimal Angular application configuration:
- `provideZoneChangeDetection({ eventCoalescing: true })` — Zone.js with coalescing
- `provideHttpClient(withInterceptors([apiErrorInterceptor]))` — HttpClient with error interceptor
- No router (shell is single-page, routes are handled within remotes)

**remote-loader.service.ts** — `RemoteLoaderService` wrapping `loadRemoteModule`:

| Method | Remote | Exposes |
|--------|--------|---------|
| `loadChat()` | chat-remote | `./ChatContainer` |
| `loadSidebar()` | sidebar-remote | `./SidebarContent` |
| `loadSettingsFlyout()` | settings-remote | `./SettingsFlyout` |
| `loadOnboardingWizard()` | settings-remote | `./OnboardingWizard` |
| `loadDomainCardRegistry()` | domain-remote | `./DomainCardRegistry` |

All methods return `RemoteEntry` with `component: Type<unknown>` and optional `providers[]`.

**setup-jest.ts** — Test setup entry point (Zone.js initialized by Angular vitest runner automatically).

### Task 2: Shell Layout Components

**AppComponent** (`app-root`) — Root layout:
- Injects `AppStore`, `RemoteLoaderService`, `Injector`, `NgZone`
- Eagerly loads `chat-remote` and `sidebar-remote` on `ngOnInit`
- Uses `requestAnimationFrame` poll to lazily load `settings-remote` on first `settingsFlyoutOpen()`
- Template: `<app-header>` + `<app-sidebar-shell [collapsed]>` + `<main>` with `NgComponentOutlet`
- Creates child `Injector` for remote providers when `entry.providers.length > 0`

**HeaderComponent** (`app-header`) — Port of React `Header.tsx`:
- Injects `ConversationStore` (interactive shipping toggle) and `AppStore` (toggle lock)
- `ShipAgentLogoComponent` (`sa-shipagent-logo`) on left
- Custom switch button bound to `conversationStore.interactiveShipping()` on right
- `onToggleInteractiveShipping()` calls `conversationStore.setInteractiveShipping()`

**SidebarShellComponent** (`app-sidebar-shell`) — Port of React `Sidebar.tsx` outer shell:
- `@Input() collapsed: boolean` controls width via `[class.w-16]` / `[class.w-80]`
- `<ng-content>` projects sidebar-remote content when expanded
- Collapse/expand toggle button at bottom using `sa-icon-chevron-left/right`
- `onToggle()` calls `appStore.toggleSidebar()`

**OnboardingGateComponent** (`app-onboarding-gate`) — First-run overlay:
- Reads `settingsStore.onboardingCompleted()` — shows overlay when `false`
- Lazily loads `OnboardingWizard` from settings-remote via `RemoteLoaderService`
- Shows loading spinner while wizard remote fetches
- Full-screen `z-50` overlay using `fixed inset-0`

**UpdateCheckerComponent** (`app-update-checker`) — Tauri auto-updater:
- Only activates when `tauriDetection.isTauri()` is `true`
- Dynamically loads `@tauri-apps/plugin-updater` via `Function()` constructor (bypasses missing-module TS error)
- Shows fixed bottom-right banner with "Install" button when update available
- Stores updater ref for `downloadAndInstall()` call

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] port-resolver.ts: invoke<number> TypeScript error**
- **Found during:** Task 1 first build
- **Issue:** `await invoke<number>('start_sidecar')` from dynamic import was flagged as `TS2347: Untyped function calls may not accept type arguments` because the dynamic import loses generic type information
- **Fix:** Replaced with typed module cast pattern: `const tauriCore = await import(...) as { invoke: (cmd: string) => Promise<unknown> }` + explicit `as number` cast
- **Files modified:** `libs/shared/tauri/src/port-resolver.ts`
- **Commit:** 3159f2c

**2. [Rule 3 - Blocking] app.component.ts: AppComponent did not exist at bootstrap import**
- **Found during:** Task 1 first build
- **Issue:** `bootstrap.ts` imports `AppComponent` from `./app/app.component` but only `App` existed (the Nx scaffold default). Angular errors with `TS2307: Cannot find module`
- **Fix:** Created minimal placeholder `AppComponent` in Task 1 commit, replaced with full implementation in Task 2
- **Files modified:** `apps/shell/src/app/app.component.ts`
- **Commit:** 3159f2c (placeholder), 7f522d8 (full implementation)

**3. [Rule 1 - Bug] sidebar-shell.component.ts: wrong icon selectors**
- **Found during:** Task 2 first build
- **Issue:** Used `sa-chevron-right-icon` / `sa-chevron-left-icon` selectors but actual selectors from shared-ui icons are `sa-icon-chevron-right` / `sa-icon-chevron-left`
- **Fix:** Updated template to use correct selectors `sa-icon-chevron-right` and `sa-icon-chevron-left`
- **Files modified:** `apps/shell/src/app/sidebar-shell/sidebar-shell.component.ts`
- **Commit:** 7f522d8

**4. [Rule 1 - Bug] app.component.ts / onboarding-gate: invalid `<ng-component-outlet>` element**
- **Found during:** Task 2 build verification (did not cause TS error but is wrong usage)
- **Issue:** Used `<ng-component-outlet [ngComponentOutlet]="..." />` but NgComponentOutlet is a directive applied to `<ng-container>`, not its own element
- **Fix:** Changed to `<ng-container [ngComponentOutlet]="..." [ngComponentOutletInjector]="..." />`
- **Files modified:** `apps/shell/src/app/app.component.ts`, `apps/shell/src/app/onboarding-gate/onboarding-gate.component.ts`
- **Commit:** 7f522d8

**5. [Rule 1 - Bug] update-checker: (import as ...) TypeScript syntax error**
- **Found during:** Task 2 first build
- **Issue:** `(import as (path: string) => Promise<any>)(...)` is invalid TypeScript syntax — `import` is a keyword, not a value that can be cast
- **Fix:** Used `new Function('modulePath', 'return import(modulePath)')` pattern to bypass TS static analysis for the unavailable `@tauri-apps/plugin-updater` package
- **Files modified:** `apps/shell/src/app/update-checker/update-checker.component.ts`
- **Commit:** 7f522d8

**6. [Rule 1 - Bug] brand-icons/index.ts: pre-existing unused NgClass import**
- **Found during:** Task 2 build (warning from Plan 03 persisted)
- **Issue:** `NG8113: All imports are unused` — `NgClass` imported but template uses `[attr.class]` attribute binding, not `ngClass` directive
- **Fix:** Removed `NgClass` from imports and deleted the `import { NgClass }` statement
- **Files modified:** `libs/shared/ui/src/components/brand-icons/index.ts`
- **Commit:** 7f522d8

**7. [Rule 2 - Missing] jest.config.ts not applicable — workspace uses vitest**
- **Found during:** Task 1 setup
- **Issue:** Plan specified `jest.config.ts` with jest-preset-angular, but workspace uses `@angular/build:unit-test` with vitest runner (not jest). Creating a jest.config.ts would be unused and confusing.
- **Fix:** Deleted the mistakenly-created jest.config.ts; created `setup-jest.ts` as a conventional test setup entry point with clear comment about vitest runner
- **Files modified:** Deleted `jest.config.ts`, created `src/setup-jest.ts`
- **Commit:** 3159f2c

## Self-Check: PASSED

All created files verified present:
- `apps/shell/src/app/remote-loader.service.ts` — FOUND
- `apps/shell/src/app/header/header.component.ts` — FOUND
- `apps/shell/src/app/sidebar-shell/sidebar-shell.component.ts` — FOUND
- `apps/shell/src/app/onboarding-gate/onboarding-gate.component.ts` — FOUND
- `apps/shell/src/app/update-checker/update-checker.component.ts` — FOUND
- `apps/shell/src/setup-jest.ts` — FOUND

Both task commits verified in git log:
- `3159f2c` — feat(09-04): build shell bootstrap, app config, and remote loader service
- `7f522d8` — feat(09-04): build shell layout components (AppComponent, Header, SidebarShell, OnboardingGate, UpdateChecker)

Shell build: PASSED (`nx build shell` succeeds — Application bundle generation complete)

Verification criteria:
- [x] Shell builds: `nx build shell` passes
- [x] Shell renders layout scaffold (header, sidebar, main, flyout slot) — AppComponent template
- [x] RemoteLoaderService wired for all 4 remotes (chat, sidebar, settings, domain)
- [x] API_BASE_URL provided at bootstrap with Tauri port resolution
- [x] OnboardingGate reads settingsStore.onboardingCompleted()
- [x] Header has interactive shipping toggle bound to conversationStore.interactiveShipping()
