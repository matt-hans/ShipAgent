# Dormant invocation acceptance and recovery (issue 66)

This is the bounded acceptance/recovery prerequisite for issues 67 and 51. It
implements neither a real Execution Grant authority nor hosted handler wiring,
approval UI, provider exports, shipment execution, deployment, or native desktop
qualification. Local API, CLI, desktop startup and shipping acquire no Redis,
PostgreSQL, Auth0 or hosted-grant requirement.

## Current integration seams

- `relay/protocol.py`: `InvocationIdentity` and `TargetAcceptanceEvidence` are
  frozen, allowlisted server-side types. The identity binds account, Provider
  Connection, exact internal Execution Target, Approval Request, tool, immutable
  argument hash, server-owned idempotency key and original authorization expiry.
  These are **not** public tool inputs. The public execute input remains opaque
  `approval_request_id` plus `preview_id`; the model supplies no key or grant.
- `execution_targets.py`: optional `DurableExecutionTarget` separates send-only
  `dispatch_invocation` from read-only `get_acceptance`. Existing
  `ExecutionTarget.invoke`, `RelayInvocationBroker`, status-only relay routing and
  desktop dispatch are unchanged and do **not** implicitly implement durability.
  A future adapter owns authenticated exact-target selection, relay session and
  increasing sequence. It uses the actual `RelayInvocationEnvelope.deadline_at`
  datetime and `relay_invocation_input_hash(tool_name, arguments)`, preserving the
  supplied invocation and idempotency IDs. Current internal relay target IDs are
  `relay:relay_device_<32hex>`, distinct from public `sa_device_*` projections.
- `relay/lifecycle_store.py`: `InvocationLifecycleStore` owns the sole lifecycle;
  `JobReferenceStore.resolve(job_ref, account_id, provider_connection_id)` returns
  that same immutable record. There is no separate grant-owned invocation state
  machine or job-state copy.
- `relay/lifecycle.py`: `InvocationLifecycleCoordinator.invoke(...)` sends at
  most once for newly created metadata and only after `GrantCallbacks.reserve`
  succeeds. Repeated invocations and `reconcile(...)` resolve existing work.
  Target failures, unknown lookup and lost acknowledgements never trigger
  redispatch or a new purchase key.

### Authority and gate integration is still disabled

`GrantCallbacks` is mandatory and not implemented by a production authority in
this slice. It accepts an immutable invocation record in `reserve`,
`consume_on_accept`, `release`, and `hold_for_reconciliation`. The future
implementation must validate live bindings, commit its required SQL ledger,
atomically reserve non-reusably, preserve the original reservation fence, and
make settlement idempotent. Redis lifecycle metadata is not purchase authority.

`consume_on_accept` is ordinary fenced consumption inside the original expiry;
it is attempted again on recovery, including a process crash after evidence
persistence but before settlement. It must recheck expiry and ownership itself.
After expiry the coordinator only calls `hold_for_reconciliation`; it may still
return the original accepted job, without renewing authorization. Issue 67 must
implement privileged expired-acceptance reconciliation/evidence recording.

`release` is privileged evidence-backed reconciliation under the original held
reservation generation. It must not be implemented as an unchecked alias for an
ordinary `ExecutionGrantReservation.release()`, which cannot reopen held state.
Delayed consume, release and hold operations must never downgrade consumed state
or affect replacement ownership. Callback failures do not prove rollback.

The current `BoundRegistryTool` separately reserves and consumes on a successful
handler return. **Do not register the coordinator directly as a confirming
handler:** its pending/unavailable result envelopes do not mean acceptance, and
its callbacks must not create an independent second reservation. Issue 67/Plan 7
must reconcile gate ownership and translate outcomes before any handler wiring.
Only verified accepted outcomes may return through the gate's accepted path;
positive preaccept evidence and unknown outcomes retain their distinct gate
semantics.

## Durable evidence and immutable storage

`sa:invocation:` and `sa:jobref:` are the existing shared namespaces. The invocation
ID derives from the server-owned random idempotency key. The opaque job reference
uses the existing `sa_job_<32hex>` grammar and a domain-separated SHA-256 digest
of that same key, truncated to the canonical 128-bit ID width. Neither reference
contains argument data. This stable pairing prevents partial state loss from
minting a replacement job reference. Active public schemas still use `job_id`;
these dormant `job_ref` envelopes are not newly exposed or silently substituted
into the existing public registry or provider projections.

Pair creation is one atomic Redis script. Exact-value CAS validates both pair
members and uses `KEEPTTL`; reads, replay, evidence updates and recovery never
refresh the original maximum **86400-second** expiry. Missing, malformed,
TTL-less, extended-lifetime, cross-account/connection, changed-target/hash or
mismatched pointer state denies. Partial pair loss cannot create a replacement
pair. If **both** records were lost, metadata creation alone cannot recognize an
old purchase; the required authority reserve must deny consumed, lost or expired
authorization before any dispatch. Recovery APIs never create either record.
SQL history is never read to reconstruct executable state.

Arguments are deep-snapshotted and hashed before suspension and remain transit
only. Redis stores only bounded references, the server idempotency material,
SHA-256 hash, timestamps, lifecycle state/revision and target-owned evidence.
The pointer contains no local job copy. Acceptance evidence commits local job
identity and state atomically. A stale timeout/unknown CAS cannot overwrite
accepted/recovered truth; a later different local job or proof is denied.
Only opaque job references appear in processing envelopes. Raw arguments,
carrier replies, local job IDs, idempotency keys and dependency exception text
never appear in provider envelopes or coordinator logging.

A trusted target adapter must return durable, exact-identity evidence:

- `accepted`: original local job reference, proof hash, and acceptance timestamp
  strictly before original authorization expiry
- `not_accepted`: a positive durable rejection fence proving that even a delayed
  original dispatch can no longer accept. A missing lookup is not this proof
- `unknown`: no acceptance claim, no release eligibility

The target adapter owns authenticated provenance; a Pydantic object by itself is
not cryptographic proof. Target acceptance remains true if consuming the grant
fails. Recovery queries the exact original target and key, never an active
replacement target or a newly generated key.

### Explicit retry boundary

This slice returns positive rejection evidence and invokes the release callback,
but its rejected invocation remains terminal. **Release does not make this
coordinator redispatchable.** Repeating it returns the same terminal rejection;
there is no automatic retry, record deletion, replacement purchase key or expiry
extension. This conservative restriction is intentional for dormant issue 66.

ADR 0003's authorized preaccept retry inside the original expiry remains an
explicit **issue 67 / issue 51 enablement requirement**. That integration must
supply a safe fenced attempt-generation protocol, preserving purchase identity,
job reference and original deadlines while excluding delayed earlier attempts.
The current target rejection fence covers the original logical invocation. This
slice does not claim complete Plan 2 retry/desktop/async-status integration.

## Bounded operations and interruption

The default ladder is **2 seconds send**, **5 seconds acceptance query**, and
**25 seconds total** from operation start, not 2+5+25. Store operations, reserve,
consume, release, hold and recovery share that monotonic total budget. Target
acceptance deadlines are also capped by original authorization expiry. Polling
defaults to **2000 milliseconds**.

Local timeout requests cancellation without awaiting uncooperative cleanup
forever. Outstanding operation tasks are strongly retained and their eventual
results retrieved without payload logging. They are individual I/O/callback
operations, not detached dispatch workflows. A late reserve completion cannot
continue into a send. Caller cancellation propagates after best-effort hold
within the **remaining** original budget; repeated cancellation never resets it.
Python cannot undo a remote write or terminate a hostile coroutine. Target
idempotence, bounded dependency I/O and authority fencing remain mandatory.

## Reproducible verification

Use the checksum-pinned disposable service setup documented in
[authorization-persistence.md](authorization-persistence.md). Fixtures use owned
loopback-only processes and synthetic records, never ambient service URLs.

```sh
python scripts/setup_control_plane_test_services.py --root /path/to/test-services
export SHIPAGENT_TEST_SERVICE_ROOT=/path/to/test-services/extracted
.venv/bin/python -m pytest tests/control_plane/persistence/test_lifecycle_store.py \
  tests/control_plane/persistence/test_invocation_lifecycle.py \
  tests/control_plane/persistence/test_lifecycle_process_recovery.py -q
```

The deterministic TCP target runs in a separate process, validates the actual
relay envelope session/hash/deadline/sequence contract and commits acceptance
plus one synthetic effect before replying. Its test-only SQLite journal is
**target-owned evidence**, not a Redis lifecycle or grant authority substitute.
It survives target restart. Separate lifecycle client processes construct fresh
Redis clients; tests cover response loss, reconnect, application restart, abrupt
kill after acceptance before consumption, cross-process races and delayed sends
following a rejection fence. Tests also inject failures **after real Redis Lua
writes complete**, so a lost reply is not confused with a rolled-back write.
Grant callbacks remain explicit test doubles; these results do not qualify the
real authority/SQL fencing requirements in issue 67 or close issue 51.
