# Dormant fenced grant authority

## Scope and sources

Implement issue 67 under ADRs 0003/0005/0008, the accepted connector design,
Plan 7 and `docs/components/execution-grant-authority-contract.md`. The real
Redis authority is explicitly constructed by disposable-service tests. No app
injection, new provider exports, approval UI, shipping effects, live API calls,
or local Redis/PostgreSQL/Auth0 requirement is introduced. Issue 51 remains a
separate enablement evidence review.

## Authority and persistence

Extend the shared Plan 4 `AuthorizationState` record with a frozen, allowlisted
grant payload. It contains only server-owned opaque references, immutable
purchase hashes, canonical price, server idempotency material, original expiry,
state and owner/attempt fences. Reuse `AuthorizationStateStore` CAS/TTL APIs;
never create a second namespace or SQL executable authority.

The required live-preview resolver returns a strict immutable purchase value.
Reserve compares exact account, connection, target, preview, policy, tool pair,
argument hash, preview hash, amount and currency, including lower prices.
Every enabling transition commits the existing hashed ledger first and checks
active SQL ownership under fresh account/connection locks. Missing state denies.

Issuance creates a fresh server-generated request ID/key as inert pending state.
Only existing-key CAS can activate it after committed audit and fresh active
ownership checks. Account deletion shares the SQL account lock and removes Redis
before deleting SQL. Delayed pending creation is inert; delayed activation after
cleanup cannot recreate a key. Revocation is terminal and cannot be reversed by
stale callbacks. SQL-only connection revocation denies all new enabling steps.

Reserve atomically transitions approved to reserved with an increasing fence and
random owner. The original expiry never changes. A short ownership lease bounds
ordinary settlement but never independently makes state reusable. Exact-value CAS
and atomic deadline checks fence consume/release/hold and preserve key TTL.
Interrupted or lost writes leave non-reusable state. All authority waits are
bounded, cancellation is propagated, and late completion cannot dispatch.

## Lifecycle integration and retry

One reservation supplies the `GrantCallbacks` adapter. It checks exact Plan 2
identity and attempt and never acquires a second reservation. Accepted evidence
must be read from the shared lifecycle; successful send alone is not acceptance.
Reconciliation returns the original job and records allowed evidence after grant
expiry without restoring or extending authorization. Ordinary stale release may
not reopen held state. Privileged release requires durable target rejection
fencing for the exact current attempt inside the original expiry.

An explicit shared lifecycle retry operation may advance only a positively
rejected attempt. Purchase idempotency, invocation ID, job reference, purchase
binding and original deadlines stay unchanged. An increasing attempt generation
separates later dispatch from delayed old attempts and stale callbacks. No
implicit retry, deletion/reset, replacement purchase key or automatic void exists.

## Verification

Use real disposable Redis and PostgreSQL plus the existing deterministic separate
process target. Cover races, process/application/target restart, lost replies
before/after writes, reserve cancellation, bounded settlement, stale callbacks,
expiry/lease loss, account deletion/revocation, exact live drift, accepted-job
recovery, positive-proof retry, immutable TTL and ledger redaction. Run targeted
then guarded broad tests under the shared resource lease. Synthetic fixtures
only. Default status-only/local operation invariants remain tested.
