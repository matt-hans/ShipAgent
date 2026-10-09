# Authenticated synthetic Agent Run composition

Date: 2026-10-09. Source baseline:
`551f257a2f66ac15195e5d25c4b64d101a3c8508`.

Status: proposed architectural slice for independent review. No implementation
has started. This advances [#77](https://github.com/matt-hans/ShipAgent/issues/77)
and [#78](https://github.com/matt-hans/ShipAgent/issues/78) under the approved
[six milestones](https://github.com/matt-hans/ShipAgent/issues/75).

## Outcome and scope

Join the real control-plane HTTP/JWT/account/link authorization path to the
existing account-dedicated, source-free Agent Run service. A real loopback MCP
client must submit, clarify, continue, reconnect, recover after target restart,
read and cancel using signed disposable tokens and a scripted model. Two links
for one account and OAuth client remain independent. Every forbidden request
produces zero additional model entries.

The current lifecycle tests build a separate MCP server with synthetic identity
middleware; the production app's real authorization path exposes status only.
This slice closes that composition gap. It does not enable a production target,
change the chosen headless architecture, or finish either milestone. The approved
actual-client synthetic journey precedes uploaded-source preview; the private
snapshot lifecycle from PR92 remains available for the later source integration.

The composition is explicit trusted application construction for local
qualification. Default production construction remains status-only. No broad
environment flag may mark an arbitrary target or dormant descriptor ready. The
composition owns exactly one account/target service and its startup/shutdown.
It cannot be selected by HTTP headers, tool arguments, a token claim, or a model.
No source upload, source reader, carrier, purchase, approval, artifact, settings
or credential tool is admitted. The provider is explicitly scripted; no ambient
model credentials or provider fallback are used.

## Existing components and bounded changes

Reuse `create_control_plane_app`, `Auth0TokenVerifier`, `AuthorizationService`,
the registry lifecycle contracts, `AgentRunExecutionTarget`, `AgentRunService`,
`AgentRunStore`, the existing coordinator lease/borrow, `process_message` and
`ConversationRuntimeSession`. Do not create another agent loop or run store.

The new code has three purposes only: preserve a verified independent link in
the current request; own a bounded PostgreSQL/target-store authorization
operation; and construct the real app with the exact qualified target. The
existing synthetic callback API may remain for its current tests, but it is not
accepted as the authority implementation of this composition.

The legacy relay wire, desktop relay consumer, held headless enrollment work,
source snapshot APIs and production boot paths are outside this slice. A later
relay adapter must carry the same ownership/lifetime semantics over its trusted
transport; this local composition is not evidence that it already does.

## Verified link identity and persistence

The strict profile pins one issuer, canonical resource, trusted client registry,
and namespaced access-token claim name in trusted configuration. Tests use a
reserved synthetic namespace. Claim names are not discovered from token content.
The claim value is a nonempty, bounded opaque string (1–128 ASCII characters,
closed printable identifier alphabet); it is never a secret, path or URL.

The issuer must give each independent authorization link its own value, retain
it through refresh, and mint a new value for a genuinely new authorization link.
This is an explicitly synthetic issuer contract at this stage. Neither client
registration ID, token `iat`/`jti`, browser session ID, per-user metadata nor MCP
session identity is accepted as a fallback.

Keep these concepts separate:

- Verified issuer link ID identifies the issuer's authorization link.
- ShipAgent connection ID is a server-minted internal ownership identity.
- Link epoch is a server-minted opaque generation stored with references.
- Token scope and expiry describe this request, not mutable server policy.

A strict link is unique by verified issuer/account/client/surface/link ID. A
refresh returns the existing connection/epoch. A revoked tuple remains a durable
denial; it is never reactivated or recreated by a request. A new issuer link
creates a new connection and epoch and cannot read the previous link's runs.
Concurrent first use must converge on one account/link without duplicate rows.

The schema migration preserves legacy rows and their existing status behavior.
Legacy connections remain epoch-unbound and cannot authorize this strict
lifecycle. A strict account must also have its issuer explicitly bound: fresh
account creation records verified issuer and subject; legacy unbound accounts
are not silently repinned. Migrating existing real accounts into this profile
requires a later explicit reviewed operation. A configured issuer change cannot
reuse a bound account merely because the subject string matches.

`scopes_text` currently records observed token scopes and must not become a grant
policy. Strict links have a separate durable allowed-scope ceiling, initialized
from trusted profile policy and changed only by the authority service. Effective
request scope is the intersection of that ceiling, the current signed token's
scopes and the profile's status/preview capabilities. A narrow request does not
rewrite policy; an older broad token cannot restore a reduced or revoked
permission. Revocation and ceiling reduction are trusted internal operations
for this local proof, not new model-callable or public management endpoints.

## Lifetimes and expected ownership

The verified request carries exact account, connection, expected epoch, surface,
effective scopes, issuer and access-token expiry into the trusted target request.
Trusted composition pins the exact target/store. These fields cannot be supplied
or overwritten by tool arguments. Never replace the captured epoch with today's
epoch looked up from the connection ID.

Four lifetimes are distinct:

1. HTTP operation deadline: at most two seconds, captured before the first
   persistent authorization lookup and carried unchanged through identity
   resolution, handler admission, storage, authority settlement, retirement and
   response. A blocked account/link lookup cannot earn a fresh handler budget.
2. Current access-token expiry: checked after identity-resolution waits and again
   before a response. A valid token at HTTP entry is not sufficient after expiry.
3. Original accepted-turn authority: persisted on each new run as the earlier of
   the accepting token's expiry and acceptance time plus 120 seconds. Queuing,
   restart and refresh never extend it. Dispatch uses the remaining window and
   the configured model timeout (at most 120 seconds, default 30 seconds).
4. Conversation/reference expiry: the existing original 24-hour ceiling, never
   renewed by poll, retry or continuation. A new continuation gets a new run's
   bounded turn authority but retains the conversation's original expiry.

Strict issued-at and expiry claims must be actual finite numeric timestamps,
excluding booleans, with an explicitly supported datetime range. Reject missing,
nonfinite, out-of-range, future-issued, inverted or already-expired values.
Preserve fractional expiry without rounding up or renewing it. Test these
checks through signed tokens as well as the principal parser.

After a turn has completed, an active same-link request with a fresh token may
read its retained result within the original reference lifetime. It does not
need the old access token to remain live, and cannot use that read to launch
work. A queued turn with expired original authority becomes interrupted without
calling the provider. A previously running turn retains the existing truthful
interrupted/no-automatic-replay restart policy.

## Operation owner and lock order

Capture an operation owner and pin the exact service/coordinator generation
before any asynchronous wait. Its scope references remain retained until actual
retirement. Closing admission prevents new operations; service shutdown cannot
release the lease above an admitted HTTP/worker operation.

The service owns one strict operation slot with prompt-busy behavior and no
unbounded waiter list. Competing HTTP operations receive a bounded retryable
denial. Its sole existing worker can wait on the owner's completion signal only
within its original turn authority; replacement adapters share the same slot.
No mutex spans SQL, filesystem work or provider I/O.

Use installed SQLAlchemy `AsyncConnection.run_sync` as an asyncpg bridge for the
existing synchronous store action, with an explicitly owned connection and
transaction rather than an ORM identity map. The fixed order is:

1. Exact coordinator borrow and strict operation slot.
2. Captured nonwaiting Agent Run SQLite writer/transaction.
3. PostgreSQL account row lock, then exact provider-link row lock.
4. Validate captured issuer/account/link/epoch/scope, account status, target,
   coordinator generation and the applicable original clocks.
5. Perform the existing bounded target-store action and classify its COMMIT.
6. Settle and verify the exact original PostgreSQL transaction, then retire
   captured SQL, target and coordinator ownership in the defined reverse order.
7. Check original response deadline/expiry after retirement before responding.

Account/link revocation and policy changes use the same account→link row-lock
order and never acquire a target store while holding those locks. Mere HTTP
identity resolution completes before target admission and does not retain a
reverse-ordered authority lock.

`run_sync` executes inline, so SQLite's ordinary I/O still runs on the event loop.
This profile must not use the current three-second SQLite busy wait while
another operation yields with the writer held. Use nonwaiting lock acquisition,
the profile's one owned slot, bounded opening/statement settings and the common
deadline. External contention produces busy; there is no recursive retry.
Blocked filesystem I/O cannot be forcibly terminated safely and retains
ownership rather than claiming bounded physical retirement.

The private action interface does not return a live connection, authority scope,
borrow or reusable commit callback. The owner captures before effects, preserves
ordinary failure privacy and deliberately handles control-flow interruption.
Uncertain retirement latches service unavailability before releasing control;
known-busy admission alone does not quarantine the service.

## Local commit and PostgreSQL settlement are separate facts

This is not an atomic cross-database transaction. A held Python connection
object is not proof that a server-side lock survived connection loss. Nor is a
normally returning COMMIT call sufficient: PostgreSQL can treat COMMIT of an
already-aborted transaction as rollback.

A fresh success requires a known local outcome plus successful settlement of
the exact original PostgreSQL connection/transaction. No automatic reconnect or
replacement transaction may satisfy the original owner. Database death, an
aborted transaction, lost settlement response or cancellation during settlement
preserves the local outcome and original idempotency key but returns unavailable.
Never retry the action, remint a reference or infer rollback from missing reply.

The supported local authority profile is PostgreSQL 17 with the installed
asyncpg/SQLAlchemy stack and one explicitly pinned database endpoint. Capture
the exact original driver connection, backend PID and top-level xid8 from
`pg_current_xact_id()` during held validation. Before COMMIT, revalidate that the
same original transaction is live. After it returns, require
`pg_xact_status(captured_xid)` to report `committed` on the same still-owned
physical connection/backend. `aborted`, `in progress`, NULL, unsupported
capability, invalidation or replacement denies success. Do not quietly use a
different database or reconnect to obtain a favorable status.

The post-COMMIT status query starts a separate evidence-only transaction. It
does not authorize another action or repin a link, and the owner must capture
and positively retire it before acknowledgment. Any earlier acquisition,
validation, local-action or settlement exception stays latched; a later status
query may refine known commit evidence but cannot convert the failed request
into success. Unsupported server/driver profiles fail this local qualification
instead of receiving an untested fallback.

If local COMMIT was not attempted and both scopes positively roll back, the
operation is an ordinary denied/precommit action. If local COMMIT was attempted
but its outcome is unknown, retain that distinction through cleanup. Later
reconciliation obtains new current authority and reads the same original key.
If the link has been revoked, it cannot disclose the retained result.

Known committed state is never erased to manufacture an all-or-nothing result.
A queued row alone is never a dispatch permit. A local row that survived a lost
HTTP/authority response remains subject to fresh worker authorization before any
model entry. Model completion, duplicate recovery and reads follow the same
current-authority/settlement rule before returning provider-visible evidence.

## Background dispatch and revocation winner

The worker uses its own captured run binding and operation owner; it never relies
on an HTTP ContextVar or caches a link epoch as current authority.

A separate captured local-only candidate/claim transaction uses the same strict
service slot and coordinator pin. It grants no model dispatch. Prior private
history is materialized only after current authority is held inside dispatch
admission. The strict profile rejects history JSON above 1 MiB before loading
it, then uses the existing shared privacy/replay limits before model input.
That raw-storage ceiling is distinct from the existing provider replay ceiling.

Under the same guards, it revalidates the current account/link/scope and the
original accepted-turn deadline before admitting exactly one source-free model
call. Dispatch admission linearizes when that original authority transaction
settles successfully. A revoked link that wins the row lock first denies
dispatch. Dispatch admitted first may remain in flight; cancellation or
revocation cannot undo an already-admitted model charge. There is no database
lock held across the provider stream.

The strict profile allows one provider call per accepted run. A provider tool
attempt is denied and cannot cause a second model call. A private one-shot
dispatch permit is bound to the exact run/generation/provider owner and original
deadline; delayed use after expiry is denied. This is a wrapper over the shared
runtime/provider seam, not a second loop.

Completion obtains fresh current authority before durable successful/clarifying
publication. Revocation that wins first suppresses that public success and
follow-up. Proven ordinary authority denial may record the existing safe
interrupted outcome as cleanup; it grants no new model work. Storage/settlement
uncertainty retains the known/unknown outcome and fences the service. Subsequent
read/cancel/continue still require their own current request authority.

A read's authorization point is inside its held guards. The final post-retirement
check enforces expiry/deadline, not the impossible claim that revocation can
never occur after authorization but before response bytes arrive.

## Required evidence and serial review gates

1. Signed JWT/link persistence and migration: two links under one client,
   refresh, revoked old tuple/new link, concurrent first use, legacy-unbound
   denial, wrong issuer, scope reduction with broad/narrow tokens in both orders,
   malformed/missing claim, strict issued-at/expiry types/ranges, and expiry after
   waits, including identity lookup that exhausts the original operation budget.
2. Shared operation owner: actual PostgreSQL row-lock ordering plus nonwaiting
   SQLite contention, copied/stale owner denial, close while admitted, bounded
   slot contention, cancellation during acquisition/settlement and before/after-
   effect retirement failures. PostgreSQL-specific claims use real disposable
   PostgreSQL, never SQLite substitutes.
3. Failure model: PostgreSQL dies after validation, before/after local COMMIT,
   and before/after settlement; also deliberately abort a real transaction
   before COMMIT and require denial even when the driver returns normally.
   Null/in-progress/aborted XID status, replacement driver/backend, reconnect and
   post-error committed status cannot authorize success or model dispatch.
   Same-key recovery preserves the exact known/unknown local state.
4. Worker lifetime: revocation-first and dispatch-first barriers count actual
   provider entries; no second call; original turn expiry before dispatch/during
   execution; completion denied after revocation; restart without replay;
   cancellation and service shutdown retain exact cleanup ownership.
5. Real loopback MCP through the real app: full submit→clarify→continue→read,
   duplicate/conflict, restart/reconnect and cancel; current-request scopes,
   foreign account/same-account foreign link/target denial; zero model calls
   from rejected work or reads; canaries absent from public results/logs.
6. Default production status-only behavior, canonical registry/artifact agreement,
   existing OAuth wire and lifecycle regressions, package inclusion, independent
   frozen-head review, fresh remote full suite/CI and separate merged-main gate.

No stage proceeds past its shared-lifecycle review checkpoint. The implementation
plan must give the exact files, RED/GREEN cases and evidence per stage before
product edits. Preserve failed and inconclusive receipts honestly.

## External gates and later work

No live issuer, OAuth client, HTTPS endpoint, credentials, deployment or paid call
is configured here. Before actual clients, prove the pinned issuer link claim's
issuance, refresh, independent-link and relink/revocation semantics for the exact
tenant/client products, approve the temporary endpoint/target and cost budget,
and complete the separately reviewed authenticated relay/headless path.

Auth0 documents custom access-token claims and Actions during refresh, but its
current event reference labels refresh-token object data Enterprise-only. Those
facts do not establish this contract for an unprovisioned tenant. No speculative
Action is installed and no per-user field is substituted for a per-link identity.

Primary references checked 2026-10-09:

- [Auth0 post-login event](https://auth0.com/docs/actions/reference/post-login/post-login-event-object)
- [Auth0 post-login API](https://auth0.com/docs/actions/reference/post-login/post-login-api-object)
- [Auth0 claims during refresh](https://support.auth0.com/center/s/article/Will-the-access-token-received-via-refresh-token-have-the-custom-claim)
- [SQLAlchemy run_sync](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#sqlalchemy.ext.asyncio.AsyncConnection.run_sync)
- [PostgreSQL 17 transaction status](https://www.postgresql.org/docs/17/functions-info.html)
- [PostgreSQL aborted COMMIT semantics](https://www.postgresql.org/message-id/E1w5qAH-001aDI-22%40gemulon.postgresql.org)

The held headless supplemental scenario remains held. No alternative route or
mocked enrollment is used to claim its resolution. Public source admission,
selection/preview, actual-client qualification and milestones #76–81 stay open.
