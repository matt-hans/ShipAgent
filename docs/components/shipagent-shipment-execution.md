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
