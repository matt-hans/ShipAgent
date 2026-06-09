# ADR 0003: Provider Confirmation And Deterministic Execution Safety

## Status

Accepted

## Decision

Every mutating operation uses a `prepare_*` tool followed by a matching
`execute_*` tool. Execution requires provider-native approval plus a one-time
ShipAgent token bound to account, connection, device, immutable preview, policy,
cost ceilings, expiry, and idempotency key.

