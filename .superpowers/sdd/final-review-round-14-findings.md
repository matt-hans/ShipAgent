# Final Whole-Branch Review — Round 14 Findings

## Completion artifacts retain durable raw-data bypasses — Critical

Locations:

- `src/api/schemas_conversations.py` save schema;
- `src/services/conversation_persistence_service.py` direct persistence/history/export;
- `src/errors/terminal_diagnostics.py` legacy projection;
- completion artifact rendering.

`SaveArtifactRequest` leaves completion artifact `content` and most metadata loose, and validates only a partial metadata subset. A forged request can put carrier/credential/customer canaries in content, job identifiers/names/commands, status, or scalar fields. Direct persistence validates only `system_artifact`, so alternate message types bypass it. History/export preserve unsafe values and legacy projection carries arbitrary values that the UI renders.

Required outcome:

- Replace partial completion validation with a closed typed completion-artifact contract.
- Validate based on `metadata.type == "completion"` regardless of message type.
- Completion artifact content must be empty or a fixed safe value; never caller-controlled diagnostic text.
- Strictly validate safe job IDs/names/commands, terminal enums, booleans, bounded integers/costs/counts and cross-field mappings; reject unknown fields and scalar canaries.
- Construct or reconcile completion metadata from authoritative job state server-side where feasible; never trust caller-owned terminal diagnostic/status fields.
- On legacy read/history/export, blank unsafe completion content and project only safe bounded fields; do not render arbitrary legacy scalars.
- Tests: content, alternate message type, scalar canaries, history, export, forged metadata, and valid compatibility cases.

## Recovery and write-back bypass safe diagnostic storage — Critical

Locations:

- `src/services/batch_engine.py` write-back and crash recovery;
- `src/services/batch_executor.py` job terminal persistence;
- `src/api/main.py` startup logs;
- normal job/row response schemas/routes.

Write-back and recovery retain `str(exception)`, tracking/idempotency details, and raw error text in result/storage/logs. These may then appear in job/row APIs or startup logs.

Required outcome:

- Apply the safe terminal diagnostic projection at every recovery/write-back mutation and terminal job error persistence.
- Persist, return, and log only bounded action/code/count diagnostic data; never tracking, idempotency, raw exception, customer, carrier request/response, or credential text.
- Ensure normal job/row REST projections cannot expose retained raw values, including legacy state.
- Tests: adversarial storage, job/row REST, recovery/write-back return values, and captured logs.

## Progress aggregate/count invariant can fail after recovery/resume — Important

Recovery produces `needs_review` row diagnostics without consistently updating parent aggregates; resume can reset counters to run-local values. REST progress can return a row failure with failed count zero, then terminal artifact validation rejects the saved shape.

Required outcome:

- Derive progress counts and diagnostic projection from one authoritative row-state projection, or transactionally reconcile job aggregates across recovery/resume.
- Preserve `failed == retained safe failures + omitted_failure_count` for all terminal artifact-compatible progress states, including `needs_review`, recovery, cancellation, and resume.
- Add crash-recovery → cancel/resume → REST → artifact-save coverage.

## Malformed row numbers and SSE omission counts break the total safe projection — Important

`project_terminal_row_diagnostic` can raise for invalid integer row numbers, and SSE emits non-cumulative omitted counts for repeated invalid failures. This can cause 500s or persist an inconsistent terminal shape.

Required outcome:

- Make the row projector total: invalid/zero/negative/out-of-range values become omitted safely, never raise.
- Enforce valid row numbers at creation/storage boundaries where possible.
- Emit cumulative retained/omitted failure accounting from SSE, and consume it without losing increments.
- Add malformed legacy DB, REST, observer, frontend accumulation, and artifact-save tests.

## Verification

- Strict vertical TDD with recorded RED/GREEN evidence.
- Preserve all prior fixes and avoid broadening unrelated artifact metadata contracts.
- Run focused recovery/write-back/job/row/progress/conversation/history/export/frontend tests, then broad backend/frontend/build/authenticated-smoke/artifact/static/Cargo checks.
- Commit implementation and report separately; append full Round 14 evidence to `.superpowers/sdd/final-review-fixes-report.md`.
