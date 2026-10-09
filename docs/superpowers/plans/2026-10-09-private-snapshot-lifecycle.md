# Private Snapshot Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. The established workflow is one implementer and one independent reviewer, serial checkpoints; do not spawn extra authors.

**Goal:** Accept bounded synthetic CSV chunks into a durable immutable private snapshot under the existing target/conversation/authority ownership rules.

**Architecture:** Reuse the reservation database and shared Agent Run lease. All disk-backed source operations borrow the conversation writer before connecting; a private common executor owns authority, explicit commit and retirement. Fixed exclusively created content files remain invisible until the lifecycle manifest commits. No public or production source admission is added.

**Tech Stack:** Python stdlib, existing SQLite reservation store, Linux process/resource primitives, existing exact-string CSV parser, pytest synthetic providers and disposable SQLite authority fixtures. No new dependency.

**Spec:** [Private snapshot lifecycle design](../specs/2026-10-09-private-snapshot-lifecycle-design.md). Base is main `cedc8a5fa951965c14b5f6bbfa78e492cb5289be`; the current design including explicit all-source-open fencing, process pin and cleanup acknowledgment is SHA256 `89357daaf985a9b76d318615f376c4543ed38cb7be64c220b5cfcdca17d8fcc4`.

Status: Task 1 is independently approved at acd071f and Task 2 at a5ffef0. Task 3 is independently approved at c4debd2. Task 4 is independently approved at 4acb46d. Task 5 is independently approved at 64ffea6. Task 6 is independently approved at a07f3e5. Task 7 is independently approved at f7febb6. Task 8A is independently approved at b9bc1a1. Task 8B real reconciliation/readiness, bound receiver admission and two-fence private reads are implemented and author-qualified locally; independent final review and publication remain pending. No task is approved merely by appearing here.

## Global constraints

- Public tools/routes/exports, model input, active-source selection, real uploads/credentials, production authority, deployment and the held headless scenario remain absent. Milestone #79 stays incomplete.
- Managed file lengths: 16 MiB content across all retained/staged/cleanup files; separately 34 MiB DB/WAL/SHM. Allocated blocks are observed and overages deny further work; no hard filesystem/CoW/journal peak quota is claimed.
- SQLite profile: source ID `c88b22011a54b4f6fbd149e9f8e4de77658ce58143a1af0e3785e4e6475127e9`, Linux unix VFS, 4096-byte pages, 4096-page DB ceiling, WAL/FULL, spill off, temp MEMORY, auto-vacuum NONE, automatic indexes off, mmap off, automatic checkpoint off, trusted schema off. Verify each disk connection; no runtime extension/global reconfiguration.
- Before every mutation: held Agent Run writer, bounded pre-open inventory, completed TRUNCATE checkpoint and zero WAL. No second dirty set after a failed/busy checkpoint. One common two-second transaction deadline includes connection/PRAGMA/lock waits.
- Every source open/transaction, including V1 setup/migration, receives the live borrowed conversation writer before sqlite3.connect. Compatibility preserves stored V1 payload/identity/lifetimes, not an unsafe unfenced internal call signature.
- Runtime caps: two receiver lifetime borrows, one parser borrow, one private-read borrow across all manager objects on a lease. Untagged transaction borrows remain separate.
- Input: nonempty bytes chunks at most 64 KiB, exact offsets, 1 MiB complete raw CSV, 2 MiB canonical normalized bytes, 10,000 data rows, 64 columns, 16 KiB encoded field. No partial retransmission or resume.
- Original upload lifetime at most 300 seconds, original source lifetime at most 86,400 seconds, both capped by conversation expiry. Receiver additionally captures the claim's authorization expiry; ten seconds without byte progress does not renew on polling/parser/retry.
- Parser: minimal isolated child; 64 MiB RLIMIT_AS, one CPU, five seconds parent wall deadline, bounded output. No preexec_fn, pickle, unbounded result frames or process-wide child reaping.
- Metadata: 1,024 reservations/tombstones, 128 completed manifests, 4 MiB total logical metadata; existing 8 KiB reservation records, 4 KiB lifecycle rows, 8 KiB manifests. Check lengths before decode and recompute accounting.
- Fixed 32-hex private snapshot IDs are distinct from reservation IDs and grant no authority. No canonical Source Reference is allocated.
- Keep only user-attributed commits. Preserve all RED/failed/inconclusive receipts and earlier refs. No publication before all tasks and independent final review.

## Review focus

1. An old source-store instance after V2 migration must not connect unfenced or bypass physical-profile/accounting checks: Task 2.
2. Cancellation while an append/fsync call is blocked must retain its descriptor, work slot and quota until that action really returns: Task 7.
3. A lost final reply after upload expiry must recover the original completed snapshot under current authority and source expiry, without reminting or extending time: Tasks 7–8.
4. A created filename without durable identity proof must not become cleanup authority after a crash: Tasks 5 and 8.
5. A parser resource failure or private-read cleanup crossing expiry must return no private values and must not affect unrelated provider children: Tasks 6 and 8.

## Common validation and checkpoint protocol

Use the prepared project Python and the reviewed common-lock supervisor for every test job. Commands below denote pytest arguments passed through that supervisor with the existing offline plugin, exact worktree/candidate guard and clean retirement checks. Use short 90–150-second / 512–1024-MiB slots while iterating; do not chain full backend runs. The final remote head gets the established 900-second / 1536-MiB full gate.

Each task follows RED → minimal implementation → focused GREEN → changed-file Ruff/format/diff checks → verify author and committer with git var → clean local commit → independent exact-head review. Freeze at each checkpoint. A failed review is repaired and rechecked before starting the next task. A completed task is marked with its actual commit/receipt; never mark the whole #79 milestone complete.

## Task 1: Bound the SQLite managed-file profile

**Files:** Create `src/services/source_ingress/sqlite_profile.py`; create `tests/services/source_ingress/test_sqlite_profile.py`. No existing production call sites change in this task.

**Interfaces:**
- `SourceSqliteProfile` is an internal fixed profile, not configurable from request data.
- `check_runtime() -> None` verifies the pinned source ID/relevant compile options through an in-memory connection.
- `inspect_files(path: Path, *, initializing: bool) -> ManagedFileInventory` returns immutable file lengths/allocated bytes/identities after bounded pre-open checks. It reveals no row data.
- `close()` retries only captured inspection/runtime cleanup. A retained uncertain inspection blocks any replacement inspection owner. The caller remains responsible for retiring its disk SQLite connection.
- `configure(db: sqlite3.Connection, *, initialize: bool, execute: Callable) -> None` binds the exact real connection to its prior inspected path, then sets/verifies the fixed profile using the caller's deadline-aware executor. It rejects proxies/uninitialized handles and preserves ownership on failure.
- `observe_active_files(path) -> ManagedFileInventory` uses stat only while the bound SQLite handle is live, preserving POSIX record locks and capturing new sidecar identities. No active check opens/closes managed descriptors. A successful close of the exact supported handle is required before another descriptor inspection; live `in_transaction=False` is not retirement.
- `before_mutation(db, *, execute, path) -> None` requires a completed TRUNCATE result and empty WAL. Caller must already own the Agent Run writer; this helper supplies no authority itself.
- Constants: DB bytes 16,777,216; WAL bytes 16,941,472; SHM bytes 65,536; aggregate managed metadata bytes 35,651,584. Unexpected nonempty rollback journal, disk-temp artifact or incompatible existing geometry fails closed.

- [x] Write `test_wrong_runtime_or_oversized_preopen_inventory_never_connects`: reject source mismatch, oversized DB/WAL/SHM, symlink/hardlink and nonempty journal before the spy connection opens. Include a valid crash WAL whose latest committed schema/header is not yet checkpointed; do not invent a WAL schema parser or reject it only from stale main-file user_version.
- [x] Run that case and preserve its missing-profile RED.
- [x] Implement the bounded profile and closed failures. Fresh empty initialization is explicit. Existing stores are never VACUUMed or silently reconfigured into compatibility. The pre-open format check bounds recovery artifacts, including every complete WAL frame's big-endian page number (1–4,096) and commit-size (0–4,096), with at most 4,112 frames. Add oversized first and late frame regressions proving no SQLite connect; malformed/torn unsupported geometry denies without repair. Keep descriptor identity pinned throughout. It does not interpret schema/version/row contents; actual schema/account validation remains on the held SQL connection in Task 2.
- [x] Add `test_pinned_reader_denies_next_mutation_until_successful_truncate`, `test_sqlite_full_rolls_back_without_second_dirty_set`, `test_near_page_ceiling_commit_stays_in_file_envelope`, `test_crash_before_after_commit_recovery_is_bounded`, and `test_observed_allocated_overage_denies_without_claiming_peak_enforcement`.
- [x] Prove an independent-process DMS lock remains held across active checks, and a fresh first owner rebuilds bounded corrupt cached SHM after actual old-process exit. Keep the first-owner requirement distinct from generic pinned-reader refusal. Add descriptor/runtime cleanup before/after-effect faults and control-flow preservation.
- [x] Verify `pytest tests/services/source_ingress/test_sqlite_profile.py`; record exact runtime/profile/file measurements and no remaining files/processes. The generic earlier probe is supporting evidence only.
- [x] Commit `feat: define bounded source SQLite storage profile`; freeze for independent profile review.

Author qualification: `snapshot-profile-source-regression` passed 276 cases, no skips and four existing warnings, including the 47 new profile cases; 12.418 seconds bounded wall time and 341.656 MiB sampled peak, with no signals, forced cleanup or survivors. Changed-file Ruff/format and diff checks passed. Independent approval followed on exact acd071f: 47 cases passed with no skips/warnings, unchanged source/guard and clean retirement. This qualifies the isolated helper; all-writer enforcement remains Task 2. The earlier `snapshot-profile-config-red` name records a test-append cwd mistake and an unchanged 19-case pass, not a valid configuration RED; its corrected successor records the actual nine failures. All failure and cleanup evidence remains preserved.

## Task 2: Fence every source connection and add V2 lifecycle metadata

**Files:** Modify `src/services/agent_runs/source_ownership.py`, `src/services/source_ingress/reservation_store.py`, `src/services/source_ingress/reservations.py`; create `src/services/source_ingress/source_store_owner.py`, `src/services/source_ingress/snapshot_contracts.py`, `src/services/source_ingress/snapshot_store.py`; create `tests/services/source_ingress/test_snapshot_store.py`, `tests/services/source_ingress/test_snapshot_migration.py`; narrowly adapt source-store fixtures/call sites in existing source-ingress tests.

**Interfaces:**
- Add `ConversationFence.require_storage_owner(*, account_id: str, execution_target_id: str, coordinator_path: Path) -> None`. It proves the exact original fence object/process, already-held writer, target/store/lease path, generation and budget without resolving conversation rows or acquiring another lock. Copied/inherited fences also reject retirement before touching the original handle. The fence owns one exact source-transaction binding across all store objects; admission precedes creation/inspection/connect and outer retirement is denied until that source fully retires. A cleanup-only identity release cannot clear another owner’s binding. Source transactions have their own weak self-identity/PID checks.
- `ReservationStore` gains trusted `coordinator_path: Path`; `open(*, conversation: ConversationFence, deadline, monotonic=...)` and `transaction(*, conversation: ConversationFence, monotonic=...)` require that live fence. Validate it before every first disk connect, including cached V1 instances.
- `SourceStoreOwner(agent_runs, store, *, clock, monotonic)` owns setup/migration scopes before acquisition. `open()`, `upgrade_to_v2()` and `close()` retain exact failed contexts, mark source quarantine on uncertainty and retire source → conversation → borrow. Maintenance returns no caller reference/row values and performs no provider work.
- Separate immutable `RESERVATION_PAYLOAD_VERSION = 1` from `SCHEMA_VERSION = 2`. V1 opening alone does not migrate; explicit upgrade preserves all old payload bytes/digests/IDs/expiry.
- `SnapshotLifecycle` is a frozen private record containing reservation/attempt ID, generation, state, original claim authorization expiry, reserved content bytes, fixed raw/normalized basenames and optional recorded file identities. Reserved is implicit only when a validated reservation has no lifecycle or manifest. Persisted states are exactly receiving, sealed, parsing, staged, complete, failed; cleanup-pending is explicit rather than pretending failed work has retired. Every bounded inventory rejects orphan or mismatched lifecycle/manifest records before identity lookup or same-key claim.
- `SnapshotManifest` contains version 1, private snapshot/reservation IDs, raw and normalized identities/lengths, row/column counts, parser profile, recorded file identities and original source expiry. Its completed snapshot ID must differ from the reservation and attempt IDs. No headers/rows are stored in metadata.
- `SnapshotTransaction(tx: ReservationTransaction)` operates on that same held SQL handle. Its methods are `lookup_lifecycle(record)`, `claim(record, *, generation, authorization_expires_at, now)`, `record_files(attempt, *, identities)`, `set_phase(attempt, *, expected, state)`, `complete(attempt, manifest)`, `mark_failed(attempt, *, cleanup_complete)`, `acknowledge_retirement(attempt, *, generation, retirement_proof)`, `lookup_manifest(namespace, private_snapshot_id)`, and `inventory(*, now)`. None commits, opens a connection or supplies authority. Task 2 rejects `acknowledge_retirement` and `mark_failed(cleanup_complete=True)` rather than inventing cleanup proof; every claimed row conservatively retains its peak charge. Task 7 must bind acknowledgment to the exact attempt, original generation, exact captured receiver token/owner and positive actual retirement. Task 8 separately proves fresh-owner exclusion of prior process/child work before reconciliation. A generic retired borrow is insufficient.
- `ReservationTransaction.insert` uses the one shared lifecycle-aware incomplete-slot rule; complete/fully-cleaned failed records still consume retention/content/logical metadata. All counter values are recomputed from bounded validated rows.

- [x] Write and run RED `test_source_open_requires_live_matching_writer_before_connect`, including closed/wrong-store/wrong-generation/copied fence, cached V1 object after a committed V2 migration, and committed version change still only in WAL. Assert zero unfenced sqlite3.connect calls.
- [x] Implement the narrow held-owner check, explicit source API and retained `SourceStoreOwner`. Adapt old fixtures to acquire real fresh-process/real lease fences; preserve behavioral assertions. Update reserve/recover to pass their already-acquired conversation fence.
- [x] Add and run RED `test_v1_upgrade_preserves_exact_rows_and_is_explicit`, then implement schema/profile integration and the lifecycle tables. Setup failure remains single-attempt and retains its handles, including known commit evidence; no failed-open latch resets. Apply bounded format checks and connection-only safeguards before any schema-dependent owner SELECT. Retirement clears the progress handler, rolls back, sets busy_timeout=0, requires successful TRUNCATE/empty-WAL checks through stat-only observations, closes the exact real connection, then performs descriptor inspection before releasing the conversation writer. Busy/error retains its stage and handle for explicit retry; blocked filesystem I/O is not forcibly terminable.
- [x] Add SQL failure and actual process-death migration cases; old or complete new version must reopen without partial schema. Test malformed/oversized lifecycle/manifest rows, counter mismatch, duplicate identity, two claims, 129-manifest inventory refusal, the actual 1,024-record store and bounded metadata admission. Normal retired-completion capacity and slot release remain at Tasks 7–8.
Task 2 can verify bounded malformed-row/count refusal and declared retention constants, but cannot produce 128 normally retired completions while acknowledgment is intentionally disabled and both incomplete slots remain charged. Tasks 7–8 own the end-to-end retirement-release and completed-retention capacity qualification.

- [x] Exercise every V2 writer including reserve, claim, transition, failure, completion and recovery through the Task 1 profile. Verify integrated busy-checkpoint and before/after-effect SQL/commit/cleanup failures retain ownership and known commit. The pinned profile’s real SQLITE_FULL pager/rollback case remains the physical-cap failure evidence; no legal V2 metadata workload is claimed to fill the 16-MiB DB cap. Cleanup of a captured connection remains explicit even after admission expiry; normal rollback/close does not require a fresh operator grant.
- [x] Verify all `tests/services/source_ingress/` plus `tests/services/agent_runs/test_source_ownership.py`; freeze the clean commit for independent shared connection/migration review before Task 3.

Author checkpoint: `snapshot-task2-author-final` passed 503 cases with no skips and seven warnings, including all source-ingress and Agent Run tests; 45.758 seconds / 368.594 MiB, with no signal attempts, forced cleanup or survivors. Real migration-process deaths before/after COMMIT preserved the old or complete new schema. Copied-fence/inherited-retirement and completed-ID reuse regressions were observed RED before their fixes. Legacy fixture adaptations use real retained fences and transaction fault hooks, preserving original before/after-effect assertions. This is author evidence on the committed content; independent exact-head approval is still required before Task 3.

Independent review held bf67d93 after reproducing DMS lock loss from a rejected second source acquisition using the same live fence. The four corresponding product negatives failed before the exact-owner binding repair; the unchanged independent DMS witness then passed in the 67-case focused successor gate. The earlier 503-pass result remains on bf67d93 and does not cover this discovered gap. The expanded successor run then reported 512 passes, one failure and one teardown error: an unfetched deadline cursor blocked TRUNCATE despite unchanged file identities. Deterministic source, conversation and cleanup-only cursor regressions were each observed RED. Explicit retained-cursor retirement then passed the 11-case targeted gate, including before/after-effect close faults and a process DMS witness. Those failed receipts remain separate; the repaired successor author gate then passed 520 cases, no skips, eight warnings in 46.431 seconds / 367.301 MiB, including the unchanged independent DMS witness, all source-ingress and all Agent Run tests. No signals, forced cleanup or survivors were observed. Independent exact-a5ffef0 review then passed 143 cases, no skips, six warnings in 14.363 seconds / 342.523 MiB with unchanged source/guard and clean retirement. Task 2 is approved only at that repaired head.

## Task 3: Add shared source-work tags to existing lease tokens

**Files:** Modify `src/services/agent_runs/coordinator.py` and `src/services/agent_runs/service.py`; create `tests/services/agent_runs/test_source_work_limits.py`.

**Interfaces:**
- Add closed internal `SourceWorkKind` values receiver, parser, private_read with caps 2, 1, 1.
- `CoordinatorLease.borrow(*, source_work: SourceWorkKind | None = None)` and `AgentRunService.borrow_coordinator(*, source_work=None)` preserve existing untagged behavior. The latter still performs no database/provider/authority work.
- `CoordinatorBorrow.allocate_process_pin() -> CoordinatorProcessPin` is restricted to an exact active parser-tagged token with PID/ownership checks. Allocation is I/O-free and retained before `pin.acquire()` duplicates the actual coordinator descriptor. `pin.child_fd` is available only while captured/active. Parent duplicates are CLOEXEC; `pin.retire()` closes only its owned duplicates and never LOCK_UN, after the parser owner has proven child exit. The parser borrow remains active through all pin/child retirement, so normal lease close cannot unlock early. The fixed child uses only the inherited FD, never copied Python token authority.
- Pin cleanup uses the exact real FileIO owner after adoption. A captured raw duplicate remains owned before the opener returns it; uncertain constructor handoff/raw-close outcome quarantines without retrying a reused integer. Test an unrelated descriptor reusing the old number. This helper never grants child-exit proof.
- Token admission/retirement proof retains the exact-token weak registry and one active-membership removal. Usage is derived from active tokens, not a second decrement counter. Invalid tags reject; tags never originate in model/request arguments.

- [x] Write RED `test_receiver_cap_is_shared_but_inner_borrows_still_work`: two receiver tokens succeed, third fails, ordinary transaction tokens still succeed, one retirement permits exactly one new receiver.
- [x] Implement the closed tag/cap admission under the existing short mutex with PID check first. Keep failure cleanup ordering and positive ownership versus denying quarantine semantics.
- [x] Add parser/read caps across two manager-like owners, concurrent last-slot races, copied/forged tokens before/after original retirement, interruption during failed admission/retirement, closing, physical ownership loss and source quarantine. Ordinary model execution must remain unaffected by source-only quarantine. Add pin allocation/adoption/close before-and-after-effect faults, copied/forged/wrong-tag denial, CLOEXEC/pass_fds restrictions and no LOCK_UN from pin cleanup. Spawn ownership and actual child-death proof remain Task 6 gates; Task 3 verifies only explicit fixed-child inheritance and wait-before-helper-retirement. Parent close must remain unavailable while child/pin/parser borrow ownership is live.
- [x] Verify all Agent Run tests plus the preserved lifecycle review probes. Commit/freeze for independent shared lease review.

Author checkpoint: `snapshot-task3-author-final` passed 565 cases, no skips,
eight warnings in 48.494 seconds / 379.738 MiB. It includes all Agent Run and
source-ingress cases plus preserved independent borrow/quarantine/retirement
probes. No signal attempts, forced cleanup or survivors occurred. Missing tags
first produced two failures; missing pin behavior then produced sixteen failures
with twelve existing passes. Before/after-effect duplication, adoption and close
faults, reused unrelated descriptors, shared cap races and PID-before-mutex
rejection pass. The actual parser-owner spawn/death sequence remains Task 6.
Changed-file lint/format and diff checks passed; independent exact-head Task 3
review is required before Task 4.

Independent review held 22497c4: blocked FileIO acquisition or retirement held
the shared mutex and prevented prompt begin_close. Both independent barriers
and the corresponding two product cases failed before repair. The successor
retains one in-flight pin action while performing I/O outside that mutex, with
concurrent child_fd/action denial. Its focused gate passed 56 cases including
the unchanged independent probes. The final repaired author gate then passed 569
cases, no skips, eight warnings in 50.340 seconds / 375.379 MiB with no
signals, forced cleanup or survivors. Independent exact-c4debd2 review passed 96 cases, no skips, one dependency
warning in 7.143 seconds / 219.418 MiB, with clean source/guard and retirement.
Task 3 is approved at that repaired head.

## Task 4: Reuse the held source operation owner

**Files:** Create `src/services/source_ingress/source_fences.py`; modify `src/services/source_ingress/reservations.py`; create `tests/services/source_ingress/test_source_fences.py`; adapt the existing contention test’s private budget-constant patch target after extraction, preserving its assertions. Re-export existing authority Protocol names for internal import compatibility if needed.

**Interfaces:**
- `SourceFenceExecutor(agent_runs, store, authority, *, expected_target_fingerprint, clock, monotonic)` owns one action at a time and retains its exact operation before acquisition. `close()` only retries its captured cleanup.
- Private `_run_action(*, operator_context, provider_connection_id, conversation_reference, request_key, action, deadline=None)` invokes only trusted module-defined actions after acquiring borrow → conversation → source → authority and resolving the original namespace. The optional deadline can only shorten the two-second budget.
- A private `HeldSourceOperation` gives the trusted action the held transaction, resolved authority, owned conversation and namespace; `require_current()`, `require_response_time()`, `set_result(receipt)`, `set_response_expiry(expires_at)` and `commit(*, before_commit=None)` preserve the existing final-guard/known-commit semantics. Hooks never acquire another lock or come from request data.
- An action returns only the exact captured immutable candidate (ReservationReceipt initially). Candidate presence is separate from known COMMIT/fresh response; a different or uncaptured return is denied. No connection, scope, borrow or reusable commit function escapes. The held interface rejects copied/late use; pre-commit hooks must return None and cannot come from request data. Reserve/recover become thin trusted actions over this same owner and keep their public result/error shapes unchanged.

- [x] Write RED `test_private_action_has_real_ordered_fences_and_cannot_escape_live_scope`, plus unchanged reserve/recover characterization against the existing authority event sequence, IDs, expiry, SQL rows and provider counters.
- [x] Extract the proven owner with minimal behavioral change. Preserve BaseException propagation after ownership retention, final success/reference-error clock checks, unknown COMMIT quarantine, two-instance denial and final-borrow positive retirement proof. Callback denial before SQL must not be mislabeled as commit-unknown.
- [x] Add a source-lifetime action showing a completed-result lookup can use original source expiry while reservation recovery still uses upload expiry. Final response-time checks apply to captured authority/conversation/source lifetime and error outcomes.
- [x] Verify all source-ingress and shared lifecycle tests plus previous independent error-expiry/commit/retirement probes. Freeze for independent extraction review before receiver code uses it.

Author checkpoint: `snapshot-task4-author-final` passed 583 cases, no skips,
eight warnings in 49.556 seconds / 376.914 MiB, with no signals, forced cleanup
or survivors. It includes all source-ingress and Agent Run tests plus preserved
independent error-expiry and retirement probes. Six missing-module/action cases
first failed. The initial extraction run had 85 passes and one private test
constant-location failure; the test target was adapted without changing its
contention assertions. A non-None commit hook was reproduced as an actual failure
and now denies before SQL. A source-lifetime test field-access mistake was fixed
only in that test and remains separately recorded. Its passing successor proves
the internal expiry selection, not a completed snapshot or public Source Reference.
Ruff/format/diff checks passed. Independent exact-head review remains required
before Task 5.

## Task 5: Own exact normalized content and private files

**Files:** Create `src/services/source_ingress/snapshot_codec.py`, `src/services/source_ingress/snapshot_files.py`; create `tests/services/source_ingress/test_snapshot_codec.py`, `tests/services/source_ingress/test_snapshot_files.py`.

**Interfaces:**
- `encode_snapshot(snapshot: CsvSnapshot) -> bytes` and `decode_snapshot(content: bytes, *, raw_content_sha256: str, expected_identity: str, row_count: int, column_count: int) -> CsvSnapshot` use the exact canonical preimage in the spec. Prefix is the 16 unpadded ASCII bytes synthetic_csv_v1; all counts/lengths are unsigned big-endian 32-bit values. EOF is accepted only at the final complete record and counts/hash must match.
- `SnapshotFiles(root: Path)` allocates without I/O; `open_root()` is a single-attempt operation that stores its directory descriptor before validation. `close()` explicitly retries retained cleanup. The manager stores this owner before calling open_root.
- `allocate(attempt) -> OwnedSnapshotFiles` and `allocate_complete(manifest) -> OwnedSnapshotFiles` allocate/register an exact file owner without I/O. The caller captures it before invoking `owner.create()` or `owner.open_complete()`. SnapshotFiles retains registered owners too, so a raise before return cannot lose acquired descriptors; root close denies while an owner remains unretired.
- `OwnedSnapshotFiles` provides `identities()`, `append(*, expected_offset, chunk)`, `seal_raw(*, content_length, content_sha256)`, `raw_fd`, `normalized_fd`, `verify_and_sync(manifest)`, the denying-only `protect_publication()`, and explicit `retire(*, remove_incomplete: bool)`. No method publishes visibility or closes another action's live descriptors.
- `OwnedSnapshotFiles.open_complete()` checks exact stored identity, private owner/mode, regular file, single link and bounded lengths through pinned descriptors. It supplies no caller path or lazy public reader. `retire()` is the named cleanup retry after any acquisition failure. Removal is denied for completed or commit-unknown content; only the operation coordinator's positively unpublished/reconciled-incomplete path can request it. File creation-before-identity recovery quarantines instead of deleting by name.

- [x] Write/run RED fixed-vector codec test for headers/data with leading zeroes, inert formulas, Unicode, quoted newlines and empty fields; assert encoded digest equals existing parser snapshot_identity.
- [x] Implement bounded codec; reject length/count overflow before allocation, malformed UTF-8/prefix/truncated/trailing bytes, mismatched manifest counts/hash and out-of-profile values. Roundtrip tests supplement fixed vectors, not replace them.
- [x] Write/run RED `test_exclusive_fixed_files_never_overwrite_and_require_identity_for_cleanup`; implement directory-relative exclusive creation and staged retirement with closed errors and repr-hidden private data.
- [x] Add symlink/hardlink/replacement, wrong mode/owner, partial write, offset mismatch, disk-full/fsync/close before-and-after-effect faults, interrupted creation and delayed I/O. Fault every open/O_EXCL immediately before and after its effect; the preallocated registered owner must retain the exact descriptor and explicitly retry cleanup even when create/open_complete raises. Bytes/identity must remain recoverable or conservatively quarantined; only positively owned incomplete files may be removed.
- [x] Verify codec/file tests plus existing CSV parser tests. Record source bytes/FD counts before/after; no global gateway/import activity. Freeze for independent artifact/file-lifetime review.

Checkpoint notes: the minimal decoder's negative corpus exceeded its bounded
RSS ceiling; retain that failed receipt and do not claim later cases executed.
The bounded successor completes the same corpus. File fault regressions reproduced
raw-before-handoff cleanup, final registry-release interruption and missing deletion
fsync; repairs retain positive ownership and durable cleanup stages. Protected
owners cannot delete even after a later pre-SQL denial. Unknown FD ownership is
qualified in disposable child processes; the helper itself grants no child-exit
proof or snapshot authority. The 699-case author gate passed on f024caf. Review
then reproduced a later-delete acknowledgment after retained-file retirement;
the successor records synchronized deletion separately and retains protection
after closure. A real FIFO probe also reproduced blocking before the file-type
check; nonblocking read-only acquisition and pre-adoption regular-file validation
now reject it promptly. The repaired focused author gate passed 191 cases including
the unchanged independent disposition probe. Independent review then passed 192 cases on exact 64ffea6, with no skips/warnings and clean retirement, after an explicit bad-mode fixture correction for umask 077. The old passing receipt does not cover these discovered gaps.

## Task 6: Run the existing parser in one owned bounded child

**Files:** Create `src/services/source_ingress/parser_worker.py`, `src/services/source_ingress/parser_owner.py`; create `tests/services/source_ingress/test_parser_owner.py`.

**Interfaces:**
- The worker is a fixed script launched by the current interpreter with -I -S -B. Its minimal stdlib bootstrap sets RLIMIT_AS=64 MiB, RLIMIT_FSIZE=2 MiB and one available CPU before importing the existing parser/codec. It receives only inherited raw/normalized descriptors, the actual coordinator lifetime-pin descriptor and bounded declared metadata, never request-selected paths/code. The child holds the pin until exit, installs a default-action wall timer for the remaining original absolute monotonic deadline before importing the parser, and never calls LOCK_UN or hands the descriptor to another worker.
- Closed result protocol: four-byte length plus at most 1,024 UTF-8 JSON bytes; exact fixed keys/status/counts/lengths/digests only, no objects/pickle/errors/prose. Parent rejects extra/truncated output before materialization. Stderr is discarded rather than included in errors.
- `OwnedParser` is captured before dup/spawn, retains the parser-tagged borrow, process pin and exact child/group until actual retirement, and exposes `run(files, request, *, deadline) -> ParserManifest` plus `close()`. The deadline is the earlier of five seconds from admission and the receiver's original deadline. No preexec_fn; no process-wide waitpid(-1)/subreaper/descendant sweep.
- Parser process exit alone is insufficient: parent verifies normalized bounded length/hash and closed result, then wait/descriptor retirement. Failure preserves receiver quota until all owned work retires.

- [x] Write/run RED a minimal valid parse through the actual child and private files, asserting exact strings/digests and no provider/runtime/network call.
- [x] Implement the fixed bootstrap/protocol and exact-owned-child terminate/kill/wait stages. Apply output-channel bounds before allocating its payload. Spawn failure/interruption retains the in-flight owner.
- [x] Measure legitimate boundary shapes under the actual 64-MiB address-space/five-second profile: near raw cap, many small fields, maximum rows/columns combinations, large UTF-8 fields and maximal admitted normalized representation. Record enforced limits separately from sampled RSS. If valid fixtures fail, stop for a reviewed profile change; do not silently raise the limit.
- [x] Add child hang/crash/memory/output/late-result tests, inherited-environment canaries, full result-pipe behavior, timeout before/after exit, failed signaling/wait and an unrelated live provider child. Retire only the parser child; uncertain wait retains its slot/quarantine. Use a real parent SIGKILL while the child is demonstrably alive: an independent process must fail to acquire the coordinator lease until actual child exit, then acquire a fresh legitimate generation successfully. No PID-guess cleanup or unrelated reaping is permitted; a stuck child conservatively keeps replacement blocked.
- [x] Verify parser/file/codec/CSV tests under the bounded supervisor. Freeze for independent process-ownership review.

Checkpoint notes: the actual worker passes exact1MiB raw and exact2MiB
normalized fixtures, 10,000 rows, 64 Unicode-heavy columns, and near-maximal
small-field object counts under the unchanged64MiB RLIMIT_AS profile. Sampled
RSS remains diagnostic. Fixed test-copy workers inject hangs/memory/output faults;
the parent-death case observes a live limited child, kills its actual parent,
proves replacement exclusion, then starts a fresh generation after actual exit.
Unknown constructor-spawn cases remain pinned until their disposable owner exits.
The eager application import boundary, result frames, full pipe, failed wait/signal,
unrelated provider child, copied/inherited owner and final response deadline are
covered. Timer setup, after-effect pipe close and bytecode-cache writes each had
observed RED before repair. The first parent-death fixture used a nonexistent store
property and remains a separate failed invocation. The combined author gate on
2e340ce passed 742 cases with 10 disclosed warnings and clean retirement.
Independent review then reproduced acceptance of unsupported UTF-16 result frames.
Strict UTF-8 decoding repairs that boundary; product UTF-16/BOM negatives were
RED, and the repaired parser plus unchanged independent probe passed 47 cases
with two warnings and clean retirement. UTF-32 frames are also denied, including
by the existing frame-size cap. Earlier passing counts remain attributed to their
exact source. Independent exact-a07f3e5 process/protocol/shared-pin review passed 87 cases
with two disclosed warnings, 13.868 seconds /347.105 MiB, unchanged source/guard
and clean retirement. This checkpoint is preserved in recovery version 18.
Receiver integration remains a separate Task 7 gate.

## Task 7: Receive chunks and publish an immutable manifest

**Files:** Create `src/services/source_ingress/snapshots.py`; create `tests/services/source_ingress/snapshot_fixtures.py`, `tests/services/source_ingress/test_snapshot_receiver.py`, `tests/services/source_ingress/test_snapshot_publication.py`. Narrow additions to Task 2 store methods are allowed only for these already-specified transitions. The reviewed composition adds the shared parser admission phase, closed snapshot action/receipt values, read-only action-scoped COMMIT facts, and bounded observational content audit in the existing parser/contracts/fence/file modules; their regression suites remain part of this checkpoint.

**Interfaces:**
- `SourceSnapshotManager(agent_runs, store, authority, root, *, expected_target_fingerprint, clock, monotonic)` requires an opened/upgraded/profile-verified V2 store. Missing authority or unsupported runtime denies admission.
- `begin_receive(*, operator_context, provider_connection_id, conversation_reference, request_key, reservation_id) -> ReceiverHandle | SnapshotReceipt` obtains the shared receiver slot, current fences and one durable claim/peak content reservation. Completed recovery returns its original receipt under source lifetime.
- `append_chunk(handle, *, operator_context, provider_connection_id, conversation_reference, expected_offset, chunk) -> None`; `finish(handle, *, same trusted context) -> SnapshotReceipt`; `abort(handle, *, same trusted context) -> AbortReceipt`. Handle identity is exact process-local membership; copied/forged objects confer nothing. Private request key/binding lives in the owned handle, never changes from later arguments.
- `SnapshotReceipt` is frozen/repr-safe: private snapshot ID, version=1, format=csv, row_count, column_count, original source expiry. It contains no values, hashes, paths, headers or authority. `AbortReceipt` acknowledges only a proven pre-publication abort with retired owned work; post-commit-admission abort raises unavailable/pending.
- Each receiver owns one in-flight action and its lifetime borrow, files, parser, fence executor and original grant/idle/whole clocks. A manager-owned watchdog retains active receivers and independently marks timeout/shutdown. Start it only when a receiver lifetime token is actually admitted, stop it when no owned receiver/retirement remains, and never start a lasting thread for an idle manager. The shared two-receiver cap consequently bounds these active watchdog owners. It never closes resources used by an in-flight action.
- The action result whitelist accepts only bounded immutable reservation/lifecycle/manifest facts, validated by exact member types. It never wraps a live scope or receiver handle. Read-only attempted/known COMMIT facts are action-scoped and distinct from an already committed manifest observed by this call.
- Parser admission pins its slot and original deadline before the fenced sealed-to-parsing transition. Spawn requires that transition's known COMMIT; busy admission must positively retire before leaving sealed retryable.
- Content audit only observes a bounded set of fixed names, identities, kinds, modes, links, lengths and allocated blocks. Unknown objects deny without repair; another claim's creation-before-recorded-identity window is a transient refusal. Only the actual creating owner may use its already captured descriptor identity to record its own files. Audit never adopts another attempt or supplies fresh-owner recovery.
- Complete manifests initially retain cleanup_pending. After positive receiver-token retirement, a separate ordinary fenced cleanup action may invoke acknowledge_retirement for the exact attempt/generation and actual retirement proof. Failure leaves the immutable completion and conservative incomplete-slot charge for authorized recovery/startup; it never downgrades or replays completion. Add tests for shutdown/expiry/quarantine between token retirement and that acknowledgment.
- `close()` stops admission and requests cleanup; uncertain work remains retained/quarantined. Closing/quarantine may deny new transaction borrows; in that case retire owned nonpublished files without inventing authority, retain durable capacity and leave failure reconciliation to startup.

- [x] Build `snapshot_target(tmp_path)` in snapshot_fixtures using the existing real waiting_target/SQLiteSourceAuthority ingredients, explicit SourceStoreOwner upgrade, current source reservation and a private content directory. Fixture teardown explicitly closes manager/store/agent and verifies no child/borrow/FD survives.
- [x] Write/run RED one real vertical: reserve exact CSV → begin → two chunks → finish → same-key completion recovery. Assert one immutable manifest, original expiry, equal private identity, one provider request only and unchanged conversation history/revision.
- [x] Implement one action owner and fixed state transitions. Authority checks precede all private identity-dependent results. Persist exclusive file identities before accepting bytes. Release all DB/authority fences during append/parser waits. Every call uses the original captured grant/whole deadline; only a successful nonempty append renews idle time.
- [x] Add duplicate/cross-process claims, forged/copy/foreign handles, offset/retransmission/length/hash/EOF errors, two receivers plus third denial, shared parser busy/sealed retry, and every authority/account/epoch/key/conversation denial boundary. Old completed files must remain byte-identical.
- [x] Add deterministic blocked append/fsync action tests. Watchdog/abort must deny publication, leave descriptors/slots/quota retained, and permit retirement only after the action returns. No successful cleanup acknowledgment may precede actual retirement.
- [x] Add publication-versus-abort barrier tests around the trusted precommit hook. The short mutex chooses one winner and samples clocks afterward; it is never held over SQL. If COMMIT admission won, abort cannot delete/free/claim success. Test commit return, unknown commit, response loss and expiry crossing during commit and cleanup.
- [x] Verify receiver/publication tests plus all existing reservation, source fence, Agent Run cleanup and authority-ordering cases. Freeze for independent receive/commit/timeout review.

Checkpoint notes: the real same-process vertical uses held SQLite authority and
conversation fences, actual bounded parser children and immutable fixed files.
Focused failures exposed invalid-input cleanup, abort/publication ordering,
post-I/O idle renewal, after-effect final token retirement, unknown acknowledgment
COMMIT, truncated-completion audit, retained scan cleanup and a failed-call versus
successor-action cleanup race. Each has a retained RED receipt and passing
successor. An active sibling audit now causes cleanup deferral with ownership
retained, without unnecessary quarantine. Admission checks the completed-count cap
before creating new files. Real 128-completion and near-content-cap runs passed
their assertions; their aggregate had one unrelated test-clock tolerance failure,
which is preserved separately. That fixture now uses paired explicit clocks rather
than assuming a real database operation always takes under 100 milliseconds.
The fresh final aggregate and independent review remain required. The initial
778-case compatibility pass is intermediate evidence, not the final gate.

The replacement-process test initially placed its exception handler after lease
construction and failed at the expected constructor denial; the corrected test
captures that actual acquisition boundary. One content-quota fixture initially
used incorrect parser keyword names; it is recorded as a fixture error. Neither
receipt is relabeled as product qualification. Known completed manifests are
retained across expired/revoked/shutdown admission and failed acknowledgment; no
completed-content deletion, startup reconciliation, private reader or public
source capability is implemented by this checkpoint. Task 8 remains separate.

Final author qualification: `snapshot-task7-author-final` passed 826 cases,
no skips and ten disclosed warnings in 122.259 seconds / 392.676 MiB. The exact
tracked-source manifest was unchanged throughout the run. Retirement required
no signals or forced cleanup and had no survivors; one exited zero-RSS child
was normally reaped. This run includes the actual 128-completion retention and
content-peak gates. Ruff, format and whitespace checks passed. This paragraph
is a documentation-only successor to those tested bytes. Independent Task 7
review is still required; Task 8 is not implemented by this checkpoint.
Independent review then reproduced raw ordinary clock exceptions at the final
post-acknowledgment response check. The narrow successor wraps only those clock
reads with the same closed-error rule, preserving control-flow interruption and
already committed/settled outcomes. Four product cases first failed while four
control-flow cases already passed; the original 826-case evidence remains on
34ad9b8 and does not cover this discovered gap. The repaired focused gate
`snapshot-final-clock-green` passes 96 cases (including the four unchanged
independent probes), with two separately qualified capacity cases deselected,
one warning, 12.697 seconds / 229.957 MiB, and clean retirement. It preserves
control-flow exceptions and never reverses the already durable outcome. Independent Task 7 review approved exact f7febb6 with 159 passing cases, no skips, eight disclosed warnings, and clean retirement, including both actual capacity cases.

## Task 8A prerequisite: Register startup readiness on the actual lease

**Files:** Narrow additions to `src/services/agent_runs/coordinator.py` and its
service accessor, `src/services/source_ingress/source_store_owner.py`, plus new
`tests/services/agent_runs/test_source_startup_registration.py`. No receiver/read
admission or actual recovery implementation in this first checkpoint. Freeze it
for independent shared-lifecycle review before proceeding with Task 8B below.

**Concrete private interfaces:**
- Frozen repr-safe `SourceStorageBinding`: exact bounded account/target strings,
  absolute store/root paths, their exact two-integer device/inode identities and
  positive current generation. It performs no I/O and contains no authority.
- `CoordinatorBorrow.allocate_source_startup(*, owner) -> CoordinatorSourceStartup`
  allocates an inert identity-guarded registration for the exact ordinary admitted
  token and original trusted maintenance owner. The caller captures it before
  `registration.acquire()` can install the single pending slot. It is not a
  request-selectable owner/callback or a generic plugin framework.
- `registration.publish(binding, *, owner)` is called only by the original
  SourceStoreOwner completion path after that exact maintenance operation proves
  all scopes retired. It atomically checks original registry/token membership and
  completed retirement plus lease admission. `registration.fail(*, owner)` is a
  denying-only sticky transition usable after final token retirement as well;
  it never releases a descriptor or erases a known database result.
- `CoordinatorLease.source_storage_binding()` and a matching availability-checked
  AgentRunService accessor return the exact immutable ready binding or deny. They
  do no SQL/provider work. `borrow_coordinator(source_work=..., source_binding=...)`
  passes a required exact binding for manager work and checks the service's stored
  generation; the later held conversation fence validates durable generation.
- A tagged borrow with no binding is a direct trusted helper call: allow it only
  while the lease has no startup registration. Every successful tagged admission
  sets sticky history before exposing the token. Once registration exists, every
  tagged call must supply the matching ready binding. Ordinary metadata borrows
  retain their existing path.
- SourceStoreOwner keeps the exact completion proof, maintenance scopes, original
  token and registration locally. The shared primitive cannot independently
  declare file/SQL retirement; it supplies no reconciliation shortcut. That prerequisite checkpoint supplied no readiness issuer; the real caller is implemented in Task 8B and awaits its final review.

**Required order for the later real operation:** capture ordinary borrow and
registration; register pending; capture/acquire conversation writer; capture
unopened dedicated SnapshotFiles owner before root open; capture/acquire source
transaction; validate inventory and pins; capture/retire each recovery file owner
and record explicit COMMIT outcome; retire dedicated scan/root; retire source
transaction/checkpoint; retire conversation; retire original token; publish ready
under the short lease transition. Every failure retains its exact current stage.

- [x] Baseline the unchanged lease/source-store-owner cases under the common lock.
- [x] RED missing readiness and simultaneous first registration. Implement only
  the closed registration/pin/identity primitive; do not add SQL/scan callbacks.
- [x] Qualify sticky prior helper history; pending/failed denial for every work
  tag; ordinary metadata compatibility; exact matching ready reuse and changed
  account/target/path/DB/root/generation denial across replacement objects.
- [x] Qualify copied/forged/forked identities before mutex access, retained original
  token ownership, and no readiness before positive original retirement.
- [x] Fault before/after registration and readiness publication, including final
  token retirement after-effect interruption. A close-between-retirement-and-ready
  barrier and shared quarantine must deny without undoing known outcome facts.
- [x] Verify the original SourceStoreOwner completion proof rejects live retained
  file/root/SQL/conversation scopes. No generic test-only proof factory may be
  wired to actual receiver admission.
- [x] Run shared lease/shutdown and existing source-store-owner regressions.
- [x] Freeze a clean user-attributed checkpoint and obtain independent review
  before Task 8B.

Author qualification: the unchanged baseline passed 137 cases. The missing
registration and maintenance-proof APIs first failed eight and seven cases,
respectively. A later fault-injection RED exposed four ordinary exception leaks
at the register/publish hooks; the closed-error repair preserves control-flow
exceptions and exact owned outcomes. `snapshot-startup-registration-qualified`
then passed 568 cases with ten disclosed dependency/fork warnings in 64.152
seconds / 380.672 MiB. The two unchanged expensive receiver capacity cases were
explicitly deselected; their prior Task 7 qualification remains separate. This
gate includes all Agent Run cases plus snapshot store/migration, reservation,
fence/recovery, parser and receiver/publication regressions. It retired without
signals, forced cleanup or survivors; one exited zero-RSS child was normally
reaped. The retained startup scope tests prove reverse resource retirement and
reject copied/live-scope completion proofs, but no production reconciliation
caller or readiness issuer existed at that checkpoint. Independent Task 8A review then approved exact b9bc1a1: 195 cases passed, no skips, four warnings in 12.257 seconds / 340.777 MiB, with unchanged source/guard and clean retirement. Task 8B alone adds the real issuer.

## Task 8B: Read privately and reconcile crashes without replay

**Files:** Extend `src/services/source_ingress/snapshots.py`, `src/services/source_ingress/source_store_owner.py`, `src/services/source_ingress/snapshot_store.py`, `src/services/source_ingress/snapshot_files.py`, `src/services/source_ingress/reservation_store.py` and the narrow parser binding argument in `parser_owner.py`; adapt real startup fixtures and receiver capacity/retry tests; create `tests/services/source_ingress/test_snapshot_reads.py`, `tests/services/source_ingress/test_snapshot_recovery.py`. Update the design/plan execution record with actual scope/evidence.

**Interfaces:**
- `describe_snapshot(*, operator_context, provider_connection_id, conversation_reference, request_key, private_snapshot_id) -> SnapshotReceipt` resolves current authority and exact original binding/source lifetime.
- `read_private_snapshot(*, same arguments) -> CsvSnapshot` pins one private-read lifetime borrow/generation through two fenced phases and bounded materialization. It returns fully materialized target-private values only after all scopes retire and the final captured expiry/deadline check passes.
- `SourceStoreOwner.reconcile_snapshots(files: SnapshotFiles) -> None` runs only under a fresh process-owned lease/generation before reception starts. It examines bounded account-owned metadata internally and reports no private rows. It never replays parser/chunk work. Acquisition of the fresh physical coordinator lease remains blocked by any surviving old parser's inherited pin, so startup cannot run around that work. Exact known completions remain immutable; only positively owned incomplete files may be retired/tombstoned after publication outcome has been resolved. A known committed manifest remains known if later inventory, checkpoint, open or cleanup fails; it becomes unavailable/quarantined rather than deleted or downgraded to failed. Missing identity/unknown bytes/unknown commit remain conservative until proven.

- [x] Write/run RED immutable private-read/reopen test and completed recovery after upload expiry but before original source expiry. Advance authority/conversation/source time during materialization and cleanup; values and metadata-dependent errors must pass the final response gate.
- [x] Implement the two-fence read with the same lifetime pin. Validate exact manifest and pinned file identities at both phases. The second fence is the linearization point; no lazy iterator or reusable authority escapes. Shared read cap is one across replacement managers.
- [x] Add actual fresh-process death barriers after claim commit, each file creation, identity commit, append/seal, parser output/exit, file fsync, directory fsync, before/after publication COMMIT and before response. Reopen with a new legitimate lease; assert no replay/remint, correct complete-versus-failed state and unchanged original lifetimes/capacity.
- [x] Add commit-unknown before/after-effect faults, cleanup before/after-effect interruption, parser/file action retirement faults, copied-process mutex denial, source quarantine across replacement managers, missing/corrupt/replaced completed content and creation-without-identity quarantine. Keep unknown files; never delete by basename alone.
- [x] Add actual SQLite authority/conversation races, pinned-reader refusal, observed allocation overage and every lifecycle-aware reserve cap after recovery. Same-key and conflict outcomes must not add provider calls or expose canaries. Explicitly assert that a committed manifest survives failed later checkpoint/inventory/cleanup byte-for-byte and its content is never selected for incomplete-file deletion.
- [x] Verify all source-ingress, Agent Run, source-free runtime, registry/default-catalog and MCP acceptance tests. Verify package discovery includes new modules/worker and no new public tool/route/runtime import is wired. Run Ruff/format/diff checks, freeze clean candidate and request final exact-head review.
- [ ] After approval only: fresh user-attributed gh-only draft PR with identical-tree mapping, fresh remote full backend/CI, match-head merge under existing authority, and exact-main focused lifecycle/entrypoint checks plus main CI. Update the same private recovery artifact, preserving failed/inconclusive evidence and #79's remaining boundaries.


Task 8B implementation and evidence record (final review pending): real startup
captures the pending registration before effects, rejects all current/newer
lifecycles before selecting deletion, audits the whole directory, binds exact
settlement proofs and preserves complete manifests through unknown COMMIT or
later cleanup failures. A permanent store-object maintenance claim prevents a
rejected owner from closing a winner's shared store; uninstalled separate-object
losers retire without quarantining the winner. The one new mutex rejects copied
and fork-inherited objects before acquisition.

Readiness is now actually issued after reverse retirement. Managers and their
parser/read tokens pass its exact binding. Private reads verify immutable bytes
between two real authority/conversation fences and apply the original response
clock/expiry bound after cleanup. Completed same-key recovery uses that same
verified path rather than trusting lengths. Early missing-API, binding, corruption,
known-busy and unknown scan-acquisition failures are preserved. The latter scan
failure reproduced premature token release; the repaired path retains/quarantines
it. Explicit manager.close separately reproduced two missing quarantine outcomes
and after-effect control-flow registry retention; its successor preserves genuine
busy deferral and positive final retirement while latching uncertain cleanup.

The actual capacity/retention cases passed again with fresh-generation complete
store startup inside the original two-second budget; the whole two-case slot was
56.902 seconds / 194.898 MiB. Crash cases use the real maintenance open as the
first post-death source SQLite connection; earlier fixtures that observed SQLite
first remain limited evidence. Five actual recovery-process death cases cover
partial deletion and before/after recovery COMMIT for incomplete/complete rows.
An integrated real parent-death case proves a surviving fixed parser blocks
replacement ownership until its exact pidfd reports exit, then startup reconciles
without touching an unrelated live child. The 72-case read/recovery gate passed
in 71.566 seconds / 360.496 MiB; the subsequent read-cleanup successor gate passed
32 cases in 9.296 seconds / 343.801 MiB. All these gates had no forced cleanup,
signals or surviving children; an exited zero-RSS orphan was normally reaped.
Broad author gates: `snapshot-task8b-source-qualified` passed 703 cases, with only the two separately qualified capacity cases deselected, in 109.336 seconds / 390.473 MiB. `snapshot-task8b-shared-qualified-corrected` passed 926 Agent Run/shared-runtime/source-free/registry/MCP/runner cases in 55.748 seconds / 448.797 MiB. All 1,274 recorded source hashes matched. Its first invocation used a nonexistent test path and executed zero tests; that failed receipt remains separate. Existing authority/conversation contention, pinned-reader refusal and observed allocation/cap tests remain in these source gates; the fresh read tests additionally revoke, relink or cancel through the real SQLite/service seams between fences. Startup proves the completed inventory and original capacity facts survive unchanged, including the actual 128-completion and near-content-cap stores.

A final static pass then found the matching receiver manager.close control-flow gap. Its four-case probe reported one failure and three passes; the narrow BaseException repair preserves known-busy deferral and positive final-token retirement. `snapshot-final-retirement-qualified` passed all 128 affected read/receiver/publication cases, with the same two separately qualified capacity cases deselected, in 21.041 seconds / 359.281 MiB. Earlier broad receipts remain attributed to their pre-repair bytes; the final remote full gate is still required. Every passing author gate retired without signal attempts, forced cleanup or survivors. An offline wheel build verified exact bytes for all 15 source-ingress modules, including the fixed worker; public API/control-plane/registry/provider artifacts/runtime/orchestrator/script files remain identical to cedc8a5. Final frozen independent review and publication remain pending.

## Self-review coverage

All eight tasks have a bounded useful deliverable and an independent gate. Profile/schema/accounting precede byte admission; shared lease and shared executor changes have separate gates. Codec/file ownership precedes parser and receiver use. Final recovery tests cover durable transitions instead of treating a successful happy path as crash proof. The approved managed-file-length limit is consistently distinct from observed allocated blocks and future filesystem quotas. The later transport, encryption/provisioning, public ID, source selection, mappings, previews and deployment surfaces are not implied by these checkboxes.
