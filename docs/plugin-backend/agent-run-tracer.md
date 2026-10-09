# Dormant source-free agent-run MCP tracer

Milestone [#77](https://github.com/matt-hans/ShipAgent/issues/77) remains open.
This is a local, synthetic integration of the approved
[authority architecture](architecture-authority.md), using the
[shared source-free runtime](source-free-runtime.md). Production `/mcp` still
exports only status. No connector, deployment, enrollment, paid shipping or
live-provider readiness is claimed.

## Implemented path

A real loopback HTTP FastMCP client initializes and lists four test-enabled
canonical contracts. `submit_shipagent_task` requires `shipagent.preview` and
truthfully describes stateful model work (`readOnlyHint=false`). It accepts a
bounded source-free task plus an idempotency key; it cannot accept source paths,
remote URLs, approval flags or shipping execution arguments.
`read_shipagent_run` requires `shipagent.status` and returns only a closed state
projection. None of these lifecycle descriptors is enabled in production provider exports.

The existing hosted gate constructs a trusted `TargetToolRequest` carrying the
account and provider-connection identity separately from model arguments. An
account-dedicated `AgentRunExecutionTarget` calls `AgentRunService`. The service
commits acceptance in its target-local SQLite store before replying with opaque
Conversation and Agent Run References, revision 1, original expiry, state,
closed outcome code and polling guidance. No inner model text, tool events,
private history or exception text crosses this result boundary.

The worker invokes canonical `process_message` with an immutable source-free
profile. It owns accepted user ingress, exact turn identity, session cleanup,
private persistence and a separate provider instance per conversation. No local
API database, ambient source, settings or audit sink participates. Empty tool
admission plus runtime policy blocks invented shipping and setup calls before
dispatch. A positive completed-stream marker, bound to the accepted turn, is
required for success; partial text is not evidence of completion. Every model
stream must finish positively before its tool batch can dispatch or another
model turn can begin.

Transport EOF alone is never terminal proof: OpenAI requires a
`response.completed` payload with completed status and a valid output list;
Gemini requires the selected candidate's `STOP`, retained across metadata-only
trailing chunks. Later conflicting content or finish reasons fail closed.
Anthropic already requires `message_stop` with every content block closed.
Scripted real-SDK/SSE regressions cover truncated text, complete tool blocks and
partial tool arguments without the enclosing terminal marker. These guarantees
concern stream integrity, not semantic completeness of the answer; Anthropic's
existing terminal `max_tokens` metadata behavior is unchanged.

## Durable cancellation

The dormant `cancel_shipagent_run` contract requires `shipagent.preview`; a
status-only caller cannot change accepted work. It takes only an opaque Agent
Run Reference, uses the trusted account/connection/target boundary, and is
stateful with an idempotent call policy. Submit/cancel descriptors disclose
possible configured-model reach through `openWorldHint=true`; this hint grants
no new authority or production admission.

Cancellation commits a generation-fenced `cancelled` terminal record before
replying or signaling the exact owned run task. Queued cancellation prevents its
first model dispatch. Running cancellation fences later model/tool dispatch and
publication; it does not refund charges, undo accepted effects, or prove an
already-in-flight provider request was aborted. Repeated cancellation, lost
caller replies and reopen preserve the original reference, request key and
expiry. Already completed, failed or cancelled records and their private
history are unchanged. Cancelling an older run cannot interrupt a newer one.

Each coordinator owns its run and cleanup tasks explicitly. A one-second
trusted cleanup budget bounds waiting, with an independent outer model deadline
so cancellation-resistant cleanup cannot silently extend admission. If owned
work remains live, the service latches unavailable, retains its original task
references and lease, and denies new acceptance/claims. Bounded `close()` then
reports failure rather than pretending to terminate that work; a later close
after actual cleanup can release ownership. Python cannot forcibly kill an
arbitrary cancellation-resistant in-process provider. This is safe fencing and
truthful resource ownership, not an arbitrary-provider termination guarantee.

Real loopback MCP tests cover queued/running cancel, duplicate/reopen recovery,
terminal immutability, minimal scope and cross-account/connection denial. They
also cover invalidating the exact current clarification follow-up while keeping
its terminal row unchanged. Shipping approval follow-ups are not implemented;
their cancellation/invalidation remains a separate approval-lifecycle gate.

## Dormant clarification and continuation

`continue_shipagent_task` requires preview scope and accepts only the owning
Conversation Reference, exact current waiting Agent Run Reference, expected
**conversation** revision, bounded follow-up text and request key. It is stateful
model work with an idempotent call policy, not shipment approval. A trusted
service callback supplies a bounded opaque connection epoch; neither MCP inputs
nor model output may choose one. The current callback result is rechecked after
storage-lock waits and before acceptance, idempotent recovery, dispatch and
publication. A missing, changed or unavailable authority fails closed. This
injection is a synthetic interface, not an implemented production relink or
reauthorization system.

Only an epoch-bound run gets the trusted closed-control prompt. A successful
clarification is exactly one complete JSON object containing only
`clarification_code`, selected from `shipping_goal`, `package_scope` or
`service_preference`. Trusted templates supply the public question; arbitrary
inner text never becomes a public question. Duplicate keys, extra fields,
malformed objects, unknown codes, multiple text blocks and missing genuine
terminal proof cannot authorize follow-up. Validation occurs on raw complete
text events before privacy projection can normalize JSON. The 256-character
control limit is distinct from the shared runtime's 65,536-character accepted
plain-text-block ceiling; neither bounds an already-materialized SDK event.

The completed waiting run keeps its immutable reference, accepted revision,
outcome and private history. Its public `conversation_revision` and
`conversation_state` describe current follow-up reality separately. The fixed
clarification object is present only while that exact run/revision still owns
live waiting input. Accepting a continuation atomically consumes that follow-up,
creates a new run at the next revision and retains the original expiry. An
identical retry recovers the accepted successor even though the original
revision is now stale; a changed request, other waiting run or foreign owner
cannot start another model request. A conversation is bounded to eight accepted
runs and the existing account/connection admission quotas.

Cancelling a quiescent waiting turn invalidates only its current follow-up;
it does not rewrite the old terminal row or transcript. Cancelling an old run
after a successor exists cannot cancel that successor. Retrying, reading or
reopening completed work does not construct another provider. A fresh shared
runtime receives only committed prior private history under its existing
30-message/16,000-serialized-character provider replay limits; these are not a
durable-storage byte cap. Dispatched work interrupted by process death is never
automatically replayed.

Version-one stores are upgraded explicitly and transactionally only during
service startup under the exclusive coordinator lease. Ordinary store open/read
does not migrate. The migration preserves old references, input hashes,
idempotency keys, histories and original expiry as epoch-unbound records; it
never silently grants them clarification/continuation authority. SQL-failure
and process-death tests cover atomic rollback and recovery. Physical storage
power loss and backup rollback remain separate qualification gates.

## Acceptance and recovery invariants

- Each store is bound to one account and exact target. Reads and idempotency keys
  are provider-connection scoped. Reusing a key with different input fails;
  identical retries recover the original record without another model run or
  changed expiry. Expired references/keys never create replacement work.
- Acceptance is transactional and checks the current coordinator generation.
  The synthetic bounds are 8,192 task characters, four pending runs per
  connection, sixteen per account, twenty accepted runs per connection/hour,
  sixty per account/hour, and 10,000 retained records. Completed runs still count
  toward the hourly budget. Repeated reads and identical accepted submits still
  consume their normal HTTP rate budget but bypass identical-call loop detection.
  Existing unrelated tool loop protection is unchanged.
- A single Linux file lease owns the coordinator. Opening or reading a store
  does not recover or drain it. Explicit service startup advances its durable
  generation and reports previously running turns as failed/interrupted.
  Queued, undispatched work may run; previously dispatched work is never
  automatically replayed. Claims and terminal writes are generation-fenced.
- Lease loss or any failed activity check is latched for the accepted turn and
  fences subsequent model dispatch as well as publication. A completion-write
  failure still cleans the owned runtime and makes the worker unavailable for
  new submissions and nonterminal reads. Completed records remain readable;
  no unhealthy worker advertises continuing progress. Recovery retains the
  original acceptance identity.
- Each run has at most three provider turns and a 30-second model deadline
  (trusted test/operator configuration may choose a positive deadline up to
  120 seconds). Timeout is reported as a closed `model_timeout` outcome.
  These bounds are not a production token or spending authorization policy.

## Local storage profile and qualification boundary

`AgentRunStore(..., create=True)` is an explicit initialization operation.
Normal reopen and every later connection require the existing, original file;
missing or replaced storage is not silently recreated. A pre-provisioned,
owned 0700 directory and owned 0600 single-link files are required. Symlinked
paths and broad permissions fail closed; code does not change an operator's
permissions or provision encryption. SQLite opens in existing-file mode,
validates schema/account/target identity before journal-mode changes, checks
WAL plus synchronous FULL, and
syncs the containing directory on initialization. The lease uses non-following
open plus exclusive `flock`. Filesystem identity checks are defense in depth,
not protection against a malicious operator sharing the process's OS identity.

Tests kill actual child processes without orderly cleanup after acceptance,
after model dispatch and after committed completion. Reopen preserves the
same references and expiry; the dispatched case is interrupted without a second
model call. This is process-crash evidence on the test filesystem, not physical
power-loss, network-filesystem, backup rollback or encrypted-volume qualification.
The production storage/encryption/backup and restore procedure needs its later
explicit setup gate. Retention cleanup is not implemented: admission fails at
its retained-record bound rather than forgetting old keys and resurrecting work.

## Still required

Useful source-backed answers and previews, authenticated ordered event cursors,
production provider revocation/relink epochs, authenticated relay ownership
envelopes, operational headless enrollment and secret storage, source/settings/
gateway isolation, token/spending budgets and actual ChatGPT/Claude client tests
remain open. The local callback-bound clarification/continuation path does not
close those authority or deployment gates. OAuth/resource alignment and bounded
status polling are implemented locally, with actual-client qualification still
in milestone #78. No pending shipment mutation or approval path is enabled.
