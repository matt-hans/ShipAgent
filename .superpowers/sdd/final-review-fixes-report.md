# Final Review Fixes Report

## Status

All six blocking findings in `final-review-findings.md` are implemented and
covered by behavioral tests. The complete fix wave is committed in five
commits:

- `d08c2fe` — `fix: validate actual server listener host`
- `88631a7` — `fix: commit portable control-plane migrations`
- `eb60b7a` — `fix: replace raw public shipment contracts`
- `89df240` — `fix: enforce typed control-plane audit fields`
- `4df45e7` — `fix: preserve application logging during migrations`

The final commit includes a regression discovered during broad-suite
verification: Alembic's logging configuration disabled existing application
loggers when migrations ran in-process, which made later `caplog` tests
order-dependent.

## Finding 1 — Actual listener host bypasses `fake_local` validation

### RED

- `test_start_daemon_rejects_actual_public_bind_for_fake_local` failed because
  `start_daemon(host="0.0.0.0")` reached Uvicorn without raising.
- `test_bundled_serve_rejects_actual_public_bind_for_fake_local` failed for the
  same bypass in bundled serve mode.
- `test_docker_server_uses_the_validated_listener_launcher` failed while the
  Docker command invoked Uvicorn directly.

### GREEN

- Added `validated_listener_host()`, which constructs settings with the exact
  launcher-supplied host, applies the existing startup security policy, and
  returns the validated host used by Uvicorn.
- Wired it into both daemon and bundled serve launchers before PID creation or
  Uvicorn startup.
- Routed the Docker command through bundled serve instead of invoking Uvicorn
  directly.
- Tests explicitly cover `fake_local`, local environment, absent database and
  Redis URLs, and a requested `0.0.0.0` listener.

## Findings 2, 4, and 5 — PostgreSQL migration commit, event-loop isolation,
and URL portability

### RED

- The configured live PostgreSQL test first failed with nested
  `asyncio.run()` when synchronous Alembic execution occurred inside the async
  pytest loop.
- After moving Alembic to a worker thread, the live test observed no migrated
  tables after reconnect because `connectable.connect()` rolled back the outer
  transaction.
- A conventional `postgresql://` live URL failed by attempting to load a sync
  PostgreSQL driver.
- Runtime session-factory coverage likewise failed for a conventional URL.
- Live ORM verification exposed an aware/naive datetime mismatch between the
  existing timezone-aware migration schema and inferred model column types.

### GREEN

- Online Alembic execution now uses `async with connectable.begin()` so schema
  creation, search-path setup, migrations, and the revision record commit
  together.
- The live async test calls synchronous Alembic through `asyncio.to_thread()`
  and retains async post-migration ORM verification.
- The live test reconnects and asserts all expected tables plus the
  `alembic_version` revision before inserting and loading a `CloudAccount`.
- Added one shared URL normalizer used by both Alembic and the runtime session
  factory. It converts `postgres://`, `postgresql://`,
  `postgresql+psycopg://`, `postgresql+psycopg2://`, and
  `postgresql+pg8000://` to `postgresql+asyncpg://`, while preserving an
  already-async URL.
- Model datetime columns now explicitly match the existing
  `DateTime(timezone=True)` migration contract.

## Finding 3 — Public provider contract carries raw shipment/address content

### RED

- A registry-wide recursive schema test reported
  `submit_one_off_shipment.input.shipment_payload` and
  `validate_shipment_address.output.normalized_address`.
- Shipment-content tool schemas lacked bounded ShipAgent reference patterns.
- Address validation lacked an opaque artifact ID and bounded guidance codes.

### GREEN

- `submit_one_off_shipment` now accepts only an `ingress_reference` minted by
  the authenticated ShipAgent ingress channel.
- Shipment-bearing public tools use bounded `sa_...` opaque references.
- Address validation returns `validation_artifact_id`, `valid`, and an
  enumerated, bounded, unique list of redacted guidance codes; it cannot return
  a normalized address.
- Added recursive registry-wide guards against raw `payload`, `address`, and
  non-count `row` property names in all public inputs and outputs.
- Regenerated all four provider artifacts from the canonical registry source;
  artifact drift is clean.

## Finding 6 — Audit safe fields accept arbitrary plaintext

### RED

Behavioral tests demonstrated acceptance or insufficient validation for:

- malformed actor and payload hashes;
- plaintext, email-like, token-like, serialized, control-character, and
  overlong opaque IDs;
- invalid top-level account/provider/device IDs;
- arbitrary status/reason values and free-form `status_note`;
- negative, boolean, and overflowing counts;
- plaintext/serialized versions and event types;
- unsupported error categories.

### GREEN

- Hashes are fixed-format lowercase 64-character SHA-256 digests.
- Each ID key has an explicit maximum length and opaque-character grammar;
  whitespace, control characters, serialized structures, and sensitive token
  markers are rejected.
- Counts are non-boolean, non-negative signed 64-bit integers.
- Versions use a bounded version grammar and explicit allowed keys.
- Safe fields are limited to enumerated `status` and `reason_code`;
  `status_note` was removed.
- Event types and error categories are validated as bounded codes.
- Legitimate fixtures and persistence assertions now use valid digests,
  opaque IDs, enums, and versions.

## Additional regression from broad verification

The first broad run produced 13 logging-test failures only when Alembic tests
ran first. A minimal reproduction showed `logging.config.fileConfig()` setting
application loggers to `disabled=True`. The new regression test failed before
the fix and passes after setting `disable_existing_loggers=False`.

## Verification evidence

Fresh final verification:

- Broad backend suite with live PostgreSQL:
  `SHIPAGENT_TEST_DATABASE_URL=postgresql://matthewhans@127.0.0.1:55432/shipagent PYTHONPATH=. ../../.venv/bin/python -m pytest -q -k 'not stream and not sse and not progress'`
  — **3,292 passed, 20 skipped, 73 deselected, 5 warnings in 45.08s**.
- Cross-cutting focused suite covering control plane, registry, provider
  adapters, launcher paths, and portability smoke — **165 passed, 3 warnings**.
- Registry/provider/projection/e2e focused suite — **59 passed**.
- Launcher-focused suite — **43 passed**.
- Audit-focused suite — **37 passed**.
- Generated artifact drift:
  `PYTHONPATH=. ../../.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -q`
  — **1 passed**.
- Ruff:
  `PYTHONPATH=. ../../.venv/bin/python -m ruff check src tests alembic`
  — **All checks passed**.
- Ruff format check over all 17 Python files changed by this fix wave —
  **17 files already formatted**.
- `git diff --check efe2292..HEAD` — no whitespace errors.

## Self-review and remaining concerns

- Requirement-by-requirement review found no remaining blocking gap.
- The repository-wide Ruff format check reports 261 pre-existing files that do
  not match current formatting. Only fix-wave files were formatted and checked
  to avoid an unrelated mechanical rewrite.
- The Docker launcher contract was verified structurally and its delegated
  bundled launcher was verified behaviorally; no Docker image build was run.
- Live database verification used an isolated local PostgreSQL database and a
  unique schema that the test dropped in its `finally` block.
- The broad suite's five warnings are pre-existing dependency/pytest/Alembic
  configuration warnings and did not hide failures.

# Round 2

## Status and commits

All Round 2 findings are implemented and committed:

- `43ac54b` — `fix: keep provider label artifacts opaque`
- `647f2f0` — `fix: secure documented Docker startup`
- `c2ed24e` — `fix: normalize TLS URLs and bound audit versions`
- `6810a86` — `test: isolate projection sanitizer fixtures`

## Finding 1 — Provider-visible label download URL and privacy guards

### RED

- `test_label_download_returns_only_an_opaque_handoff_artifact` failed because
  `create_label_download` still returned `download_url` instead of
  `label_artifact_id`.
- The parameterized provider-contract privacy test produced seven
  `DID NOT RAISE` failures for label URLs, document bytes, label data,
  credentials, confirmation tokens, raw carrier requests, and carrier response
  bodies.

### GREEN

- `create_label_download` now returns a bounded `sa_...` label artifact plus a
  status code. Its description explicitly places resolution in an
  authenticated ShipAgent-owned channel.
- Added a recursive canonical registry privacy validator. Provider-exported
  public contracts now reject:
  - raw payload, address, and non-count row fields;
  - credential, password, secret, and token fields;
  - label/document URL, URI, download, bytes, data, content, and base64 fields;
  - raw/carrier request and response bodies/data.
- Replaced the provider-facing `confirmation_token` with a bounded
  `confirmation_artifact_id`, preserving the prepare/execute confirmation
  policy without exposing a token.
- The registry-wide test uses the same canonical validator to check every
  public input/output schema.
- Regenerated all four provider artifacts from
  `scripts/generate_provider_artifacts.py`; no provider artifact contains the
  former label URL or confirmation token fields.

Files:

- `src/registry/privacy.py`
- `src/registry/models.py`
- `src/registry/tools/public.py`
- `tests/registry/test_catalog.py`
- `tests/hosted/test_hosted_mcp_registry.py`
- `generated/provider_artifacts/*.json`

## Finding 2 — Documented Docker quick start fails closed

### RED

`test_documented_docker_environment_starts_authenticated_public_launcher`
loaded the documented `.env.example`/Compose environment and exercised bundled
serve with `--host 0.0.0.0`. It failed at the real listener security gate
because the effective mode was `fake_local`.

### GREEN

- Added a committed `docker.env` loaded after `.env` by both development and
  production Compose files. It selects `auth0` public-listener mode only inside
  Docker and leaves local/desktop `.env` behavior loopback-only.
- Compose now requires `SHIPAGENT_API_KEY` using `${VAR:?message}` and refuses
  to resolve without it. API routes therefore use the existing constant-time
  `X-API-Key` middleware rather than an anonymous public bind.
- The README quick start generates a 64-character key, documents the layered
  override, keeps the published port on `127.0.0.1`, and corrects the app URL
  to port 8080.
- `.env.example` documents the loopback-only `fake_local` boundary and the
  Docker API-key requirement.
- The behavioral smoke loads the documented env files in Compose order,
  validates key strength, and reaches the actual bundled launcher/Uvicorn
  boundary on `0.0.0.0`.
- The original regression still proves `fake_local` rejects `0.0.0.0`.
- A real `docker compose config` resolution confirmed effective
  `SHIPAGENT_AUTH_MODE=auth0` and a 64-character API key.

Files:

- `docker.env`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `.env.example`
- `README.md`
- `tests/test_docker_launch.py`

## Finding 3a — PostgreSQL TLS query normalization

### RED

- The conventional TLS URL test failed because normalization retained
  `sslmode=require` after switching to the asyncpg scheme.
- The explicit conflict test failed with `DID NOT RAISE` for a URL containing
  both `sslmode=require` and `ssl=disable`.

### GREEN

- URL normalization now parses PostgreSQL URLs structurally with
  `urlsplit()`/`urlunsplit()`.
- Conventional sync schemes still become `postgresql+asyncpg`.
- `sslmode` becomes asyncpg-compatible `ssl` for both conventional and
  already-async URLs.
- Supplying both keys is a fail-closed `ValueError`, eliminating ambiguous TLS
  precedence.
- Unrelated query segments, encoded credentials, encoded database paths, and
  percent-encoded query values remain byte-for-byte unchanged.

Files:

- `src/control_plane/database_url.py`
- `tests/control_plane/test_database_url.py`

## Finding 3b — Audit version bounds

### RED

Four parameterized cases—oversized numeric, prerelease, build, and total
versions—were accepted and failed with `DID NOT RAISE`.

### GREEN

`ControlPlaneAuditService` now enforces a 64-character maximum before applying
the version regex. All four oversized forms are rejected with a bounded-version
error while existing legitimate versions remain accepted.

Files:

- `src/control_plane/audit/service.py`
- `tests/control_plane/audit/test_service.py`

## Broad-verification regression and resolution

The first cross-cutting run had five failures in
`tests/control_plane/test_result_projection.py`. Root-cause tracing showed those
projection-only fixtures marked deliberately unsafe `payload` schemas as real
provider exports. The new canonical privacy gate correctly rejected them
before the projection layer ran.

The fixture helper now creates non-exported contracts so the result projection
continues to test its independent defense-in-depth sanitizer. Real exported
contracts remain covered by the canonical registry privacy tests. The exact
projection file then passed 13 tests, and the repeated cross-cutting suite
passed 176 tests.

## Round 2 verification evidence

- Broad backend suite with live PostgreSQL:
  `SHIPAGENT_TEST_DATABASE_URL=postgresql://matthewhans@127.0.0.1:55432/shipagent PYTHONPATH=. ../../.venv/bin/python -m pytest -q -k 'not stream and not sse and not progress'`
  — **3,308 passed, 20 skipped, 73 deselected, 5 warnings in 43.16s**.
- Focused control-plane, registry, provider-adapter, hosted MCP, launcher, and
  portability suite with live PostgreSQL — **176 passed, 4 warnings**.
- Docker/startup/auth focused suite — **39 passed, 1 warning**.
- Registry/model/hosted MCP focused suite — **45 passed**.
- URL, audit, and migration focused suite — **53 passed, 1 skipped,
  2 warnings**.
- Artifact drift:
  `PYTHONPATH=. ../../.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -q`
  — **1 passed**.
- Ruff:
  `PYTHONPATH=. ../../.venv/bin/python -m ruff check src tests alembic`
  — **All checks passed**.
- Ruff format check over all 11 Python files changed in Round 2 —
  **11 files already formatted**.
- Real Docker Compose config resolution — effective mode was `auth0` and the
  required API key was 64 characters.
- `git diff --check 4df45e7..HEAD` — no whitespace errors.
- Worktree status after all Round 2 commits — clean.

## Round 2 self-review and concerns

- Requirement-by-requirement and aggregate-diff review found no remaining
  blocking gap.
- No Docker image build was run. The verification covers Compose interpolation,
  documented env layering, key validation, and the actual bundled launcher
  boundary, but not frontend API-key injection in a built image.
- The broad suite warnings remain the same pre-existing dependency,
  unregistered pytest mark, and Alembic configuration warnings.
- Repository-wide formatting still has the pre-existing baseline noted above;
  all Round 2 Python files match the configured formatter.

# Round 3

## Status and commits

All three Round 3 blockers are implemented:

- Docker browser authentication exchanges the existing API key for a signed,
  short-lived HttpOnly cookie without embedding or persisting the key.
- Public provider contracts accept only a small, recursively closed JSON
  Schema dialect and reject dynamic/traversal constructs plus sensitive naming
  aliases.
- Every provider-visible `status` field is a bounded enum, so real result
  projection rejects free-form data smuggling.

Round 3 commits:

- `fb2d27b` — `docs: design round 3 security hardening`
- `e5e8930` — `docs: plan round 3 security hardening`
- `7b53ce3` — `feat: add secure browser API sessions`
- `05f1c70` — `feat: gate browser UI with API sessions`
- `98f6293` — `test: smoke authenticated production browser flow`
- `6f672e8` — `fix: restrict public provider schema dialect`
- `ee9bb3a` — `fix: bound provider-visible status codes`
- `5610213` — `fix: normalize acronym schema aliases`
- `4fd594f` — `test: expand browser secret leak assertions`
- `e835384` — `test: isolate browser smoke credentials`

## Finding 1 — Docker browser flow cannot use the required API key safely

### RED

- Browser-session token tests initially failed at collection because no signed
  session module existed.
- Route tests observed a missing session endpoint and cookie-only requests to
  the real settings endpoint remained unauthorized.
- Angular HTTP tests had no session status/create/delete contract or common
  cookie-aware client provider.
- Shell lifecycle tests had no authentication gate and initialized settings
  and federation remotes before browser authentication.

### GREEN

- Added an eight-hour, versioned HMAC-SHA256 browser token containing only
  issue/expiry times and a random nonce. Verification rejects malformed,
  oversized, tampered, expired, future-issued, wrong-lifetime, and key-rotated
  tokens with constant-time signature comparison.
- Added `GET|POST|DELETE /api/v1/auth/session`. The POST remains protected by
  the existing constant-time `X-API-Key` middleware and sets a host-only
  `HttpOnly`, `SameSite=Strict`, `/api`-scoped cookie, with `Secure` under
  HTTPS. GET exposes only two booleans; DELETE is public and idempotent.
- Middleware preserves header authentication for CLI/integration callers and
  accepts a valid browser cookie for protected API paths. Invalid header and
  cookie attempts retain the existing rate limit.
- Added one `provideShipAgentHttpClient()` provider for the shell and four
  standalone remotes. Normal requests use browser credentials without an API
  key header; only the session-creation POST receives the transient entered
  key.
- The shell checks session state before settings or Native Federation remote
  initialization. It supports checking, retryable connection error, password
  entry, ready, clear-session, and re-authentication paths.
- The password component clears its signal and rendered input after every
  request, uses generic error copy, and has no frontend credential store.

## Real production browser smoke

The committed Playwright smoke performs the complete no-mock path:

1. Builds all seven Angular projects in production mode.
2. Links the four Native Federation remotes into the shell.
3. Generates a unique API key, filter-token secret, credential-encryption key,
   temporary database, and temporary label directory.
4. Starts the real bundled FastAPI static-server entry point on an ephemeral
   loopback port.
5. Opens the emitted shell in a real Chrome/Chromium process, enters the key,
   and observes a real authenticated `GET /api/v1/settings` response.
6. Verifies the session cookie is HttpOnly and SameSite Strict and does not
   contain the key.
7. Clears the session, observes the gate, authenticates again, and observes a
   second real settings response.
8. Proves the key is absent from local/session storage keys and values, request
   URLs, browser console output, the rendered DOM, the cookie value, and every
   emitted production asset.
9. Rejects browser console/page errors and development error overlays.

The final smoke rerun reported `Credential key source: env`, confirming it did
not read or create the developer's platformdirs credential key.

## Finding 2 — Public-schema privacy checks can be bypassed

### RED

The initial adversarial catalog run produced **37 failures**. The existing
walker ignored or accepted:

- `oneOf`, `anyOf`, `allOf`, and `not`;
- `$ref`, `$defs`, and legacy definitions;
- conditional and dependent schemas;
- `prefixItems` and tuple/boolean-valued `items`;
- pattern/property-name/contains/unevaluated schemas;
- missing, `true`, or schema-valued `additionalProperties`;
- boolean property schemas, union types, and unknown keywords; and
- `api_key`, `access_key`, authentication-header, bearer, `href`, and `link`
  aliases.

A later casing audit produced two additional RED failures for `APIKey` and
`xAPIKey`.

### GREEN

- Provider-exported public schemas now use a deliberately small grammar:
  explicit primitive types; single-schema arrays; closed objects with explicit
  dictionary `properties`, list `required`, and
  `additionalProperties: false`; descriptions, enums, and bounded
  string/number/array constraints.
- Every unknown or type-inappropriate keyword is a contract-construction
  violation. Only accepted `properties` and dictionary `items` positions are
  traversed after dialect validation, closing the proof over the supported
  grammar.
- Sensitive field normalization now splits ordinary camel case and
  acronym-to-word boundaries. Snake, camel, and acronym aliases for API/access
  keys, auth/authorization headers, bearer values, label hrefs, and document
  links are rejected.
- Existing provider-safe public contracts remain valid; non-exported/private
  contract behavior remains independently testable.

## Finding 3 — Free-form provider-visible statuses allow scalar smuggling

### RED

The focused RED run produced **16 failures**:

- all four canonical status schemas lacked the required enum; and
- real `project_result()` calls accepted URLs, bearer/credential text, and
  customer name/address text hidden in `status` for all four public tools.

### GREEN

- System status is exactly `ready | degraded | unavailable`.
- Job/execution status is exactly
  `queued | running | completed | failed | cancelled`.
- Label status is exactly `pending | ready | unavailable`.
- Tests use actual canonical public `ToolContract` instances. JSON Schema
  projection rejects each smuggled scalar before it can reach a provider.
- OpenAI Apps, Claude public MCP, generic MCP, and the canonical registry
  artifacts were regenerated from the source registry.

## Artifact-generator regression found during verification

The shared project virtualenv is editable-installed against the main checkout.
When the generator was invoked by file path from this worktree, Python could
import registry code from that other checkout. The artifact drift test exposed
the mismatch. The generator now prepends its own repository root before
importing `src`, so regeneration is deterministic for the active checkout or
worktree. The clean-tree artifact drift test passes without `PYTHONPATH`
workarounds.

## Round 3 verification evidence

- Fresh broad backend suite:
  `../../.venv/bin/python -m pytest -k "not stream and not sse and not progress"`
  — **3,357 passed, 21 skipped, 103 deselected, 4 warnings in 43.97s**.
- Backend browser-session/auth/settings slice — **35 passed**.
- Final catalog suite, including dialect and alias cases — **71 passed**.
- Registry, provider projection, control-plane result projection, and hosted
  MCP focused run — **135 passed** before the final acronym additions; those
  additions are covered by the later broad run.
- Clean-tree provider artifact drift — **1 passed**.
- Frontend reproducibility: `npm ci` completed successfully.
- Frontend typecheck: all **6** configured project targets passed after the
  required `shared-state` declaration build.
- Frontend lint: all **6** configured project targets passed with **0 errors**;
  the existing settings/chat rules emitted 43 warnings.
- Frontend unit tests: all **6** project targets passed, **124 tests** total.
- Production frontend build: all **7** projects passed and all four remotes
  linked successfully.
- Full default production browser smoke passed; the final current-code rerun
  also passed the expanded secret-leak and isolated-key assertions.
- `../../.venv/bin/python -m ruff check src/ tests/` — **All checks passed**.
- Ruff check and format check over all **11** Python files changed in Round 3 —
  **11 files already formatted**.
- Prettier and `node --check` pass for the production browser smoke.
- `git diff --check` reports no whitespace errors.

## Round 3 self-review and remaining concerns

- Requirement-by-requirement and aggregate-diff review found no remaining
  Round 3 blocker.
- Repository-wide Ruff format check still reports **253 pre-existing files**
  outside this change set. Round 3 files are format-clean; no unrelated
  mechanical rewrite was performed.
- `npm ci` reported 87 dependency advisories (2 low, 36 moderate, 46 high,
  3 critical). No automatic dependency upgrade was performed because that
  would be a separate, broad dependency-remediation effort.
- Frontend lint/build output includes existing template, native-output,
  extended-diagnostic, and component-budget warnings; all commands exit zero.
- The browser smoke exercises real emitted assets, federation remotes, FastAPI,
  middleware, cookies, and browser behavior on the host. It does not build or
  launch a Docker image, and it requires either a Chrome channel or an
  installed Playwright Chromium binary.
- The four broad-backend warnings are existing dependency, pytest-mark, and
  Alembic configuration warnings and did not hide failures.

# Round 4

## Status and commits

All five Round 4 blockers are implemented:

- hosted MCP projection failures return one generic provider-visible error and
  produce only operation-safe logs;
- cookie-authenticated mutations require an exact trusted origin, while valid
  API-key headers and safe session operations retain their intended behavior;
- browser-session renewal is always authorized by the API-key header rather
  than by an existing cookie;
- compact and case-varied sensitive public-schema aliases are rejected; and
- any protected frontend 401 restores the shell authentication gate across
  Native Federation boundaries and supports a clean reauthentication path.

Round 4 commits:

- `780f249` — `fix(hosted): sanitize result projection failures`
- `3ecb5d9` — `fix(auth): protect browser session mutations`
- `43d8d32` — `fix(registry): reject compact sensitive aliases`
- `586dae7` — `fix(frontend): restore auth gate on session expiry`
- `97fb132` — `test(frontend): smoke automatic session expiry recovery`
- `4a8ec33` — `test(frontend): serialize production smoke builds`
- `77e8ff9` — `style(frontend): format session expiry changes`

## Finding 1 — Hosted projection failures exposed rejected provider data

### RED

Four real FastMCP client calls failed the new boundary assertions. Schema,
privacy, size-cap, and non-object projection failures exposed rejected detail
through provider errors, exception chaining, or framework logging.

### GREEN

- The hosted boundary catches every projection exception at the
  `project_result()` call site, raises one generic `ToolError` without an
  exception chain, and does not change execution-error behavior outside that
  projection boundary.
- Its warning contains only the canonical tool operation. It omits returned
  data, validator detail, exception text, and exception arguments.
- Boundary tests call the actual FastMCP server through `Client(server)` and
  inspect both the provider response and captured logs.
- The tests cover four representative sensitive-data categories and assert
  that none of their fixture values, rejected schema detail, or exception
  detail crosses either boundary. Sensitive fixture values are intentionally
  not reproduced in this report.

The four adversarial boundary cases pass after the fix; the broader hosted MCP
and result-projection slice passes **33 tests**.

## Finding 2 — Cookie authentication permitted cross-origin mutations

### RED

A cookie-authenticated request without `Origin` successfully mutated the real
onboarding settings endpoint. Hostile same-site and missing-origin requests
therefore lacked a fail-closed browser mutation boundary.

### GREEN

- Cookie-only unsafe methods require `Origin` to normalize to the exact request
  scheme, host, and effective port.
- Missing, malformed, cross-origin, and hostile same-site origins receive 403
  before route mutation.
- A valid `X-API-Key` header remains exempt for non-browser integrations.
- Safe methods and the public session-status/session-clear operations retain
  their existing behavior.
- Tests exercise the real onboarding mutation and prove rejected requests leave
  persisted state unchanged, while exact-origin and valid-header requests
  succeed.

## Finding 3 — A session cookie could renew itself

### RED

With a valid browser cookie, session-creation POSTs with a missing or incorrect
API-key header returned 200 and could replace the session cookie.

### GREEN

- `POST /api/v1/auth/session` is now always header-authorized when API-key
  protection is configured, even when the request already has a valid cookie.
- Missing and incorrect headers return 401 and do not emit a replacement
  session cookie.
- The correct header succeeds and replaces the cookie.
- The change preserves rate limiting and public GET/DELETE session semantics.

The combined browser-session, authentication-middleware, and settings slice
passes **37 tests**.

## Finding 4 — Compact sensitive aliases bypassed schema privacy checks

### RED

The new lower-, mixed-, and all-uppercase fixtures produced **18 failures**.
Compact spellings of credential keys, authentication/authorization headers,
and label/document payload or link fields were accepted because token-only
normalization could not prove their sensitive meaning.

### GREEN

- Public-schema privacy validation now combines the existing token analysis
  with deterministic compact-name normalization.
- A bounded compact alias set rejects API/access-key, authentication/header,
  and label/document payload/link families without applying fuzzy matching.
- Tests cover all three casing styles across the credential, authorization,
  label, and document families.
- The full registry suite passes **113 tests**, and canonical generated provider
  artifacts remain unchanged.

## Finding 5 — Protected frontend 401s did not restore the auth gate

### RED

- The shared API library initially had no session-expiration contract.
- A shell lifecycle test could keep authenticated chat, sidebar, and settings
  state rendered after a protected request returned 401.

### GREEN

- Added a root-provided, monotonic browser-session expiration signal in the
  shared API library.
- The common error interceptor emits the signal for protected 401 responses and
  excludes the exact browser-session flow so failed login/status/clear requests
  cannot recursively invalidate their own gate.
- The shell reacts to each new expiration event by returning to the
  authentication gate, clearing settings state, closing the settings flyout,
  and destroying authenticated shell/remote content.
- The transient password input is blank when the gate reappears.
- Successful reauthentication restores authenticated content.
- Shell and all standalone remotes use the same common HTTP provider; Native
  Federation shares the library as a singleton.
- HTTP tests prove protected 401 emission and session-flow exclusion. Shell
  tests prove ready-to-gate teardown and successful recovery.

The shared frontend unit suite passes **126 tests**: shared state **41**, shell
**28**, chat **54**, and one each for domain, sidebar, and settings.

## Real production browser invalidation smoke

The updated no-mock Playwright smoke:

1. Builds all seven frontend projects in production mode and links all four
   Native Federation remotes.
2. Starts the real bundled FastAPI/static frontend boundary on an ephemeral
   loopback port and authenticates through the browser session flow.
3. Performs the onboarding mutation through a same-origin page request.
4. Opens federated settings content, invalidates the HttpOnly session cookie,
   and observes real protected API 401 responses.
5. Proves the shared interceptor restores the gate without a page reload,
   authenticated shell content is absent, and the transient input is blank.
6. Reauthenticates and observes a successful protected settings response.
7. Rechecks storage keys and values, request URLs, console output, DOM, cookie
   content, and all emitted bundles for credential leakage.

Only generic browser resource diagnostics corresponding to the deliberate 401
invalidation window are accepted, and the smoke asserts that at least one such
diagnostic occurred. Every other console or page error still fails the run.

An intermittent Native Federation worker-shutdown hang appeared when all seven
production builds ran concurrently. The smoke now asks Nx to build
sequentially. Two final default sequential smoke runs passed, including a fresh
run from the exact final formatted source.

## Round 4 verification evidence

- Fresh affected backend slice:
  `../../.venv/bin/python -m pytest tests/api/test_browser_session.py tests/api/test_auth_middleware.py tests/api/test_settings.py tests/hosted/test_hosted_mcp_registry.py tests/control_plane/test_result_projection.py tests/registry -q`
  — **183 passed, 1 warning in 0.70s**.
- Fresh broad backend suite:
  `../../.venv/bin/python -m pytest -q -k "not stream and not sse and not progress"`
  — **3,381 passed, 21 skipped, 103 deselected, 4 warnings in 48.86s**.
- Clean-tree provider artifact drift — **1 passed**.
- Frontend typecheck: all **6** configured project targets passed after the
  required shared-state declaration build.
- Frontend lint: all **6** configured project targets passed with **0 errors**
  and the existing **43 warnings**.
- Frontend tests: all **6** configured project targets passed, **126 tests**
  total.
- Exact-source production browser smoke: all **7** production builds passed,
  all four remotes linked, and invalidation/recovery/leak assertions passed.
  Nx reused valid cached output for two of the seven hash-matched build tasks.
- `../../.venv/bin/python -m ruff check src/ tests/` — **All checks passed**.
- Ruff format check over the **6** changed Python files — all already formatted.
- Prettier check over the **5** changed TypeScript files and `node --check` over
  the smoke script passed.
- `git diff --check 84f37d1..HEAD` reports no whitespace errors.

## Round 4 self-review and remaining concerns

- Requirement-by-requirement and aggregate-diff review found no remaining
  Round 4 blocker.
- The broad backend suite retains four existing dependency, pytest-mark, and
  Alembic configuration warnings.
- Frontend lint retains 43 existing chat/settings warnings. Production output
  also retains existing Angular template/build, component-budget, Native
  Federation, and unconnected Nx Cloud warnings; all validation commands exit
  zero.
- The smoke validates emitted production assets, real federation, FastAPI,
  middleware, HttpOnly cookies, automatic invalidation, and recovery on the
  host. It does not build or launch a Docker image.
- No dependency manifests changed, so no dependency installation or upgrade was
  required for Round 4.
- Generated provider artifacts are unchanged.
- No raw credential, canary, customer, or label fixture value is included in
  this report.

# Round 5

## Status and commits

All six Round 5 blockers are implemented:

- every exported provider scalar family is structurally bounded and covered at
  the canonical projection and real MCP boundaries;
- input, handler, and projection failures share one context-free,
  provider-safe hosted MCP error path;
- compact privacy names are derived from the same families as tokenized names;
- HttpClient, native fetch, and EventSource transports share browser-session
  state, expiry, and recovery;
- browser CSRF tokens are cryptographically bound to one exact signed session
  and retained only in frontend memory; and
- hostile browser origins are rejected before authentication rate-limit
  accounting.

Round 5 commits:

- `77d6e9b` — `docs: design round 5 security hardening`
- `ed82903` — `fix(registry): bound provider-visible scalar families`
- `4bf61ee` — `fix(hosted): sanitize all provider tool failures`
- `3c74604` — `fix(registry): derive compact privacy compounds`
- `fdf94de` — `fix(auth): bind csrf to browser sessions`
- `1ec65cb` — `fix(frontend): share browser session transport expiry`
- `94569fc` — `test(frontend): smoke session-aware native transport`

The approved Round 3 browser-session design now records the Round 5
session-bound CSRF, trusted-origin, provider-scalar, hosted-error, native-fetch,
and EventSource extensions. The implementation plan records the vertical
RED/GREEN order used for this round.

## Finding 1 — Remaining provider scalars could smuggle sensitive text

### RED

The recursive exported-schema audit found unbounded identifiers, references,
capability collections, service/rate fields, monetary values, delivery dates,
counts, and arrays. Canonical `project_result()` calls and real
`FastMCP Client(server)` calls could keep a valid status while substituting
credential-, customer-, address-, or URL-shaped content into those other
scalar families. Numeric over-range cases were also accepted.

### GREEN

- All ShipAgent-owned IDs use a family-specific prefix and a bounded opaque
  body. Correlation, device, ingress, input, validation, preview, confirmation,
  job, and label families are distinct.
- Capabilities and address-guidance values are finite canonical enums.
- UPS service codes and names are sourced from the existing centralized
  carrier constants; the currency enum is sourced from the existing default
  currency constant.
- Money uses a bounded decimal grammar, delivery dates use a fixed ISO-date
  grammar, numeric values have explicit minima/maxima, and every exported array
  has an explicit maximum size.
- The privacy/schema walker now enforces the scalar-bound proof recursively for
  every exported input and output schema.
- Projection and real MCP tests preserve valid surrounding values while
  rejecting one adversarial scalar or out-of-range number at a time. The real
  MCP boundary returns only the generic provider error.
- OpenAI Apps, Claude public MCP, generic MCP, and canonical registry artifacts
  were regenerated from the canonical registry source.

## Finding 2 — Handler failures and exception context crossed the MCP boundary

### RED

Direct synchronous handler invocation and asynchronous handler awaiting could
raise their original exceptions. Projection failures raised the generic error
inside an `except` scope, retaining the rejected failure through
`__context__`. Real MCP responses and captured logs therefore had paths to
handler or rejected-result detail.

### GREEN

- Input validation, handler invocation/await, and result projection set only a
  bounded failure category.
- Logging and the generic `ToolError` occur after all `except` scopes. Both
  `__cause__` and `__context__` are absent.
- The warning contains only the canonical tool name and one of the bounded
  input/handler/projection categories. It never interpolates arguments,
  results, validator output, exception messages, or tracebacks.
- Direct sync/async tests and real FastMCP calls scan provider responses,
  exception links, and captured logs for every sensitive fixture category.

## Finding 3 — Compact privacy aliases were incomplete

### RED

Lowercase, camel/acronym, and uppercase adjacent spellings for API-key and
bearer material, customer content/rows, confirmation material, carrier
exchange bodies, and label/document transfer content passed the public-schema
privacy check. Token splitting alone could not establish their meaning.

### GREEN

- Credential, authorization-header, customer-content, customer-row,
  confirmation, carrier-direction/content, and label/document-transfer
  families are declared once.
- Compact fragments and ordering variants are deterministically derived from
  those same families, avoiding a second drifting alias list.
- Lowercase, camel/acronym, and uppercase fixtures are rejected.
- Legitimate bounded operational fields and opaque artifact identifiers remain
  accepted, and privacy-only changes do not create artifact drift.

## Finding 4 — Raw fetch and EventSource clients missed session expiry

### RED

A label PDF request returning 401 remained a local preview error, and
EventSource failures could enter consumer reconnect behavior without restoring
the shell gate. The common expiration signal was previously limited to Angular
HttpClient responses.

### GREEN

- A shared browser transport owns credentialed native fetch, adds the current
  CSRF token only to unsafe ShipAgent API requests, and expires the common
  browser session on 401. Origin and API-base matching prevent token forwarding
  to a different host with a similar path.
- Label PDF loading uses that transport.
- Shared conversation SSE and the dedicated job-progress EventSource use
  credentialed connections. An error closes the source before one session
  status check.
- Confirmed unauthenticated status completes the observable and emits the
  common expiry signal; it does not surface an ordinary consumer error or
  schedule a reconnect. Authenticated status produces one ordinary stream
  error.
- Label-401, shared SSE, job-progress SSE, and shell lifecycle tests cover
  blank-gate teardown and successful reauthentication across Native Federation
  boundaries.

## Finding 5 — Portable browser CSRF for Docker, Angular development, and Tauri

### RED

Origin-only cookie mutation checks could not support configured cross-origin
Angular development and Tauri sidecar clients. The mutation matrix lacked a
session-bound proof, and missing or invalid proof values did not provide the
approved portable boundary.

### GREEN

- Successful session exchange creates an HMAC-SHA256 CSRF value over a
  domain-separated message containing the complete signed browser session.
  Authenticated status deterministically recovers the same bounded token.
- Verification is length-bounded and uses constant-time comparison against the
  exact current session and configured API key. A token from another session or
  key fails.
- Disabled/unauthenticated status and session clear return `csrf_token: null`.
  The frontend stores authenticated tokens only in an injectable in-memory
  signal, clears them on expiry/clear, and never writes them to persistent
  storage.
- Protected unsafe cookie-authenticated requests require a trusted exact
  Origin and `X-CSRF-Token`. Valid API-key header callers remain exempt.
- The shared origin policy accepts normalized same-origin Docker requests and
  only explicitly configured Angular-development or Tauri origins. CORS exposes
  the dedicated CSRF request header only to that allowlist.
- Real onboarding mutations cover same-origin, configured development, Tauri,
  hostile, missing-token, invalid-token, and API-key-exempt cases. Rejections
  occur before route execution and leave persisted settings unchanged.

## Finding 6 — Hostile origins poisoned authentication rate limiting

### RED

More than the authentication-failure limit of hostile-origin/bad-key requests
could fill the shared loopback bucket. A following correct API-key request from
the same client then received 429.

### GREEN

- Any present, untrusted browser Origin is rejected before client-IP lookup,
  rate-limit lookup, or bad-key failure recording.
- Trusted-origin and non-browser bad-key requests retain normal authentication
  failure accounting.
- The regression floods the middleware with hostile-origin failures, observes
  403 for them, and then proves a correct API-key request from the same client
  succeeds.

## Real production non-HttpClient expiry smoke

The final default Playwright smoke:

1. Builds all seven frontend projects in production configuration and links all
   four Native Federation remotes.
2. Starts the real bundled FastAPI/static boundary with random runtime
   credentials and a deterministic fake conversation provider.
3. Authenticates, checks the HttpOnly/SameSite cookie, obtains the session-bound
   CSRF token, and proves a direct page `fetch()` mutation succeeds only with
   the dedicated header.
4. Clears the session, restores the blank gate, and authenticates a second
   distinct session.
5. Loads real federated chat content, creates a real conversation and
   EventSource, invalidates the exact browser cookie, and ends the controlled
   stream.
6. Observes an unauthenticated browser-session status check, gate restoration,
   remote teardown, a blank transient input, no page reload, and no EventSource
   reconnect.
7. Authenticates a third session and observes a protected settings response
   return 200.
8. Proves the three CSRF tokens are distinct, then scans local/session storage
   keys and values, request URLs, console output, rendered DOM, all observed
   cookie values, and every emitted asset for both the random API key and every
   CSRF token.

The pre-fix smoke RED was the direct onboarding request returning 403 without
CSRF. The final default build-and-smoke run passes with no browser console/page
error allowance and no runtime credential found on any inspected surface.

## Round 5 verification evidence

- Fresh affected backend slice:
  `../../.venv/bin/python -m pytest tests/api/test_browser_session.py tests/api/test_auth_middleware.py tests/api/test_main_config.py tests/hosted/test_hosted_mcp_registry.py tests/control_plane/test_result_projection.py tests/registry -q`
  — **283 passed, 1 warning in 1.04s**.
- Fresh broad backend suite:
  `../../.venv/bin/python -m pytest -q -k "not stream and not sse and not progress"`
  — **3,483 passed, 21 skipped, 103 deselected, 4 warnings in 48.98s**.
- Canonical provider regeneration produced no uncommitted change; artifact
  drift — **1 passed**.
- Frontend typecheck: all **6** configured project targets and the required
  shared-state declaration build passed.
- Frontend lint: all **6** configured targets passed with **0 errors** and the
  existing **43 warnings**.
- Frontend tests: all **6** configured targets passed, **132 tests** total:
  shared state **41**, chat **58**, shell **30**, and one each for domain,
  sidebar, and settings.
- Final default production smoke: all **7** production builds passed, all
  **4** remotes linked, and the real EventSource expiry/recovery/leak path
  passed. Two hash-matched build tasks used valid Nx cache output.
- `../../.venv/bin/python -m ruff check src/ tests/` — **All checks passed**.
- Ruff format check over all **15** Python files changed in Round 5 — all
  already formatted.
- Prettier check over every changed frontend TypeScript/MJS file and
  `node --check` over the smoke script passed.
- `git diff --check 3fd6290..HEAD` reports no whitespace errors.

## Round 5 self-review and remaining concerns

- Requirement-by-requirement review and aggregate-diff review found no
  remaining Round 5 blocker or regression to prior startup, migration,
  confirmation, audit, privacy, browser-session, or artifact fixes.
- Repository-wide Ruff format check still reports **251 pre-existing files**
  outside the Round 5 change set. All 15 changed Python files are format-clean;
  no unrelated repository-wide rewrite was performed.
- The broad backend warnings remain the existing defusedxml deprecation,
  unregistered extended pytest mark, and Alembic path-separator warnings.
- Frontend lint retains the 43 existing template/native-output warnings.
  Test/build output also retains existing Native Federation test-builder,
  Angular extended-diagnostic/component-budget, unconnected Nx Cloud, and
  outdated Nx agent-configuration notices; all required Nx commands exit zero.
  Nx task history labels `shell:test` as flaky, while the current run passed all
  **30** shell tests.
- The host production smoke exercises emitted assets, real federation,
  FastAPI, middleware, cookies, native EventSource behavior, and
  reauthentication. It does not build a Docker image or launch a Tauri binary;
  backend mutation tests cover configured Docker/dev/Tauri origins and frontend
  unit tests cover Tauri-safe API scoping.
- No dependency manifest changed, and no dependency installation or upgrade was
  required.
- No raw credential, CSRF, canary, customer, handler, carrier, or label fixture
  value is reproduced in this report.

# Round 6

## Status and commits

Both Round 6 blockers are implemented:

- compact provider-schema privacy compounds are derived in both token orders
  for every sensitive multi-token family; and
- production Tauri retains the Strict browser-session cookie by handing the
  trusted custom-protocol bootstrap to a sidecar-served, genuinely same-origin
  shell before federation or Angular initializes.

Round 6 implementation and design commits:

- `a805dbc` — `fix(registry): reject reversed compact privacy aliases`
- `1772833` — `fix(desktop): hand off Tauri shell to sidecar origin`
- `20f34af` — `docs: specify Tauri same-origin handoff`

The approved Round 3 security-hardening design now records the desktop
handoff, local-only native capability boundary, self-contained static package
topology, and Round 6 verification requirements.

## Finding 1 — Reversed compact privacy compounds

### RED

The new lower-, camel/acronym-, and uppercase matrix initially produced
**10 failures and 20 passes**. Concrete reversed compact names could bypass
the provider privacy guard even though their tokenized equivalents were
rejected. The probes covered:

- authentication header (`headerauthorization`);
- API and access keys (`keyapi`, `keyaccess`);
- label/document transfer (`urllabel`, `datadocument`);
- customer payload/address (`payloadcustomer`, `addresscustomer`);
- carrier exchange (`bodyrequest`); and
- token/secret values (`valuetoken`, `valuesecret`).

### GREEN

- Added one bidirectional compound generator and derived both orders from the
  existing centralized token families.
- Authentication headers, API/access keys, bearer values, label/document
  transfer, carrier exchange, customer content/rows, confirmation material,
  and token/secret values now use that generator.
- Tokenized credential-key checks use the same centralized key qualifiers.
- The complete case matrix now rejects schema construction at the canonical
  privacy boundary while existing legitimate compound fields remain accepted.
- Canonical provider artifact regeneration produces no change, and the drift
  test remains clean.

## Finding 2 — Tauri Strict cookie required a same-origin production shell

### RED

The vertical bootstrap tests first failed to compile because the repository had
no handoff function, pre-federation startup coordinator, relative production
API contract, or native-capability classifier. Packaging tests then failed
because:

- the trusted custom shell did not expose the supported Tauri global API;
- the capability did not explicitly prove a local-only boundary;
- the backend bundler omitted remote staging;
- the linker could not be exercised against an isolated frontend root; and
- PyInstaller collected a broader build directory instead of the exact
  sidecar static runtime path.

The first real production browser run exposed a further integration defect:
the pre-federation entry point statically imported the mapped
`@shipagent/shared-tauri` workspace library. The browser requested
`/%40shipagent/shared-tauri`, FastAPI returned the SPA fallback document, and
the authentication gate timed out after 30 seconds. Moving the handoff into a
shell-local module made that mapped import impossible before federation
initialization.

The first native compile also exposed an undeclared direct `tokio` dependency
for the existing timeout code. `cargo check` failed until the dependency was
declared explicitly.

### GREEN

- The packaged `tauri:`/`http://tauri.localhost` bootstrap invokes only
  `start_sidecar`, validates the returned ephemeral port, and uses
  `location.replace("http://127.0.0.1:<port>/")`.
- The handoff runs before federation and Angular. Its module is local to the
  shell and has no mapped workspace import.
- The sidecar reload is not classified as a packaged bootstrap origin, so it
  performs no native invocation or replacement and initializes exactly once.
- Production and ordinary FastAPI/Docker shells use relative `/api/v1`;
  Native Federation development at `http://localhost:4200` retains the
  `http://localhost:8000/api/v1` fallback.
- The Tauri command accepts no secret and returns only the port. The main
  capability is explicitly local and grants no remote URL IPC access.
  Frontend native detection also rejects the sidecar HTTP origin.
- Production bundling builds all projects, then requires and physically stages
  all four remotes inside the shell tree. Missing remote output fails closed.
- PyInstaller collects that exact self-contained tree at the frozen FastAPI
  runtime path. The sidecar therefore serves the shell, federation manifest,
  remote entries, chunks, API, cookie, native fetch, and EventSource from one
  origin.
- The production browser smoke explicitly fetches the manifest and all four
  remote entries from the sidecar origin, rejects unresolved pre-federation
  workspace imports, authenticates with the Strict HttpOnly cookie, mutates
  with session-bound CSRF, expires and reauthenticates, exercises EventSource
  recovery, and scans browser and emitted-static surfaces for the runtime API
  key and all CSRF tokens.

## Round 6 verification evidence

- Focused compact-name and legitimate-compound registry slice:
  `../../.venv/bin/python -m pytest tests/registry/test_catalog.py -q -k
  'compact_sensitive_aliases or legitimate_compound'`
  — **81 passed, 82 deselected**.
- Shell tests — **36 passed**.
- Desktop topology/packaging tests — **5 passed**.
- Fresh affected backend/security/registry/package slice:
  `../../.venv/bin/python -m pytest tests/registry
  tests/packaging/test_desktop_same_origin.py
  tests/api/test_browser_session.py tests/api/test_auth_middleware.py
  tests/api/test_main_config.py tests/api/test_security_headers.py -q`
  — **255 passed, 1 warning in 0.99s**.
- Fresh broad backend suite:
  `../../.venv/bin/python -m pytest -q -k "not stream and not sse and not
  progress"` — **3,518 passed, 21 skipped, 103 deselected, 4 warnings in
  51.09s**.
- Canonical provider regeneration produced no artifact change; artifact drift
  — **1 passed in 0.24s**.
- Frontend typecheck: all **6** configured targets plus the required
  shared-state declaration build passed.
- Frontend lint: all **6** configured targets passed with **0 errors** and the
  existing **43 warnings**.
- Frontend tests: all **6** configured targets passed, **138 tests** total:
  shared state **41**, chat **58**, shell **36**, and one each for domain,
  sidebar, and settings.
- Final default production build-and-browser smoke: all **7** production builds
  passed, all **4** remotes were physically staged, and the real same-origin
  shell/manifest/remotes/auth/CSRF/expiry/EventSource/recovery/leak path passed.
- `cargo fmt --check`, `cargo check --locked`, and `cargo test --locked` passed;
  the Rust target currently has **0 tests**.
- `../../.venv/bin/python -m ruff check src/ tests/` passed. Ruff format checks
  over all Round 6 Python changes passed.
- Prettier checks over every Round 6 TypeScript/MJS change, `node --check` over
  the production smoke, and shell syntax checks over both modified packaging
  scripts passed.
- `git diff --check` reports no whitespace errors.

## Round 6 self-review and remaining concerns

- Requirement-by-requirement and aggregate-diff review found no remaining
  Round 6 blocker or regression to prior startup, migration, confirmation,
  audit, provider privacy, hosted MCP, browser session, CSRF, expiry, artifact,
  or production-smoke fixes.
- No `cargo-tauri` CLI is installed, and the complete PyInstaller
  `dist/shipagent-core` resource was not available. An actual packaged Tauri
  WebView therefore could not be built or launched in this environment.
  Deterministic Tauri config/capability/package tests, locked Rust
  compile/tests, and the real Chrome/FastAPI bundled-equivalent static path
  provide the retained evidence required by the finding.
- Tauri's compile-time resource check required an exact temporary placeholder
  at the expected sidecar resource path. It was created only for the locked
  Cargo checks and removed immediately afterward; no placeholder or `dist`
  output remains.
- The sidecar-served document intentionally has no remote-origin native
  privilege. Consequently, the current Angular updater component does not run
  after the production handoff. A future updater must be owned by trusted
  local/native code rather than broadening sidecar-origin IPC access.
- A full PyInstaller bundle and Docker image were not built. The packaging
  tests exercise the exact collection/staging contracts, and the default
  production browser smoke rebuilds all frontend projects and uses the actual
  FastAPI static-serving code.
- Broad backend warnings remain the existing defusedxml deprecation,
  unregistered extended pytest mark, and Alembic path-separator warnings.
  Frontend lint retains the existing 43 warnings; production build output
  retains the existing Native Federation/Angular budget, Nx Cloud, and Nx
  agent-configuration notices.
- One direct `tokio` dependency was added to match the Rust source's existing
  timeout use. No JavaScript or Python dependency was installed or upgraded.
- No API key, signed session, CSRF token, customer content, carrier content,
  or label data is passed through the native bridge or reproduced in this
  report.

# Round 7

## Status and commits

All four Round 7 findings are implemented:

- downgrade removes only ShipAgent-owned control-plane tables and preserves a
  pre-existing PostgreSQL schema;
- browser development uses a relative API URL through the real Nx proxy to the
  documented backend port;
- audit identifiers use key-specific canonical families while external
  identifiers are hashed before persistence; and
- remote staging and the production smoke validate real federation manifests
  and emitted chunks instead of accepting a 200 SPA fallback.

Round 7 implementation commits:

- `5f73abd` — `fix(control-plane): preserve schemas on migration downgrade`
- `f1a15e8` — `fix(frontend): proxy relative dev API to port 8080`
- `ae18474` — `fix(control-plane): enforce audit ID families`
- `92a7113` — `fix(frontend): validate staged federation assets`

## Finding 1 — Downgrade destroyed unrelated schema objects

### RED

The new live PostgreSQL upgrade-to-downgrade test first created a unique schema
and sentinel table before Alembic ran. With the prior downgrade, the final
sentinel query failed because `DROP SCHEMA ... CASCADE` removed the complete
pre-existing schema, including the sentinel and Alembic state.

### GREEN

- Downgrade drops `audit_events`, `provider_connections`, and
  `cloud_accounts` explicitly and no longer drops the configured schema.
- The live test upgrades to `20260609_0001`, exercises the ORM against the
  migrated schema, downgrades to `base`, and proves the sentinel row survives.
- The same post-downgrade transaction proves all three ShipAgent tables and
  their audit indexes are absent and the retained Alembic version table has no
  active revision.
- The test uses a unique schema and removes it only in test cleanup.

## Finding 2 — Development API routing disagreed with the documented ports

### RED

The shell bootstrap unit test expected `/api/v1` at `localhost:4200` but
received the hard-coded `http://localhost:8000/api/v1` fallback. The first real
development smoke then launched the documented backend on 8080 and
`npx nx serve shell` on 4200; the old proxy attempted port 8000 and returned a
500 connection-refused response instead of backend JSON.

### GREEN

- Browser development, ordinary FastAPI/Docker production, and the
  sidecar-served Tauri shell all use relative `/api/v1`.
- The shell's Nx/Vite proxy forwards `/api` to `http://localhost:8080`, matching
  `scripts/start-backend.sh` and the README. No broad CORS allowance is needed.
- The backend launcher retains `.env` and the project virtualenv as defaults
  while permitting explicit environment-file and Python paths for an isolated
  smoke.
- `smoke:development-proxy` invokes the exact documented backend and frontend
  launchers, waits for both real servers, requests
  `/api/v1/auth/session` through port 4200, and requires the expected JSON
  contract.
- The final smoke observed the proxied request at the backend on 8080 and shut
  down both process groups cleanly.

## Finding 3 — Audit opaque IDs admitted compact PII and credential text

### RED

The vertical audit tests initially showed four missing boundaries:

- a compact person-like job identifier was accepted;
- compact internal account/connection/device fixtures were accepted;
- compact correlation/preview/confirmation fixtures were accepted; and
- the recorder had no external-identifier hashing input.

The expanded case matrix also covered mixed-case adjacent address, customer,
recipient/name, API/access-key, bearer/token, client-secret, password, and
`sk` credential marker families.

### GREEN

- Top-level account, provider-connection, and device identifiers accept only
  canonical lowercase UUIDs or their explicit `sa_account_`,
  `sa_connection_`, and `sa_device_` hexadecimal families.
- Job, correlation, preview, confirmation, and artifact identifiers accept
  canonical UUIDs or bounded family-specific ShipAgent prefixes. Artifact
  subfamilies cover artifact, document, label, and validation identifiers.
- Delimiter-insensitive, case-insensitive marker normalization rejects compact
  customer/address/name and credential/token/secret families before
  persistence.
- External order, provider reference/subject, and tracking identifiers enter
  through a separate bounded API and are persisted only as named SHA-256
  digests.
- Cleanup now validates its account identifier through the same canonical
  grammar.
- Legitimate fixtures were migrated to canonical values, with positive tests
  for every internal and workflow family and negative tests for compact
  privacy/credential forms.

## Finding 4 — Federation packaging and smoke accepted SPA fallbacks

### RED

The new packaging probes initially demonstrated that the linker exited zero
for an empty remote output, an HTML document named `remoteEntry.json`, a
manifest without exposed chunks, and a manifest referencing a missing chunk.
The prior browser smoke checked only status 200, which could not distinguish
those assets from FastAPI's `index.html` fallback.

### GREEN

- A dedicated linker validator requires a regular, non-symlink JSON entry with
  the expected remote name, at least one exposed chunk, a shared-chunk array,
  safe JavaScript basenames, and regular emitted files for every referenced
  exposed/shared chunk.
- Exposed chunks must contain JavaScript content; all referenced chunks reject
  HTML. The validator runs both before and after the physical copy into the
  shell, preserving the self-contained runtime topology.
- Negative packaging tests cover a missing remote, empty output, missing entry
  in a non-empty output, malformed/HTML entry, missing exposes, and a dangling
  chunk. The positive test proves manifests and chunks are physically staged,
  while the existing PyInstaller runtime-path contract remains covered.
- The production browser smoke parses the root federation manifest and each of
  the chat, sidebar, settings, and domain entries. It requires same-origin JSON
  responses, rejects HTML bodies, validates the declared remote name and
  exposed chunk path, then fetches a non-empty same-origin JavaScript chunk for
  every remote.
- The final real run fetched chat's `ChatContainer`, sidebar's
  `SidebarContent`, settings' `SettingsFlyout`, and domain's
  `DomainCardRegistry` emitted chunks before completing the authenticated
  sidecar flow.

## Round 7 verification evidence

- Focused live PostgreSQL migration coverage:
  `SHIPAGENT_TEST_DATABASE_URL=<isolated PostgreSQL 17 URL>
  ../../.venv/bin/python -m pytest
  tests/control_plane/test_migrations_postgres.py -q` — **3 passed**, including
  the pre-existing-schema upgrade/downgrade case.
- Complete control-plane suite with the same live PostgreSQL URL configured:
  `../../.venv/bin/python -m pytest tests/control_plane -q` — **135 passed,
  4 warnings in 0.71s**.
- Focused audit recorder suite — **71 passed in 0.29s**.
- Desktop same-origin/packaging suite — **10 passed in 0.83s**.
- Fresh broad backend suite:
  `../../.venv/bin/python -m pytest -q -k "not stream and not sse and not
  progress"` — **3,553 passed, 21 skipped, 103 deselected, 4 warnings in
  59.45s**.
- Canonical provider regeneration produced no uncommitted change; artifact
  drift — **1 passed in 0.26s**.
- Fresh uncached frontend typecheck, lint, and test matrix passed all **6**
  configured projects plus the required shared-state build. Tests totaled
  **138**: shared state **41**, chat **58**, shell **36**, and one each for
  domain, sidebar, and settings.
- The real development smoke launched the documented backend on 8080 and
  `nx serve shell` on 4200, then received authenticated-session JSON through
  the relative frontend `/api/v1` path.
- The final default production build-and-browser smoke passed all **7**
  production builds, physically staged all **4** remotes, fetched and parsed
  every entry plus an emitted JavaScript chunk, and completed the real
  same-origin auth/CSRF/expiry/EventSource/recovery/leak flow.
- `../../.venv/bin/python -m ruff check src/ tests/` passed. Ruff format checks
  over all **5** Round 7 Python files passed.
- Prettier checks over every changed frontend TypeScript, JSON, and MJS file
  passed. `node --check` passed for all **3** Round 7 MJS scripts.
- `cargo fmt --check`, `cargo check --locked`, and `cargo test --locked`
  passed; the Rust target currently has **0 tests**.
- Shell syntax checks passed for the backend launcher, backend bundler, and
  remote linker. `git diff --check 73f08dd..HEAD` reports no whitespace
  errors.

## Round 7 self-review and remaining concerns

- Requirement-by-requirement review and aggregate-diff review found no
  remaining Round 7 blocker or regression to the prior migration, Tauri,
  browser-session, CSRF, provider-privacy, MCP-sanitization, frontend-expiry,
  artifact, or packaging fixes.
- Docker Desktop's client is installed, but its daemon is unavailable. The
  required migration test therefore used an isolated local PostgreSQL 17
  server rather than a container; all live upgrade/downgrade assertions ran
  against that server.
- A complete PyInstaller backend bundle, Docker image, and packaged Tauri
  WebView were not built. Static packaging tests cover the exact staging and
  resource contracts, and the production smoke rebuilt the real frontend
  outputs and served them through the actual FastAPI static boundary.
- Tauri's resource check required the exact temporary
  `dist/shipagent-core` directory. It existed only for the locked Cargo checks
  and was removed immediately afterward; no backend placeholder remains.
- Broad backend output retains the existing defusedxml deprecation,
  unregistered `extended` pytest mark, and Alembic path-separator warnings.
  Frontend lint retains the existing **43 warnings**; build/test output retains
  the existing Native Federation builder, Angular diagnostic/budget, Nx Cloud,
  and Nx agent-configuration notices. All required commands exited zero.
- The repository README has broad pre-existing formatting drift outside the
  frontend Prettier gate and was not subjected to an unrelated whole-file
  rewrite. All changed executable frontend files are Prettier-clean, all
  changed Python files are Ruff-format-clean, and the aggregate diff is
  whitespace-clean.
- No dependency manifest was changed beyond adding npm smoke command entries;
  no dependency was installed or upgraded.
- No database credential, API key, signed session, CSRF value, customer
  fixture, external identifier, carrier content, or label data is reproduced
  in this report.

# Round 8

## Status and commits

The Round 8 job-progress SSE reliability finding is implemented. Authenticated
or conservatively unconfirmed transient failures now refresh the authoritative
REST progress snapshot and reconnect with bounded exponential backoff, while
confirmed session expiry retains the shared expiry gate and no-loop behavior.

Round 8 implementation commit:

- `a5e4277` — `fix(frontend): recover job progress streams`

## Vertical TDD evidence

### Authenticated transient recovery

RED:

- The first new behavior test authenticated the browser session, failed the
  active progress `EventSource`, advanced timers, and required a second REST
  progress request followed by exactly one replacement stream.
- The old service logged the closed connection and froze. The focused run
  failed with `getJobProgress` expected **2** calls but receiving **1**; the
  suite result was **1 failed, 58 passed**.

GREEN:

- Progress connections now have a job/lifecycle generation, one active source,
  and a recovery path that closes the failed source, performs one session
  check, refreshes `GET /jobs/{id}/progress`, and only then schedules a
  replacement source.
- The authenticated test proves one status check, two total snapshots
  (initial plus recovery), one closed failed source, and one replacement source
  using credentials.
- A separate test makes the status endpoint fail transiently and proves the
  conservative branch still attempts the authoritative snapshot and bounded
  reconnect instead of freezing.

### Missed terminal snapshot recovery

RED:

- A real `ProgressDisplayComponent` test started from a running snapshot,
  failed SSE, returned `completed` from the recovery snapshot, and required the
  component completion output without another stream.
- The progress signal and output recovered, but the initial implementation
  incorrectly opened a replacement stream. The focused run failed with **2**
  sources instead of **1**; the suite result was **1 failed, 59 passed**.

GREEN:

- Snapshot refresh returns the authoritative status. Recovery stops before
  scheduling when it observes `completed` or `failed`, updates the job-list
  projection, and leaves the terminal progress signal available to the
  component effects.
- Component-level tests prove both completion and failure outputs fire exactly
  once from missed terminal REST snapshots, with no terminal reconnect.
- Initial page-refresh recovery also avoids opening a stream for a snapshot
  already known to be completed or failed.

### Bounded failures and no duplicate streams

RED:

- The repeated-failure test double-fired each failed source to exercise the
  per-source error guard, then failed four consecutive stream generations.
- The unbounded implementation created **5** sources where the test permitted
  only the initial stream plus **3** reconnects; the suite result was
  **1 failed, 61 passed**.

GREEN:

- Consecutive recovery uses delays of **250 ms**, **500 ms**, and **1,000 ms**
  with a limit of **3** replacement attempts. A successfully opened source
  resets the consecutive-failure budget.
- Every failed generation still performs one status check and one authoritative
  snapshot, including the exhausted generation so terminal state is not lost.
- The repeated-failure test proves four failures cause four status checks, four
  recovery snapshots, only four total sources, no active source after
  exhaustion, and no duplicate effect from a repeated error callback.

### Stale work cancellation and generation guards

RED:

- The job-change test held the failed generation's session-status Observable
  open and switched jobs. Generation checks prevented a stale reopen, but the
  underlying request remained subscribed; the run failed because its teardown
  flag stayed `false` (**1 failed, 62 passed**).
- A later stale-source test switched jobs, then delivered a terminal message
  through the old closed source. The old handler changed the new job's status
  to `completed` instead of leaving it `running` (**1 failed, 67 passed**).

GREEN:

- The shared browser-session confirmation accepts an optional abort signal.
  Job lifecycle changes abort `takeUntil`-guarded status and snapshot
  Observables, so their actual subscriptions are torn down rather than merely
  ignored after resolution. Existing shared conversation SSE callers retain
  the unchanged no-signal behavior.
- Disconnect/job change and destruction abort pending status/snapshot work,
  clear reconnect timers, close the source, reset attempts, and increment the
  lifecycle generation.
- Source message/error handlers verify both source identity and job generation.
  Stale sources cannot update progress, start another session check, reset retry
  state, or reopen a stream.
- Behavioral tests separately prove cancellation of a pending status check on
  job change, a pending snapshot on destroy, and scheduled timers on both job
  change and destroy.

### Confirmed expiry

- The retained expiry test now additionally proves that the failed progress
  source performs only its initial snapshot: one session check emits the shared
  expiry signal, repeated error delivery does nothing, no recovery snapshot is
  requested, and no replacement `EventSource` is created.

## Round 8 verification evidence

- Focused chat service/component suite:
  `npx nx test chat-remote` — **68 passed** across **5** files. The Round 8
  change adds **10** job-progress recovery behaviors to the previous **58**.
- Fresh uncached frontend typecheck matrix:
  `NX_SKIP_NX_CACHE=true npx nx run-many -t typecheck --all` — all **6**
  configured projects and the required shared-state dependency build passed.
- Fresh uncached frontend lint matrix:
  `NX_SKIP_NX_CACHE=true npx nx run-many -t lint --all` — all **6** projects
  passed with **0 errors** and the unchanged **43 warnings**.
- Fresh uncached frontend test matrix:
  `NX_SKIP_NX_CACHE=true npx nx run-many -t test --all` — all **6** projects
  passed, **148 tests** total: shared state **41**, chat **68**, shell **36**,
  and one each for domain, sidebar, and settings.
- Fresh uncached frontend production builds:
  `NX_SKIP_NX_CACHE=true npx nx run-many -t build --all
  --configuration=production` — all **7** targets passed.
- Default production browser smoke:
  `npm run smoke:authenticated-production` — rebuilt the production targets,
  physically staged all **4** remotes, fetched and parsed their real
  federation entries and emitted chunks, and passed the same-origin
  auth/CSRF/expiry/EventSource/recovery/cleanup flow through the actual FastAPI
  static boundary.
- Relevant packaging and provider checks:
  `../../.venv/bin/python -m pytest
  tests/packaging/test_desktop_same_origin.py
  tests/registry/test_artifact_drift.py -q` — **11 passed**.
- Fresh broad backend regression suite:
  `../../.venv/bin/python -m pytest -q -k "not stream and not sse and not
  progress"` — **3,553 passed, 21 skipped, 103 deselected, 4 warnings in
  51.68s**.
- `../../.venv/bin/python -m ruff check src/ tests/`, Prettier checks over all
  **3** changed TypeScript files, `node --check` over the production smoke, and
  `git diff --check` all passed.

## Round 8 self-review and remaining concerns

- Requirement-by-requirement and aggregate-diff review found no remaining Round
  8 blocker and no regression to the existing shared browser-session expiry,
  credentialed EventSource, CSRF, same-origin, federation, packaging, provider,
  migration, Tauri, or audit boundaries.
- Recovery is intentionally bounded to three consecutive replacement streams.
  A successful `open` event resets that budget; an indefinitely unhealthy
  endpoint stops reconnecting after the final authoritative snapshot rather
  than creating an endless browser loop.
- A transient failure of both session confirmation and the progress snapshot
  still consumes one bounded retry. A confirmed unauthenticated session always
  stops immediately and emits the shared expiry signal.
- Broad backend output retains the existing defusedxml deprecation,
  unregistered `extended` pytest mark, and Alembic path-separator warnings.
  Frontend lint retains the existing **43 warnings**; production build output
  retains the existing Native Federation, Angular diagnostic/budget, Nx Cloud,
  and Nx agent-configuration notices. All required commands exited zero.
- No dependency or generated provider artifact changed. No API key, signed
  session, CSRF token, customer content, carrier content, or label data is
  reproduced in this report.

# Round 9

## Status and commits

All four Round 9 findings are implemented. Provider-visible identifiers now use
one centralized, server-minted, family-specific 32-lowercase-hex format. Job
progress recovery now has a meaningful-frame retry reset, a hard handshake
failure cap, post-subscription REST reconciliation with stale-result guards, and
diagnostic-preserving snapshot merges.

Round 9 implementation commits:

- `99a52f3` — `fix(registry): require server-minted provider IDs`
- `df0df55` — `fix(frontend): harden job progress recovery`
- `1123fde` — `fix(audit): enforce canonical provider IDs`

## Vertical TDD evidence

### Exact server-minted provider identifiers

RED:

- The first mint/parse test failed during collection with
  `ModuleNotFoundError: src.registry.identifiers`.
- After introducing the identifier module, the whole-public-catalog schema scan
  failed against the permissive 16–96-character public schemas.
- Migrating schemas to the exact format exposed **18** stale positive fixtures
  that still used 16-character bodies.
- A provider-export admission regression test then failed with
  `DID NOT RAISE`, proving a hand-written permissive `job_id` schema could still
  bypass the canonical helper.

GREEN:

- `ShipAgentIdFamily` is the single registry of the **9** public families:
  correlation, device, ingress, input, validation, preview, confirmation, job,
  and label.
- The shared helper emits exact
  `^sa_<family>_[0-9a-f]{32}$` schemas with matching fixed `minLength` and
  `maxLength`, mints values with cryptographic randomness, and parses only the
  canonical representation.
- Provider export admission recursively rejects known ID/reference fields that
  do not use their registered family schema, as well as unregistered
  provider-visible `*_id` and `*_reference` fields.
- Catalog tests scan every input/output schema and prove all registered fields
  use the exact helper. Positive tests mint and parse every family.
- Direct result-projection and real FastMCP matrices cover all **9** families
  against **6** correctly prefixed compact/base64 canary bodies: credential,
  token, customer/name, recipient, address, and base64-encoded content. Invalid
  inputs never reach handlers; invalid outputs return only the provider-safe
  error and do not enter logs.
- Real FastMCP round-trip fixtures exercise every public tool and every
  canonical family occurrence.
- All four provider artifacts were regenerated from the canonical registry and
  now contain the exact patterns and fixed lengths.

The required ownership check was evaluated separately from syntax validation.
This branch has no production hosted public-tool handlers or backing reference
store: the hosted registry is a contract/readiness boundary and the real MCP
tests bind test handlers. FastMCP therefore enforces the exact syntax before
dispatch, but there is no truthful tenant-ownership lookup to add yet. A future
production handler must validate reference existence and authenticated tenant
ownership at its service boundary.

### Audit-boundary consistency addendum

RED:

- Aggregate self-review found that the control-plane audit allowlist still
  recognized legacy variable-length `sa_*` bodies. Six new device/workflow
  cases using 24- or 34-hex bodies all failed with `DID NOT RAISE`; the focused
  result was **6 failed, 71 deselected**.

GREEN:

- Workflow IDs persisted in audit details now delegate to the same canonical
  parser used by provider contracts. Internal account/connection identifiers
  and UUIDs remain separate internal formats.
- The 36-character audit `device_id` column remains an internal UUID field and
  now rejects `sa_device_*` values instead of accepting a noncanonical body or
  silently widening persistence without a migration.
- Internal `sa_artifact_*`/`sa_document_*` values are fixed at 32 hex, while
  public label and validation artifacts use their registered canonical
  families.
- The complete audit service suite is **76 passed**; the complete
  control-plane suite is **193 passed, 1 skipped, 2 warnings**.

### Retry budget no longer resets on handshake

RED:

- The repeated `open → error` test double-fired each error callback and expected
  the initial stream plus at most three replacements. The old `onopen` reset
  produced **5** sources instead of **4**; the focused result was
  **1 failed, 68 passed**.
- A follow-up test required a real progress frame to restore retry capacity.
  Before implementing the meaningful-frame reset it saw **4** sources instead
  of **5**; the focused result was **1 failed, 69 passed**.

GREEN:

- Opening a socket no longer changes the retry budget. Only a recognized,
  non-ping progress event resets consecutive failures.
- The handshake-loop test proves four failures produce only four total sources,
  four session checks, eight snapshots, no live source, and no pending timer.
- The meaningful-frame test proves an actual `row_started` event resets the
  budget and permits a later bounded recovery sequence.

### Post-subscription terminal reconciliation

RED:

- A component test returned `running` before the 250 ms backoff and
  `completed` only after the replacement should have subscribed. The first
  implementation made only **2** snapshot calls instead of the required
  **3**; the focused result was **1 failed, 70 passed**.
- A held post-subscription snapshot then overwrote a newer `row_completed`
  frame, leaving `processed` at **1** instead of **2**; the focused result was
  **1 failed, 71 passed**.

GREEN:

- Each bounded retry establishes its replacement EventSource first and then
  requests an authoritative REST snapshot, closing the replacement immediately
  when reconciliation observes `completed` or `failed`.
- A per-job progress revision plus exact source/generation identity guards
  prevent a delayed reconciliation from overwriting a newer SSE frame, another
  source generation, a job switch, or a destroyed component.
- The real `ProgressDisplayComponent` test proves a completion transition
  during backoff emits completion once and closes the replacement stream.

### Recovery preserves event-only diagnostics

RED:

- The terminal-failure recovery test first delivered row-completed,
  row-failed, and row-started events, then applied running and failed REST
  snapshots. The old replacement update erased `error`, `rowFailures`,
  `currentRow`, and `lastTrackingNumber`; the focused result was
  **1 failed, 72 passed**.
- Extracting completion metadata into a directly testable helper first failed
  because the module did not exist.

GREEN:

- REST reconciliation merges authoritative aggregate counts, cost, optional
  international fields, and status into the current same-job signal while
  preserving event-only diagnostics that the REST contract does not contain.
- Diagnostics are reset explicitly only when a new job initializes or when an
  SSE event actually supersedes them.
- The shared completion-metadata builder is used by both success and failure
  paths and carries `error`, `rowFailures`, `currentRow`, and
  `lastTrackingNumber` into the persisted chat artifact.
- The final chat suite is **73 passed** across **5** files.

## Round 9 verification evidence

- Final focused audit/provider/MCP/projection suite:
  `../../.venv/bin/python -m pytest
  tests/control_plane/audit/test_service.py
  tests/registry/test_identifiers.py tests/registry/test_catalog.py
  tests/provider_adapters/test_projections.py
  tests/control_plane/test_result_projection.py
  tests/hosted/test_hosted_mcp_registry.py
  tests/registry/test_artifact_drift.py -q` — **456 passed in 1.94s**.
- Fresh broad backend regression suite:
  `../../.venv/bin/python -m pytest -q -k "not stream and not sse and not
  progress"` — **3,672 passed, 21 skipped, 103 deselected, 4 warnings in
  51.34s**. The later audit addendum was revalidated by both the 76-test audit
  suite and the complete 193-test control-plane suite.
- Fresh uncached frontend typecheck matrix passed all **6** configured projects
  and the required shared-state build.
- Fresh uncached frontend lint matrix passed all **6** projects with **0
  errors** and the unchanged **43 warnings**.
- Fresh uncached frontend test matrix passed all **153 tests**: shared state
  **41**, chat **73**, shell **36**, and one each for domain, sidebar, and
  settings.
- Fresh uncached production builds passed all **7** targets.
- `npm run smoke:authenticated-production` rebuilt the production application,
  physically staged all **4** remotes, loaded the real federation shell through
  FastAPI, and passed authenticated settings, session clearing/restoration,
  same-origin API, CSRF/session expiry, EventSource invalidation/recovery, and
  cleanup checks with runtime secrets absent.
- Desktop same-origin packaging plus artifact drift — **11 passed**.
  Canonical provider regeneration produced zero uncommitted changes; the
  standalone artifact drift test also passed.
- `../../.venv/bin/python -m ruff check src tests` passed. Ruff format checks
  passed over all **10** Round 9 Python files.
- Prettier checks passed over the three fully modified/new job-progress service,
  test, and metadata files. The small ChatContainer integration was
  diff-reviewed without rewriting its unrelated pre-existing whole-file style.
- `bash -n` passed for every repository shell script. `node --check` passed for
  all three frontend MJS validation/smoke scripts.
- `cargo fmt --check`, `cargo check --locked`, and `cargo test --locked`
  passed; the Rust target currently has **0 tests**.
- Provider regeneration, final artifact drift, and aggregate
  `git diff --check` all passed with a clean worktree before this report commit.

## Round 9 self-review and remaining concerns

- Requirement-by-requirement review, implementation-diff review, and a search
  for the removed permissive public-ID grammar found no remaining Round 9
  blocker or regression to the prior provider privacy, MCP projection, auth,
  CSRF, migration, Tauri, development proxy, audit, packaging, or SSE-expiry
  fixes.
- Public ID schemas intentionally validate syntax, not ownership. Ownership
  cannot be truthfully tested until production hosted handlers and a
  tenant-scoped reference store exist; that future service boundary remains a
  release requirement when those handlers are implemented.
- Retry recovery remains intentionally bounded to three replacement streams.
  A handshake alone never signals stability; one recognized progress event
  does. Every failed generation still performs the pre-backoff session/snapshot
  checks, and every created replacement performs post-subscription
  reconciliation.
- Broad backend output retains the existing defusedxml deprecation,
  unregistered `extended` pytest mark, and Alembic path-separator warnings.
  Frontend output retains the existing 43 lint warnings and Native Federation,
  Angular diagnostic/budget, Nx Cloud, and Nx agent-configuration notices. All
  required commands exited zero.
- Tauri's resource check required the exact temporary
  `dist/shipagent-core` directory. It existed only for the locked Cargo checks
  and was removed immediately afterward.
- A complete PyInstaller bundle, Docker image, and packaged Tauri WebView were
  not built. Static packaging contracts, all production frontend builds, and
  the real production browser smoke cover the changed paths.
- No dependency was added or upgraded. No API key, signed session, CSRF value,
  credential canary, customer content, carrier content, or label data is
  reproduced in this report.

# Round 10 final review fixes

## Status and commits

All four Round 10 findings are fixed. There are no known Round 10 blockers.

Round 10 implementation commits:

- `e0c6fe6` — `fix(registry): reject identifier alias bypasses`
- `becf6b0` — `fix(frontend): close terminal and stale SSE races`

## Vertical TDD evidence

### Replacement reconciliation starts only after EventSource `open`

RED:

- The replacement-subscription test asserted that the initial snapshot and
  pre-retry recovery snapshot were the only two REST calls before
  `emitOpen()`. The old implementation had already made a third call, so the
  assertion failed with **expected 2, received 3**.
- Repeating `emitOpen()` was included in the regression scenario so an
  unguarded callback would start duplicate reconciliation.

GREEN:

- A replacement EventSource receives an `onopen` handler carrying the exact
  source, job ID, lifecycle generation, and active abort signal.
- Reconciliation starts from that handler only. A source-local
  `reconciliationStarted` guard makes repeated open callbacks idempotent.
- Initial streams do not perform an unnecessary post-open snapshot; only
  bounded replacement streams reconcile after the server has accepted the
  subscription.
- `onopen` does not touch the retry counter. Only a recognized non-ping
  progress frame restores retry capacity.
- The regression test proves there are exactly two snapshots before open,
  exactly one additional snapshot after two open callbacks, terminal
  completion is recovered, the replacement closes, and completion emits once.
- The delayed-reconciliation revision/source tests and repeated retry-budget
  tests remain green.

### Identifier admission covers normalized singular and plural aliases

RED:

- The camel/Pascal/acronym fixtures for `artifactId`,
  `ArtifactReference`, and `artifactID` all failed with `DID NOT RAISE`.
- Compact aliases including `artifactid` and `artifactreferences` also failed
  with `DID NOT RAISE`.
- A registered-family `job_ids` field using the canonical scalar schema instead
  of an array failed with `DID NOT RAISE`.

GREEN:

- Property names are tokenized across snake case, camel case, Pascal case,
  acronym boundaries, hyphens, dots, and other non-alphanumeric separators.
- Singular/plural `id`, `ids`, `reference`, and `references` suffixes normalize
  to the compact canonical field registry.
- Compact spellings are fail-closed. The established boolean field `valid` is
  the sole documented exception because its ordinary spelling happens to end
  in `id`.
- Unregistered identifier-like fields fail provider-export admission.
  Registered aliases must use the exact canonical family schema, and plural
  aliases must be arrays whose items use that exact schema.
- The existing object/array visitor enforces the same rules recursively.
- Adversarial tests cover snake, camel, Pascal, acronym, hyphen, dot, compact,
  plural, nested-object, and nested-array cases. Positive fixtures cover
  registered aliases and exact singular/plural family schemas.
- Final identifier/catalog/artifact focused result: **186 passed**. Canonical
  provider regeneration produced no changed artifact, and artifact drift
  passed independently.

### Warning and cancellation statuses are terminal on every progress path

RED:

- An initial `completed_with_warnings` snapshot left the component completion
  spy at **0 calls**.
- A live warning completion was collapsed to `completed`, losing the warning
  outcome.
- The warning and cancellation completion artifacts lacked explicit status,
  outcome, warning/cancellation flags, and user-facing terminal messages.
- The backend observer test initially failed because
  `on_batch_completed(..., status="completed_with_warnings")` did not accept or
  emit a status.

GREEN:

- The shared `JobStatus` union now matches the backend enum by including
  `completed_with_warnings`.
- `getJobTerminalState` is the single frontend classifier for completed,
  completed-with-warnings, failed, and cancelled states.
  `resolveJobTerminalStatus` accepts a reported live status only when it
  belongs to that event's completion/failure outcome, preserving legacy frames
  that omit status without allowing a mismatched frame to cross outcome paths.
- Initial REST, pre-retry recovery, post-open reconciliation, and live SSE all
  use the centralized classification. Warning completion follows the existing
  completion output; cancellation follows the existing failure output with an
  explicit cancellation message.
- Any live terminal frame closes the exact source, aborts its lifecycle, clears
  pending recovery, and refreshes the job list. Warning/cancellation snapshots
  likewise stop stream creation or reconnection.
- Backend live completion frames now include `completed` or
  `completed_with_warnings`; failure frames can include `failed` or
  `cancelled`. Preview execution forwards its canonical successful terminal
  status.
- Progress and completion-artifact components distinguish warning and
  cancellation headers, badges, messages, and actions. Component outputs carry
  the complete terminal interpretation, and persisted completion metadata
  retains status, outcome, warning flag, cancellation flag, and message.
- Tests cover initial snapshot, live frame, and missed-event recovery snapshot
  for both new statuses, plus component output and persisted metadata.
  Existing completed/failed recovery tests remain green.
- Backend observer coverage is **2 passed**; the complete chat-remote suite is
  **86 passed**.

### Shared SSE cannot apply an old session check after teardown

RED:

- In the delayed-response scenario, replacing an errored old stream left its
  browser-session request subscribed:
  `oldStatusCheckCancelled` was **false**.
- That demonstrated the old request could later apply an unauthenticated
  response after a replacement session had been authenticated.

GREEN:

- Every shared SSE subscription owns a monotonically increasing generation and
  an AbortController.
- Unsubscribe, explicit disconnect, a replacement `connect`, and service
  destruction abort the outstanding session confirmation even when the failed
  EventSource itself is already null.
- Open, message, error, async confirmation continuation, and teardown paths
  require the exact generation/controller/source identity. Teardown from an
  old Observable cannot close a newer source.
- Browser session confirmation checks both cancellation and the supplied
  current-generation predicate immediately before applying status or expiry.
- The delayed old-stream test performs error, source replacement, expiry,
  re-authentication with a new CSRF token, and delivery of the old
  unauthenticated result. It proves the request was cancelled and the new token
  and expiration generation remain unchanged.
- Parameterized tests prove the same result for unsubscribe, disconnect, and
  destruction. Stale source callbacks are also ignored.
- Existing confirmed-expiry one-check/no-loop behavior and ordinary authenticated
  error behavior remain green. The focused session-aware suite is **31 passed**.

## Round 10 verification evidence

- Focused backend provider/registry/model/projection/control-plane/hosted
  boundary/artifact/observer/preview matrix:
  `../../.venv/bin/python -m pytest
  tests/registry/test_identifiers.py tests/registry/test_models.py
  tests/registry/test_catalog.py tests/provider_adapters/test_projections.py
  tests/control_plane/test_result_projection.py
  tests/hosted/test_hosted_mcp_registry.py
  tests/registry/test_artifact_drift.py
  tests/orchestrator/batch/test_sse_observer.py tests/api/test_preview.py -q`
  — **446 passed, 1 warning in 1.64s**.
- Non-stream progress API fallback coverage:
  `../../.venv/bin/python -m pytest tests/api/test_progress.py -q -k "not
  stream"` — **4 passed, 3 deselected, 1 warning**.
- Fresh broad backend regression suite:
  `../../.venv/bin/python -m pytest -q -k "not stream and not sse and not
  progress"` — **3,696 passed, 21 skipped, 105 deselected, 4 warnings in
  48.90s**.
- Fresh uncached frontend typecheck matrix passed all **6** configured projects
  and the required shared-state build.
- Fresh uncached frontend lint matrix passed all **6** projects with **0
  errors** and the unchanged **43 warnings**.
- Fresh uncached frontend test matrix passed all **166 tests**: shared state
  **41**, chat **86**, shell **36**, and one each for domain, sidebar, and
  settings.
- Fresh uncached production builds passed all **7** targets.
- `npm run smoke:authenticated-production` rebuilt all production targets,
  physically staged all **4** remotes, served the federation shell through
  FastAPI, and passed authenticated settings, session clear/restore,
  same-origin API, EventSource invalidation/recovery, retry authentication, and
  cleanup checks with runtime secrets absent.
- Provider artifacts were regenerated from the canonical registry and produced
  no worktree changes. The standalone drift test passed.
- Desktop same-origin packaging plus artifact drift passed **11 tests**.
- `../../.venv/bin/python -m ruff check src tests` passed. Ruff format checks
  passed over the four fully modified/new Round 10 Python files. The one-line
  preview integration was diff-reviewed without rewriting that file's
  unrelated pre-existing format differences.
- Prettier checks passed over the six fully modified frontend service/type/test
  files. The small integrations in four pre-existing component files were
  diff-reviewed without whole-file formatting churn.
- `bash -n` passed for every tracked repository shell script. `node --check`
  passed for every tracked MJS script.
- `cargo fmt --check`, `cargo check --locked`, and `cargo test --locked`
  passed; the Rust target currently has **0 tests**.
- Provider regeneration, final artifact drift, cached-diff checks, and
  aggregate `git diff --check` all passed.

## Round 10 self-review and remaining concerns

- Requirement-by-requirement review, implementation-diff review, and targeted
  searches for direct completed/failed comparisons in the changed progress
  lifecycle found no remaining Round 10 blocker.
- Replacement reconciliation is intentionally tied to the browser's `open`
  callback. This is the earliest EventSource signal that the connection has
  been established; exact identity and revision guards still discard stale
  results if a newer frame or lifecycle wins the race.
- Compact identifier detection is intentionally fail-closed. Ordinary compact
  words ending in `id` require an explicit reviewed exception; only the
  existing provider field `valid` is currently exempted.
- Older live terminal frames remain compatible because missing status maps to
  `completed` or `failed`. An invalid or cross-outcome status cannot turn a
  failure frame into success or a completion frame into failure.
- The synchronous TestClient tests that call an infinite SSE endpoint with
  `client.get()` do not terminate, despite their comments saying they close
  immediately. An aggregate focused attempt that included those existing tests
  was stopped after approximately 85 seconds; it is not reported as a pass.
  This repository's documented broad command excludes stream/SSE/progress
  tests. The changed live contracts are covered by observer tests, 31
  session-aware frontend tests, the full frontend matrix, and the real
  authenticated production browser smoke.
- Broad backend output retains the existing defusedxml deprecation,
  unregistered `extended` pytest mark, and Alembic path-separator warnings.
  Frontend output retains the existing 43 lint warnings and Angular,
  federation, Nx Cloud, and Nx agent-configuration notices. All required
  completed commands exited zero.
- Tauri's resource check required the exact temporary
  `dist/shipagent-core` directory. It existed only for the locked Cargo checks
  and was removed immediately afterward.
- A complete PyInstaller bundle, Docker image, and packaged Tauri WebView were
  not built. Static packaging contracts, every production frontend build, and
  the production browser smoke cover the changed paths.
- No dependency was added or upgraded. No generated provider artifact changed.
  No API key, authenticated session value, CSRF token, credential canary,
  customer content, carrier content, or label data is reproduced in this
  report.

# Round 11 final review fixes

Status: all three findings in
`.superpowers/sdd/final-review-round-11-findings.md` are fixed and verified.

Implementation commits:

- `29728c7 fix(security): fail closed on public listeners`
- `391f827 fix(registry): export warning job status`
- `f543802 fix(frontend): persist every terminal job artifact`

## Round 11 TDD evidence and implementation

### Public listeners require authentication that is actually installed

RED:

- A public bundled launch configured with `auth_mode=auth0` plus issuer and
  audience strings did not raise when `SHIPAGENT_API_KEY` was absent.
- A public bundled launch also accepted a configured API key below the
  middleware's existing minimum strength.
- These failures demonstrated that future-looking Auth0 configuration was
  being treated as a launch posture even though there is no JWT/Auth0 request
  verifier installed.

GREEN:

- `validate_startup_security()` now treats the exact listener bind host as the
  security boundary. Every non-loopback host invokes the API middleware's
  existing key-strength validator and requires a nonempty
  `SHIPAGENT_API_KEY`.
- The startup gate imports the same key resolver and strength validator used by
  request middleware, so launch admission and actual request enforcement
  cannot silently use different definitions of an effective key.
- `auth_mode=auth0`, issuer strings, audience strings, and environment labels
  do not count as request authentication. A future real JWT verifier must be
  installed and explicitly wired before this policy can be relaxed.
- The bundled server validates before constructing/running Uvicorn. The daemon
  validates before importing Uvicorn, inspecting or writing a PID file, or
  starting a process.
- Missing, weak, and strong-key cases are covered for both public bundled and
  daemon launches. Loopback keyless regressions remain usable, `fake_local`
  remains restricted to local loopback operation, and the existing Docker
  strong-key path remains green.
- A real FastAPI lifespan/TestClient smoke starts in public production mode
  with a strong key and calls `/api/v1/jobs`: the request without credentials
  returns **401**, while the request carrying the configured key returns
  **200**.
- Focused startup, configuration, bundle, daemon, Docker, and real auth-route
  coverage is included in the **461-test** combined Round 11 backend matrix.

### Provider job status comes from one explicit canonical mapping

RED:

- A real hosted FastMCP call returning
  `status="completed_with_warnings"` was rejected at the provider-safe result
  projection boundary.
- The first canonical-source tests failed because no neutral job-status module
  or backend-to-provider mapping existed.
- The deliberately unexported `paused` status initially leaked a raw mapping
  lookup failure instead of explaining that the state is not provider-visible.
- Moving the enum initially changed the established OpenAPI component name.
  A regression test caught that compatibility change.
- Before regeneration, the artifact drift test reported the expected status
  enum deltas in all four generated provider artifacts.

GREEN:

- `src/job_status.py` is the canonical neutral module shared by the database
  model and API schema. `JobStatusEnum` preserves the established OpenAPI
  component name, and `JobStatus` remains the database/runtime alias.
- `ProviderJobStatus` and the immutable
  `BACKEND_TO_PROVIDER_JOB_STATUS` mapping make every exposed semantic
  conversion explicit: backend `pending` becomes provider `queued`; running
  and the four terminal states preserve their meanings.
- `completed_with_warnings` is now a first-class provider-safe terminal value.
  Backend `paused` remains intentionally unexported and the conversion helper
  raises a specific `ValueError` for it.
- Both public job output schemas derive their enum from the mapping; the old
  registry-local status string list is removed.
- A real FastMCP round trip now accepts and returns
  `completed_with_warnings`, while the existing strict result projection still
  rejects values outside the generated contract.
- The OpenAI Apps, generic MCP, Claude remote MCP, and canonical registry
  artifacts were regenerated from the canonical source. Regeneration is
  idempotent and the drift test passes from a clean tree.

### Every terminal chat outcome appends and persists the same artifact shape

RED:

- A component-level failed-job test reached the terminal handler but observed
  **0** calls to `saveArtifact()`. The artifact existed only in the in-memory
  conversation store and would disappear after history reload.

GREEN:

- `appendAndPersistTerminalArtifact()` is the single component path for
  completed, completed-with-warnings, failed, and cancelled outcomes.
- The helper builds metadata once, appends the system artifact, and invokes
  `saveArtifact()` while the executing job identity is still active. Both
  terminal handlers clear execution state only after that invocation.
- Failure and cancellation preserve the shared terminal interpretation plus
  recovered error, row-failure, current-row, last-tracking-number, cost, and
  shipment-count diagnostics. Existing user-visible failed and cancelled
  messages are retained.
- Component tests use the real Angular signal stores and real internal chat
  services, replacing only API and SSE system boundaries. They cover all four
  terminal outcomes and assert the exact persisted failed/cancelled metadata.
- A history-load test reconstructs persisted failed and cancelled system
  artifacts, proving the metadata survives a conversation reload.
- Persistence remains best-effort: synchronous and Observable failures emit
  only a fixed generic warning, keep the already-appended in-memory artifact,
  and clear the UI execution state immediately. Tests prove that credential,
  recipient-row, and tracking canaries are absent from logs.
- The focused chat suite is now **92 passed**, up from **86** before Round 11.

## Round 11 verification evidence

- Focused startup/auth, canonical-status, registry/model/projection,
  hosted-MCP, bundle/daemon/Docker, and artifact matrix:
  `../../.venv/bin/python -m pytest
  tests/control_plane/test_startup.py tests/control_plane/test_config.py
  tests/cli/test_daemon.py tests/test_bundle_entry.py
  tests/test_docker_launch.py tests/api/test_auth_middleware.py
  tests/test_job_status.py tests/registry/test_catalog.py
  tests/registry/test_models.py
  tests/provider_adapters/test_projections.py
  tests/control_plane/test_result_projection.py
  tests/hosted/test_hosted_mcp_registry.py
  tests/registry/test_artifact_drift.py -q` —
  **461 passed, 1 warning in 1.42s**.
- Fresh broad backend regression suite:
  `../../.venv/bin/python -m pytest -q -k "not stream and not sse and not
  progress"` — **3,712 passed, 21 skipped, 105 deselected, 4 warnings in
  47.57s**.
- Focused chat component/service suite — **92 passed**.
- Fresh uncached frontend typecheck matrix passed all **6** configured
  projects and the required shared-state build.
- Fresh uncached frontend lint matrix passed all **6** projects with **0
  errors** and the unchanged **43 warnings**.
- Fresh uncached frontend test matrix passed all **172 tests**: shared state
  **41**, chat **92**, shell **36**, and one each for domain, sidebar, and
  settings.
- Fresh uncached production builds passed all **7** targets.
- `npm run smoke:authenticated-production` rebuilt the production application,
  physically staged all **4** federation remotes, served the shell and API
  through the real FastAPI same-origin boundary, and passed authenticated
  settings, logout/gate restoration, re-authentication, EventSource session
  invalidation/recovery, and cleanup checks with runtime secrets absent.
- Desktop same-origin packaging plus artifact drift passed **11 tests**.
- `../../.venv/bin/python -m ruff check src tests` passed. Targeted Ruff format
  checks passed over all **10** fully formatted Round 11 Python files.
- Prettier passed for the new component-level spec. The two small integrations
  in pre-existing TypeScript files were diff-reviewed without unrelated
  whole-file formatting churn.
- `bash -n` passed for every tracked repository shell script. `node --check`
  passed for every tracked MJS script.
- `cargo fmt --check`, `cargo check --locked`, and `cargo test --locked`
  passed; the Rust target currently has **0 tests**.
- Canonical provider regeneration produced no subsequent worktree change. The
  standalone artifact drift test, aggregate `git diff --check`, and clean-tree
  checks all passed.

## Round 11 self-review and remaining concerns

- Requirement-by-requirement review, aggregate implementation-diff review, and
  targeted searches for registry-local job status lists, append-only failure
  artifacts, sensitive persistence logs, and Auth0-string launch bypasses found
  no remaining Round 11 blocker.
- Non-loopback launch admission intentionally requires the installed API-key
  middleware today. Merely configuring Auth0 metadata remains insufficient;
  supporting JWT-only public listeners requires a future explicit verifier and
  a corresponding reviewed startup branch.
- `paused` is deliberately a backend-only reconnect state rather than a
  provider promise. Its explicit conversion failure prevents accidental schema
  expansion.
- Terminal artifact persistence is intentionally non-blocking and has no
  automatic retry in this round. If persistence fails, the UI is never stuck
  and no diagnostic payload is logged; the artifact remains visible for the
  current in-memory session.
- Broad output retains the existing defusedxml deprecation, unregistered
  `extended` pytest mark, Alembic path-separator, frontend lint, Angular,
  federation, Nx Cloud, and Nx agent-configuration warnings. All required
  completed commands exited zero.
- Tauri's resource check required the exact temporary
  `dist/shipagent-core` directory. It existed only for the locked Cargo checks
  and was removed immediately afterward.
- A complete PyInstaller bundle, Docker image, and packaged Tauri WebView were
  not built. Static packaging contracts, both launcher matrices, every
  production frontend build, and the authenticated production browser smoke
  cover the changed paths.
- No dependency was added or upgraded. No API key, authenticated session value,
  CSRF token, credential canary, customer row, carrier payload, tracking
  canary, or label data is reproduced in this report.
