# ADR 0009: User-Controlled Headless Full-Agent Authority

## Status

Accepted architecture, 2026-10-08. The owner selected an always-on
user-controlled server, approved development, and explicitly approved the
permission split, separately signed-in browser enrollment with local server
confirmation, and restricted secrets on encrypted target storage. Actual setup,
credentials, spending, deployment and paid mutations remain separately gated.

Parent: [#75](https://github.com/matt-hans/ShipAgent/issues/75).
Architecture gate: [#76](https://github.com/matt-hans/ShipAgent/issues/76).
[Recorded hosting selection](https://github.com/matt-hans/ShipAgent/issues/76#issuecomment-6062947290).

## Selected execution profile

The initial Execution Target is an always-on server under the user's control.
It requires no Mac app, desktop runtime, or browser on the server. One account
owns one dedicated target process and persistent data root. The operator owns
availability, infrastructure, model access, carrier access, backups and support.
The actual provider, server, budgets, credentials and deployment remain separate
owner decisions; no expenditure or configuration is authorized by this ADR.
ChatGPT and Claude custom connectors are the intended first client surfaces;
each must be independently qualified before support is advertised.

Keep the relay boundary from ADRs 0002/0005/0007: raw shipment sources,
transcripts, private model continuation, jobs, previews, labels and credentials
stay on the target. The control plane stores only permitted expiring metadata
and redacted durable audit, never raw rows or provider prompts. Transit-only
approved detail and artifact streams are no-store and excluded from logs.
ShipAgent-operated workers and shared multi-account processes are not selected.

## Public authority interpretation

Keep the four public scopes in ADR 0001. Internal granular scopes and target
management scopes are not advertised in provider OAuth metadata.

| Operation | Required public scope | Additional authority |
| --- | --- | --- |
| Target status and exact-reference run/job reads | `shipagent.status` | Active account/connection and exact ownership; read never starts a model or job |
| Submit or continue an Agent Run | `shipagent.preview` | Bounded model budget, exact target, idempotency and conversation revision |
| Cancel future work or pending follow-up | `shipagent.preview` | Exact reference ownership; no void/refund or uncertain purchase-key release |
| Select an existing source and prepare a preview | `shipagent.preview` | Preauthorized session-bound handle and immutable source/settings versions |
| Execute an approved shipment | `shipagent.execute` | Reviewed surface, explicit trusted human approval, one-time server-side Execution Grant and durable exact-target acceptance |
| Create a label download reference | `shipagent.artifacts` | Originating connection and exact target/job; same-account browser authentication at redemption |
| Set up credentials/sources, enroll/rotate/revoke/replace targets | None of the four | Separate authenticated operator/account management; no model-callable setup |

The preview permission includes potentially charged ShipAgent model turns.
Consent and onboarding must say so; a ChatGPT/Claude subscription is not a
backend API credential or spending authorization. Read-only shipping mode can
still use paid model work and must not be annotated as a read-only tool when it
creates durable state. Initial development uses scripted providers and synthetic
boundaries; no live model or carrier access is part of this decision.

Every reference is scoped to account, originating Provider Connection/link
generation, exact target and conversation/run as applicable. Possession is never
authorization. Reconnection cannot resurrect a revoked link. Source selection
cannot establish credentials or change an unrelated session's active source.

## Headless enrollment extension

This extends desktop-specific wording in ADRs 0001/0002/0004/0005 only for the
selected target profile. Existing desktop behavior stays unchanged.

1. The local administrative CLI generates an Ed25519 key on the server and
   creates a short-lived enrollment bundle containing only the public key,
   fingerprint and random single-use challenge. The private key never leaves
   the target. No account identity supplied by that bundle is trusted.
2. An operator opens a separate first-party enrollment page in an ordinary
   browser. Auth0 Authorization Code + PKCE establishes the human/account.
   Management requests require an explicitly registered operator-client
   purpose, `relay:device:manage`, and verified `auth_time` no older than ten
   minutes. Provider-client tokens fail even if they contain that scope.
3. The page shows the exact public-key fingerprint and account for explicit
   enrollment. Browser sessions, PKCE/state, CSRF and replay protections apply.
   The service issues an authenticated enrollment receipt bound to that
   account, public key, target identity, challenge and original expiry.
4. The operator installs and explicitly confirms this receipt using local
   administrative access on the server. The target verifies it, pins the
   expected account/target/key, and proves possession through the existing
   nonce-bound relay handshake. A copied public bundle cannot make a running
   server adopt another account. A remote registration alone does not activate
   the server or replace an existing account binding.
5. Challenges expire within five minutes, cannot be extended by reads, and
   are consumed atomically. Wrong-account/key, replay, expired, copied and
   concurrently claimed bundles/receipts fail closed. Cross-account reuse of
   an enrolled key is denied. Local account replacement requires explicit
   fresh operator action and invalidates pending workflow authority.
6. Subsequent authenticated WSS sessions use proof of possession, sequence,
   invocation/input identities, deadlines and capability/version gates from
   ADRs 0004/0006. Short-lived operator authorization is discarded, never
   retained as a daemon refresh token. Rotate/revoke/replace/unlink retains
   the recent human-authentication gate; proof of possession alone cannot
   manage the account or target.

No callback listener or desktop keychain is required on the server. No Auth0
Device Authorization grant, new client configuration or credential provisioning
is presumed. The specific deployment's approved operator client and issuer must
prove the browser flow and fresh authentication claim before enrollment is
admitted outside local synthetic tests.

## Target secret-storage profile

Use a dedicated unprivileged Unix service identity and an operator-owned
encrypted persistent volume. The data/secrets roots are owner-only directories
(mode 0700); relay keys and configured model/carrier/commerce secrets use
owner-only regular files (mode 0600). Reject symlinks, wrong ownership, insecure
permissions and missing storage. Never silently fall back to desktop keychain,
public configuration, chat input, a shared process environment or another
account's credentials. Encryption keys, volume unlock and recovery are
operator-managed; file permissions do not claim protection from the server's
root administrator. Backups require equivalent protection and bounded retention.

Dedicated gateway children receive only the credentials they need. Relay
identity is never exported through the existing KeyringStore environment-sync
behavior. Actual secret entry, encryption setup, permissions changes on a
production server, OAuth grants and account configuration require separate
operator authorization. Synthetic tests use only disposable local data roots.

## Approval profile remains a later gate

This ADR does not resolve the ChatGPT full-detail approval conflict in
ADRs 0003/0007/0008. Do not send imported rows in widget-private metadata or
approve batches from aggregates. Paid mutations, execute exports, approval
issuance and label access stay disabled until their complete reviewed
preview/gesture/acceptance/reconciliation/artifact slices pass. A model's
approval argument or conversational agreement cannot substitute for human proof.

## Consequences and acceptance evidence

- Keep the account-dedicated target boundary and isolate conversation snapshots,
  settings and gateway children even for two sessions on the same account.
  The local administrative API and process-global active source are not public
  multi-account or multi-session isolation boundaries.
- Persist an accepted Agent Run before returning its reference. One active
  fenced writer owns each conversation; stale leases/results cannot overwrite
  a newer turn. Preserve original lifetimes and non-reusable uncertain effects.
- Qualify target storage separately: SQLite WAL with synchronous NORMAL is not
  proof of power-loss durability. The implementation must document the tested
  storage/failure model, and cannot replay accepted purchases after restore.
- Review [the architecture packet](../plugin-backend/architecture-authority.md)
  and real protocol, persistence, enrollment, source-isolation and privacy
  tests. Local synthetic evidence is not actual-client or deployment readiness.
- Keep milestones #76–81 open until their own applicable acceptance is met;
  this does not complete or modify unrelated #30/#41.
