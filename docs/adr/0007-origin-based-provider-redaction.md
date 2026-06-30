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
one-off provider flow are shown in full. Tracking numbers from active-source or
existing-batch flows are aggregate-only in provider results and available in the
authenticated artifact manifest; tracking numbers from local job history are
masked. Labels are delivered as short-lived signed download URLs whose bytes
stream desktop-to-browser without cloud persistence. Possession of a
provider-visible label URL is not sufficient authorization: download also
requires an Auth0 browser session bound to the same Cloud Account, and the
opaque reference permits one successful download.

A completed job exposes one downloadable artifact. A single-label job streams
its PDF. A multi-label job streams a ZIP generated on the Execution Target with
opaque PDF filenames and a first-party manifest containing ordinal,
current-flow tracking number, and status but no recipient PII. Neither ZIP nor
manifest is persisted cloud-side.

The Auth0-protected Claude Approval Surface is a ShipAgent-owned confirmation
boundary, not a provider-visible result. It may display full immutable preview
detail fetched live from the active Execution Target, including locally sourced
recipient and package fields, provided that detail is never persisted,
provider-visible, model-visible, logged, or sent to third parties.
