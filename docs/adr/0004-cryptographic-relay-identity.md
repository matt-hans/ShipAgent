# ADR 0004: Cryptographic Desktop Relay Identity

## Status

Accepted

## Decision

Each desktop runtime that enables Cloud AI Features generates an Ed25519
keypair. The private key lives in the OS keychain; the public key is registered
cloud-side as a `RelayDevice` bound to account, device ID, and key fingerprint.
Registration follows an independent desktop Auth0 Authorization Code + PKCE
browser login that proves the human's Cloud Account and grants only
device-management scopes.
Relay connections require a proof-of-possession handshake: the desktop signs a
short-lived nonce-bound JWT that the cloud verifies against the registered key,
account binding, audience, expiry, revocation state, and version metadata.
Invocation replay protection relies on authenticated WSS plus session
sequencing: every invocation carries the relay session ID, a strictly
increasing per-session sequence number, invocation ID, deadline, input hash, and
idempotency key. The desktop rejects wrong-session, duplicate, expired, or
non-increasing envelopes. Message-level cloud signatures are a future hardening
option, not an MVP requirement. Keys support explicit rotation; cloud-side
revocation immediately severs the relay session.

Device registration, key rotation, revocation, active-target selection, and
unlink require an Auth0 desktop login no older than 10 minutes. Relay proof of
possession alone cannot authorize these human account-management actions. Target
revocation or replacement invalidates its pending Approval Requests and
unconsumed Execution Grants.
