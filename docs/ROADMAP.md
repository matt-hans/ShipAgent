# ShipAgent development roadmap

Updated 2026-10-03. This is the entry point for current development priorities,
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

## Current baseline

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
- Deferred: issue #51 (hosted grant authority/store) stays deferred and blocks
  enabling the dormant public mutation tools.

Earlier statements about commit `a4a4bd1` are superseded by this baseline.

| Capability | Evidence-backed state | Remaining work |
| --- | --- | --- |
| Desktop shipping application | Existing FastAPI services, Angular frontend, Tauri packaging, deterministic shipping workflows | Preserve behavior through migration and validate integration |
| Shared conversation runtime | Implemented normalized messages/events, tool catalog, dispatch, policy, interruption and conversation ownership | Complete Claude cutover and remove provider-shaped core contracts |
| OpenAI and Gemini adapters | Implemented on main; runtime milestone merged in PR #25 | Maintain common behavior and adapter contract coverage |
| Anthropic adapter | Direct Messages adapter has a plan but is not implemented | Implement, switch Claude selection to the shared runtime, remove Claude Agent SDK |
| Provider contracts and control plane | Foundation and Auth0 authorization merged in PRs #26 and #27 | Reconcile findings and finish production workflow wiring |
| Relay walking skeleton | Plan 1 merged through PR #28 with subsequent hardening | Durable lifecycle/recovery, compatibility, full workflow dispatch |
| Hosted provider shipping | Descriptors and plans exist; production target handler map currently wires only status | Implement prepare/approve/execute, continuation and artifact delivery |
| Provider interfaces | Connector designs and widget plans exist | Complete reviewed approval profiles and real integration; descriptors alone are not readiness |

Earlier checks on this main baseline passed 155 targeted runtime/provider/artifact
tests and 309 targeted control-plane/hosted/projection/portability tests. These
are baseline evidence, not full-suite, frontend, live-carrier or marketplace
release certification.

## Milestone 1: Reconcile and integrate existing findings

The branch `codex/provider-contracts-control-plane-foundation-findings` is in a
separate local worktree. Its inspected head is `ad86359`; GitHub's branch head
is `bde0e0b`. It has 73 unpublished commits and diverges from main by 76 branch
commits versus 56 main commits. Its common ancestor is `ab77b2f`. The branch
contains extensive contract/privacy, browser authentication, migration,
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

References: the findings worktree's July 23 reconciliation plan, July 24 hardening
plans, and final review fixes report. These remain in that worktree until
integration; they are not all present in main.

## Milestone 2: Finish provider-neutral orchestration

Implement the [runtime convergence spec](superpowers/specs/2026-10-01-provider-neutral-runtime-convergence.md)
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
Plan 1's walking skeleton exists; the remaining plans are not a claim of
completed implementation. Their existing primitives must be checked before
each slice starts.

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
