# Dormant Execution Grant prerequisite qualification (issue 51)

Reviewed evidence date: **2026-10-08 UTC**.

## Decision and scope

The four prerequisites in [issue #51](https://github.com/matt-hans/ShipAgent/issues/51)
are satisfied for the **dormant authority/store implementation** at main
`1616278768ec6d1774801979494d06287279782f`. Each has a documented design and tests
against real disposable Redis/PostgreSQL. This record supports closing that
bounded verification gate. It does **not** authorize production authority
injection, approval UI, non-status hosted handlers/exports or deployment.

Issue #51 originally described missing behavior in the PR #50 protocol/fake.
The implementations subsequently landed separately in [PR #65](https://github.com/matt-hans/ShipAgent/pull/65)
(bounded gate), [PR #68](https://github.com/matt-hans/ShipAgent/pull/68) (issue #64
persistence), [PR #69](https://github.com/matt-hans/ShipAgent/pull/69) (issue #66
lifecycle/recovery), and [PR #70](https://github.com/matt-hans/ShipAgent/pull/70)
(issue #67 real authority). The original issue is an acceptance gate, not a
claim that the remaining connector or production enablement work is complete.

## Exact source and evidence provenance

| Evidence | Source identity | Observed result |
| --- | --- | --- |
| Fresh merged-main smoke | Main `1616278768ec6d1774801979494d06287279782f` | **119 passed, 0 skipped**, pytest exit 0 |
| Earlier full guarded backend run | Candidate `9a5021d69ec72f40741626227815e4ea39296d38` | **5,251 passed, 29 skipped, 19 warnings**; whole `src/` + `tests/` Ruff passed |
| Earlier independent review | Same exact candidate `9a5021d69ec72f40741626227815e4ea39296d38` | **450 passed**: 447 repository tests plus 3 reviewer-owned integrations; 12 reserved-ID skips; changed-Python Ruff passed |
| [Merged-main CI](https://github.com/matt-hans/ShipAgent/actions/runs/37715171604) | Main `1616278768ec6d1774801979494d06287279782f` | Completed **success**: Docker build/health/smoke, provider artifact verification, cleanup |
| [Candidate CI](https://github.com/matt-hans/ShipAgent/actions/runs/37714060562) | Candidate `9a5021d69ec72f40741626227815e4ea39296d38` | Completed **success** |

Both commits have Git tree `9adc336440b0cdaedd82e7d9ec376c9c9de9538a`.
The [pinned real-store test sources](https://github.com/matt-hans/ShipAgent/tree/1616278768ec6d1774801979494d06287279782f/tests/control_plane/persistence)
define the assertions qualified here; later changes require their own evidence.
The clean source snapshots also have identical source-manifest SHA-256
`863102a197f8c1a84f9770efaf2698b301bb017609b40a2d78e2403699f50332`.
The fresh-main snapshot was captured at `2026-10-08T01:57:27.155892+00:00`;
the candidate snapshot at `2026-10-08T01:46:58.695509+00:00`. Source HEAD and
clean status were checked before/after copying. **The earlier full and independent
candidate runs are not fresh-main runs.** This documentation-only qualification
does not change product code, tests, exports, configuration or dependencies.

The record was checked against retained command, source-origin, test-log and
supervisor receipts: `issue67-main-1616278-smoke`, `issue67-full-9a5021d`, and
independent `verification-9a5021d`. Public PR #70 records the final candidate
verification and scope. The workspace-only harness and reviewer supplemental
tests are not shipped application dependencies or repository test files.

## Requirement-by-requirement acceptance

### 1. Settlement timeout and acceptance reconciliation

Design: the [gate contract](../components/execution-grant-authority-contract.md)
gives consume plus fallback hold one five-second monotonic deadline. Repeated
cancellation does not reset it. The [real authority](redis-grant-authority.md)
bounds I/O to two seconds by default (five maximum) and bounds SQL transaction
waits. [The shared lifecycle](invocation-recovery.md) distinguishes exact durable
acceptance, permanently fenced nonacceptance and unknown evidence. Recovery
keeps the original target, purchase key, generation, invocation and job; unknown
evidence never authorizes a second dispatch.

Real-store assertions, all included in the fresh-main smoke:

- [`test_grant_settlement_faults.py`](../../tests/control_plane/persistence/test_grant_settlement_faults.py):
  `test_delayed_cancelled_settlement_cannot_downgrade_later_state` bounds each
  consume/release/hold wait and then completes the delayed real Redis CAS. Stale
  writes cannot downgrade held, replacement-reserved or revoked state.
  `test_real_settlement_write_with_lost_response_remains_fenced` loses the reply
  **after** successful real writes; a failed reply is never mistaken for rollback.
- [`test_grant_process_recovery.py`](../../tests/control_plane/persistence/test_grant_process_recovery.py):
  lost target acceptance replies and abrupt authority termination after
  persisted acceptance recover the same job and one target effect. Target and
  authority/application restarts construct fresh clients.
- [`test_grant_recovery.py`](../../tests/control_plane/persistence/test_grant_recovery.py):
  the gate retains the original hidden owner; ambiguous results cannot return
  accepted success; lost acceptance-evidence write replies are read back and
  normalized only from exact persisted evidence.

Fake-backed gate deadline/cancellation tests remain supporting unit evidence;
they are not used as the real-store proof.

### 2. Original expiry and lease recheck at consume

Design: ordinary consume requires the exact owner/fence, persisted acceptance,
live lease and original authorization expiry. Redis uses server time and
existing-key CAS with original TTL. Expiry means denial, never availability or
renewal. Exact accepted truth can still be recovered after grant expiry through
an audit-only SQL path, without recreating executable authorization.

Real-store assertions, included in the fresh-main smoke:

- `test_ordinary_consume_after_lease_requires_positive_evidence_reconciliation`
  in `test_grant_settlement_faults.py` denies ordinary consume after lease expiry;
  privileged persisted-evidence settlement preserves both original deadlines.
- `test_accepted_recovery_after_lease_and_original_expiry_is_audit_only` in
  `test_grant_recovery.py` recovers the original job and one effect after grant
  expiry, records hashed consumed evidence and verifies the Redis grant remains
  absent. Both reserve and recovery-callback reserve deny.
- `test_positive_proof_releases_held_owner_after_lease_without_renewing_authorization`
  keeps the original key/expiry and rejects stale callbacks after proof-backed
  generation advancement. The shared persistence suites additionally cover
  server-time expiry, TTL-less/malformed state, partial pair loss and retention.

### 3. Failed release/hold and cancellation during reserve

Design: reserve atomically installs exclusive ownership before dispatch. Required
hashed SQL evidence commits before an enabling Redis CAS; fresh account/connection
locks coordinate that CAS with deletion/revocation. Lost replies or cancellation
after publication quarantine the original reservation until evidence-based
reconciliation or expiry to denial. Missing keys cannot be recreated by CAS.
Ordinary release cannot reopen held, consumed, revoked or dispatch-claimed state.

Real-store assertions, included in the fresh-main smoke:

- [`test_grant_authority.py`](../../tests/control_plane/persistence/test_grant_authority.py):
  `test_reserve_cancellation_before_or_after_write_never_returns_owner` exercises
  both sides of the actual write; the post-write case remains in-use.
  `test_lost_reserve_reply_and_expired_lease_never_reenable` denies stranded reuse.
- `test_cancelled_reserve_remote_write_after_account_deletion_cannot_revive`,
  `test_late_pending_create_after_delete_is_inert_and_cannot_activate` and
  `test_real_sql_transaction_failure_prevents_reserve_cas` cover delayed
  publication, deletion and genuine SQL transaction failure.
- The settlement-fault cases in item 1 cover failed/timed-out release and hold
  against real writes and newer states. A release whose positive-proof CAS
  actually committed may permit retry within original expiry despite reply loss;
  no other failed/uncertain settlement is treated as permission to reuse.
- Revoke, fresh-ID collision, corrupt-state, missing-key and stale-owner tests
  ensure neither SQL evidence nor a surviving Approval Request remints a grant.

### 4. Real-store atomic replay and process restart

Design and assertions use the actual Redis authority/lifecycle and PostgreSQL
ledger. Independent processes use separate clients. The deterministic target's
SQLite journal holds synthetic **target-owned acceptance evidence**, not cloud
grants or a second lifecycle/job store.

`test_independent_real_authorities_race_one_grant_and_restart_denies_replay`
starts four authority processes against one grant: exactly one accepted result
and target effect; competitors receive `grant_in_use`, `grant_consumed` or
`reconciliation_pending`. A fresh authority process returns `grant_consumed`
without another effect. The other process-recovery tests verify unchanged job,
effect and Redis expiry after acceptance reply loss/restart, and recovery after
abrupt termination before consume. All three run in the fresh-main smoke.

The candidate's additional independent integrations cover three proof-backed
attempt generations with unchanged purchase/job/deadlines, target/fresh-authority
restart, delayed old sends and revocation immediately after retry reset CAS.
The third supplemental test checks the active legacy status broker against the
actual older desktop decoder. Repository retry/fault and legacy-wire tests also
run on merged main.

**Durability boundary:** Redis itself stays running during these process tests;
the disposable Redis fixture disables snapshots and AOF. This proves atomic
real-store ownership/replay across application/authority/target restart while
Redis retains state. It does **not** prove Redis restart, AOF, power-loss,
replication or failover durability. A production persistence/failure policy and
its qualification remain prerequisites for activation.

## Commands, services, skips and cleanup

The real-store runs explicitly configured `SHIPAGENT_TEST_SERVICE_ROOT` using
the [checksum-pinned service setup](authorization-persistence.md#real-store-reproduction).
An unset service root causes skips and is not acceptance evidence. Configured
missing/broken binaries fail. Services were PostgreSQL **17.11**
(`17.11-0+deb13u1`) and Redis **8.0.2** (`5:8.0.2-3+deb13u2`), with Python
**3.12.14**, pytest **9.0.2**, SQLAlchemy **2.0.46**, asyncpg **0.31.0**,
redis-py **7.1.0** and Alembic **1.18.4**. Full package checksums/licenses and
fixture isolation are documented in that setup guide and its package manifest.

The actual fresh-main pytest command used the following selection in a clean
source snapshot with the workspace defensive offline plugin:

```sh
.venv/bin/python -m pytest -p offline_pytest -q -ra \
  tests/control_plane/persistence/test_grant_authority.py \
  tests/control_plane/persistence/test_grant_recovery.py \
  tests/control_plane/persistence/test_grant_process_recovery.py \
  tests/control_plane/persistence/test_grant_settlement_faults.py \
  tests/control_plane/persistence/test_lifecycle_reattempt.py \
  tests/control_plane/persistence/test_lifecycle_reattempt_faults.py \
  tests/control_plane/relay/test_invocations.py \
  tests/services/test_desktop_relay_client.py \
  tests/packaging/test_sdk_free_runtime.py \
  tests/hosted/test_execution_grant_gate.py::test_default_build_server_fails_closed_for_execute \
  tests/hosted/test_hosted_mcp_registry.py::test_hosted_mcp_server_does_not_register_unbound_catalog_tools \
  tests/control_plane/persistence/test_contract.py::test_retention_is_bounded_and_not_enabled_by_local_settings \
  tests/registry/test_artifact_drift.py
```

The earlier candidate full run used `.venv/bin/python -m pytest -p offline_pytest
-q -ra` and `.venv/bin/python -m ruff check src/ tests/`. Independent repository
verification used `pytest -q` on `tests/control_plane/persistence`, execution-grant
and startup contracts, legacy relay/desktop, hosted registry, artifact drift,
provider projections, CLI factory and API configuration/startup recovery, plus
three reviewer-owned tests. All service processes used synthetic data, isolated
directories and owned loopback ports; no live carrier/model calls were made.

For a checkout without the workspace-only offline plugin, the repository
reproduction command is the selection above **without** `-p offline_pytest`,
after the pinned disposable service setup. Run only in a suitably isolated test
environment without live credentials; omission of the plugin does not reproduce
its defensive network guard. The guard is not kernel isolation and makes no
claim about hostile native code or direct syscalls.

Every recorded run acquired the shared `development-heavy.lock` and used bounded
process-tree supervision with two CPUs, 2,048 MiB sampled aggregate RSS,
five-second TERM and five-second KILL/reap grace. Results:

| Run | Wall limit / observed | Sampled peak RSS | Cleanup |
| --- | --- | --- | --- |
| Fresh-main smoke | 180 s / 31.319 s | 552.379 MiB | Root/supervisor exit 0, verified, zero survivors, no forced cleanup |
| Candidate full | 900 s / 252.586 s | 853.434 MiB | Root/supervisor exit 0, verified, zero survivors, no forced cleanup |
| Candidate independent | 300 s / 30.614 s | 584.832 MiB | Root/supervisor exit 0, verified, zero survivors, no forced cleanup |

The full run's **29 skips** are: one wildcard/non-loopback listener test excluded
by the offline guard; one migration test requiring an ambient PostgreSQL URL
(the separate disposable PostgreSQL migration tests ran); 12 unused public ID
family cases; eight live Shopify cases; four live UPS cases; three absent optional
data fixtures. The independent run's 12 skips are only the unused ingress and
confirmation ID families. **No real-store prerequisite test was skipped.**
The 19 full-run warnings were retained. Earlier missing Node/npx launcher failures
remain failed historical runs; restoring the verified installed Node path led
to the successful final candidate run without a product change.

No duplicate full-suite run was needed for this docs-only acceptance: the new
main smoke contains every mapped grant requirement, and the candidate/main trees
and snapshot manifests are identical.

## Other acceptance conditions and retained blockers

- [Shipment-execution caller obligations](../components/shipagent-shipment-execution.md#execution-grant-gate-issue-46-adr-00030008)
  describe atomic ownership, exact live preview binding, original expiry,
  evidence-based reconciliation and sanitized results. The gate unit/real-store
  distinction is explicit in the authority contract and this record.
- [PR #50 already links #51](https://github.com/matt-hans/ShipAgent/pull/50#issuecomment-5955747901)
  and lists all four prerequisites. The historical statement that no grant
  store existed describes that earlier PR, not current implementation status.
- Production authenticated post-gesture approval, current immutable preview
  validation and authenticated exact-target adapters remain absent. A typed
  preview/fingerprint or synthetic test gesture does not supply authentication.
- Provider-safe original-job/status projection, coordinated revocation/account
  deletion/retention startup, and production Redis durability/failure policy
  remain activation obligations. Plans 2/4/6 and the broader Plan 7 connector
  safety/dependency gates still apply; these slices do not complete those plans.
- Default applications do not inject this authority; non-status hosted
  handlers/exports stay disabled. Local API, CLI, desktop startup and shipping
  require no Redis, PostgreSQL, Auth0 or hosted-grant service.
- Native macOS/rendered release qualification in issues #30/#41 remains separate.
  This record proves no native release, approval UI, paid API call, real shipping,
  deployment or marketplace readiness.
