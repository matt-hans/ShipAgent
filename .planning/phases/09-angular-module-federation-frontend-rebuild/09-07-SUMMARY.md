---
phase: 09-angular-module-federation-frontend-rebuild
plan: 07
subsystem: settings-remote
tags: [angular, module-federation, settings, onboarding, credential-management, address-book]
dependency_graph:
  requires: ["09-04"]
  provides: ["settings-remote/SettingsFlyoutComponent", "settings-remote/OnboardingWizardComponent"]
  affects: ["shell/OnboardingGateComponent", "shell/SettingsFlyoutLoader"]
tech_stack:
  added: []
  patterns: ["Angular 21 standalone components", "OnPush change detection", "NgRx SignalStore", "inject() function-based DI"]
key_files:
  created:
    - shipagent-frontend/apps/settings-remote/src/app/remote-entry.ts
    - shipagent-frontend/apps/settings-remote/src/app/onboarding-wizard/onboarding-wizard.component.ts
    - shipagent-frontend/apps/settings-remote/src/app/onboarding-wizard/step-anthropic.component.ts
    - shipagent-frontend/apps/settings-remote/src/app/onboarding-wizard/step-ups.component.ts
    - shipagent-frontend/apps/settings-remote/src/app/onboarding-wizard/step-shipper.component.ts
    - shipagent-frontend/apps/settings-remote/src/services/platforms.service.ts
    - shipagent-frontend/apps/settings-remote/src/app/settings-flyout/settings-flyout.component.ts
    - shipagent-frontend/apps/settings-remote/src/app/connections-section/connections-section.component.ts
    - shipagent-frontend/apps/settings-remote/src/app/connections-section/provider-card.component.ts
    - shipagent-frontend/apps/settings-remote/src/app/connections-section/anthropic-key-form.component.ts
    - shipagent-frontend/apps/settings-remote/src/app/connections-section/shopify-connect-form.component.ts
    - shipagent-frontend/apps/settings-remote/src/app/connections-section/amazon-connect-form.component.ts
    - shipagent-frontend/apps/settings-remote/src/app/connections-section/ups-connect-form.component.ts
    - shipagent-frontend/apps/settings-remote/src/app/address-book-section/address-book-section.component.ts
    - shipagent-frontend/apps/settings-remote/src/app/address-book-section/contact-form.component.ts
    - shipagent-frontend/apps/settings-remote/src/app/custom-commands-section/custom-commands-section.component.ts
    - shipagent-frontend/apps/settings-remote/src/app/shipment-behaviour-section/shipment-behaviour-section.component.ts
  modified:
    - shipagent-frontend/apps/settings-remote/src/app/connections-section/provider-card.component.ts
    - shipagent-frontend/apps/settings-remote/src/app/connections-section/ups-connect-form.component.ts
decisions:
  - "PlatformsService is component-scoped (not root) to keep platform connection lifecycle tied to settings-remote"
  - "Connection state uses PlatformsStore for cross-remote visibility of platform status"
  - "Shipper address saved on demand (dirty flag) rather than auto-saving to reduce API calls"
  - "Onboarding completes via apiService.completeOnboarding() then updates SettingsStore.setOnboardingCompleted(true) to dismiss overlay"
metrics:
  duration: 877s
  completed: 2026-03-25
  tasks: 2
  files: 17
---

# Phase 9 Plan 07: Settings Remote Summary

Settings Remote — onboarding wizard (3-step first-run flow), settings flyout (connections, address book, commands, preferences), platform credential forms, and platform management service.

## What Was Built

### Task 1: Onboarding Wizard and Platform Management Service

**OnboardingWizardComponent** (`onboarding-wizard.component.ts`) — Full-screen overlay shown on first launch via the shell's OnboardingGateComponent. Three sequential steps with progress indicator dots.

**Step components:**
- `StepAnthropicComponent`: Anthropic API key input; validates non-empty; calls `apiService.putCredential('ANTHROPIC_API_KEY', value)`. Required step before proceeding.
- `StepUpsComponent`: UPS Client ID + Client Secret + Account Number (optional); saves each via `putCredential()`; skip button goes directly to step 3.
- `StepShipperComponent`: Shipper address form (company, contact, phone, address, city, state, zip, country); pre-populated from `SettingsStore.appSettings()`; saves via `apiService.patchSettings()`.

On wizard completion: calls `apiService.completeOnboarding()`, then updates `SettingsStore.setOnboardingCompleted(true)` to dismiss the shell overlay.

**PlatformsService** (`platforms.service.ts`) — Angular port of `useExternalSources.ts` React hook. Component-scoped injectable (provided in settings-remote `remoteEntry.providers`). Methods: `connectPlatform()`, `disconnectPlatform()`, `testConnection()`, `fetchOrders()`, `checkShopifyEnv()`, `checkAmazonEnv()`, `refreshConnections()`, `saveProviderCredentials()`, `validateProviderConnection()`, `deleteProviderConnection()`, `disconnectProviderConnection()`. All methods update PlatformsStore on success.

**remote-entry.ts** — Exports both `SettingsFlyoutComponent` and `OnboardingWizardComponent` as named exports. `remoteEntry.providers: [PlatformsService]` scopes the service to settings-remote's child injector.

### Task 2: Settings Flyout with All Sections

**SettingsFlyoutComponent** (`settings-flyout.component.ts`) — Slide-in panel from right with backdrop. Four accordion sections controlled by `openSection` signal. Close via `appStore.closeSettings()`. Backdrop click closes. Imports all 4 section components.

**ConnectionsSectionComponent** (`connections-section.component.ts`) — Provider cards for Anthropic, UPS, Shopify, Amazon. Loads credential status and connections on `ngOnInit`. Shows active count badge. UPS cards include environment toggle (Test CIE / Production). Computed signals for filtered connection lists by provider.

**ProviderCardComponent** (`provider-card.component.ts`) — Reusable expandable card with validate/disconnect/delete action buttons per connection. Uses inline SVG icons (no external icon library). Status badges with color-coded CSS classes. Confirm-before-delete flow.

**Credential form components:**
- `AnthropicKeyFormComponent`: Password input, saves via `putCredential('ANTHROPIC_API_KEY', value)`, shows success/error inline.
- `ShopifyConnectFormComponent`: Store domain (validated as `*.myshopify.com`) + admin access token; auto-validates after save.
- `AmazonConnectFormComponent`: LWA Client ID + Secret + Refresh Token + marketplace dropdown + sandbox toggle; auto-validates.
- `UpsConnectFormComponent`: Environment selector (Test/Production) + Client ID + Secret + Account Number; auto-validates, sets active environment on first save.

**AddressBookSectionComponent** (`address-book-section.component.ts`) — Loads contacts on `ngOnInit` into ContactsStore. Search filters by handle/name/city/state. Tag filter chips. Contact list with inline edit/delete (confirm before delete). Form/list toggle within the accordion.

**ContactFormComponent** (`contact-form.component.ts`) — Full contact form with handle auto-slug from display name. Tag chips with add/remove. Fields: handle, display name, company, attention, phone, email, address lines, city, state, postal, country, tags, notes. Emits `submitted` event with ContactCreate/ContactUpdate.

**CustomCommandsSectionComponent** (`custom-commands-section.component.ts`) — Lists slash commands with inline edit mode. Name validation (lowercase + numbers + hyphens). Create new form with dashed border. Commands persist via ApiService, state via CommandsStore.

**ShipmentBehaviourSectionComponent** (`shipment-behaviour-section.component.ts`) — Batch concurrency range slider (1-20) with 400ms debounced save. Agent model dropdown (Haiku 4.5 / Sonnet 4.6 / Opus 4.6) with immediate save. Default shipper address fields with dirty-flag-gated save button.

## Verification

Build: `nx build settings-remote` — passes with only two NG8102 warnings (unnecessary `?? null` — non-breaking).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed unused imports in provider-card.component.ts**
- **Found during:** Task 2 build
- **Issue:** `ContentChild` and `TemplateRef` imported but never used; `NgTemplateOutlet` in imports array but unused. TypeScript strict mode treats these as errors (TS6133).
- **Fix:** Removed `ContentChild`, `TemplateRef`, and `NgTemplateOutlet` from the file.
- **Files modified:** `connections-section/provider-card.component.ts`
- **Commit:** `2402948`

**2. [Rule 1 - Bug] Fixed unused inject in ups-connect-form.component.ts**
- **Found during:** Task 2 build
- **Issue:** `PlatformsService` was injected but never used — the form uses `ApiService` directly. TypeScript strict mode treats this as TS6133 error.
- **Fix:** Removed `PlatformsService` import and inject from `UpsConnectFormComponent`.
- **Files modified:** `connections-section/ups-connect-form.component.ts`
- **Commit:** `2402948`

## Self-Check: PASSED

All 17 key files verified present on disk. Commits bf4ee06 and 2402948 confirmed in git log.
