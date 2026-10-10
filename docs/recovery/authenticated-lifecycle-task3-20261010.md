# Authenticated lifecycle Task 3: partial-profile recovery checkpoint

This branch preserves the independently accepted first three checkpoints of the
[serial plan](../superpowers/plans/2026-10-09-authenticated-agent-lifecycle.md).
The full authenticated lifecycle profile remains unfinished. Default production
construction still exports status only. No live issuer, credentials, deployment,
upload or real model call is configured here.

This note supersedes the resume status in the retained Task 1 and Task 2 recovery
notes. Their original evidence and existing GitHub branches remain unchanged.

## Accepted source and evidence

Task 3 is accepted at local commit
`21649d68dcec51bc243ea1f6b89321e4ef00fd2a`, tree
`7808342302c536ef3c06feb712c8fdcd41f6eb38`. It owns a strict operation from captured
HTTP identity service/session through the local SQLite writer and original
PostgreSQL account/link transaction. Each asynchronous stage remains captured
when bounded observation ends; uncertain cleanup retains the coordinator and
service slot. Local COMMIT and original PostgreSQL settlement remain separate
facts. The original physical connection/backend and committed xid8 are required
for fresh success; reconnecting or a normally returning aborted COMMIT cannot
supply that proof.

Private dispatch/history and publication contracts are implemented but not yet
connected to the worker. The permit is bound to one exact run, generation,
provider owner, original thread and original lifetime. The next checkpoint must
prove actual provider-entry counts and strict worker behavior.

The author aggregate passed 1,397 tests with two existing disclosed skips and
31 warnings in 76.291 seconds (634.383 MiB sampled peak). It covers all control-plane
and Agent Run tests plus affected source-store/migration/fence suites. The two
skips are an existing separately configured migration test and a production-only
stateless assertion; disposable PostgreSQL tests did execute. Independent review
passed 404 tests with no skips and 14 warnings in 39.383 seconds (352.215 MiB).
Both gates preserved source and retired cleanly, with no limit failure, forced
cleanup or survivors. The independent gate also verified the loaded guard and
removed its disposable runtime.

Real backend/session death was tested around local and PostgreSQL COMMIT; these
are original-connection loss checks, not whole-server crash/restart qualification.
The evidence includes an actually aborted PostgreSQL transaction whose COMMIT
returns normally, retained cancellation-resistant tasks, safe precommit errors
requiring original rollback, and known local outcomes surviving later failures.
The [evidence index](evidence/authenticated-lifecycle-task3-20261010.json) contains
1,288 qualified source hashes, all 29 author receipt/log digest pairs and the
independent review digest. All 15 nonzero author receipts remain failures;
missing-feature RED, invocation/fixture corrections and product findings are
preserved separately from their passing successors. The unrelated historical
nested-runner missing-receipt caveat remains unresolved.

## Restore and resume

Clone this recovery branch from GitHub into a new directory. New commit messages
carry Original-local-commit and Original-source-tree footers, so the mapping is
available without local artifacts. The first new commit is the exact accepted
Task 3 tree above remote `801c8971`, the matching accepted Task 2 source commit.
The final commit adds this note/evidence and retains the exact prior Task 2 note
and evidence. Existing main and recovery refs are not rewritten.

Resume with Task 4 only, following its independent checkpoint gate:

- Route strict requests and the sole worker through the captured authority.
- Capture a bounded local-only candidate claim without granting dispatch.
- Consume the one-shot permit immediately before actual provider entry, with
  one shared-runtime turn and zero tools.
- Prove revocation, expiry, shutdown and configuration-loss/restart negatives,
  including a legacy service refusing to dispatch persisted strict rows.

Task 5 still owns the real HTTP/JWT/persistent-link composition, including
pre-auth cleanup when no lifecycle handler runs. Actual external-client testing,
live issuer setup and deployment remain later scoped gates. This recovery branch
creates no feature PR, release, deployment or main merge.

With prepared project dependencies and disposable PostgreSQL, reproduce the
author selection under the reviewed bounded/offline environment:

```sh
python -m pytest -c pyproject.toml -q -ra tests/control_plane \
  tests/services/agent_runs \
  tests/services/source_ingress/test_reservation_store.py \
  tests/services/source_ingress/test_snapshot_store.py \
  tests/services/source_ingress/test_snapshot_migration.py \
  tests/services/source_ingress/test_source_fences.py
```

Repository validation sources remain in `scripts/validation/`; the evidence
identifies the separately qualified external supervisor used for the author run.
No existing database or real credentials are required.
