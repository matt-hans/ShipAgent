# Authenticated lifecycle Task 2: partial-profile recovery checkpoint

This branch preserves the independently reviewed first two checkpoints of the
[serial implementation plan](../superpowers/plans/2026-10-09-authenticated-agent-lifecycle.md).
The complete authenticated lifecycle profile is unfinished. Production construction
still exports status only. No live issuer, credential, grant, deployment, upload
or real provider call is configured by this work.

This note supersedes the resume status in the historical Task 1 recovery note.
Task 1 was subsequently approved at local `b6cf12e` with 158 independent passes,
two disclosed existing skips and 18 warnings. Its existing recovery branch stays
unchanged at `13846ccdef4bf8ccae63eb7140dab7f7c857c825`.

## Reviewed source and next step

Task 2 is approved at local commit
`d21e1bd2e312ff6b6fc25c62a1ffefa7f724c205`, source tree
`59b6bf0230831cd0aff10ff9ad016991110a3fbc`. It adds captured, nonwaiting SQLite
operations; an explicit V1/V2-to-V3 migration; private original-turn expiry;
bounded authorized history reads; and retained migration cleanup ownership.
Shared store actions keep existing idempotency, revision and cancellation rules.
Public/runtime wiring and PostgreSQL dispatch authority remain later checkpoints.

The author gate passed 460 tests with no skips and seven warnings in 35.49 seconds
(369.5 MiB sampled peak). Independent review passed 461 tests with no skips and
seven warnings in 36.706 seconds (369.66 MiB sampled peak), including the unchanged
independent reference-expiry regression. Both runs retired cleanly with unchanged
source, no limit failures, forced cleanup or survivors. The independent run also
verified the loaded guard and removal of its disposable runtime.

Resume with Task 3 only: capture the original HTTP identity service/session before
persistent effects; preserve one original deadline; prove exact PostgreSQL
transaction settlement and bounded cleanup. A successful local SQLite commit
alone grants neither a fresh response nor model dispatch. Tasks 4 and 5 still need
the strict worker and real HTTP/JWT/persistent-link integration. A later restart
must also prove that the legacy worker cannot dispatch a persisted strict row
without a PostgreSQL permit. Independent checkpoint review precedes each stage.

## Restore and reproduce

Clone this recovery branch from GitHub into a new directory and compare its
tracked content with the [evidence summary](evidence/authenticated-lifecycle-task2-20261010.json).
The three new remote commit messages carry Original-local-commit and
Original-source-tree footers. Those footers provide the source mapping directly
on GitHub even though authenticated GitHub commit creation changes metadata SHAs.
The ordered code trees are `102458f` (initial checkpoint with the recorded expiry
finding), then corrected `d21e1bd`; the final commit adds only this recovery note
and evidence. Do not resume implementation from the initial defective checkpoint.
Existing main and recovery refs were not rewritten.

With prepared project dependencies, the author selection is:

```sh
python -m pytest -c pyproject.toml -q -ra tests/services/agent_runs \
  tests/services/source_ingress/test_reservation_store.py \
  tests/services/source_ingress/test_snapshot_store.py \
  tests/services/source_ingress/test_snapshot_migration.py \
  tests/services/source_ingress/test_source_fences.py
```

Use the reviewed bounded/offline validation environment. Repository validation
sources remain in `scripts/validation/`; the author receipt used the separately
qualified external supervisor identified in the evidence. No existing database
or real credentials are required. The independent extra expiry probe is external
review evidence; the corresponding regressions are also in the published tests.

The evidence preserves expected missing-feature failures, cleanup ownership and
control-flow failures, claim-cutoff and original-reference expiry regressions,
and successful successors as distinct outcomes. Raw local receipts remain
preserved separately; no earlier failed receipt is relabeled. The historical
unrelated nested-runner missing-receipt caveat remains unresolved. This checkpoint
is a recovery branch, with no new release, feature PR, deployment or main merge.
