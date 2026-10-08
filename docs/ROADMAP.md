# ShipAgent development roadmap

Updated 2026-10-08. This is the entry point for current development priorities,
implemented milestones, and the specifications that govern remaining work.
ShipAgent owns conversation orchestration and deterministic shipping workflows;
model providers and client surfaces connect through adapters.

Implementation spec: [GitHub issue #30](https://github.com/matt-hans/ShipAgent/issues/30),
labeled `ready-for-agent`. Its primary acceptance boundary was confirmed by the
user: the existing shared conversation service, with adapter and packaging
checks supplementing it.

The [approved ticket execution guide](superpowers/plans/2026-10-01-provider-neutral-runtime-execution-guide.md)
maps issues #31–#41 to the sequential foundation, four parallel workflow lanes,
SDK cutover and final verification. Native GitHub blocking links define which
tickets can start.

## Current runtime and release qualification

The SDK cutover is integrated at `aa138ddd4eb8e95c3a30fbffc05327ad80c834d1`
([PR #62](https://github.com/matt-hans/ShipAgent/pull/62), issue #40). Anthropic,
OpenAI and Gemini use the ShipAgent-owned shared runtime. Default/legacy Claude
selectors are adapter aliases; production SDK client/hooks, dependency,
startup-probe and packaging coupling are removed. Issues #36–#40 are integrated.
See [runtime setup and migration](runtime/sdk-free-runtime.md) and the
[coverage migration](runtime/sdk-removal-coverage.md).

[Draft PR #63](https://github.com/matt-hans/ShipAgent/pull/63) records issue #41's
current verification and package repairs. Runtime/artifact-tested source is
`15422b911a3018ed1625d20dc341598651bc715e`: a genuine clean SDK-free installation,
384 shared/adapter acceptance tests, 4,986 full-backend passes (29 accounted
skips), 160 frontend tests, all seven production targets, and actual read-only
Linux frozen-sidecar startup/CSV+Excel uploads/owned-process shutdown. See the
[exact evidence, artifact hashes and reproduction notes](runtime/sdk-free-release-evidence.md).

**Issue #41 remains open.** Native macOS Tauri startup and actual rendered
shell/chat/settings fallback-font layout are mandatory unverified gates. Linux
sidecar evidence, source tests and successful builds do not establish those
results. No desktop release, cloud connector completion, live shipment or
offline model inference is implied. The separate dormant authority/store
qualification is recorded below; hosted mutation enablement remains blocked.

## Dormant grant and recovery prerequisite qualification

The following connector-foundation slices are merged and remain opt-in:

- Issue #64, [PR #68](https://github.com/matt-hans/ShipAgent/pull/68), main
  `e305d3a5959a235549fe678d4d8c3a4efc2a4322`: immutable Redis lifetimes,
  hashed PostgreSQL authorization ledger, retention and account cleanup
- Issue #66, [PR #69](https://github.com/matt-hans/ShipAgent/pull/69), main
  `6982504853e63c0385dd41446f1ddf4ec808a442`: bounded durable invocation
  acceptance/recovery, original Job References and proof-backed retry seam
- Issue #67, [PR #70](https://github.com/matt-hans/ShipAgent/pull/70), main
  `1616278768ec6d1774801979494d06287279782f`: fenced real Redis authority,
  commit-before-enable PostgreSQL evidence and single-owner lifecycle bridge

[Issue #51's qualification record](control-plane/execution-grant-qualification.md)
maps all four prerequisites to their design and real-store tests. On pinned main
`1616278`, the focused acceptance/default-wiring smoke passed **119 tests, zero
skips**, and Docker smoke/artifact CI succeeded. Earlier candidate `9a5021d` has
the identical Git tree: its full guarded backend run passed **5,251 tests with
29 accounted skips**, and independent review ran **450 tests with 12 reserved-ID
skips**. Those candidate runs are not relabeled as fresh-main full-suite runs.

This qualifies the dormant prerequisite scope only. Production authenticated
post-gesture approval and live-preview/exact-target adapters, provider-safe
job/status projection, coordinated revocation/retention startup, Redis
persistence/failure policy and broader Plans 2/4/6/7 integration remain required.
The restart proof retains Redis; Redis AOF/power-loss/failover is unverified.
No non-status handler/export is enabled, and local API/CLI/desktop/shipping still
needs no Redis, PostgreSQL, Auth0 or hosted grant service.

## Historical baseline evidence

The following baseline/earlier milestone notes record the state when written;
SDK compatibility references here are historical, superseded by the cutover
above and its migration guide.


Issue #32 establishes the validated baseline in
[PR #54](https://github.com/matt-hans/ShipAgent/pull/54) (draft; merge pending
independent review), branch `codex/issue32-validated-baseline`, based on main
`6db9e41` (PR #53 merge, after the reconciliation PRs #49, #50, #52 and #53 closed
issues #31 and #42–#48). Candidate head reviewed so far: `690be08`; the review-2
blocker fixes are in `dcb3b5a` on the same branch (PR #54 lists the final head). Evidence recorded 2026-10-02 and 2026-10-03, against disposable
databases, isolated data directories and worktree-local locked environments:

- Backend: ruff check clean; full pytest suite passes with hermetic environment
  isolation: `4387 passed, 33 skipped` (2026-10-03, review-2 fix tree). Focused
  suites on `690be08`: registry 250 passed; hosted 248 passed, 12 skipped;
  security 31; provider adapters 20; packaging 13; control plane 431 passed,
  1 skipped. Drift/privacy coverage (provider-artifact drift, contract and
  privacy/redaction suites) is inside the hosted, security and provider-adapter
  counts above and in the full run.
- Migrations: SQLite and disposable PostgreSQL 17 up/down/up chains passed on
  2026-10-02 (revision `20260723_0003`). They were not rerun: no model or
  alembic change since commit `5e21a0c` (2026-10-01) — `git diff 6db9e41..HEAD`
  over `src/db` and `alembic` is empty.
- Frontend (Node 20.x): `npm ci`, lint, typecheck, 186 unit tests and production
  build pass; authenticated production and development-proxy smoke tests passed
  on 2026-10-03 (independent review run) after the polyfills change. No frontend
  source changed afterwards, so they were not rerun.
- Packaging: PyInstaller sidecar builds on Python 3.12. Its hermetic smoke test
  (throwaway `SHIPAGENT_DATA_DIR`, keyring disabled, synthetic secret) now
  requires `/health`, `GET /api/v1/data-sources/status` = 200 and a synthetic
  `.xlsx` import (2 rows) through the bundled data-source MCP child. Review 2
  found that this path was broken in the frozen app and it is fixed: the
  programmatic MCP clients spawned `python -m <module>` (rejected by the frozen
  binary) instead of `mcp-data`/`mcp-external`/`mcp-ups`; and the spec lacked
  `rich._unicode_data` submodules, `lupa.lua51` and fakeredis data that
  fastmcp's `docket` needs at startup. The `calamine` hidden import was a wrong
  module name (`python_calamine`). `.xls` import through calamine was not
  exercised. `cargo tauri build --bundles app` (tauri-cli 2.12.1) succeeds.
- Desktop: the shell previously aborted at launch because the updater plugin was
  registered without `plugins.updater`; it is now registered only when
  configured. The window then stayed blank because the sidecar handoff lived in
  `main`, behind es-module-shims, whose init waits on a blob script the CSP
  blocks; the handoff now runs from the native `polyfills` entry. Verified on a
  release `.app` built on this machine with isolated data and synthetic
  credentials: the app spawns its own `backend-dist/shipagent-core` child, the
  window shows the onboarding screen, `data-sources/status` returns 200 and a
  synthetic Excel import succeeds. Normal Apple-event quit and `SIGTERM` of the
  app both leave no app, sidecar or MCP child (the app kills the exact retained
  child on `RunEvent::Exit` and on SIGTERM). A crash or `SIGKILL` of the app
  cannot be intercepted and leaves the sidecar running until stopped manually;
  there is no automatic parent-death cleanup. DMG, code signing and other
  machines are not verified. Auto-update remains off until a real Ed25519 key is
  provisioned; `capabilities/default.json` still grants `updater:default`.
- At this historical baseline, issue #51 was deferred. Its current bounded
  prerequisite qualification is recorded above; public mutations remain dormant.

Issue #33 (neutral policy decisions) is implemented on branch
`codex/issue33-neutral-policy` from baseline `ccaf0e9` (PR #54 merged); see its
draft PR for the head and evidence. Shared runtime policy gates and the
dispatcher use `PolicyDecision`/`PolicyDenialCode`; the Claude hook envelope is
now a projection localized in `hooks.py`. Scripted-provider acceptance
scenarios live in `tests/services/conversation_acceptance.py`. Issue #51 was
deferred at this milestone; no dormant hosted tools were enabled. Evidence 2026-10-03: full
`pytest` `4416 passed, 33 skipped` at implementation round 1 (isolated data dir,
keyring off); after round 2 the full suite was not re-run, and the focused run
is `273 passed`; `ruff check` clean. Claude SDK removal remains issue #40.

Earlier statements about commit `a4a4bd1` are superseded by this baseline.

## Current capability summary

| Capability | Evidence-backed state | Remaining work |
| --- | --- | --- |
| Desktop shipping application | API/CLI workflows and Linux frozen sidecar verified at `15422b9`; configured Tauri targets remain macOS | Native wrapper startup and rendered layout under #41 |
| Shared conversation runtime | Anthropic/OpenAI/Gemini share orchestration, policy, history, lifecycle and deterministic tools; SDK cutover merged in PR #62 | Finish the explicit native/visual release gates |
| OpenAI and Gemini adapters | Implemented on main; runtime milestone merged in PR #25 | Maintain common behavior and adapter contract coverage |
| Anthropic adapter | Direct Messages translation, shared default selection and SDK removal implemented and tested | Preserve adapter conformance as providers evolve |
| Provider contracts and control plane | Foundation and Auth0 authorization merged, with reconciliation integrated | Finish production workflow wiring and separate connector foundations |
| Relay walking skeleton | Plan 1 merged through PR #28; dormant durable lifecycle/recovery and real authority merged in PRs #69/#70 | Production adapter integration, compatibility and full workflow dispatch |
| Grant persistence and authority | Optional Redis/PostgreSQL prerequisites merged in PRs #68–#70; bounded #51 qualification recorded | Authenticated approval/preview/target integration, safe status projection and production failure-policy qualification |
| Hosted provider shipping | Descriptors and plans exist; production target handler map currently wires only status | Implement prepare/approve/execute, continuation and artifact delivery |
| Provider interfaces | Connector designs and widget plans exist | Complete reviewed approval profiles and real integration; descriptors alone are not readiness |

Earlier historical baseline checks passed 155 targeted runtime/provider/artifact
tests and 309 targeted control-plane/hosted/projection/portability tests. These
are baseline evidence, not full-suite, frontend, live-carrier or marketplace
release certification.

## Milestone 1: Reconcile and integrate existing findings

The reconciled baseline is integrated; the historical planning snapshot and
sequence below explain how it was established, not an outstanding merge task.

At planning time, the branch `codex/provider-contracts-control-plane-foundation-findings` was in a
separate local worktree. Its inspected head was `ad86359`; GitHub's branch head
was `bde0e0b`. It had 73 unpublished commits and diverged from main by 76 branch
commits versus 56 main commits. Its common ancestor was `ab77b2f`. The branch
contained extensive contract/privacy, browser authentication, migration,
terminal diagnostic, recovery and progress fixes, not the completed connector.

Execution order:

1. Record and preserve both branch tips; inspect all worktree changes before
   any integration. Back up and publish existing local findings commits.
2. Merge current main into the findings branch without rewriting its existing
   history. Resolve conflicts against accepted ADRs and current runtime behavior.
3. Assess the final combined diff, including duplicated or superseded fixes.
   Treat historical verification reports as evidence of past runs, not a
   substitute for current checks.
4. Verify backend behavior, provider artifact drift, control-plane migrations,
   affected frontend contracts and builds, and desktop packaging. Run migration
   checks against disposable databases, never a user's operational database.
5. Integrate through a reviewed PR. Splitting coherent subsets is acceptable
   if the combined diff cannot be reviewed reliably; document their dependencies.

Exit: findings are integrated or explicitly deferred with reasons, current main
is the validated baseline, and valuable local work is preserved.

Historical references: the findings worktree's July 23 reconciliation plan,
July 24 hardening plans and final review fixes report. Current integrated
status and evidence are recorded above.

## Milestone 2: Finish provider-neutral orchestration

Implementation through the SDK cutover is integrated. Issue #41's native and
visual release qualification remains open as described above.

The implementation follows the [runtime convergence spec](superpowers/specs/2026-10-01-provider-neutral-runtime-convergence.md)
from the reconciled baseline. ShipAgent owns the model/tool loop, history,
streaming, policy, lifecycle, cancellation, audit and artifact behavior. OpenAI,
Gemini and Anthropic all implement the same model-provider boundary.

Sequence: establish behavior coverage, implement Anthropic protocol translation,
cut model selection and CLI/API entry points over, then remove the Claude SDK
compatibility path, dependencies and packaging/startup probes. These are staged
implementation slices; the milestone is not complete while the compatibility
path is still required.

Exit: equivalent shared workflow behavior across providers, preserved local
confirmation and privacy guarantees, and startup/package validation without the
Claude Agent SDK. Thin vendor HTTP clients are allowed inside adapters; vendor
agent frameworks do not own core orchestration.

## Milestone 3: Complete relay and connector foundations

Follow the [connector execution guide](superpowers/plans/2026-06-30-openai-claude-connector-parallel-execution-guide.md).
Plan 1's walking skeleton exists. Plans 4 and 2 now have the dormant persistence
and recovery slices above, and issue #67 supplies their real-authority bridge.
These are bounded prerequisites, not complete production Plans 2/4/7 or a
completed connector. Check the existing primitives before each remaining slice.

| Order | Existing plans | Required result |
| --- | --- | --- |
| Foundation | 5 ingress; 4 retention/audit; 2 lifecycle/recovery | Guarded ingress, canonical ephemeral state, durable redacted authorization audit, safe accepted-invocation reconciliation and Job References |
| Compatibility and visibility | 3 version gate, then 6 projections | Reject incompatible Execution Targets before dispatch; enforce origin-based visibility and reviewed public schemas |
| Desktop integration | 9 settings/device management | Real account linking and device management against the stable relay contracts |

The guide allows independent lanes after Plan 1. Preserve its shared-file merge
ordering, especially registry, generated artifacts, migrations and Redis keys.
Foundations may proceed alongside milestone 2 after milestone 1 if ownership
and integration boundaries are explicit.

Exit: these foundation gates pass with real process-boundary relay coverage;
status readiness is not shipment execution readiness.

## Milestone 4: Ship reviewed provider workflows

Implement Plan 7 approval/execution after Plans 2, 4 and 6; integrate Plan 8's
OpenAI widget after its backend dependencies; then run Plan 10's golden and
adversarial acceptance corpus. Deliver immutable previews, explicit approval,
Execution Grants, exact approved purchase, Job References and authenticated
Label Download References.

OpenAI execution stays app-only behind a user gesture. Claude uses a
ShipAgent-owned Approval Surface and then continues the provider-led workflow.
Generic MCP remains status/preview-only until it has a separately reviewed
confirmation profile. Cloud persistence excludes rows, labels and credentials.

Exit: reviewed approval profiles and end-to-end workflows work through the
Execution Target, with failure/recovery coverage and no unsafe retry after
ambiguous carrier effects. Deployment and marketplace submission are separate
release actions, not consequences of passing tests.

## Documentation precedence and maintenance

Accepted ADRs and the domain language in `CONTEXT.md` govern business safety and
ownership. This roadmap governs milestone order and current status. The new
runtime convergence spec governs completing SDK removal. The June 10 connector
design and June 30 plans govern the relay-first provider product.

The June 2 portability design supplies the overall direction. The June 4
marketplace production-readiness design contains an earlier hosted-storage
architecture; its incompatible tenant/import/storage proposals do not override
the later relay-first ADRs. The June 5 runtime design and adapter plans remain
useful implementation references, but their optional Claude SDK endpoint is
superseded by the new convergence spec's final SDK-free requirement.

Update this roadmap on each merged milestone with the commit/PR, validation
evidence, remaining gaps and any deferrals. Unchecked historical tasks and
generated descriptors are not implementation status. No single broad rewrite
branch needs to remain open until every marketplace milestone is complete.
