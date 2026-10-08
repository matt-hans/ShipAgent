# Durable accepted-job recovery implementation plan

> Agent execution: implement these vertical test-first slices, with independent review before completion. User planning checkpoints are already waived.

**Goal:** Fulfil issue 66's dormant, real-Redis lifecycle seam without enabling hosted mutations or changing local API/CLI/desktop dependencies.

**Architecture:** One Redis invocation lifecycle and one immutable job-reference pointer share an original maximum 86400-second deadline. A stable server-owned idempotency binding identifies the invocation across processes. Dispatch, durable acceptance and reconciliation are separate target operations; only fenced positive nonacceptance can release authorization. Current status-only `ExecutionTarget.invoke` remains unchanged.

**Tech stack:** Existing Python 3.12, Pydantic, redis.asyncio, pytest, and pinned disposable Debian Redis/PostgreSQL fixtures. No new application dependencies.

**Sources:** Issue 66, ADR 0003, authorization-persistence.md, execution-grant-authority-contract.md, and accepted Plan 2. Historical Plan 2 snippets using model tokens, TTL refresh, guessed target APIs, or timeout-as-nonacceptance are superseded.

## Constraints and interfaces

- Raw arguments remain transit-only; compute `relay_invocation_input_hash(tool_name, arguments)` internally.
- Canonical `sa_job_<32hex>` values are used for dormant `job_ref`. Public `job_id` schemas/projections remain unchanged pending separate enablement.
- Use existing `RelayInvocationEnvelope.deadline_at` and fields. A new optional durable-target protocol explicitly distinguishes sending from evidence queries; status-only desktop targets do not implicitly provide it.
- Exact account, Provider Connection, Execution Target, tool, hash, approval reference, original expiry and server key remain immutable.
- Redis changes use atomic scripts and original expiry, never refresh/recreate missing records on reads/transitions.
- Positive nonacceptance requires a target-side durable rejection fence against delayed original dispatch; a missing target lookup is unknown.
- Reserve precedes dispatch; accepted evidence is durable before consume. Ambiguous/cancelled writes preserve denial. Accepted jobs remain recoverable after approval expiry.
- Default timeout ladder: send 2s, acceptance 5s, overall 25s, 2000ms polling. Each awaited callback/store/target operation is bounded by a shared monotonic budget.
- No production wiring, grant implementation duplication, provider export enablement, live provider requests, or desktop requirement.

## Review focus

Cross-process same-key races, lost write replies, late UNKNOWN after accepted, target identity/rejection-fence spoofing, and approval/state expiry during dispatch must fail closed without duplicate work.

## Test-first slices

1. Typed protocol and shared store (`relay/protocol.py`, `relay/lifecycle_store.py`, real-Redis `persistence/test_lifecycle_store.py`). Verify atomic single pair, exact scope/hash binding, immutable original TTL, missing/corrupt state denial, CAS transitions, immutable local job, and scoped job resolution. Run failing test, implement only its behavior, rerun, repeat; commit and checkpoint.
2. Coordinator and callbacks (`relay/lifecycle.py`, `execution_targets.py`, `persistence/test_invocation_lifecycle.py`). Verify reserve-before-send, acceptance-only consumption, ambiguity holds, positive fenced nonacceptance, original expiry, same-job recovery, cancellation, errors/redaction and bounded timeouts. Repeat vertical red/green steps; commit and checkpoint.
3. Separate-process protocol fixture and recovery tests. Persist deterministic target evidence locally; terminate/restart lifecycle processes and reconnect/restart target protocol process. Demonstrate one effect/original job and one Redis pair with independent Redis clients/processes. Commit and checkpoint.
4. Document contract and dormant integration boundary. Run complete control-plane tests with real stores, migrations, local-first/offline startup regressions, repository lint and full offline backend suite one heavy job at a time. Independent review, fix through reproducing regressions, verify final exact commit, and checkpoint. No remote writes until parent confirms authentication restoration.
