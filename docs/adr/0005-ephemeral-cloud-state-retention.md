# ADR 0005: Ephemeral Cloud-State Retention

## Status

Accepted

## Decision

All provider- and relay-related cloud state is ephemeral and TTL-bound in
Redis: heartbeats (60–120 s), relay sessions (disconnect + 5 min), invocation
state, jobRef mappings, redacted preview summaries, and poll tokens (24 h max).
A purge job sweeps key patterns every 5 minutes. The only durable cloud records
are thin redacted audit events (provider, account, tool, result category,
duration, device fingerprint, correlation IDs). The local desktop runtime
remains the source of truth for jobs, rows, previews, labels, and full audit.
