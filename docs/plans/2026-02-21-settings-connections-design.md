# Settings Connections Design — UPS & Shopify Provider Management

**Date:** 2026-02-21
**Status:** Approved (Rev 5 — final pre-implementation)
**Approach:** Thin DB Layer (Approach A)

## Preflight Decisions (finalized before coding)

| Decision | Resolution |
|----------|------------|
| Scope model | Single-user local desktop app. No `user_id` or `workspace_id` scoping. If multi-user/hosted deployment becomes a requirement, add `owner_id` + scoped queries in a future phase. |
| Key source precedence | `SHIPAGENT_CREDENTIAL_KEY` (base64 env) → `SHIPAGENT_CREDENTIAL_KEY_FILE` (explicit path) → platformdirs local file |
| Resolver status policy | Skip `disconnected` and `needs_reconnect`. Allow `configured` and `error`. Document reasoning below. |
| Runtime propagation contract | `src/services/runtime_credentials.py` — single adapter module. All call sites use `resolve_ups_credentials()` / `resolve_shopify_credentials()`. No ad hoc env reads. |
| Migration policy | Idempotent `CREATE TABLE IF NOT EXISTS` + `PRAGMA table_info` column introspection + `CREATE INDEX IF NOT EXISTS`. Same pattern as existing `_ensure_columns_exist()`. |

## Scope

This is **Phase 1 foundation**: persistent encrypted credential storage + Settings UI + credential resolver + **runtime integration** (UPS MCP and Shopify data source clients read from DB-stored credentials instead of env vars). It does NOT implement UPS OAuth loopback or Shopify guided wizard flows — those are Phase 2.

**This app runs locally on users' machines.** It is not a multi-tenant web application. There is no `user_id` or `workspace_id` scoping. The encryption key file lives in the user's app-data directory. If multi-user/hosted deployment becomes a requirement in the future, add `owner_id` column to `ProviderConnection`, update uniqueness constraint to `UNIQUE(owner_id, connection_key)`, include `owner_id` in AAD string, and scope all service queries.

## Objective

Deliver a Settings-based UI for connecting UPS and Shopify providers with persistent encrypted credential storage, replacing the current `.env`-only and process-memory patterns. Users open the Settings flyout and configure both providers through guided forms with immediate validation feedback. Once saved, runtime systems (agent MCP config, batch executor, gateway provider, Shopify tools) automatically use DB-stored credentials with `.env` fallback.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Secret storage | Encrypted DB (AES-256-GCM) | App runs as local server, not native desktop — no OS keychain APIs. Cross-platform. No new OS dependencies. |
| Key storage location | User app-data directory (`platformdirs`) with env var override | Not project root — survives app updates, per-user, not shared. Env var override enables testing and edge cases. |
| UPS auth flow | Settings credential form (Phase 1) | OAuth loopback is significant effort; UPS MCP already handles client-credentials auth. Ship fast, upgrade later. |
| Shopify flow | Both legacy token + client credentials | Covers existing merchants (legacy) and new setups (Dev Dashboard). Auto-detect via radio selector. |
| UI location | New accordion section in SettingsFlyout | Centralizes all provider management. Keeps existing flyout pattern. |
| Shopify migration | Move credentials to Settings, keep data source switch | DataSourcePanel keeps "Switch to Shopify" but checks Settings for connection first. |
| Credential delivery | In-memory resolver via `runtime_credentials.py` (no `os.environ` injection) | Single adapter module. Avoids global mutable state, child process leaks, and multi-connection clobber. |
| Connection identity | `connection_key` (non-null, unique) | Deterministic identity for multi-profile support (e.g., `ups:test`, `shopify:mystore.myshopify.com`). |
| Phase 1 UI scope | UPS: two subprofiles (test/prod) in one card. Shopify: single store only. | Backend supports multiple, UI limits to simplest Phase 1 experience. |
| Route naming | `POST /{provider}/save` (not `/connect`) | "Save" is honest about Phase 1 semantics — persists credentials without live validation. `/connect` reserved for Phase 2 live flows. |
| Runtime integration | DB-stored creds used at all call sites via shared adapter with env fallback | Ensures saved credentials are actually used for shipping/data operations, not just stored. |

## Section 1: Data Model & Encryption

### `ProviderConnection` Table (new in `src/db/models.py`)

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | `generate_uuid` default |
| `connection_key` | String(255), unique, non-null | Stable identity: `ups:test`, `ups:production`, `shopify:<domain>` |
| `provider` | String(20) | `"ups"` or `"shopify"` |
| `display_name` | String(255) | e.g., "UPS Production" or "My Shopify Store" |
| `auth_mode` | String(50) | `"client_credentials"`, `"legacy_token"`, `"client_credentials_shopify"` |
| `environment` | String(20), nullable | `"test"` or `"production"` — UPS only (required for UPS, null for Shopify) |
| `status` | String(20) | `"configured"`, `"validating"`, `"connected"`, `"disconnected"`, `"error"`, `"needs_reconnect"` |
| `encrypted_credentials` | Text | AES-256-GCM versioned envelope (see below) |
| `metadata_json` | Text | Non-secret metadata (store_name, scopes, account_number) |
| `last_validated_at` | String(50), nullable | ISO8601 |
| `last_error_code` | String(50), nullable | Structured error code (e.g., `AUTH_FAILED`, `SCOPE_MISSING`) |
| `error_message` | Text, nullable | Human-readable error for diagnostics |
| `schema_version` | Integer, default 1 | For future model migrations |
| `key_version` | Integer, default 1 | For future key rotation support |
| `created_at` | String(50) | ISO8601 |
| `updated_at` | String(50) | ISO8601 |

**Unique constraint:** `connection_key` (not `(provider, environment)` — avoids SQLite NULL uniqueness issues).

### Connection Key Convention

| Provider | Key Format | Examples |
|----------|-----------|----------|
| UPS | `ups:{environment}` | `ups:test`, `ups:production` |
| Shopify | `shopify:{normalized_domain}` | `shopify:mystore.myshopify.com` |

**Domain normalization (Shopify):** `store_domain` is normalized server-side before key generation: lowercased, trimmed, protocol stripped (`https://`), trailing slashes removed, validated against `*.myshopify.com`. Malformed domains are rejected with 400.

**Environment validation (UPS):** `environment` is required for UPS and must be exactly `"test"` or `"production"`. Missing or invalid values are rejected with 400 — no silent defaults.

### Connection Status Model

| Status | Meaning | Transition From |
|--------|---------|----------------|
| `configured` | Credentials saved, not yet validated | (initial), error, needs_reconnect, disconnected (via re-save) |
| `validating` | Live validation in progress (Phase 2) | configured, error |
| `connected` | Validated against live provider API (Phase 2) | validating |
| `disconnected` | User-initiated disconnect, credentials preserved | connected, configured |
| `error` | Validation or connection failed | validating, connected |
| `needs_reconnect` | Decryption failed on startup | configured, connected |

**Status transition rules:**

| Action | Status Change | Notes |
|--------|--------------|-------|
| `save_connection()` (new) | → `configured` | Initial save |
| `save_connection()` (overwrite) | → `configured` | Re-save always resets to `configured`, even from `disconnected` |
| `disconnect()` | → `disconnected` | Credentials preserved |
| `check_all()` decrypt success | `needs_reconnect` → `configured` | Recovery. All other statuses preserved. |
| `check_all()` decrypt failure | → `needs_reconnect` | Marks unreadable credentials |
| Phase 2 `/test` success | `configured` → `connected` | Live validation |
| Phase 2 `/test` failure | → `error` | Live validation failure |

**Phase 1 note:** In Phase 1, credentials are saved as `"configured"`. The `"connected"` status is only set when live validation confirms the credentials work against the provider API (Phase 2). `check_all()` on startup does NOT mark rows as `"connected"` — it only runs a decryptability check and marks failures as `"needs_reconnect"`. Successful decryption preserves the row's existing status, **except** if the current status is `"needs_reconnect"` — in that case, it recovers to `"configured"` (the key issue was decryption, which is now resolved).

### `disconnected` Status Semantics

`disconnected` means the user intentionally disabled usage of this provider connection. It is an **operational disable**, not just a visual state:

- User clicks "Disconnect" → status becomes `disconnected`
- Credentials are preserved in DB (not wiped)
- The connection is **not available** for runtime use
- Credential resolvers (`resolve_ups_credentials`, `resolve_shopify_credentials`) skip rows with `disconnected` status
- DataSourcePanel does NOT show `disconnected` Shopify connections as available sources
- To re-enable: user re-saves credentials (resets to `configured`), or Phase 2 adds a "Reconnect" action

### Resolver Skip-Status Policy

Credential resolvers skip rows where the credentials are unusable or intentionally disabled:

| Status | Resolver returns? | Rationale |
|--------|-------------------|-----------|
| `configured` | Yes | Saved but not yet validated — best available in Phase 1 |
| `connected` | Yes | Validated (Phase 2) |
| `validating` | Yes | In-flight validation, credentials are still usable |
| `disconnected` | **No — skip** | User intentionally disabled |
| `needs_reconnect` | **No — skip** | Decryption may fail; would generate noise + repeated errors |
| `error` | Yes | Credentials may be temporarily invalid (transient API outage). Phase 2 may separate `auth_error` (skip) from `network_error` (retry). |

**Phase 1 rationale for keeping `error` usable:** In Phase 1, `error` status is never set (no live validation). It exists for Phase 2 forward compatibility. When Phase 2 introduces live validation, it may distinguish `auth_error` (bad credentials — skip) from `network_error` (transient — keep usable). For now, keeping `error` usable is the safer default.

### Encryption Scheme

- **Algorithm:** AES-256-GCM (authenticated encryption)
- **Key source precedence:**
  1. `SHIPAGENT_CREDENTIAL_KEY` env var (base64-encoded 32-byte key) — for testing and containerized deployments
  2. `SHIPAGENT_CREDENTIAL_KEY_FILE` env var (absolute path to raw key file) — for explicit key management
  3. platformdirs local file (auto-generated) — default for local desktop use
     - macOS: `~/Library/Application Support/shipagent/.shipagent_key`
     - Linux: `~/.local/share/shipagent/.shipagent_key`
     - Windows: `C:\Users\<user>\AppData\Local\shipagent\.shipagent_key`
- **Auto-generated:** on first app startup via `os.urandom(32)` if no key source is configured
- **Permissions:** `0o600` on Unix (platform-aware — skipped on Windows)
- **Per-record IV:** fresh 12-byte nonce per encrypt, stored in envelope
- **Format (versioned envelope):** `{"v":1, "alg":"AES-256-GCM", "nonce":"<b64>", "ct":"<b64>"}` → JSON → stored in `encrypted_credentials`
- **Canonical serialization:** `json.dumps(credentials, sort_keys=True)` before encryption for deterministic ciphertext structure
- **AAD (Additional Authenticated Data):** `provider:auth_mode:connection_key` — binds ciphertext to its record
- **AAD construction:** Centralized in `ConnectionService._build_aad(row)` — single function, not scattered across call sites
- **Algorithm validation:** Decrypt rejects envelopes where `alg` is not `"AES-256-GCM"`
- **Payload validation:** Decrypt verifies the decrypted payload is a `dict` (not a list or scalar)
- **Implementation:** `src/services/credential_encryption.py` using Python `cryptography` library + `platformdirs`

### Threat Model (Phase 1)

Phase 1 provides **app-local at-rest encryption**: credentials are encrypted in the DB using a key stored on the local filesystem (or provided via env var). This protects against:

- DB-only leakage (e.g., backup exposure, SQLite file shared without key)

It does **not** protect against:

- Host compromise / same-user filesystem access (attacker with access to both DB file and key file can decrypt)

Future hardening options (Phase 2+):
- macOS Keychain integration
- Windows DPAPI
- libsecret / GNOME Keyring
- KMS for hosted deployments

### Encrypted vs. Plaintext Fields (per provider)

| Provider | Encrypted | Metadata (plaintext JSON) |
|----------|-----------|---------------------------|
| UPS | `client_id`, `client_secret` | `account_number`, `environment`, `base_url` |
| Shopify (legacy) | `access_token` | `store_domain`, `store_name`, `scopes`, `api_version` |
| Shopify (client_credentials) | `client_id`, `client_secret` | `store_domain`, `store_name`, `scopes`, `api_version` |

**Shopify `client_credentials_shopify` credential contract (Phase 1):** In Phase 1, only `client_id` and `client_secret` are stored. The `access_token` is **not required** — it will be obtained via the client-credentials grant flow in Phase 2. The `ShopifyClientCredentials` dataclass has `access_token` as an optional field (empty string default). This avoids half-baked token handling and keeps Phase 1 clean.

## Section 2: Backend Service Layer & API Routes

### Secret Redaction Utility (`src/utils/redaction.py`)

A centralized redaction helper prevents credential leakage in logs and error responses:

```python
def redact_for_logging(obj: dict, sensitive_keys: frozenset[str] = ...) -> dict:
    """Redact sensitive values from a dict for safe logging/error responses."""
```

Used in:
- API exception logging (connection routes)
- Startup check warning logs
- Runtime resolver fallback warnings
- Error response bodies (500s)

Default sensitive keys: `{"client_id", "client_secret", "access_token", "refresh_token", "password"}`.

### `ConnectionService` (`src/services/connection_service.py`)

```python
class ConnectionService:
    # CRUD
    def list_connections() -> list[ProviderConnectionResponse]  # ordered by provider, connection_key
    def get_connection(connection_key) -> ProviderConnectionResponse | None
    def save_connection(provider, auth_mode, credentials, metadata, ...) -> ProviderConnectionResponse  # includes is_new flag
    def delete_connection(connection_key) -> bool

    # Lifecycle
    def disconnect(connection_key) -> bool  # sets "disconnected", preserves creds
    def update_status(connection_key, status, ...) -> bool  # for error/recovery transitions

    # Credential Resolver (replaces os.environ injection)
    def get_ups_credentials(environment) -> UPSCredentials | None
    def get_shopify_credentials(store_domain) -> ShopifyLegacyCredentials | ShopifyClientCredentials | None

    # Startup
    def check_all() -> dict[str, str]  # decryptability scan only

    # Internal
    def _build_aad(row: ProviderConnection) -> str  # centralized AAD construction
```

**Key behaviors:**

- `save_connection()` — validates input, normalizes domain, encrypts and persists credentials. Sets status to `"configured"` (even on overwrite of a `"disconnected"` row — re-save is a reconnect). Returns `is_new: bool` flag to distinguish create vs. overwrite. Does NOT validate against live API.
- `disconnect()` — sets status to `"disconnected"`, preserves encrypted credentials.
- `delete_connection()` — disconnects AND wipes credentials from DB.
- `get_ups_credentials(environment)` — typed credential resolver. Decrypts on demand. Skips `disconnected` and `needs_reconnect` rows. Returns `UPSCredentials | None`.
- `get_shopify_credentials(store_domain)` — typed credential resolver. Input domain is normalized before lookup. Skips `disconnected` and `needs_reconnect` rows. Returns `ShopifyLegacyCredentials | ShopifyClientCredentials | None` depending on `auth_mode`.
- `check_all()` — called during FastAPI lifespan startup. Runs a decryptability scan on all rows. On success: if status is `"needs_reconnect"` recovers it to `"configured"` and clears error fields; all other statuses preserved. On decrypt failure: sets `"needs_reconnect"` + `last_error_code = "DECRYPT_FAILED"`. Does NOT promote any row to `"connected"`. Does NOT write to `os.environ`. Does NOT populate any in-memory cache.
- `_build_aad(row)` — constructs AAD string as `f"{row.provider}:{row.auth_mode}:{row.connection_key}"`. Single function, consistent across all encrypt/decrypt operations.

### Credential Resolver (replaces `os.environ` injection)

Instead of injecting secrets into `os.environ` on startup, the `ConnectionService` provides typed credential objects:

```python
@dataclass
class UPSCredentials:
    client_id: str
    client_secret: str
    account_number: str
    environment: str  # "test" or "production"
    base_url: str

@dataclass
class ShopifyLegacyCredentials:
    access_token: str
    store_domain: str

@dataclass
class ShopifyClientCredentials:
    client_id: str
    client_secret: str
    access_token: str  # empty string if not yet acquired (Phase 2 obtains this)
    store_domain: str
```

**Shopify resolver is not ambiguous.** `get_shopify_credentials(store_domain)` requires an explicit store domain — no "first row found" nondeterminism. Input domain is normalized before DB lookup. Returns the appropriate typed dataclass based on `auth_mode`.

### Runtime Credential Adapter (`src/services/runtime_credentials.py`)

**This is the single contract for runtime credential resolution.** All call sites use this module instead of ad hoc `os.environ` reads or direct `ConnectionService` calls. This ensures:

- Consistent resolution logic (DB → env fallback)
- Consistent logging (warn on fallback, with redacted context)
- Consistent skip-status enforcement
- Single place to add caching, metrics, or multi-tenant scoping later

```python
def resolve_ups_credentials(
    environment: str | None = None,
) -> UPSCredentials | None:
    """Resolve UPS credentials: DB-stored (priority) → env var (fallback).

    Args:
        environment: "test" or "production". Defaults to env var UPS_ENVIRONMENT or "test".

    Returns:
        UPSCredentials if available, None if neither DB nor env configured.

    Logs:
        WARNING (once) if falling back to env vars.
        WARNING if neither source available.
    """

def resolve_shopify_credentials(
    store_domain: str | None = None,
) -> dict | None:
    """Resolve Shopify credentials: DB-stored (priority) → env var (fallback).

    Args:
        store_domain: Explicit domain. If None, uses first available DB connection
                      (Phase 1 single-store; deterministic via ORDER BY connection_key ASC).

    Returns:
        Dict with 'access_token' and 'store_domain', or None.

    Logs:
        WARNING (once) if falling back to env vars.
        WARNING if neither source available.
    """
```

**Fallback logging policy:** Warnings are logged with safe context (provider, environment/domain, exception class — never raw credentials). Each fallback reason is logged at most once per process lifetime to avoid log noise.

**Shopify default selection (Phase 1):** When no `store_domain` is specified, the resolver picks the first non-skipped Shopify connection ordered by `connection_key ASC`. This is deterministic and temporary — Phase 2 will require explicit store selection in all runtime paths. This behavior is documented in code comments.

### Runtime Resolver Integration (Phase 1 — active use of stored credentials)

Phase 1 does **not** just store credentials — it wires them into the runtime call sites that currently read `.env`. Each call site uses `runtime_credentials.py` adapter functions. The adapter checks DB first, falls back to `os.environ`.

#### UPS Runtime Call Sites (5 locations)

| Call Site | File | Current | Phase 1 Change |
|-----------|------|---------|----------------|
| Agent MCP config | `config.py:get_ups_mcp_config()` | `os.environ.get("UPS_CLIENT_ID")` | Accept optional `UPSCredentials` param, env fallback |
| Agent creation | `client.py:_create_options()` | Calls `create_mcp_servers_config()` | Call `resolve_ups_credentials()` before creating config |
| Batch executor | `batch_executor.py:execute_batch()` | `os.environ.get("UPS_CLIENT_ID")` | Accept optional `UPSCredentials` param, env fallback |
| Gateway provider | `gateway_provider.py:_build_ups_gateway()` | `os.environ.get("UPS_CLIENT_ID")` | Accept optional `UPSCredentials` param, env fallback |
| Pipeline tool | `tools/pipeline.py:ship_command_pipeline()` | `os.environ.get("UPS_ACCOUNT_NUMBER")` | Call `resolve_ups_credentials()`, read `account_number` |
| Interactive tool | `tools/interactive.py` | `os.environ.get("UPS_ACCOUNT_NUMBER")` | Call `resolve_ups_credentials()`, read `account_number` |

**Pattern:** Low-level functions (`get_ups_mcp_config`, `execute_batch`, `_build_ups_gateway`) gain an optional `credentials: UPSCredentials | None = None` parameter. When `None`, existing env var reads are preserved. Callers resolve credentials via `resolve_ups_credentials()` and pass them down. Tool functions (`pipeline.py`, `interactive.py`) call `resolve_ups_credentials()` directly for `account_number`.

**`create_mcp_servers_config()` change:** Accepts optional `UPSCredentials` and passes to `get_ups_mcp_config()`. `OrchestrationAgent._create_options()` calls `resolve_ups_credentials()` before calling `create_mcp_servers_config()`.

#### Shopify Runtime Call Sites (6 locations)

| Call Site | File | Current | Phase 1 Change |
|-----------|------|---------|----------------|
| Connect tool | `tools/data.py:connect_shopify_tool()` | `os.environ.get("SHOPIFY_ACCESS_TOKEN")` | Call `resolve_shopify_credentials()` first |
| Platform status | `tools/data.py:get_platform_status_tool()` | `os.environ.get("SHOPIFY_ACCESS_TOKEN")` | Call `resolve_shopify_credentials()` first |
| System prompt | `system_prompt.py:build_system_prompt()` | `os.environ.get("SHOPIFY_ACCESS_TOKEN")` | Call `resolve_shopify_credentials()` first |
| Batch executor | `batch_executor.py:get_shipper_for_job()` | `os.environ.get("SHOPIFY_ACCESS_TOKEN")` | Call `resolve_shopify_credentials()` first |
| Env status route | `platforms.py:get_shopify_env_status()` | `os.environ.get("SHOPIFY_ACCESS_TOKEN")` | Call `resolve_shopify_credentials()` first |
| CLI paths | `http_client.py`, `runner.py` | `os.environ.get("SHOPIFY_ACCESS_TOKEN")` | Phase 1: env-only (CLI is secondary priority) |

**Pattern:** All Shopify call sites call `resolve_shopify_credentials()` which checks DB first (via `ConnectionService`), falls back to env vars. The resolver returns a simple dict with `access_token` and `store_domain`.

### API Routes (`src/api/routes/connections.py`)

| Method | Path | Purpose | Success | Error |
|--------|------|---------|---------|-------|
| `GET` | `/connections/` | List all saved connections (no secrets) | 200 | — |
| `GET` | `/connections/{connection_key}` | Get single connection details | 200 | 404 |
| `POST` | `/connections/{provider}/save` | Encrypt + persist (no live validation) | 201 (create) / 200 (update) | 400, 422 |
| `POST` | `/connections/{connection_key}/disconnect` | Disconnect, keep credentials | 200 | 404 |
| `DELETE` | `/connections/{connection_key}` | Disconnect + wipe credentials | 200 | 404 |

**Save response codes:** `201 Created` when a new connection is created, `200 OK` when an existing connection is updated (overwritten). The service layer returns an `is_new` flag to distinguish.

**Phase 1 omissions (deferred to Phase 2):**
- `POST /connections/{connection_key}/test` — live credential validation
- `POST /connections/{provider}/connect` — save + validate + connect in one call

**Provider path validation:** `provider` is validated against `Literal["ups", "shopify"]`. Invalid providers return 400.

**Input validation:**

- UPS: `environment` required (`"test"` or `"production"`), `client_id` and `client_secret` non-empty
- Shopify: `store_domain` required, normalized and validated against `*.myshopify.com`, credential fields validated per auth_mode
- Invalid provider → 400, invalid auth_mode → 400, missing required fields → 400
- 500 errors use `redact_for_logging()` — no raw exception strings or credential values

Credentials are **never** returned in any API response.

**Pydantic model validation:** Ensure field validators do not echo submitted secret values in FastAPI default 422 responses. Use `json_schema_extra` or custom error messages if needed.

### Startup Flow

**Current:** FastAPI lifespan → nothing (credentials in `.env`)
**New:** FastAPI lifespan → `ConnectionService.check_all()` → reads DB → verifies each row is decryptable → marks failures as `"needs_reconnect"` → recovers `"needs_reconnect"` rows to `"configured"` on success → clears errors only on `needs_reconnect` recovery

No status promotion to `"connected"`. No env injection. No in-memory cache.

`.env` remains as fallback for backwards compatibility.

### Commit Safety

All `ConnectionService` methods that modify DB wrap commits in try/except with rollback on failure:

```python
try:
    self._db.commit()
except Exception:
    self._db.rollback()
    raise
```

This prevents SQLAlchemy session corruption on IntegrityError or other DB exceptions. Applied to: `save_connection`, `delete_connection`, `disconnect`, `update_status`, `check_all`.

### Migration Strategy

The `provider_connections` table is created and maintained using the same idempotent migration pattern as all other tables in `_ensure_columns_exist()`:

1. `CREATE TABLE IF NOT EXISTS provider_connections (...)` — creates table on fresh installs
2. `PRAGMA table_info(provider_connections)` — introspects existing columns on upgrades
3. `ALTER TABLE provider_connections ADD COLUMN ...` — adds any missing columns idempotently
4. `CREATE INDEX IF NOT EXISTS idx_provider_connections_provider ON provider_connections (provider)` — ensures index exists

This handles:
- Fresh installs (table created)
- Existing installs with older schema (missing columns added)
- Partial upgrades (interrupted migrations completed)
- Repeated startups (all operations idempotent)

No Alembic required — consistent with the existing project migration approach.

## Section 3: Frontend UI

### Component Structure

```
frontend/src/components/settings/
├── SettingsFlyout.tsx          (modified — add ConnectionsSection first)
├── ConnectionsSection.tsx     (new — accordion wrapper with configured/connected count)
├── ProviderCard.tsx           (new — status badge, actions, expandable form)
├── UPSConnectForm.tsx         (new — Client ID, Secret, Account #, Environment toggle)
├── ShopifyConnectForm.tsx     (new — auth mode selector + variant forms)
```

### Phase 1 UI Scope

| Provider | UI Shape | Cardinality |
|----------|----------|-------------|
| UPS | One card with Test/Production environment toggle | Two subprofiles (`ups:test`, `ups:production`) within one card |
| Shopify | One card with auth mode radio selector | Single store only (backend supports multiple, UI enforces one in Phase 1) |

### UPS One-Card / Two-Environment UX Specification

The UPS card contains **two subprofiles** (Test and Production), managed within a single card:

**Card structure:**
- Card header: "UPS" with summary badge showing configuration count (e.g., "0/2", "1/2", "2/2 configured")
- Environment toggle (tab-style): `Test` | `Production` — controls which subprofile's form/state is displayed
- Form area: shows credentials form or saved-state for the selected environment
- Actions: Save, Replace credentials, Disconnect, Remove — all operate on the **currently selected environment's** `connection_key` only

**Behavior rules:**
- User can save **both** Test and Production credentials independently
- Each environment maps to its own `connection_key` (`ups:test`, `ups:production`) and DB row
- Environment toggle switches the form target; it does NOT affect the other environment's data
- If Test exists and Production does not: toggling to Production shows the empty credentials form
- If both exist: toggling switches between their saved states
- "Disconnect" applies to the selected environment only (e.g., disconnects `ups:test`, `ups:production` remains)
- "Remove" (delete) applies to the selected environment only
- Parent card badge: summary of both (e.g., "1/2 configured" = one env saved, other not)
- Status badge per environment: shown as sub-status indicators or derived from toggle state

**Default state:** No environment pre-selected. User must choose Test or Production before saving.

### Provider Card States

| State | Visual | Phase 1 Actions |
|-------|--------|----------------|
| Not configured | Grey badge, form expanded | Save |
| Configured | Blue badge, form collapsed | Edit, Disconnect, Remove |
| Disconnected | Grey badge, form collapsed | Edit, Remove |
| Error / Needs Reconnect | Amber badge, error shown | Edit, Remove |

**Phase 1 omissions:** "Test" and "Validate" buttons are hidden (no live validation endpoint). They appear in Phase 2 when `/test` endpoint ships.

### Credential Display After Save

Credentials are never returned from the API. After save, the form shows:
- Placeholder dots (`••••••••`) — not masked real values
- "Saved" indicator
- "Replace credentials" action to re-expand form

No "masked after save" pattern — the frontend does not know the saved secret values.

### UPS Form Fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| Client ID | text | Yes | From UPS developer portal. Shows `••••••••` after save. |
| Client Secret | password | Yes | From UPS developer portal. Shows `••••••••` after save. |
| Account Number | text | No | Required for pickup/paperless/landed cost |
| Environment | toggle: Test / Production | Yes | Required, no default — user must select |

### Shopify Form Fields

**Auth mode selector** (radio):
- "I have an access token" (legacy) → single token field
- "I have client credentials" (new) → client ID + client secret fields (no access_token field — Phase 2 obtains it)

Both modes require **Store domain** (validated against `*.myshopify.com`, normalized on submit).

### State Management

New in `useAppState`:
- `providerConnections: ProviderConnectionInfo[]` — hydrated on mount
- `providerConnectionsLoading: boolean`
- `refreshProviderConnections(): void` — bumps version counter

**Frontend metadata type:** `Record<string, unknown>` (not `Record<string, string>`) to handle booleans, arrays, and nested data.

### Frontend URL Safety

All `connectionKey` values are passed through `encodeURIComponent()` before interpolation into URL paths in `api.ts`.

### Frontend Error Handling & Loading States

- **Save/Disconnect/Delete buttons:** Show loading spinner during API call, disabled to prevent duplicate submission
- **Save errors:** Inline error message below form (not toast), card stays expanded with form accessible
- **Disconnect/Delete:** Confirmation dialog before delete (destructive action), no confirmation for disconnect (reversible via re-save)
- **Network errors:** Inline error with retry guidance
- **Loading state on mount:** Skeleton placeholder while `providerConnectionsLoading` is true

### DataSourcePanel Migration

- Shopify `configured` or `connected` → show as available data source with switch button (existing behavior)
- Shopify `disconnected`, `error`, `needs_reconnect`, or not configured → show "Connect Shopify in Settings" link that calls `setSettingsFlyoutOpen(true)`
- No credential entry in sidebar anymore

**Rationale:** `disconnected` means the user intentionally disabled the connection, so it should not appear as an available source. Only `configured` (saved, not yet validated) and `connected` (validated, Phase 2) are considered usable.

## Section 4: Validation & Error Handling

### Phase 1 Validation (save-time only)

**UPS:**
1. `environment` required, must be `"test"` or `"production"`
2. `client_id` non-empty
3. `client_secret` non-empty

**Shopify:**
1. `store_domain` required, normalized (lowercase, protocol stripped, validated against `*.myshopify.com`)
2. Legacy mode: `access_token` non-empty
3. Client credentials mode: `client_id` and `client_secret` non-empty (no `access_token` required)

### Phase 2 Validation (live — future)
1. UPS: OAuth token fetch against selected environment
2. Shopify: GraphQL shop query (legacy) or token acquisition (client credentials)
3. Scope checks, DNS resolution

### Error Display
Errors render inline in the ProviderCard — no toasts. Card shows error message with colored indicator and keeps form accessible.

### Error Codes

Structured `last_error_code` values for programmatic handling:

| Code | Meaning |
|------|---------|
| `AUTH_FAILED` | Credentials rejected by provider (Phase 2) |
| `NETWORK_ERROR` | Cannot reach provider API (Phase 2) |
| `SCOPE_MISSING` | Connected but missing required scopes (Phase 2) |
| `DOMAIN_INVALID` | Store domain does not resolve (Phase 2) |
| `TOKEN_EXPIRED` | Token expired and refresh failed (Phase 2) |
| `DECRYPT_FAILED` | Cannot decrypt stored credentials (Phase 1 — startup check) |

### Startup Errors
- Each row checked independently
- Decrypt failure → `status = "needs_reconnect"`, `last_error_code = "DECRYPT_FAILED"`
- Successful decrypt + status is `"needs_reconnect"` → recover to `"configured"`, clear error fields
- Successful decrypt + any other status → preserve status, do NOT clear error fields (they may be from Phase 2 auth errors)
- Errors logged to stderr (redacted), surfaced in Settings UI on next open

## Section 5: API Test Fixture

All API tests that use in-memory SQLite with FastAPI TestClient must use `StaticPool` to avoid per-connection isolation issues:

```python
from sqlalchemy.pool import StaticPool

engine = create_engine(
    "sqlite://",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
```

This ensures all requests in the test share the same in-memory database connection.

## Section 6: File Inventory

### New Files

| File | Purpose |
|------|---------|
| `src/services/credential_encryption.py` | AES-256-GCM encrypt/decrypt + key file management (platformdirs + env var override) |
| `src/services/connection_service.py` | Connection CRUD, credential resolver, startup check, AAD construction |
| `src/services/runtime_credentials.py` | Single adapter for runtime credential resolution (DB → env fallback) |
| `src/utils/redaction.py` | Secret redaction utility for safe logging and error responses |
| `src/api/routes/connections.py` | REST endpoints for `/connections/*` with input validation |
| `frontend/src/components/settings/ConnectionsSection.tsx` | Accordion wrapper |
| `frontend/src/components/settings/ProviderCard.tsx` | Shared card component |
| `frontend/src/components/settings/UPSConnectForm.tsx` | UPS credential form |
| `frontend/src/components/settings/ShopifyConnectForm.tsx` | Shopify form with auth mode selector |
| `tests/services/test_credential_encryption.py` | Encryption tests |
| `tests/services/test_connection_service.py` | Service layer tests |
| `tests/api/test_connections.py` | Route tests |
| `tests/services/test_startup_check.py` | Startup check tests |
| `tests/services/test_runtime_credentials.py` | Runtime resolver adapter tests |
| `tests/integration/test_connection_round_trip.py` | Integration + edge case tests |

### Modified Files

| File | Change |
|------|--------|
| `src/db/models.py` | Add `ProviderConnection` model with `connection_key` |
| `src/db/connection.py` | Add `provider_connections` table migration (CREATE TABLE + PRAGMA introspection + indexes) |
| `src/api/main.py` | Register `/connections` router + `check_all()` in lifespan |
| `src/orchestrator/agent/config.py` | Accept `UPSCredentials` parameter, env var fallback |
| `src/orchestrator/agent/client.py` | Call `resolve_ups_credentials()` before creating MCP config |
| `src/services/batch_executor.py` | Accept `UPSCredentials` parameter in `execute_batch()`, use `resolve_shopify_credentials()` |
| `src/services/gateway_provider.py` | Accept `UPSCredentials` parameter in `_build_ups_gateway()` |
| `src/orchestrator/agent/tools/data.py` | Use `resolve_shopify_credentials()` in `connect_shopify_tool()` and `get_platform_status_tool()` |
| `src/orchestrator/agent/tools/pipeline.py` | Call `resolve_ups_credentials()` for `account_number` |
| `src/orchestrator/agent/tools/interactive.py` | Call `resolve_ups_credentials()` for `account_number` |
| `src/orchestrator/agent/system_prompt.py` | Use `resolve_shopify_credentials()` for Shopify config detection |
| `src/api/routes/platforms.py` | Use `resolve_shopify_credentials()` for Shopify env-status |
| `frontend/src/components/settings/SettingsFlyout.tsx` | Add `ConnectionsSection` as first accordion |
| `frontend/src/hooks/useAppState.tsx` | Add connections state + refresh |
| `frontend/src/lib/api.ts` | Add connection API functions (with `encodeURIComponent`) |
| `frontend/src/types/api.ts` | Add connection types (metadata as `Record<string, unknown>`) |
| `frontend/src/components/sidebar/DataSourcePanel.tsx` | Replace Shopify form with Settings link |
| `.gitignore` | Add `.shipagent_key` |
| `pyproject.toml` | Add `cryptography`, `platformdirs` dependencies |

### What Does NOT Change

- MCP architecture (stdio, gateway singletons)
- Agent tool system (tool definitions, hook system)
- Batch engine / UPSMCPClient core logic
- Platform routes (`/platforms/*`) — still used for order operations
- Existing test suites
- CLI paths (env-only for now — secondary priority)

## Migration Path

**Phase 1 (this implementation):**
- New table auto-created by SQLAlchemy on startup, with column introspection for upgrades
- Encryption key auto-generated in app-data dir (or loaded from env var)
- `.env` vars work as fallback — no breaking changes
- DB takes precedence once user saves through Settings
- `runtime_credentials.py` adapter provides single resolution path for all call sites
- Status is `"configured"` after save — `"connected"` only set by live validation (Phase 2)
- Startup runs decryptability check only (no live validation, no env injection)
- `disconnected` and `needs_reconnect` means operationally disabled — not available for use
- Re-saving on a `disconnected` row resets to `configured`

**Phase 2 (future):**
- UPS OAuth Authorization Code + PKCE loopback flow
- Shopify guided wizard with step-by-step instructions
- Shopify client-credentials token acquisition + auto-refresh scheduler
- `POST /connections/{provider}/connect` — save + validate + connect
- `POST /connections/{connection_key}/test` — live credential test
- "Test" button in UI
- Connection health dashboard
- Key rotation support (leverages `key_version` column)
- Multi-store Shopify UI (with explicit store selection in runtime paths)
- OS keychain / KMS integration options
- Explicit store selection required in all Shopify runtime paths (replace Phase 1 first-available default)
- Error status sub-classification (`auth_error` vs `network_error`)
