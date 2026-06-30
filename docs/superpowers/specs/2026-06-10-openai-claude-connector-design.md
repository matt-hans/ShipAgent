# OpenAI App & Claude Connector — Technical Design

**Date:** 2026-06-10
**Status:** Approved — ready for implementation planning
**Supersedes in part:** `2026-06-08-provider-compatibility-design.md` (handoff subsystem, preview-only posture, bespoke OAuth)
**Execution model:** Subagent-driven development — one implementation plan per slice below

---

## 0. Design review log

### Q1 — Claude execution authority (resolved)

The current design assumes Claude provides a native, per-call approval prompt
that can serve as the second confirmation factor for `execute_shipments`. That
assumption is not portable across the named Claude surfaces:

- Claude custom connectors may invoke tools automatically in some modes,
  including Research, without further approval.
- The Messages API MCP connector executes server tools when the model selects
  them; any additional approval UX belongs to the calling application, which
  ShipAgent does not control.
- Claude interactive connectors can expose explicit confirm actions, but
  third-party purchases or financial transactions are not currently supported.

Therefore conversational agreement plus a model-visible confirmation token does
not independently prove an explicit user gesture. This conflicts with the
repository invariant that shipment purchase requires explicit confirmation.

**Decision:** Claude must support confirmation, shipment execution, and label
creation in the MVP. A preview-only Claude surface is rejected.

This requirement does not resolve the confirmation mechanism. ShipAgent still
must not treat conversational agreement, model-selected tool invocation, or a
model-visible token as proof of explicit user confirmation.

### Q2 — Claude confirmation channel (resolved)

Claude's hosted surfaces do not provide one universal confirmation primitive:

- Claude Enterprise can configure a connector tool as `Needs approval`, but this
  is an organization policy, not a portable server-verifiable artifact.
- Research may invoke custom connector tools automatically without further
  approval.
- The Messages API MCP connector invokes server tools when selected by the
  model; approval UX belongs to the calling application.
- Interactive connectors cannot perform third-party purchases or financial
  transactions.

**Decision:** restore a narrow ShipAgent approval handoff for Claude execution
only. `prepare_shipments` returns an opaque Approval Request; the user explicitly
approves it on a ShipAgent-owned surface, and only then does the cloud mint a
one-time Execution Token. Claude can subsequently call `execute_shipments`,
receive status, and create the label download, but neither the model nor the
Claude host can mint or infer approval. OpenAI continues to use its widget
button.

This changes ADR 0008 from “no handoff” to “no workflow handoff; confirmation
approval handoff permitted for surfaces without a trustworthy in-provider
gesture.”

**Rejected:** restricting Claude execution to controlled hosts. Claude
Enterprise `Needs approval` and approval UX in ShipAgent-owned Messages API
clients may provide defense in depth, but neither is the canonical ShipAgent
approval proof.

### Q3 — Canonical Claude approval surface (resolved)

The Approval Request needs one canonical user surface:

- **ShipAgent web approval page:** portable from Claude web, desktop, and mobile;
  authenticates the user through Auth0; displays the immutable redacted preview
  and cost ceiling; records an explicit approve/reject gesture; requires no
  inbound access to the desktop.
- **ShipAgent Desktop prompt:** keeps approval local and can show full local
  detail, but requires the user to be at the active desktop, introduces
  notification/focus behavior, and is not portable to Claude mobile.

**Decision:** use an Auth0-protected ShipAgent web approval page as the canonical
Claude approval surface. The page receives only an opaque, short-lived Approval
Request reference. Desktop notification/deep-link support is an optional
convenience, not an authorization requirement.

### Q4 — Approval-page detail boundary (resolved)

For locally imported shipments, the provider result is intentionally aggregate
only. The approval page, however, must let the person understand exactly what
will be purchased:

- **Aggregate-only page:** preserves the current provider-safe projection but
  makes batch approval effectively blind to recipient, package, and service
  mistakes.
- **Detailed ShipAgent-owned page:** fetches the immutable preview live from the
  active Execution Target and may display full recipient/package detail. The
  cloud relays this response but never persists it; Redis retains only the
  redacted summary and hashes.

**Decision:** permit full immutable preview detail on the Auth0-protected
ShipAgent approval page, including locally sourced recipient and package fields.
Keep Claude results aggregate-only. The approval response is fetched on demand,
uses `Cache-Control: no-store`, excludes analytics and third-party resources, is
omitted from application/access logs, and never enters Redis, SQL, model
context, or provider results. This avoids approving purchases from an aggregate
summary while preserving the no-cloud-persistence boundary.

### Q5 — Claude execution credential exposure (resolved)

The current text says the approval page mints an Execution Token and Claude then
passes that token to `execute_shipments`. That unnecessarily exposes an
authorization bearer artifact to model context and provider retention.

Two designs satisfy the explicit approval requirement:

- **Model-visible Execution Token:** `get_approval_status` returns the token and
  Claude submits it to `execute_shipments`. This preserves the existing input
  shape but places a replay-sensitive credential in provider-visible content.
- **Server-side Execution Grant:** Claude retains only the opaque Approval
  Request reference. Approval atomically creates a hash-bound, one-time
  Execution Grant server-side. `execute_shipments` receives the Approval Request
  reference, validates and consumes the grant internally, and never returns the
  credential to Claude.

**Decision:** use a server-side Execution Grant for Claude. The Approval Request
reference is a correlation identifier, not authorization by itself. OpenAI may
use widget-private metadata for its grant, but no Execution Token or grant
secret enters model-visible structured content.

The grant is cloud control-plane state bound to `account_id`,
`provider_connection_id`, `device_id`, immutable preview hash, cost ceiling,
operation, expiry, and idempotency key. Approval creates it atomically;
`execute_shipments` consumes it atomically. The existing
`src/hosted/confirmation_service.py` is not reused directly because it persists
against desktop/hosted-tenant models rather than Cloud Accounts.

### Q6 — Claude post-approval continuation (resolved)

After the user approves in a separate browser tab, Claude has no portable
server-initiated callback that resumes the original conversation. Two workable
flows remain:

- **Return-and-continue:** the approval page says “Approved — return to Claude.”
  The user returns and sends a short continuation such as “approved.” Claude
  calls `execute_shipments` with the Approval Request reference; the server
  consumes the Execution Grant.
- **Execute on approval:** the approval page immediately starts shipment
  execution, while Claude later polls status. This is smoother but makes the
  approval page an execution initiator and contradicts the resolved boundary
  that it may approve or reject only.

**Decision:** require return-and-continue. The approval page never executes
shipments. After approving, the user returns to Claude and sends a continuation
such as “approved.” Claude calls `execute_shipments` with the Approval Request
reference. Before approval the tool returns `approval_pending`; after approval
the first call consumes the grant and starts or returns the idempotency-bound
job; later calls return the same job reference.

### Q7 — Approval Surface application architecture (resolved)

The repository has no hosted browser-auth application or Auth0 SPA integration.
The Angular shell is a desktop/Tauri host, and `provider-widget` is an indexless
provider resource rather than a standalone authenticated site. The control
plane already owns Auth0 account resolution and includes Jinja.

Two implementation shapes are viable:

- **Standalone Angular approval app:** adds a new deployable frontend, browser
  Auth0 SDK, access-token handling, CSP/build/deployment work, and another API
  boundary.
- **Server-rendered control-plane page:** uses Auth0 Authorization Code + PKCE,
  an encrypted `HttpOnly`, `Secure`, `SameSite=Lax` session cookie, server-side
  CSRF protection, and first-party HTML/CSS only.

**Decision:** make the Approval Surface a minimal server-rendered control-plane
application. It does not reuse the desktop Angular shell or the OpenAI provider
widget. Browser authentication uses Auth0 Authorization Code + PKCE. The
control plane holds the browser session in an encrypted `HttpOnly`, `Secure`,
`SameSite=Lax` cookie; approval and rejection POSTs require server-side CSRF
validation. Pages contain first-party HTML/CSS only and no analytics,
third-party resources, or browser-stored access tokens.

Approval Requests use the existing 15-minute confirmation lifetime unless a
future policy explicitly overrides it. Browser authentication does not extend
the request or grant expiry.

### Q8 — Label-download authorization (resolved)

Labels contain recipient data and shipment identifiers. The current design
returns a short-lived signed URL in provider-visible content. A signature alone
makes that URL a bearer credential: provider link scanners, transcript
retention, copied messages, or browser history could disclose it before expiry.

Two delivery policies are possible:

- **Signed URL only:** simplest click-through, but possession of provider-visible
  text is sufficient to download a label.
- **Signed reference plus Auth0 session:** the URL carries an opaque,
  single-use download reference, but the browser must authenticate to the same
  Cloud Account before the control plane streams the label from the Execution
  Target.

**Decision:** require both the short-lived, single-use download reference and an
Auth0 browser session bound to the same Cloud Account. Use `Cache-Control:
no-store`, `Content-Disposition: attachment`, strict `Referrer-Policy:
no-referrer`, no application/access logging of the reference, and no cloud
persistence of label bytes. Provider-visible possession alone never authorizes
label access.

### Q9 — Label stream recovery boundary (resolved)

The label bytes remain only on the Execution Target. A browser download can fail
after the single-use reference is validated but before all bytes arrive because
the relay disconnects, the user cancels, or the network breaks.

Two consumption policies are possible:

- **Consume before streaming:** strongest replay resistance, but any interrupted
  transfer permanently invalidates the reference and forces Claude to request a
  new one.
- **Lease then consume on completed stream:** atomically changes
  `ready → streaming` for one browser session, prevents concurrent downloads,
  and marks `consumed` only after the stream completes. On interruption it
  returns to `ready` after a short lease timeout, still within the original
  expiry.

**Decision:** use lease-then-consume. Bind the lease to the Auth0 browser session
and Cloud Account; permit no concurrent stream; retain no label bytes; and
require a fresh reference after successful completion or original expiry. The
reference state is `ready → streaming → consumed`; an interrupted stream returns
to `ready` only after its short lease expires and only while the original
reference remains unexpired.

### Q10 — Price and shipment drift after approval (resolved)

Approval binds an immutable preview hash and cost ceiling, but execution may
encounter a changed UPS rate, address correction, package measurement, service
selection, row set, or source checksum. The repository already enforces preview
hashes for local execution but does not define a cloud-provider tolerance policy.

Two policies are possible:

- **Bounded tolerance:** execute when the final charge remains below an approved
  ceiling or percentage tolerance. This reduces reapproval but means the person
  may purchase a result not exactly shown on the Approval Surface.
- **Exact approved purchase:** any change to recipient, package, service, row
  set, selected-rate checksum, or total authorized amount invalidates the
  Execution Grant and requires a new preview and Approval Request.

**Decision:** exact approved purchase for MVP. The approved currency and total
amount are hard ceilings, but they are not permission to accept drift. Lower or
higher final cost, changed rate, address correction, package measurement,
service selection, row set, selected-rate checksum, source checksum, or any
material preview-hash change invalidates the Execution Grant and requires a new
preview and Approval Request.

### Q11 — Batch execution failure policy (resolved)

Even with an exact approved preview, a multi-row batch can fail partway through:
UPS may accept earlier labels and reject a later row, or the relay may disconnect
after some purchases. Already-created labels cannot be treated as rolled back.

The existing `BatchEngine` intentionally isolates rows and distinguishes:

- deterministic pre-UPS or UPS hard rejection, where no shipment was created;
- ambiguous transport or post-UPS failure, where a shipment may exist and the
  row becomes `needs_review`.

Two policies are possible:

- **Uniform best effort:** continue all independent rows after either category
  and report mixed completion.
- **Category-aware fail stop:** continue after deterministic row-local
  rejections, but trip a batch stop flag after an ambiguous/systemic failure.
  Already in-flight UPS calls reconcile; queued rows do not start.

**Decision:** use category-aware fail stop for provider-originated batches.
Preserve row isolation for deterministic failures, but stop launching new rows
after relay loss, timeout after possible dispatch, malformed UPS success, label
persistence failure, or any other `needs_review` condition. Never cancel an
in-flight UPS call or automatically void a created shipment. Return an aggregate
mixed-result summary in Claude/OpenAI; detailed remediation remains in ShipAgent
Desktop. One-off shipments naturally remain all-or-one.

### Q12 — Canonical prepare contract for one-off and local batches (resolved)

The existing public contract cannot deliver the stated product flow:

- `prepare_shipments` accepts only `order_batch_id`, but no public tool creates
  or discovers that identifier.
- `submit_one_off_shipment` is itself a purchase tool, creating a second
  execution path beside `prepare_shipments → execute_shipments`.
- The provider must configure local-row selection without receiving row data.

Two contract shapes are possible:

- **Separate flows:** retain `submit_one_off_shipment`; add more tools to create
  or select local batches before `prepare_shipments`.
- **Unified prepare flow:** `prepare_shipments` accepts a closed discriminated
  `shipment_source`:
  - `one_off`: provider-supplied shipment fields;
  - `active_source_selection`: a deterministic filter/mapping/package/service
    plan applied locally to the active source;
  - optionally `existing_batch`: an opaque locally created batch reference.
  All modes produce the same immutable preview, Approval Request, Execution
  Grant, and `execute_shipments` path.

**Decision:** use the unified prepare flow and remove
`submit_one_off_shipment` from the public provider surface. Reuse the canonical
filter and shipment-plan models already used by local orchestration; never send
source rows to the provider. This preserves one mutation path and makes an
existing batch reference an optional advanced source rather than an unexplained
prerequisite.

### Q13 — Tier-B filter confirmation in provider flows (resolved)

The canonical filter design currently requires two gates:

1. confirm Tier-B semantic expansion before any DuckDB query;
2. confirm the priced shipment preview before execution.

That rule was designed for the local conversation UI. The provider Approval
Surface now displays the full exact row set and immutable purchase details, so a
separate semantic gate may be redundant.

Two policies are possible:

- **Preserve two gates:** expose filter-resolution/confirmation tools publicly;
  the user confirms terms such as “Northeast” before `prepare_shipments` can
  query and price rows.
- **Provisional preview, one approval:** `prepare_shipments` accepts canonical
  `FilterIntent`, resolves Tier-B terms deterministically, and applies the
  candidate selection only to create a no-mutation preview. Claude/OpenAI receive
  only aggregates. The Approval Surface prominently shows the expansion, exact
  selected rows, and price; approving confirms both the interpretation and the
  purchase. Tier-C unresolved terms still require conversational clarification
  before preview.

**Decision:** use provisional preview with one approval for provider-originated
flows. Tier-B candidate expansions may touch DuckDB only for an ephemeral,
non-mutating preview whose full row set, expansion explanation, and purchase
details are shown on the ShipAgent Approval Surface. Approval confirms both the
interpretation and the Exact Approved Purchase. Tier-C unresolved terms still
require conversational clarification before preview. Local desktop workflows
retain the existing two-gate behavior.

### Q14 — OAuth scope escalation by provider surface (resolved)

The current design assumes incremental `shipagent.execute` consent works equally
across providers. Current platform behavior is asymmetric:

- ChatGPT Apps supports per-tool scopes and reauthorization for additional
  scopes through OAuth challenges.
- Claude custom connectors expose a connect/reconnect flow but do not document a
  portable per-tool incremental-scope escalation contract.
- Messages API MCP callers must obtain and supply the bearer token themselves.

Two policies are possible:

- **Uniform incremental scopes:** request status/read initially and rely on every
  Claude host to reauthorize for preview/execute. This is least privilege but not
  reliably portable.
- **Surface-specific grants:** ChatGPT starts with status/read and steps up to
  preview/execute. Claude custom connectors request the full MVP scope set when
  connected; Messages API clients must supply a token with the scopes required
  by the enabled tools.

**Decision:** use surface-specific grants. ChatGPT starts with status/read scopes
and steps up through OAuth challenges when preview or execution is first needed.
Claude custom connectors request the full MVP scope set when connected. Messages
API clients must obtain and supply an Auth0 token containing the scopes required
by the tools they enable.

Full Claude OAuth scope does not authorize a purchase by itself; the ShipAgent
Approval Surface and one-time Execution Grant remain mandatory. Provider
Connections record the scopes actually present, and every tool call enforces its
canonical scope set.

### Q15 — Canonical public OAuth scope vocabulary (resolved)

The design names `shipagent.status`, `shipagent.read_summaries`,
`shipagent.preview`, and `shipagent.execute`, while the implemented registry uses
unrelated colon scopes such as `account:read`, `device:read`,
`shipments:preview`, `shipments:execute`, `jobs:read`, and `labels:read`.

Two models are possible:

- **Per-tool resource scopes:** preserve the granular colon scopes. This creates
  a larger external Auth0 contract and makes provider consent copy unstable as
  tools evolve.
- **Stable workflow tiers:** use a small public namespace:
  `shipagent.status`, `shipagent.preview`, `shipagent.execute`, and
  `shipagent.artifacts`. Read-only job summaries required to continue an
  approved flow are covered by the tier that created the job; label-download
  reference creation requires `shipagent.artifacts`.

**Decision:** adopt the stable `shipagent.*` workflow tiers for all public
provider tools and reserve granular/internal scopes for non-public APIs. The
public scopes are:

- `shipagent.status` — `get_shipagent_status`;
- `shipagent.preview` — address validation, rates, and `prepare_shipments`;
- `shipagent.execute` — `execute_shipments` and status polling for jobs created
  by that execution flow;
- `shipagent.artifacts` — create and redeem label download references.

`shipagent.read_summaries` is removed. `get_job_status` is reference-scoped
continuation, not general account-history access.

### Q16 — Provider Connection binding for continuation references (resolved)

Cloud Account binding prevents cross-user access, but one account may connect
both ChatGPT and Claude. If job, approval, poll, or label references are scoped
only to the account, one provider connection could use opaque references created
by the other after those references appear in copied text or logs.

Two policies are possible:

- **Account-wide continuation:** any active Provider Connection for the same
  Cloud Account and scope can continue or retrieve artifacts.
- **Originating-connection continuation:** Approval Requests, Execution Grants,
  job references, poll references, and label-reference creation are bound to the
  originating `provider_connection_id`. Browser approval/download additionally
  binds to the Cloud Account, but browser login is not itself a Provider
  Connection.

**Decision:** bind all provider-callable continuation references to the
originating Provider Connection. ChatGPT cannot poll or request labels for
Claude-created jobs, or vice versa. A future explicit transfer feature would
need its own user-approved contract; it is not implicit account sharing.

The Auth0 Approval Surface and label-download browser endpoint bind to the Cloud
Account because a browser session is not a Provider Connection. Their opaque
references still retain the originating Provider Connection binding, and any
subsequent MCP continuation must come from that same connection.

### Q17 — Execution Target binding across approval and reconnect (resolved)

Approval Requests and Execution Grants currently bind to `device_id`. The
product also permits relay reconnect, device-key rotation, and replacement of
the Active Desktop Device. If the active target changes after preview, the new
runtime may not hold the same local job, rows, or labels.

Two policies are possible:

- **Account-level target binding:** execute on whichever target is active when
  Claude returns. This is flexible but can route an approved preview to a
  different local dataset/runtime.
- **Exact target binding:** bind the preview, Approval Request, Execution Grant,
  job/poll references, and label references to the exact `execution_target_id`
  that produced the preview. Relay session reconnect and device key rotation do
  not change that identity; selecting a replacement device invalidates pending
  approvals and requires re-preview.

**Decision:** use exact target binding. Preview, Approval Request, Execution
Grant, job/poll references, and label references bind to the exact
`execution_target_id` that produced the preview. Relay session reconnect and
device-key rotation preserve target identity. Selecting or replacing the active
target invalidates pending approvals and requires re-preview.

The contract uses `execution_target_id`, not `device_id`, so a future SaaS worker
fits the same rule.

### Q18 — Approval Surface behavior while target is offline (resolved)

The Approval Surface must fetch full detail live because the cloud stores only a
redacted summary. If the bound Execution Target is offline when the link opens,
the page cannot present the exact purchase.

Two policies are possible:

- **Allow aggregate approval:** show the stored summary and accept approval while
  the target is offline, then validate detail later. This violates informed
  approval and can approve a purchase the person did not inspect.
- **Fail closed until target returns:** show only an unavailable state with the
  request expiry and retry control. Do not reveal stale detail and do not record
  approval. If the target reconnects with the same identity before expiry, the
  page can fetch and display the exact preview.

**Decision:** fail closed until the exact bound target is online. The Approval
Surface shows an unavailable state, original expiry, and retry control, but no
stale or aggregate approval action. Approval never extends the 15-minute request
expiry. If the request expires offline, Claude must create a new preview and
Approval Request.

### Q19 — Execution Grant consumption point (resolved)

The user may approve while the target is online, then return to Claude after the
relay disconnects. Consuming the one-time Execution Grant before the target
accepts the invocation would strand an approved purchase without starting a job.

Two policies are possible:

- **Consume at execute-tool entry:** simplest atomic check, but target-offline or
  pre-accept transport failure burns the grant.
- **Reserve then consume on target acceptance:** atomically transition
  `approved → reserved`, dispatch to the exact target, then transition
  `reserved → consumed` only when the target durably accepts the
  idempotency-bound invocation. If dispatch never reaches `accepted`, release the
  reservation back to `approved` while the original expiry remains valid.

**Decision:** reserve then consume on durable target acceptance. The grant state
is `approved → reserved → consumed`. If dispatch never reaches `accepted`, the
reservation returns to `approved` while the original expiry remains valid. Once
the exact target durably accepts the idempotency-bound invocation, the grant is
consumed permanently; retries return the original or recovered job.

### Q20 — Public polling reference shape (resolved)

The current async contract returns both `jobRef` and `pollToken`, then requires
the model to pass both back. Both are opaque, scoped, short-lived continuation
references, and the design already binds them to account, Provider Connection,
and Execution Target.

Two shapes are possible:

- **Separate job and poll references:** permits independent revocation but
  increases model error, result size, Redis mappings, and missing-token recovery
  cases.
- **Single Job Reference:** `execute_shipments` returns one opaque `job_ref`;
  `get_job_status` and `create_label_download` accept that reference. The cloud
  maps it to the local job and enforces account, connection, target, scope, and
  expiry internally.

**Decision:** use one opaque Job Reference. Never expose local desktop job IDs
or a separate poll credential. Keep the mapping for 24 hours or the configured
terminal-job retention, whichever is shorter.

### Q21 — Multi-label download artifact (resolved)

A completed batch can produce multiple labels, while the current
`create_label_download` schema returns one `download_url`. Provider results must
not enumerate local paths or expose per-row locally sourced recipient data.

Two artifact shapes are possible:

- **Per-label references:** return an array of download actions keyed by row or
  shipment. This increases provider-visible cardinality and can leak local batch
  structure.
- **One job artifact:** create one Label Download Reference for the completed
  job. The authenticated browser receives a deterministic ZIP for multiple label
  files and the original label media type for a single artifact.

**Decision:** use one job-level artifact. For multiple labels, stream a ZIP
generated on the Execution Target with opaque filenames such as
`label-0001.pdf`; include a first-party `manifest.csv` mapping ordinal,
provider-flow tracking number, and status, but no recipient PII. For one label,
stream the original PDF/ZPL/PNG artifact directly. Nothing is persisted
cloud-side.

### Q22 — Tracking-number visibility in provider results (resolved)

ADR 0007 currently allows full tracking numbers for shipments created in the
current provider flow. For a local-source batch, returning an array of all
tracking numbers to Claude/OpenAI reveals row-level output cardinality and
copies durable shipment identifiers into provider retention, even though the
provider cannot see the corresponding local recipients.

Two policies are possible:

- **Full current-flow tracking results:** return every created tracking number in
  `get_job_status`, plus the artifact manifest.
- **Artifact-only batch tracking:** for one-off shipments, return the full
  tracking number in provider results. For local-source or existing-batch jobs,
  return only aggregate completion counts; full tracking numbers exist in the
  authenticated downloaded artifact manifest and ShipAgent Desktop.

**Decision:** use artifact-only batch tracking. One-off provider results may
return the full tracking number created in that flow. Active-source and
existing-batch provider results return aggregate completion counts only. Their
full tracking numbers are available in the authenticated job artifact manifest
and ShipAgent Desktop.

The manifest is protected by the account-bound Label Download Reference and is
never provider-visible unless the user uploads it themselves.

### Q23 — OpenAI execution-tool visibility (resolved)

OpenAI's MCP Apps contract supports app-only tools through
`_meta.ui.visibility: ["app"]`. A tool with default visibility is available to
both the model and widget, so a button click alone is not an authorization
boundary if the model can invoke the same tool.

Two projections are possible:

- **Model-and-app execute tool:** rely on prompt instructions telling the model
  not to call `execute_shipments`. This is not an enforceable user-gesture gate.
- **Surface-specific visibility:** project canonical `execute_shipments` as
  app-only for OpenAI and model-visible for Claude. The OpenAI widget calls it
  through `tools/call`; Claude calls it after the external Approval Surface
  creates its Execution Grant.

**Decision:** use surface-specific visibility on the same canonical workflow
tool. OpenAI's model never receives the execute-tool descriptor and cannot
invoke it. The widget calls it through `tools/call`. Claude receives the
model-visible descriptor because its server-side Execution Grant is created
through the external Approval Surface. This is projection metadata, not
provider-specific shipping logic.

### Q24 — Generic MCP execution export (resolved)

The public registry currently exports every public tool to `generic_mcp`.
Generic MCP hosts have no guaranteed app-only tool visibility, Auth0 browser
approval flow integration, or known provider identity semantics.

Two policies are possible:

- **Export execution generically:** allow any compatible MCP host to use the
  Claude-style Approval Surface and Execution Grant flow. This broadens reach but
  creates an unreviewed public purchase surface with unknown host behavior.
- **Restrict the MVP:** export status/preview tools generically, but export
  `execute_shipments`, execution status continuation, and label artifact actions
  only to the explicitly designed OpenAI and Claude surfaces.

**Decision:** restrict mutating and artifact-bearing workflows to OpenAI Apps and
Claude for MVP. Generic MCP remains status/preview-only until a host profile
defines authentication, approval continuation, tool visibility, privacy, and
adversarial tests.

`execute_shipments`, execution Job Reference continuation, and
`create_label_download` are not exported through the generic MCP profile.

### Q25 — Claude surface identity separation (resolved)

The design names both Claude custom connectors and Messages API MCP callers as
“Claude,” but their authorization and revocation relationships differ:

- a claude.ai custom connector is an Auth0 OAuth client managed through the
  Claude connection UI;
- a Messages API integration is an arbitrary calling application that obtains
  and supplies its own Auth0 token.

If both resolve to one generic `claude` Provider Connection, revoking one may
affect the other, and originating-connection isolation becomes ambiguous.

**Decision:** treat `claude_ai` and `claude_messages_api` as distinct provider
surfaces and Provider Connections. Each authorized Messages API OAuth client ID
creates its own independently revocable connection rather than sharing a single
global “Claude API” identity. Both use the same Claude tool projection and
Approval Surface policy.

### Q26 — Desktop-to-Cloud Account linking ceremony (resolved)

The relay key proves possession of a device key, but it does not prove which
Cloud Account is allowed to register that key. The current design says the
desktop calls `/relay/devices/register` yet does not define how the desktop
obtains a human-authenticated Cloud Account session.

Two ceremonies are possible:

- **Desktop browser login:** ShipAgent Desktop initiates Auth0 Authorization Code
  + PKCE in the system browser with a loopback callback, then registers its
  public key using the resulting account-scoped token.
- **Provider-issued pairing code:** the provider connection creates a code that
  the desktop claims. This couples relay identity to a provider surface and
  violates the rule that Provider Connections do not define account identity.

**Decision:** use independent desktop browser login through Auth0 Authorization
Code + PKCE with a loopback callback. The desktop client has only
device-management scopes; provider scopes are not granted. Registration binds
the device public key and stable local installation ID to the Cloud Account,
after which relay PoP authenticates reconnects without retaining the Auth0
access token.

The existing loopback-only Python sidecar owns the temporary callback listener
on an OS-assigned `127.0.0.1` port. Tauri has no deep-link plugin and does not
receive OAuth credentials through `shipagent://`; the custom scheme remains a
navigation convenience only.

### Q27 — Desktop reauthentication and device-management authorization (resolved)

After initial registration, relay PoP proves the device identity but should not
silently authorize human account-management actions such as key rotation,
revoking another device, or unlinking the Cloud Account.

Two policies are possible:

- **Relay-authenticated management:** any connected device may rotate/revoke
  device registrations through its relay session.
- **Fresh human authorization:** relay reconnect uses PoP only, but register,
  rotate, revoke, set-active, and unlink require a fresh or recently
  authenticated Auth0 desktop session with device-management scopes. Local
  private-key deletion additionally requires an explicit desktop confirmation.

**Decision:** require fresh human authorization for all device management.
Register, rotate, revoke, set-active, and unlink require an Auth0 desktop session
authenticated within the previous 10 minutes; outside that window, repeat the
browser PKCE flow. Local private-key deletion additionally requires explicit
desktop confirmation.

A revoked, replaced, or unlinked target's relay session terminates immediately.
Its pending Approval Requests and unconsumed Execution Grants become terminally
invalid; accepted jobs remain recoverable by their original target identity if
the target is reauthorized rather than replaced.

### Q28 — Durable authorization audit content (resolved)

The current durable cloud audit lists provider, account, tool, result category,
duration, target fingerprint, and correlation IDs. That is insufficient to prove
why a purchase was authorized or whether a grant was replayed, while storing
preview detail or user identity would violate the thin-audit boundary.

Two policies are possible:

- **Operational audit only:** keep tool/result timing fields and rely on desktop
  audit for confirmation evidence.
- **Hashed authorization ledger:** additionally record approval decision and
  Execution Grant lifecycle events with opaque IDs and hashes: Approval Request
  ID, preview hash, purchase-scope hash, authorized amount/currency, approving
  Auth0 subject hash, Provider Connection ID, Execution Target fingerprint,
  grant state transition, idempotency-key hash, result category, and
  timestamps—never raw PII, row data, labels, tracking numbers, tokens, or URLs.

**Decision:** use the hashed authorization ledger. Durable cloud audit records:

- Approval Request ID and event type;
- preview and purchase-scope hashes;
- authorized amount and currency;
- approving Auth0 subject hash;
- Provider Connection ID;
- Execution Target fingerprint;
- Execution Grant state transition;
- idempotency-key hash;
- result category, correlation IDs, and timestamps.

It never records raw PII, row data, labels, tracking numbers, tokens, URLs, or
provider prompts. This ledger proves that approval preceded target acceptance
without persisting shipment detail.

### Q29 — Durable cloud audit retention (resolved)

The spec says SQL retention is “configurable” but defines no default or deletion
guarantee. A security ledger without a retention policy tends to become
indefinite personal/account metadata.

Two policies are possible:

- **Indefinite/config-only:** operators choose retention. This maximizes
  investigation history but weakens the product's ephemeral-cloud posture.
- **Finite default with bounded override:** default to 90 days, purge daily, and
  allow deployment configuration within a documented range. Security/legal
  hold requires an explicit separate mechanism.

**Decision:** default to 90 days with a daily purge and permit a 30–365 day
deployment setting. Account deletion purges audit rows unless a separately
recorded legal hold applies. The desktop remains the durable source for full
operational audit.

Legal hold is not inferred from account status or operator convention. It must
be an explicit separately audited control; absent that control, deletion
proceeds.

### Q30 — Approval Request URL exposure and login binding (resolved)

The Claude result must contain a URL the user can open. Even though the Approval
Request reference is not authorization by itself, URLs are retained in provider
transcripts, browser history, and link scanners.

Two URL shapes are possible:

- **Raw request ID in path/query:** easy to implement, but exposes a stable Redis
  lookup key and makes accidental logging more likely.
- **Random public locator:** return a high-entropy, short-lived locator whose
  hash maps to the Approval Request. Opening it reveals nothing until Auth0 login
  resolves the same Cloud Account. The locator is never an approval credential
  and is invalidated on approve, reject, expiry, target replacement, or
  connection revocation.

**Decision:** use a random 256-bit public locator, store only its hash, and never
put internal Approval Request IDs in URLs. Add
`Referrer-Policy: no-referrer`, redact the path from access logs, and show a
generic not-found page for wrong-account, invalid, or expired locators to avoid
account/request enumeration.

### Q31 — Relay invocation replay protection (resolved)

The relay section requires a “session-bound MAC” on every invocation, but the
handshake defines only a device-signed JWT and no shared session-key agreement.
A MAC without a defined key derivation, rotation, and teardown protocol is not
implementable. It also does not protect against an attacker that has compromised
one relay endpoint and therefore possesses the live session key.

Two coherent protocols are possible:

- **TLS channel plus session sequencing:** rely on authenticated WSS for
  cloud-to-desktop integrity. Every invocation includes the unpredictable
  `relay_session_id`, a strictly increasing per-session sequence number,
  `relay_invocation_id`, deadline, and idempotency key. The desktop rejects
  wrong-session, duplicate, expired, or non-increasing envelopes and retains
  accepted invocation IDs for recovery.
- **Message-level cloud signatures:** additionally sign every envelope with a
  cloud signing key pinned or trust-anchored by the desktop. This survives
  TLS-terminating intermediaries but adds cloud-key distribution, rotation,
  canonical serialization, and signature-verification failure modes.

**Decision:** use authenticated WSS plus session sequencing for MVP and remove
the undefined MAC. Every invocation carries `relay_session_id`, a strictly
increasing per-session sequence number, `relay_invocation_id`, deadline, input
hash, and idempotency key. The desktop rejects wrong-session, duplicate,
expired, or non-increasing envelopes. Replay of captured frames is in scope,
while compromise of either live endpoint is not mitigated by the relay protocol.
Message-level cloud signatures remain a future hardening option if deployment
introduces untrusted TLS termination.

Official references:

- <https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp>
- <https://docs.anthropic.com/en/docs/agents-and-tools/mcp-connector>
- <https://support.claude.com/en/articles/13454812-use-interactive-connectors-in-claude>
- <https://developers.openai.com/apps-sdk/build/mcp-server>

---

## 1. Summary

ShipAgent exposes its workflow tools to ChatGPT (OpenAI Apps SDK) and Claude
(claude.ai custom connectors and the Messages API MCP connector) through the
existing cloud MCP control plane. Preview, execution, tracking, and label
download happen in the provider app. OpenAI confirmation happens in its widget;
Claude confirmation uses a narrow ShipAgent-owned Approval Request handoff
because Claude does not expose a portable server-verifiable confirmation
gesture. The canonical Claude approval surface is an Auth0-protected ShipAgent
web page; desktop prompts are optional convenience only. The local desktop
runtime remains the execution authority (it owns imported rows, UPS
credentials, BatchEngine, and label storage) and is reached through a
cryptographically authenticated outbound relay.

The desktop relay is an **intermediary step toward a full SaaS backend.** Every provider-facing contract is therefore target-agnostic: the cloud dispatches through the `ExecutionTarget` protocol (ADR 0002), the relay is the first implementation, and a future SaaS worker replaces it without changing any public tool contract.

Three hard requirements carried from the June 5–6 component docs:

1. **Cryptographic relay identity** — Ed25519 proof-of-possession; no spoofed desktops.
2. **Relay-loss recovery** — deterministic provider responses for every disconnect mode.
3. **Ephemeral cloud-state retention** — TTL'd Redis state, scheduled purge, thin redacted durable audit.

General workflow handoff remains rejected. A narrow Claude Approval Request
handoff is required solely to obtain a ShipAgent-verifiable user gesture before
purchase. Provider results may include a bare `shipagent://` deep link for
convenience, but approval credentials are never placed in deep links.

## 2. What already exists (do not rebuild)

| Component | Location | State |
|---|---|---|
| Tool registry with `ToolContract` (incl. `max_sync_seconds`, `max_result_bytes`, `minimum_capabilities`, `rate_limit_class`, `prepare_tool`, `execution_target_required`, `result_profile`, provider exports) | `src/registry/` | Built; drift tests in `tests/registry/` |
| Public tool surface foundation: `get_shipagent_status`, `validate_shipment_address`, `get_shipment_rates`, `prepare_shipments`, `execute_shipments`, `get_job_status`, `create_label_download` | `src/registry/tools/public.py` | Contract skeleton built; schemas require this design's revisions |
| Provider projections (OpenAI, Gemini, Microsoft, generic MCP) | `src/provider_adapters/` | Built |
| Cloud control plane: FastAPI app, Auth0 token verification, OAuth protected-resource metadata, Streamable HTTP `/mcp` mount, Redis `RequestControls` (rate limits), result projection, audit service, startup security guard | `src/control_plane/` | Built |
| Desktop/hosted `ConfirmationService` — one-time tokens for existing hosted-tenant flows | `src/hosted/confirmation_service.py` | Built; not the cloud Approval Request store |
| UPS boundary (hosted `shipagent_v1` envelopes, validators, readiness) | `src/hosted/ups_boundary/` | Built |
| `ShippingWorkflowService` + `CarrierGateway` protocol | `src/workflows/` | Built |
| `provider-widget` Nx app scaffold | `shipagent-frontend/apps/provider-widget/` | Scaffolded |
| ADRs 0001 (Auth0 identity), 0002 (relay-first `ExecutionTarget`), 0003 (prepare/execute + one-time token) | `docs/adr/` | Accepted |

**Not built:** the desktop relay subsystem, cloud relay router and crypto
handshake, invocation lifecycle and recovery, version gate, ephemeral
TTL/purge, output profiles, the OpenAI widget content, the Claude Approval
Surface, desktop settings for cloud features, golden-prompt corpus.

## 3. Architecture

```
ChatGPT App / Claude connector / Claude API MCP
        │  HTTPS + Auth0 Bearer (existing)
        ▼
Cloud Control Plane  (src/control_plane — exists, extended)
   /mcp Streamable HTTP (exists) · OAuth metadata (exists) · Auth0 verify (exists)
   + relay router · device identity · version gate · ingress guard v2
   + ephemeral Redis state w/ TTLs · output profiles · thin redacted audit
        ▲
        │  Server-rendered Auth0 Approval Surface (Claude explicit gesture)
        │  ExecutionTarget protocol  ← the SaaS seam (ADR 0002)
        ▼
RelayExecutionTarget → outbound WSS → ShipAgent Desktop  (new)
   Ed25519 keypair in OS keychain · PoP handshake · heartbeat w/ version metadata
   relay invocation dispatcher → existing workflow services
        │  unchanged
        ▼
BatchEngine → UPSMCPClient → ups-mcp (stdio, upstream, never modified)
```

### 3.1 Decisions

**D1 — Provider-led execution with per-surface confirmation.** ADR 0003's
`prepare_*` → `execute_*` model stays:
- **OpenAI:** execution is triggered only by the confirmation widget's button —
  a user gesture, not a model-initiated call. The OpenAI projection makes
  `execute_shipments` app-only with `_meta.ui.visibility: ["app"]`; the widget
  invokes it through `tools/call`. Widget-private metadata carries only opaque
  references; no execution credential is exposed to the model.
- **Claude:** `prepare_shipments` returns an opaque Approval Request. A
  ShipAgent-owned, Auth0-protected web page records an explicit user gesture and
  atomically creates a server-side Execution Grant. Claude then calls
  `execute_shipments` with the Approval Request reference after the user returns
  to Claude and continues the conversation.
- Claude host approval prompts are defense in depth only. Conversational
  agreement and model-selected calls are not ShipAgent approval proof.
- Both paths consume an Execution Grant bound to account, provider connection,
  Execution Target, immutable preview hash, exact authorized amount/currency,
  expiry, and idempotency key.
  Neither surface can execute a shipment the user has not seen priced.

**D2 — Auth0 stays with surface-specific grant timing (ADR 0001).** No bespoke
`/oauth/authorize`, `/oauth/token`, or JWKS endpoints. Per-tool `auth_scopes` on
`ToolContract` are enforced at the hosted MCP boundary. ChatGPT uses incremental
scope escalation. Claude custom connectors request all MVP scopes at connection
time. Messages API callers provide an appropriately scoped Auth0 token.

**D2a — Stable public scope tiers.** Public provider contracts use only
`shipagent.status`, `shipagent.preview`, `shipagent.execute`, and
`shipagent.artifacts`. Internal APIs may retain finer-grained scopes.

**D2b — Originating Provider Connection isolation.** Provider-callable approval,
job, poll, and artifact references are valid only for the Provider Connection
that created them. Cloud Account browser authentication does not erase that
origin binding.

**D2c — Claude connection separation.** `claude_ai` and every authorized
Messages API OAuth client are distinct Provider Connections with independent
revocation and continuation references.

**D3 — Target-agnostic contracts (SaaS-forward).** Public tools and envelopes never encode "desktop":
- Status tool reports `executionTarget: {state: "ready" | "offline" | "update_required"}`.
- Machine reason codes are `target_offline`, `target_update_required` — not `desktop_*`.
- User-facing message text may say "your ShipAgent runtime" / "ShipAgent Desktop" for clarity, but no schema field does.
- The SaaS worker later implements `ExecutionTarget`; the provider surface does not change.
- Every provider workflow reference binds to the exact `execution_target_id`
  that created its preview. Active-target replacement invalidates pending
  approval rather than rerouting it.

**D4 — Origin-based redaction (ADR 0007).** Replaces the blanket PII bans of the preview-only plan:
- Data the user supplied through the provider conversation (a one-off recipient address, a package weight) may be echoed back in results.
- Data originating from locally imported sources (rows, customer lists) is provider-visible **only as aggregates** (counts, totals, warning counts) — never as row arrays or full per-row addresses.
- The Auth0-protected Approval Surface may display the full immutable local
  preview because it is a ShipAgent-owned confirmation boundary, not a provider
  result. Detail is fetched live from the Execution Target and is never stored
  cloud-side.
- Never provider-visible under any origin: UPS credentials, UPS account numbers, raw UPS payloads, label bytes/base64, keyring contents.
- Tracking numbers for one-off shipments created in the current provider flow
  are visible in full. Active-source and existing-batch results remain
  aggregate-only; their full tracking numbers are confined to the authenticated
  artifact manifest and ShipAgent Desktop. Tracking numbers surfaced from local
  job history are masked (`1Z999…9999`).
- Labels are delivered through short-lived, opaque, single-use download
  references (`create_label_download`, existing `artifact_action` result
  profile). The browser must authenticate to the same Cloud Account before bytes
  stream Execution Target→cloud→browser; label bytes are never persisted
  cloud-side.
- A batch job produces one artifact. Multiple labels are packaged on the
  Execution Target as a ZIP with opaque filenames and a first-party non-PII
  manifest. ShipAgent's canonical label format is PDF. A one-label job streams
  its PDF directly.

**D5 — Hard requirements.** Relay identity, relay-loss recovery, and ephemeral retention are blocking design requirements implemented in Plans 1, 2, and 4 respectively, with adversarial coverage in Plan 10.

**D5a — Exact approved purchase.** Provider-originated execution fails closed on
any material drift from the immutable preview, including cost reductions. No
tolerance policy applies in the MVP; re-preview and reapproval are required.

**D5b — Category-aware batch fail stop.** Deterministic row-local rejections do
not prevent other approved rows from executing. Ambiguous or systemic failures
set a shared stop flag: already in-flight calls reconcile, queued rows remain
unstarted, and the job becomes `needs_review`. Created shipments are never
automatically voided.

**D6 — Workflow handoff rejected; Claude approval handoff retained (ADR 0008).**
There is no transfer of workflow ownership or execution to another client.
Claude uses a short-lived Approval Request solely to collect a
ShipAgent-verifiable user gesture on an Auth0-protected ShipAgent web page. The
approval surface cannot execute shipments; it can only approve or reject the
immutable preview. The user returns to Claude after approval; Claude remains the
initiator of `execute_shipments`.

**D7 — Server-rendered Approval Surface.** The control plane serves the Claude
Approval Surface directly using Auth0 Authorization Code + PKCE, encrypted
server-side browser sessions, and CSRF-protected approve/reject POSTs. The page
uses first-party HTML/CSS only, stores no browser access token, and shares no
runtime with the desktop Angular shell or OpenAI widget.

The Approval Surface can render actionable detail only while the exact bound
Execution Target is online. Offline requests fail closed and cannot be approved
from the stored aggregate summary.

**D8 — Unified prepare/execute mutation path.** One-off shipments, deterministic
selections from the active local source, and optional existing local batches all
enter through `prepare_shipments` and produce the same immutable preview.
`execute_shipments` is the only public shipment-purchase tool.
`submit_one_off_shipment` is removed from provider exports.

**D9 — Provider-only combined semantic and purchase approval.** A Tier-B
semantic expansion may be applied provisionally to local data only to generate a
non-mutating provider preview. The Approval Surface shows the expansion and
exact selected rows; one explicit approval confirms both interpretation and
purchase. Tier-C ambiguity still blocks preview. Local workflows keep their
separate semantic and purchase gates.

**D10 — Surface-specific execute visibility.** The canonical execute workflow is
projected app-only on OpenAI and model-visible on Claude. Provider adapters
control descriptor visibility only; all execution policy remains in shared
control-plane services.

**D11 — Reviewed execution surfaces only.** Generic MCP exports status and
preview capabilities but no purchase, execution continuation, or label artifact
tools. Additional hosts require an explicit reviewed provider profile.

### 3.2 Relay protocol (canonical module: `src/control_plane/relay/protocol.py`)

All envelope, handshake, heartbeat, and state definitions live in this one canonical module, imported by both cloud and desktop sides (per the canonical-data-models rule). Highlights:

- **Device identity:** Ed25519 keypair generated on the desktop when the user enables Cloud AI Features; private key in the OS keychain via the existing `keyring` infrastructure; public key registered cloud-side as a `RelayDevice` bound to `account_id + device_id + fingerprint`. Rotate and revoke flows; revocation immediately severs the session.
- **Account linking:** before registration, Desktop authenticates the human
  independently through Auth0 Authorization Code + PKCE with a loopback
  callback. The desktop OAuth client receives device-management scopes only;
  provider workflow scopes remain confined to Provider Connections. The local
  sidecar receives the callback on an OS-assigned loopback port; no custom-scheme
  OAuth callback is supported.
- **Device management:** register, rotate, revoke, set-active, and unlink require
  Auth0 authentication no older than 10 minutes. Relay PoP alone cannot perform
  human account-management actions.
- **Handshake:** desktop opens outbound `WSS /relay/connect`; cloud issues nonce + `relay_session_id`; desktop returns a short-lived JWT signed with its device key carrying `sub=device_id`, `aud=shipagent-cloud-relay`, account binding, nonce, expiry, and version metadata (`shipagent_core_version`, `registry_contract_version`, `ups_boundary_contract_version`, capability list). Cloud verifies signature, binding, nonce freshness, audience, expiry, revocation, and version compatibility before accepting.
- **Invocation envelopes:** every cloud→desktop invocation is sent over authenticated WSS and carries `relay_session_id`, a strictly increasing per-session sequence number, `relay_invocation_id`, tool name, input hash, deadline, idempotency key, and audit correlation ID. The desktop rejects wrong-session, duplicate, expired, or non-increasing envelopes and retains accepted invocation IDs for recovery. Message-level cloud signatures are a future hardening option, not an MVP requirement.
- **Heartbeat:** version metadata + capability list + opaque active-source fingerprint, refreshed continuously; Redis TTL 60–120 s.

### 3.3 Invocation lifecycle and recovery

States: `queued → sent_to_target → accepted → running → result_returned`, with failure exits `target_offline_before_accept`, `target_disconnected_mid_call`, `deadline_exceeded`, `abandoned`, `recovered_by_poll`.

Timeout ladder: 2 s cloud send → 5 s target accept → 25 s sync hard deadline (under the 30 s provider budget). Tools that may exceed it follow the async contract: immediate `{status: "processing", job_ref, poll_after_ms}` response, polled via `get_job_status`. No MCP session memory; the model passes `job_ref` explicitly.

Recovery: on reconnect, the desktop reports outstanding local jobs and invocation IDs; the cloud reconciles `processing_unknown` invocations to `recovered_by_poll`. Cloud→relay automatic retries are permitted only for invocations that never reached `accepted`. An Execution Grant reservation is released only for those pre-accept failures. At `accepted`, the grant becomes consumed and recovery proceeds through the idempotency record. `execute_shipments` is idempotency-keyed end to end: a duplicate call for the same Approval Request returns the original result, never a second charge.

### 3.4 Ephemeral retention

| Data | Store | TTL |
|---|---|---|
| Relay heartbeat | Redis | 60–120 s |
| Relay session metadata | Redis | disconnect + 5 min |
| Invocation state | Redis | 24 h |
| Job Reference mapping and redacted preview summary | Redis | 24 h |
| Approval Request + one-time Execution Grant | Redis, account + connection + target scoped | short TTL; reserve on dispatch, consume on target accept |
| Approval browser session | Encrypted secure cookie + server-side session state | bounded independently; cannot extend approval expiry |
| Full approval preview detail | Transit only from Execution Target | Never persisted; no-store response |
| Label download reference | Redis, account + connection + target scoped | short TTL; single successful download |
| Label stream lease | Redis, browser-session bound | seconds; never extends reference expiry |
| Rate-limit / loop-breaker counters | Redis | sliding windows |
| Durable cloud authorization audit (hashed approval/grant/tool metadata only) | SQL | 90 days default; configurable 30–365 days; daily purge |

A purge job sweeps Redis key patterns every 5 minutes. The desktop remains the source of truth for jobs, rows, previews, labels, and detailed audit.
Every provider-callable Redis reference also stores and enforces its originating
`provider_connection_id`.

### 3.5 Error envelope contract

Every provider-facing failure is a **schema-valid result**, never an MCP protocol error:

```json
{"status": "blocked|unavailable|processing_unknown",
 "reason": "machine_code", "terminal": true,
 "message": "model-readable instruction stating what the user should do"}
```

Terminal reasons (`target_update_required`, `repeated_tool_call`, `approval_expired`, `approval_rejected`, `target_offline` before accept) instruct the model not to retry. Non-terminal (`approval_pending`, `processing_unknown`) carries the relevant Approval Request or `job_ref` plus polling guidance. Reason codes register as **E-6xxx** in the error registry. Raw UPS `ToolError` payloads always map through the hosted safe-category envelopes.

Execution drift returns terminal `preview_changed` with a new-preview
instruction. It never consumes the stale grant into a shipment job.
Mixed batch completion returns aggregate counts for `completed`, `failed`,
`needs_review`, and `not_started`; no local row details enter provider results.
One-off completion may additionally return its full current-flow tracking
number. Batch completion never returns a tracking-number array.

### 3.6 Ingress guard v2

Extends the existing `RequestControls`: per-account/tool token buckets (exists), canonical input hashing, duplicate-call collapse, in-flight coalescing, a semantic loop breaker emitting the terminal `repeated_tool_call` envelope, and result-size caps from each contract's `max_result_bytes`.

### 3.7 Output profiles

`result_projection.py` gains explicit profiles — `OPENAI_STRUCTURED`, `OPENAI_WIDGET_META` (widget-only payloads, still redacted), `CLAUDE_MARKDOWN` (compact tables, ≤150k-char Claude limit with headroom) — all applying the D4 origin-based redaction rules. Both providers share deterministic handlers; only metadata and formatting differ.

## 4. Slice map — 10 plans, 4 waves

### Wave 0 (serial)

**Plan 1 — Relay walking skeleton.** Canonical protocol module; cloud `WS /relay/connect` + `POST /relay/devices/{register,rotate-key,revoke}`; Redis device-session registry; desktop `relay_key_service.py` + `desktop_relay_client.py`; `RelayExecutionTarget`; `LoopbackExecutionTarget` test fixture. **Exit:** `get_shipagent_status` answered by a real desktop process through cloud `/mcp`, and by loopback in CI. Deliberately the largest slice: splitting cloud/desktop halves would reintroduce fixture drift.

### Wave 1 (parallel after Plan 1 — disjoint file sets)

**Plan 2 — Invocation lifecycle + relay-loss recovery.** State machine, timeout ladder, reconnect reconciliation, degraded envelopes, single-Job-Reference async contract. (`src/control_plane/relay/lifecycle.py`, dispatcher changes desktop-side.)
**Plan 3 — Version gate.** Heartbeat version enforcement against a compatibility matrix derived from `ToolContract.minimum_capabilities`; `target_update_required` envelope. (`src/control_plane/relay/version_gate.py`.)
**Plan 4 — Ephemeral retention + purge + authorization audit.** TTL policy in
`redis_keys.py`, Redis sweeper, daily SQL retention purge, account-deletion
cleanup, legal-hold guard, and thin durable hashed authorization-ledger models.
**Plan 5 — Ingress guard v2.** Loop breaker, dedupe, coalescing, result caps in `request_controls.py`.
**Plan 6 — Provider projections, output profiles + origin-based redaction.**
Surface-specific descriptor visibility; profiles in `result_projection.py`;
origin tagging on workflow inputs; aggregate projection for local-source data;
tracking-number masking rules; unified `prepare_shipments` source schema
projection.
**Plan 9 — Desktop settings + device management** (only needs Plan 1). Cloud AI
Features enablement in settings-remote (browser PKCE login, generate key,
register, status), device list with recent-auth revoke/rotate/set-active/unlink,
relay status indicator, Tauri keychain entitlement check.

### Wave 2

**Plan 7 — Provider execution and approval flow** (needs Plans 2 + 6).
`prepare_shipments` accepts a closed `shipment_source` union for provider-supplied
one-off data, deterministic active-source selection, or an existing opaque local
batch reference, then creates an immutable preview. OpenAI receives a widget-bound
confirmation action whose grant remains widget-private. Claude receives an
opaque Approval Request URL; the Auth0-protected ShipAgent approval page records
approve/reject and atomically creates a server-side Execution Grant. The
approval page is a dedicated cloud frontend, not the provider widget.
It is server-rendered by the control plane with Auth0 code flow, secure
server-side sessions, and CSRF-protected approve/reject actions.
`execute_shipments` receives the Approval Request reference and internally
validates and consumes the grant, cost ceiling, and idempotency binding before
relay dispatch to BatchEngine. Execution rebuilds the canonical purchase payload
and verifies exact preview, selected-rate, amount, currency, row-set, and source
bindings before any UPS create call. The provider execution mode adds a
category-aware shared stop flag around the existing row-isolated BatchEngine;
then `get_job_status` and
`create_label_download` completes the flow with an Auth0-account-bound,
single-use reference and lease-then-consume, no-persistence streaming
(desktop→cloud→browser, no cloud persistence). It creates one job-level artifact:
direct PDF for one label or target-generated ZIP of PDFs + manifest for multiple
labels. Enforce execution and artifact scopes according to the resolved public
scope vocabulary.
The approval page instructs the user to return to Claude; it never dispatches
execution itself.
**Plan 8 — OpenAI widget** (needs Plan 6 schema). `provider-widget`: rates, preview/confirm with the execute button gesture, job progress, label download action; served as MCP Apps HTML resources via existing `ui_resource` fields.

### Wave 3

**Plan 10 — Golden prompt + adversarial corpus** (needs Plans 7 + 8). `tests/provider_golden/prompts.yaml`: tool selection, confirmation behavior on both surfaces, loop retry, target-offline, grant replay, spoofed-relay handshake, PII/raw-UPS leakage, oversized results, missing `job_ref`. Claude API allowlist smoke config (beta `mcp-client-2025-11-20`), MCP Inspector scripts, ChatGPT developer-mode checklist.

### Dependency graph

```
Plan 1 ──┬─→ Plan 2 ──┬─→ Plan 7 ──┬─→ Plan 10
         ├─→ Plan 3   │            │
         ├─→ Plan 4   │            │
         ├─→ Plan 5   │            │
         ├─→ Plan 6 ──┴─→ Plan 8 ──┘
         └─→ Plan 9
```

**Critical path:** 1 → 2 → 7 → 10 (4 sessions). **Peak concurrency:** 6 agents in Wave 1 (Plans 2–6 + 9). Plans 3, 4, 5 are small; 1, 2, 7 are the heavy ones.

## 5. Testing strategy

- Every plan: unit tests + integration test against `LoopbackExecutionTarget`.
- Plans 1, 2, 7: additionally a two-process integration test (real WSS, real Ed25519 handshake, in-memory Redis).
- UPS calls in tests: hosted fixtures and UPS CIE only.
- Claude-surface tests: synthetic data only (the Claude MCP connector is not ZDR-eligible).
- Registry drift tests must pass after every contract change; provider artifacts stay generated via `scripts/generate_provider_artifacts.py` — never hand-edited.
- Registry tests assert that `execute_shipments` is the only public shipment
  purchase tool and that every source variant reaches the same prepare/execute
  confirmation path.
- Registry and hosted-MCP tests assert the four canonical public scopes and
  reject legacy colon-scope exports.
- Projection tests assert `execute_shipments` is app-only for OpenAI,
  model-visible for Claude, and never model-visible in the OpenAI descriptor.
- Export tests assert generic MCP contains no mutating, job-continuation, or
  label-artifact tools.
- Auth tests assert claude.ai and Messages API client IDs resolve to distinct
  Provider Connections even for the same Cloud Account.
- Filter tests assert that Tier-B provider previews are non-mutating and bind the
  expansion into the preview hash, while Tier-C terms block before any row query.
- Projection tests assert that full tracking numbers are visible only for
  provider one-off flows and authenticated job artifacts, never batch tool
  results or local history.
- Security checks land with their slice and are re-attacked in Plan 10: handshake rejection matrix (unregistered key, stale nonce, wrong audience, revoked device, incompatible version), envelope replay, grant one-time/binding properties, per-tool scope enforcement.
- Approval-page tests verify no-store headers, no third-party resources, log
  redaction, no persistence of detailed previews, Auth0 account binding, and
  immutable-preview hash matching.
- Audit tests assert approval-before-accept ordering and reject raw PII, tokens,
  URLs, labels, tracking numbers, and provider prompt content.
- Retention tests enforce the 30–365 day configuration bounds, 90-day default,
  daily cutoff behavior, account-deletion cleanup, and explicit legal-hold
  exception.

## 6. Out of scope

- SaaS worker implementation (only the `ExecutionTarget` seam it will use).
- General workflow handoff, claim, or push-to-desktop execution subsystem. The
  narrow Claude Approval Request flow is in scope.
- Multi-device-per-account routing — one Active Desktop Device per account (ADR 0002).
- New UPS capabilities: void, pickup, paperless, landed cost, raw tools remain unexported to public providers.
- Any modification to the upstream `ups-mcp` package.

## 7. ADR deltas (committed with this spec)

- **ADR 0003 (amended):** per-surface confirmation — OpenAI widget gesture;
  Claude ShipAgent-owned Approval Request gesture; same Execution Grant safety
  properties.
- **ADR 0004 (new):** cryptographic desktop relay identity (Ed25519 PoP, keychain storage, rotate/revoke).
- **ADR 0005 (new):** ephemeral cloud-state retention (TTLs, purge, thin redacted audit).
- **ADR 0006 (new):** relay version compatibility gate.
- **ADR 0007 (new):** origin-based provider redaction.
- **ADR 0008 (amended):** provider-led execution adopted; workflow handoff
  rejected; narrow Claude approval handoff retained.
