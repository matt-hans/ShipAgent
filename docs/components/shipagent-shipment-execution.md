## Responsibility

The Shipment Execution component owns deterministic preview and shipment creation after the model or user has selected a workflow. `src/orchestrator/agent/tools/pipeline.py` implements the fast shipping pipeline: validate command/filter arguments, compile `FilterSpec`, fetch rows through the data gateway, create a `Job`, persist `JobRow` records, run `BatchEngine.preview()`, write a preview hash, and emit `preview_ready`. `src/api/routes/preview.py` exposes preview and confirm endpoints and schedules background execution after preview integrity checks and atomic pending-to-running transition.

The core engine is `src/services/batch_engine.py`. It rates previews, executes rows through UPS, manages two-phase row states, writes labels through `src/services/label_storage.py`, enqueues durable write-back tasks through `src/services/write_back_worker.py`, handles international shipment enrichment and commodity prefetch, and supports crash recovery of in-flight rows. `src/services/batch_executor.py` is the shared execution orchestrator for HTTP, CLI, and watchdog callers. `src/services/job_service.py` owns job/row CRUD, state validation, counts, and summaries.

Evidence: `tests/services/test_batch_engine.py`, `tests/services/test_batch_executor.py`, `tests/services/test_batch_engine_inflight.py`, `tests/orchestrator/batch/test_inflight_recovery.py`, `tests/integration/test_execution_determinism.py`, `tests/api/test_preview.py`, `tests/api/test_startup_recovery.py`, and `tests/services/test_write_back_e2e.py`.

## Read Variables

- User command text, `filter_spec` or `all_rows`, service-code and packaging overrides, source signatures, schema signatures, compiled SQL and params, fetched rows, and row checksums.
- `Job` and `JobRow` ORM state, `order_data` JSON, preview hashes, write-back preference, interactive-job flags, confirmation payloads, and selected service codes.
- UPS credentials resolved by `runtime_credentials`, UPS account number, shipper settings/env/shop data, active data source, external platform connection state, and batch concurrency/timeout environment or settings values.
- International rules, commodity records, payload builder constants, service code mappings, and label storage backend configuration.
- Progress observer callbacks and decision audit run IDs.

## Write Variables

- `Job` records, `JobRow` records, row counts, preview hashes, row statuses, row error codes/messages, tracking numbers, label references, UPS shipment IDs, idempotency keys, costs, destination countries, duties/taxes, and charge breakdown JSON.
- Preview response payloads, `preview_partial` and `preview_ready` artifact events, confirm responses, SSE progress events, and final batch completion/failure events.
- Staged and final label files or S3 objects, write-back tasks, completed/dead-letter write-back task states, and source/platform tracking updates.
- Decision audit events for pipeline creation, mapping, preview readiness, confirmation, execution start, completion, and failure.
- Final execution result dictionaries with successful/failed counts, total cost, international aggregates, and write-back status.

## Conditional Loops

- Pipeline validation rejects raw SQL, conflicting `filter_spec`/`all_rows`, filtered commands with `all_rows=true`, cached filter specs with mismatched schema signatures, deterministic-unsafe sources, and truncated match sets above configured maximums.
- Preview rates rows with bounded concurrency, optional preview caps, per-row UPS rate timeout handling, commodity prefetch timeout handling, and average-cost estimation for additional rows.
- Confirm requires a preview hash, recomputes row checksum hash to prevent time-of-check/time-of-use drift, atomically transitions `pending -> running`, and blocks concurrent confirmations.
- Execution loops over pending rows with a semaphore and uses a two-phase state machine: pre-UPS parse/validation failures can fail a row; ambiguous post-call errors mark `needs_review`; successful calls promote labels before DB commit.
- Write-back branches to local data-source write-back or external platform tracking update; failures produce partial/error status and leave durable tasks for retry.
- Startup recovery scans running jobs, inspects `in_flight` rows, tracks UPS packages when possible, increments recovery attempts, marks rows completed or `needs_review`, and cleans safe staging files.

## Mermaid (internal flow)

```mermaid
flowchart TD
    Pipeline[ship_command_pipeline] -->|read filter/source| Gateway[Data gateway]
    Pipeline -->|write Job and JobRows| Jobs[JobService]
    Pipeline -->|write preview request| Engine[BatchEngine.preview]
    Engine -->|read UPS rates| UPS[UPSMCPClient]
    Engine -->|write preview rows/hash| Jobs
    Confirm[POST /jobs/{id}/confirm] -->|read preview hash| Jobs
    Confirm -->|write running state| Executor[batch_executor.execute_batch]
    Executor -->|read rows/shipper/credentials| EngineExec[BatchEngine.execute]
    EngineExec -->|write shipments| UPS
    EngineExec -->|write labels| Labels[LabelStorage]
    EngineExec -->|write tasks/source updates| WriteBack[write_back_worker and gateways]
    EngineExec -->|write progress/final status| Jobs
```

## Execution Grant Gate (Issue #46, ADR 0003/0008)

**Purpose:** `BoundRegistryTool.run` (`src/hosted_mcp/server.py`) fails closed for
every confirming tool. The only public one is `execute_shipments`.

**Contract removal note (2026-10-02):** `submit_one_off_shipment` is removed from
the public catalog. One-off, local-source and batch purchases all use
`prepare_shipments → execute_shipments(preview_id, approval_request_id)`. Rollback:
revert PR #50; no data migrations, no handlers or exports were enabled.

**Flow:** `reserve` → handler → `consume` | `release` | `hold_for_reconciliation`.

| Outcome | Reservation |
|---|---|
| Handler returns | consume attempted; successful consumption is one-time |
| Handler raises `PreAcceptFailure` (provably before the target accepted) | release attempted; retry only if it succeeds within original expiry |
| Any other exception or cancellation | hold attempted; replay denied `reconciliation_pending` or `grant_in_use` until reconciled by idempotency key |
| Handler returns but `consume` fails or times out | acceptance still reported; existing reserve remains non-reusable, hold attempted only within remaining budget |
| Malformed, mismatched or non-exact-type binding | release attempted, call denied `execution_grant_invalid` |
| No authority, bad reference, authority error | denied `execution_grant_unavailable` |

The gate reads `reservation.binding` once, requires the exact
`ExecutionGrantBinding` type (a subclass could override `validate`), and hands
that same validated object to the handler. Consume, release and hold use one
five-second monotonic settlement budget, including consume-to-hold fallback.
Cancellation arriving mid-step is remembered and propagated after settlement or
that deadline. Timeout requests cancellation of the local operation; it does not
prove rollback of a remote write or target execution. Late outcomes are observed,
and no new hold or release is started after the deadline. Failed settlement
leaves the original reserve non-reusable; expiry means denial, never availability.
The authority must make reserve atomic, bound its own I/O and safely clean up or
quarantine interrupted reservations. The real Redis authority is dormant and explicitly constructed only; default apps do not inject it.
A handler-raised `ToolAuthorizationError` is projected as the generic provider
error like any other handler failure; only gate-raised errors keep their code.

**Caller obligations** (`src/control_plane/execution_grants.py`):

- *Authority* (`ExecutionGrantAuthority.reserve`, dormant Redis implementation): exclusively reserve; compare
  target, policy, amount, currency and payload against the live approved preview
  and reject any drift, including a lower amount; deny a second reservation.
  Atomically fence settlement against the original owner, recheck expiry at
  consume, and reconcile uncertain acceptance through the Plan 2 lifecycle.
  Failed hold writes must not undo the original reservation's denial of reuse.
  Never reconstruct missing/expired authorization from requests or SQL audit.
- *Handler*: register only via `build_server(confirmed_tool_handlers=...)`
  (`(context, arguments, binding)`); invoke the bound Execution Target with the
  binding's idempotency key and approved amount; return only after durable
  acceptance, and raise `PreAcceptFailure` only when nothing could have been
  accepted. A socket/ack timeout alone is insufficient proof. Plain `tool_handlers` entries for a
  confirming tool raise `ValueError` at `build_server`.
- *Gate* checks what needs no live data: account, Provider Connection, preview,
  expiry (timezone-aware), policy equal to the tool's `confirmation_policy`,
  amount (`MONEY_PATTERN`, positive), currency (`RATE_CURRENCY_CODES`), identity fields.

**Logging:** reserve, denial, hold, release and consume failures log tool name,
operation, denial code and exception type only, never identifiers, amounts or
authority exception messages. An accepted result preserved across settlement
failure reports target acceptance, not successful persistence or final shipping.

See [the authority contract and separate implementation prerequisites](execution-grant-authority-contract.md)
for cancellation, original expiry, reconciliation and required real-store tests.
Existing fake-backed gate tests do not satisfy issue 51's persistent replay proof.

**Status:** the real grant store/authority is dormant; no approval page, connector, non-status handler or provider export is enabled. `confirmation_artifact_id` and the `INGRESS` family
remain reserved with no tool consumer.

The dormant authority adds a hidden server-only reservation token to the binding
passed unchanged by the gate. Callers use `callbacks_for_binding`/`invoke_bound`
to retain that exact owner, never a latest-owner lookup. Only persisted accepted
results can return normally; exact positive rejection raises `PreAcceptFailure`,
and unknown outcomes remain held. New attempt generations preserve original
purchase/job/deadline identity. Public job-reference/status projection and real
adapter wiring remain separate enablement obligations. See
[the real authority implementation](../control-plane/redis-grant-authority.md)
for bounded I/O, original-expiry audit-only recovery and issue 51's remaining gate.
