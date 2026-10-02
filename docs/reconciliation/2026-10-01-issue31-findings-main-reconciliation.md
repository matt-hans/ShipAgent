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
| Startup security gate | Findings' stricter `validate_startup_security` (`src/control_plane/startup.py`) is the only gate; main's `app.py` calls it once. | Retained; no duplicate gate. |
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

- Stream/SSE tests in `tests/api/test_progress.py` hang (see Validation).
  Pre-existing; not addressed in this ticket.
- Frontend checks: see Validation.
- Eight pre-existing main files would be reformatted by `ruff format`
  (`app.py`, `jwt_verifier.py`, `provider_clients.py`, `service.py`,
  `redis_keys.py`, `request_controls.py`, `test_redis_keys.py`,
  `scripts/check_provider_oauth_metadata.py`); left as-is to keep the merge
  diff attributable.
- Four pre-existing ruff findings under `scripts/` (`batch_void.py`,
  `benchmark_regression_check.py`, `test_pipeline.py`), outside the documented
  `src/ tests/` lint scope.

## Seam defects fixed in this phase

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
| The 1 failure | Classified pre-existing/environmental: `is_pid_alive` logic is unchanged by the merge (formatting plus an unrelated host-validation line); the test fails whenever the pytest command line contains `shipagent` (this checkout path does). |
| PostgreSQL 14 disposable (`initdb` in a job temp dir, port 55432) | `test_migrations_postgres.py` 3 passed after fix; `alembic upgrade head`, `downgrade base`, `upgrade head` ok; head `20260723_0003`; 4 tables plus `relay_devices` in `shipagent_private`. Docker daemon was not running; local PG binaries used. |
| Frontend `nx typecheck` | Pass with `--parallel=1`. First parallel run failed with TS6305 (project-reference output not yet built, cold cache race). |
| Frontend `nx lint` / `test` / `build --configuration=production` | Pass; tests 41+36+1+1+1+105 passed. |
| `ruff check src tests alembic` | Clean. |
| Backend type checking | None configured (no mypy/pyright in `pyproject.toml` or CI); `compileall` of `src tests alembic scripts` ok. |
| Artifact drift | `tests/registry/test_artifact_drift.py` pass. |


## Rollback

The branch is unpushed. `git reset --hard ad86359` restores the pre-merge
findings tip (requires authorization). Or revert merge `9b993e0` with
`git revert -m 1`.
