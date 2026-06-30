# ADR 0005: Ephemeral Cloud-State Retention

## Status

Accepted

## Decision

All provider- and relay-related cloud state is ephemeral and TTL-bound in
Redis: heartbeats (60–120 s), relay sessions (disconnect + 5 min), invocation
state, Job Reference mappings and redacted preview summaries (24 h max),
Approval Requests, one-time Execution Grants, and label download references. A
purge job sweeps key patterns every 5 minutes. The only durable cloud records
are thin redacted audit events and a hashed authorization ledger. The ledger may
contain opaque Approval Request IDs, preview and purchase-scope hashes,
authorized amount/currency, approving subject hash, Provider Connection ID,
Execution Target fingerprint, Execution Grant transitions, idempotency-key hash,
result category, correlation IDs, and timestamps. It never stores raw PII, row
data, labels, tracking numbers, tokens, URLs, or provider prompts. The local
desktop runtime remains the source of truth for jobs, rows, previews, labels,
and full audit.

Durable cloud audit defaults to 90-day retention and is purged daily. A
deployment may configure 30–365 days. Cloud Account deletion purges its audit
rows unless an explicit, separately audited legal hold exists; legal hold is
never inferred from account state or operator convention.

The Auth0-protected Claude Approval Surface may fetch full immutable preview
detail live from the active Execution Target so the person can make an informed
decision. That detail is transit-only: responses use `Cache-Control: no-store`,
contain no third-party resources, are excluded from application and access
logs, and are never written to Redis or SQL.

Label download references are short-lived and Cloud Account scoped. Download
requires an authenticated browser session for the same account. Label bytes
stream from the Execution Target through the control plane and are never
persisted, cached, or logged cloud-side. A download uses an exclusive
browser-session-bound lease: the reference transitions `ready → streaming →
consumed`, and an interrupted stream returns to `ready` only after the short
lease expires and only within the original reference lifetime.
