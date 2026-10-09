# Authenticated Agent Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the existing source-free Agent Run lifecycle through the real
HTTP/JWT/persistent-link authorization path with one explicitly owned local target.

**Architecture:** Keep one existing run store, service and shared model runtime.
A captured operation pins the target coordinator, acquires a nonwaiting SQLite
writer followed by PostgreSQL account/link authority, and preserves separate
local commit and original PostgreSQL settlement evidence. The worker obtains
its own one-shot dispatch authorization and fresh publication authority.

**Tech Stack:** Existing Python, FastAPI/FastMCP, SQLite, SQLAlchemy asyncpg bridge,
PostgreSQL 17, Alembic and pytest. No new dependency or live service provisioning.

**Spec:** [Authenticated synthetic lifecycle](../specs/2026-10-09-authenticated-agent-lifecycle-design.md),
SHA256 `2a5f55340b90c1b5b90827bb08345d4fece47a80d257bd0af543aeb0aef0b343`.

**Execution:** Serial implementation by the current integrator and independent
review after each checkpoint. Task 1 begins only after this plan is reviewed.
Do not create additional worker lanes or implement later tasks before their gate.
Current status: Task 1 author qualification is in progress; Tasks 2–5 remain unstarted.

## Global Constraints

- Baseline is main `551f257a2f66ac15195e5d25c4b64d101a3c8508`.
- Production construction stays status-only; no public upload, mutation, credential,
  source, approval or artifact admission; no changes to the held headless work.
- The local composition uses a scripted provider and exact account/target pins.
- Strict operation budget is two seconds, captured before persistent identity work.
- Accepted-turn authority is `min(token_expiry, accepted_at + 120 seconds)`;
  configured model timeout is at most 120 seconds, default 30 seconds.
- Original conversation/reference ceiling remains 24 hours; no refresh on retry.
- Strict profile admits one model call per accepted run; zero tool declarations.
- Strict private-history JSON is at most 1 MiB before materialization; existing
  privacy projection and provider replay limits still apply separately.
- Per-service strict operation slot allows one owner and zero HTTP waiters.
- Lock order is coordinator → SQLite writer → PostgreSQL account → link.
- PostgreSQL COMMIT is the dispatch authorization linearization point. The later
  same-connection committed-XID query proves that earlier event; it does not move it.
- No implicit reconnect, recursive action retry, new idempotency key or cross-DB
  atomicity claim. Prior failure stays latched even if a commit is later known.
- Pin the physical driver/backend/top-level xid8 and positively retire the
  evidence-only status-query transaction before releasing ownership.
- All checks use the shared bounded validation lock and preserve RED/failure receipts.
- Preflight author and committer as `matt-hans <m.hans93@icloud.com>` before each
  plain commit. No identity overrides, publication rewrite or force push.

## Review Focus

- A valid token expires during identity resolution: the handler receives the
  original exhausted budget and denies without creating a run (Tasks 1 and 5).
- An older broad token arrives after policy reduction: request scope cannot
  restore durable permission or revive a revoked link (Tasks 1 and 3).
- PostgreSQL returns normally from COMMIT of an aborted transaction: the exact
  captured XID remains aborted and no response/dispatch is acknowledged (Task 3).
- One SQLite writer yields to asyncpg while another request arrives: prompt busy
  avoids blocking the event loop needed by the first owner (Tasks 2 and 3).
- Shutdown or cancellation occurs after local COMMIT: retain the same key and
  exact scopes, deny fresh success if settlement/retirement is uncertain, and
  never replay the model on restart (Tasks 3–5).

## Validation convention

The commands below are the child pytest selections, not permission to bypass the
established supervisor. Use the prepared project interpreter, reviewed bounded
runner/guard, common heavy lock and unique receipt name. Include the existing
disposable service root for PostgreSQL tests; missing required service binaries
are a blocked gate, not a passing skip. Use `-c pyproject.toml` explicitly. Keep
source/hash guards and no-limit/no-cleanup/no-survivor/runtime-removal checks.

Focused iterations use 30–90 second bounds; combined process/HTTP checkpoints
may use 150 seconds after measuring the selection. The final fresh remote full
uses the unchanged reviewed external supervisor and existing 900-second/1536-MiB
bound. Release between checkpoints and honor already-queued Bulldog work.

## Task 1: Verified independent links and request lifetimes

**Files:**
- Modify `src/control_plane/auth/jwt_verifier.py`, `context.py`, `service.py`.
- Modify `src/control_plane/models.py`, `config.py`, `app.py` only for verified
  claim configuration and propagation of the original authorization deadline.
- Create `alembic/versions/20261009_0005_provider_links.py`.
- Modify `tests/control_plane/auth/test_jwt_verifier.py`, `test_service.py`,
  `tests/control_plane/test_models.py`, `test_migrations_postgres.py`.
- Create `tests/control_plane/persistence/test_provider_links.py`.
- Adapt existing fake auth fixtures only where the extended trusted signature
  requires it; preserve their actual assertions and legacy status behavior.

**Interfaces:**
- Extend `TokenPrincipal` with verified `issuer: str | None`,
  `issued_at: float | None`, `expires_at: float | None`,
  `issuer_link_id: str | None`; legacy fixture defaults remain unbound.
- `Auth0TokenVerifier(..., provider_link_claim: str | None = None)` reads only
  the configured claim after signature/issuer/audience validation.
- Extend `AuthorizationContext` with optional `issuer`, `link_epoch`,
  `token_expires_at`, `operation_deadline`; existing public identity fields stay.
- Extend `AuthorizationService.resolve` with the verified issuer/link/expiry
  fields and original monotonic deadline. Missing strict proof denies lifecycle;
  legacy status resolution remains explicitly separate.
- Persist nullable account issuer and strict connection issuer-link ID, epoch
  and allowed-scope ceiling. Enforce all-or-none strict binding and distinct
  legacy/strict uniqueness. Keep revoked rows as tombstones.
- Add trusted internal `revoke_link(account_id, connection_id)` and
  `reduce_link_scopes(account_id, connection_id, allowed_scopes)` methods using
  account→link row locks. Reduction cannot expand scope or reactivate a row.

- [ ] **Establish baseline.** Run existing auth/app/OAuth wire/model/migration
  selection on the unchanged executable tree; retain exact receipt.
- [ ] **Write RED tests.** Signed tokens reject bool, NaN/infinity, out-of-range,
  inverted, future-issued and expired timestamps; fractional expiry is exact.
  Assert two issuer link IDs under the same subject/client produce different
  connection IDs/epochs, while refreshed tokens preserve one link.
- [ ] **Run the focused RED selection.** Expected failures are missing strict
  fields/independent resolution, not fixture/network errors.
- [ ] **Implement the exact fields and migration.** Claim IDs use
  `[A-Za-z0-9_-]{1,128}`; configured claim names are bounded HTTPS namespace URIs
  without userinfo/query/fragment. New strict accounts bind verified issuer;
  legacy rows remain unbound. Do not copy token scopes into strict allowed policy.
- [ ] **Add persistence RED/GREEN cases.** Concurrent first use converges; legacy
  NULL bindings cannot authorize strict runs; old revoked tuples remain denied;
  a new grant gets a new identity; older broad/narrow tokens in both orders cannot
  change a reduced ceiling. Wrong issuer and expired post-lock resolution deny.
  Run real PostgreSQL migration upgrade/rollback-failure checks preserving rows.
- [ ] **Preserve failed identity cleanup.** Keep the exact session and original
  failure when rollback fails, deny further use, and test cancellation/timeout
  plus rollback faults. This checkpoint does not qualify bounded HTTP cleanup;
  the Task 3 owner must capture the same service/session before effects and own
  bounded retirement before any opt-in profile is enabled.
- [ ] **Run GREEN and commit.** `pytest -c pyproject.toml -q tests/control_plane/auth
  tests/control_plane/test_app_auth.py tests/control_plane/test_models.py
  tests/control_plane/test_migrations_postgres.py
  tests/control_plane/persistence/test_provider_links.py`.
  Run changed-file Ruff/diff checks; freeze and obtain independent Task 1 approval.

## Task 2: Owned nonwaiting run-store operations and turn expiry

**Files:**
- Modify `src/services/agent_runs/store.py`.
- Create `src/services/agent_runs/transaction.py`.
- Modify `src/services/agent_runs/source_ownership.py` only for explicit new
  Agent Run schema-version compatibility; preserve its source ownership rules.
- Create `tests/services/agent_runs/test_authorized_transaction.py` and
  `test_authority_migration.py`.
- Extend `tests/services/agent_runs/test_store.py` for original turn deadlines.

**Interfaces:**
- `AgentRun` gains private optional `turn_authority_expires_at: float | None`.
- Explicit lease-owned upgrade moves V1/V2 to V3 atomically and leaves legacy
  run authority NULL; reads/opens still do not perform migration.
- `AgentRunStore.transaction(*, borrow, generation, monotonic)` allocates an
  unacquired `AgentRunTransaction`; caller captures it before `acquire(deadline)`.
- The transaction exposes fixed accept/continue/read/cancel/claim/history/finish
  actions, `commit()` and `retire()`, plus read-only attempted/known-commit facts.
  It never exposes its raw connection/cursor or a reusable commit closure.
- Existing store entrypoints and owned actions share private connection-scoped
  SQL helpers; do not duplicate acceptance/idempotency/revision logic.
- Owned history reads inspect stored byte length before fetching/parsing JSON;
  the strict ceiling is 1 MiB. This does not relabel the provider replay limit
  as a durable-storage cap or change legacy private reads.
- Owned scope uses `timeout=0`/`busy_timeout=0`, current coordinator/path identity,
  strict deadline checks and retained cursors/connection before every effect.

- [ ] **Write and run RED.** Hold an external SQLite writer; owned acquire must
  return busy promptly without the existing three-second wait. Verify copied/
  fork-inherited owners cannot use or retire original handles.
- [ ] **Implement captured ownership.** Record local COMMIT attempted immediately
  before SQL and known only after success; capture every cursor before post-SQL
  deadline checks. Explicit retirement closes cursors before physical connection
  proof. Before/after-effect failures retain retryable stages and original borrow.
- [ ] **Write migration/expiry RED.** Preserve legacy rows unbound across normal
  upgrade, SQL failure and process death. A new strict run stores exactly the
  minimum accepting-token/120-second deadline; duplicate/reopen does not renew
  it; continuation keeps the original conversation expiry. Stored history above
  1 MiB is denied before materialization; the bounded private result still passes
  through the existing provider privacy/replay limits.
- [ ] **Implement V3 compatibility and run GREEN.** New strict operations reject
  legacy NULL authority; old explicitly synthetic callers retain their historical
  behavior. Source ownership only recognizes compatible version3 layout; no source
  feature is enabled or changed.
- [ ] **Qualify and commit.** `pytest -c pyproject.toml -q tests/services/agent_runs
  tests/services/source_ingress/test_reservation_store.py
  tests/services/source_ingress/test_snapshot_store.py
  tests/services/source_ingress/test_snapshot_migration.py
  tests/services/source_ingress/test_source_fences.py`.
  Freeze for
  independent shared-storage/lifecycle review before Task 3.

## Task 3: PostgreSQL authority operation and settlement proof

**Files:**
- Create `src/services/agent_runs/authority.py` for closed immutable request/
  accepted-run contracts and the six-method internal authority protocol.
- Create `src/control_plane/agent_run_authority.py` for its PostgreSQL implementation.
- Modify `src/services/agent_runs/service.py` only for captured ordinary coordinator
  borrow, one prompt-busy operation slot, shutdown retention and explicit retry cleanup.
- Create `tests/control_plane/persistence/test_agent_run_authority.py`,
  `test_agent_run_authority_faults.py`, `agent_run_authority_process.py`.
- Extend `tests/services/agent_runs/test_coordinator_borrow.py` for close above
  an admitted authority operation. Reuse existing disposable PostgreSQL fixtures.

**Interfaces:**
- `RunRequestAuthority` is immutable, exact-type validated and private: account,
  connection, expected epoch, issuer, surface, effective scopes, exact target,
  token expiry and original operation deadline. No public JSON argument creates it.
- `AgentRunAuthority` has async `submit`, `continue_turn`, `read`, `cancel`,
  `admit_dispatch` and `publish` methods. Their inputs are the exact service,
  `RunRequestAuthority` or persisted `AgentRun`, plus the existing closed operation
  arguments. Submit/continue/read/cancel return `AgentRun`; dispatch returns a
  private `AuthorizedRunDispatch`; publish returns no new reference.
- `AuthorizedRunDispatch` contains the one-shot `RunDispatchPermit` and bounded
  immutable `private_history_json: bytes`, hidden from repr. History is read
  under held current authority and returned only after settlement/retirement;
  it never enters public target requests/results or PostgreSQL metadata.
- `PostgresAgentRunAuthority` implements those fixed operations. Its captured
  private owner holds the exact target transaction, PostgreSQL connection/
  transaction, original driver/backend/XID, deadline and result/failure state.
- `begin_http_operation(service, deadline) -> AgentRunAuthorityOwner` captures
  the ordinary coordinator borrow and slot synchronously before persistent
  identity resolution. It owns the exact Task 1 service/session, including
  retained rollback failures; no automatic context exit may discard them. After resolution, `owner.bind_request(context)` creates
  the one immutable `RunRequestAuthority` for that owner. The fixed HTTP methods
  require that exact bound object to belong to the still-active owner; a copied
  value or another request cannot adopt it. Worker methods allocate their own
  owner and never look up the current HTTP owner.
- A `RunDispatchPermit` names one exact run/service/generation and original
  deadline. It is issued only after proven settlement and retirement, and can
  be consumed exactly once by that service's captured provider owner.

- [ ] **Write/run RED.** Compose real PostgreSQL and owned SQLite transactions;
  prove account→link lock order, expected-epoch denial and policy intersection.
  A barrier must let the asyncio heartbeat/cancel task run while PostgreSQL is
  blocked; a second own operation is promptly busy with no waiter accumulation.
- [ ] **Implement bounded acquisition.** Capture service/borrow/slot before awaits,
  use `AsyncConnection.run_sync` and exact connection-bound Core queries, apply
  remaining-budget pool/statement/lock timeouts, and sample expiry after waits.
  Authority mutations never acquire the Agent Run store while holding row locks.
- [ ] **Write/run settlement RED.** Deliberately abort a real transaction, then
  allow COMMIT to return normally: `pg_xact_status(original_xid)` must be aborted
  and the request denied. Check committed/in-progress/NULL/unsupported outcomes,
  changed driver/backend, implicit reconnect, and a failure followed by a known
  commit. A failed request stays failed in every case.
- [ ] **Implement settlement and retirement.** Pin top-level xid8 and original
  driver/backend; verify the original live transaction before COMMIT, then require
  committed status on that same connection. Capture and retire the evidence-only
  transaction. PostgreSQL COMMIT is the authorization point; status is later proof.
- [ ] **Run death/cancel RED/GREEN.** Kill only owned disposable PostgreSQL at
  controlled validation/local-COMMIT/PG-COMMIT boundaries. Preserve same-key local
  outcomes, no action retry, no model permit and no falsely fresh success.
  Cancellation/control-flow interruption and close faults retain ownership and
  denial before escaping; restored explicit cleanup never remints work.
- [ ] **Qualify and commit.** `pytest -c pyproject.toml -q
  tests/control_plane/persistence/test_provider_links.py
  tests/control_plane/persistence/test_agent_run_authority.py
  tests/control_plane/persistence/test_agent_run_authority_faults.py
  tests/services/agent_runs/test_authorized_transaction.py
  tests/services/agent_runs/test_coordinator_borrow.py`.
  Freeze for independent real-PostgreSQL/cleanup review before worker wiring.

## Task 4: Strict service and one-shot worker dispatch

**Files:**
- Modify `src/services/agent_runs/service.py`, `execution_target.py`, `authority.py`.
- Create `src/services/agent_runs/authorized_provider.py`.
- Create `tests/services/agent_runs/test_authenticated_service.py`,
  `test_authenticated_recovery.py`.
- Extend the Task3 real PostgreSQL tests for dispatch/publication races.

**Interfaces:**
- `AgentRunService(..., authority: AgentRunAuthority | None = None)` is mutually
  exclusive with the legacy `connection_epoch` callback. Its strict mode denies
  the unbound synchronous submit/read/cancel API rather than falling back.
- Async `submit_authenticated`, `continue_authenticated`, `read_authenticated`
  and `cancel_authenticated` accept `RunRequestAuthority` and existing arguments,
  delegate to the authority owner, then apply existing public result projection.
- The strict worker uses `admit_dispatch(service, run)` and
  `publish(service, run, outcome, private_history, clarification)` from Task3.
- Before dispatch, `AgentRunService._claim_strict_candidate()` owns a separate
  local-only Task2 transaction under its coordinator borrow and strict slot. It
  claims one candidate or returns none and positively retires; it grants no
  provider permission and does not fetch private history. Any wait between this
  claim and Task3 admission remains under the original turn/reference expiry.
- `AuthorizedRunProvider(provider, permit)` implements the existing
  `ModelProviderClient.stream_turn`/`cancel`; it consumes the exact permit before
  invoking the owned provider and rejects any second call. The same shared
  runtime runs with `max_turns=1` for this strict source-free profile.

- [ ] **Write/run RED.** Revocation-before-dispatch produces zero provider calls;
  dispatch-before-revocation permits only the already-admitted call and no later
  successful/clarifying publication. Count actual provider entries, not only
  factory creation. Reusing or copying a permit, changing run/provider, and
  expiry before consumption deny before entry.
- [ ] **Implement strict worker routing.** Every strict SQLite operation,
  including claim/history, timeout/denial cleanup and coordinator checks, uses
  the bounded owned path. Do not call the legacy fixed-timeout DB helper while
  another strict operation yields. No ambient request context or epoch cache.
  Decode the private dispatch result only for the original session/runtime;
  never attach its history to a public request, result, log or control-plane row.
- [ ] **Add lifetime/restart RED/GREEN.** Queued original authority expires with
  zero calls; refreshed tokens do not extend an old turn; accepted retry/restart
  preserves identity; interrupted running work never replays. Ordinary authority
  denial records safe interruption only, while storage/settlement uncertainty
  fences the service and keeps commit evidence.
- [ ] **Run cancellation/close RED/GREEN.** HTTP caller cancellation after commit,
  service close during acquisition/settlement, hostile provider cleanup and late
  completion retain the original coordinator until actual retirement. A model
  tool attempt has zero external effects and never triggers a second model call.
- [ ] **Qualify and commit.** Run all Agent Run tests, Task3 PostgreSQL tests and
  `tests/services/test_source_free_conversation.py` plus
  `tests/services/conversation_runtime/`. Freeze for independent
  worker/lifetime review before the app can opt into this path.

## Task 5: Real authenticated app composition and final qualification

**Files:**
- Create `src/control_plane/agent_run_profile.py`.
- Modify `src/control_plane/app.py`, `execution_targets.py`,
  `src/hosted_mcp/execution_target_handlers.py` for trusted profile/context routing.
- Create `tests/control_plane/test_authenticated_agent_lifecycle.py` and
  `tests/control_plane/persistence/test_authenticated_agent_restart.py`.
- Update `docs/plugin-backend/agent-run-tracer.md`,
  `docs/integrations/auth0-provider-clients.md`, and this plan's checkpoint status.
- Update `scripts/run_mcp_acceptance.sh`/acceptance guide only if the independent
  reviewer approves adding the bounded new selection to the existing entrypoint.

**Interfaces:**
- `AuthenticatedAgentRunProfile` owns one exact account/target/store/service,
  pinned strict issuer contract and PostgreSQL authority implementation. It owns
  asynchronous start/close and the retained cleanup path. Only trusted code can
  construct it; scripted provider access is explicit and no live SDK is selected.
- `create_control_plane_app(..., agent_run_profile=None)` accepts this exact
  profile only as a trusted argument. Reject an additional conflicting target,
  nonlocal qualification environment or mismatched account/target/configuration.
  No environment boolean or request data enables the profile.
- Internal `TargetToolRequest` carries the immutable captured strict authority;
  fixed lifecycle handlers preserve it rather than reconstructing current epoch.
  Default target/status construction and the legacy relay wire remain unchanged.
- Opt-in descriptors are exactly status plus the four canonical lifecycle tools;
  do not enable arbitrary registry entries or modify model-visible schemas.
- The profile owns a fixed `get_shipagent_status` handler for its healthy pinned
  target. It returns the existing ready/status projection and capability
  `get_shipagent_status` only; lifecycle availability is accurately listed by
  the four tool descriptors. It performs no model or run-store action and never
  invents a capability code. Unavailable target ownership yields unavailable.

- [ ] **Write/run RED.** Launch the actual app on loopback with real signature/
  issuer/audience checks, real persistent links/PostgreSQL and the scripted target.
  No synthetic identity middleware or mocked AuthorizationService. Assert the
  precise catalog, per-tool scopes/annotations and full lifecycle outcome.
- [ ] **Implement the explicit composition.** One original deadline is captured
  before persistent auth and reaches the handler unchanged. Call Task3's
  `begin_http_operation` before that first await and retain it on the current
  verified HTTP request; bind its immutable request only after actual resolution.
  Private fixed handlers use that owner-bound object, never a header or ambient
  fallback. The HTTP owner retires on auth denial as well as handler completion.
  The middleware owns retirement for initialize/list, missing scope, unknown
  tool, schema denial, disconnect and BaseException even when no lifecycle
  handler executes. Failed/uncertain cleanup retains the same owner and closes
  admission instead of leaking a slot or releasing its coordinator.
  Profile startup owns
  target lifecycle, account/store pins and failures; shutdown keeps uncertain
  scopes captured. Default construction still exports only status.
- [ ] **Exercise adversarial HTTP RED/GREEN.** Two links using one OAuth client,
  wrong account/target, stale request epoch, revoked old token/new link, expiry
  after a blocked lookup, scope narrowing/older broad token, conflict/duplicate,
  restart/reconnect and cancellation. Assert zero additional provider calls on
  every rejected/read-only path and no sensitive canary in results or logs.
  Explicitly test every no-handler retirement path above and qualified status
  before/after target shutdown; prove the next legitimate request can use a
  positively released slot and cannot use an uncertain one.
- [ ] **Verify metadata/package/docs.** Existing registry schemas should be
  unchanged; run artifact drift and regenerate only if canonical source changed.
  Check wheel inclusion if existing tools support it. Document exact local proof,
  legacy migration limit, issuer/relay/live-client gates and no deployment claim.
- [ ] **Freeze and obtain combined independent review.** Run focused HTTP,
  PostgreSQL, lifecycle, source-free runtime and default OAuth/relay compatibility.
  Include the preserved failure probes and changed shared lifecycle regressions.
- [ ] **Publish and qualify only the approved final tree.** Fresh user-attributed
  draft PR, exact remote identity/tree mapping, one fresh full suite, exact-head
  CI, match-head merge after clean review, then bounded actual-entrypoint plus
  new HTTP/restart tests on main and exact-main CI. Keep prior caveats/history.

## Completion boundary and remaining choices

This plan completes one local authenticated synthetic path. It leaves actual
issuer claim configuration/refresh proof, authenticated relay delivery/headless
startup, temporary HTTPS destination, credentials and cost budget to their
explicit later gates. The held headless audit is untouched. Source-backed
answers/previews, uploads and milestones #76–81 remain incomplete.

Technical choices for this slice are explicit in the approved spec and this
plan. If real PostgreSQL cannot provide the exact settlement evidence or the
existing store cannot keep the promised loop responsiveness without a larger
change, stop at that checkpoint and return the concrete finding for design
review. Do not quietly add a broker, grant ledger, alternate runtime or deployment.
