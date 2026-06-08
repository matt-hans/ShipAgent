# ShipAgent Provider Compatibility Design
**Date:** 2026-06-08
**Status:** Approved — ready for implementation planning
**First implementation tranche:** Phases 0–2 (ADR pack + registry hardening + cloud skeleton)

---

## 1. Executive Summary

ShipAgent exposes a public, OAuth-protected, registry-driven MCP control plane to OpenAI ChatGPT and Claude connectors, while keeping all real shipping data, UPS credentials, imported rows, labels, and deterministic execution inside the local ShipAgent desktop runtime.

The MVP topology is **Hybrid Relay** — the cloud is a control plane and relay broker, not a shipping backend. Full SaaS execution (hosting tenant order data cloud-side) is explicitly deferred (ADR-009).

---

## 2. Architecture and Topology

### 2.1 Component Diagram

```
OpenAI ChatGPT App / Apps SDK
Claude.ai Custom Connector
Claude Messages API MCP Connector
        │  HTTPS + OAuth (Bearer token)
        ▼
ShipAgent Cloud MCP Control Plane         [new service — src/hosted_mcp/cloud_server.py]
  ├── GET  /.well-known/oauth-protected-resource
  ├── GET  /.well-known/oauth-authorization-server
  ├── POST /oauth/authorize
  ├── POST /oauth/token
  ├── GET  /oauth/jwks.json
  ├── POST /mcp                  (Streamable HTTP MCP — relay-first tool surface)
  ├── GET  /health + /ready
  ├── WS   /relay/connect        (Ed25519 PoP JWT handshake — stub in Phase 2)
  ├── POST /relay/devices/*      (register, rotate-key, revoke — stub in Phase 2)
  └── POST /handoffs/*           (claim, push-to-desktop, status — stub in Phase 2)
        │  WSS + Ed25519 proof-of-possession JWT  [Phase 3+]
        ▼
ShipAgent Desktop Relay                   [new modules — src/services/desktop_relay_client.py]
  ├── Outbound WebSocket to cloud
  ├── Heartbeat (version metadata, capability list, active source fingerprint)
  ├── Ed25519 private key in OS keychain (macOS Keychain / libsecret)
  ├── Local FastAPI sidecar bridge
  ├── Local data-source gateway (DuckDB, single active source)
  ├── Local SQLite runtime (unchanged)
  ├── Local confirmation UI (unchanged)
  └── Local UPSMCPClient boundary (unchanged)
        │  stdio (unchanged)
        ▼
ups-mcp stdio server                      [upstream dep — never changed by ShipAgent]
  ├── hosted shipagent_v1: rate_shipment, validate_address, create_shipment
  └── raw mode: all tools (behind ShipAgent-side projection only)
```

### 2.2 What Does NOT Change

The following existing components are untouched by this work:
- `OrchestrationAgent` and all Claude Agent SDK adapter code
- `BatchEngine` and `UPSMCPClient`
- `AgentSessionManager`
- All existing FastAPI routes and SSE conversations
- Local `SQLite` / `DuckDB` persistence
- The Angular/Nx frontend (except Phase 6+ additions to settings-remote and chat-remote)
- `ups-mcp` upstream package (never modified by ShipAgent)

### 2.3 Non-Negotiable Invariants

These are unconditional. Any code change that violates them must be reverted:

1. No raw row-level shipping data, customer PII, credentials, labels, raw UPS payloads, or unmasked tracking numbers enter provider-visible tool results or model prompts.
2. OpenAI and Claude can prepare previews and rate estimates but cannot purchase labels, void shipments, schedule pickups, or write back tracking — these are UI-only operations.
3. UPS access stays behind `UPSMCPClient` and workflow wrappers. Provider tools never import or call `ups-mcp` directly.
4. Provider adapters remain translation layers. Business logic stays in workflow services and registry-owned tool metadata.
5. The cloud control plane stores only opaque references and redacted summaries. No tenant order data, no PII, no labels, no raw UPS payloads.

---

## 3. Infrastructure Decisions

| Concern | Decision | Rationale |
|---------|----------|-----------|
| Cloud hosting | Railway / Render / Fly.io (containerized PaaS) | Compatible with existing docker-compose setup; minimal ops overhead |
| Cloud ephemeral state | Redis (Upstash or Railway Redis) — required from day one | Keeps control plane stateless and horizontally scalable; no in-memory fallback |
| OAuth AS | Bespoke implementation in `cloud_server.py` | Full control; matches RFC 9728 + PKCE requirements; no external SaaS dependency |
| MCP transport | Streamable HTTP (preferred per Claude docs) | Legacy HTTP+SSE deprecated; Streamable HTTP supported by both OpenAI and Claude |
| Desktop relay transport | Outbound WSS from desktop to cloud | Traverses NAT and firewalls; no inbound port required on user's machine |
| Desktop key algorithm | Ed25519 (RSA-2048/3072 only if platform constraints require) | Compact JWTs, fast signing/verification |
| ADR location | `docs/adr/` | Standard location; CLAUDE.md already references `docs/adr/` as a skills read target |
| Spec location | `docs/superpowers/specs/` | Consistent with other superpowers specs |

---

## 4. Registry Changes (Phase 1)

### 4.1 ProviderExport Enum — New Values

Two new values are appended to the existing `ProviderExport` StrEnum (existing values unchanged):

```python
class ProviderExport(StrEnum):
    openai = "openai"                                     # existing
    anthropic = "anthropic"                               # existing
    microsoft = "microsoft"                               # existing
    gemini = "gemini"                                     # existing
    generic_mcp = "generic_mcp"                           # existing
    openai_apps_public = "openai_apps_public"             # NEW
    claude_remote_mcp_public = "claude_remote_mcp_public" # NEW
```

`openai_apps_public` — relay-first ChatGPT App / Apps SDK surface. Includes `_meta.ui.resourceUri` for widget tools via `openai_projection.py`.

`claude_remote_mcp_public` — relay-first Claude.ai connector and Claude Messages API MCP surface. Claude-specific markdown output profile; no widget metadata. Handled by new `src/provider_adapters/claude_mcp_projection.py`.

### 4.2 ToolContract — New Fields

All new fields have safe defaults so existing tool definitions remain valid without modification:

```python
# Relay requirements
requires_desktop_relay: bool = False
requires_online_desktop: bool = False

# Async contract
async_mode: Literal["sync_only", "async_allowed", "async_required"] = "sync_only"
max_sync_duration_ms: int = 25_000          # hard deadline before async_required applies
max_result_bytes: int = 50_000              # Claude 150k char limit leaves headroom

# Rate limiting and loop breaking
rate_limit_class: RateLimitClass = RateLimitClass.standard
loop_breaker_class: LoopBreakerClass = LoopBreakerClass.none

# Handoff and cross-device
handoff_behavior: HandoffBehavior = HandoffBehavior.none

# Version compatibility gating
min_desktop_core_version: str | None = None
min_registry_contract_version: str | None = None
min_ups_boundary_contract_version: str | None = None  # e.g. "hosted-v1"

# Incremental OAuth
incremental_auth_scopes: list[str] = []

# Provider behavior hints
model_behavior_hint: str = ""
user_facing_completion_text: str = ""
```

New enums added to `src/registry/models.py`:

```python
class RateLimitClass(StrEnum):
    none = "none"
    standard = "standard"       # status/read tools: 30/min
    preview = "preview"         # preview/handoff: 3/min
    rate_query = "rate_query"   # rate tools: 6/min

class LoopBreakerClass(StrEnum):
    none = "none"
    idempotent_hash = "idempotent_hash"  # collapse identical input calls
    semantic = "semantic"                 # detect semantic repeats

class HandoffBehavior(StrEnum):
    none = "none"
    create_token = "create_token"  # tool result includes handoffUrl + desktopDeepLink
```

### 4.3 New Relay-First Public Tool Surface

Added to `src/registry/tools/public.py` as a separate `RELAY_TOOLS` list (included in `all_tools()`). `scripts/generate_provider_artifacts.py` is extended to filter by `ProviderExport.openai_apps_public` and `ProviderExport.claude_remote_mcp_public` and write the two new artifact files. These tools use `provider_exports=[ProviderExport.openai_apps_public, ProviderExport.claude_remote_mcp_public]`.

| Tool name | relay? | async_mode | rate_limit_class | handoff_behavior | Phase 2 handler |
|-----------|--------|-----------|-----------------|-----------------|-----------------|
| `shipagent_status` | No | sync_only | standard | none | Live |
| `shipagent_desktop_status` | No | sync_only | standard | none | Live |
| `shipagent_validate_address_preview` | Yes | sync_only | rate_query | none | Stub (relay not configured) |
| `shipagent_rate_preview` | Yes | async_allowed | rate_query | none | Stub |
| `shipagent_prepare_interactive_preview` | Yes | async_allowed | preview | create_token | Stub |
| `shipagent_get_preview_status` | Maybe | sync_only | rate_query | none | Stub |
| `shipagent_render_preview_widget` | No | sync_only | standard | none | Stub (OpenAI only) |

`shipagent_render_preview_widget` has `provider_exports=[ProviderExport.openai_apps_public]` only.

### 4.4 Existing SaaS-Path Tools

The existing tools in `PUBLIC_TOOLS` (`connect_carrier_account`, `upload_or_import_orders`, `preview_shipments`, `create_shipments`, etc.) remain unchanged. They retain `provider_exports=[ProviderExport.openai, ProviderExport.microsoft, ProviderExport.gemini, ProviderExport.generic_mcp]`. Their `hosted_readiness` values reflect the full SaaS backend path, which is deferred (ADR-009).

### 4.5 CI Validators

`tests/registry/test_models.py` extended with validators that **fail CI** if any `openai_apps_public` or `claude_remote_mcp_public` tool:
- Lacks a non-empty `output_schema`
- Lacks `max_sync_duration_ms`
- Has `async_mode == "sync_only"` and `max_sync_duration_ms > 30_000`
- Lacks `auth_scopes`
- Has `side_effect in {write, purchase, external_mutation, destructive}` and `requires_desktop_relay == False` (relay-exported tools with side effects must go through relay)
- Is `provider_export_enabled=True` without `min_desktop_core_version` set
- Has `result_sensitivity == ResultSensitivity.confidential`

All relay-first tools must pass `scripts/generate_provider_artifacts.py` and drift tests (`tests/registry/test_artifact_drift.py`) before merging.

### 4.6 New Provider Artifacts

Two new artifact files added to `generated/provider_artifacts/`:
- `openai_apps_relay_tools.json` — relay-first tools in OpenAI app tool format (with `_meta.ui.resourceUri` where applicable)
- `claude_remote_mcp_tools.json` — relay-first tools in generic MCP format (used by `src/hosted_mcp/cloud_server.py`)

New provider projection module: `src/provider_adapters/claude_mcp_projection.py` — identical to `mcp_projection.py` for now, but diverges as Claude-specific output profiles are added.

---

## 5. Cloud MCP Control Plane (Phase 2)

### 5.1 Module Layout

```
src/hosted_mcp/
  __init__.py
  server.py               # existing — generic hosted MCP server, unchanged
  cloud_server.py         # NEW — FastAPI app for the cloud control plane
  provider_profiles.py    # NEW — OpenAI and Claude provider profile metadata
  oauth/
    __init__.py
    server.py             # NEW — PKCE authorization server, token endpoint, JWKS
    models.py             # NEW — Pydantic models for OAuth flows
    tokens.py             # NEW — JWT signing/verification (Ed25519 or RS256)
  relay/
    __init__.py
    router.py             # NEW — WS /relay/connect stub + future relay routing
    auth.py               # NEW — relay JWT verification stub
    models.py             # NEW — relay session, invocation, heartbeat models
  handoff/
    __init__.py
    service.py            # NEW — handoff token stub
    models.py             # NEW — HandoffToken, HandoffStatus models
  ephemeral_store.py      # NEW — Redis client wrapper (TTL-aware key helpers)
  ingress_guard.py        # NEW — rate-limit + loop-breaker stub (Phase 9 fills in)
  output_sanitizer.py     # NEW — ProviderOutputProfile enum + sanitize() stub
  Dockerfile              # NEW — cloud control plane container
```

Supporting service modules:
```
src/services/
  provider_consent_service.py   # NEW — scope grant persistence
  provider_audit_projection.py  # NEW — redacted cloud audit event writer
```

New routes (added to `src/api/routes/` for the cloud app, not the local FastAPI app):
```
src/api/routes/
  oauth.py    # NEW
  handoff.py  # NEW
  relay.py    # NEW
```

### 5.2 Endpoint Specifications

#### OAuth Discovery

`GET /.well-known/oauth-protected-resource` — RFC 9728 response:
```json
{
  "resource": "https://mcp.shipagent.cloud",
  "authorization_servers": ["https://mcp.shipagent.cloud"],
  "bearer_methods_supported": ["header"],
  "resource_documentation": "https://mcp.shipagent.cloud/docs"
}
```

`GET /.well-known/oauth-authorization-server` — RFC 8414 response including `scopes_supported`, `code_challenge_methods_supported: ["S256"]`, `response_types_supported: ["code"]`.

`GET /oauth/jwks.json` — JWK Set with public key used to verify issued access tokens.

#### OAuth Token Flow

`POST /oauth/authorize` — PKCE authorization endpoint. Validates `client_id`, `redirect_uri`, `code_challenge`, `code_challenge_method=S256`, `scope`. Issues a short-lived authorization code (stored in Redis, TTL 10 minutes).

`POST /oauth/token` — exchanges `authorization_code` for `access_token` (JWT, TTL 1 hour) + `refresh_token` (opaque, TTL 30 days). Server verifies `code_verifier` against stored `code_challenge`. Validates issuer, audience, expiry, and replay on every call.

#### MCP Endpoint

`POST /mcp` — Streamable HTTP MCP. Validates Bearer token (JWT, verifies signature against JWKS, checks issuer/audience/expiry/scopes). Serves relay-first tools from `claude_remote_mcp_tools.json` (generated artifact). In Phase 2, `shipagent_status` and `shipagent_desktop_status` have live handlers; all relay-required tools return:
```json
{
  "status": "relay_not_configured",
  "reason": "desktop_relay_required",
  "terminal": false,
  "message": "ShipAgent Desktop must be running and connected before this tool can be used. Open ShipAgent Desktop and enable Cloud AI Features."
}
```

#### Relay Stubs (Phase 2 — correct route shape, 501/426 body)

`WS /relay/connect` — returns HTTP 426 Upgrade Required until Phase 3.
`POST /relay/devices/register` — returns HTTP 501 Not Implemented until Phase 3.
`POST /relay/devices/{device_id}/rotate-key` — returns HTTP 501.
`POST /relay/devices/{device_id}/revoke` — returns HTTP 501.

#### Handoff Stubs (Phase 2)

`POST /handoffs/{handoff_token}/claim` — returns HTTP 501.
`POST /handoffs/{handoff_token}/push-to-desktop` — returns HTTP 501.
`GET /handoffs/{handoff_token}/status` — returns HTTP 501.

### 5.3 OAuth Scope Definitions

Initial scopes served by the authorization server:

| Scope | Purpose | Initial grant |
|-------|---------|--------------|
| `shipagent.status` | Cloud/desktop readiness checks | Yes |
| `shipagent.desktop_status` | Desktop relay status | Yes |
| `shipagent.read_summaries` | Redacted summaries and audit | Yes |
| `shipagent.preview` | Prepare previews, rate queries, address validation | Incremental |
| `shipagent.handoff` | Create and claim handoff tokens | Incremental |
| `shipagent.ship.execute` | Label purchase (withheld) | Withheld |
| `shipagent.ship.void` | Void shipment (withheld) | Withheld |
| `shipagent.pickup.schedule` | Schedule pickup (withheld) | Withheld |
| `shipagent.writeback.execute` | Tracking write-back (withheld) | Withheld |
| `shipagent.admin` | Admin operations (withheld) | Withheld |

Consent screen copy (displayed at OAuth authorize):
```
Connect ChatGPT/Claude to ShipAgent

This connection CAN:
✓ Check whether ShipAgent Desktop is online.
✓ Validate addresses (redacted summaries only).
✓ Estimate shipping rates.
✓ Prepare shipment previews.
✓ Create a handoff link so you can confirm inside ShipAgent.

This connection CANNOT:
✗ Purchase labels.
✗ Void shipments.
✗ Schedule pickups.
✗ Update any connected store or data source.
✗ Read full customer rows.
✗ View UPS credentials.
✗ View label files.
✗ View unmasked tracking numbers.
```

### 5.4 Redis Key Schema

All keys are prefixed with `sa:` and include tenant and provider context. TTLs are enforced by Redis EX, not by application logic:

| Key pattern | TTL | Contents |
|-------------|-----|---------|
| `sa:relay:heartbeat:{device_id}` | 120s | Last heartbeat timestamp + version metadata |
| `sa:relay:session:{relay_session_id}` | Until disconnect + 5min | Session metadata (no PII) |
| `sa:invocation:{relay_invocation_id}` | 24h | Status enum + opaque routing IDs |
| `sa:jobref:{job_ref}` | 24h | Maps provider-visible ref → tenant+local job ref (opaque) |
| `sa:preview:{job_ref}` | 24h | Redacted preview summary (no row data, no full address, no labels) |
| `sa:handoff:{token_hash}` | 30min | One-time claim state (hashed token only, no PII) |
| `sa:poll:{poll_token}` | 24h | Opaque poll token → job ref mapping |
| `sa:ratelimit:{tenant_id}:{provider}:{tool}` | Sliding windows | Token bucket counters |
| `sa:loopbreaker:{tenant_id}:{provider}:{input_hash}` | 10min | Duplicate call fingerprint |
| `sa:oauth:authcode:{code_hash}` | 10min | PKCE authorization code state |
| `sa:oauth:refresh:{token_hash}` | 30d | Refresh token state |

### 5.5 Deployment

```dockerfile
# src/hosted_mcp/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[cloud]"
COPY src/ ./src/
EXPOSE 8080
CMD ["uvicorn", "src.hosted_mcp.cloud_server:app", "--host", "0.0.0.0", "--port", "8080"]
```

`pyproject.toml` gets a new `[cloud]` optional dependency group: `fastapi`, `uvicorn`, `redis[hiredis]`, `python-jose[cryptography]`, `pydantic`.

`docker-compose.cloud.yml` (local cloud plane dev):
```yaml
services:
  cloud:
    build: { context: ., dockerfile: src/hosted_mcp/Dockerfile }
    ports: ["8080:8080"]
    environment:
      REDIS_URL: redis://redis:6379/0
      JWT_PRIVATE_KEY_PATH: /run/secrets/cloud_jwt_key
      SHIPAGENT_CLOUD_DOMAIN: localhost:8080
    depends_on: [redis]
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
```

---

## 6. Desktop Relay Modules (Phase 3 — not in first implementation plan)

Documented here for completeness; the first plan covers only the stubs declared in Phase 2.

New modules (Phase 3):
- `src/services/desktop_relay_client.py` — manages outbound WSS connection, reconnect, heartbeat
- `src/services/relay_key_service.py` — Ed25519 keypair generation, OS keychain storage, rotation
- `src/services/relay_invocation_dispatcher.py` — receives relay envelopes, dispatches to local FastAPI
- `src/services/relay_heartbeat_service.py` — sends version metadata heartbeats
- `src/services/handoff_claim_service.py` — listens for push-to-desktop commands, opens local confirmation modal
- `src/api/routes/relay_local.py` — local-only relay bridge endpoints (not exposed publicly)
- `src-tauri/src/deeplink.rs` — handles `shipagent://handoff/...` deep links
- `src-tauri/src/relay.rs` — Tauri plugin for relay lifecycle (enable/disable Cloud AI Features)

Desktop relay heartbeat payload (Phase 3):
```json
{
  "deviceId": "dev_...",
  "shipagentCoreVersion": "0.9.4",
  "registryContractVersion": "2026-06-08.1",
  "providerArtifactsVersion": "2026-06-08.1",
  "upsBoundaryContractVersion": "hosted-v1",
  "upsMcpPackageVersion": "x.y.z",
  "supports": ["relay.invoke.v1", "handoff.push.v1", "preview.prepare.v1", "rate.preview.v1"],
  "activeSourceState": { "hasActiveSource": true, "sourceFingerprint": "opaque" }
}
```

---

## 7. Provider Output Sanitizer (Phase 11 — referenced for context)

```python
class ProviderOutputProfile(StrEnum):
    openai_structured = "openai_structured"   # Compact JSON summary + opaque refs + handoff URL
    openai_widget_meta = "openai_widget_meta" # Widget-visible preview summary + actions
    claude_markdown = "claude_markdown"        # Human-readable markdown table + safe refs
    relay_internal = "relay_internal"          # Cloud↔desktop routing only — never provider-visible
```

Forbidden fields in any `openai_structured` or `claude_markdown` result: full addresses, names (unless user-typed in same prompt), emails, phone numbers, UPS account number, UPS credentials, label base64, raw UPS payloads. Tracking numbers masked: `1Z9999999999999999 → 1Z999…9999`.

---

## 8. Security Model

### 8.1 Provider Edge (Cloud)
- All `/mcp` requests require valid Bearer JWT (issuer, audience, expiry, scopes, replay)
- OAuth PKCE only (no implicit flow, no client_credentials without PKCE)
- `hmac.compare_digest` for all token comparisons
- CORS restricted to known provider origins
- Rate limits enforced before any relay dispatch

### 8.2 Relay Edge (Cloud↔Desktop)
- Ed25519 proof-of-possession JWT on WebSocket upgrade (Phase 3)
- Nonce freshness check (TTL 60s)
- Device revocation checked on every relay connection attempt
- Relay invocation envelopes signed/MAC-bound to prevent replay

### 8.3 Execution Edge (Desktop)
- Provider-originated jobs carry `origin` metadata
- Confirm endpoint rejects: missing/stale preview hash, provider-only approval, reused/expired handoff token, tenant/device mismatch, job already running, source checksum/schema drift

### 8.4 Data Isolation
- Cloud Redis stores only opaque IDs and redacted summaries (TTL ≤ 24h)
- No PII, row data, labels, credentials, or raw UPS payloads ever written to cloud storage
- Cloud audit log stores only: provider, tenant, tool name, result category, duration, rate-limit decision, relay device ID, opaque correlation IDs

---

## 9. Phase Sequence Summary

| Phase | Goal | First plan? |
|-------|------|-------------|
| 0 | ADR pack (9 ADRs in docs/adr/) | ✓ Yes |
| 1 | Registry hardening: ToolContract extension, new tools, new artifacts, CI validators | ✓ Yes |
| 2 | Cloud control plane skeleton: OAuth AS, /mcp, relay stubs, deployment | ✓ Yes |
| 3 | Cryptographic relay identity: Ed25519 keypair, WSS handshake, device register/revoke | Later |
| 4 | Relay version compatibility gate | Later |
| 5 | Incremental OAuth and consent design | Later |
| 6 | Cross-device handoff and push-to-desktop | Later |
| 7 | Relay disconnection and degraded responses | Later |
| 8 | Ephemeral cloud-state retention and purge | Later |
| 9 | Provider ingress guard: rate limits, loop breaker, duplicate collapse | Later |
| 10 | Async/stateless tool contract | Later |
| 11 | Provider output sanitizer v3 | Later |
| 12 | UPS boundary hardening | Later |
| 13 | OpenAI app implementation (tool-only, then widget) | Later |
| 14 | Claude connector implementation | Later |
| 15 | Shipment execution safety hardening | Later |
| 16 | Golden prompt and adversarial test corpus | Later |

---

## 10. CI and Test Matrix (Phases 0–2)

### Phase 0 (ADRs)
ADRs are markdown documents — no test additions. Reviewed and approved before Phase 1 starts.

### Phase 1 (Registry hardening)
```bash
pytest tests/registry/test_catalog.py
pytest tests/registry/test_models.py        # includes new relay-tool validators
pytest tests/registry/test_artifact_drift.py
pytest tests/provider_adapters/test_projections.py
pytest tests/provider_adapters/test_openai_apps_projection.py
pytest tests/provider_adapters/test_claude_mcp_projection.py  # NEW
python scripts/generate_provider_artifacts.py && git diff --exit-code generated/provider_artifacts/
```

### Phase 2 (Cloud skeleton)
```bash
pytest tests/hosted/test_hosted_mcp_registry.py
pytest tests/hosted/test_openai_mcp_contract.py
pytest tests/hosted/test_claude_mcp_contract.py
pytest tests/api/test_oauth_metadata.py
pytest tests/api/test_provider_oauth_flow.py
pytest tests/hosted/test_result_size_caps.py
```

---

## 11. Readiness Criteria for This Phase

The Phases 0–2 implementation is complete when:

1. All 9 ADRs exist in `docs/adr/` and are committed.
2. `ToolContract` carries all relay, version, TTL, and auth fields with safe defaults.
3. Both `openai_apps_public` and `claude_remote_mcp_public` exist in `ProviderExport`.
4. All 7 relay-first tools are in the registry and pass CI validators.
5. `openai_apps_relay_tools.json` and `claude_remote_mcp_tools.json` are generated and committed.
6. The cloud FastAPI app starts, serves OAuth metadata, and returns valid responses from `POST /mcp` for `shipagent_status` and `shipagent_desktop_status`.
7. Relay stubs return the correct HTTP status codes (426 for WSS, 501 for device/handoff endpoints).
8. The Dockerfile builds and the app passes `/health` + `/ready` inside the container.
9. `docker-compose.cloud.yml` starts both the cloud app and Redis without error.
10. All registry and cloud MCP tests pass without database or relay state.

---

## 12. Rejected Alternatives

| Alternative | Rejected because |
|------------|-----------------|
| Expose local Tauri sidecar directly to providers | OS-assigned localhost port not reachable from provider cloud infra. NAT, VPN, firewall issues make this unreliable as a public endpoint. |
| Expose ups-mcp directly to OpenAI/Claude | Violates invariant: raw UPS payloads and credentials must never enter provider-visible paths. ups-mcp raw mode has no PII/payload sanitization. |
| Full SaaS backend for MVP | Current data-source gateway has a process-local DuckDB model and single-active-source constraint. Moving tenant data cloud-side requires a major persistence refactor. Deferred as ADR-009. |
| In-memory fallback for Redis | Would require maintaining two code paths. Cloud control plane should be stateless from day one. |
| Managed IdP (Auth0/Clerk) | Adds an external SaaS billing dependency and changes the OAuth flow in ways that complicate provider-specific auth challenges. |
| OpenAI widget before tool-only validation | Widget development without validated tool flows leads to assumptions about provider model behavior that golden prompts must correct. Tool-only pass first. |
