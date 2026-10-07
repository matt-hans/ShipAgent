# Interactive and auxiliary workflow confirmation

The shared conversation service exposes the same deterministic workflows to
Anthropic Messages, OpenAI, Gemini and the scripted test provider. Provider
adapters contain no pickup, document or shipment decisions.

## User authority

- Interactive shipping still creates a priced `preview_ready` job. The existing
  job confirmation endpoint executes it. The assistant cannot call `batch_execute`
  or a raw carrier shipment tool, even with an approval flag.
- `rate_pickup` validates one closed payload, obtains a finite nonnegative quote,
  and emits the existing `pickup_preview`. Its Confirm button calls
  `POST /conversations/{id}/workflow-confirmation` directly, never the model.
  `schedule_pickup` calls from a model are always denied.
- `cancel_pickup` prepares a cancellation `pickup_preview`. An exact PRN is
  required at execution. Account lookup resolves one unambiguous pending PRN at
  preparation; if there are several, the user must choose a PRN.
- Document attachment/deletion prepare `paperless_result` cards with
  `push_preview` / `delete_preview` actions. Their buttons use the same trusted
  decision endpoint; final `pushed` / `deleted` artifacts retain their existing
  event names and are persisted.
- The document upload form is the explicit upload gesture. Its one-shot
  attachment ID binds the exact user-selected bytes, format, name, type and
  original UPS gateway. The model can consume that grant once; it cannot supply
  bytes or change any of those fields. Later uploads supersede older requests,
  including out-of-order connection completion. Session teardown revokes them.

The decision body contains only `confirmation_token` and `decision`
(`confirm` or `cancel`); extra payload fields are rejected. Pending actions own
an immutable serialized payload and the original gateway identity. Confirmation
consumes the action before gateway acquisition or dispatch. Cancellation also
consumes it. New chat turns, replaced preparations (including failed pricing),
expiry and session teardown invalidate pending authority. Previews expire after
10 minutes; an already-confirmed action is never automatically re-armed.

Carrier exceptions, interrupted calls and unrecognized success responses have
an unconfirmed outcome. Check carrier status before trying a new operation.
The original confirmation cannot be retried, and the client disables that card.
The auxiliary gateway operations also reject the historical 503/upstream retry exception. They make exactly one carrier attempt; pre-existing shipment-only retry policy is unchanged. Confirmation
and outcome events are recorded in the redaction-aware decision audit.

## Local data and continued workflows

A successful upload returns an opaque current-session `document_handle`. The
provider can use it in `push_document_to_shipment` or
`delete_paperless_document`; deterministic code resolves it locally against the
same gateway. Document IDs, filenames and bytes never have to travel through
the provider. The owner sees the real document/shipment identifiers in the
confirmation card. Explicit user-supplied document IDs remain supported.

The session keeps at most 32 document handles. They are not durable across a
backend restart or session teardown. For older documents, use the ID shown in
Forms History or the owner-facing result. Never retry an uncertain upload just
to recover a handle.

Rate, address and transit tools keep their closed, actionable provider results
and normal assistant text. They have no dedicated domain-card events in the
existing desktop contract. Tracking retains its `tracking_result` card and
history artifact, including current-flow tracking numbers. Pickup, upload and
paperless event names are unchanged; multiple distinct artifacts of the same
kind in one turn are now retained, while duplicate emission is deduplicated by
content. Provider histories still exclude owner-only artifacts.

## Deliberate limits and verification

- A provider-neutral shipment-void workflow is still absent; raw void remains
  denied. This change does not invent one.
- Chat text, model `confirmed` flags and copied tokens are never user authority.
  Older token-only pickup cards require a fresh preview.
- Pickup prices remain carrier estimates. No new carrier service or pricing
  capability is added.
- The legacy SDK remains a compatibility path until issue #40. It shares these
  handlers, and its generic hook now also denies raw document mutations; this
  change does not claim SDK-free packaging.
- Acceptance uses real workflow handlers and local synthetic carrier seams on
  every supported adapter's actual serialized protocol, including a dynamic
  upload-to-attachment chain driven by the returned handle. No live purchases,
  pickups, document uploads, provider spending or release deployment are needed.
