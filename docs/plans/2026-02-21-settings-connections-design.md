# Settings Connections Design — UPS & Shopify Provider Management

**Date:** 2026-02-21
**Status:** Approved (Rev 13 — final pre-implementation)
**Approach:** Thin DB Layer (Approach A)

## Preflight Decisions (finalized before coding)

| Decision | Resolution |
|----------|------------|
| Scope model | Single-user local desktop app. No `user_id` or `workspace_id` scoping. If multi-user/hosted deployment becomes a requirement, add `owner_id` + scoped queries in a future phase. |
| Key source precedence | `SHIPAGENT_CREDENTIAL_KEY` (base64 env) → `SHIPAGENT_CREDENTIAL_KEY_FILE` (explicit path) → platformdirs local file |
| Resolver status policy | Skip `disconnected` and `needs_reconnect`. Allow `configured` and `error`. Document reasoning below. |
| Runtime propagation contract | `src/services/runtime_credentials.py` — single adapter module. All call sites use `resolve_ups_credentials()` / `resolve_shopify_credentials()`. No ad hoc env reads. |
| Migration policy | Idempotent `CREATE TABLE IF NOT EXISTS` + `PRAGMA table_info` column introspection + `CREATE UNIQUE INDEX IF NOT EXISTS` for constraint hardening + `CREATE INDEX IF NOT EXISTS`. Same pattern as existing `_ensure_columns_exist()`. |
| Shopify Phase 1 auth modes | `client_credentials_shopify` is **hidden in Phase 1 UI**. Backend type support exists for forward compatibility, but the Shopify form only exposes `legacy_token` mode. Phase 2 enables `client_credentials_shopify` when token acquisition flow is implemented. |
| UPS env fallback contract | When falling back to env vars, the adapter derives environment from the requested `environment` parameter first, then `UPS_ENVIRONMENT` env var, then defaults to `"test"`. `UPS_BASE_URL` is validated for consistency — a mismatch with the resolved environment triggers a warning. |
| 422 redaction strategy | Two layers: (1) Connection routes accept raw `dict` payloads — no Pydantic credential binding. (2) Custom `RequestValidationError` handler for `/connections/*` routes strips raw input values from validation detail, returning sanitized error messages. Both layers are tested. |
| Local desktop threat model | Phase 1 provides app-local at-rest encryption. It does NOT protect against same-user host compromise. Documented explicitly — no overclaiming. |
| Key length enforcement | `encrypt_credentials()` and `decrypt_credentials()` enforce `len(key) == 32`. Prevents silent downgrade to AES-128-GCM or AES-192-GCM from callers passing wrong-length keys. |
| Server-side runtime_usable | Connection API responses include a computed `runtime_usable: bool` field (and optional `runtime_reason`) determined by the backend. Frontend uses this field directly — no client-side inference from `auth_mode`. |
| Redaction depth | `redact_for_logging()` uses case-insensitive substring matching for sensitive key detection, supports recursive container keys, and handles nested dicts + lists of dicts. |
| Error message sanitization | `error_message` values are sanitized and length-capped before DB persistence to prevent secrets leaking through upstream exception messages. |
| platformdirs production warning | Startup logs a WARNING when key source is `platformdirs`. |
| Persistent key enforcement | `SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY=true` → fail startup if key source is `platformdirs`. Prevents `needs_reconnect` storms in ephemeral containers. Default `false` (local desktop). |
| Concurrent key creation race | `get_or_create_key()` handles `FileExistsError` from `O_EXCL` by retrying read of existing file. Safe for multi-worker startup and dev reloads. |
| Key file path validation | `SHIPAGENT_CREDENTIAL_KEY_FILE` must point to an existing, readable regular file that is not a symlink. Missing/unreadable/directory/symlink paths raise `ValueError`. Symlink rejection prevents link-following attacks in shared environments. |
| Env override precedence | When both `SHIPAGENT_CREDENTIAL_KEY` and `SHIPAGENT_CREDENTIAL_KEY_FILE` are set, env key wins (documented and tested). |
| Sanitizer scope | Best-effort regex sanitizer, not a full parser. Covers common formats; uncovered edge cases degrade gracefully (unsanitized but truncated). |
| API sanitization split | Structured payloads → `redact_for_logging()`. Free-text error strings → `sanitize_error_message()`. Complementary, never interchangeable. |
| Phase 1 status semantics | `configured` = stored and decryptable (not validated). `connected` = reserved for Phase 2 live validation. `validating` = reserved. `error` = auth/runtime issue. `needs_reconnect` = decrypt failure. `disconnected` = user-disabled. |
| check_all() disconnected behavior | `check_all()` skips decryptability checks for `disconnected` rows entirely — preserving user-intent status. |
| Model attribute naming | DB column attr is `metadata_json` (avoids SQLAlchemy `Base.metadata` collision). API serializer maps it to `metadata` in responses. |
| key_version Phase 1 scope | `key_version` is persisted but always `1` in Phase 1. No rotation or re-encryption flow exists yet. Phase 2 defines rotation semantics. |
| Env fallback UI behavior | Phase 1: UI shows DB connections only. When env fallback is active (no DB row, env vars present), runtime works but UI shows "Not configured — Connect in Settings". No "env fallback detected" indicator in Phase 1 — transition is silent. Document this behavior in release notes: "If you have UPS/Shopify credentials in .env, they continue to work. Save credentials in Settings to migrate." |
| Sanitizer coverage | `sanitize_error_message()` handles `Authorization: Bearer <token>`, JSON-style `"key":"value"`, quoted values, and multi-token lines in addition to `key=value` pairs. **Best-effort sanitizer** — not a full parser. Covered formats are tested; uncovered formats degrade gracefully (unsanitized but truncated). **Known non-covered formats** (degrade gracefully — unsanitized but truncated): single-quoted JSON-like blobs (e.g., `{'key': 'value'}`), deeply nested stringified payloads, multiline tokens spanning multiple lines, escaped quotes within values. |
| Code review enforcement | Final verification includes code review checklist item: "no new direct env reads for provider creds" (beyond grep). |
| Credential payload allowlists | Each provider/auth_mode combination has an explicit allowlist of required, optional, and rejected credential keys. Unknown keys are rejected with 400 — the request fails. This catches typos early (e.g., client_secert) and is more deterministic than silent dropping. Max field lengths enforced. |
| metadata_json storage strategy | Stored as `TEXT` column with manual `json.loads()` in service layer (not SQLAlchemy JSON type). On parse failure: return `{}` and log non-fatal WARNING (sanitized). Prevents ORM-level deserialization crashes. |
| Migration nullability strategy | All new columns added as `nullable` via `ALTER TABLE ADD COLUMN` (SQLite requirement). Defaults applied at application level. Missing `status` → `"needs_reconnect"`, missing `auth_mode` → `"needs_reconnect"`, missing `encrypted_credentials` → `"needs_reconnect"`. Backfill step runs after column additions. |
| Credential dataclass location | Credential dataclasses (`UPSCredentials`, `ShopifyLegacyCredentials`, `ShopifyClientCredentials`) live in `src/services/connection_types.py` — a neutral module with no DB or service-layer imports. This prevents circular dependencies when `runtime_credentials.py`, `connection_service.py`, and `config.py` all import them. |
| Status validation | `VALID_STATUSES` constant defined alongside other shared constants. `update_status()` validates incoming status against `VALID_STATUSES` and raises `ValueError` on unknown status. Prevents accidental invalid statuses. |
| API error response schema | Connection route errors use a consistent schema: `{"error": {"code": str, "message": str}}`. No raw exception strings. All messages pass through sanitization. |
| Phase 1 status production wording | Phase 1 automated flows only produce `configured` / `needs_reconnect` / `disconnected`. `error` is allowed in Phase 1 via explicit `update_status()` calls (e.g., Phase 2 prep, manual intervention), but is NOT produced by any automated validation or check flow. |
| 422 schema exception | Custom 422 handler wraps sanitized validation detail in the standard error schema: `{"error": {"code": "VALIDATION_ERROR", "message": "Invalid request payload"}, "detail": [...]}`. This preserves both consistency and machine readability. Non-connection routes delegate to FastAPI's default validation error handler (not a re-created response) to avoid altering existing API behavior. |
| Shopify CLI env-read exemption | No runtime server path call site outside `runtime_credentials.py` may directly read provider credential env vars in Phase 1. CLI paths (`http_client.py`, `runner.py`) are temporarily exempt with TODO comments. Grep check in Task 17 excludes these explicitly exempt files. |
| Explicit key misconfig fatality | Invalid explicit key configuration (bad base64, wrong length, missing/unreadable key file) is **fatal at startup** — `ValueError` propagates and stops boot. Only per-row decrypt failures (`check_all()` → `needs_reconnect`) are non-blocking. This prevents the app from booting "successfully" but breaking credential operations later. |
| Timestamp backfill | `created_at` and `updated_at` are backfilled during migration for existing rows (`datetime.now(UTC).isoformat()`). Frontend types remain strict (`string`, not `string \| null`). |
| list/get decrypt resilience | `list_connections()` and `get_connection()` never fail due to credential decrypt errors. On decrypt failure during `runtime_usable` computation: `runtime_usable = false`, `runtime_reason = "decrypt_failed"`, status is NOT mutated (mutation is only in `check_all()` / explicit flows), warning logged (sanitized). |
| check_all() task split | Task 4 defines `check_all()` as a stub (raises `NotImplementedError` or returns empty dict). Task 6 implements the full `check_all()` logic including decryptability scan, status recovery, error marking, key-mismatch hint, and startup integration. This avoids duplicating behavior across two tasks. |
| Task 4 split | Task 4 is split into two sub-tasks to reduce blast radius: **Task 4A** = types + validation + CRUD (save/get/list/delete/disconnect) + AAD + encryption integration. **Task 4B** = resolvers (get_ups_credentials, get_shopify_credentials, get_first_shopify_credentials) + runtime_usable computation + decrypt resilience + status updates. Each gets its own commit and test suite. |
| Key file permission warning | On Unix, if an existing key file has permissions more permissive than `0600`, log a WARNING recommending `chmod 600`. Do not auto-fix (user may have intentional config). |
| client_id redaction tradeoff | `client_id` is redacted as sensitive in Phase 1 (safe default). This reduces debugging usefulness but prevents accidental leakage if client IDs are later made secret by a provider. Document this decision so nobody "optimizes" redaction later. |
| Sanitizer known gaps | `sanitize_error_message()` does not cover: single-quoted JSON-like blobs, deeply nested stringified payloads, multiline tokens, or escaped quotes. These degrade gracefully (unsanitized but truncated to max_length). |
| Timestamp format | All ISO8601 timestamps (created_at, updated_at, last_validated_at, backfill values) use UTC with Z suffix: `YYYY-MM-DDTHH:MM:SSZ`. This prevents mixed naive/aware strings and frontend parsing inconsistencies. Python: `datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")`. |
| Integration test split | Task 16 integration tests are split into two groups: **Core smoke tests** (must-pass, fast — CRUD round-trip, save→resolve→use, env fallback, startup check, frontend type contract) and **Extended edge-case tests** (slower — corrupt data recovery, multi-provider interleaving, migration partial-upgrade, concurrent operations). Extended tests run in CI only; core smoke tests run in local dev. |
| CI env-read enforcement | The grep check from Task 17 is also implemented as a standalone test (`tests/integration/test_no_env_reads.py`) that fails if provider env reads are reintroduced outside `runtime_credentials.py`. This prevents regression as the codebase grows. The test uses the same grep exclusions (test files, CLI exempt files, `__pycache__`). |
| ProviderConnection column types | `id`: TEXT PK (UUID4 string, generated in Python via `str(uuid4())`). `created_at` / `updated_at`: TEXT columns storing `YYYY-MM-DDTHH:MM:SSZ` strings (service-managed, NOT SQLAlchemy `DateTime` — avoids ORM serialization producing `+00:00` instead of `Z`). `updated_at` set manually in `save_connection()` and `update_status()` (not ORM `onupdate`). `provider`, `auth_mode`, `status`, `environment`: TEXT, no length constraints (SQLite ignores them). `encrypted_credentials`: TEXT (JSON envelope string). `metadata_json`: TEXT (manual `json.loads()`). `connection_key`: TEXT with UNIQUE index. `display_name`: TEXT. `last_error_code`, `error_message`: TEXT nullable. `schema_version`, `key_version`: INTEGER default 1. |
| Shopify env fallback domain matching | When `resolve_shopify_credentials(store_domain=X)` is called with an explicit domain and no DB match exists, env fallback only returns credentials if the env `SHOPIFY_STORE_DOMAIN` matches the normalized requested domain. Mismatched domains return `None` with a WARNING log: "Requested store X but env has store Y — skipping env fallback." This prevents silently using the wrong store's credentials. `resolve_shopify_credentials()` without a domain (or via `get_first_shopify_credentials()`) uses env fallback unconditionally. |
| Migration duplicate-key pre-check | Before `CREATE UNIQUE INDEX`, the migration queries for duplicate `connection_key` values: `SELECT connection_key, COUNT(*) c FROM provider_connections GROUP BY connection_key HAVING c > 1`. If duplicates exist: log sanitized duplicate keys at ERROR level, raise `RuntimeError` with count. This makes the hardened migration deterministic and debuggable rather than relying on SQLite's index creation failure. |
| check_all() malformed rows | `check_all()` validates required row fields (`provider`, `auth_mode`, `connection_key`, `encrypted_credentials`) before attempting decrypt. Rows missing any of these are marked `needs_reconnect` with error code `INVALID_ROW` (not `DECRYPT_FAILED`). Processing continues for remaining rows. This keeps startup robust on partially-migrated or corrupt databases. |
| Connection error taxonomy | `ConnectionService` raises typed exceptions instead of bare `ValueError`. `ConnectionValidationError(code: str, message: str)` replaces all validation `ValueError` raises. Error codes: `INVALID_PROVIDER`, `INVALID_AUTH_MODE`, `INVALID_ENVIRONMENT`, `MISSING_FIELD`, `UNKNOWN_CREDENTIAL_KEY`, `VALUE_TOO_LONG`, `INVALID_DOMAIN`. API routes map `ConnectionValidationError` → 400 with `{"error": {"code": e.code, "message": e.message}}`. Other unexpected exceptions → 500 `INTERNAL_ERROR`. This eliminates brittle message-string parsing in routes. Defined in `src/services/connection_types.py` alongside credential dataclasses. |

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
| Shopify flow | Legacy token only in Phase 1 UI | Client credentials mode hidden in Phase 1 UI (backend type support exists). Phase 2 enables when token acquisition flow is implemented. |
| UI location | New accordion section in SettingsFlyout | Centralizes all provider management. Keeps existing flyout pattern. |
| Shopify migration | Move credentials to Settings, keep data source switch | DataSourcePanel keeps "Switch to Shopify" but checks Settings for connection first. |
| Credential delivery | In-memory resolver via `runtime_credentials.py` (no `os.environ` injection) | Single adapter module. Avoids global mutable state, child process leaks, and multi-connection clobber. |
| Connection identity | `connection_key` (non-null, unique) | Deterministic identity for multi-profile support (e.g., `ups:test`, `shopify:mystore.myshopify.com`). |
| Phase 1 UI scope | UPS: two subprofiles (test/prod) in one card. Shopify: legacy token only, single store. | Backend supports multiple auth modes, UI limits to simplest Phase 1 experience. |
| Route naming | `POST /{provider}/save` (not `/connect`) | "Save" is honest about Phase 1 semantics — persists credentials without live validation. `/connect` reserved for Phase 2 live flows. |
| Runtime integration | DB-stored creds used at all call sites via shared adapter with env fallback | Ensures saved credentials are actually used for shipping/data operations, not just stored. |
| 422 redaction | Raw dict payloads + custom RequestValidationError handler | Two-layer defense: no Pydantic credential binding prevents echo in field validation; custom exception handler sanitizes any remaining 422 responses on `/connections/*` routes. |
| Key length enforcement | Validate in encrypt/decrypt, not just key generation | Prevents AES-128/192 silent downgrade if caller passes wrong-length key. |
| Runtime usability | Server-side computed field | Backend-authoritative `runtime_usable` keeps UI dumb and prevents Phase 2 drift. |

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
| `metadata_json` | Text | Non-secret metadata (store_name, scopes, account_number). **Named `metadata_json` to avoid SQLAlchemy `Base.metadata` attribute collision.** API serializer maps to `metadata` in responses. Stored as TEXT with manual `json.loads()` in service layer. On parse failure: return `{}` and log WARNING. |
| `last_validated_at` | String(50), nullable | ISO8601 |
| `last_error_code` | String(50), nullable | Structured error code (e.g., `AUTH_FAILED`, `SCOPE_MISSING`) |
| `error_message` | Text, nullable | Human-readable error for diagnostics (**sanitized before persistence**, capped at 2000 chars) |
| `schema_version` | Integer, default 1 | For future model migrations |
| `key_version` | Integer, default 1 | For future key rotation support. **Phase 1: always `1`, no rotation/re-encryption flow.** |
| `created_at` | String(50) | ISO8601 |
| `updated_at` | String(50) | ISO8601 |

**Column type contract (prevents backend/frontend drift):**
- `id` is a UUID4 string generated in Python (`str(uuid.uuid4())`), not an auto-incrementing integer.
- `created_at` and `updated_at` are stored as TEXT (not SQLAlchemy `DateTime`). This ensures the `Z` suffix is always present and avoids ORM serialization producing `+00:00`.
- `updated_at` is set manually by the service layer in `save_connection()` and `update_status()` — no ORM `onupdate` hook. This keeps timestamp control deterministic and testable.
- No column length constraints are applied (SQLite ignores declared lengths). Validation happens at the service layer via credential payload allowlists.

**Unique constraint:** `connection_key` (not `(provider, environment)` — avoids SQLite NULL uniqueness issues).

### Connection Key Convention

| Provider | Key Format | Examples |
|----------|-----------|----------|
| UPS | `ups:{environment}` | `ups:test`, `ups:production` |
| Shopify | `shopify:{normalized_domain}` | `shopify:mystore.myshopify.com` |

**Domain normalization (Shopify):** `store_domain` is normalized server-side before key generation: lowercased, trimmed, protocol stripped (`https://`), trailing slashes removed, validated against `*.myshopify.com`. Malformed domains are rejected with 400.

**Environment validation (UPS):** `environment` is required for UPS and must be exactly `"test"` or `"production"`. Missing or invalid values are rejected with 400 — no silent defaults.

### Shared Constants / Enums

To prevent string drift across backend, frontend, and tests, the following are defined as constants or enums and imported everywhere:

```python
# In connection_service.py or a dedicated constants module
VALID_PROVIDERS = frozenset({"ups", "shopify"})
VALID_AUTH_MODES = {
    "ups": frozenset({"client_credentials"}),
    "shopify": frozenset({"legacy_token", "client_credentials_shopify"}),
}
VALID_ENVIRONMENTS = frozenset({"test", "production"})
SKIP_STATUSES = frozenset({"disconnected", "needs_reconnect"})
VALID_STATUSES = frozenset({"configured", "validating", "connected", "disconnected", "error", "needs_reconnect"})
RUNTIME_USABLE_STATUSES = frozenset({"configured", "connected", "validating", "error"})
```

These constants are used by `ConnectionService`, `runtime_credentials.py`, API routes, and tests. Frontend mirrors them in TypeScript types.

### Connection Status Model

| Status | Meaning | Phase 1 Semantics | Transition From |
|--------|---------|-------------------|----------------|
| `configured` | Credentials saved, not yet validated | **Stored and decryptable** — not necessarily validated against provider | (initial), error, needs_reconnect, disconnected (via re-save) |
| `validating` | Live validation in progress | **Reserved — never set in Phase 1** | configured, error |
| `connected` | Validated against live provider API | **Reserved — never set in Phase 1** (no live validation) | validating |
| `disconnected` | User-initiated disconnect, credentials preserved | **User-disabled** — operationally inactive, skipped by resolvers and `check_all()` | connected, configured |
| `error` | Validation or connection failed | **Never set in Phase 1** (exists for Phase 2 forward compatibility) | validating, connected |
| `needs_reconnect` | Decryption failed on startup | **Decrypt failure** — key changed or credentials corrupted | configured, connected |

**Status transition rules:**

| Action | Status Change | Notes |
|--------|--------------|-------|
| `save_connection()` (new) | → `configured` | Initial save |
| `save_connection()` (overwrite) | → `configured` | Re-save always resets to `configured`, even from `disconnected` |
| `disconnect()` | → `disconnected` | Credentials preserved |
| `check_all()` decrypt success | `needs_reconnect` → `configured` | Recovery. All other statuses preserved. |
| `check_all()` decrypt failure | → `needs_reconnect` | Marks unreadable credentials |
| `check_all()` on `disconnected` | *(skipped)* | User-disabled rows are not checked |
| Phase 2 `/test` success | `configured` → `connected` | Live validation |
| Phase 2 `/test` failure | → `error` | Live validation failure |

**Phase 1 status semantics:** Phase 1 automated flows only produce three statuses: `configured` (saved and decryptable), `needs_reconnect` (decrypt failure), and `disconnected` (user-disabled). The remaining statuses exist in the schema for Phase 2 forward compatibility. `error` may still appear via explicit `update_status()` calls or legacy/manual paths, but is not produced by any Phase 1 automated workflow. `check_all()` on startup runs a decryptability scan on all non-`disconnected` rows. Successful decryption preserves the row's existing status, **except** `needs_reconnect` which recovers to `configured`. Failures are marked `needs_reconnect`.

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

### Shopify Phase 1 Runtime-Usability

**`client_credentials_shopify` is hidden in the Phase 1 UI.** The backend type support exists for forward compatibility (backend validates and stores `client_credentials_shopify` rows), but:

- The Shopify form radio selector only shows "I have an access token" (legacy) in Phase 1
- `client_credentials_shopify` rows saved via API are stored correctly but are **not runtime-usable** in Phase 1 because:
  - `ShopifyClientCredentials.access_token` is empty (Phase 2 obtains it)
  - `resolve_shopify_credentials()` returns `None` for these rows (empty access_token)
  - The backend computes `runtime_usable: false` with `runtime_reason: "missing_access_token"` for these rows
- The UI prevents this ambiguity by not exposing the mode
- Phase 2 enables the radio option when token acquisition flow ships

This avoids the "configured but not usable" false-positive that would confuse users.

### Encryption Scheme

- **Algorithm:** AES-256-GCM (authenticated encryption)
- **Key length enforcement:** Both `encrypt_credentials()` and `decrypt_credentials()` validate `len(key) == 32`. Passing a 16-byte or 24-byte key raises `ValueError` / `CredentialDecryptionError` respectively, preventing silent downgrade from AES-256-GCM to AES-128-GCM or AES-192-GCM while the envelope still claims "AES-256-GCM".
- **Key source precedence:**
  1. `SHIPAGENT_CREDENTIAL_KEY` env var (base64-encoded 32-byte key) — for testing and containerized deployments
  2. `SHIPAGENT_CREDENTIAL_KEY_FILE` env var (absolute path to raw key file) — for explicit key management. File must exist, be readable, be a regular file, and not be a symlink. Missing file, unreadable permissions, or directory path raises `ValueError` with clear message.
  3. platformdirs local file (auto-generated) — default for local desktop use
     - macOS: `~/Library/Application Support/shipagent/.shipagent_key`
     - Linux: `~/.local/share/shipagent/.shipagent_key`
     - Windows: `C:\Users\<user>\AppData\Local\shipagent\.shipagent_key`
- **Auto-generated:** on first app startup via `os.urandom(32)` if no key source is configured. Uses `O_EXCL` for atomic creation. On `FileExistsError` (concurrent startup race), immediately reads the existing file and validates length — no error raised.
- **Permissions:** `0o600` on Unix (platform-aware — skipped on Windows)
- **Permission check on existing files:** If an existing key file is found with permissions more permissive than `0o600` on Unix (e.g., `0o644`), log a WARNING: *"Key file {path} has permissions {mode} — recommend chmod 600 for security."* Do not auto-fix (user may have intentional configuration).
- **Per-record IV:** fresh 12-byte nonce per encrypt, stored in envelope
- **Format (versioned envelope):** `{"v":1, "alg":"AES-256-GCM", "nonce":"<b64>", "ct":"<b64>"}` → JSON → stored in `encrypted_credentials`
- **Canonical serialization:** `json.dumps(credentials, sort_keys=True)` before encryption for deterministic ciphertext structure
- **AAD (Additional Authenticated Data):** `provider:auth_mode:connection_key` — binds ciphertext to its record
- **AAD construction:** Centralized in `ConnectionService._build_aad(row)` — single function, not scattered across call sites
- **Algorithm validation:** Decrypt rejects envelopes where `alg` is not `"AES-256-GCM"`
- **Payload validation:** Decrypt verifies the decrypted payload is a `dict` (not a list or scalar)
- **Base64 validation:** `base64.b64decode(..., validate=True)` used for env key decoding and envelope fields; invalid base64 raises `ValueError` with clear message
- **Env override precedence:** When both `SHIPAGENT_CREDENTIAL_KEY` and `SHIPAGENT_CREDENTIAL_KEY_FILE` are set, `SHIPAGENT_CREDENTIAL_KEY` wins (env key takes priority over env file path). Tested explicitly.
- **Implementation:** `src/services/credential_encryption.py` using Python `cryptography` library + `platformdirs`

### Key Source Observability

For local desktop support/debugging, a helper reports which key source is active:

```python
def get_key_source_info() -> dict:
    """Return metadata about the active key source (without revealing the key).

    Returns:
        {"source": "env"|"env_file"|"platformdirs", "path": "..." or None}
    """
```

Logged at startup (INFO level) alongside `check_all()` results. This saves support time when users move machines or launch via different shells.

**platformdirs production warning:** If `get_key_source_info()` returns `"platformdirs"`, the startup log includes a guidance note: *"Using auto-generated key from local filesystem. For production or containerized deployments, set SHIPAGENT_CREDENTIAL_KEY or SHIPAGENT_CREDENTIAL_KEY_FILE."*

**Strict key policy (opt-in):** If `SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY=true` is set and the resolved key source is `platformdirs`, startup raises `RuntimeError` with a clear message instead of silently using a local key. This prevents `needs_reconnect` storms in ephemeral container environments where the auto-generated key is lost on restart. Default is `false` (local desktop use case — platformdirs is fine).

### Threat Model (Phase 1)

Phase 1 provides **app-local at-rest encryption**: credentials are encrypted in the DB using a key stored on the local filesystem (or provided via env var). This protects against:

- DB-only leakage (e.g., backup exposure, SQLite file shared without key)

It does **not** protect against:

- Host compromise / same-user filesystem access (attacker with access to both DB file and key file can decrypt)

**Desktop-specific implications:**

- Copying DB to another machine/profile without the key file → credentials become undecryptable (→ `needs_reconnect` on startup)
- Using a different launch method with different env vars can change key source precedence
- This is **not equivalent** to OS keychain-backed protection

Future hardening options (Phase 2+):
- macOS Keychain integration
- Windows DPAPI
- libsecret / GNOME Keyring
- KMS for hosted deployments
- Explicit "export/import settings" flow that excludes secrets or re-wraps them

### Encrypted vs. Plaintext Fields (per provider)

| Provider | Encrypted | Metadata (plaintext JSON) |
|----------|-----------|---------------------------|
| UPS | `client_id`, `client_secret` | `account_number`, `environment`, `base_url` |
| Shopify (legacy) | `access_token` | `store_domain`, `store_name`, `scopes`, `api_version` |
| Shopify (client_credentials) | `client_id`, `client_secret` | `store_domain`, `store_name`, `scopes`, `api_version` |

**Shopify `client_credentials_shopify` credential contract (Phase 1):** In Phase 1, only `client_id` and `client_secret` are stored. The `access_token` is **not required** — it will be obtained via the client-credentials grant flow in Phase 2. The `ShopifyClientCredentials` dataclass has `access_token` as an optional field (empty string default). This mode is hidden in the Phase 1 UI.

### Credential Payload Allowlists

Each provider/auth_mode combination has explicit key validation. Unknown keys are rejected with 400 — the request fails immediately. This catches typos (e.g., client_secert → client_secret) early and keeps behavior deterministic. Required keys must be present and non-empty. Max field lengths prevent storage of excessively large payloads.

| Provider | Auth Mode | Required Keys | Optional Keys | Max Length |
|----------|-----------|---------------|---------------|-----------|
| UPS | `client_credentials` | `client_id`, `client_secret` | — | 1024 chars each |
| Shopify | `legacy_token` | `access_token` | — | 4096 chars |
| Shopify | `client_credentials_shopify` | `client_id`, `client_secret` | `access_token` | 1024 / 1024 / 4096 chars |

**`account_number` is metadata, not a credential.** It is stored in `metadata_json`, not in the encrypted credential blob. Same for `store_domain`, `scopes`, `api_version`.

**Validation location:** `ConnectionService._validate_credential_keys()` validates keys before encryption. Runs after `_validate_save_input()` (which checks provider, auth_mode, environment) and before `encrypt_credentials()`.

## Section 2: Backend Service Layer & API Routes

### Secret Redaction Utility (`src/utils/redaction.py`)

A centralized redaction helper prevents credential leakage in logs and error responses:

```python
def redact_for_logging(obj: dict, sensitive_keys: frozenset[str] = ...) -> dict:
    """Redact sensitive values from a dict for safe logging/error responses.

    Handles nested dicts and lists of dicts.
    Key matching is case-insensitive and uses substring patterns.
    """
```

Used in:
- API exception logging (connection routes)
- Startup check warning logs
- Runtime resolver fallback warnings
- Error response bodies (500s)
- Custom 422 validation error handler
- `error_message` sanitization before DB persistence

Default sensitive patterns (case-insensitive substring match): `secret`, `token`, `authorization`, `api_key`, `password`, `credential`, `client_id`, `client_secret`, `access_token`, `refresh_token`.

**`client_id` redaction tradeoff:** `client_id` is included in the default sensitive patterns. While client IDs are often non-secret (public identifiers), redacting them in Phase 1 is the safe default. This reduces debugging usefulness slightly (masked in logs), but prevents accidental leakage if a provider later makes client IDs confidential. This is a documented intentional choice — do not remove `client_id` from patterns without explicit review.

Supports:
- **Case-insensitive key matching** (catches `ClientSecret`, `ACCESS_TOKEN`, `client_secret`)
- **Substring pattern matching** (catches `x_api_key`, `bearer_token`, `shopify_access_token`)
- **Nested dict redaction** (recursive)
- **Lists of dicts** (e.g., FastAPI validation error arrays)
- **Known container keys** (`credentials`, `headers`) redacted recursively
- Custom sensitive key overrides

### Error Message Sanitization

Before persisting `error_message` to the `ProviderConnection` table, values are:

1. Passed through `redact_for_logging()` if they contain dict-like content
2. Scanned by `sanitize_error_message()` which handles multiple secret formats:
   - `key=value` pairs (e.g., `client_secret=abc123`)
   - `Authorization: Bearer <token>` headers
   - JSON-style `"key": "value"` and `"key":"value"` pairs
   - Quoted values (e.g., `access_token = "abc 123"`)
   - Multiple sensitive pairs on one line (e.g., `client_id=foo client_secret=bar`)
3. Truncated to a maximum of 2000 characters
4. `last_error_code` is always preserved for stable programmatic handling

This prevents upstream exception messages (which may contain headers, payloads, or auth details) from becoming a secret sink in the database.

**Known non-covered formats** (degrade gracefully — unsanitized but truncated):
- Single-quoted JSON-like blobs (e.g., `{'key': 'value'}`)
- Deeply nested stringified payloads
- Multiline tokens spanning multiple lines
- Escaped quotes within values

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
    def get_first_shopify_credentials() -> ShopifyLegacyCredentials | ShopifyClientCredentials | None  # Phase 1 default

    # Startup
    def check_all() -> dict[str, str]  # decryptability scan only

    # Runtime usability (computed)
    def _is_runtime_usable(row: ProviderConnection) -> tuple[bool, str | None]  # (usable, reason)

    # Internal
    def _build_aad(row: ProviderConnection) -> str  # centralized AAD construction
    def _sanitize_error_message(msg: str | None) -> str | None  # redact + truncate
```

**Key behaviors:**

- `save_connection()` — validates input, normalizes domain, encrypts and persists credentials. Sets status to `"configured"` (even on overwrite of a `"disconnected"` row — re-save is a reconnect). Returns `is_new: bool` flag to distinguish create vs. overwrite. Does NOT validate against live API. Sanitizes `error_message` before persistence.
- `disconnect()` — sets status to `"disconnected"`, preserves encrypted credentials.
- `update_status()` validates `status` against `VALID_STATUSES` constant. Unknown statuses raise `ValueError`.
- `delete_connection()` — disconnects AND wipes credentials from DB.
- `get_ups_credentials(environment)` — typed credential resolver. Decrypts on demand. Skips `disconnected` and `needs_reconnect` rows (uses `SKIP_STATUSES` constant). Returns `UPSCredentials | None`.
- `get_shopify_credentials(store_domain)` — typed credential resolver. Input domain is normalized before lookup. Skips `disconnected` and `needs_reconnect` rows (uses `SKIP_STATUSES` constant). Returns `ShopifyLegacyCredentials | ShopifyClientCredentials | None` depending on `auth_mode`.
- `get_first_shopify_credentials()` — Phase 1 default selection. Returns the first non-skipped Shopify connection ordered by `connection_key ASC` at the **DB query level** (not list filtering after fetch). Deterministic and documented as temporary (Phase 2 requires explicit store selection).
- `check_all()` — called during FastAPI lifespan startup. Runs a decryptability scan on all non-`disconnected` rows (**skips `disconnected` rows entirely** to preserve user-intent status). On success: if status is `"needs_reconnect"` recovers it to `"configured"` and clears error fields; all other statuses preserved. On decrypt failure: sets `"needs_reconnect"` + `last_error_code = "DECRYPT_FAILED"` + sanitized error message. Does NOT promote any row to `"connected"`. Does NOT write to `os.environ`. Does NOT populate any in-memory cache. Logs key source info at start for diagnostics.
- `_is_runtime_usable(row)` — computed per-row: returns `(False, "disconnected")` for skip statuses, `(False, "missing_access_token")` for `client_credentials_shopify` with no token, `(True, None)` otherwise. Used when building API responses.
- **list/get decrypt resilience:** `list_connections()` and `get_connection()` never raise due to credential decrypt errors. When computing `runtime_usable` for a row with corrupt/wrong-key encrypted credentials: `runtime_usable = false`, `runtime_reason = "decrypt_failed"`, status is NOT mutated (status mutation is exclusively in `check_all()` and explicit `update_status()` calls). WARNING logged with sanitized context. This prevents a corrupt row from 500-ing the Settings page.
- `_build_aad(row)` — constructs AAD string as `f"{row.provider}:{row.auth_mode}:{row.connection_key}"`. Single function, consistent across all encrypt/decrypt operations. **Auth-mode switch safety:** When overwriting a row (e.g., `legacy_token` → `client_credentials_shopify`), the old row's credentials do NOT need to be decrypted first — the entire `encrypted_credentials` blob is replaced. The new AAD is built from the updated `auth_mode`, so decrypt on the new blob uses the new AAD correctly.
- `_sanitize_error_message(msg)` — redacts sensitive substrings, truncates to 2000 chars. Applied to all `error_message` values before DB write.

### Credential Resolver (replaces `os.environ` injection)

Instead of injecting secrets into `os.environ` on startup, the `ConnectionService` provides typed credential objects:

**Module location:** These dataclasses live in `src/services/connection_types.py` — a neutral module with no DB or service-layer imports. This prevents circular dependency issues when multiple modules need to import them.

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
    db: Session | None = None,
    key_dir: str | None = None,
) -> UPSCredentials | None:
    """Resolve UPS credentials: DB-stored (priority) → env var (fallback).

    Args:
        environment: "test" or "production". Defaults to UPS_ENVIRONMENT env or "test".
        db: SQLAlchemy session. If None, acquires one internally via get_db_context().
        key_dir: Key directory override (testing).

    Returns:
        UPSCredentials if available, None if neither DB nor env configured.

    Logs:
        WARNING (once) if falling back to env vars.
        WARNING if neither source available.

    UPS environment/base_url resolution (env fallback):
        1. Target environment = explicit `environment` param → UPS_ENVIRONMENT env → "test"
        2. Base URL derived from target environment:
           - "test" → "https://wwwcie.ups.com"
           - "production" → "https://onlinetools.ups.com"
        3. If UPS_BASE_URL is explicitly set and conflicts with derived URL → log WARNING
        4. Explicit UPS_BASE_URL wins (user override), but mismatch is flagged
    """

def resolve_shopify_credentials(
    store_domain: str | None = None,
    db: Session | None = None,
    key_dir: str | None = None,
) -> ShopifyLegacyCredentials | ShopifyClientCredentials | None:
    """Resolve Shopify credentials: DB-stored (priority) → env var (fallback).

    Args:
        store_domain: Explicit domain. If None, uses first available DB connection
                      (Phase 1 single-store; deterministic via ORDER BY connection_key ASC).
        db: SQLAlchemy session. If None, acquires one internally via get_db_context().
        key_dir: Key directory override (testing).

    Returns:
        ShopifyLegacyCredentials or ShopifyClientCredentials if available, None otherwise.
        Returns None if access_token is empty (client_credentials_shopify without token acquisition). Call sites that need dict access should use dataclasses.asdict() at the boundary.

    **Domain-matched env fallback:** When `store_domain` is explicitly provided and no DB row matches, env fallback only activates if `SHOPIFY_STORE_DOMAIN` matches the normalized requested domain. Mismatched domains return `None` with a WARNING. This prevents silently routing credentials to the wrong store.

    Logs:
        WARNING (once) if falling back to env vars.
        WARNING if neither source available.
    """
```

**`db=None` behavior:** When `db` is not provided, the adapter acquires a DB session internally via `get_db_context()` (same helper used throughout the codebase). This allows call sites that don't have a session readily available to still use the adapter. For testing, always pass `db` explicitly to control the database state.

**Fallback logging policy:** Warnings are logged with safe context (provider, environment/domain, exception class — never raw credentials). Each fallback reason is logged at most once per process lifetime to avoid log noise. Tests reset `_ups_fallback_warned` / `_shopify_fallback_warned` flags in setup to avoid cross-test pollution.

**Shopify runtime-usability filter:** `resolve_shopify_credentials()` returns `None` if the resolved `access_token` is empty (as with `client_credentials_shopify` rows that have no token yet). This prevents downstream call sites from receiving a "looks valid but isn't" credential dict.

**UPS env fallback environment/base_url resolution:** When falling back to env vars:
1. Target environment = explicit `environment` parameter → `UPS_ENVIRONMENT` env → `"test"`
2. Default base URL = derived from target environment (`"test"` → `"https://wwwcie.ups.com"`, `"production"` → `"https://onlinetools.ups.com"`)
3. If `UPS_BASE_URL` is explicitly set, use it — but if it conflicts with the derived default (e.g., `environment="production"` but `UPS_BASE_URL` contains `wwwcie`), log a WARNING about the mismatch
4. This prevents silent environment/URL mismatches when users set only some env vars

**Shopify default selection (Phase 1):** When no `store_domain` is specified, the resolver picks the first non-skipped Shopify connection ordered by `connection_key ASC`. This is deterministic and temporary — Phase 2 will require explicit store selection in all runtime paths. This behavior is documented in code comments.

**Call-site None behavior (when adapter returns None):**

| Call Site | File | Behavior on None |
|-----------|------|-----------------|
| MCP config creation | `orchestrator/agent/config.py` | Skip UPS MCP server from config (agent starts without UPS tools) |
| System prompt builder | `orchestrator/agent/system_prompt.py` | Soft message: "UPS/Shopify not configured — connect in Settings" |
| Batch execution | `services/batch_engine.py` | Hard failure with actionable error: "No UPS credentials configured. Open Settings to connect." |
| Interactive shipment tool | `orchestrator/agent/tools/interactive.py` | Warning + prompt: "UPS not connected. Would you like to set it up in Settings?" |
| Shopify platform connect | `api/routes/platforms.py` | Return error response: "No Shopify credentials configured" |

### Enforcement Rule: No Ad Hoc Env Reads After Integration

After Tasks 8–9 are complete, **no runtime server path call site outside `runtime_credentials.py` may directly read provider credential env vars** (`UPS_CLIENT_ID`, `UPS_CLIENT_SECRET`, `SHOPIFY_ACCESS_TOKEN`, `UPS_ACCOUNT_NUMBER`, `UPS_BASE_URL`, `UPS_ENVIRONMENT`, `SHOPIFY_STORE_DOMAIN`, etc.). CLI paths (`http_client.py`, `runner.py`) are **temporarily exempt** in Phase 1 with TODO comments for Phase 2 migration. The final verification (Task 17) includes an expanded grep check that excludes these explicitly exempt CLI files:

```bash
grep -rn "UPS_CLIENT_ID\|UPS_CLIENT_SECRET\|UPS_ACCOUNT_NUMBER\|UPS_BASE_URL\|UPS_ENVIRONMENT\|SHOPIFY_ACCESS_TOKEN\|SHOPIFY_STORE_DOMAIN" src/ \
  --include="*.py" | grep -v runtime_credentials | grep -v test | grep -v __pycache__ | grep -v http_client | grep -v runner
```

Remaining occurrences must be only in `runtime_credentials.py` (and tests/config documentation).

**Code review enforcement (beyond grep):** Grep catches direct string references but misses indirect env reads (wrapper functions, settings objects). The final verification includes a code review checklist:
1. No new `os.environ.get()` or `os.getenv()` calls for provider credential env vars outside `runtime_credentials.py`
2. No wrapper functions, settings objects, or config utilities that read provider creds indirectly
3. No new imports of `os.environ` in files that handle provider credentials (except `runtime_credentials.py`)

For longer-term enforcement, consider an optional AST/ruff/semgrep rule.

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

**Pattern:** All Shopify call sites call `resolve_shopify_credentials()` which checks DB first (via `ConnectionService`), falls back to env vars. The resolver returns a simple dict with `access_token` and `store_domain`, or `None` if `access_token` is empty (client_credentials_shopify without token).

### API Routes (`src/api/routes/connections.py`)

| Method | Path | Purpose | Success | Error |
|--------|------|---------|---------|-------|
| `GET` | `/connections/` | List all saved connections (no secrets, includes `runtime_usable`) | 200 | — |
| `GET` | `/connections/{connection_key}` | Get single connection details (includes `runtime_usable`) | 200 | 404 |
| `POST` | `/connections/{provider}/save` | Encrypt + persist (no live validation) | 201 (create) / 200 (update) | 400, 422 |
| `POST` | `/connections/{connection_key}/disconnect` | Disconnect, keep credentials | 200 | 404 |
| `DELETE` | `/connections/{connection_key}` | Disconnect + wipe credentials | 200 | 404 |

**Save response codes:** `201 Created` when a new connection is created, `200 OK` when an existing connection is updated (overwritten). The service layer returns an `is_new` flag to distinguish.

**Phase 1 omissions (deferred to Phase 2):**
- `POST /connections/{connection_key}/test` — live credential validation
- `POST /connections/{provider}/connect` — save + validate + connect in one call

**Provider path validation:** `provider` is validated against `Literal["ups", "shopify"]`. Invalid providers return 400.

**Server-side `runtime_usable` field:** All connection responses include:
- `runtime_usable: bool` — computed by `ConnectionService._is_runtime_usable(row)`
- `runtime_reason: str | null` — reason when not usable (e.g., `"disconnected"`, `"needs_reconnect"`, `"missing_access_token"`)

This keeps the frontend dumb — it reads `runtime_usable` directly instead of inferring from `auth_mode` or `status`. When Phase 2 adds token acquisition, the backend logic changes but the frontend API contract stays the same.

**Input validation and 422 redaction strategy (two-layer defense):**

1. **Layer 1 — Raw dict payloads:** Connection routes accept `body: dict = Body(...)` — no Pydantic model binding for credential fields. This prevents FastAPI from including submitted secret values in automatic 422 field-level validation error responses.
2. **Layer 2 — Custom `RequestValidationError` handler:** A custom exception handler registered in `src/api/main.py` intercepts `RequestValidationError` for `/connections/*` routes and returns sanitized validation errors that strip raw input values from the error detail. The handler wraps sanitized detail in the standard error schema for consistency. For other routes, the default FastAPI behavior is preserved.

- Route signature: `async def save_provider(provider: str, body: dict = Body(...)):`
- All field validation (required fields, formats, auth_mode) happens in `ConnectionService.save_connection()` which raises `ConnectionValidationError` from service → 400 with `{"error": {"code": e.code, "message": e.message}}`. Unexpected exceptions → 500 `INTERNAL_ERROR` (sanitized).
- UPS: `environment` required (`"test"` or `"production"`), `client_id` and `client_secret` non-empty
- Shopify: `store_domain` required, normalized and validated against `*.myshopify.com`, credential fields validated per auth_mode
- Invalid provider → 400, invalid auth_mode → 400, missing required fields → 400
- 500 errors: structured payloads (dicts/lists) use `redact_for_logging()`; free-text exception strings use `sanitize_error_message()`. These are complementary — `redact_for_logging` handles dict key-value structures, `sanitize_error_message` handles unstructured error strings. Neither raw exception strings nor credential values ever reach API responses.

Credentials are **never** returned in any API response.

**Standardized error response schema:** All connection route errors use a consistent format:

```json
{"error": {"code": "INVALID_PROVIDER", "message": "Provider 'fedex' is not supported. Valid: ups, shopify"}}
```

Error codes are structured strings (not numeric). Messages are human-readable and sanitized. This gives frontend a reliable contract for error handling. Phase 2 may add an optional `fields` array for per-field validation errors.

**422 validation errors** also use this schema with an additional `detail` array for field-level errors:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request payload"
  },
  "detail": [
    {"type": "missing", "loc": ["body", "credentials"], "msg": "Field required"}
  ]
}
```

This preserves both consistency (outer `error` envelope) and machine readability (structured `detail` array). Non-connection routes delegate to default FastAPI 422 format for non-connection routes.

### Startup Flow

**Current:** FastAPI lifespan → nothing (credentials in `.env`)
**New:** FastAPI lifespan → log key source info (with platformdirs production warning if applicable) → `ConnectionService.check_all()` → reads DB → **skips `disconnected` rows** → verifies each non-disconnected row is decryptable → marks failures as `"needs_reconnect"` (with sanitized error messages) → recovers `"needs_reconnect"` rows to `"configured"` on success → clears errors only on `needs_reconnect` recovery

**Startup key mismatch hint:** If `check_all()` marks any rows as `needs_reconnect`, log a prominent warning:

```
WARNING: N provider connection(s) could not be decrypted. This may indicate the encryption key has changed
(e.g., moved to a different machine, or launched with different environment variables).
Re-save credentials in Settings to fix. Key source: {source} ({path})
```

**Startup exception handling:** The startup check is non-blocking but uses narrowed exception handling:

```python
from src.services.credential_encryption import CredentialDecryptionError

try:
    key_info = get_key_source_info()
    logger.info("Credential key source: %s (%s)", key_info["source"], key_info.get("path", "n/a"))
    if key_info["source"] == "platformdirs":
        strict = os.environ.get("SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY", "").lower() == "true"
        if strict:
            raise RuntimeError(
                "SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY is set but key source is 'platformdirs'. "
                "Set SHIPAGENT_CREDENTIAL_KEY or SHIPAGENT_CREDENTIAL_KEY_FILE for persistent deployments."
            )
        logger.info(
            "Using auto-generated key from local filesystem. "
            "For production or containerized deployments, set "
            "SHIPAGENT_CREDENTIAL_KEY or SHIPAGENT_CREDENTIAL_KEY_FILE."
        )
    with get_db_context() as db:
        from src.services.connection_service import ConnectionService
        conn_service = ConnectionService(db=db)
        check_results = conn_service.check_all()
        if check_results:
            logger.info("Provider credential check results: %s", check_results)
except (RuntimeError, ValueError):
    raise  # Key config errors and strict policy — must not be swallowed
except CredentialDecryptionError as e:
    logger.warning("Provider credential check failed (non-blocking): %s: %s",
                   type(e).__name__, e, exc_info=True)
except Exception as e:
    logger.error("Unexpected error during provider credential check: %s: %s",
                 type(e).__name__, e, exc_info=True)
```

This logs exception type + stack trace (for debugging). Key configuration errors (`ValueError` from bad base64, wrong key length, missing key file) and strict policy violations (`RuntimeError`) are fatal — the app does not start with a misconfigured key source. Per-row decrypt failures during `check_all()` are non-blocking (app starts, rows marked `needs_reconnect`).

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
4. `CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_connections_connection_key ON provider_connections (connection_key)` — hardens unique constraint for partial-upgrade scenarios where the table may exist without the `UNIQUE` constraint
5. `CREATE INDEX IF NOT EXISTS idx_provider_connections_provider ON provider_connections (provider)` — ensures index exists

**Duplicate row handling:** If the unique index creation fails because duplicate `connection_key` rows already exist (from a corrupted partial upgrade), the migration logs an ERROR with the duplicate keys and raises — it does not silently proceed with a broken schema. The user must manually resolve duplicates before the app can start.

This handles:
- Fresh installs (table created with all constraints)
- Existing installs with older schema (missing columns added, unique index hardened)
- Partial upgrades (interrupted migrations completed)
- Partial tables without unique constraint (index creation hardens them)
- Repeated startups (all operations idempotent)

No Alembic required — consistent with the existing project migration approach.

**Nullability and backfill strategy (SQLite):**

SQLite `ALTER TABLE ADD COLUMN` requires columns to be nullable or have a default value. All new columns are added as nullable. Defaults and constraints are enforced at the application level:

| Column | ALTER TABLE | Application Default | Backfill Behavior |
|--------|-------------|--------------------|--------------------|
| `status` | Nullable | `"configured"` | Missing → `"needs_reconnect"` (cannot verify decryptability during migration) |
| `auth_mode` | Nullable | None | Missing → row marked `"needs_reconnect"` |
| `encrypted_credentials` | Nullable | None | Missing → row marked `"needs_reconnect"` |
| `metadata_json` | Nullable | `"{}"` | Missing → `"{}"` |
| `environment` | Nullable | None | UPS-only, nullable for Shopify |
| `schema_version` | Nullable | `1` | Missing → `1` |
| `key_version` | Nullable | `1` | Missing → `1` |
| `created_at` | Nullable | `datetime.now(UTC).isoformat()` | Missing → current timestamp |
| `updated_at` | Nullable | `datetime.now(UTC).isoformat()` | Missing → current timestamp |

After column additions, a backfill step runs:
1. Set `metadata_json = '{}'` where NULL
2. Set `schema_version = 1` where NULL
3. Set `key_version = 1` where NULL
4. Set `status = 'needs_reconnect'` where NULL (forces re-save)
5. Log count of backfilled rows
6. Set `created_at` and `updated_at` to current ISO8601 timestamp where NULL

## Section 3: Frontend UI

### Component Structure

```
frontend/src/components/settings/
├── SettingsFlyout.tsx          (modified — add ConnectionsSection first)
├── ConnectionsSection.tsx     (new — accordion wrapper with configured/connected count)
├── ProviderCard.tsx           (new — status badge, actions, expandable form)
├── UPSConnectForm.tsx         (new — Client ID, Secret, Account #, Environment toggle)
├── ShopifyConnectForm.tsx     (new — legacy token form only in Phase 1)
```

### Phase 1 UI Scope

| Provider | UI Shape | Cardinality |
|----------|----------|-------------|
| UPS | One card with Test/Production environment toggle | Two subprofiles (`ups:test`, `ups:production`) within one card |
| Shopify | One card with legacy token form only | Single store only. Client credentials radio option hidden in Phase 1. |

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

**Disconnect vs Delete semantics (UI copy):**
- **Disconnect** = disable use, keep saved credentials (reversible via re-save). No confirmation dialog.
- **Delete** = remove stored credentials permanently (irreversible). Confirmation dialog required.
- Tooltip on Disconnect button: "Temporarily disable this connection. Credentials are preserved."
- Tooltip on Delete button: "Permanently remove this connection and its stored credentials."

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

### Shopify Form Fields (Phase 1)

**Phase 1:** Single form for legacy token mode only. No radio selector (client credentials mode hidden).

Fields:
- **Store domain** (required, validated against `*.myshopify.com`, normalized on submit)
- **Access Token** (required, password field)

**Phase 2 addition:** Radio selector "I have an access token" (legacy) vs "I have client credentials" (new) — currently hidden.

### State Management

New in `useAppState`:
- `providerConnections: ProviderConnectionInfo[]` — hydrated on mount
- `providerConnectionsLoading: boolean`
- `refreshProviderConnections(): void` — bumps version counter

**Frontend type strictness:**
- `ProviderConnectionInfo.id` is `string` (backend serializes UUID as string via `str(row.id)`)
- `SaveProviderRequest.auth_mode` uses `ProviderAuthMode` union type (not bare `string`) for compile-time safety
- `ProviderConnectionInfo.metadata` is `Record<string, unknown>` (not `Record<string, string>`) to handle booleans, arrays, and nested data
- `ProviderConnectionStatus` type union is wide for forward compatibility, but **Phase 1 actively produces only `configured`, `disconnected`, `needs_reconnect`**. Add a TSDoc comment: `// Phase 1: only configured, disconnected, needs_reconnect are actively produced. Others reserved for Phase 2.`

**Frontend runtime-usable consumption:** Frontend uses the `runtime_usable` field from API responses directly. No client-side inference from `auth_mode`, `status`, or other fields. This field drives:
- DataSourcePanel Shopify availability
- ProviderCard status display
- Any future feature-gating decisions

### Frontend URL Safety

All `connectionKey` values are passed through `encodeURIComponent()` before interpolation into URL paths in `api.ts`.

### Frontend Error Handling & Loading States

- **Save/Disconnect/Delete buttons:** Show loading spinner during API call, disabled to prevent duplicate submission
- **Save errors:** Inline error message below form (not toast), card stays expanded with form accessible
- **Disconnect/Delete:** Confirmation dialog before delete (destructive action), no confirmation for disconnect (reversible via re-save)
- **Network errors:** Inline error with retry guidance
- **Loading state on mount:** Skeleton placeholder while `providerConnectionsLoading` is true

### DataSourcePanel Migration

- Shopify connection with `runtime_usable: true` → show as available data source with switch button (existing behavior)
- Shopify `runtime_usable: false` or not configured → show "Connect Shopify in Settings" link that calls `setSettingsFlyoutOpen(true)`
- No credential entry in sidebar anymore

**Env fallback UI behavior (Phase 1):** The UI shows DB connections only. When a user has valid `.env` Shopify credentials but no DB row, the runtime still works (env fallback in `runtime_credentials.py`), but the UI shows "Connect Shopify in Settings." This is the intended transition behavior — users are encouraged to migrate credentials to Settings without breaking existing workflows. No "env fallback detected" indicator in Phase 1.

**Runtime-usable gating:** DataSourcePanel reads the `runtime_usable` field from the connection response directly. No client-side inference from `auth_mode` or `status`. This field is computed server-side by `ConnectionService._is_runtime_usable()`, which returns `false` for: skip statuses (`disconnected`, `needs_reconnect`), `client_credentials_shopify` with empty token, and any other non-usable state.

**Rationale:** `disconnected` means the user intentionally disabled the connection, so it should not appear as an available source. Only connections where `runtime_usable: true` are shown as available data sources.

## Section 4: Validation & Error Handling

### Phase 1 Validation (save-time only)

**UPS:**
1. `environment` required, must be `"test"` or `"production"` (use `VALID_ENVIRONMENTS` constant)
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
- `disconnected` rows are **skipped** entirely (user-intent status preserved)
- Each remaining row checked independently
- Decrypt failure → `status = "needs_reconnect"`, `last_error_code = "DECRYPT_FAILED"`, `error_message` sanitized
- Successful decrypt + status is `"needs_reconnect"` → recover to `"configured"`, clear error fields
- Successful decrypt + any other status → preserve status, do NOT clear error fields (they may be from Phase 2 auth errors)
- Errors logged to stderr (redacted), surfaced in Settings UI on next open
- If any rows marked `needs_reconnect`, log prominent key-mismatch hint (see Startup Flow)
- Exception handling uses narrowed types with `exc_info=True` for debugging

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
| `src/services/credential_encryption.py` | AES-256-GCM encrypt/decrypt with key length enforcement + key file management (platformdirs + env var override + key source info + platformdirs production warning) |
| `src/services/connection_service.py` | Connection CRUD, credential resolver, startup check (skips disconnected), AAD construction (with auth-mode switch safety), shared constants, runtime_usable computation, error message sanitization |
| `src/services/runtime_credentials.py` | Single adapter for runtime credential resolution (DB → env fallback, internal DB session acquisition) |
| `src/utils/redaction.py` | Secret redaction utility for safe logging and error responses (case-insensitive substring matching, nested dicts + lists, container keys) |
| `src/api/routes/connections.py` | REST endpoints for `/connections/*` with raw dict payloads (no Pydantic credential binding) |
| `frontend/src/components/settings/ConnectionsSection.tsx` | Accordion wrapper |
| `frontend/src/components/settings/ProviderCard.tsx` | Shared card component |
| `frontend/src/components/settings/UPSConnectForm.tsx` | UPS credential form |
| `frontend/src/components/settings/ShopifyConnectForm.tsx` | Shopify form (legacy token only in Phase 1) |
| `tests/services/test_credential_encryption.py` | Encryption tests (includes invalid base64, key source precedence, key length enforcement) |
| `tests/services/test_connection_service.py` | Service layer tests (includes auth_mode switching on same connection_key) |
| `tests/api/test_connections.py` | Route tests (includes 422 redaction verification via custom handler) |
| `tests/services/test_startup_check.py` | Startup check tests (includes wrong-key, key-mismatch hint, narrowed exception handling) |
| `tests/services/test_runtime_credentials.py` | Runtime resolver adapter tests (includes env mismatch, empty token filter) |
| `tests/integration/test_connection_round_trip.py` | Integration + edge case tests |

### Modified Files

| File | Change |
|------|--------|
| `src/db/models.py` | Add `ProviderConnection` model with `connection_key` |
| `src/db/connection.py` | Add `provider_connections` table migration (CREATE TABLE + PRAGMA introspection + unique index hardening + provider index) |
| `src/api/main.py` | Register `/connections` router + `check_all()` in lifespan with key source logging + platformdirs warning + custom `RequestValidationError` handler for `/connections/*` + narrowed startup exception handling |
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
| `frontend/src/types/api.ts` | Add connection types (metadata as `Record<string, unknown>`, `runtime_usable` field) |
| `frontend/src/components/sidebar/DataSourcePanel.tsx` | Replace Shopify form with Settings link, `runtime_usable` gating |
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
- New table auto-created by SQLAlchemy on startup, with column introspection and unique index hardening for upgrades
- Encryption key auto-generated in app-data dir (or loaded from env var)
- Key source logged at startup for diagnostics (with platformdirs production warning)
- `.env` vars work as fallback — no breaking changes
- DB takes precedence once user saves through Settings
- `runtime_credentials.py` adapter provides single resolution path for all call sites
- Status is `"configured"` after save — `"connected"` only set by live validation (Phase 2)
- Startup runs decryptability check only (no live validation, no env injection)
- `disconnected` and `needs_reconnect` means operationally disabled — not available for use
- Re-saving on a `disconnected` row resets to `configured`
- Shopify `client_credentials_shopify` hidden in UI (backend support exists)
- No ad hoc env reads outside `runtime_credentials.py` after integration
- Connection responses include server-side `runtime_usable` field
- Error messages sanitized and capped before DB persistence
- Key length enforced in both encrypt and decrypt functions
- Custom 422 handler prevents secret echo on `/connections/*` routes
- `check_all()` skips `disconnected` rows (user-intent preservation)
- `key_version` persisted as `1` (no rotation in Phase 1)
- `metadata_json` DB attr avoids SQLAlchemy `Base.metadata` collision
- Frontend types use strict `ProviderAuthMode` union (not bare `string`)
- Sanitizer covers Bearer tokens, JSON-style, quoted values, and multi-token lines
- Code review checklist enforces no ad hoc env reads beyond grep (includes `os.getenv` + indirect reads)
- `get_or_create_key()` handles concurrent startup race via `FileExistsError` retry
- `SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY` opt-in strict mode for ephemeral environments
- `SHIPAGENT_CREDENTIAL_KEY_FILE` validates file existence, readability, and type
- Env override precedence tested: env key wins over env file when both set
- Sanitizer documented as best-effort (not a parser); uncovered formats degrade gracefully

**Phase 2 (future):**
- UPS OAuth Authorization Code + PKCE loopback flow
- Shopify guided wizard with step-by-step instructions
- Shopify client-credentials token acquisition + auto-refresh scheduler
- Enable `client_credentials_shopify` radio option in Shopify form
- `POST /connections/{provider}/connect` — save + validate + connect
- `POST /connections/{connection_key}/test` — live credential test
- "Test" button in UI
- Connection health dashboard
- Key rotation support (leverages `key_version` column; defines rotation semantics, re-encryption flow)
- Multi-store Shopify UI (with explicit store selection in runtime paths)
- OS keychain / KMS integration options
- Explicit store selection required in all Shopify runtime paths (replace Phase 1 first-available default)
- Error status sub-classification (`auth_error` vs `network_error`)
- Export/import settings flow (excluding secrets or re-wrapping them)

## Phase 2 Notes

- **Operator key source hint:** Consider adding a UI indicator or `/connections/health` endpoint that shows key source metadata. When users move DB to another machine and everything becomes `needs_reconnect`, they won't know why unless logs are checked. Phase 1 logs this; Phase 2 could surface it in the UI to reduce support friction.
