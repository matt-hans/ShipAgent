# Authenticated lifecycle Task 1: WIP recovery checkpoint

This branch preserves unfinished work. It is not an implementation approval,
release, deployment, or an instruction to enable lifecycle tools in production.
Default application construction still exports status only.

## Resume point

Base main: `551f257a2f66ac15195e5d25c4b64d101a3c8508` (merged PR92).
The approved serial plan is
[authenticated-agent-lifecycle.md](../superpowers/plans/2026-10-09-authenticated-agent-lifecycle.md),
with its [design](../superpowers/specs/2026-10-09-authenticated-agent-lifecycle-design.md).
Only Task 1 has implementation changes. Tasks 2–5 are unstarted and remain gated
by independent review of each preceding checkpoint.

The draft adds verified independent issuer-link identity, server-owned epochs,
request expiry/deadline propagation, a separate durable scope ceiling, revocation
tombstones, and a legacy-preserving control-plane migration. Strict policy is an
explicit trusted constructor argument, absent by default. No live issuer, token,
OAuth grant, relay enrollment, upload, carrier call or deployment was configured.

The latest author gate passed **866 tests, with two existing skips and 26
warnings** across `tests/control_plane`. It took 41.225 seconds with a sampled
533.574 MiB aggregate peak. There were no signals, forced cleanup, survivors or
resource-limit failures. All 1,278 source hashes matched before/after the run.
This is author evidence; independent implementation acceptance is pending.
The only post-gate additions are this recovery note and its evidence summary.

## What to do next

1. Check the recovered source tree and read the spec/plan and evidence summary.
2. Obtain independent Task 1 link/auth/migration review. Do not infer approval
   from the existence of this recovery branch or its passing author tests.
3. Resolve any findings with preserved RED/GREEN evidence, then freeze an exact
   user-attributed checkpoint before Task 2.
4. In Task 3, capture the existing identity service/session before effects and
   own bounded rollback/close. Task 1 retains failed cleanup and prevents reuse,
   but does not prove the complete two-second HTTP cleanup bound. An automatic
   session-context exit must not discard an uncertain owner.
5. Follow the remaining serial plan before the final remote full-suite, CI,
   guarded merge and renewed-main checks. Actual ChatGPT/Claude setup remains
   a later explicitly authorized qualification step.

For ordinary local reproduction with prepared dependencies:

```sh
python -m pytest -c pyproject.toml -q -ra tests/control_plane
```

Real PostgreSQL/Redis cases use the existing disposable-service fixture and
`SHIPAGENT_TEST_SERVICE_ROOT`, which must name an already prepared synthetic
service root. No existing database or real credentials are needed. The reviewed
repository runner and offline guard are under `scripts/validation/`; the author
receipt used the separately qualified external supervisor with the hash recorded
in the evidence. Missing required binaries are not a passing qualification.

## Preserved history and failed evidence

The local docs history above main is, in order:

- `a5bf521acd4bd283d489030b143e1aec417758c1`: initial composition design
- `1e697ce72e7b74a916e63579998062d8f72c0603`: deadline/settlement clarification
- `17fcf0417885c80e5172b38883826f4e1503c755`: serial implementation plan
- `7e8810d2d736c7643c579dcef3bd2e4a0a99f86a`: candidate and HTTP cleanup details

The recovery publication preserves these ordered source trees with an explicit
[local-to-remote mapping](evidence/authenticated-lifecycle-task1-publication-map.json). GitHub-created commit metadata may give different SHAs;
source-tree equality is checked for every step. Existing main and remote refs
are not rewritten.

The [evidence summary](evidence/authenticated-lifecycle-task1-20261009.json)
retains the failed invocation, expected missing-feature failures, reproduced
cleanup and downgrade races, route-fixture compatibility failure, and successful
successors separately. Raw local receipts remain preserved; none is relabeled.
The earlier unrelated intermittent nested-runner missing-receipt issue from
PR91 remains unresolved; this checkpoint does not claim to fix it.
