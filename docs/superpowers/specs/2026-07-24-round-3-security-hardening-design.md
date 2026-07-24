# Round 3 Security Hardening Design

## Objective

Close the three remaining provider-contract review blockers:

1. Make the documented Docker browser flow usable with
   `SHIPAGENT_API_KEY` without embedding or persistently storing that shared
   secret in frontend assets or browser storage.
2. Make public provider-schema privacy validation resistant to JSON Schema
   traversal and naming-alias bypasses.
3. Prevent provider-visible status strings from carrying URLs, credentials, or
   customer data.

The changes preserve ShipAgent's existing header-based API authentication for
non-browser clients and preserve provider/runtime neutrality.

## Browser Authentication Architecture

### Session lifecycle

The browser shell becomes an authentication gate before it initializes
settings, onboarding, or Native Federation remotes.

1. On startup the shell calls `GET /api/v1/auth/session`.
2. When `SHIPAGENT_API_KEY` is not configured, the endpoint reports that
   authentication is not required and the shell starts normally.
3. When the key is configured and the browser has no valid session cookie, the
   endpoint reports that authentication is required. The shell renders a
   password dialog and does not initialize settings or remotes.
4. The user enters the Docker API key. The frontend sends it only in the
   `X-API-Key` header of `POST /api/v1/auth/session`.
5. Existing middleware validates the header. The route then returns a
   short-lived signed session token in an HttpOnly cookie.
6. The response includes a bounded CSRF token derived from, and valid only
   with, the exact signed browser session. The frontend discards its API-key
   input, retains the CSRF token only in memory, and retries normal
   initialization.
7. Subsequent HttpClient, raw fetch, and EventSource requests use the
   browser-managed cookie. Unsafe cookie-authenticated requests also send the
   in-memory CSRF token.
8. The shell exposes a clear-session action. `DELETE /api/v1/auth/session`
   expires the cookie and returns the shell to the password gate.

The frontend never writes the API key to local storage, session storage,
cookies, URL parameters, Angular configuration, logs, or built assets.

### Session token

The backend owns token creation and verification in one focused module. A token
contains:

- a format version;
- issued-at and expiry timestamps;
- a cryptographically random nonce; and
- an HMAC-SHA256 signature keyed by the configured `SHIPAGENT_API_KEY`.

The token carries no API key or customer data. Verification rejects malformed,
expired, future-issued, or incorrectly signed tokens with constant-time
signature comparison. Rotating `SHIPAGENT_API_KEY` invalidates every existing
browser session automatically. The session lifetime is eight hours.

The CSRF token is an HMAC-derived, versioned value bound to the complete signed
session token and the configured API key. It is deterministic for one session
so authenticated session-status recovery can return it without server-side
state. It has an explicit maximum length, contains no session token, API key,
or customer data, and is checked with constant-time comparison. A renewed,
expired, tampered, or key-rotated session cannot reuse an earlier CSRF token.

The cookie is:

- `HttpOnly`;
- `SameSite=Strict`;
- scoped to `/api`;
- `Secure` whenever the request is HTTPS; and
- bounded by the token's eight-hour lifetime.

### Middleware and route behavior

The API-key middleware accepts either:

- the existing correct `X-API-Key` header; or
- a valid browser session cookie.

Header authentication remains unchanged for CLI, tests, and integrations.
Invalid credentials still use the existing authentication-failure rate limit.
Valid API-key headers are exempt from CSRF validation. Every unsafe request
authenticated only by the session cookie requires the dedicated
`X-CSRF-Token` header to match that exact session.

Any request carrying a browser `Origin` is checked before rate-limit lookup or
failure recording. The origin must be either the request's exact normalized
origin or an exact normalized member of the existing `ALLOWED_ORIGINS`
configuration. This supports the same-origin Docker shell, explicitly
configured Angular development origins, and explicitly configured Tauri
origins. Unconfigured or malformed origins fail with 403 and cannot poison the
authentication-failure bucket. Trusted-origin and non-browser bad credentials
remain rate-limited.

`GET /api/v1/auth/session` and `DELETE /api/v1/auth/session` are intentionally
safe without an authenticated session: status inspection reveals only whether
authentication is required/authenticated, and deletion only expires a browser
cookie. `POST /api/v1/auth/session` remains protected by middleware and creates
or renews the cookie after successful authentication.

The route contract is:

```json
{
  "required": true,
  "authenticated": false,
  "csrf_token": null
}
```

The first two fields are booleans. `csrf_token` is null unless a configured
deployment has a valid browser session; successful exchange and authenticated
status recovery return the bounded session-bound token. No API key, signed
session value, customer material, failure detail, or configured-key metadata
is returned.

### Frontend integration

The shared API library provides one `provideShipAgentHttpClient()` registration
that installs cookie-aware auth behavior and the existing error interceptor in
a consistent order. The shell and the standalone chat, sidebar, settings, and
domain remote application configurations use this helper. This keeps direct
remote development consistent while Native Federation continues to share the
singleton API library in production.

`ApiService` adds methods for reading, creating, and clearing the browser
session. The create method receives the key as a call argument and attaches it
only to that POST request. No application-wide credential store is introduced.

The shared browser-session state stores only the current CSRF token and a
monotonic expiration signal in memory. Session status/exchange responses update
that state, session clear and protected 401 responses erase it, and the common
HttpClient interceptor adds it only to unsafe non-session requests. Neither the
API key nor the CSRF token is written to local/session storage, cookies, URLs,
logs, or bundles.

Authenticated raw fetch/blob access goes through one shared session-aware
client. It sends browser credentials, applies the same CSRF rule to unsafe
methods, and emits the common expiration signal on 401. Shared EventSource
handling uses credentials, closes the failed source while checking session
status, and emits expiration without scheduling another reconnect when status
reports unauthenticated. If the session remains authenticated, normal bounded
stream reconnect behavior may continue.

The shell owns four explicit states:

- checking session;
- API-key entry required;
- submitting/retrying after an authentication error; and
- authenticated/application ready.

Errors use generic copy and never echo the attempted key. A failed attempt keeps
the dialog open and allows retry. A successful attempt clears the input before
normal initialization. Clearing the session unloads the authenticated shell
view and restores the gate.

## Provider Schema Privacy Dialect

Public provider exports support a deliberately small JSON Schema dialect:

- primitive schemas;
- arrays with exactly one schema-valued `items`;
- closed objects with explicit `properties`;
- `required`, `description`, bounded string/number/array constraints, and
  `enum`.

For provider-exported public tools, validation rejects schema constructs that
can introduce unvisited or dynamic values:

- `$ref`, `$defs`, and `definitions`;
- `oneOf`, `anyOf`, `allOf`, and `not`;
- conditional or dependent schemas;
- `prefixItems` and tuple-valued `items`;
- `patternProperties`, `propertyNames`, `contains`, and unevaluated schemas;
- schema-valued or `true` `additionalProperties`.

The validator recursively walks only the supported `properties` and
schema-valued `items` locations after checking the dialect. This makes the
privacy proof closed over the accepted grammar instead of attempting to
interpret every JSON Schema feature.

Sensitive-name detection expands normalization and aliases to cover:

- API keys and access keys;
- authentication/authorization headers;
- bearer values and credentials;
- URL/link aliases such as `href` and `link`; and
- existing token, secret, address, payload, row, raw carrier exchange, label,
  and document transfer names.

Tests construct otherwise valid public contracts with each bypass family and
prove contract construction fails.

## Provider-Safe Status Codes

Every provider-exported `status` property becomes a bounded enum:

- system status: `ready`, `degraded`, `unavailable`;
- job/execution status: `queued`, `running`, `completed`, `failed`,
  `cancelled`;
- label status: `pending`, `ready`, `unavailable`.

The schemas are the public contract boundary. Internal handlers must map
free-form internal states or messages to one of these codes before projection.
Provider result projection rejects any other scalar, including a URL,
credential, customer name, address, or combined free-form message hidden in a
field named `status`.

Generated OpenAI, Claude, and generic MCP artifacts are regenerated from the
canonical registry; generated files are never hand-edited.

## Error Handling and Security Properties

- Authentication failures use generic UI and API messages.
- The entered key is cleared from the component immediately after each request
  completes.
- Invalid session cookies do not fall back to partial authentication.
- Cookie parsing and signature failures are ordinary authentication failures,
  not server errors.
- Missing or invalid CSRF tokens and hostile origins fail before route
  execution.
- Hostile browser origins fail before authentication rate-limit lookup or
  failure accounting.
- Session status never discloses whether a submitted candidate was close to the
  configured key.
- Existing auth rate limiting and minimum key-length validation remain active.
- No row-level shipping data enters prompts or new browser-session payloads.

## Test Strategy

### Backend

- Unit tests cover token issue/verify, expiration, tampering, future timestamps,
  key rotation, CSRF/session binding, bounded CSRF shape, and constant-time
  rejection behavior.
- API tests cover unauthenticated status, successful header-to-cookie exchange,
  cookie-only access to a real protected settings endpoint, clearing, secure
  cookie behavior, invalid-cookie rejection, and session-status CSRF recovery.
- Real mutation tests cover same-origin Docker, configured Angular development,
  configured Tauri, hostile origin, missing CSRF, invalid CSRF, valid API-key
  exemption, and pre-rate-limit hostile-origin rejection.
- Existing header authentication and rate-limit tests remain green.

### Frontend

- Shared API tests prove the key is attached only to session creation and that
  all normal requests use browser credentials without an API-key header.
- Shared API tests prove the in-memory CSRF token is added only to unsafe
  authenticated non-session requests and is erased on expiry.
- Label-download and EventSource tests prove non-HttpClient 401/session loss
  emits the same expiration signal and suppresses reconnect loops.
- Shell tests prove unauthenticated startup does not load settings/remotes,
  incorrect keys show retryable generic errors, successful entry initializes
  the application, and clear returns to the gate.
- Configuration tests or static assertions prove shell and each relevant remote
  register the shared HttpClient provider.

### Production browser smoke

The smoke test:

1. Generates a new high-entropy API key at runtime.
2. Builds all Angular applications in production mode and links the remotes.
3. Starts the real FastAPI static-server path with that runtime key.
4. Opens the built shell in a real browser.
5. Enters the key in the password dialog.
6. Observes a real successful `/api/v1/settings` response.
7. Clears the session, observes the gate, and authenticates again.
8. Invalidates the session through a non-HttpClient request path, observes the
   gate without a page reload, and authenticates again.
9. Searches emitted JavaScript and static assets and proves both runtime
   credential material and CSRF fixtures are absent.

The smoke does not mock Uvicorn, the API response, authentication, or remote
loading.

## Non-Goals

- Replacing the shared Docker API key with per-user identity.
- Persisting browser sessions in a database.
- Supporting unconfigured or third-party browser origins. Explicitly configured
  first-party Angular development and Tauri origins are supported.
- Expanding the accepted provider JSON Schema dialect.
- Changing shipping workflow confirmation or carrier logic.

## Completion Criteria

- The documented Docker-style browser path authenticates successfully without
  exposing the API key in static assets or persistent browser storage.
- Same-origin Docker, configured Angular development, and configured Tauri
  browser origins can perform cookie-authenticated mutations with a
  session-bound in-memory CSRF token.
- Shell and relevant remotes use consistent HttpClient authentication/error
  registration.
- Public schema bypass fixtures fail contract construction.
- Every exported status value is bounded and smuggling fixtures fail result
  projection.
- Provider artifacts are regenerated and drift-clean.
- Targeted and broad backend/frontend checks, production build, browser smoke,
  and Ruff checks pass.

## Round 5 Provider and Hosted-Boundary Extension

The Round 5 review extends this approved design in three provider-facing areas:

1. Every scalar position in every exported input and output schema is bounded.
   ShipAgent-owned identifiers use family-specific `sa_` prefixes and opaque
   character/length grammars. Capability, UPS service-code, UPS service-name,
   and currency values come from canonical enumerations. Monetary strings use
   a bounded decimal grammar, delivery dates use a fixed ISO-date grammar,
   counts have minimum/maximum bounds, and arrays have explicit item limits.
   Contract validation recursively rejects any future unbounded exported
   string, number, integer, or array.
2. Actual result projection and MCP calls exercise valid surrounding results
   with forbidden URL, token, customer, and address values in every remaining
   scalar family. Canonical provider artifacts are regenerated from source and
   checked for drift.
3. Hosted MCP handler and projection failures use one provider-safe error path.
   Both synchronous and asynchronous handler errors are caught. Only canonical
   tool name and a bounded failure category are logged. The generic `ToolError`
   is raised after leaving all exception scopes so both `__cause__` and
   `__context__` are absent.

Compact privacy-name handling is likewise derived from the same centralized
token families used by ordinary snake/camel-case validation. Deterministic
compound generation covers X-API-key, authorization/bearer, customer content,
confirmation material, carrier exchanges, and label/document transfer
families across lower, camel/acronym, and uppercase spellings. Exact legitimate
opaque identifier fields remain allowed.
