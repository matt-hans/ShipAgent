# SDK-free release verification

Recorded 2026-10-07 for [issue #41](https://github.com/matt-hans/ShipAgent/issues/41)
and [draft PR #63](https://github.com/matt-hans/ShipAgent/pull/63).

**Qualification is incomplete.** The clean installation, shared runtime and
Linux frozen sidecar have current evidence. Native macOS Tauri startup and
rendered fallback-font layout remain mandatory open gates. This report does not
certify a desktop release or close issue #41.

## Identity and scope

- Integrated SDK cutover: `aa138ddd4eb8e95c3a30fbffc05327ad80c834d1`,
  [PR #62](https://github.com/matt-hans/ShipAgent/pull/62), issue #40
- Runtime, complete backend and frozen artifact tested here:
  `15422b911a3018ed1625d20dc341598651bc715e`
- Frontend installation/type/lint/tests/build:
  `4242f4b1a34dc3f2b126f49531192d6487eb2230`; frontend, package manifests and
  lockfiles are byte-identical through the runtime-tested commit
- Application versions: Python project, Cargo and Tauri `0.1.0`; the private
  Angular workspace package remains `0.0.0`. No version bump or tag was made
- Later roadmap/evidence-only changes do not change the tested executable
  inputs. PR review must verify that identity; a subsequent runtime, dependency,
  frontend or packaging change requires the affected gates to run again

The published [parent specification](../superpowers/specs/2026-10-01-provider-neutral-runtime-convergence.md)
and issue #30 are unchanged. The separate connector roadmap and deferred
issue #51 are not completed by this work. No live model, carrier, commerce,
shipment purchase, release publication or deployment was exercised.

## Environment and clean installation

Tested platform: Linux x86_64, glibc 2.41, Python 3.12.14. Tool versions:
uv 0.12.19, PyInstaller 6.19.0, hooks-contrib 2026.1, Node 24.19.0,
npm 11.9.0, Nx 22.6.1, Angular 21.2.5, Native Federation 21.2.2,
Vitest 4.1.1, pytest 9.0.2 and Ruff 0.14.14.

`uv sync --frozen --extra dev --link-mode copy --no-python-downloads` used an
already installed Python 3.12.14, an absent virtual environment and an empty
isolated cache. All 129 installed distributions match the locked runtime/dev
versions. Module discovery and distribution lookup both establish that
`claude_agent_sdk` / `claude-agent-sdk` are absent, without an import mock.
Installed dependency files have no symlinks to another environment. The project
uses its normal editable installation; this is not a non-editable wheel test.
PEP 517 build requirements retain their declared constraints, so this does not
claim permanently bit-reproducible build-tool resolution.

The clean interpreter exercised the actual API/SSE/history, persisted model
settings, CLI workflow, source-sidecar and development entrypoints. Provider
HTTP responses and shipping gateways were synthetic; shared orchestration,
policy, persistence and public entrypoints were real. The fast regression
fixture in `test_sdk_free_runtime.py` still uses an SDK-free dependency view;
that fixture alone is not the clean-install evidence.

A separate empty npm cache and absent `node_modules` were populated by `npm ci`:
1,728 packages, 354,664,000 bytes of cached download payload. No Nx Cloud token,
`NX_NO_CLOUD` or Codex override was used for the frontend gates.

## Acceptance reconciliation

| Required behavior | Current acceptance boundary |
| --- | --- |
| Three providers, streamed text/tool IDs/arguments/continuation/errors | `test_tool_workflow_acceptance.py`, `test_anthropic_conversation_acceptance.py`, the three `conversation_runtime/test_*_provider.py` suites |
| Batch preview, explicit confirmation, single execution, uncertainty/retry safety, progress/write-back | `test_batch_confirmation_acceptance.py` and shipping/workflow regressions |
| Interactive shipping, rates, transit/tracking, pickup/document preparation and confirmation | `test_auxiliary_workflow_acceptance.py` and deterministic workflow/gateway regressions |
| SQL/raw-carrier denials, mode isolation and neutral audit | `test_conversation_policy_acceptance.py`, runtime policy and batch/lifecycle audit assertions |
| Imported-row, credential, label/carrier and origin-aware privacy | `test_conversation_privacy_acceptance.py` and `test_conversation_privacy_boundaries.py` |
| Persisted history, interruption, accepted side effects, safe provider switching and private continuation | `test_conversation_lifecycle_acceptance.py`, handler/resume/session suites |
| SDK-free API/CLI and architecture/artifact drift | Fresh interpreter workflows, `test_sdk_free_runtime.py`, `test_claude_sdk_optional.py`, `test_artifact_drift.py` |
| Clean frozen backend, actual local imports and isolation | Unmodified Linux binary, package inventory and real HTTP/stdio smoke described below |
| Native desktop wrapper and rendered typography | **Open; no native startup or rendered layout pass claimed** |

The shared conversation/three-adapter matrix passed **384 tests** on
`15422b9` (24.3 seconds, 420.2 MiB aggregate RSS, one CPU). The complete backend
passed **4,986 tests, 29 skipped, 16 warnings** on the same commit (163.44 seconds
including runner teardown, 713.14 MiB aggregate RSS, two CPUs). There were no
surviving owned test processes. Local DataSource startup was unpatched: the
historical test harness's DuckDB extension-install replacement was removed.

The 29 skips are accounted for: one unavailable non-loopback interface, one
unconfigured PostgreSQL migration target, twelve inapplicable public-tool
field-family cases, eight live Shopify checks, four opt-in live UPS checks and
three absent legacy XML/fixed-width sample files. They are not reported as
passes. The deterministic parent acceptance matrix has no skipped scenario.
Inherited warnings concern defusedxml, an unregistered `extended` marker,
WebSocket deprecations and Alembic path separators.

Ruff and whitespace checks passed. Provider-artifact drift and production
SDK-absence architecture checks passed and are included in the full suite.
All available ordinary Nx typecheck/lint targets and **160 frontend tests**
passed. All **seven production build targets** passed, all four remotes were
staged and **1,205 artifact hashes** were independently verified. The first
build exceeded a 2 GiB process-tree limit and is explicitly a failed attempt;
the successful authorized retry took 120.35 seconds and 1,840.75 MiB with two
CPUs and one Angular worker. No source change was used to hide that cap failure.

## Actual frozen artifact

PyInstaller built the production spec from the clean environment at `15422b9`:
37.40 seconds, 218.66 MiB aggregate RSS, two CPUs, no downloads or test hooks.
The Linux one-folder artifact contains 852 files / 151,150,359 bytes and 5,114
archive entries. Inspection found no SDK code/metadata, no test-harness module,
no symlink to external dependencies, and all three provider adapters.

- Binary SHA-256:
  `f827f5b7cda0d9adf86648d7a6f9002986955767eef0da7d8d03b788cabdc642`
- Retained archive: `issue41-sidecar-linux-x86_64-15422b9.tar.gz`, 67,285,496 bytes
- Archive SHA-256:
  `a88d7a8aac9a428a91755924d6d22e24ddb17f0535e9338401070505509b5dc8`
- Full frontend manifest SHA-256:
  `652606999f16e2d83d944e3dc48e29176be624916e5680302568818a43e2dcd7`

All seven complete UPS YAMLs are present, including real TimeInTransit. Their
registry preserves the previous 24 interpreted route/parameter contracts and
adds transit as operation 25. All 593 packaged shell/staged-remote files match
the production build exactly. Full file/module manifests and failed-attempt
logs are retained with the verification artifacts; no binary was published.

With **all 948 bundle files/directories made unwritable**, the unchanged binary
passed CLI version/help, dynamic-port startup, health/readiness/settings, shell
HTML, all four remote manifests/exposed chunks, conversation persistence, and
real two-row CSV and Excel multipart uploads through its actual bundled
DataSource MCP child. It used temporary home/data/database, no provider keys,
no `PYTHONPATH` injection and no transport/startup mock. The sidecar and its
owned MCP child both stopped. Modes were restored and all hashes independently
reverified. Independent probes also rejected sibling data files, `.env`,
symlink/traversal escapes and symlink-overwrite uploads without replacing the
active source. This validates HTTP/assets and local workflows, **not pixels**.

## Reproduced fixes

- Local DataSource startup no longer eagerly installs PostgreSQL/MySQL
  extensions. Explicit remote database connections still require DuckDB's
  optional extension to be installed or downloadable
- UPS contracts come from the pinned read-only package, with fail-closed
  completeness checks. No installation-relative cache or placeholder transit
  contract is generated
- Uploaded files now use `get_data_dir()/uploads`; source and frozen launchers
  pass the same resolved directory to the MCP child. The rest of the data
  directory is not added to allowed roots. Existing files are not migrated or
  deleted, and existing source-path/sensitive-name guards remain
- Direct EDI imports now apply that same guard before reading, logging or
  touching context. Valid EDI parsing and source metadata remain covered
- Bundle smoke uses temporary HOME **and CWD**, a clean environment and the real
  upload route; it waits for its exact owned process on failure and success
- Release testing no longer requires an undeclared timeout plugin or excludes
  streaming acceptance. The existing release job uses the shared
  build/link/freeze/smoke path. Its native architecture labels are now
  `macos-15` (arm64) and `macos-15-intel` (Intel), verified against
  [GitHub's runner table](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
  on 2026-10-07. No release workflow was dispatched

## Residual qualification and stopping conditions

1. Build the configured native macOS `.app` from the reviewed candidate, start
   its own bundled sidecar, verify the real window and normal owned-process
   shutdown. The Linux sidecar is not a substitute for the Tauri wrapper
2. Render the shell, populated chat/composer and shipment settings with local
   fallback fonts; inspect legibility, wrapping, truncation, horizontal overflow
   and control layout. The available cloud browser route was blocked before
   rendering, so no screenshot or visual assertion passed
3. Other native targets, DMG, signing/notarization and auto-update are
   unverified. Windows/Linux desktop parity is not configured by this PR
4. Frozen MCP shutdown emits a closed-stdio `ValueError` after successful work.
   A separate raw JSON-RPC probe completed CSV import, then stdin EOF produced
   exit 0 and no survivor. The symptom matches
   [upstream MCP issue #1933](https://github.com/modelcontextprotocol/python-sdk/issues/1933);
   that causal attribution is an inference. The diagnostic is retained rather
   than suppressed. API SIGTERM still completes lifespan cleanup and returns
   the expected signal termination status
5. PyInstaller retains warnings for optional pycparser tables, unused alternate
   database drivers and Linux-unavailable Windows `user32`; tested SQLite,
   local import and provider-module paths work. Live carrier/model/database
   connectivity is outside this deterministic gate

Issue #41 stays open until mandatory native startup and visual evidence exist.
PR review and hosted Docker checks do not convert those gaps into passes.

## Reproduction outline

Use an isolated checkout with no `.env`, no credentials, temporary HOME/data/DB,
and no live-provider integration opt-ins. Keep local fixture work separate from
real shipments. Select the recorded interpreter and locked metadata:

```bash
UV_CACHE_DIR=/path/to/empty/cache uv sync --frozen --extra dev --link-mode copy --no-python-downloads
.venv/bin/python -m pytest -ra
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m pytest tests/registry/test_artifact_drift.py
cd shipagent-frontend
npm ci
npm exec -- nx run-many -t typecheck lint --all --parallel=1 --skip-nx-cache
npm exec -- nx run-many -t test --all --parallel=1 --skip-nx-cache
npm exec -- nx run-many -t build --all --configuration=production --parallel=1 --skip-nx-cache
./scripts/link-remotes.sh
cd ..
.venv/bin/python -m PyInstaller shipagent-core.spec --clean --noconfirm
```

`./scripts/bundle_backend.sh` provides the normal build/link/freeze/upload-smoke
pipeline. A native Tauri build and actual GUI validation are additional steps,
not implied by these commands. Recheck module/distribution absence and inspect
the actual binary archive; a source scan or an old pass report is insufficient.
