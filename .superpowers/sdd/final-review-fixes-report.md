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
