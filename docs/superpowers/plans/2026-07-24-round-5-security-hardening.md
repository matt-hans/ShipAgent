# Round 5 Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all six verified Round 5 provider-boundary, error-sanitization, browser-session, CSRF, and session-expiry blockers without weakening prior fixes.

**Architecture:** Canonical registry helpers make every exported scalar structurally bounded and generated artifacts inherit those constraints. Hosted MCP uses one post-exception generic error path. Browser authentication derives an in-memory CSRF token from the exact signed session, validates trusted origins before rate-limit accounting, and shares session loss across HttpClient, native fetch, and EventSource transports.

**Tech Stack:** Python 3.12, FastAPI/Starlette, FastMCP, Pydantic, JSON Schema, pytest, Angular 21, RxJS, Nx 22, Vitest/Jest, Native Federation, Playwright.

## Global Constraints

- Use vertical RED/GREEN cycles through public boundaries.
- Never expose provider handler arguments/results, rejected values, exception text, exception traceback/context, credentials, API keys, CSRF tokens, customer data, or label data.
- Never persist or bundle API keys or CSRF tokens.
- Preserve API-key header clients, browser-session GET/DELETE behavior, startup validation, confirmation gates, generated-source ownership, and provider/runtime neutrality.
- Same-origin Docker and configured first-party Angular development and Tauri origins must work.
- Unconfigured browser origins must fail before authentication rate-limit lookup or failure recording.
- Regenerate provider artifacts only from canonical registry source.

---

### Task 1: Extend the Approved Security Design

**Files:**
- Modify: `docs/superpowers/specs/2026-07-24-round-3-security-hardening-design.md`
- Create: `docs/superpowers/plans/2026-07-24-round-5-security-hardening.md`

**Interfaces:**
- Consumes: the approved signed browser-session architecture and all six verified Round 5 findings.
- Produces: the exact CSRF, trusted-origin, scalar-bound, error-sanitization, raw-fetch, and EventSource behavior implemented by Tasks 2–7.

- [ ] **Step 1: Update the browser-session contract**

Document `csrf_token: string | null`, deterministic HMAC binding to the complete signed session, memory-only frontend retention, `X-CSRF-Token` on unsafe cookie-authenticated requests, and valid API-key exemption.

- [ ] **Step 2: Update browser-origin and transport behavior**

Document exact same-origin or normalized `ALLOWED_ORIGINS` membership, pre-rate-limit hostile-origin rejection, credentialed native transports, EventSource session-status checks, and reconnect suppression after confirmed expiry.

- [ ] **Step 3: Add the Round 5 provider-boundary extension**

Document family-specific ShipAgent ID prefixes, canonical enums, bounded monetary/date/count/array schemas, recursive scalar auditing, unified hosted errors, and derived compact privacy compounds.

- [ ] **Step 4: Self-review and commit**

Run:

```bash
rg -n "TB[D]|TO[D]O|implement[[:space:]]+later|supporting cross-origin third-party" \
  docs/superpowers/specs/2026-07-24-round-3-security-hardening-design.md \
  docs/superpowers/plans/2026-07-24-round-5-security-hardening.md
git diff --check
git add -f docs/superpowers/specs/2026-07-24-round-3-security-hardening-design.md \
  docs/superpowers/plans/2026-07-24-round-5-security-hardening.md
git commit -m "docs: design round 5 security hardening"
```

Expected: no unresolved placeholder or obsolete non-goal, no whitespace error, and one documentation commit.

### Task 2: Bound Every Exported Provider Scalar

**Files:**
- Modify: `src/registry/tools/public.py`
- Modify: `src/registry/privacy.py`
- Modify: `tests/registry/test_catalog.py`
- Modify: `tests/control_plane/test_result_projection.py`
- Modify: `tests/hosted/test_hosted_mcp_registry.py`
- Regenerate: `generated/provider_artifacts/*.json`

**Interfaces:**
- Consumes: `ServiceCode`, `SERVICE_CODE_NAMES`, and `DEFAULT_CURRENCY_CODE` canonical carrier constants.
- Produces: `shipagent_id_schema(kind, description)`, `SHIPAGENT_CAPABILITY_CODES`, and recursively bounded public input/output schemas.

- [ ] **Step 1: RED the recursive scalar audit**

Add a recursive catalog test that visits every exported input/output schema and requires:

```python
if schema["type"] == "string":
    assert "enum" in schema or {
        "pattern",
        "minLength",
        "maxLength",
    } <= schema.keys()
elif schema["type"] in {"integer", "number"}:
    assert {"minimum", "maximum"} <= schema.keys()
elif schema["type"] == "array":
    assert "maxItems" in schema
```

Run:

```bash
../../.venv/bin/python -m pytest \
  tests/registry/test_catalog.py::test_every_exported_scalar_family_is_bounded -q
```

Expected: FAIL on correlation/device/job/preview IDs, capabilities, rates, count, and selected service.

- [ ] **Step 2: GREEN family-specific IDs and canonical enums**

Implement an opaque schema helper with exact family prefixes:

```python
def shipagent_id_schema(kind: str, description: str) -> dict[str, object]:
    prefix = f"sa_{kind}_"
    return {
        "type": "string",
        "description": description,
        "pattern": rf"^{prefix}[A-Za-z0-9_-]{{16,96}}$",
        "minLength": len(prefix) + 16,
        "maxLength": len(prefix) + 96,
    }
```

Use distinct correlation, device, ingress, input, validation, preview,
confirmation, job, and label kinds. Source UPS service code/name enums from
`src.services.ups_service_codes`, and the rate currency enum from
`DEFAULT_CURRENCY_CODE`.

- [ ] **Step 3: GREEN monetary, date, count, and collection bounds**

Use exact decimal and date patterns:

```python
MONEY_PATTERN = r"^(0|[1-9][0-9]{0,9})\.[0-9]{2}$"
ISO_DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
```

Bound capability/guidance/rate arrays, make capabilities and selected service
finite enums, and give shipment counts explicit minimum/maximum values.

- [ ] **Step 4: RED/GREEN real projection and MCP canaries**

Parameterize canonical projection and `FastMCP Client(server)` tests over each
remaining scalar family. Keep all surrounding enum/status values valid and
inject representative URL, credential, customer, or address text into one
field at a time. Numeric families use out-of-range values. Assert projection
rejects each result and the real MCP response is the generic safe error.

Run:

```bash
../../.venv/bin/python -m pytest \
  tests/registry/test_catalog.py \
  tests/control_plane/test_result_projection.py \
  tests/hosted/test_hosted_mcp_registry.py -q
```

Expected: all scalar audit, projection, and real MCP cases pass.

- [ ] **Step 5: Regenerate and commit**

Run:

```bash
../../.venv/bin/python scripts/generate_provider_artifacts.py
../../.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -q
git add src/registry/tools/public.py src/registry/privacy.py \
  tests/registry/test_catalog.py tests/control_plane/test_result_projection.py \
  tests/hosted/test_hosted_mcp_registry.py generated/provider_artifacts
git commit -m "fix(registry): bound provider-visible scalar families"
```

Expected: artifact drift passes and generated changes are committed with their canonical source.

### Task 3: Sanitize Handler and Projection Failures

**Files:**
- Modify: `src/hosted_mcp/server.py`
- Modify: `tests/hosted/test_hosted_mcp_registry.py`

**Interfaces:**
- Consumes: `BoundRegistryTool.run()` and `PROVIDER_RESULT_ERROR`.
- Produces: one generic provider-visible error and safe category-only logging for `handler` and `projection`.

- [ ] **Step 1: RED direct sync/async handler failures**

Add direct tool tests whose synchronous handler invocation and asynchronous
await each raise with sensitive fixture text. Assert:

```python
assert str(exc_info.value) == PROVIDER_RESULT_ERROR
assert exc_info.value.__cause__ is None
assert exc_info.value.__context__ is None
```

Expected: RED because handler failures currently bypass the sanitizer.

- [ ] **Step 2: RED projection exception context**

Extend the direct projection failure test to assert both exception links are
absent. Expected: RED because raising inside `except` retains `__context__`.

- [ ] **Step 3: GREEN one post-exception path**

Catch handler invocation/await and projection separately, set only a bounded
failure category, leave each `except` scope, then log and raise:

```python
if failure_category is not None:
    logger.warning(
        "Provider tool failure for tool %s category=%s",
        self._contract.name,
        failure_category,
    )
    raise ToolError(PROVIDER_RESULT_ERROR)
```

Never interpolate the exception, arguments, result, validator output, or
traceback.

- [ ] **Step 4: GREEN real MCP and caplog boundaries**

Call both failure categories through `FastMCP Client(server)`. Assert the
provider message and all captured logs contain only the generic error,
canonical operation, and bounded category; scan out every sensitive fixture.

Run:

```bash
../../.venv/bin/python -m pytest tests/hosted/test_hosted_mcp_registry.py -q
```

Expected: all direct and real boundary tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/hosted_mcp/server.py tests/hosted/test_hosted_mcp_registry.py
git commit -m "fix(hosted): sanitize all provider tool failures"
```

### Task 4: Derive Compact Privacy Compounds

**Files:**
- Modify: `src/registry/privacy.py`
- Modify: `tests/registry/test_catalog.py`

**Interfaces:**
- Consumes: the existing tokenized credential, customer-content, carrier-exchange, and label/document-transfer predicates.
- Produces: centralized privacy atom/compound families used by both tokenized and compact-name checks.

- [ ] **Step 1: RED adjacent compact families**

Add lower-, camel/acronym-, and uppercase fixtures covering X-API-key,
authorization/bearer, customer address/payload/rows, confirmation
token/artifact material, carrier request/response bodies, and label/document
payload/transfer names. Include legitimate fields such as `shipmentCount`,
`validationArtifactId`, and `serviceCode`.

Run:

```bash
../../.venv/bin/python -m pytest \
  tests/registry/test_catalog.py -k "compact_privacy or legitimate_compact" -q
```

Expected: the adversarial adjacent compounds fail while legitimate controls pass.

- [ ] **Step 2: GREEN centralized compound derivation**

Represent forbidden token groups once, derive deterministic compact fragments
from those groups, and use the same constants in ordinary token checks:

```python
_PRIVACY_COMPOUNDS = (
    ("x", "api", "key"),
    ("api", "key"),
    ("access", "key"),
    ("bearer", "value"),
    ("customer", "address"),
    ("confirmation", "token"),
    ("carrier", "response", "body"),
    ("label", "payload"),
)
```

Generate required ordering variants systematically where tokenized semantics
are order-independent. Preserve explicitly bounded opaque `*_artifact_id`
fields.

- [ ] **Step 3: Run registry and artifact drift**

```bash
../../.venv/bin/python -m pytest tests/registry -q
../../.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -q
```

Expected: all privacy cases and legitimate controls pass; artifacts do not change from privacy-only logic.

- [ ] **Step 4: Commit**

```bash
git add src/registry/privacy.py tests/registry/test_catalog.py
git commit -m "fix(registry): derive compact privacy compounds"
```

### Task 5: Bind CSRF to Browser Sessions and Order Origin Rejection

**Files:**
- Create: `src/api/browser_origins.py`
- Modify: `src/api/browser_session.py`
- Modify: `src/api/middleware/auth.py`
- Modify: `src/api/routes/auth_session.py`
- Modify: `src/api/main.py`
- Modify: `.env.example`
- Modify: `tests/api/test_browser_session.py`
- Modify: `tests/api/test_auth_middleware.py`
- Modify: `tests/api/test_main_config.py`

**Interfaces:**
- Produces: `BROWSER_CSRF_HEADER`, `derive_browser_csrf_token(session_token, api_key)`, `verify_browser_csrf_token(candidate, session_token, api_key)`, `configured_browser_origins()`, and `is_trusted_browser_origin(request)`.
- Consumes: the exact signed browser-session cookie and `ALLOWED_ORIGINS`.

- [ ] **Step 1: RED CSRF derivation and binding**

Test bounded token shape, deterministic recovery for one session, rejection
against another session/key, malformed values, and absence of API/session
material from the derived token.

- [ ] **Step 2: GREEN CSRF primitives**

Derive a versioned HMAC-SHA256 value from a domain-separated message containing
the complete signed session. Enforce an explicit maximum length and compare
with `hmac.compare_digest`.

- [ ] **Step 3: RED session response contract**

Test that unauthenticated/disabled status returns `csrf_token: null`, successful
exchange returns a token, and authenticated GET recovers the same token.

- [ ] **Step 4: GREEN route response**

Extend `BrowserSessionStatus` with `csrf_token: str | None`, derive it only for
a verified cookie, return it from successful exchange/status, and clear it on
DELETE.

- [ ] **Step 5: RED real mutation matrix**

Use the real onboarding mutation for same-origin Docker, configured
`http://localhost:4200`, configured Tauri origin, hostile origin, missing CSRF,
invalid CSRF, and valid header exemption. Assert rejected mutations leave
settings unchanged.

- [ ] **Step 6: RED hostile-origin rate-limit ordering**

Send more than `_AUTH_FAIL_MAX` protected requests with a hostile `Origin` and
bad key, then send a correct non-browser API-key request from the same client.
Expected before the fix: 429; required result: hostile requests are 403 and the
correct request succeeds.

- [ ] **Step 7: GREEN shared origin policy and middleware**

Normalize same-origin and configured origin strings in one backend module.
Reject any present untrusted origin before client-IP/rate-limit work. Then:

```python
if header_is_valid:
    return await call_next(request)
if not session_is_valid:
    record_failure_and_return_401()
if method_is_unsafe and not csrf_is_valid:
    return csrf_403()
```

Keep public session GET/DELETE and OPTIONS behavior. Add `X-CSRF-Token` to CORS
allowed headers.

- [ ] **Step 8: Run and commit**

```bash
../../.venv/bin/python -m pytest \
  tests/api/test_browser_session.py \
  tests/api/test_auth_middleware.py \
  tests/api/test_main_config.py \
  tests/api/test_settings.py -q
git add src/api/browser_origins.py src/api/browser_session.py \
  src/api/middleware/auth.py src/api/routes/auth_session.py src/api/main.py \
  .env.example tests/api/test_browser_session.py \
  tests/api/test_auth_middleware.py tests/api/test_main_config.py
git commit -m "fix(auth): bind csrf to browser sessions"
```

Expected: the mutation/origin/rate-limit matrix passes.

### Task 6: Share Session Expiry Across HttpClient, Fetch, and EventSource

**Files:**
- Modify: `shipagent-frontend/libs/shared/types/src/api.types.ts`
- Modify: `shipagent-frontend/libs/shared/api/src/browser-session.state.ts`
- Modify: `shipagent-frontend/libs/shared/api/src/api.service.ts`
- Modify: `shipagent-frontend/libs/shared/api/src/api.interceptors.ts`
- Create: `shipagent-frontend/libs/shared/api/src/browser-session-transport.service.ts`
- Modify: `shipagent-frontend/libs/shared/api/src/index.ts`
- Modify: `shipagent-frontend/libs/shared/sse/src/sse.service.ts`
- Modify: `shipagent-frontend/apps/chat-remote/src/app/label-preview-modal/label-preview-modal.component.ts`
- Modify: `shipagent-frontend/apps/chat-remote/src/services/job-progress-sse.service.ts`
- Modify: `shipagent-frontend/apps/shell/src/app/api-session-http.spec.ts`
- Create: `shipagent-frontend/apps/chat-remote/src/app/label-preview-modal/label-preview-modal.component.spec.ts`
- Create: `shipagent-frontend/apps/chat-remote/src/services/session-aware-sse.spec.ts`
- Modify: `shipagent-frontend/apps/shell/src/app/app.component.spec.ts`

**Interfaces:**
- Produces: memory-only `BrowserSessionState.csrfToken`, `applySessionStatus(status)`, and `BrowserSessionTransportService.fetch()` / `confirmSessionAfterEventSourceError()`.
- Consumes: backend `csrf_token`, common expiration signal, and `ApiService.getBrowserSessionStatus()`.

- [ ] **Step 1: RED memory-only CSRF HTTP behavior**

Test that session status/exchange stores the token only in the injectable
signal, unsafe non-session HttpClient requests receive `X-CSRF-Token`, safe
requests and session flows do not, and protected 401/clear erases it.

- [ ] **Step 2: GREEN shared state and interceptor**

Add `csrf_token: string | null` to the DTO. Update session API methods with
`tap(status => browserSession.applySessionStatus(status))`. Clone unsafe
non-session requests with the current CSRF header and browser credentials.

- [ ] **Step 3: RED label native-fetch expiry**

Open the label preview with a mocked native 401 response and assert the common
expiration version increments instead of leaving only a local PDF error.

- [ ] **Step 4: GREEN shared native transport**

Implement one root-provided native fetch wrapper that always uses
`credentials: 'include'`, applies CSRF to unsafe methods, and calls
`markExpired()` on 401. Route label PDF loading through it.

- [ ] **Step 5: RED EventSource session loss**

Use a controlled EventSource and session-status response. Trigger `onerror`,
assert the source closes, unauthenticated status increments expiration, and no
consumer reconnect error is emitted. An authenticated status result may emit
the ordinary stream error once.

- [ ] **Step 6: GREEN shared SSE guard**

Create EventSource with `{ withCredentials: true }`. On error, close it before
one session-status check. Complete the observable after confirmed expiry;
surface one normal error only when the browser session remains authenticated.
Apply the same guard to the dedicated job-progress EventSource path.

- [ ] **Step 7: GREEN shell recovery regression**

Extend the shell test from ready content through native-transport expiration,
blank gate, destroyed remote content, and successful reauthentication.

- [ ] **Step 8: Targeted frontend verification and commit**

```bash
cd shipagent-frontend
npx nx test shell
npx nx test chat-remote
npx nx typecheck shell
npx nx typecheck chat-remote
npx nx lint shell
npx nx lint chat-remote
git add libs/shared/types/src/api.types.ts libs/shared/api/src \
  libs/shared/sse/src/sse.service.ts apps/chat-remote/src \
  apps/shell/src/app/api-session-http.spec.ts \
  apps/shell/src/app/app.component.spec.ts
git commit -m "fix(frontend): share browser session transport expiry"
```

Expected: shared, label, SSE, and shell recovery tests pass.

### Task 7: Production Smoke, Broad Verification, and Round 5 Report

**Files:**
- Modify: `shipagent-frontend/scripts/smoke-authenticated-production.mjs`
- Modify: `.superpowers/sdd/final-review-fixes-report.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: real-browser evidence, a clean aggregate diff, and the Round 5 RED/GREEN report.

- [ ] **Step 1: RED/GREEN a non-HttpClient production expiry path**

After authenticating and opening federated chat content, invalidate the exact
session cookie and trigger label PDF loading or an EventSource failure. Assert
the gate returns without reload, authenticated content disappears, the input is
blank, reauthentication succeeds, and a protected request returns 200.

- [ ] **Step 2: Preserve leak and browser-error checks**

Search storage keys/values, URLs, console output, DOM, cookies, and every
emitted asset for runtime credential and CSRF fixtures. Accept only the generic
401 diagnostics scoped to deliberate invalidation.

- [ ] **Step 3: Run affected and broad backend verification**

```bash
../../.venv/bin/python -m pytest \
  tests/registry tests/control_plane/test_result_projection.py \
  tests/hosted/test_hosted_mcp_registry.py \
  tests/api/test_browser_session.py tests/api/test_auth_middleware.py \
  tests/api/test_main_config.py tests/api/test_settings.py -q
../../.venv/bin/python -m pytest -q -k "not stream and not sse and not progress"
../../.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -q
../../.venv/bin/python -m ruff check src/ tests/
../../.venv/bin/python -m ruff format --check src/ tests/
```

Expected: all affected and broad tests pass, artifacts are drift-clean, and Ruff exits zero.

- [ ] **Step 4: Run broad frontend and production verification**

```bash
cd shipagent-frontend
npx nx run shared-state:build
npx nx run-many -t typecheck --all
npx nx run-many -t lint --all
npx nx run-many -t test --all
npm run smoke:authenticated-production
npx prettier --check \
  libs/shared/types/src/api.types.ts \
  libs/shared/api/src \
  libs/shared/sse/src/sse.service.ts \
  apps/chat-remote/src \
  apps/shell/src/app/api-session-http.spec.ts \
  apps/shell/src/app/app.component.spec.ts \
  scripts/smoke-authenticated-production.mjs
node --check scripts/smoke-authenticated-production.mjs
```

Expected: all configured projects, seven production builds, four linked remotes, and the real browser smoke pass.

- [ ] **Step 5: Self-review the aggregate diff**

```bash
git diff --check 3fd6290..HEAD
git diff --stat 3fd6290..HEAD
git status --short
```

Inspect every changed file for prior-fix regressions, generated/manual-edit
mixups, persistent secrets, missing failure categories, open scalar schemas,
origin-order mistakes, and transport reconnect loops.

- [ ] **Step 6: Append the Round 5 report and commit**

Record each RED failure, GREEN behavior, commit, exact test/build count, smoke
path, known warning, and remaining limitation without reproducing sensitive
fixtures.

```bash
git add shipagent-frontend/scripts/smoke-authenticated-production.mjs
git commit -m "test(frontend): smoke native session expiry recovery"
git add -f .superpowers/sdd/final-review-fixes-report.md
git commit -m "docs: report round 5 security hardening"
git diff --check 3fd6290..HEAD
git status --short
```

Expected: the final worktree is clean and the full Round 5 range is whitespace-clean.
