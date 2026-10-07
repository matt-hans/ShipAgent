# Dormant Execution Grant authority contract

Related: [issue 51](https://github.com/matt-hans/ShipAgent/issues/51), ADRs
[0003](../adr/0003-provider-confirmation-execution-safety.md),
[0005](../adr/0005-ephemeral-cloud-state-retention.md) and
[0008](../adr/0008-in-provider-execution-no-handoff.md).

**Enablement remains blocked.** This documents the dormant gate's caller
contract. No production grant authority/store, approval UI or non-status hosted
handler is enabled. Gate tests use explicit in-memory test doubles; they are not
real-store replay, fencing, expiry or recovery proof. Issue 51 stays open until
its documented design **and real-store tests** acceptance is met.

The current public input is
`execute_shipments(preview_id, approval_request_id)`. The opaque Approval Request
ID locates server-held authorization; it is not approval proof. Idempotency and
execution credentials never come from model arguments. Old examples in Plans 2
and 7 are superseded by the notices at their start.

## Ownership and transitions

`ExecutionGrantAuthority.reserve` verifies the exact live approved preview:
account, Provider Connection, Execution Target, immutable payload, policy,
currency and exact amount. Even a lower amount requires new preview/approval.
It atomically checks expiry and existing state and returns exclusive ownership.

The authority must associate each reservation with a server-owned fencing
identity. Consume/release/hold compare that identity atomically. Late callbacks
cannot release a new reservation or downgrade held/consumed state. These are
requirements for the missing store, not properties supplied by the Python
protocol or the test fake.

| Outcome | Required behavior |
|---|---|
| Valid reserve | Non-reusable before handler dispatch; concurrent reserve denies `grant_in_use` |
| Handler returns durable target acceptance | Attempt consume; return that same accepted result even if settlement fails |
| Proven pre-acceptance failure | Fenced release may allow retry only inside original expiry |
| Ambiguous handler failure or cancellation | Hold for reconciliation; never release |
| Consume failure | Best-effort hold within remaining settlement budget; never release |
| Failed/timed-out release or hold | Existing reserve remains non-reusable; local timeout proves no rollback |
| Reconciled acceptance | Record consumption and recover original job through Plan 2; never purchase twice |
| Unknown recovery evidence | Continue denial, without new dispatch or idempotency key |
| Expired/missing authorization | Deny; never reconstruct executable authorization from an approved request or ledger |

A handler return must mean the exact target durably accepted the idempotent
invocation, not merely that a socket send succeeded. Plan 2 owns that acceptance
and recovery evidence. `PreAcceptFailure` requires positive proof that nothing
could have been accepted; a bare send/ack timeout is insufficient. This stricter
safety obligation governs historical Plan 2 timeout examples.

## Bounded local settlement

`BoundRegistryTool` uses a five-second monotonic budget for each settlement
path. Consume plus failure-to-hold fallback shares **one absolute deadline**.
This is a local wait bound, not a target execution timeout or extension of the
approval lifetime. Plan 2 remains owner of the dispatch/accept/result ladder.

Caller cancellation is remembered while the operation gets the remaining
budget. Repeated cancellation never resets it. At the deadline the gate requests
local task cancellation and stops waiting; it does not await cancellation
cleanup indefinitely, run compensating release, or start a new hold after the
deadline. Outstanding operations are strongly referenced and eventual outcomes
are retrieved and logged without payloads. A child operation's self-cancellation
is a failed settlement, distinct from cancellation of the caller.

The future authority must use bounded I/O and cancellation-cooperative
coroutines. Python cannot stop an uncooperative coroutine or undo an uncertain
remote write. Fencing and idempotence remain essential even after the caller
returns. The gate's timer cannot establish those store guarantees.

Response provenance:

- A verified accepted handler result is preserved on settlement failure/timeout.
  It reports acceptance, not successful grant persistence or completed shipping
- An ambiguous handler error remains a generic sanitized provider error; replay
  stays denied as in-use or pending reconciliation
- A provable pre-accept failure remains a sanitized error; retry is possible
  only if release actually succeeded and the grant is still valid
- Caller cancellation propagates after settlement or its deadline, without
  claiming target work stopped
- In-use, consumed and reconciliation denials direct callers to check/recover
  existing work rather than obtain authorization for another purchase

Public result schemas are unchanged. Future enabled handlers must use Plan 2/7
provider-safe processing/recovery envelopes and original job references; logs
alone are not a user-facing recovery flow.

## Reserve interruption, expiry and reconciliation

Cancellation or a lost response after the atomic reserve write can strand an
exclusive reservation. Failure to deliver its object does not prove the write
failed. The authority may release it only under its original fence and proof
no dispatch/acceptance could occur; otherwise reconcile or expire to denial.
It must not suppress cancellation and return dispatchable ownership.

Keep original authorization expiry separate from ownership and target deadlines.
The authority must recheck original expiry and its reservation fence at consume.
If either is invalid, normal consume cannot renew/reuse the grant: route to
reconciliation. A target effect accepted before settlement remains accepted even
when grant expiry passes during the handler.

Reconciliation queries the exact target using the server-owned idempotency key.
Accepted evidence recovers the original job; positive nonacceptance evidence can
allow fenced release only before original expiry. Unreachable or ambiguous
evidence never means safe replay. No automatic second purchase or created-label
void is permitted.

Ordinary `reservation.release()` must not reopen a held reservation. A future
Plan 2-driven reconciliation transition may do so only on positive nonacceptance
evidence, atomically matching the held generation and original unexpired
authorization. That privileged reconciliation is distinct from a stale or late
gate release; its real-store implementation and proof remain prerequisites.

Redis Approval Requests/Execution Grants stay TTL-bound; deletion or expiry
denies the old reference. Neither an approved request nor a durable SQL ledger
can resurrect executable authorization. SQL stores only ADR 0005's permitted
hashed/redacted fields. Do not keep raw grants indefinitely as SQL tombstones or
extend retention to avoid designing lifecycle recovery.

## Separately bounded implementation prerequisites

The shared persistence primitives are documented in
[authorization-persistence.md](../control-plane/authorization-persistence.md).
Issue 66's bounded `InvocationLifecycleCoordinator`, `GrantCallbacks` and
`JobReferenceStore` seam is documented in
[invocation-recovery.md](../control-plane/invocation-recovery.md). It supplies
real-Redis acceptance/recovery evidence and a deterministic process target;
production grant authority, gate ownership adaptation, safe authorized preaccept
retry and hosted enablement remain issue 67 / issue 51 obligations. Its terminal
rejection evidence must not be mistaken for an implemented redispatch protocol.


Issue 51 explicitly excludes building the store. The following missing work
must be tracked separately, then used for issue 51's real-store verification:

1. **Plan 4 shared Redis lifetime and hashed ledger.** Implement the shared
   Approval Request/Execution Grant key/TTL APIs and authorization-ledger
   service/models/migrations consumed by Plan 7. Include required TTL sweeps,
   SQL retention/account deletion and explicit legal-hold behavior for introduced
   records. Approval/grant TTL is 900 seconds in Plan 4; invocation/job-reference
   retention is at most 24 hours. No raw PII, rows, labels, tracking, tokens,
   URLs or prompts belong in the ledger. Existing audit events are not this API
2. **Plan 2 acceptance/reconciliation seam.** Provide the shared
   `InvocationLifecycleCoordinator`, `GrantCallbacks`, `JobReferenceStore` and
   exact-target recovery using the actual relay/target prerequisites from
   Plan 1. Prove accepted-response loss and original-job recovery without a
   second effect. Do not release merely because the acceptance timer elapsed
3. **Plan 7 dormant real authority.** Consume those shared APIs to implement
   atomic fenced reserve/consume/release/hold, live preview validation, original
   expiry checks and stranded/accepted-outcome recovery. Tests may instantiate
   it explicitly; production wiring, approval UI and non-status exports remain
   disabled. Broader Plan 7 integration retains its Plans 2/4/6 dependency gate

These scopes must reuse the accepted lifecycle and ledger; no parallel state
machine, desktop job store or SQLite authority substitute is introduced here.
See the [parallel execution guide](../superpowers/plans/2026-06-30-openai-claude-connector-parallel-execution-guide.md)
and accepted Plans
[2](../superpowers/plans/2026-06-30-openai-claude-connector-02-invocation-lifecycle-relay-recovery.md),
[4](../superpowers/plans/2026-06-30-openai-claude-connector-04-ephemeral-retention-authorization-audit.md),
[7](../superpowers/plans/2026-06-30-openai-claude-connector-07-provider-execution-approval-flow.md).

## Real-store evidence required before enablement

Use synthetic references/hashes and disposable services, not live shipments.
Run separate clients/processes against the real selected Redis authority and
ledger/lifecycle dependencies. Verify one effect for races and replay, including
application/authority process restart while Redis retains state; lost replies
after successful writes; interruption before/after reserve commit; expiry and
fence loss during consume; failed release/hold; delayed stale callbacks; and
accepted-but-unsettled original-job reconciliation. Missing/expired store state
must deny rather than remint. Verify TTL/redaction/retention and account cleanup.

The deterministic target may be a fake; the **authority/store may not** be an
in-memory fake for this acceptance. Gate tests only show how the gate responds
to its injected authority's declared outcomes. No native Mac test substitutes
for these prerequisites, and this source work does not complete native release
qualification in issues 30/41.
