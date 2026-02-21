# Settings Connections Design — UPS & Shopify Provider Management

**Date:** 2026-02-21
**Status:** Approved
**Approach:** Thin DB Layer (Approach A)

## Objective

Deliver a Settings-based UI for connecting UPS and Shopify providers with persistent encrypted credential storage, replacing the current `.env`-only and process-memory patterns. Users open the Settings flyout and connect to both providers through guided forms with immediate validation feedback.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Secret storage | Encrypted DB (AES-256-GCM) | App runs as web server, not native desktop — no OS keychain APIs. Cross-platform. No new OS dependencies. |
| UPS auth flow | Settings credential form (Phase 1) | OAuth loopback is significant effort; UPS MCP already handles client-credentials auth. Ship fast, upgrade later. |
| Shopify flow | Both legacy token + client credentials | Covers existing merchants (legacy) and new setups (Dev Dashboard). Auto-detect via radio selector. |
| UI location | New accordion section in SettingsFlyout | Centralizes all provider management. Keeps existing flyout pattern. |
| Shopify migration | Move credentials to Settings, keep data source switch | DataSourcePanel keeps "Switch to Shopify" but checks Settings for connection first. |

## Section 1: Data Model & Encryption

### `ProviderConnection` Table (new in `src/db/models.py`)

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | `generate_uuid` default |
| `provider` | String(20) | `"ups"` or `"shopify"` |
| `display_name` | String(255) | e.g., "UPS Production" or "My Shopify Store" |
| `auth_mode` | String(50) | `"client_credentials"`, `"legacy_token"`, `"client_credentials_shopify"` |
| `environment` | String(20), nullable | `"test"` or `"production"` — UPS only |
| `status` | String(20) | `"connected"`, `"disconnected"`, `"error"`, `"needs_reconnect"` |
| `encrypted_credentials` | Text | AES-256-GCM encrypted JSON blob |
| `metadata_json` | Text | Non-secret metadata (store_name, scopes, account_number) |
| `last_validated_at` | String(50), nullable | ISO8601 |
| `error_message` | Text, nullable | Last error for diagnostics |
| `created_at` | String(50) | ISO8601 |
| `updated_at` | String(50) | ISO8601 |

**Unique constraint:** `(provider, environment)` — one UPS connection per environment, one Shopify connection total.

### Encryption Scheme

- **Algorithm:** AES-256-GCM (authenticated encryption)
- **Key:** 32-byte key stored in `.shipagent_key` (git-ignored, `0600` permissions)
- **Auto-generated:** on first app startup via `os.urandom(32)` if missing
- **Per-record IV:** fresh 12-byte nonce per encrypt, stored as prefix in blob
- **Format:** `nonce (12 bytes) || ciphertext || tag (16 bytes)` → base64 → stored in `encrypted_credentials`
- **Implementation:** `src/services/credential_encryption.py` using Python `cryptography` library

### Encrypted vs. Plaintext Fields (per provider)

| Provider | Encrypted | Metadata (plaintext JSON) |
|----------|-----------|---------------------------|
| UPS | `client_id`, `client_secret` | `account_number`, `environment`, `base_url` |
| Shopify (legacy) | `access_token` | `store_domain`, `store_name`, `scopes`, `api_version` |
| Shopify (client_credentials) | `client_id`, `client_secret`, `access_token` | `store_domain`, `store_name`, `scopes`, `api_version`, `token_expires_at` |

## Section 2: Backend Service Layer & API Routes

### `ConnectionService` (`src/services/connection_service.py`)

```python
class ConnectionService:
    # CRUD
    async def list_connections() -> list[ProviderConnectionResponse]
    async def get_connection(provider, environment=None) -> ProviderConnectionResponse | None
    async def save_connection(provider, auth_mode, credentials, metadata, environment=None) -> ProviderConnectionResponse
    async def delete_connection(provider, environment=None) -> bool

    # Lifecycle
    async def validate_and_connect(provider, auth_mode, credentials, metadata) -> ConnectResult
    async def test_connection(provider, environment=None) -> TestResult
    async def disconnect(provider, environment=None) -> bool

    # Startup
    async def auto_reconnect_all() -> dict[str, str]  # provider -> status
```

**Key behaviors:**

- `validate_and_connect()` — validates credentials against live API, encrypts, persists to DB, connects the live MCP gateway
- `auto_reconnect_all()` — called during FastAPI lifespan startup. Reads DB, decrypts, reconnects each provider. Replaces `.env` bootstrapping.
- `test_connection()` — lightweight read-only API call to verify stored credentials. Updates `last_validated_at`.
- `disconnect()` — tears down live MCP connection, sets status to `"disconnected"`, preserves encrypted credentials
- `delete_connection()` — disconnects AND wipes credentials from DB

### Integration with Existing MCP Architecture

The `ConnectionService` sits above MCP clients, not replacing them:

- **UPS:** writes decrypted credentials into `os.environ` → existing `get_ups_mcp_config()` reads them → `agent_source_hash` detects change → agent rebuilds
- **Shopify:** calls existing `connect_platform()` via `ExternalSourcesMCPClient` with decrypted credentials

### API Routes (`src/api/routes/connections.py`)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/connections/` | List all saved connections (no secrets) |
| `GET` | `/connections/{provider}` | Get single connection details |
| `POST` | `/connections/{provider}/connect` | Validate + encrypt + persist + connect |
| `POST` | `/connections/{provider}/test` | Test stored credentials |
| `POST` | `/connections/{provider}/disconnect` | Disconnect, keep credentials |
| `DELETE` | `/connections/{provider}` | Disconnect + wipe credentials |

**Request body (`POST /connections/{provider}/connect`):**
```json
{
  "auth_mode": "client_credentials",
  "credentials": { "client_id": "...", "client_secret": "..." },
  "metadata": { "account_number": "...", "environment": "test" }
}
```

Credentials are **never** returned in any API response.

### Startup Flow

**Current:** FastAPI lifespan → nothing (credentials in `.env`)
**New:** FastAPI lifespan → `auto_reconnect_all()` → reads DB → decrypts → reconnects

`.env` remains as fallback for backwards compatibility.

## Section 3: Frontend UI

### Component Structure

```
frontend/src/components/settings/
├── SettingsFlyout.tsx          (modified — add ConnectionsSection first)
├── ConnectionsSection.tsx     (new — accordion wrapper with connected count)
├── ProviderCard.tsx           (new — status badge, actions, expandable form)
├── UPSConnectForm.tsx         (new — Client ID, Secret, Account #, Environment)
├── ShopifyConnectForm.tsx     (new — auth mode selector + variant forms)
```

### Provider Card States

| State | Visual | Actions |
|-------|--------|---------|
| Disconnected | Grey badge, form expanded | Connect |
| Connecting | Spinner, form disabled | Cancel |
| Connected | Green badge, form collapsed | Test, Disconnect, Remove, Edit |
| Error / Needs Reconnect | Amber badge, error shown | Reconnect, Edit, Remove |

### UPS Form Fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| Client ID | text (masked) | Yes | From UPS developer portal |
| Client Secret | password | Yes | From UPS developer portal |
| Account Number | text | No | Required for pickup/paperless/landed cost |
| Environment | toggle: Test / Production | Yes | Defaults to Test |

### Shopify Form Fields

**Auth mode selector** (radio):
- "I have an access token" (legacy) → single token field
- "I have client credentials" (new) → client ID + secret fields

Both modes require **Store domain** (validated against `*.myshopify.com`).

### State Management

New in `useAppState`:
- `connections: ConnectionStatus[]` — hydrated on mount
- `connectionsLoading: boolean`
- `refreshConnections(): void` — bumps version counter

### DataSourcePanel Migration

- Shopify connected → show as available data source with switch button
- Shopify not connected → show "Connect Shopify in Settings" link that opens flyout
- No credential entry in sidebar anymore

## Section 4: Validation & Error Handling

### UPS Validation Flow
1. Format check (non-empty fields)
2. Live auth test (OAuth token fetch against selected environment)
3. Account validation (lightweight API call if account number provided)

### Shopify Validation Flow
1. Format check (domain pattern, non-empty credentials)
2. DNS resolution of store domain
3. Live auth test (GraphQL shop query for legacy; token acquisition + shop query for client credentials)
4. Scope check — surface missing scopes as actionable warnings

### Error Display
Errors render inline in the ProviderCard — no toasts. Card shows error message with colored indicator and keeps form accessible.

### Auto-Reconnect Errors (startup)
- Each provider reconnects independently
- Failed providers get `status = "needs_reconnect"`
- Errors logged to stderr, surfaced in Settings UI on next open

### Shopify Token Refresh
- Client-credentials tokens tracked via `token_expires_at` in metadata
- Auto-refresh when within 1 hour of expiry
- Refresh failure → mark "needs_reconnect"

## Section 5: File Inventory

### New Files

| File | Purpose |
|------|---------|
| `src/services/credential_encryption.py` | AES-256-GCM encrypt/decrypt + key file management |
| `src/services/connection_service.py` | Connection CRUD, validate-and-connect, auto-reconnect |
| `src/api/routes/connections.py` | REST endpoints for `/connections/*` |
| `frontend/src/components/settings/ConnectionsSection.tsx` | Accordion wrapper |
| `frontend/src/components/settings/ProviderCard.tsx` | Shared card component |
| `frontend/src/components/settings/UPSConnectForm.tsx` | UPS credential form |
| `frontend/src/components/settings/ShopifyConnectForm.tsx` | Shopify form with auth mode selector |
| `tests/services/test_credential_encryption.py` | Encryption tests |
| `tests/services/test_connection_service.py` | Service layer tests |
| `tests/api/test_connections.py` | Route tests |

### Modified Files

| File | Change |
|------|--------|
| `src/db/models.py` | Add `ProviderConnection` model + `ConnectionStatus` enum |
| `src/api/main.py` | Register `/connections` router + `auto_reconnect_all()` in lifespan |
| `src/orchestrator/agent/config.py` | Read from `ConnectionService` first, env var fallback |
| `frontend/src/components/settings/SettingsFlyout.tsx` | Add `ConnectionsSection` as first accordion |
| `frontend/src/hooks/useAppState.tsx` | Add connections state + refresh |
| `frontend/src/lib/api.ts` | Add connection API functions |
| `frontend/src/types/api.ts` | Add connection types |
| `frontend/src/components/sidebar/DataSourcePanel.tsx` | Replace Shopify form with Settings link |
| `.gitignore` | Add `.shipagent_key` |
| `requirements.txt` / `pyproject.toml` | Add `cryptography` dependency |

### What Does NOT Change

- MCP architecture (stdio, gateway singletons)
- Agent tool system
- Batch engine / UPSMCPClient
- Platform routes (`/platforms/*`) — still used for order operations
- Existing test suites

## Migration Path

**Phase 1 (this implementation):**
- New table auto-created by SQLAlchemy on startup
- `.shipagent_key` auto-generated on first startup
- `.env` vars work as fallback — no breaking changes
- DB takes precedence once user saves through Settings

**Phase 2 (future):**
- UPS OAuth Authorization Code + PKCE loopback flow
- Shopify client-credentials token auto-refresh scheduler
- Connection health dashboard
