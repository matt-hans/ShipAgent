---
phase: 09-angular-module-federation-frontend-rebuild
plan: 02
subsystem: shared-infrastructure
tags: [angular, types, api-service, tauri, testing, rxjs, httpclient]
dependency_graph:
  requires: [09-01-PLAN]
  provides: [shared-types, shared-api, shared-tauri, testing]
  affects: [all-remotes, shell-app]
tech_stack:
  added: [Angular HttpClient, RxJS Observables, InjectionToken<Signal<string>>]
  patterns: [barrel-exports, jasmine-spy-objects, fixture-factories]
key_files:
  created:
    - shipagent-frontend/libs/shared/types/src/api.types.ts
    - shipagent-frontend/libs/shared/types/src/conversation.types.ts
    - shipagent-frontend/libs/shared/types/src/job.types.ts
    - shipagent-frontend/libs/shared/types/src/settings.types.ts
    - shipagent-frontend/libs/shared/types/src/platform.types.ts
    - shipagent-frontend/libs/shared/types/src/contact.types.ts
    - shipagent-frontend/libs/shared/types/src/command.types.ts
    - shipagent-frontend/libs/shared/types/src/data-source.types.ts
    - shipagent-frontend/libs/shared/types/src/domain-cards.types.ts
    - shipagent-frontend/libs/shared/types/src/connection.types.ts
    - shipagent-frontend/libs/shared/api/src/api.service.ts
    - shipagent-frontend/libs/shared/api/src/api-url.token.ts
    - shipagent-frontend/libs/shared/api/src/api.interceptors.ts
    - shipagent-frontend/libs/shared/api/src/api.models.ts
    - shipagent-frontend/libs/shared/tauri/src/tauri-detection.service.ts
    - shipagent-frontend/libs/shared/tauri/src/port-resolver.ts
    - shipagent-frontend/libs/testing/src/mocks/api.service.mock.ts
    - shipagent-frontend/libs/testing/src/mocks/sse.service.mock.ts
    - shipagent-frontend/libs/testing/src/mocks/store.mocks.ts
    - shipagent-frontend/libs/testing/src/mocks/tauri.mock.ts
    - shipagent-frontend/libs/testing/src/fixtures/job.fixtures.ts
    - shipagent-frontend/libs/testing/src/fixtures/conversation.fixtures.ts
    - shipagent-frontend/libs/testing/src/fixtures/settings.fixtures.ts
    - shipagent-frontend/libs/testing/src/fixtures/platform.fixtures.ts
    - shipagent-frontend/libs/testing/src/utils/test-host.component.ts
  modified:
    - shipagent-frontend/libs/shared/types/src/index.ts
    - shipagent-frontend/libs/shared/api/src/index.ts
    - shipagent-frontend/libs/shared/tauri/src/index.ts
    - shipagent-frontend/libs/testing/src/index.ts
decisions:
  - key: Signal-based InjectionToken for API base URL
    value: InjectionToken<Signal<string>> allows reactive URL updates when Tauri sidecar port changes
  - key: Domain-organized type files
    value: Split monolithic api.ts into 10 focused files for maintainability and tree-shaking
  - key: Jasmine spy factories for mocks
    value: createMockApiService() returns pre-built spy objects — no need for manual jasmine.createSpyObj in each test
  - key: Fixture factories as functions (not constants)
    value: Factory functions prevent accidental state sharing between tests
metrics:
  duration_seconds: 505
  completed: 2026-03-24T21:08:17Z
  tasks_completed: 2
  files_created: 25
  files_modified: 4
---

# Phase 9 Plan 02: Shared Infrastructure — Types, API, Tauri, Testing Summary

**One-liner:** Angular shared libraries porting all React types to domain files, Angular HttpClient API service with 62 endpoints, Signal-based InjectionToken for Tauri-safe URL injection, and a testing library with jasmine spy mocks and fixture factories.

## What Was Built

### Task 1: Shared Types Library + Tauri Utilities

**shared-types** (`@shipagent/shared-types`): All TypeScript interfaces from the React frontend were ported into 10 domain-organized files, replacing the incorrect placeholder types from plan 09-01:

- `api.types.ts` — ErrorResponse, PaginatedResponse, AuditLogEntry
- `job.types.ts` — Job, JobRow, BatchPreview, PreviewRow, progress/SSE event types, ConfirmResponse
- `conversation.types.ts` — AgentEventType, ChatSessionSummary, PersistedMessage, SessionDetail, WarningPreference, ConversationMessage
- `settings.types.ts` — AppSettings, CredentialStatus, CredentialKey
- `platform.types.ts` — PlatformType, PlatformConnection, all credential types per platform, ShopifyEnvStatus, AmazonEnvStatus
- `contact.types.ts` — Contact, ContactCreate, ContactUpdate, ContactListResponse
- `command.types.ts` — CustomCommand, CommandCreate, CommandUpdate, CommandListResponse
- `data-source.types.ts` — DataSourceType, ColumnMetadata, DataSourceImportRequest/Response, SavedDataSource, UploadDocumentResponse
- `domain-cards.types.ts` — PickupResult, LocationResult, LandedCostResult, PaperlessUploadPrompt, PaperlessResult, TrackingResult, PickupPreview, ContactSavedResult
- `connection.types.ts` — ProviderConnectionInfo, SaveProviderRequest, ValidateConnectionResult, ProviderType, ProviderConnectionStatus, ProviderAuthMode

**shared-tauri** (`@shipagent/shared-tauri`):
- `TauriDetectionService` — Injectable with `isTauri`, `isBundled`, `sidecarPort` signals
- `resolveSidecarPort()` — Async function invoking Tauri 'start_sidecar' command with IANA port validation
- `computeApiBaseUrl()` — Returns Tauri URL (`http://127.0.0.1:{port}/api/v1`) or relative URL (`/api/v1`)

### Task 2: API Service, Error Interceptor, Testing Library

**shared-api** (`@shipagent/shared-api`):

- `API_BASE_URL` — `InjectionToken<Signal<string>>` enabling reactive URL updates and Tauri sidecar port injection
- `ApiService` — 62 methods across 10 endpoint domains:
  - Conversations (10): createConversation, sendMessage, getConversations, getConversationMessages, deleteConversation, deleteAllConversations, renameConversation, exportConversation, saveArtifact, uploadDocument + getStreamUrl (URL)
  - Jobs (9): getJobs, getJob, getJobRows, confirmJob, cancelJob, deleteJob, skipFailedRows, getJobProgress + getJobProgressUrl, getMergedLabelsUrl, getZipLabelsUrl (URLs)
  - Data Sources (4): importDataSource, uploadDataSource, disconnectDataSource, getDataSourceStatus
  - Saved Sources (4): getSavedSources, reconnectSavedSource, deleteSavedSource, bulkDeleteSavedSources
  - Platforms (8): connectPlatform, disconnectPlatform, getPlatformEnvStatus, getPlatformOrders, getPlatformConnections, activateShopify, activateAmazon, testPlatformConnection
  - Connections/Provider (6): listProviderConnections, getProviderConnection, saveProviderCredentials, deleteProviderConnection, validateProviderConnection, disconnectProvider
  - Settings (5): getSettings, patchSettings, putCredential, getCredentialStatus, completeOnboarding
  - Contacts (6): getContacts, getContactByHandle, createContact, updateContact, deleteContact, searchContacts
  - Commands (4): getCommands, createCommand, updateCommand, deleteCommand
- `apiErrorInterceptor` — Maps HttpErrorResponse to typed `ApiError` with nested error body support
- `apiAuthInterceptor` — Adds X-API-Key header when configured
- `API_AUTH_KEY` — Optional InjectionToken for auth key configuration
- `ApiError` — Error class with statusCode and errorResponse fields

**testing** (`@shipagent/testing`):
- `createMockApiService()` — Jasmine spy object with all 62 methods stubbed
- `createMockSseService()` — Controllable Subject for SSE event simulation
- Store state factories for all 8 domains (conversation, job, data-source, settings, contacts, commands, platforms, app)
- `mockTauriEnvironment(port)` — Injects `window.__TAURI__` and `window.__SHIPAGENT_PORT__` with cleanup function
- Fixtures: `jobFixtures`, `conversationFixtures`, `settingsFixtures`, `platformFixtures`
- `TestHostComponent` + `createTestHost()` for content projection testing

## Verification

All four libraries compile without TypeScript errors (`tsc --noEmit`).

Key endpoints verified present:
- `deleteAllConversations` — maps to `POST /conversations/bulk-delete`
- `getJobRows` — maps to `GET /jobs/{id}/rows`
- `getContactByHandle` — maps to `GET /contacts/by-handle/{handle}`
- `uploadDocument` — maps to `POST /conversations/{id}/upload-document`
- `connections` group — all 6 methods mapping to `/connections/` routes
- `API_BASE_URL` — exported InjectionToken

## Deviations from Plan

**1. [Rule 1 - Bug] Replaced incorrect placeholder types from 09-01**
- **Found during:** Task 1 setup
- **Issue:** The index.ts from plan 09-01 had simplified/incorrect types (e.g., JobStatus missing states, BatchPreview with wrong shape, Contact missing fields)
- **Fix:** Replaced the entire index.ts with a barrel re-exporting from domain files
- **Files modified:** `libs/shared/types/src/index.ts`
- **Commit:** 66991ce

## Self-Check: PASSED

All key files exist and both commit hashes are valid in git history.
