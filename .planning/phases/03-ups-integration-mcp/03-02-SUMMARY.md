---
phase: 03
plan: 02
subsystem: ups-mcp
tags: [typescript, oauth, http-client, retry-logic, authentication]

dependency-graph:
  requires:
    - 03-01 (TypeScript Package & Schema Foundation)
  provides:
    - OAuth 2.0 token management with caching
    - HTTP client with exponential backoff retry
    - Typed error classes for API failures
  affects:
    - 03-03 (Rating Tools)
    - 03-04 (Shipping Tools)
    - 03-05 (Address Validation)

tech-stack:
  added: []
  patterns:
    - OAuth client_credentials flow with token caching
    - Exponential backoff retry (1s/2s/4s)
    - Fail-fast on 4xx errors
    - UPS transaction headers (transId, transactionSrc)

key-files:
  created:
    - packages/ups-mcp/src/client/errors.ts
    - packages/ups-mcp/src/auth/manager.ts
    - packages/ups-mcp/src/client/api.ts
    - packages/ups-mcp/tests/auth.test.ts
  modified: []

decisions:
  - id: 60-second-token-buffer
    summary: "Token refresh 60 seconds before expiry"
    rationale: "Ensures tokens are never used at exact expiry, providing safe buffer for network latency"
  - id: 4xx-no-retry
    summary: "No retry on 4xx client errors"
    rationale: "Client errors (invalid request, auth failure) won't succeed on retry; fail immediately for faster feedback"
  - id: transaction-headers
    summary: "Include transId and transactionSrc in all requests"
    rationale: "UPS requires these headers for request tracking and debugging"

metrics:
  duration: 5m
  completed: 2026-01-24
---

# Phase 3 Plan 2: OAuth Authentication Summary

**One-liner:** OAuth 2.0 token manager with 60-second refresh buffer and HTTP client with exponential backoff retry on 5xx/network errors.

## What Was Built

### Error Types (`src/client/errors.ts`)

Three typed error classes for error handling:

| Class | Purpose | Properties |
|-------|---------|------------|
| `UpsAuthError` | OAuth authentication failures | message, cause |
| `UpsApiError` | UPS API error responses | statusCode, errorCode, errorMessage, field |
| `UpsNetworkError` | Network/connection failures | message, cause |

Per CONTEXT.md Decision 4: UPS error codes passed through as-is (no translation at MCP layer).

### OAuth Token Manager (`src/auth/manager.ts`)

`UpsAuthManager` class implementing OAuth 2.0 client_credentials flow:

- Acquires tokens from UPS sandbox endpoint (`/security/v1/oauth/token`)
- Uses Basic auth header with base64-encoded credentials
- Caches tokens and reuses until 60 seconds before expiry
- Automatic refresh when token expires or nears expiry
- Clears cache immediately on auth failures

```typescript
const authManager = new UpsAuthManager(clientId, clientSecret);
const token = await authManager.getToken(); // Cached automatically
```

### HTTP Client (`src/client/api.ts`)

`UpsApiClient` class with retry logic:

- Integrates with `UpsAuthManager` for authentication
- Includes required UPS headers: `transId` (UUID) and `transactionSrc`
- Exponential backoff retry: 1s, 2s, 4s delays
- Retries on 5xx server errors and network failures
- Fails immediately on 4xx client errors

```typescript
const client = new UpsApiClient(authManager);
const response = await client.post<ShipmentResponse>(
  '/shipments/v2409/ship',
  { ShipmentRequest: { ... } }
);
```

### Unit Tests (`tests/auth.test.ts`)

11 tests covering:

| Category | Tests |
|----------|-------|
| Token acquisition | New token, cached token, refresh on expiry |
| Token refresh | Within 60s buffer, fully expired |
| Error handling | 401, 403, network errors, cache clearing |
| Token management | clearToken, force refresh |
| Authentication | Base64 credential encoding |

## Key Design Decisions

### 60-Second Token Buffer
Token is refreshed 60 seconds before expiry rather than at exact expiry. This provides:
- Safety margin for network latency
- No risk of using expired tokens
- Matches UPS recommended practice

### No Retry on 4xx Errors
Client errors (400, 401, 403, 404, etc.) fail immediately without retry because:
- These indicate request problems, not transient failures
- Retrying won't fix the issue
- Faster feedback for error handling

### Transaction Headers
Every request includes:
- `transId`: UUID for request tracing
- `transactionSrc`: "shipagent" identifier

UPS uses these for request tracking and debugging in their logs.

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

All verification checks passed:

```
OK: UpsAuthError class exists
OK: UpsApiError class exists
OK: UpsNetworkError class exists
OK: UpsAuthManager class with getToken/refreshToken/clearToken
OK: UpsApiClient class with fetchWithRetry
OK: transId header included
OK: TypeScript compiles
OK: 11 tests pass
```

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 4bf3178 | feat | add typed error classes for UPS API |
| 9a83178 | feat | implement OAuth token manager with tests |
| 2370791 | feat | implement HTTP client with retry logic |

## Next Plan Readiness

Plan 03-03 (Rating Tools) can proceed. This plan provides:
- `UpsAuthManager` for OAuth tokens
- `UpsApiClient` for authenticated API requests with retry
- Error types for proper error handling

**Blockers for next plan:** None

---

*Completed: 2026-01-24 | Duration: 5 minutes*
