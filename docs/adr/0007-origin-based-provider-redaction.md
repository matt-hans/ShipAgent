# ADR 0007: Origin-Based Provider Redaction

## Status

Accepted

## Decision

Provider visibility is determined by data origin, not blanket field bans. Data
the user supplied through the provider conversation may be echoed back. Data
originating from locally imported sources is provider-visible only as
aggregates — never row arrays or per-row addresses. UPS credentials, account
numbers, raw UPS payloads, label bytes, and keyring contents are never
provider-visible regardless of origin. Tracking numbers from the current
provider flow are shown in full; tracking numbers from local job history are
masked. Labels are delivered as short-lived signed download URLs whose bytes
stream desktop-to-browser without cloud persistence.
