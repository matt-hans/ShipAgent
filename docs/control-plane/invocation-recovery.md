# Dormant invocation acceptance and recovery (issue 66)

This is the bounded acceptance/recovery prerequisite for issues 67 and 51. It
does not itself implement an Execution Grant authority or hosted handler wiring,
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

### Dormant authority and gate integration

Issue 67 provides an explicitly constructed real Redis authority and a single-
owner callback adapter; see [redis-grant-authority.md](redis-grant-authority.md).
`GrantCallbacks` remains mandatory. A hidden server-only token in the exact gate
binding pins its original reservation, so callbacks do not independently reserve
or opportunistically adopt a later owner. `invoke_bound` returns through the
accepted handler path only after exact persisted acceptance; pending/unavailable
results remain ambiguous failures. Nothing is injected into a default app.

Ordinary consumption is lease/expiry-bound. Positive persisted evidence may
privileged-settle the same current owner within original authorization expiry;
expired accepted work records hashed SQL evidence without restoring a grant.
Ordinary release cannot reopen held or dispatch-claimed state. Privileged release
requires a durable exact-attempt rejection fence and is idempotent; it permits a
new generation only inside original expiry. Late callbacks cannot affect a new
owner, and failed writes never prove rollback.

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

### Explicit safe retry boundary

`InvocationIdentity.attempt_generation` starts at zero and increases only through
explicit `InvocationLifecycleCoordinator.reattempt(target, rejected_record,
arguments, grant_callbacks)`. The method validates the current exact persisted
rejection proof, snapshots arguments, validates the next candidate with the same
newly authorized reservation, then performs `begin_reattempt` exact CAS. After
SENT it validates that owner again before dispatch. Lost reservation/CAS replies
or interruption hold the candidate and never implicitly resume a queued attempt.

Purchase key, logical invocation ID, original job reference, immutable purchase
fields and retention/authorization deadlines do not change. The initial invoke
persists `dispatch_deadline_at`, the earlier of original authorization expiry and
the first call's total budget. Retry keeps this conservative initial window and
rechecks it after asynchronous callbacks; accepted evidence must precede it.
Existing serialized dormant records lacking this required deadline fail closed.

The existing non-durable `RelayInvocationBroker` omits the new generation field
from its legacy wire format, preserving older desktops' strict status decoder.
Explicit durable-target envelopes retain their generation; default status traffic
does not silently opt into the new protocol.

The target authenticates generation in envelope, query and proof, durably rejects
old attempts forever, requires proof-backed sequencing for new generations, and
keeps one accepted effect per purchase key. A retry never deletes/reset records,
mints a new key or extends deadlines. Ordinary invoke with a stale identity
denies; reconcile by original job reference reads the current generation. The
optional paired `purchase_scope_hash`/`preview_hash` and target-fingerprint identity
fields are immutable hashed evidence (all required by the real authority), never
new public inputs. A target ID alone is not a key/fingerprint binding.

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
The issue 66 suites still use explicit callback test doubles. Separate issue 67
`test_grant_*` suites exercise the real authority and PostgreSQL ledger with
independent processes. Neither test group enables hosted execution or closes
issue 51 without its separate evidence review.
