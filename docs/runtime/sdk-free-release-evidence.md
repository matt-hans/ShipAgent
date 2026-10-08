# SDK-free release verification

## Current qualification at 04a4bba

Updated 2026-10-08 for [issue #41](https://github.com/matt-hans/ShipAgent/issues/41)
and the unchanged [parent specification](../superpowers/specs/2026-10-01-provider-neutral-runtime-convergence.md).

**Cloud/Linux qualification passes; native macOS acceptance remains open.**
The current executable candidate is
`04a4bbaee3b00ed57115367477a7578216c06a21`, tree
`1fa25ce299522665c4bffbaf642fdc0e0f4e1897`. It includes the SDK cutover in
[PR #62](https://github.com/matt-hans/ShipAgent/pull/62), packaging repairs in
[PR #63](https://github.com/matt-hans/ShipAgent/pull/63), the postal-field layout
repair in [PR #72](https://github.com/matt-hans/ShipAgent/pull/72), and active-guide
reconciliation in [PR #73](https://github.com/matt-hans/ShipAgent/pull/73).

Anthropic, OpenAI and Gemini remain supported through the same ShipAgent-owned
runtime. Removing the Claude Agent SDK does not remove Anthropic support.
Local CSV/Excel operation still requires no Redis, PostgreSQL, Auth0 or hosted
grant service. The separate connector roadmap, live providers/carriers,
marketplace publication and deployment are not qualified by this work.

### Evidence identities and test accounting

All 1,187 original candidate source files were inventoried and independently
matched against the exact Git blobs. Source, dependency and artifact evidence
was retained before any later documentation reconciliation. Documentation-only
changes do not silently become newly tested executable source.

| Gate | Evidence and scope |
| --- | --- |
| Fresh shared acceptance and protocol checks | **752 passed, zero skips, one warning** on `04a4bba`; shared workflows, adapters, privacy/lifecycle, API/CLI entrypoints, packaging-source checks and provider-artifact drift. Pytest 68.63 s; guarded wall 74.623 s, peak 584.105 MiB |
| Fresh backend lint | Ruff passed on `04a4bba` |
| Fresh frontend checks | Ordinary Nx typecheck/lint and **199 tests across six projects** passed on `04a4bba`; guarded wall 57.807 s, peak 1,255.930 MiB |
| Fresh production frontend | **Seven individually guarded targets** passed and all four remotes were staged; maximum per-target peak 1,732.754 MiB |
| Fresh frozen backend | Production PyInstaller spec passed on `04a4bba`; 35.199 s, peak 237.098 MiB; actual archive inspected without SDK/test instrumentation |
| Actual frozen runtime and rendered UI | Read-only-install local workflows and six settled Chromium layouts passed; 17.468 s, peak 1,152.539 MiB |
| Committed layout regression | All **14 states** passed on the final production assets; 7.852 s, peak 804.184 MiB; default/minimum window, keyboard/caret, validation/retry, scrolling and reopen |
| Prior equivalent-input full backend | **5,251 passed, 29 skipped, 19 warnings** at `9a5021d69ec72f40741626227815e4ea39296d38`; its tree equals `1616278`. Backend source/tests/dependency and packaging inputs remain unchanged through `04a4bba`. This is **not a fresh final-commit full-suite rerun** |
| Additional prior smoke/docs evidence | The 119-test `1616278` integration smoke and PR #73's 341 guarded checks are separate records; neither is added to the 752 fresh checks |
| Native macOS build and static inspection | **Passed on ARM64**: native locked install, type/lint, a separate **199-test** frontend run, seven builds, native freeze and app-only Tauri packaging. Native manifests, linkage and SDK absence checked; this is not a runtime pass |
| Native packaged sidecar runtime | **Passed**: exact app-bundled binary, two owned local starts, CLI/API/assets, synthetic CSV/XLSX import/write-back, export/persistence, MCP EOF and planned standalone SIGTERM; 8.093 s, peak 541.688 MiB; no app/WebView launch |
| Native macOS wrapper | **Pending**: actual final ARM64 `.app`, its own bundled sidecar, real window/local workflows and normal owned-process shutdown |

All successful guarded stages ended with verified cleanup and zero owned
survivors. The 29 inherited full-suite skips remain accounted for: one
non-loopback LAN-listener case outside the local-only harness, one unconfigured
PostgreSQL migration target, 12 inapplicable public-tool field-family cases,
eight unconfigured live Shopify checks, four opt-in live UPS checks and three
absent legacy XML/fixed-width fixtures. None is reported as a pass.

### Final installation and build environment

Linux x86_64; Python 3.12.14, uv 0.12.19, PyInstaller 6.19.0,
hooks-contrib 2026.1, Node 24.19.0, npm 11.9.0, Nx 22.6.1, Angular core 21.2.5,
Angular CLI/build 21.2.3, Native Federation 21.2.2, Vitest 4.1.1,
pytest 9.0.2, Ruff 0.14.14 and Chromium 154.0.8037.57.

Fresh virtualenv and frontend dependency directories were populated from
unchanged locked inputs and previously validated download caches. **These final
runs do not claim empty download caches.** All 129 installed Python
distributions match `uv.lock`; no dependency-package symlinks or
`claude_agent_sdk` module / `claude-agent-sdk` distribution exist. The project
retains its normal editable installation. PEP 517 build requirements remain
constrained by the project, not permanently bit-reproducible.

`npm ci --offline --no-audit --foreground-scripts` installed 1,728 packages
with a 768 MiB Node heap. An optional development-browser postinstall warned
that `pnpm` was absent; the actual browser checks used installed Chromium and
passed. Supported `NX_DAEMON=false` and `NX_ISOLATE_PLUGINS=false` settings avoided
this executor's unavailable Unix-domain worker sockets. No product source,
lockfile or network guard was changed to obtain a pass.

Builds used two CPUs, one Angular worker and a 2,048 MiB process-tree watchdog.
The first cached npm attempt exceeded that guard at 2,097.848 MiB; the first
production loop reached 2,050.234 MiB. Both were stopped with zero survivors and
remain failed attempts. Serial lifecycle scripts and a separate guarded Nx
invocation for each production target, with a 768 MiB per-Node heap, passed
under the same cap. An Nx success line before guard termination is not a stage
pass. Full commands, resource receipts and failed-attempt logs are retained.

### Reproduction boundary

Use an isolated exact-source checkout, the recorded locked dependency versions,
no operator `.env` or credentials, and bounded serial jobs with retained exit
and cleanup receipts. An empty cache requires an ordinary locked install;
`--offline` is appropriate only when the required cache is already complete.
Do not infer a full-suite pass from a focused command or a successful build.

The frontend production path used the supported local Nx settings and separate
invocations below, rather than a memory-accumulating combined production job:

```sh
export NX_DAEMON=false NX_ISOLATE_PLUGINS=false NG_BUILD_MAX_WORKERS=1
npm exec -- nx run-many -t typecheck lint --all --parallel=1 --skip-nx-cache
npm exec -- nx run-many -t test --all --parallel=1 --skip-nx-cache
for project in shared-state provider-widget settings-remote sidebar-remote domain-remote chat-remote shell; do
  NODE_OPTIONS=--max-old-space-size=768 npm exec -- nx build "$project" --configuration=production --parallel=1 --skip-nx-cache
done
./scripts/link-remotes.sh
npm run smoke:shipment-settings-layout
```

The browser regression needs an installed compatible Chromium, selected with
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` when necessary. Run the production
`shipagent-core.spec` through the locked native Python environment after staging
assets. The normal `bundle_backend.sh` includes its own npm install/build, so
native qualification of already verified staged inputs invokes PyInstaller
directly before the app-only Tauri build. Inspect the actual final package;
source scans alone are insufficient.

### Actual frozen artifact

PyInstaller ran in an explicit clean environment with no `PYTHONPATH`,
`LD_PRELOAD`, test hook, runtime mock or operator credentials. Actual inspection
found 5,103 PYZ modules plus 11 outer archive entries, all three provider
adapters, and no SDK, tests, pytest, `_pytest`, offline instrumentation or
`sitecustomize`. All seven UPS YAMLs match the pinned package, and all 593
packaged shell/staged-remote files match the final production frontend.

- Source files: **1,187**, byte-verified against the candidate
- Full frontend: **1,202 files / 38,379,939 bytes**
- Frontend manifest SHA-256:
  `8632ddd316fc1d763cc58cfbf78313a55eff81a2a97cea3dd0167f20a70db448`
- Frozen folder: **852 regular files**, no external dependency symlinks
- Executable SHA-256:
  `34d01e72af8c33cc213edf35fa3962608b832038e59e63180ff2b4e331134081`
- Retained Linux test archive: `shipagent-linux-test-sidecar-04a4bba.tar.gz`,
  **67,222,304 bytes**, SHA-256
  `ea6e89b3b984cec4d91c92df20fdd0577a01a4f4a3e850295e83e40a94edab6b`
- Retained cloud evidence: `shipagent-cloud-qualified-evidence-04a4bba.zip`,
  **2,268,301 bytes**, SHA-256
  `15204b9a0cb47686600f8e5d659c8ed63912d2052e31e2de1fa1b050e4a1a844`

The executable hash matches the previous candidate because backend code is
unchanged; separately bundled frontend bytes changed. It is not sufficient to
compare only the executable when qualifying the corrected UI. Archives and
complete manifests were independently checked. No binary was published as a
release.

### Actual local workflows and pixels

With all 948 bundle files/directories unwritable, the unchanged binary passed
CLI version/help, dynamic-port startup, health/settings/readiness diagnostics,
real DataSource MCP child startup, all four remote manifests/exposed chunks,
two-row CSV/XLSX multipart imports, conversation JSON export, and raw frozen
CSV/XLSX import plus atomic write-back of synthetic tracking values. Sibling,
sensitive-name, traversal, symlink and symlink-overwrite requests were denied
without replacing the active source. Bundle modes were restored and every hash
remained unchanged.

The tests used empty temporary HOME/CWD/data/SQLite storage, disabled dotenv
and keyring, and no real provider/carrier/commerce credentials. Data/UPS/external
MCP startup/list probes exposed 23/18/8 tools and each exited 0 on EOF. Only the
UPS listing probe received obvious synthetic client credentials; it made no
`tools/call` request. No real shipment or live service call was made.

The actual frozen-origin browser rendered shell, populated chat/composer and
Shipment Behaviour settings at 1200×800 and 900×600, including scrolled
minimum-size settings. Actual local fallback fonts were Noto Sans and DejaVu
Sans Mono. All six layouts had no page/control horizontal overflow, browser
page/console error or external request. Repeated settings close/reopen,
history navigation from Data and from a collapsed sidebar, and unsent-draft
preservation passed.

The separate committed production-layout regression used synthetic API fixtures
and passed 14 states: practical postal width, ancestor clipping, long
labels/values/errors, Tab order, visible focus/caret, rejected-save/retry,
scrolling, header/close hit-testing and reopen. The postal field fits at both
window sizes. Finite animations were settled before pixel review; full raw PNG
checks confirm the header is drawn, rather than relying on a scaled image view.

### Native ARM64 build and static evidence

The exact `04a4bba` source was fetched into an isolated native checkout and
verified clean. Backend, Python lock/spec, Tauri and frontend dependency inputs
were compared with the prepared environment. The native Python 3.12.12
environment contains **128 platform-specific distributions**, matched to the
lockfile and rechecked for SDK absence; the Linux count of 129 is not imposed
on macOS. Build tools were Rust/Cargo 1.92.0, Tauri CLI 2.12.1 and the existing
Command Line Tools SDK 15.4, selected per process on macOS 15.3. No global Xcode
selection or security settings were changed.

The first attempt under installed ARM64 Node 22.17.0/npm 11.9.0 passed install,
type/lint, 199 tests and shared-state, then failed inside
`ModuleLoader.getModuleJobForRequire` with an undefined `getStatus` during the
shell build. It exceeded no resource cap and remains a failed build attempt.
A task-local official **Node 24.19.0 / npm 11.17.0** retry used a fresh dependency
directory and fresh outputs, preserving the first attempt. The official ARM64
archive checksum was checked before extraction. No source or dependency-version
patch was used, and the native npm version is not relabeled as cloud npm 11.9.0.

| Native stage | Retained result |
| --- | --- |
| Fresh `npm ci --no-audit --foreground-scripts` | Exit 0; 172.955 s, peak 399.266 MiB |
| Typecheck/lint | Exit 0; 9.311 s, peak 662.203 MiB |
| Frontend tests | **199 passed**, exit 0; 18.241 s, peak 2,089.172 MiB; separate from the cloud run |
| Seven separate production targets | Passed; maximum target peak 1,436.109 MiB; all four staged remotes byte-equal their native build outputs |
| PyInstaller plus first inspection | PyInstaller completed successfully; the combined wrapper exited **1** after inspection-helper false positives; 26.725 s, peak 402.016 MiB |
| Corrected static reinspection | Exit 0; 1.201 s, peak 112.188 MiB; unchanged frozen artifact, no refreeze |
| App-only Tauri build/inspection | Exit 0; 153.658 s, peak 1,624.953 MiB; Cargo lock unchanged |

The first inspector mistakenly treated Mach-O `LC_ID_DYLIB` self-identifiers
as load dependencies and only recognized `dist-info`, missing valid project
`egg-info/PKG-INFO`. Retained `otool` records and metadata support the two helper
corrections. Original failures, helper diff and reinspection are preserved;
the failed wrapper is not reported as exit 0. Every stage's owned-process
cleanup was verified with no remaining owned processes. RSS was sampled over
the owned tree; ordinary macOS scheduling was used, with no CPU-affinity claim.

The app-only command was `cargo tauri build --bundles app --ci --no-sign --
--locked --jobs 2`, with per-command CLT selection, no inherited `TAURI_CONFIG`
and no build-hook override. The actual committed config has no frontend build
hook. Existing verified frontend/sidecar inputs were packaged without rerunning
`bundle_backend.sh`.

Native inspection found **5,099 distinct outer/inner frozen archive names**,
all three provider adapters and no Claude Agent SDK. The retained full inventory
also has no pytest, `_pytest`, project tests, offline harness or `sitecustomize`.
All **85 native sidecar Mach-O files** contain ARM64; actual load dependencies
resolve within the bundle or to macOS system libraries. Four Python-framework
symlinks in the standalone freeze resolve internally. The Tauri copy contains
**915 regular files / 156,445,257 bytes** and no symlinks. Its packaged sidecar
resources match the native freeze; all **593 shell/staged-remote files** match
the native frontend manifest. The seven UPS YAML hashes also match the pinned
source-package hashes already retained in cloud evidence.

- Native frontend manifest SHA-256:
  `9ddaa6c44a81be8d31d756747d20b52baf43cdb2f722525667e7e0d0d1542222`
- Native app manifest SHA-256:
  `3cf8b286b01cc4eb7344d3aa200b82b200a03fa8f46cff2344e81f5d23519997`
- Native app executable SHA-256:
  `8e205475de4b620f8cfbd4fa0322dcc137a83ce1dedd316dc364c4a4a58f8ed8`
- Native sidecar SHA-256:
  `8072fa9ea38163cba50181d4532ecc9c6637081332a6c95c4d7519da58aba5b9`
- Retained static evidence: `shipagent-native-static-evidence-04a4bba-20261008.zip`,
  **282,636 bytes**, SHA-256
  `8884fbc41a1c6035d2f7557c3f1ede450a2c5a82b2dab7166b5a6d358bec2a7e`.
  Its 98 archive members include 97 independently hash-checked payload files
  plus the manifest. Binaries, dependencies, credentials and real profile
  contents are excluded.

### Native QA derivative and packaged-sidecar runtime

**Neither native app has been opened.** Read-only preflight proved that temporary
`HOME` does not redirect macOS Foundation home/Library/Application Support;
existing ShipAgent-specific persistent WebKit/cache locations are present.
Their contents were not inspected or changed. The production wrapper uses
the default persistent WebKit store. A reviewed QA derivative was therefore
built with a **one-key bundle-identifier overlay**,
`com.shipagent.qa.r04a4bba.t20261008`, preserving that store type and every other
configuration field. Eight identity-specific namespaces were absent, with
non-symlink ancestry verified. The original production app was preserved and
all 915 original file hashes rechecked before and after the QA build.

The QA app-only build passed in **27.935 s**, peak **973.047 MiB**. Only
`Contents/Info.plist` and the wrapper executable changed; the sole plist change
is `CFBundleIdentifier`. All **913 resource files**, including the full frozen
backend and frontend, are byte-identical. The source remains clean at `04a4bba`
and all four tracked lockfile hashes match. This derivative does not test the
production identifier, existing-profile migration, signing or distribution.

- QA app executable SHA-256:
  `d129af41b825caf8b46481c148ad16d72af442268aaaf1761495840c38cf4be3`
- QA app manifest SHA-256:
  `cbbfc1dda2d3c96f7544d9d06d1b3c5c09f6d41434b90762a33159d7235f7a96`
- QA supplement: `shipagent-native-qa-supplement-04a4bba-20261008.zip`,
  **158,093 bytes**, SHA-256
  `5768ee89c9e7721ca76a04b4d98be6b414f254bc198ef3e5a8ffa4a3e48ac472`.
  All 57 payload hashes plus the archive manifest were checked. It also retains
  raw `LC_ID_DYLIB` / project metadata evidence for the earlier helper corrections.

Native GUI permission preflight found screen capture available but no usable
Accessibility/event-posting route. No app was launched and no permission was
changed. That environment prerequisite is not a product runtime failure.
Real native window/font/keyboard/scroll/dismissal/repeated-flow and ordinary
application Quit acceptance remain **not run**.

The independent backend gate used the QA app's **actual bundled sidecar**, whose
bytes equal the preserved production sidecar, without starting Tauri or WebKit.
Its 360-second / 2 GiB guard completed in **8.093 s**, peak **541.688 MiB**, exit 0.
The exact reviewed harness hashes were verified on the Mac and in retained
evidence. Both the harness and outer supervisor recorded **zero fallback
signals, zero ownership-monitor errors and zero owned survivors**.

The run used fresh task-local HOME/CWD/TMPDIR, data/SQLite, audit and credential-key
paths, disabled dotenv/keyring, a disposable filter secret, fake-local auth and
loopback binding. Credential-status booleans were false for all providers,
carrier, commerce and API credentials; only the synthetic filter secret was
present. No hot-folder config, chat/model request or live service call was used.

Observed checks include CLI version/help, health/readiness, settings, two
dynamic-port starts with exact PID/start/executable and `lsof` listener ownership,
and all four remote manifests/exposed chunks matched to native packaged hashes.
Two-row CSV/XLSX multipart imports and raw DataSource MCP atomic write-back
passed. Sibling, sensitive-name, traversal, symlink and overwrite denials
preserved the **complete** active-source identity/schema, not just row count.
Data/UPS/external MCP exposed **23/18/8** tools and all three exited **0 on EOF**;
only DataSource local import/write-back tools were called. UPS listing used
disposable synthetic credentials.

One synthetic message was inserted directly into the disposable SQLite database
to test conversation JSON export and restart persistence. No chat endpoint or
provider submission was used. The exported session/title and exact message
ID/role/type/content/sequence matched across restart; saved settings survived and
`PRAGMA integrity_check` returned `ok`. This does not test model responses or
cross-port WebView localStorage persistence.

Both standalone servers retired on their intended exact-child **SIGTERM** with
exit **-15**; both listeners closed and observed MCP descendants retired without
fallback. This is not an ordinary Tauri Quit result or an exit-0 graceful-server
claim. The locked native wrapper's normal UI-quit policy calls
`CommandChild.kill()` (Unix SIGKILL); its separate future acceptance must verify
actual listener/sidecar/MCP retirement and database integrity without external
supervisor cleanup. The known closed-stdio `ValueError` remains in all three MCP
logs despite EOF exit 0. Expected negative-import errors and single-worker /
in-memory-queue warnings are also retained.

Source, all four locks, native packaged bytes and QA app manifest remained
unchanged. Native read-only bundle modes were not enforced; the unwritable-install
result remains Linux-only. Runtime evidence is retained as
`shipagent-native-sidecar-evidence-04a4bba-20261008.zip`, **84,742 bytes**, SHA-256
`e4e27d08c1462c8980b7733d7bdfdd090e344ad6b76ad8665fd0d571bc819435`;
all 33 payload hashes plus the archive manifest were checked. It contains no
secret values, databases, binaries or user profile contents.

### Remaining native gate and residual limitations

1. The exact candidate's native build/static checks above are complete. Preserve
   its own frontend, staged-remote and app-resource identities; do not require
   cross-toolchain equality with Linux or substitute a Linux binary/environment.
   The one-key QA identity provides the reviewed isolation approach and verified
   absent-path preconditions; actual WebKit write paths await launch. GUI control
   remains unavailable until the environment prerequisite is resolved.
2. Launch the reviewed QA `.app`, verify that it starts its own native sidecar, inspect
   its real window/default and minimum size, exercise synthetic local workflows,
   then verify ordinary UI quit stops the exact owned sidecar/listener/MCP children
   without supervisor fallback. Preserve the production-identity limitations.
3. Record native source, architecture, toolchain, commands, artifact hashes,
   screenshots and cleanup. Until those observations exist, #41 and #30 remain
   open and no complete desktop qualification is claimed.
4. `/readyz` is intentionally degraded because UPS credentials are absent;
   database/filter-secret checks are healthy. This is not live carrier readiness.
   Frozen MCP shutdown still logs the known closed-stdio `ValueError` after
   successful work. EOF probes exit 0, server SIGTERM completes lifespan cleanup,
   and owned-process supervision finds no survivors. The diagnostic is retained,
   not suppressed or claimed fixed; upstream causality is not proven here.
5. Optional PyInstaller warnings for pycparser tables, unused alternate database
   drivers and Windows `user32` on Linux remain in the logs. DMG,
   signing/notarization, updater, Intel and other native targets remain unverified.
   No hosted deployment or separate connector-roadmap completion is implied.

The previous 71995b7 candidate's clipped postal control and all failed attempts
are preserved separately; they are not retroactively described as passes.

## Historical qualification record

The following 2026-10-07 report is retained as originally recorded for its
source/artifact identities. Its earlier test counts, then-open visual gate and
PR status are historical. The current qualification and remaining native gate
above supersede its status summary.

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
