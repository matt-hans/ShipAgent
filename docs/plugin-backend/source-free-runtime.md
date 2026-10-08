# Source-free conversation prerequisite

This is an internal prerequisite for [milestone 2 (#77)](https://github.com/matt-hans/ShipAgent/issues/77),
under [ADR 0009](../adr/0009-headless-full-agent-authority.md). It is not the
completed full-agent MCP facade, a durable run store, or a public export.

## Ownership

A trusted target-side caller constructs a `SourceFreeConversationConfig` with an
already configured provider client and gives it to a new `AgentSession` (directly
or through `AgentSessionManager.get_or_create_session`). The profile is pinned
for that session's lifetime. Omitting it on a later lookup preserves it;
reconfiguration of an existing local or restricted session is rejected. Invalid
profile objects cannot silently fall back to the local conversation path.

The caller owns accepted user ingress, its stable turn IDs, account/connection/
exact-target binding and durable persistence. This adapter consumes only that
session's authored history and completed runtime events. It does not resolve
credentials or read the local API's active source, settings, contacts or stored
history. It does not write local conversation/audit state; the future durable
run owner must record accepted turns, projected events, cancellation and private
continuation on the target before it acknowledges the relevant operation.
No durable acceptance or crash-recovery claim is made by this seam.

## Runtime and safety

`process_message` remains the canonical entrypoint and dispatches the pinned
profile before any ambient persistence or gateway work. The source-free adapter
uses the existing `ConversationRuntimeSession`; it introduces no second model
reasoning loop. Local conversation behavior uses the unchanged default path.

The profile exposes an empty workflow catalog. Independent runtime policy denies
invented/unadmitted calls before dispatch, including setup, raw carrier, purchase,
contact, file/URL and source calls. A nonempty admission list never bypasses the
existing purchase-confirmation policy. The optional runtime admission/audit
parameters are trusted internal configuration, never model or provider fields.

Only completed privacy-checked text and a closed generic error can leave this
adapter. Raw tool arguments, artifact events, provider error detail and private
continuation are not forwarded. The later public facade still needs its own
origin-safe structured evidence projection; adapter text is not permission to
relay arbitrary inner-runtime output to a host.

Each turn uses the session lock and generation guard. Cancellation of a waiting
caller cannot interrupt the active owner. Explicit stream closure closes the
owned iterator, releases the lock and restores inherited audit/turn contexts.
A replaced runtime object is stopped and rebuilt rather than trusted because
an older profile marker remains. History rebuild uses accepted turn identity,
preserves completed authored pairs and excludes queued future ingress.

The source-free model-turn default is three and the internal allowed range is
one through five. This is a bounded prerequisite/test profile, not a production
spend, token, wall-time or operational SLO guarantee. Those limits belong to the
durable run admission/supervision layer and must pass milestone acceptance.

## Verification boundary

`tests/services/test_source_free_conversation.py` drives the actual canonical
service and shared runtime with a scripted model boundary. Its checks include:

- Forbidden ambient reads/writes and model-input canaries
- Invented tool denial, absent declarations and preserved purchase gates
- Pinned profile, alternate-entrypoint denial and runtime replacement
- Queue-versus-active cancellation and explicit stream-close cleanup
- Exact-turn history rebuild, repeated text and excluded queued future work
- Independent session histories/providers and closed provider errors

The wider conversation/runtime suite checks default local behavior. Every new
behavior's RED/GREEN evidence and final source identity are retained with the
PR verification; required broader checks and skips are reported separately.

Still required: durable target-owned acceptance/revisions/events, authenticated
MCP submit/continue/read/cancel, reference/cursor lifetimes, worker fencing,
restart/restore semantics, budgets, source-backed session isolation, enrollment,
real client OAuth and all later shipment/approval/artifact gates. Production
remote MCP remains status-only in this slice.
