# Issue #31 reconciliation report: findings branch + main

## Purpose

Records how the preserved findings branch (`ad86359`) and `origin/main`
(`a4a4bd135b108e79d030c99b62cc3f53e4a96503`) were merged on
`codex/issue31-reconcile-main`, and which behavior was retained, deferred or
left unresolved. It is evidence for review of #31 (parent #30) and
follow-ups #42-#45. It is **not** a runtime-readiness statement; no shipping
mutations or live carrier calls were made.

Merge commit: `9b993e0` (parents `ad86359`, `a4a4bd1`). No history rewritten.
Reproduce the diff: `git diff origin/main...HEAD`.

Scope: this is a **reviewable integration candidate** for #31, not the #32
validated baseline. Baseline blockers: #42-#45 (implemented here, dispositions
below), #46, #47 and #48 (open, unresolved).

## Preservation and publication of the findings branch

The preserved findings commits **were published** in phase 1 (an earlier
review note saying they were not published was wrong).

| Ref | SHA | Evidence |
|---|---|---|
| `origin/codex/provider-contracts-control-plane-foundation-findings` before | `bde0e0b79fe04e4439c2b71bcb0d075668ba494f` | ancestor of local tip |
| same ref after phase-1 plain push (fast-forward, no force) | `ad86359a31e5fbbd5e89e0648f77d59b000fdab4` | `git ls-remote origin refs/heads/codex/provider-contracts-control-plane-foundation-findings` re-run at delivery returns this SHA |
| local findings worktree tip | `ad86359a31e5fbbd5e89e0648f77d59b000fdab4` | equal to remote |

Local backup refs (`refs/backup/issue31/*`) and the bundle are local-only
recovery aids and were not pushed.

## Scope decisions by follow-up

| Issue | Scope | Outcome |
|---|---|---|
| #42 | alembic env/0001, control-plane config/db/models | Both sides kept: findings `control_plane_schema` + URL normalization; main sqlite-aware schema, `RelayDevice`, `auth0_provider_clients`. 0001 not edited for relay tables; 0002/0003 forward-only. Verified on SQLite and a disposable PostgreSQL 14. |
| #43 | registry public tools, hosted MCP server, tests, generated artifacts | Merged by decision (see below). Artifacts regenerated, drift test passes. |
| #44 | `uv.lock` | Re-resolved with `uv lock` from merged `pyproject.toml`; `uv lock --check` ok. |
| #45 | Overlap and duplicate assessment | This document. |

## #45 duplicate / superseded assessment

Method: files changed by both sides since merge-base `ab77b2f` (19 files) and
semantic comparison of main's relay hardening against findings' privacy and
diagnostic hardening. No patch-identical duplicates exist (all 76 findings
commits unmatched in main).

### Non-conflicting overlapping files (reviewed, both sides present)

| File | Findings | Main | Result |
|---|---|---|---|
| `.env.example` | `SHIPAGENT_API_KEY` generation guidance, CORS origins | `SHIPAGENT_AUTH0_*` settings | Both present and non-contradictory. |
| `README.md` | Docker API key, ports 8080/4200, dev proxy | MIT license badge and text | Both present. |
| `alembic.ini` | `sqlalchemy.url = CONFIGURE_ME` (fail closed) | trailing-blank-line removal | Findings value kept; tests set URL explicitly. |

### Semantic overlap

| Area | Finding | Decision |
|---|---|---|
| Startup security gate | Main's `validate_startup_security` checked only `fake_local` loopback restrictions. Findings added a non-loopback `SHIPAGENT_API_KEY` requirement into the same function, which also ran for the hosted Auth0 app (`app.py`) and conflated desktop API-key auth with ADR 0001 Auth0 identity. | **Fixed in phase 6:** `validate_startup_security` is auth-mode only again; the API-key rule is `validate_desktop_listener_security`, called by `validated_listener_host` (daemon, bundle entry) and the desktop API lifespan. Tests in `tests/control_plane/test_startup.py`. |
| Redaction | `request_controls._SENSITIVE_ARGUMENT_KEYS` redacts values before hashing for loop detection; `registry/privacy.py` validates provider-visible *schemas* at registration; `result_projection.project_result` filters runtime output. Three layers, three purposes. | Retained; not duplicates. Unifying the key vocabulary is deferred (below). |
| Result projection | Main's tests asserted `target_id`/`message`; findings' privacy rules forbid them. | Findings' rule wins; status projected by `project_status_for_provider`. Main's tests updated. |
| `BoundRegistryTool.run` | Both added gates. | Single ordered pipeline (auth, scope, schema validation, request controls, handler, projection, fail-closed). |
| Audit service / diagnostics | Findings only (`audit/service.py`, `errors/terminal_diagnostics.py`); main's relay carries only `audit_correlation_id`. | No overlap; correlation ids use canonical `sa_correlation_*`. |
| Frontend (56 files), `src/api`, `src/services`, `src-tauri` | Changed on one side only (findings), except relay client/key service (main only). | No overlap. |

### Retained

- All findings hardening (identifier families, privacy validators, terminal
  diagnostics, audit service, startup gate, API-key/CORS/Docker changes).
- All main relay work (Auth0 plane, relay registry/invocations/protocol,
  request controls, device keys, forward-only relay migrations, MIT license).

### Deferred (with reasons)

Phase 6 follow-up issues: #46 (dormant tool contracts vs ADR 0003/0008, `BoundRegistryTool.run` confirming-tool guard) and #47 (ADR 0007 vs opaque-only contracts, sensitive-key and capability vocabularies). Both block exporting any tool except `get_shipagent_status`; neither affects runtime today because only the status handler is registered.

1. **Export of the 7 non-status public tools.** Only `get_shipagent_status` is
   `provider_export_enabled`. Reason: no relay handlers, reviewed per-provider
   profiles, or OAuth scopes (`address:validate`, `shipments:rate`,
   `shipments:execute` absent from `SUPPORTED_SCOPES`); ADR 0003.
2. **Capability vocabulary.** Status `capabilities` enum mixes findings' codes
   with relay tool names (`get_shipagent_status`, `rate_shipment`). Reason: the
   relay publishes tool names today; a decision on one vocabulary needs the
   owner.
3. **Shared sensitive-key vocabulary** between `request_controls` and
   `registry/privacy`. Reason: different layers; unification is a refactor
   outside reconciliation.
4. **License text.** `NOTICE` and `CONTRIBUTING.md` still say Apache 2.0 while
   `LICENSE`/README (main #29) say MIT. Present on `origin/main`; legal owner
   decision, not edited here. (The main checkout has uncommitted
   `CONTRIBUTING.md` edits that were deliberately not touched.)
5. **Claude Agent SDK removal** is #40, untouched.

### Unresolved / known

- Stream tests `TestProgressStream::test_stream_endpoint_exists` and
  `::test_stream_returns_event_format` hang. **Confirmed pre-existing:** both
  time out at 60 s on a pristine detached `a4a4bd1` worktree as well as on the
  candidate. Not addressed in this ticket (root cause not investigated).
- Frontend checks: see Validation.
- Eight pre-existing main files would be reformatted by `ruff format`
  (`app.py`, `jwt_verifier.py`, `provider_clients.py`, `service.py`,
  `redis_keys.py`, `request_controls.py`, `test_redis_keys.py`,
  `scripts/check_provider_oauth_metadata.py`); left as-is to keep the merge
  diff attributable.
- Four pre-existing ruff findings under `scripts/` (`batch_void.py`,
  `benchmark_regression_check.py`, `test_pipeline.py`), outside the documented
  `src/ tests/` lint scope.

## Frontend / Tauri duplicate and superseded assessment

Method: `git diff --stat ab77b2f..ad86359 -- shipagent-frontend src-tauri`
(findings side) against `git diff --stat ab77b2f..origin/main` for the same
paths (main side), plus a grep for `relay|auth0` under
`shipagent-frontend/apps`, `shipagent-frontend/libs` and `src-tauri/src`.

Result: main changed **zero** frontend or `src-tauri` files since the
merge-base, and nothing in those trees references relay or Auth0. There is no
file-level overlap, so there is nothing superseded or duplicated by main; all
56 findings-side files were retained unchanged by the merge. Main's only
desktop-adjacent change is Python (`src/services/desktop_relay_client.py`,
`src/services/relay_key_service.py`), which no frontend code consumes yet.

| Area (findings-only files) | Retained because |
|---|---|
| Browser session / API transport: `libs/shared/api/src/browser-session-request.ts`, `browser-session-transport.service.ts`, `browser-session.state.ts`, `api.interceptors.ts`, `api.service.ts`; shell `api-key-gate/`, `desktop-handoff.ts`, `shell-startup.ts`, `bootstrap.ts`, `app.component.ts` | Pair with backend `src/api/browser_session.py`, `routes/auth_session.py`, `middleware/auth.py` (also findings-only). Dropping one half would break the session handshake. |
| Progress/SSE: `libs/shared/sse/src/sse.service.ts`, `chat-remote/src/services/job-progress-sse.service.ts`, `session-aware-sse.spec.ts`, `libs/shared/types/src/job.types.ts` | Pair with `src/services/job_progress_projection.py` and `routes/progress.py` (findings-only). Main did not touch progress. |
| Completion UI: `chat-remote/.../completion-artifact.component.ts`, `label-preview-modal.component.ts`, `chat-container.component.ts`, `job-completion-metadata.ts` | Findings-only UI hardening with specs; no main counterpart. |
| Tauri port/detection: `libs/shared/tauri/src/port-resolver.ts`, `tauri-detection.service.ts`; `src-tauri/src/main.rs`, `tauri.conf.json`, `capabilities/default.json`, `Cargo.toml`/`Cargo.lock` | Findings-only; main.rs hunk is a custom-protocol bootstrap plus rustfmt churn. |
| Smoke/validate scripts: `shipagent-frontend/scripts/smoke-authenticated-production.mjs`, `smoke-development-proxy.mjs`, `validate-remote-entry.mjs`, `link-remotes.sh` | Findings-only tooling; not executed in this phase (see limits). |

Deferred / not verified (reasons):

- **Tauri was not built or run.** `cargo tauri build` and desktop startup were
  not executed; `src-tauri` is reviewed by diff only. Desktop packaging and
  startup validation belongs to #32 acceptance.
- Frontend dependencies were installed with `npm ci --ignore-scripts` (a plain
  `npm ci` stalled in lifecycle scripts), so postinstall-dependent behavior is
  unverified. The three smoke scripts above were not run.
- No claim is made that the 56 files were line-by-line reviewed; evidence is
  the typecheck/lint/test/build results under Validation plus the pairing
  analysis above.

## Review coverage and limits

Three review rounds ran as separate parallel Sonnet 5.5 agents (Standards and
Spec axes), recorded outside the repo in `REVIEW-phase5*.md` and
`REVIEW-phase7.md`:

- Phase 5 (HEAD `559c1d3`): 11 standards rows (S1-S11) and 15 spec rows
  (P1-P4, B1-B3, C1-C7, V1). Phase 6 dispositioned all 26:
  3 defects fixed with red-first tests, 2 issues filed (#46, #47), the rest
  false positives, judgement calls, or deliberately not actioned.
- Phase 7 (HEAD `f9b9ec8`): 0 hard standards violations, about 10 judgement
  items, 4 spec gaps (nothing published, no PR, #45 validation incomplete,
  frontend/Tauri assessment thin) and one residual listener-gate gap.

**Limits.** The review is a sample, not a full audit. The standards agent
sampled by grep/stat rather than reading all 155 changed files; the spec agent
ran no tests; the orchestrator did not re-verify every cited line. The review
agents are not independent evidence of correctness for the 83 preserved
hardening commits. The `.claude/rules/*` files exist only untracked in the
main checkout and were not imposed (the docstring finding stays a false
positive).

**Inherited listener-gate gap (#48).** `src/api/main.py` `lifespan` calls
`validate_desktop_listener_security(ControlPlaneSettings().bind_host)`, which
reads `SHIPAGENT_BIND_HOST`, not the host uvicorn binds, so
`uvicorn src.api.main:app --host 0.0.0.0` skips the non-loopback API-key gate.
Launchers (`daemon`, `bundle_entry`) pass the real host and are covered. Not
introduced by the merge; tracked as **#48**, a blocker for #32.

## Findings-branch working reports (removed from PR #49)

`.superpowers/sdd/final-review-fixes-report.md` and
`.superpowers/sdd/final-review-round-14-findings.md` were force-added on the
findings branch despite `.gitignore` listing `.superpowers/*` (`a4a4bd1` has
none). PR review (LOOP-PR49-REVIEW1, S1) flagged them as agent transcripts that
add review noise, so they were `git rm`-ed from this branch. The contents are
**not lost**: both files, byte-identical (sha256/sha1 verified against the
removed blobs), plus the rest of `.superpowers/sdd/`, are in the out-of-tree
archive `~/ShipAgent-issue31-reconciliation/artifacts/findings-worktree-ignored-superpowers-sdd.tgz`
(listed in that directory's `SHA256SUMS`). They remain recoverable from earlier
commits of this branch (`git show 9ac6c61:.superpowers/sdd/<file>`) and from
`artifacts/issue31-all-refs.bundle`. A regex scan for key/token/private-key
patterns over `.superpowers/` found no secrets. They were historical reports,
not proof of merged correctness.

## Launcher, compose, and listener behaviour changes

These ride along with the preserved hardening commits and were not described in
issue #31 itself (LOOP-PR49-REVIEW1 S2/ST6):

- `docker-compose.yml`: `SHIPAGENT_API_KEY` is now **required** (`:?`); compose
  fails fast unless a generated 32+ character key is set. Compose also loads
  `docker.env` after `.env`.
- `docker.env` (new): `SHIPAGENT_AUTH_MODE=auth0` and
  `SHIPAGENT_BIND_HOST=0.0.0.0` for the container only. The `auth0` value is
  used to step outside the `fake_local` loopback-only gate in
  `validate_startup_security`; it does not configure Auth0 (that function only
  checks `fake_local`). The real protection for this listener is the required
  API key plus `validate_desktop_listener_security`.
- `Dockerfile` `CMD`: `uvicorn src.api.main:app --host 0.0.0.0` was replaced by
  `python -m src.bundle_entry serve --host 0.0.0.0`, so the container goes
  through the same listener gate as the desktop launchers (see #48 for the
  direct-`uvicorn` bypass that remains).
- `.github/workflows/docker.yml` (**not yet changed; required follow-up**): the
  smoke job runs `docker run` without `SHIPAGENT_API_KEY`, so the container now
  exits on `0.0.0.0` with `RuntimeError: Non-loopback listeners require
  SHIPAGENT_API_KEY authentication` (CI run 36958568974, after the lockfile
  fix). The smoke job must pass a per-run generated, masked key
  (`openssl rand -hex 32`); the gate must not be weakened and no key may be
  committed. Pushing workflow files needs a token with `workflow` scope.
- `scripts/start-backend.sh`: honours `SHIPAGENT_ENV_FILE` (default `.env`) and
  `SHIPAGENT_PYTHON` (default `.venv/bin/python`).
- `scripts/bundle_backend.sh`: runs `shipagent-frontend/scripts/link-remotes.sh`
  after the production frontend build.
- `shipagent-frontend/apps/shell/proxy.conf.json`: dev proxy target `8000` to
  `8080`, matching `SHIPAGENT_PORT`'s default.
- `src-tauri`: `withGlobalTauri: true` and `"local": true` capability; the
  `connect-src http://127.0.0.1:*` CSP is unchanged (needed because the
  sidecar port is OS-assigned). Not exercised by a Tauri build in this PR.
- Startup recovery and orphan-reaper logs carry a bounded structured message
  plus `job_id` (only when it is a canonical UUID; otherwise `unknown`) and
  never include exception text.

Rollback: revert the PR commit(s); none of these change persisted data.

## Alembic `search_path` check (mixed-case schema)

Question raised in review: `alembic/env.py` passes the unquoted schema as
asyncpg `server_settings.search_path`, whereas `src/control_plane/db.py` now
quotes it. Verified on a disposable PostgreSQL 14 (local `initdb`, port
55434, removed afterwards) with `SHIPAGENT_CONTROL_PLANE_SCHEMA=MixedCase`:
online `alembic upgrade head` created `alembic_version`, `cloud_accounts`,
`provider_connections`, `audit_events`, `relay_devices` all in schema
`"MixedCase"` (none in a folded lowercase schema), head `20260723_0003`;
`downgrade base` also ran. **Not a real gap:** the connect-time value only
seeds a harmless lowercase path, and `_run` immediately issues the quoted
`SET search_path TO "MixedCase"` before any migration or version-table access.
No code change. (The `db.py` quoting remains necessary because runtime
sessions have no such follow-up `SET`.)

## Defects fixed in phase 6 (review findings, each reproduced first)

- Hosted Auth0 startup required the desktop API key on non-loopback bind (above).
- `alembic/env.py`: ambient `SHIPAGENT_DATABASE_URL`/`DATABASE_URL` overrode an explicit `sqlalchemy.url`. Now an explicit non-placeholder URL wins; the `CONFIGURE_ME` placeholder or empty value falls back to the environment (the #42 fail-closed and env-driven cases both preserved).
- `src/control_plane/db.py`: asyncpg `server_settings` `search_path` was unquoted, so a mixed-case schema folded to lowercase (the pre-merge listener quoted it). Now quoted; verified on a disposable PG 14 (`SHOW search_path` returns `"MixedCase"`).

## Seam defects fixed in phase 4

- `tests/control_plane/test_migrations_postgres.py` asserted revision
  `20260609_0001` and omitted `relay_devices`; it failed against PostgreSQL once
  relay migrations 0002/0003 existed. Now asserts the script head and the
  relay table (red then green on disposable PG).
- `docs/components/shipagent-workflow-tool-registry.md` listed stale artifact
  names and did not describe the `BoundRegistryTool.run` order or export gating.

## Validation

See `HANDOFF-phase4.md` (outside the repo, in
`~/ShipAgent-issue31-reconciliation/`) for command output and failure
classification; summary below.

| Check | Result |
|---|---|
| Full `pytest tests` (attempted, bounded by 240 s faulthandler) | **Incomplete.** Run 1 hung at `tests/api/test_progress.py::TestProgressStream::test_stream_endpoint_exists`; run 2 (that case deselected) hung at `tests/api/test_progress.py::TestProgressStream::test_stream_returns_event_format`. Both killed; neither reached a result. 4158 tests collect without errors. |
| Reduced `pytest -k "not stream and not sse and not progress"` | 4019 passed, 21 skipped, 117 deselected, **1 failed** (`tests/cli/test_daemon.py::TestPidFile::test_is_pid_alive_non_daemon_process`). Does not substitute for the full suite. |
| The 1 failure | **Confirmed pre-existing:** `test_is_pid_alive_non_daemon_process` fails identically on pristine `a4a4bd1` (1 failed) and the candidate; cause is path-dependent (pytest command line contains `shipagent`). |
| PostgreSQL 14 disposable (`initdb` in a job temp dir, port 55432) | `test_migrations_postgres.py` 3 passed after fix; `alembic upgrade head`, `downgrade base`, `upgrade head` ok; head `20260723_0003`; 4 tables plus `relay_devices` in `shipagent_private`. Docker daemon was not running; local PG binaries used. |
| Frontend `nx typecheck` | Pass with `--parallel=1`. First parallel run failed with TS6305 (project-reference output not yet built, cold cache race). |
| Frontend `nx lint` / `test` / `build --configuration=production` | Pass; tests 41+36+1+1+1+105 passed. |
| `ruff check src tests alembic` | Clean. |
| Backend type checking | None configured (no mypy/pyright in `pyproject.toml` or CI); `compileall` of `src tests alembic scripts` ok. |
| Phase 6 bounded repros (60 s each, pristine `a4a4bd1` detached worktree vs candidate) | Both hung stream tests: TIMEOUT on both trees. Daemon test: fails on both trees. |
| Phase 6 remaining stream/sse/progress cases (everything matching the reduced-run `-k` exclusion except the two hung tests) | 114 passed, 4048 deselected, 7.55 s. (Phase 4 counted 117 deselected; 114 + 2 hung = 116; the 1-case difference is unexplained and not chased.) |
| Phase 6 focused | `tests/control_plane` + drift + daemon (minus pid test) + bundle entry + auth middleware: 428 passed, 1 skipped. PG 14: `test_migrations_postgres.py` 3 passed; mixed-case `search_path` verified. `ruff check src tests alembic` clean. |
| Artifact drift | `tests/registry/test_artifact_drift.py` pass. |


## Rollback

Do not rewrite history once the branch is published. Revert through a PR:
`git revert -m 1 9b993e0` (merge) and/or the phase-6 fix commits (`24b543a`,
`5e21a0c`, `00415a4`). The pre-merge findings tip `ad86359` stays on
`origin/codex/provider-contracts-control-plane-foundation-findings`.
