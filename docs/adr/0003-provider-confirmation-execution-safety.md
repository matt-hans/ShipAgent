# ADR 0003: Provider Confirmation And Deterministic Execution Safety

## Status

Accepted (amended 2026-06-10)

## Decision

Every mutating operation uses a `prepare_*` tool followed by a matching
`execute_*` tool. Execution requires an explicit user gesture plus a one-time
ShipAgent Execution Grant bound to account, Provider Connection, exact Execution
Target, immutable preview, policy, exact authorized amount and currency, expiry,
and idempotency key.

One-off shipments, deterministic selections from the active local source, and
optional existing local batches all use `prepare_shipments → execute_shipments`.
There is no separate public one-off purchase tool.

## Amendment (2026-06-10)

Confirmation is per-surface. On OpenAI Apps, `execute_*` is triggered only by
the confirmation widget's button — a user gesture, not a model-initiated call.
The OpenAI projection marks the execute tool app-only, so the model never
receives its descriptor; the widget invokes it through the MCP Apps tool bridge.
On Claude surfaces, `prepare_*` creates an opaque Approval Request that must be
approved on an Auth0-protected ShipAgent web page before ShipAgent mints a
server-side, one-time Execution Grant. Claude receives only the Approval Request
reference; it never receives an execution credential. Desktop prompts may
notify or deep-link to that page but are not required for authorization.
Approval URLs expose only a random 256-bit public locator whose hash maps to the
internal request. The locator is account-bound after Auth0 login, is not an
approval credential, and is invalidated on approval, rejection, expiry, target
replacement, or Provider Connection revocation.
Conversational agreement, model-selected invocation, and Claude host approval
prompts are not ShipAgent approval proof. OpenAI keeps equivalent grant material
in widget-private metadata. Both paths use grants with the same binding and
one-time-consumption properties; neither surface can execute a shipment the
user has not seen priced.

Cloud Approval Requests and Execution Grants belong to the control plane and
are scoped to Cloud Accounts and Provider Connections. They do not reuse
desktop/hosted-tenant confirmation persistence.

The Claude Approval Surface only approves or rejects. After approval, the user
returns to Claude and continues the conversation; Claude calls `execute_*` with
the Approval Request reference. The control plane reserves the Execution Grant
while dispatching and consumes it only when the exact Execution Target durably
accepts the idempotency-bound invocation. A pre-accept failure releases the
reservation within the original expiry; after acceptance, repeated calls return
the original or recovered job.

The Approval Surface cannot approve while the exact bound Execution Target is
offline because full immutable detail is fetched live and never stored
cloud-side. Offline approval fails closed and does not extend request expiry.

Provider-originated execution accepts no price or payload drift in the MVP.
Changed recipient, address correction, package, service, row set, selected-rate
checksum, source checksum, currency, or final amount — including a lower amount
— invalidates the grant and requires a new preview and explicit approval.

Provider-originated batch execution continues after deterministic row-local
rejections that prove no shipment was created. Any ambiguous or systemic failure
that produces `needs_review` stops new rows from launching while already
in-flight calls reconcile. Created shipments are never automatically voided.

Public shipment execution is exported only to provider surfaces with a reviewed
confirmation profile. For the MVP these are OpenAI Apps and Claude. Generic MCP
hosts remain status/preview-only.
