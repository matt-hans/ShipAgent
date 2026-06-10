# ADR 0003: Provider Confirmation And Deterministic Execution Safety

## Status

Accepted (amended 2026-06-10)

## Decision

Every mutating operation uses a `prepare_*` tool followed by a matching
`execute_*` tool. Execution requires provider-native approval plus a one-time
ShipAgent token bound to account, connection, device, immutable preview, policy,
cost ceilings, expiry, and idempotency key.

## Amendment (2026-06-10)

Confirmation is per-surface. On OpenAI Apps, `execute_*` is triggered only by
the confirmation widget's button — a user gesture, not a model-initiated call.
On Claude surfaces, conversational confirmation is permitted, backed by Claude's
native tool-approval prompt. Both paths consume the same one-time token; neither
surface can execute a shipment the user has not seen priced.

