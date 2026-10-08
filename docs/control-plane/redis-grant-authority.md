# Dormant Redis Execution Grant authority (issue 67)

`RedisExecutionGrantAuthority` is an explicitly constructed implementation of the
ADR 0003/0008 contract. It is **not injected into either application**, and no
non-status handler/export, approval surface or deployment is enabled. Local API,
CLI, desktop startup and shipping require no Redis, PostgreSQL, Auth0 or hosted
grant. The supplied target and live-preview adapter are trusted server-side
interfaces; this module does not implement production approval/authentication.

## Required inputs and stored data

A `LiveApprovedPreview` adapter resolves the exact account/connection/target and
returns `ApprovedPurchase`: canonical preview reference, tool pair, policy, exact
amount/currency, preview hash and target argument hash. Full preview detail,
shipping rows, carrier data, labels, tokens and URLs stay outside this record.
Every field must match during reserve, including a lower amount. The adapter
must fetch/validate current immutable data and authenticate target provenance.

The internal post-gesture `issue_approved` API generates a fresh Approval Request
ID and random server purchase key. It cannot accept an old ID/key to restore
lost state. The caller is responsible for an explicit authenticated gesture;
there is no public route to this dormant API. SQL validates live account subject,
Provider Connection ownership, client/surface and active status.

Plan 4 `AuthorizationStateStore` owns the same approval/grant namespaces, strict
serialization, exact-value CAS and original **900-second maximum** TTL. Its
optional frozen `GrantRecord` holds immutable purchase metadata, status, monotonic
owner fence, random hidden owner token, attempt generation, dispatch-claim bit
and lease deadline. Neither missing nor TTL-less/corrupt state is executable.

## Publication and deletion ordering

Executable state is never created with SET NX:

1. Write only inert pending metadata with fresh random references.
2. Commit the required permitted hashed ledger event in PostgreSQL.
3. Reacquire account/connection row locks and recheck active ownership.
4. CAS the existing exact pending/approved/reserved record while locks are held.

Account deletion uses the same account lock and removes Redis before SQL rows.
A delayed enabling CAS after cleanup finds no key and cannot recreate one. A
late initial pending CREATE is inert and expires normally; it cannot activate
without the fresh SQL check. SQL commit, validation, cancellation or uncertain
Redis response fails closed. Evidence-only ledger rows may outlive an uncertain
publication; they are never replayed into executable state.

Terminal authority `revoke` cannot be reversed by late owner callbacks. SQL-only
Provider Connection revocation leaves existing ephemeral metadata but prevents
all new enabling operations and dispatch-claim validation. Production revocation
must coordinate terminal invalidation with connection/account changes; it must
not bypass these locks/cleanup semantics or treat an old context as current.

## Exclusive ownership and bounded operations

Reserve atomically changes approved to reserved, increments the fence and installs
one random token before returning dispatchable ownership. Concurrent processes
receive `grant_in_use`, `grant_consumed` or reconciliation denial. Reserve response
loss strands non-reusable state; it is quarantined until original expiry or exact
lifecycle reconciliation, never automatically released merely because a lease
or local timer elapsed.

Default authority I/O budget is **2 seconds**, configurable within **5 seconds**.
The default ownership lease is **30 seconds**, capped at original authorization
expiry. PostgreSQL lock/statement waits are bounded at 1500 ms inside transactions.
These are local wait bounds, not distributed rollback or lease renewal. The
shared bounded-operation helper retains/observes late tasks and propagates caller
cancellation. A late operation cannot continue into dispatch after its caller
has stopped waiting. Redis CAS uses server time and never extends TTL.

Ordinary release is possible only before a lifecycle dispatch claim and within
the original owner lease/authorization. Once callbacks have claimed dispatch,
only durable exact-attempt nonacceptance evidence may release. Ordinary consume
requires persisted exact acceptance and a live lease. Held/consumed/revoked,
missing/expired or another owner's state cannot be downgraded by stale callbacks.

## Gate and shared lifecycle bridge

A real `ExecutionGrantBinding` carries a repr-hidden server-only reservation token
and repr-hidden purchase key. Public tool arguments remain only preview and
Approval Request references. The gate passes the same immutable binding to its
handler; `callbacks_for_binding` requires that exact token and purchase and never
adopts the latest owner. `invoke_bound` is a dormant handler helper that shares
this one reservation with `InvocationLifecycleCoordinator`; no second reserve is
performed. Only persisted acceptance can return success through the gate. A
positive target rejection raises `PreAcceptFailure`; unknown outcomes raise a
closed ambiguous failure and remain held. Result projection/public schema wiring
remains the enabling caller's separate responsibility.

Plan 2 owns the sole lifecycle and job reference. Its identity carries optional
paired scope/preview hashes (required by this real authority) and an immutable
attempt generation. Durable acceptance records the exact target/key/generation
and original job before grant consumption. Privileged callbacks validate that
same persisted record; positive rejection may release a held owner after its
lease ended, but only inside original authorization expiry. It advances the
allowed generation and clears dispatch claim; it does not renew the old lease.

An explicit retry advances only a positively fenced rejected attempt. The target
must permanently reject delayed old-generation sends while allowing a newer
approved generation. The purchase key, logical invocation ID, job reference,
purchase binding, original retention/authorization and initial dispatch deadline
stay fixed. Normal repeated invoke never resets or silently dispatches again.
The conservative original dispatch window may expire before approval expiry;
then retry safely denies without extending either deadline.

## Restart, missing state and expired acceptance

`recovery_callbacks(context, job_ref)` pins the existing scoped lifecycle identity
and can never reserve or dispatch. It uses the original exact target for status.
Accepted work is recoverable after grant expiry; an evidence-only SQL lookup
matches account, connection, Approval Request, key/target/scope/preview hashes and
records only permitted consumed evidence. Consumption evidence is idempotent
across recovery processes under the existing account lock. This SQL path never
returns a key, creates a grant, extends TTL or authorizes a second effect.

If a live exact grant owner remains, privileged reconciliation can settle it.
If that state has disappeared or been revoked, accepted truth may still be
recorded while authorization remains absent/terminal. Unknown evidence remains
non-reusable. Account deletion/revocation can prevent authenticated recovery;
there is no account or ledger reconstruction from target data.

## Acceptance and remaining issue 51 gate

The tests instantiate the real authority with disposable Redis/PostgreSQL and
synthetic deterministic target evidence. They include separate authority
processes and target/application restart, atomic races, accepted-response loss,
abrupt termination before consume, real post-write reply loss, cancellation,
lease/original-expiry boundaries, deletion/revocation, explicit retry, stale
owner callbacks and hash/redaction invariants. The target's test-only SQLite
journal records target acceptance, never cloud grants or a competing job store.
See `authorization-persistence.md` for pinned disposable service setup.

```sh
SHIPAGENT_TEST_SERVICE_ROOT=/path/to/test-services/extracted \
  .venv/bin/python -m pytest tests/control_plane/persistence -q
```

Issue 51 still requires review of the actual final-head evidence and production
integration obligations before enabling: authenticated exact-target/live-preview
and post-gesture adapters, supported provider result/status projection, coordinated
revocation/retention startup, production Redis persistence/recovery policy and
the broader Plans 2/4/6/7 dependency gate. Disposable process restart tests retain
the Redis service; they do not claim power-loss/failover or Redis AOF qualification.
No native release qualification, live carrier/model API, approval UI, deployment
or real shipping is exercised or enabled by this work.
