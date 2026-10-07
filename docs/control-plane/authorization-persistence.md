# Dormant authorization persistence (issue 64)

This slice implements the persistence prerequisite in [Plan 4](../superpowers/plans/2026-06-30-openai-claude-connector-04-ephemeral-retention-authorization-audit.md) and [ADR 0005](../adr/0005-ephemeral-cloud-state-retention.md). It does not implement an Execution Grant authority, approval endpoints, reserve/consume/reconciliation, provider exports, or a deployment. It never produces `ExecutionGrantBinding` and is not injected into the hosted tool gate.

## Shared keys and immutable lifetimes

`RedisKey` remains the shared policy owner. Approval Requests use `sa:approval:request:<canonical approval ID>` and Execution Grants use `sa:approval:grant:<canonical approval ID>`. Each original lifetime is at most **900 seconds**. Invocation and Job Reference lifetimes are **86400 seconds**. Plan 2's accepted `sa:jobref:` spelling wins over Plan 4's conflicting `sa:job_ref:` snippet; there is no parallel namespace. `invocation()` delegates to `relay_invocation()`.

The existing 90-second live relay-session behavior is unchanged. Plan 4's 300-second *after-disconnect* relay policy is separate lifecycle work, not a reason to silently change the live-session constant here.

`AuthorizationStateStore` persists only `AuthorizationMetadata` and its original timestamps/revision. It uses Redis server time, atomic `SET NX PXAT`, and exact-value CAS with `KEEPTTL`. Duplicate create, reads and successful CAS never refresh expiry; CAS cannot recreate a missing key. A missing, expired, TTL-less, malformed, cross-account or extended-expiry key denies with a closed error. Only newly minted approval IDs may create new state. Create is an internal storage primitive, not approval or grant issuance. Future authority code must still check live account/connection/target/preview and protect state publication against account deletion; these primitives alone authorize nothing.

The Redis sweeper checks the shared allowlisted ephemeral patterns every **300 seconds** when enabled. It atomically checks and deletes TTL-less keys, preserving active TTLs. Account cleanup deletes only matching approval/grant metadata. Legal holds retain SQL evidence, never live executable state.

## Ledger and failure contract

`AuthorizationLedgerService.record` accepts only the frozen, validated metadata type plus closed event, transition and result codes. IDs follow existing canonical grammars; hashes are lowercase SHA-256; amounts are strict nonnegative signed-64-bit minor units paired with the canonical registry currency. Account existence and Provider Connection ownership are checked under account/connection row locks. No arbitrary payload column, raw subject, rows, labels, tracking number, token, URL, prompt or executable credential is accepted. Ledger rows cannot reconstruct a grant or resurrect approval.

The caller owns the SQL transaction. `record` flushes, **it does not commit**. The future authority must:

1. Commit required ledger evidence before publishing an enabling Redis change
2. Deny on SQL validation/write/commit failure, Redis failure, or uncertain publication
3. Treat a committed ledger row with missing Redis state as evidence only
4. Never replay SQL history into active Redis grants
5. Keep accepted/ambiguous target reconciliation non-reusable until the authority resolves it (issue 67)

There is deliberately no distributed-transaction success claim. If SQL commits and Redis fails, an evidence-only row can remain. If account cleanup removes Redis and the SQL transaction later fails, the state remains unavailable; no automatic restoration occurs. Caller cancellation must not be interpreted as proof of nonpublication.

## Retention, holds, account deletion

SQL retention defaults to **90 days**, configurable from **30 through 365** with `SHIPAGENT_AUDIT_RETENTION_DAYS`. A daily pass removes expired audit and ledger rows and old *released* legal-hold rows. An active explicit hold is the only retention exception; account suspension/status never implies a hold.

Legal-hold placement/release and their redacted audit events share a caller-owned SQL transaction. These are internal privileged operator APIs, not authenticated public endpoints; `release(hold_id)` is not an account-scoped user operation. Account row locks serialize placement/release against purge/deletion. Both audit and ledger cleanup entrypoints check holds, as does account deletion. Direct SQL access is privileged and must not bypass these services. Holds block account deletion. After release, deletion removes introduced records, audit, provider connections and account state. Account cleanup requires its state store; Redis failure prevents SQL deletion.

`SHIPAGENT_RETENTION_BACKGROUND_TASKS_ENABLED=true` explicitly enables the two workers in the **control-plane app only**. Default is false because this feature is dormant. Starting workers performs an initial pass, then uses 300/86400-second intervals. Independent loops retry failures with fixed sanitized log codes and cancel/reap on shutdown. A future authority/deployment must enable retention as part of enabling state creation. No new SQL/Redis connections, Auth0 credentials or hosted grants are required by local API, CLI, desktop or shipping. FastMCP already brings the Redis Python client transitively through Docket; absence of a required Redis *service* is the invariant, not a claim that the client library can be removed.

## Real-store reproduction

The fixtures launch fresh unprivileged PostgreSQL and Redis processes, create isolated 0700 temporary data directories, bind only randomized **127.0.0.1** TCP ports, disable PostgreSQL Unix sockets and Redis snapshots/AOF, and stop/reap processes in `finally`. They never accept an external database URL or existing Redis server. Fixture PostgreSQL trust authentication is exclusively for synthetic local data and never a deployment configuration. No model/carrier/production calls occur.

This executor rejects AF_UNIX socket creation with OS `Operation not permitted`, including after an approved execution escalation; there was no tool/reviewer denial of running services. AF_INET loopback binding is supported. The approved TCP alternative changes no firewall, security or network settings. Redis's host overcommit warning is left unchanged because persistence/replication are disabled and changing host sysctls is out of scope.

On compatible Debian 13 amd64 (with its base runtime libraries and `dpkg-deb`):

```sh
python scripts/setup_control_plane_test_services.py --root /path/to/workspace/test-services
export SHIPAGENT_TEST_SERVICE_ROOT=/path/to/workspace/test-services/extracted
.venv/bin/python -m pytest tests/control_plane/persistence -q
```

An unset service-root variable produces explicit skips; a configured missing/broken service fails. The real-store acceptance run always sets it. `scripts/control_plane_test_packages.json` records exact official Debian HTTPS URLs, byte sizes and SHA-256 values verified against the trixie package index on 2026-10-07. Extraction uses only `dpkg-deb -x`; no maintainer scripts, system install, repository/key additions, or global environment changes. The setup command is separate from application installation. On other systems, use a compatible Linux test environment; these fixtures do not claim native macOS coverage.

Verified service/tool versions:

- PostgreSQL 17.11, Debian `17.11-0+deb13u1` (server, client and libpq)
- Redis 8.0.2, Debian `5:8.0.2-3+deb13u2` (server/tools)
- liblzf `3.6-4+b3`, jemalloc `5.3.0-3`
- Python 3.12.14, pytest 9.0.2, SQLAlchemy 2.0.46, asyncpg 0.31.0, redis-py 7.1.0, Alembic 1.18.4 (verify installed manifest before rerunning)

These binaries are **local test tools, not shipped application dependencies**. Packaged Redis offers a choice of RSALv2, SSPLv1 or AGPLv3, with separate component notices; it is not described as BSD-only. PostgreSQL/libpq use the PostgreSQL license plus component notices. liblzf and jemalloc principally use BSD-2-Clause with additional packaged component notices. The full exact notices remain in each manifest-listed `usr/share/doc/<package>/copyright` file in the extracted tools; neither binaries nor vendored notices are bundled into ShipAgent.
