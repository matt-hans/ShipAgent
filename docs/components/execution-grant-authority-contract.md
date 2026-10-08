# Dormant Execution Grant authority contract

Related: [issue 51](https://github.com/matt-hans/ShipAgent/issues/51), ADRs
[0003](../adr/0003-provider-confirmation-execution-safety.md),
[0005](../adr/0005-ephemeral-cloud-state-retention.md) and
[0008](../adr/0008-in-provider-execution-no-handoff.md).

**Enablement remains blocked.** This documents the dormant gate's caller
contract. No production grant authority/store, approval UI or non-status hosted
handler is enabled. Gate unit tests use explicit in-memory test doubles;
separate integration tests inject the real Redis authority and PostgreSQL ledger,
including independent authority and deterministic target processes. The
[issue 51 qualification record](../control-plane/execution-grant-qualification.md)
maps all four prerequisites to their design and real-store assertions on pinned
main. That bounded prerequisite qualification does not enable hosted mutations.

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
implemented by the dormant Redis authority; the Python protocol and in-memory
gate fake alone do not establish those guarantees.

| Outcome | Required behavior |
|---|---|
| Valid reserve | Non-reusable before handler dispatch; concurrent reserve denies `grant_in_use` |
| Handler returns durable target acceptance | Attempt consume; return that same accepted result even if settlement fails |
| Proven pre-acceptance failure | Fenced release may allow retry only inside original expiry |
| Ambiguous handler failure or cancellation | Hold for reconciliation; never release |
| Consume failure | Best-effort hold within remaining settlement budget; never release |
| Failed/timed-out release or hold | Never infer rollback or reuse; only a positive-proof release that actually committed can reopen state |
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

The dormant authority uses a two-second bounded I/O budget (at most five
seconds when configured) and cancellation-cooperative operations. Python cannot stop an uncooperative coroutine or undo an uncertain
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

Ordinary `reservation.release()` cannot reopen held or dispatch-claimed state.
Plan 2-driven privileged reconciliation requires positive nonacceptance evidence,
atomically matches the held owner/generation and original unexpired authorization,
and advances only the permitted next attempt. This is distinct from a stale or
late gate release; lease expiry alone never authorizes reuse.

Redis Approval Requests/Execution Grants stay TTL-bound; deletion or expiry
denies the old reference. Neither an approved request nor a durable SQL ledger
can resurrect executable authorization. SQL stores only ADR 0005's permitted
hashed/redacted fields. Do not keep raw grants indefinitely as SQL tombstones or
extend retention to avoid designing lifecycle recovery.

## Implemented dormant prerequisites and remaining gate

Plan 4's shared lifetime/hashed-ledger APIs are documented in
[authorization-persistence.md](../control-plane/authorization-persistence.md).
Plan 2's sole lifecycle/job-reference store and explicit safe attempt-generation
seam are documented in
[invocation-recovery.md](../control-plane/invocation-recovery.md).
Issue 67's real Redis authority, PostgreSQL commit-before-enable ordering,
server-only gate ownership token, dispatch claim and evidence-only expired
acceptance recovery are documented in
[redis-grant-authority.md](../control-plane/redis-grant-authority.md).

The dormant authority reuses those APIs; there is no parallel invocation/job
store or SQL executable grant. Explicit next-attempt dispatch preserves purchase
key, logical invocation, original job and all original deadlines while permanent
target rejection fences block delayed older attempts. Repeated ordinary invoke
never resets or silently redispatches.

The [issue 51 evidence review](../control-plane/execution-grant-qualification.md)
qualifies these dormant prerequisites separately from production enablement.
Production post-gesture approval, authenticated exact-target/live-preview adapters,
provider-safe job/status projection, coordinated revoke/retention startup and
production Redis persistence/failover policy are not enabled by this slice.
Broader Plan 7 integration retains its accepted Plans 2/4/6 dependency gate.

## Real-store qualification boundary

The qualification uses synthetic references/hashes and disposable services, not
live shipments. Separate clients/processes use the real Redis authority and
ledger/lifecycle dependencies. The mapped tests verify one effect for races and
replay, including application/authority process restart while Redis retains state; lost replies
after successful writes; interruption before/after reserve commit; expiry and
fence loss during consume; failed release/hold; delayed stale callbacks; and
accepted-but-unsettled original-job reconciliation. Missing/expired store state
must deny rather than remint. TTL/redaction/retention and account cleanup are
covered by the shared persistence suites. See the qualification record for exact
source identities, commands, counts, skips and service versions.

The deterministic target may be a fake; the **authority/store may not** be an
in-memory fake for this acceptance. In-memory gate tests alone only show responses to a fake authority. The separate
real-store tests explicitly inject the real authority into a test-only gate and
exercise separate authority/target processes; default wiring remains unchanged.
Redis remains running across those application/authority restarts. Redis AOF,
power-loss and failover durability are not qualified. No native Mac test substitutes
for these prerequisites, and this source work does not complete native release
qualification in issues 30/41.
