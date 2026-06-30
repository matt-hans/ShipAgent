# OpenAI Claude Connector Parallel Execution Guide

This guide coordinates the ten implementation plans drafted from `docs/superpowers/specs/2026-06-10-openai-claude-connector-design.md`. Use it as the merge and worktree plan; the individual plan files remain the task-level source of truth.

## Plan Inventory

1. `2026-06-30-openai-claude-connector-01-relay-walking-skeleton.md`
2. `2026-06-30-openai-claude-connector-02-invocation-lifecycle-relay-recovery.md`
3. `2026-06-30-openai-claude-connector-03-version-gate.md`
4. `2026-06-30-openai-claude-connector-04-ephemeral-retention-authorization-audit.md`
5. `2026-06-30-openai-claude-connector-05-ingress-guard-v2.md`
6. `2026-06-30-openai-claude-connector-06-provider-projections-origin-redaction.md`
7. `2026-06-30-openai-claude-connector-07-provider-execution-approval-flow.md`
8. `2026-06-30-openai-claude-connector-08-openai-widget.md`
9. `2026-06-30-openai-claude-connector-09-desktop-settings-device-management.md`
10. `2026-06-30-openai-claude-connector-10-golden-prompt-adversarial-corpus.md`

## Dependency Gates

Implement in this dependency order:

1. **Gate A:** Plan 1 lands first. It creates the relay protocol, device endpoints, relay session store, execution target seam, and desktop relay primitives.
2. **Gate B:** After Plan 1, start the parallel lanes below.
3. **Gate C:** Plan 7 starts only after Plans 2, 4, and 6 are merged. Plan 5 is not a hard functional dependency for Plan 7, but merging Plan 5 first avoids a later ingress-wrapper rebase.
4. **Gate D:** Plan 8 backend resource registration starts after Plan 6. Plan 8 full widget integration starts after Plan 7 exposes execution/status/label handlers.
5. **Gate E:** Plan 10 starts after Plans 7 and 8 are merged.

## Parallel Lanes After Plan 1

Use separate worktrees for each lane and do not merge generated artifacts from two lanes at once.

- **Critical relay lane:** Plan 2.
  - Owns lifecycle/recovery and `job_ref`.
  - Coordinate `src/control_plane/redis_keys.py` with the retention lane.

- **Retention/audit lane:** Plan 4.
  - Owns durable authorization ledger, purge jobs, legal hold, and canonical Redis TTL policy.
  - Merge its Redis key policy before Plan 2 finalizes lifecycle-store constants when possible.

- **Ingress lane:** Plan 5.
  - Owns only `src/control_plane/request_controls.py` and targeted tests.
  - Safe to run in parallel with Plans 2, 3, 4, 6, and 9.

- **Registry/projection lane:** Plans 3 then 6, in that order.
  - Do not merge Plans 3 and 6 independently with separate generated-artifact diffs.
  - Merge order for `src/registry/tools/public.py` and generated artifacts is Plan 1 -> Plan 2 job-ref contract -> Plan 3 minimum capabilities -> Plan 6 scopes/source schema/projection visibility.

- **Desktop settings lane:** Plan 9.
  - Frontend, local API, SignalStore, and Tauri entitlement work can run against fakes after Plan 1 starts.
  - Real `CloudAiSettingsService.from_environment()` runtime verification waits for Plan 1's stable service imports and full relay-device endpoints.

## Shared File Merge Order

- `src/control_plane/app.py`
  - Merge order: Plan 1 base app/relay wiring -> Plan 3 version gate -> Plan 4 retention lifespan -> Plan 7 approval/artifact routes -> Plan 8 widget static assets.
  - Every change is additive. Do not replace the file from a single plan once another plan has landed.

- `src/hosted_mcp/server.py`
  - Merge order: Plan 3 version gate -> Plan 6 projection context -> Plan 7 handler map -> Plan 8 widget resources.
  - Keep this module as registry/auth/projection/resource wiring only. No shipping business logic belongs here.

- `src/registry/tools/public.py`
  - Merge order: Plan 1 status tool -> Plan 2 `job_ref` async contract -> Plan 3 compatibility metadata -> Plan 6 public scopes/source schema/visibility -> Plan 7 provider execution tools -> Plan 8 `ui_resource` entries.

- `generated/provider_artifacts/*`
  - Regenerate with `.venv/bin/python scripts/generate_provider_artifacts.py`.
  - Never hand-edit generated JSON.
  - In the registry/projection lane, regenerate once after each merge step and run `.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v`.

- `src/control_plane/redis_keys.py`
  - Merge order: Plan 1 live relay/session helpers -> Plan 4 canonical TTL/key policy -> Plan 2 invocation/job-ref helpers -> Plan 7 approval/grant/label helpers.
  - Plan 5 keeps guard-only keys private in `request_controls.py`.

- Alembic migrations
  - Plan 1 relay-device migration should follow `20260609_0001`.
  - Plan 4 authorization-ledger migration should use the current head after Plan 1 lands.
  - If both are developed in parallel, rebase only `down_revision` before merge; keep revision IDs stable.

## Runtime Contract Notes

- Plan 1 must provide cloud relay-device capabilities for register, list, rotate key, revoke, set active, and unlink before Plan 9 runtime integration.
- If Plan 1 implements desktop relay primitives under `src.desktop.*`, add thin re-export modules under `src.services.*` before Plans 2 and 9 production integration.
- Plan 7 must use Plan 2's lifecycle coordinator and Plan 4's authorization ledger. It must not create a second invocation state machine or a second audit store.
- Plan 8 must not expose `execute_shipments` to the OpenAI model. Only the widget may call the app-only execution tool after a user gesture.
- Plan 10 is test-only and smoke-material-only. If its tests fail because Plan 7 or Plan 8 changed machine reasons or descriptor shapes, fix the owning plan or update the spec first.

## Recommended Merge Sequence

1. Merge Plan 1.
2. Merge Plan 5 if ready.
3. Merge Plan 4 Redis/audit/migration work.
4. Merge Plan 2 lifecycle/recovery.
5. Merge Plan 3 version gate.
6. Merge Plan 6 projections/source schema/artifacts.
7. Merge Plan 9 local settings work, with real runtime integration only after Plan 1 endpoint/import contract is verified.
8. Merge Plan 7 provider execution/approval flow.
9. Merge Plan 8 OpenAI widget.
10. Merge Plan 10 golden/adversarial corpus.

## Validation Ladder

Run targeted tests from each plan while iterating. Before merging the full connector branch, run:

```bash
.venv/bin/python -m pytest tests/control_plane -v
.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v
.venv/bin/python -m pytest tests/hosted tests/provider_adapters tests/provider_golden -v
.venv/bin/python -m pytest -k "not stream and not sse and not progress"
.venv/bin/python -m ruff check src/ tests/
cd shipagent-frontend && npx nx run-many -t typecheck --all
cd shipagent-frontend && npx nx run-many -t test --all
cd src-tauri && cargo check
```
