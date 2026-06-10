# ADR 0004: Cryptographic Desktop Relay Identity

## Status

Accepted

## Decision

Each desktop runtime that enables Cloud AI Features generates an Ed25519
keypair. The private key lives in the OS keychain; the public key is registered
cloud-side as a `RelayDevice` bound to account, device ID, and key fingerprint.
Relay connections require a proof-of-possession handshake: the desktop signs a
short-lived nonce-bound JWT that the cloud verifies against the registered key,
account binding, audience, expiry, revocation state, and version metadata.
Invocation envelopes are session-MAC-bound to prevent replay. Keys support
explicit rotation; cloud-side revocation immediately severs the relay session.
