# OpenAI App & Claude Connector — Technical Design

**Date:** 2026-06-10
**Status:** Approved — ready for implementation planning
**Supersedes in part:** `2026-06-08-provider-compatibility-design.md` (handoff subsystem, preview-only posture, bespoke OAuth)
**Execution model:** Subagent-driven development — one implementation plan per slice below

---

## 1. Summary

ShipAgent exposes its workflow tools to ChatGPT (OpenAI Apps SDK) and Claude (claude.ai custom connectors and the Messages API MCP connector) through the existing cloud MCP control plane. The **entire user experience — preview, confirmation, execution, tracking, label download — happens inside the provider app.** The local desktop runtime remains the execution authority (it owns imported rows, UPS credentials, BatchEngine, and label storage) and is reached through a cryptographically authenticated outbound relay.

The desktop relay is an **intermediary step toward a full SaaS backend.** Every provider-facing contract is therefore target-agnostic: the cloud dispatches through the `ExecutionTarget` protocol (ADR 0002), the relay is the first implementation, and a future SaaS worker replaces it without changing any public tool contract.

Three hard requirements carried from the June 5–6 component docs:

1. **Cryptographic relay identity** — Ed25519 proof-of-possession; no spoofed desktops.
2. **Relay-loss recovery** — deterministic provider responses for every disconnect mode.
3. **Ephemeral cloud-state retention** — TTL'd Redis state, scheduled purge, thin redacted durable audit.

The fourth proposed requirement, **cross-device confirmation handoff, is rejected** (ADR 0008): with in-provider execution there is nothing to hand off. Provider results may include a bare `shipagent://` deep link (no tokens, no confirmation semantics) for convenience.

## 2. What already exists (do not rebuild)

| Component | Location | State |
|---|---|---|
| Tool registry with `ToolContract` (incl. `max_sync_seconds`, `max_result_bytes`, `minimum_capabilities`, `rate_limit_class`, `prepare_tool`, `execution_target_required`, `result_profile`, provider exports) | `src/registry/` | Built; drift tests in `tests/registry/` |
| Public tool surface: `get_shipagent_status`, `submit_one_off_shipment`, `validate_shipment_address`, `get_shipment_rates`, `prepare_shipments`, `execute_shipments`, `get_job_status`, `create_label_download` | `src/registry/tools/public.py` | Built |
| Provider projections (OpenAI, Gemini, Microsoft, generic MCP) | `src/provider_adapters/` | Built |
| Cloud control plane: FastAPI app, Auth0 token verification, OAuth protected-resource metadata, Streamable HTTP `/mcp` mount, Redis `RequestControls` (rate limits), result projection, audit service, startup security guard | `src/control_plane/` | Built |
| `ConfirmationService` — one-time tokens, hash-stored, issue/validate/consume | `src/hosted/confirmation_service.py` | Built |
| UPS boundary (hosted `shipagent_v1` envelopes, validators, readiness) | `src/hosted/ups_boundary/` | Built |
| `ShippingWorkflowService` + `CarrierGateway` protocol | `src/workflows/` | Built |
| `provider-widget` Nx app scaffold | `shipagent-frontend/apps/provider-widget/` | Scaffolded |
| ADRs 0001 (Auth0 identity), 0002 (relay-first `ExecutionTarget`), 0003 (prepare/execute + one-time token) | `docs/adr/` | Accepted |

**Not built:** the desktop relay subsystem, cloud relay router and crypto handshake, invocation lifecycle and recovery, version gate, ephemeral TTL/purge, output profiles, the OpenAI widget content, desktop settings for cloud features, golden-prompt corpus.

## 3. Architecture

```
ChatGPT App / Claude connector / Claude API MCP
        │  HTTPS + Auth0 Bearer (existing)
        ▼
Cloud Control Plane  (src/control_plane — exists, extended)
   /mcp Streamable HTTP (exists) · OAuth metadata (exists) · Auth0 verify (exists)
   + relay router · device identity · version gate · ingress guard v2
   + ephemeral Redis state w/ TTLs · output profiles · thin redacted audit
        │  ExecutionTarget protocol  ← the SaaS seam (ADR 0002)
        ▼
RelayExecutionTarget → outbound WSS → ShipAgent Desktop  (new)
   Ed25519 keypair in OS keychain · PoP handshake · heartbeat w/ version metadata
   relay invocation dispatcher → existing workflow services
        │  unchanged
        ▼
BatchEngine → UPSMCPClient → ups-mcp (stdio, upstream, never modified)
```

### 3.1 Decisions

**D1 — In-provider end-to-end experience.** ADR 0003's `prepare_*` → `execute_*` model stays. Per-surface confirmation (ADR 0003 amendment):
- **OpenAI:** execution is triggered only by the confirmation widget's button — a user gesture, not a model-initiated call. The widget calls `execute_shipments` with the one-time token.
- **Claude:** conversational confirmation; the model calls `execute_shipments` with the token after the user agrees, additionally backed by Claude's native tool-approval prompt.
- Both paths consume the same `ConfirmationService` token bound to: account, provider connection, device, immutable preview hash, cost ceiling, expiry, and idempotency key. Neither surface can execute a shipment the user has not seen priced.

**D2 — Auth0 stays (ADR 0001).** No bespoke `/oauth/authorize`, `/oauth/token`, or JWKS endpoints. Incremental scope escalation uses Auth0 scopes plus the existing `WWW-Authenticate` resource-metadata challenge. Scope tiers: `shipagent.status` / `shipagent.read_summaries` (initial), `shipagent.preview`, `shipagent.execute` (consent-gated). Per-tool `auth_scopes` on `ToolContract` are enforced in the control plane middleware.

**D3 — Target-agnostic contracts (SaaS-forward).** Public tools and envelopes never encode "desktop":
- Status tool reports `executionTarget: {state: "ready" | "offline" | "update_required"}`.
- Machine reason codes are `target_offline`, `target_update_required` — not `desktop_*`.
- User-facing message text may say "your ShipAgent runtime" / "ShipAgent Desktop" for clarity, but no schema field does.
- The SaaS worker later implements `ExecutionTarget`; the provider surface does not change.

**D4 — Origin-based redaction (ADR 0007).** Replaces the blanket PII bans of the preview-only plan:
- Data the user supplied through the provider conversation (a one-off recipient address, a package weight) may be echoed back in results.
- Data originating from locally imported sources (rows, customer lists) is provider-visible **only as aggregates** (counts, totals, warning counts) — never as row arrays or full per-row addresses.
- Never provider-visible under any origin: UPS credentials, UPS account numbers, raw UPS payloads, label bytes/base64, keyring contents.
- Tracking numbers for shipments created in the current provider flow are visible in full (the user needs them). Tracking numbers surfaced from local job history are masked (`1Z999…9999`).
- Labels are delivered as short-lived signed download URLs (`create_label_download`, existing `artifact_action` result profile); the URL is provider-visible, the bytes stream desktop→cloud→browser and are never persisted cloud-side.

**D5 — Hard requirements.** Relay identity, relay-loss recovery, and ephemeral retention are blocking design requirements implemented in Plans 1, 2, and 4 respectively, with adversarial coverage in Plan 10.

**D6 — Handoff rejected (ADR 0008).** No handoff token service, no claim/push-to-desktop endpoints, no web fallback page.

### 3.2 Relay protocol (canonical module: `src/control_plane/relay/protocol.py`)

All envelope, handshake, heartbeat, and state definitions live in this one canonical module, imported by both cloud and desktop sides (per the canonical-data-models rule). Highlights:

- **Device identity:** Ed25519 keypair generated on the desktop when the user enables Cloud AI Features; private key in the OS keychain via the existing `keyring` infrastructure; public key registered cloud-side as a `RelayDevice` bound to `account_id + device_id + fingerprint`. Rotate and revoke flows; revocation immediately severs the session.
- **Handshake:** desktop opens outbound `WSS /relay/connect`; cloud issues nonce + `relay_session_id`; desktop returns a short-lived JWT signed with its device key carrying `sub=device_id`, `aud=shipagent-cloud-relay`, account binding, nonce, expiry, and version metadata (`shipagent_core_version`, `registry_contract_version`, `ups_boundary_contract_version`, capability list). Cloud verifies signature, binding, nonce freshness, audience, expiry, revocation, and version compatibility before accepting.
- **Invocation envelopes:** every cloud→desktop invocation carries `relay_invocation_id`, tool name, input hash, deadline, idempotency key, audit correlation ID, and a session-bound MAC so a compromised connection cannot replay prior calls.
- **Heartbeat:** version metadata + capability list + opaque active-source fingerprint, refreshed continuously; Redis TTL 60–120 s.

### 3.3 Invocation lifecycle and recovery

States: `queued → sent_to_target → accepted → running → result_returned`, with failure exits `target_offline_before_accept`, `target_disconnected_mid_call`, `deadline_exceeded`, `abandoned`, `recovered_by_poll`.

Timeout ladder: 2 s cloud send → 5 s target accept → 25 s sync hard deadline (under the 30 s provider budget). Tools that may exceed it follow the async contract: immediate `{status: "processing", jobRef, pollToken, pollAfterMs}` response, polled via `get_job_status`. No MCP session memory; the model passes `jobRef`/`pollToken` explicitly.

Recovery: on reconnect, the desktop reports outstanding local jobs and invocation IDs; the cloud reconciles `processing_unknown` invocations to `recovered_by_poll`. Cloud→relay automatic retries are permitted only for invocations that never reached `accepted`. `execute_shipments` is idempotency-keyed end to end: a duplicate call with the same token returns the original result, never a second charge.

### 3.4 Ephemeral retention

| Data | Store | TTL |
|---|---|---|
| Relay heartbeat | Redis | 60–120 s |
| Relay session metadata | Redis | disconnect + 5 min |
| Invocation state | Redis | 24 h |
| `jobRef` mapping, redacted preview summary, poll token | Redis | 24 h |
| Confirmation token hash | DB via `ConfirmationService` | token expiry (short) |
| Rate-limit / loop-breaker counters | Redis | sliding windows |
| Durable cloud audit (provider, account, tool, result category, duration, device fingerprint, correlation IDs only) | SQL | configurable |

A purge job sweeps Redis key patterns every 5 minutes. The desktop remains the source of truth for jobs, rows, previews, labels, and detailed audit.

### 3.5 Error envelope contract

Every provider-facing failure is a **schema-valid result**, never an MCP protocol error:

```json
{"status": "blocked|unavailable|processing_unknown",
 "reason": "machine_code", "terminal": true,
 "message": "model-readable instruction stating what the user should do"}
```

Terminal reasons (`target_update_required`, `repeated_tool_call`, `token_expired`, `token_replayed`, `target_offline` before accept) instruct the model not to retry. Non-terminal (`processing_unknown`) carries `jobRef` + `pollAfterMs`. Reason codes register as **E-6xxx** in the error registry. Raw UPS `ToolError` payloads always map through the hosted safe-category envelopes.

### 3.6 Ingress guard v2

Extends the existing `RequestControls`: per-account/tool token buckets (exists), canonical input hashing, duplicate-call collapse, in-flight coalescing, a semantic loop breaker emitting the terminal `repeated_tool_call` envelope, and result-size caps from each contract's `max_result_bytes`.

### 3.7 Output profiles

`result_projection.py` gains explicit profiles — `OPENAI_STRUCTURED`, `OPENAI_WIDGET_META` (widget-only payloads, still redacted), `CLAUDE_MARKDOWN` (compact tables, ≤150k-char Claude limit with headroom) — all applying the D4 origin-based redaction rules. Both providers share deterministic handlers; only metadata and formatting differ.

## 4. Slice map — 10 plans, 4 waves

### Wave 0 (serial)

**Plan 1 — Relay walking skeleton.** Canonical protocol module; cloud `WS /relay/connect` + `POST /relay/devices/{register,rotate-key,revoke}`; Redis device-session registry; desktop `relay_key_service.py` + `desktop_relay_client.py`; `RelayExecutionTarget`; `LoopbackExecutionTarget` test fixture. **Exit:** `get_shipagent_status` answered by a real desktop process through cloud `/mcp`, and by loopback in CI. Deliberately the largest slice: splitting cloud/desktop halves would reintroduce fixture drift.

### Wave 1 (parallel after Plan 1 — disjoint file sets)

**Plan 2 — Invocation lifecycle + relay-loss recovery.** State machine, timeout ladder, reconnect reconciliation, degraded envelopes, async/poll contract. (`src/control_plane/relay/lifecycle.py`, dispatcher changes desktop-side.)
**Plan 3 — Version gate.** Heartbeat version enforcement against a compatibility matrix derived from `ToolContract.minimum_capabilities`; `target_update_required` envelope. (`src/control_plane/relay/version_gate.py`.)
**Plan 4 — Ephemeral retention + purge + cloud audit.** TTL policy in `redis_keys.py`, purge job, thin durable audit models.
**Plan 5 — Ingress guard v2.** Loop breaker, dedupe, coalescing, result caps in `request_controls.py`.
**Plan 6 — Output profiles + origin-based redaction.** Profiles in `result_projection.py`; origin tagging on workflow inputs; aggregate projection for local-source data; tracking-number masking rules.
**Plan 9 — Desktop settings + device management** (only needs Plan 1). Cloud AI Features enablement in settings-remote (generate key, register, status), device list with revoke/rotate, relay status indicator, Tauri keychain entitlement check.

### Wave 2

**Plan 7 — In-provider execution flow** (needs Plans 2 + 6). `prepare_shipments` issues `ConfirmationService` token in the preview result → `execute_shipments` through the relay with token validation, cost ceiling, idempotency on the BatchEngine path → `get_job_status` → `create_label_download` signed-URL streaming (desktop→cloud→browser, no cloud persistence). Execute-scope enforcement (`shipagent.execute`).
**Plan 8 — OpenAI widget** (needs Plan 6 schema). `provider-widget`: rates, preview/confirm with the execute button gesture, job progress, label download action; served as MCP Apps HTML resources via existing `ui_resource` fields.

### Wave 3

**Plan 10 — Golden prompt + adversarial corpus** (needs Plans 7 + 8). `tests/provider_golden/prompts.yaml`: tool selection, confirmation behavior on both surfaces, loop retry, target-offline, token replay, spoofed-relay handshake, PII/raw-UPS leakage, oversized results, missing-jobRef. Claude API allowlist smoke config (beta `mcp-client-2025-11-20`), MCP Inspector scripts, ChatGPT developer-mode checklist.

### Dependency graph

```
Plan 1 ──┬─→ Plan 2 ──┬─→ Plan 7 ──┬─→ Plan 10
         ├─→ Plan 3   │            │
         ├─→ Plan 4   │            │
         ├─→ Plan 5   │            │
         ├─→ Plan 6 ──┴─→ Plan 8 ──┘
         └─→ Plan 9
```

**Critical path:** 1 → 2 → 7 → 10 (4 sessions). **Peak concurrency:** 6 agents in Wave 1 (Plans 2–6 + 9). Plans 3, 4, 5 are small; 1, 2, 7 are the heavy ones.

## 5. Testing strategy

- Every plan: unit tests + integration test against `LoopbackExecutionTarget`.
- Plans 1, 2, 7: additionally a two-process integration test (real WSS, real Ed25519 handshake, in-memory Redis).
- UPS calls in tests: hosted fixtures and UPS CIE only.
- Claude-surface tests: synthetic data only (the Claude MCP connector is not ZDR-eligible).
- Registry drift tests must pass after every contract change; provider artifacts stay generated via `scripts/generate_provider_artifacts.py` — never hand-edited.
- Security checks land with their slice and are re-attacked in Plan 10: handshake rejection matrix (unregistered key, stale nonce, wrong audience, revoked device, incompatible version), envelope replay, token one-time/binding properties, per-tool scope enforcement.

## 6. Out of scope

- SaaS worker implementation (only the `ExecutionTarget` seam it will use).
- Handoff/push-to-desktop subsystem (rejected, ADR 0008).
- Multi-device-per-account routing — one Active Desktop Device per account (ADR 0002).
- New UPS capabilities: void, pickup, paperless, landed cost, raw tools remain unexported to public providers.
- Any modification to the upstream `ups-mcp` package.

## 7. ADR deltas (committed with this spec)

- **ADR 0003 (amended):** per-surface confirmation — OpenAI widget gesture, Claude conversational, same one-time token.
- **ADR 0004 (new):** cryptographic desktop relay identity (Ed25519 PoP, keychain storage, rotate/revoke).
- **ADR 0005 (new):** ephemeral cloud-state retention (TTLs, purge, thin redacted audit).
- **ADR 0006 (new):** relay version compatibility gate.
- **ADR 0007 (new):** origin-based provider redaction.
- **ADR 0008 (new):** in-provider execution adopted; cross-device handoff rejected.
