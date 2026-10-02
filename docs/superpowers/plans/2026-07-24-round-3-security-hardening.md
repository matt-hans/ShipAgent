# Round 3 Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Docker browser authentication usable without exposing the shared API key, close public JSON Schema privacy bypasses, and bound every provider-visible status value.

**Architecture:** FastAPI exchanges the existing `X-API-Key` once for an eight-hour HMAC-signed HttpOnly cookie, while Angular gates remote initialization behind session status and uses one shared credential-aware HttpClient provider. Provider contracts accept only a small closed JSON Schema dialect, and canonical status schemas use provider-safe enums so result projection rejects free-form smuggling.

**Tech Stack:** Python 3.12, FastAPI/Starlette, HMAC-SHA256, pytest, Angular 21, Nx 22, TypeScript 5.9, Vitest, RxJS, Playwright 1.58, JSON Schema, Ruff

## Global Constraints

- Never embed or persist `SHIPAGENT_API_KEY` in static assets, local storage, session storage, frontend cookies, URLs, or logs.
- Preserve `X-API-Key` authentication for non-browser clients.
- The browser-session cookie is HttpOnly, SameSite Strict, scoped to `/api`, secure under HTTPS, and valid for no more than eight hours.
- Shell settings and Native Federation remotes initialize only after session status is authenticated or API authentication is disabled.
- Public provider schemas reject refs, definitions, combinators, dynamic properties, tuple arrays, and open/schema-valued additional properties.
- All provider-visible status fields use bounded provider-safe enums.
- Generated provider artifacts are regenerated from canonical registry sources and never hand-edited.
- Backend contract changes consumed by Angular are reflected in `shipagent-frontend/libs/shared/types/src/`.
- Use the repository Python virtualenv at `../../.venv/bin/python` from the isolated worktree.

---

## File Map

- `src/api/browser_session.py`: pure session-token issue/verify helpers and cookie constants.
- `src/api/middleware/auth.py`: authenticate protected API requests by header or valid session cookie.
- `src/api/routes/auth_session.py`: thin GET/POST/DELETE browser-session HTTP contract.
- `src/api/main.py`: register the auth-session router.
- `tests/api/test_browser_session.py`: token and real API session lifecycle coverage.
- `tests/api/test_auth_middleware.py`: header/cookie middleware regression coverage.
- `shipagent-frontend/libs/shared/types/src/api.types.ts`: `BrowserSessionStatus` frontend contract.
- `shipagent-frontend/libs/shared/api/src/api.providers.ts`: common Angular HttpClient registration.
- `shipagent-frontend/libs/shared/api/src/api.interceptors.ts`: browser-credential behavior without build-time secrets.
- `shipagent-frontend/libs/shared/api/src/api.service.ts`: session status/create/delete methods.
- `shipagent-frontend/libs/shared/api/src/index.ts`: public shared API exports.
- `shipagent-frontend/apps/*/src/app/app.config.ts`: consistent shell and remote HttpClient providers.
- `shipagent-frontend/apps/shell/src/app/api-key-gate/api-key-gate.component.ts`: password entry, generic failure, and retry UI.
- `shipagent-frontend/apps/shell/src/app/app.component.ts`: gate application initialization and clear/retry flow.
- `shipagent-frontend/apps/shell/src/app/header/header.component.ts`: clear-session action in the authenticated shell.
- `shipagent-frontend/apps/shell/src/app/app.component.spec.ts`: shell lifecycle tests.
- `shipagent-frontend/apps/shell/src/app/api-key-gate/api-key-gate.component.spec.ts`: password-dialog tests.
- `shipagent-frontend/apps/shell/src/app/api-session-http.spec.ts`: request-header and cookie-credentials tests.
- `shipagent-frontend/package.json` and `package-lock.json`: pinned Playwright smoke dependency and command.
- `shipagent-frontend/scripts/smoke-authenticated-production.mjs`: production build, real backend, browser authentication, clear/retry, and bundle scan.
- `src/registry/privacy.py`: strict schema dialect and expanded sensitive aliases.
- `tests/registry/test_catalog.py`: schema bypass fixtures.
- `src/registry/tools/public.py`: canonical provider-safe status enums.
- `tests/control_plane/test_result_projection.py`: negative scalar-smuggling fixtures.
- `generated/provider_artifacts/*`: regenerated canonical exports.
- `.superpowers/sdd/final-review-fixes-report.md`: append Round 3 implementation, verification, and commit evidence.

---

### Task 1: Backend Browser Session Exchange

**Files:**
- Create: `src/api/browser_session.py`
- Create: `src/api/routes/auth_session.py`
- Create: `tests/api/test_browser_session.py`
- Modify: `src/api/middleware/auth.py`
- Modify: `src/api/main.py`
- Modify: `tests/api/test_auth_middleware.py`

**Interfaces:**
- Consumes: `get_expected_api_key() -> str` and existing `X-API-Key` middleware behavior.
- Produces: `BROWSER_SESSION_COOKIE`, `BROWSER_SESSION_TTL_SECONDS`, `issue_browser_session(api_key: str, now: int | None = None) -> str`, and `verify_browser_session(token: str, api_key: str, now: int | None = None) -> bool`.
- Produces: `GET|POST|DELETE /api/v1/auth/session` with `{required: bool, authenticated: bool}`.

- [ ] **Step 1: Write failing token tests**

Add deterministic tests that issue a token, verify it with the same key/time,
and reject tampering, expiry, future issue time, malformed values, and key
rotation:

```python
def test_browser_session_token_is_bounded_and_key_bound():
    key = "k" * 64
    token = issue_browser_session(key, now=1_000)
    assert verify_browser_session(token, key, now=1_001)
    assert not verify_browser_session(token, "r" * 64, now=1_001)
    assert not verify_browser_session(token + "x", key, now=1_001)
    assert not verify_browser_session(
        token, key, now=1_000 + BROWSER_SESSION_TTL_SECONDS + 1
    )
```

- [ ] **Step 2: Run token tests and confirm RED**

Run:

```bash
../../.venv/bin/python -m pytest tests/api/test_browser_session.py -v
```

Expected: collection fails because `src.api.browser_session` does not exist.

- [ ] **Step 3: Implement the minimal signed-token module**

Use a versioned payload and URL-safe encoding:

```python
BROWSER_SESSION_COOKIE = "shipagent_browser_session"
BROWSER_SESSION_TTL_SECONDS = 8 * 60 * 60
_CLOCK_SKEW_SECONDS = 60

def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)

def issue_browser_session(api_key: str, now: int | None = None) -> str:
    issued_at = int(time.time()) if now is None else now
    expires_at = issued_at + BROWSER_SESSION_TTL_SECONDS
    payload = f"v1.{issued_at}.{expires_at}.{secrets.token_urlsafe(18)}"
    signature = hmac.new(
        api_key.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{payload}.{_encode(signature)}"

def verify_browser_session(
    token: str, api_key: str, now: int | None = None
) -> bool:
    try:
        version, issued_raw, expires_raw, nonce, signature_raw = token.split(".")
        issued_at = int(issued_raw)
        expires_at = int(expires_raw)
        signature = _decode(signature_raw)
    except (TypeError, ValueError):
        return False
    current = int(time.time()) if now is None else now
    if (
        version != "v1"
        or not nonce
        or issued_at > current + _CLOCK_SKEW_SECONDS
        or expires_at <= current
        or expires_at - issued_at != BROWSER_SESSION_TTL_SECONDS
    ):
        return False
    payload = f"{version}.{issued_at}.{expires_at}.{nonce}"
    expected = hmac.new(
        api_key.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).digest()
    return hmac.compare_digest(signature, expected)
```

Verification returns `False`, rather than raising, for every untrusted token
parse or signature failure.

- [ ] **Step 4: Run token tests and confirm GREEN**

Run:

```bash
../../.venv/bin/python -m pytest tests/api/test_browser_session.py -v
```

Expected: token tests pass.

- [ ] **Step 5: Write failing session-route and middleware tests**

Cover disabled authentication, configured authentication without a cookie,
header-to-cookie exchange, cookie-only access to the real settings endpoint,
tampering, clearing, and HTTPS cookie flags:

```python
def test_header_exchange_grants_cookie_only_settings_access(client, monkeypatch):
    key = secrets.token_urlsafe(48)
    monkeypatch.setenv("SHIPAGENT_API_KEY", key)

    status = client.get("/api/v1/auth/session")
    assert status.json() == {"required": True, "authenticated": False}

    created = client.post(
        "/api/v1/auth/session", headers={"X-API-Key": key}
    )
    assert created.status_code == 200
    assert created.json() == {"required": True, "authenticated": True}
    assert "HttpOnly" in created.headers["set-cookie"]
    assert "SameSite=strict" in created.headers["set-cookie"]

    assert client.get("/api/v1/settings").status_code == 200
    assert client.delete("/api/v1/auth/session").status_code == 200
    assert client.get("/api/v1/settings").status_code == 401
```

Use separate `TestClient` instances when asserting missing versus retained
cookies, and use a runtime-generated key rather than a repository literal.

- [ ] **Step 6: Run route tests and confirm RED**

Run:

```bash
../../.venv/bin/python -m pytest tests/api/test_browser_session.py tests/api/test_auth_middleware.py -v
```

Expected: the new session endpoints return 404 and cookie-only API requests
return 401.

- [ ] **Step 7: Implement the thin route and middleware integration**

Create an `APIRouter(prefix="/auth/session", tags=["authentication"])` with:

```python
class BrowserSessionStatus(BaseModel):
    required: bool
    authenticated: bool

@router.get("")
def get_browser_session_status(request: Request) -> BrowserSessionStatus:
    expected = get_expected_api_key()
    return BrowserSessionStatus(
        required=bool(expected),
        authenticated=not expected or request_has_valid_browser_session(
            request, expected
        ),
    )

@router.post("")
def create_browser_session(request: Request, response: Response) -> BrowserSessionStatus:
    expected = get_expected_api_key()
    if expected:
        response.set_cookie(
            BROWSER_SESSION_COOKIE,
            issue_browser_session(expected),
            max_age=BROWSER_SESSION_TTL_SECONDS,
            path="/api",
            secure=request.url.scheme == "https",
            httponly=True,
            samesite="strict",
        )
    return BrowserSessionStatus(required=bool(expected), authenticated=True)

@router.delete("")
def delete_browser_session(request: Request, response: Response) -> BrowserSessionStatus:
    response.delete_cookie(
        BROWSER_SESSION_COOKIE,
        path="/api",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )
    required = bool(get_expected_api_key())
    return BrowserSessionStatus(
        required=required, authenticated=not required
    )
```

Exempt only GET and DELETE of the exact session endpoint from middleware.
For every other protected API request, accept a constant-time matching header
or a valid browser cookie before recording an auth failure.

- [ ] **Step 8: Run backend auth tests and confirm GREEN**

Run:

```bash
../../.venv/bin/python -m pytest tests/api/test_browser_session.py tests/api/test_auth_middleware.py tests/api/test_settings.py -v
```

Expected: all selected tests pass and original header authentication remains
covered.

- [ ] **Step 9: Commit the backend vertical slice**

```bash
git add src/api/browser_session.py src/api/routes/auth_session.py \
  src/api/middleware/auth.py src/api/main.py \
  tests/api/test_browser_session.py tests/api/test_auth_middleware.py
git commit -m "feat: add secure browser API sessions"
```

---

### Task 2: Angular Authentication Gate and Shared Client Registration

**Files:**
- Modify: `shipagent-frontend/libs/shared/types/src/api.types.ts`
- Create: `shipagent-frontend/libs/shared/api/src/api.providers.ts`
- Modify: `shipagent-frontend/libs/shared/api/src/api.interceptors.ts`
- Modify: `shipagent-frontend/libs/shared/api/src/api.service.ts`
- Modify: `shipagent-frontend/libs/shared/api/src/index.ts`
- Modify: `shipagent-frontend/apps/shell/src/app/app.config.ts`
- Modify: `shipagent-frontend/apps/chat-remote/src/app/app.config.ts`
- Modify: `shipagent-frontend/apps/sidebar-remote/src/app/app.config.ts`
- Modify: `shipagent-frontend/apps/settings-remote/src/app/app.config.ts`
- Modify: `shipagent-frontend/apps/domain-remote/src/app/app.config.ts`
- Create: `shipagent-frontend/apps/shell/src/app/api-session-http.spec.ts`
- Create: `shipagent-frontend/apps/shell/src/app/api-key-gate/api-key-gate.component.ts`
- Create: `shipagent-frontend/apps/shell/src/app/api-key-gate/api-key-gate.component.spec.ts`
- Modify: `shipagent-frontend/apps/shell/src/app/app.component.ts`
- Modify: `shipagent-frontend/apps/shell/src/app/app.component.spec.ts`
- Modify: `shipagent-frontend/apps/shell/src/app/header/header.component.ts`

**Interfaces:**
- Consumes: `BrowserSessionStatus { required: boolean; authenticated: boolean }`.
- Produces: `provideShipAgentHttpClient(): EnvironmentProviders`.
- Produces: `ApiService.getBrowserSessionStatus()`, `createBrowserSession(apiKey)`, and `clearBrowserSession()`.
- Produces: `ApiKeyGateComponent.authenticated` output after a successful POST.

- [ ] **Step 1: Install frontend dependencies**

Run:

```bash
cd shipagent-frontend
npm ci
```

Expected: the Nx 22 workspace installs from the committed lockfile.

- [ ] **Step 2: Write failing shared HTTP behavior tests**

Configure `TestBed` with the common provider and `HttpTestingController`. Prove
normal requests use browser credentials without an API key, while session
creation sends the entered key only on the POST:

```typescript
api.getSettings().subscribe();
const settings = http.expectOne('/api/v1/settings');
expect(settings.request.withCredentials).toBe(true);
expect(settings.request.headers.has('X-API-Key')).toBe(false);

api.createBrowserSession('runtime-only-key').subscribe();
const session = http.expectOne('/api/v1/auth/session');
expect(session.request.method).toBe('POST');
expect(session.request.headers.get('X-API-Key')).toBe('runtime-only-key');
```

- [ ] **Step 3: Run the focused shell tests and confirm RED**

Run:

```bash
cd shipagent-frontend
npx nx test shell --testNamePattern="browser session HTTP"
```

Expected: compilation fails because the new provider and service methods do not
exist.

- [ ] **Step 4: Implement the shared API contract**

Add:

```typescript
export interface BrowserSessionStatus {
  required: boolean;
  authenticated: boolean;
}
```

Replace the build-time `API_AUTH_KEY` token with:

```typescript
export const apiAuthInterceptor: HttpInterceptorFn = (req, next) =>
  next(req.clone({ withCredentials: true }));

export function provideShipAgentHttpClient(): EnvironmentProviders {
  return provideHttpClient(
    withInterceptors([apiAuthInterceptor, apiErrorInterceptor]),
  );
}
```

Add typed service methods. Only `createBrowserSession` sets `X-API-Key`, using
`HttpHeaders`; no shared key state is introduced.

- [ ] **Step 5: Register the common provider in shell and remotes**

Replace direct `provideHttpClient` registrations with
`provideShipAgentHttpClient()` in shell and chat. Add the same provider to
sidebar, settings, and domain standalone configurations.

- [ ] **Step 6: Run focused HTTP/config type checks and confirm GREEN**

Run:

```bash
cd shipagent-frontend
npx nx test shell --testNamePattern="browser session HTTP"
npx nx run-many -t typecheck --projects=shell,chat-remote,sidebar-remote,settings-remote,domain-remote
```

Expected: the HTTP test and five application typechecks pass.

- [ ] **Step 7: Write failing gate and shell lifecycle tests**

Test the dialog and application lifecycle with a typed mock `ApiService`:

```typescript
expect(mockLoader.loadChat).not.toHaveBeenCalled();
expect(mockLoader.loadSidebar).not.toHaveBeenCalled();
expect(element.querySelector('input[type="password"]')).toBeTruthy();
```

Also cover:

- the entered value is blanked after POST completion;
- an incorrect key renders generic retryable copy that does not contain the key;
- a successful response loads settings and both eager remotes;
- clear calls DELETE and returns to the password dialog;
- disabled authentication initializes normally.

- [ ] **Step 8: Run shell lifecycle tests and confirm RED**

Run:

```bash
cd shipagent-frontend
npx nx test shell
```

Expected: new gate selectors and lifecycle assertions fail against eager
initialization.

- [ ] **Step 9: Implement the password gate and guarded initialization**

The gate uses `FormsModule`, a password input with label `Docker API key`, a
submit button named `Unlock ShipAgent`, and generic error copy:

```typescript
submit(): void {
  const candidate = this.apiKey();
  if (!candidate || this.submitting()) return;
  this.submitting.set(true);
  this.error.set(false);
  this.api.createBrowserSession(candidate)
    .pipe(finalize(() => {
      this.apiKey.set('');
      this.submitting.set(false);
    }))
    .subscribe({
      next: () => this.authenticated.emit(),
      error: () => this.error.set(true),
    });
}
```

`AppComponent.ngOnInit()` checks session status first. Move the existing
settings fetch, eager remote loads, and settings watcher behind a single
idempotent `initializeAuthenticatedApplication()` method. Render checking,
password-gate, and authenticated-shell states explicitly. The header emits a
clear action; successful DELETE removes the authenticated view and restores the
gate.

- [ ] **Step 10: Run shell and affected remote tests and confirm GREEN**

Run:

```bash
cd shipagent-frontend
npx nx run-many -t test --projects=shell,chat-remote,sidebar-remote,settings-remote,domain-remote
npx nx run-many -t typecheck --projects=shell,chat-remote,sidebar-remote,settings-remote,domain-remote
npx nx run-many -t lint --projects=shell,chat-remote,sidebar-remote,settings-remote,domain-remote
```

Expected: all selected targets pass.

- [ ] **Step 11: Commit the frontend vertical slice**

```bash
git add shipagent-frontend/libs/shared/types/src/api.types.ts \
  shipagent-frontend/libs/shared/api/src \
  shipagent-frontend/apps/shell/src/app \
  shipagent-frontend/apps/chat-remote/src/app/app.config.ts \
  shipagent-frontend/apps/sidebar-remote/src/app/app.config.ts \
  shipagent-frontend/apps/settings-remote/src/app/app.config.ts \
  shipagent-frontend/apps/domain-remote/src/app/app.config.ts
git commit -m "feat: gate browser UI with API sessions"
```

---

### Task 3: Real Production Browser Authentication Smoke

**Files:**
- Create: `shipagent-frontend/scripts/smoke-authenticated-production.mjs`
- Modify: `shipagent-frontend/package.json`
- Modify: `shipagent-frontend/package-lock.json`

**Interfaces:**
- Consumes: built shell/remotes, `../../.venv/bin/python -m src.bundle_entry`,
  and accessible labels/buttons from Task 2.
- Produces: `npm run smoke:authenticated-production`.

- [ ] **Step 1: Add Playwright 1.58 as an exact development dependency**

Run:

```bash
cd shipagent-frontend
npm install --save-dev --save-exact playwright@1.58.2
```

Expected: `package.json` and `package-lock.json` record version `1.58.2`.

- [ ] **Step 2: Write the production smoke script**

The ES module must:

```javascript
const runtimeKey = randomBytes(48).toString('base64url');
run('npx', ['nx', 'run-many', '-t', 'build', '--all',
  '--configuration=production']);
run('./scripts/link-remotes.sh', []);
const backend = spawn(python, ['-m', 'src.bundle_entry', 'serve',
  '--host', '127.0.0.1', '--port', '0'], {
  cwd: repositoryRoot,
  env: {
    ...process.env,
    SHIPAGENT_API_KEY: runtimeKey,
    DATABASE_URL: `sqlite:///${databasePath}`,
  },
});
```

Parse `SHIPAGENT_PORT=<port>` from stdout, then use Playwright:

```javascript
const settingsResponse = page.waitForResponse(
  response => response.url().endsWith('/api/v1/settings')
    && response.status() === 200,
);
await page.getByLabel('Docker API key').fill(runtimeKey);
await page.getByRole('button', { name: 'Unlock ShipAgent' }).click();
await settingsResponse;
await page.getByRole('button', { name: 'Clear API session' }).click();
await page.getByLabel('Docker API key').waitFor();
```

Authenticate a second time and observe another real settings 200. Recursively
read emitted files under `dist/apps` and fail if any contains `runtimeKey`.
Always close page/context/browser, terminate the backend, and remove the
temporary database directory in `finally`.

- [ ] **Step 3: Run the real production smoke**

Run:

```bash
cd shipagent-frontend
npm run smoke:authenticated-production
```

Expected output includes:

```text
authenticated settings request: 200
session cleared and gate restored
authenticated retry settings request: 200
runtime API key absent from production bundles
```

- [ ] **Step 4: Commit the durable browser smoke**

```bash
git add shipagent-frontend/package.json shipagent-frontend/package-lock.json \
  shipagent-frontend/scripts/smoke-authenticated-production.mjs
git commit -m "test: smoke authenticated production browser flow"
```

---

### Task 4: Strict Public Provider Schema Dialect

**Files:**
- Modify: `src/registry/privacy.py`
- Modify: `tests/registry/test_catalog.py`

**Interfaces:**
- Consumes: `provider_schema_privacy_violations(tool_name, schema)`.
- Produces: violations for unsupported schema grammar and sensitive aliases,
  consumed by `ToolContract._validate_public_export`.

- [ ] **Step 1: Write failing bypass tests**

Parameterize valid JSON Schema bypass families:

```python
@pytest.mark.parametrize(
    "bypass",
    [
        {"oneOf": [{"properties": {"label_url": {"type": "string"}}}]},
        {"$defs": {"secret": {"properties": {"api_key": {"type": "string"}}}}},
        {"$ref": "#/$defs/secret"},
        {"prefixItems": [{"properties": {"auth_header": {"type": "string"}}}]},
        {"patternProperties": {".*": {"type": "string"}}},
        {"additionalProperties": {"type": "string"}},
        {"additionalProperties": True},
    ],
)
def test_public_provider_contract_rejects_unsupported_schema_bypass(bypass):
    schema = object_schema({"safe": {"type": "string"}}, ["safe"])
    schema.update(bypass)
    with pytest.raises(ValueError, match="provider privacy"):
        public_tool(
            "unsafe_schema",
            "Unsafe schema",
            "A provider-visible contract with an unsupported schema construct.",
            SideEffectClass.read,
            ["tools:read"],
            object_schema({}, []),
            schema,
            provider_export_enabled=True,
        )
```

Add direct alias cases for `api_key`, `access_key`, `auth_header`,
`authorization_header`, `bearer_value`, `label_href`, and `document_link`.

- [ ] **Step 2: Run registry tests and confirm RED**

Run:

```bash
../../.venv/bin/python -m pytest tests/registry/test_catalog.py -v
```

Expected: unsupported constructs and aliases are accepted.

- [ ] **Step 3: Implement the strict recursive dialect validator**

Allow only:

```python
_ALLOWED_SCHEMA_KEYWORDS = frozenset({
    "type", "description", "properties", "required", "additionalProperties",
    "items", "enum", "pattern", "minLength", "maxLength", "minimum",
    "maximum", "minItems", "maxItems", "uniqueItems",
})
_ALLOWED_TYPES = frozenset({
    "object", "array", "string", "integer", "number", "boolean", "null",
})
```

For each schema node:

- reject non-dictionary child schemas;
- reject unknown keywords;
- require `additionalProperties is False` for objects;
- recurse explicit property schemas;
- require one dictionary-valued `items` schema for arrays;
- reject `properties` on non-objects and `items` on non-arrays.

Expand sensitive aliases with token-set predicates so `api_key`,
`access_key`, auth/authorization headers, bearer values, href, and link fields
are violations without flagging every harmless field containing the token
`key`.

- [ ] **Step 4: Run registry/model/export tests and confirm GREEN**

Run:

```bash
../../.venv/bin/python -m pytest tests/registry tests/provider_adapters -v
```

Expected: bypass tests pass and every existing canonical public schema remains
valid.

- [ ] **Step 5: Commit the schema hardening slice**

```bash
git add src/registry/privacy.py tests/registry/test_catalog.py
git commit -m "fix: restrict public provider schema dialect"
```

---

### Task 5: Provider-Safe Status Enums and Generated Artifacts

**Files:**
- Modify: `src/registry/tools/public.py`
- Modify: `tests/registry/test_catalog.py`
- Modify: `tests/control_plane/test_result_projection.py`
- Regenerate: `generated/provider_artifacts/*`

**Interfaces:**
- Produces: `SYSTEM_STATUS_CODES`, `JOB_STATUS_CODES`, and
  `LABEL_STATUS_CODES`.
- Consumes: `project_result(contract, result)` JSON Schema validation.

- [ ] **Step 1: Write failing canonical-enum and smuggling tests**

Assert all four exported status schemas have exact enums and reject free-form
values:

```python
@pytest.mark.parametrize(
    ("tool_name", "unsafe_status"),
    [
        ("create_label_download", "ready: https://example.test/label?token=x"),
        ("create_label_download", "ready for Jane Doe at 1 Main St"),
        ("get_job_status", "running authorization=Bearer secret"),
        ("execute_shipments", "queued customer_payload=private"),
        ("get_shipagent_status", "ready https://internal.example.test"),
    ],
)
def test_provider_status_fields_reject_scalar_smuggling(tool_name, unsafe_status):
    contract = next(tool for tool in public_tools() if tool.name == tool_name)
    result = {
        "create_label_download": {
            "label_artifact_id": "sa_" + "x" * 20,
            "status": unsafe_status,
        },
        "get_job_status": {"job_id": "job-1", "status": unsafe_status},
        "execute_shipments": {"job_id": "job-1", "status": unsafe_status},
        "get_shipagent_status": {
            "status": unsafe_status,
            "active_device_id": "device-1",
            "capabilities": [],
        },
    }[tool_name]
    with pytest.raises(ValidationError):
        project_result(contract, result)
```

- [ ] **Step 2: Run focused status tests and confirm RED**

Run:

```bash
../../.venv/bin/python -m pytest \
  tests/registry/test_catalog.py \
  tests/control_plane/test_result_projection.py -v
```

Expected: free-form status strings validate successfully.

- [ ] **Step 3: Add bounded canonical status schemas**

Use:

```python
SYSTEM_STATUS_CODES = ["ready", "degraded", "unavailable"]
JOB_STATUS_CODES = ["queued", "running", "completed", "failed", "cancelled"]
LABEL_STATUS_CODES = ["pending", "ready", "unavailable"]
```

Replace every provider-exported `{"type": "string"}` status schema with the
matching enum. Do not add free-form message, reason, URL, or detail fields.

- [ ] **Step 4: Run focused status tests and confirm GREEN**

Run:

```bash
../../.venv/bin/python -m pytest \
  tests/registry/test_catalog.py \
  tests/control_plane/test_result_projection.py \
  tests/hosted/test_hosted_mcp_registry.py -v
```

Expected: safe `running` fixtures pass and all smuggling values fail.

- [ ] **Step 5: Regenerate artifacts and prove no drift**

Run:

```bash
../../.venv/bin/python scripts/generate_provider_artifacts.py
../../.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v
```

Expected: generated OpenAI, Claude, and generic MCP artifacts contain status
enums and the drift test passes.

- [ ] **Step 6: Commit statuses and generated artifacts**

```bash
git add src/registry/tools/public.py \
  tests/registry/test_catalog.py \
  tests/control_plane/test_result_projection.py \
  generated/provider_artifacts
git commit -m "fix: bound provider-visible status codes"
```

---

### Task 6: Full Verification, Self-Review, and Round 3 Report

**Files:**
- Modify: `.superpowers/sdd/final-review-fixes-report.md`
- Modify only if verification exposes a defect: the directly affected source
  and test files from Tasks 1–5.

**Interfaces:**
- Consumes: all previous slices.
- Produces: reproducible final evidence and clean worktree.

- [ ] **Step 1: Run complete frontend validation**

```bash
cd shipagent-frontend
npx nx run-many -t typecheck --all
npx nx run-many -t lint --all
npx nx run-many -t test --all
npx nx run-many -t build --all --configuration=production
./scripts/link-remotes.sh
npm run smoke:authenticated-production
```

Expected: every target and the real browser smoke pass.

- [ ] **Step 2: Run complete focused and broad backend validation**

```bash
../../.venv/bin/python -m pytest \
  tests/api/test_browser_session.py \
  tests/api/test_auth_middleware.py \
  tests/api/test_settings.py \
  tests/registry \
  tests/control_plane/test_result_projection.py \
  tests/hosted/test_hosted_mcp_registry.py \
  tests/provider_adapters -v
../../.venv/bin/python -m pytest -k "not stream and not sse and not progress"
../../.venv/bin/python -m ruff check src/ tests/
../../.venv/bin/python -m ruff format --check src/ tests/
```

Expected: all selected/broad tests pass and Ruff reports no errors or formatting
changes.

- [ ] **Step 3: Inspect the complete Round 3 diff**

```bash
git diff fb2d27b^..HEAD --check
git diff --stat fb2d27b^..HEAD
git status --short
```

Review for:

- secret values or persistent browser storage;
- cookie scope/flags and authentication bypasses;
- unbounded schema paths or status strings;
- accidental generated-file hand edits;
- unrelated user changes; and
- missing test coverage.

- [ ] **Step 4: Append the detailed Round 3 report**

Add a section recording:

- each original finding and its concrete resolution;
- TDD RED/GREEN commands;
- production browser-smoke behavior;
- generated artifact command and drift result;
- full frontend/backend/Ruff results;
- Round 3 commit hashes; and
- remaining concerns, or `None` when no material concern remains.

- [ ] **Step 5: Commit the final report and any verification-only corrections**

```bash
git add -f .superpowers/sdd/final-review-fixes-report.md
git commit -m "docs: report round 3 final review fixes"
```

- [ ] **Step 6: Confirm final clean state**

```bash
git status --short --branch
git log --oneline -8
```

Expected: the worktree is clean and the Round 3 commits are visible.
