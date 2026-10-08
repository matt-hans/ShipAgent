# Full-agent plugin architecture and authority packet

Date: 2026-10-08. Initial source baseline:
`049811742f9e0a99b12d579f7eb332eaf1a75ef2`.

This packet implements the architecture work for
[#76](https://github.com/matt-hans/ShipAgent/issues/76) under the approved
[parent and six milestones](https://github.com/matt-hans/ShipAgent/issues/75).
It does not claim those milestones or a deployment are complete.
[ADR 0009](../adr/0009-headless-full-agent-authority.md) records the approved
user-controlled headless profile and authority/enrollment/storage design.

## Boundaries and one synthetic task

1. ChatGPT or Claude authenticates to the **external remote MCP facade** with
   a provider OAuth token. Auth0 subject maps to a Cloud Account; a trusted
   registration plus independently revocable link generation establishes the
   Provider Connection and surface. Text arguments cannot choose either.
2. Submit requires preview authority, bounded task input, explicit mode and
   caller request key. The control plane resolves the exact enrolled target,
   verifies its versions/capabilities, and sends a separately authenticated
   ownership envelope. It does not persist the task text or source bytes.
3. The account-dedicated target atomically records conversation/run identity,
   canonical input hash, source/settings snapshot and original acceptance time.
   Only then may it acknowledge an Agent Run Reference. Retry of the same key
   and input recovers the original run; a conflicting input is rejected.
4. A fenced target worker invokes the existing `process_message` service and
   ShipAgent-owned `ConversationRuntimeSession`. The host never orchestrates
   raw carrier tools. The **internal UPS MCP gateway** remains a distinct
   target-private carrier boundary; it is not the external `/mcp` facade.
5. Deterministic source services retain rows. The inner model receives only
   allowed task text, schema/configuration and safe tool projections. A run
   result is built from allowlisted evidence and accepted events, never raw
   model reasoning, protocol continuation, source samples or tool transcripts.
6. Read requires status authority and the original connection/target reference.
   It returns bounded stable state/events and an authenticated opaque cursor;
   it cannot create a job or invoke the model. At the advertised interval,
   repeated valid polls are permitted under a read-rate budget, rather than
   tripping the identical-model-call guard.
7. A clarification is a quiescent run outcome. Continue requires preview
   authority, exact expected conversation revision and a new turn request key.
   Its atomic acceptance links a new run and increments the revision once.
8. Cancel requires preview authority and ownership. It prevents future model,
   tool and row launches at safe boundaries. It invalidates pending follow-up
   without rewriting past waiting/approval outcomes, does not void shipments,
   and cannot release an uncertain accepted purchase identity.
9. Later shipping preparation creates an immutable preview on the target.
   Trusted live-detail review and explicit human approval are required before
   a server-side Execution Grant can exist. **This path is disabled for the
   synthetic lifecycle tier.** ChatGPT full-detail approval remains a separate
   ADR/product proof gate; Claude's approval page cannot execute.
10. Later execution revalidates the exact approved inputs, amount/currency,
    connection, target, expiry and policy. Durable target acceptance is distinct
    from transport delivery. Ambiguous outcomes become Needs Review, never a
    fresh purchase. Authenticated, one-use label downloads stream from the
    exact target; bytes and manifest remain outside shared cloud storage.

## Isolation and durability choices

A target is account-dedicated, including job DB, settings, sources, labels,
credentials, caches and children. Concurrent conversations additionally need
explicit immutable source/settings contexts and isolated gateway ownership.
The existing process-global gateway or local API cannot be the public session
boundary. Initial implementation does not admit source-backed concurrent runs
until the isolation test demonstrates different snapshots without replacement.

The target owns durable conversations, turns, events and necessary private
provider continuation. The control plane owns expiring reference mappings and
redacted audit. An accepted turn is never represented solely by an asyncio task
or SSE queue. Queued work survives process restart under the same identity;
interrupted work without a proven resumable boundary reports interruption or
Needs Review, rather than automatically replaying a new turn.

Use transactional acceptance and revision updates, one fenced active writer,
lease generations and cancellation generations. A stale worker cannot dispatch
again or commit output after lease loss. Document and test durable storage
settings and fsync behavior; SQLite WAL/NORMAL alone does not prove power-loss
acceptance. A backup restore is a distinct failure model. It cannot restore
consumed grants or cause repurchase; uncertain restoration fails closed.

Provider-visible references and cursors contain no target-local paths or IDs.
Their original expiry is at most the ADR 0005 24-hour reference ceiling. Read,
reconnect and retry cannot refresh it or recover expired approval. Retention
must be enabled with any state creator. Cursor scope covers account,
connection/link epoch, exact target, conversation/run and accepted event range.

## Capability-by-tier admission matrix

The matrix is a set of gates, not a claim that current code qualifies.
Both intended clients require independent evidence on the same candidate.

| Tier | Intended capabilities | Evidence required | Current admission |
| --- | --- | --- | --- |
| T0 local synthetic | Submit/continue/read/cancel via real loopback MCP, scripted inner model and deterministic fake external boundaries | Durable accepted identity, negative scope/ownership tests, privacy canaries, restart/fencing, zero unauthorized effects | Implementation target; no live integrations |
| T1 private read/preparation | Actual ChatGPT and Claude lifecycle, then supported upload/read/immutable preview | Separately approved temporary HTTPS/auth setup and budgets; actual-client OAuth, revocation, source/session isolation; per-capability external-read authorization | Blocked pending #77–79 and actual-client authorization/evidence |
| T2 authorized sandbox | One shipment, then bounded batch, trusted human approval and authenticated labels | Approved surface profile, full immutable detail, durable acceptance/reconciliation, operation-specific policy review and authorized sandbox account | Disabled pending #80; no sandbox credentials assumed |
| T3 bounded live pilot | The same specifically approved shipment cases | Exact transaction authorization and cost disclosure, actual carrier guarantees, support/reconciliation readiness | Disabled; no live spending authorized |
| T4 private production | Only profiles/operations proven in the release pack | Explicit deployment/release acceptance, SLO/cost/capacity limits, backup/restore, incident and data lifecycle ownership | Disabled pending #81 and owner acceptance |
| Public distribution | Only the separately reviewed supported profile | Provider submission approval, eligibility/privacy/support terms and verified actual acceptance | Deferred; no listing submitted |

Status remains the only actual production handler/export at this baseline.
Void, pickup mutation, international document submission and commerce write-back
remain disabled roadmap capabilities. Read-only commerce is additive and is not
advertised until source-specific evidence exists. Managed hosting is unselected.

## Current client-contract review

Official sources checked 2026-10-08:

- [OpenAI authentication](https://developers.openai.com/plugins/build/auth):
  protected-resource discovery, resource/audience validation, PKCE, trusted
  client registration and tool-level auth challenges need actual-client tests.
- [OpenAI MCP server](https://developers.openai.com/plugins/build/mcp-server):
  annotations must describe actual effects; stateful agent submit/continue
  cannot be marked read-only. Annotations do not enforce authorization.
- [OpenAI connection testing](https://developers.openai.com/plugins/deploy/connect-chatgpt):
  protocol inspection precedes testing the actual intended ChatGPT product;
  a public HTTPS endpoint or supported test tunnel requires separate setup
  authority. No tunnel or endpoint has been provisioned here.
- [Claude authentication](https://claude.com/docs/connectors/building/authentication):
  resource must equal the entered MCP endpoint including its path; discovery
  begins with HTTP 401, PKCE uses S256, and registration/refresh timing need
  real-client evidence. Available registration modes are not interchangeable.
- [Claude review checklist](https://claude.com/docs/connectors/building/review-criteria):
  directory review and legitimate upstream API use are separate acceptance
  requirements. Generic connector documentation does not approve this
  product's paid shipping or its proposed human-approval surface.

- [OpenAI plugin guidelines](https://developers.openai.com/plugins/plugin-guidelines)
  and [monetization](https://developers.openai.com/plugins/build/monetization):
  commerce rules distinguish eligible physical goods from services and describe
  specific checkout paths. They do not expressly classify ShipAgent carrier-label
  billing or approve the proposed app-only flow. Public-directory eligibility
  therefore remains unresolved, without claiming that private shipping is
  categorically prohibited. A generic executor cannot hide unreviewed actions.
- [OpenAI UI](https://developers.openai.com/plugins/build/chatgpt-ui): use the
  standard MCP Apps resource/bridge and feature-detect optional host extensions.
  UI visibility is not server-verifiable proof of a human gesture.
- [Claude connector building](https://claude.com/docs/connectors/building):
  private custom connectors and reviewed directory listings are distinct.
  The directory checklist excludes financial-asset transfers but does not
  expressly classify a shipping-label purchase; that ambiguity is not approval.

Concrete baseline drift: protected-resource metadata advertises internal and
management scopes and uses only the origin; current Provider Connection lookup
collapses account/client/surface without a distinct authorization-link epoch;
per-tool OAuth metadata/challenges need reconciliation. These are required
repairs before T1, not reasons to weaken target identity or grant authority.

For each client, shipment purchase/void/pickup/document submission/commerce
write-back remain **policy and implementation gated**. The above technical
pages do not establish affirmative eligibility for each operation. Required
provider clarification, if any, needs owner-approved outreach. Technical local
or sandbox success does not imply public-listing or paid-operation approval.

## First implementation and review slices

1. Enforce the approved management boundary through real registration/rotation/
   activation/revocation endpoint tests: provider-purpose tokens with accidental
   management scope are denied; trusted operator and existing desktop clients
   still require fresh login and account ownership. This prevents the new
   headless enrollment from inheriting a scope-only authority check.
2. Add the smallest complete T0 submit-to-result path through real loopback MCP,
   a durable account/connection/target-bound local run store, and the existing
   conversation service with a scripted provider. Test accepted retry and
   conflict, read without a model call, wrong ownership, denied mutation and
   sanitized output. Keep production exports off until the target qualifies.
3. Extend that same path with clarification/continue, durable ordered cursors,
   interruption/restart and cancellation/fencing. Add real-store failure and
   concurrent conversation/source-isolation evidence before source admission.
4. Reconcile metadata/resource/scope/link-generation contracts before actual
   ChatGPT/Claude enrollment. Actual client access requires an approved bounded
   HTTPS deployment, accounts and cost/credential setup; stop at that gate.

Each slice follows red/green tests, an atomic commit, exact-head independent
review, draft PR, same-head guarded merge, and fresh main verification. Changes
to these gates are surfaced rather than silently chosen. The complete #77
acceptance remains required even when an earlier repair is independently merged.

## Open human and external gates

The owner approved architecture only. Still required at the affected stage:
server/provider and control-plane destination, named operator/support ownership,
budgets and model/carrier account setup, actual OAuth client configuration,
ChatGPT full-detail approval ADR review, operation-specific policy allowance,
sandbox/live authorization, deployment and final release acceptance. Milestone
#76 remains open while its applicable policy/authority acceptance is incomplete;
local T0 work can proceed under the approved architecture without claiming an
external rollout gate has passed. No macOS qualification is a prerequisite.
