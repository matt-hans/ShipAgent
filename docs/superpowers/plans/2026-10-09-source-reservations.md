# Fenced Source Reservations Implementation Plan

> **Execution:** Implement this plan serially, task by task, with the established independent reviewer and no additional author lanes.

**Goal:** Persist and recover bounded target-private source-setup reservations under a real ownership/authority fence, without accepting content or creating usable sources.

**Architecture:** One operation owner pins the existing coordinator lease, reserves the Agent Run writer, reserves the metadata-store writer, then acquires injected authority. It reads the owned waiting conversation on the held connection and explicitly commits only metadata before retiring every scope and the borrow token. Production authority remains absent/fail-closed.

**Tech Stack:** Python 3.12, existing SQLite/private-file/coordinator helpers, standard-library synchronization and JSON, pytest with disposable synthetic stores; no new dependency or daemon.

**Spec:** `docs/superpowers/specs/2026-10-09-source-reservation-fence-design.md` (source SHA-256 `7e5c35f06431753d1b7ae0df3ff94a6ec4da4496d316d087a884fb331686d1d7`).

The checkboxes below preserve the original serial execution checklist. They are not a claim that the broader ingress contract or milestone #79 is complete. The checkpoint record at the end identifies verified work and pending gates.

## Global Constraints

- Baseline: merged main `533eca6bf70cdd78fdb9b5fc86ef838d4ea57bee`; preserve prior refs and receipts.
- Native serial implementation by the integration owner, with independent review. Shared heavy lock; 2 CPUs and at most 1,536 MiB; every test through the reviewed supervisor.
- No production authority adapter, routes/tools, receiver, bytes, parser invocation, usable completed Source Reference, reader, mapping, active-source pointer or model/runtime admission.
- Both operations require operator-source-setup purpose and an owned, unexpired, epoch-bound `waiting_for_input` conversation.
- At most two live metadata reservations, 1,024 retained records, 4 MiB counted persisted metadata, 8 KiB per record. No pruning or recycling.
- Original upload expiry ≤ five minutes and prospective source expiry ≤ 24 hours from admission, both capped by original conversation expiry. `now >= expiry` is expired.
- One two-second monotonic operation deadline includes connection/PRAGMA/lock waits. This is not hostile-filesystem termination or physical disk-quota qualification.
- No authority → store acquisition; no arbitrary callbacks/network/parsing while store reservations are held.
- All product commits use verified repo-local matt-hans identity, no overrides. Publication remains gh-only through the established review/full/CI/main loop.

## File map

Modify:
- `src/services/agent_runs/coordinator.py`: lease borrow/closing lifetime primitive.
- `src/services/agent_runs/service.py`: early closing marker and trusted borrow accessor only.
- `src/services/agent_runs/store.py`: a narrow borrowed-conversation-fence factory, leaving unrelated connection callers unchanged.

Create:
- `src/services/agent_runs/source_ownership.py`: explicit owned conversation transaction with a shared deadline and bounded projections.
- `src/services/source_ingress/reservation_contracts.py`: closed purposes/errors, request and receipt types, canonical metadata validation/accounting.
- `src/services/source_ingress/reservation_store.py`: explicit private metadata store and transaction object; no content columns.
- `src/services/source_ingress/reservations.py`: operation coordinator and injected authority-scope protocol; no default adapter.
- `tests/services/agent_runs/test_coordinator_borrow.py` and `test_source_ownership.py`.
- `tests/services/source_ingress/test_reservation_contracts.py`, `test_reservation_store.py`, `test_reservations.py`, `test_reservation_recovery.py` and `reservation_fixtures.py`.

Preserve the historical source-ingress design/47-RED packet unchanged in its old worktree. Do not admit that whole unimplemented suite, blanket-xfail it or rename it into passing coverage. New cases cover only this selected slice.

## Review Focus

1. Close racing borrow/commit must never unlock the lease beneath owned work; Task 1 tests closing admission, repeated retirement and replacement denial.
2. A database/schema/PRAGMA wait before BEGIN must consume the same deadline; Task 2 tests contention at opening and after each wait.
3. New coordinator objects must not evade unknown-retirement quarantine; Tasks 4–5 test shared borrow-admission fencing and explicit owner restart.
4. Expiry during successful COMMIT must preserve the accepted record/capacity without acknowledging live authority; Task 5 tests after-commit failure and later original-key recovery.
5. Receipt/decoder helpers must not leak raw metadata or provide work after retirement; Tasks 3–4 test canaries, strict decoding and bounded materialized receipts.

## Validation wrapper and baseline

For each command below, invoke the current reviewed full supervisor with a unique receipt name, explicit checkout/interpreter, `--seconds 90 --rss-mib 768` (up to 1,024 MiB for the combined focused gate), and the common heavy lock. The supervisor is task-local and independently reviewed; do not commit its runtime state. Its frozen SHA is `b2dfa4da13a37eb90983c30a2d15d2ff892abe64a1d9b5adb1110e6f222571d0`.

Example command payload: project Python `-m pytest -p offline_pytest -q <exact test files>`. Do not launch bare pytest or change guards/environment to hide a failed check. Archive expected RED receipts and all retirement failures.

- [ ] Verify baseline/source identity and current Git author/committer. Run existing `test_coordinator.py`, cancellation service/store tests and `test_completion_failure_fence.py` before product edits. Any baseline failure is diagnosed first.

## Task 1: Pin coordinator lifetime through concurrent shutdown

**Files:** coordinator.py, service.py, new test_coordinator_borrow.py.

**Interfaces:**
- `CoordinatorLease.begin_close() -> None`: non-waiting admission marker; no descriptor release.
- `CoordinatorLease.borrow() -> CoordinatorBorrow`: reject closing/closed or wrong-process use, increment a protected count.
- `CoordinatorBorrow.require_owned() -> None`, `require_source_usable() -> None`; `retire() -> None`: process-bound proof and idempotent one-shot retirement; never decrement twice.
- `CoordinatorBorrow.retirement_completed -> bool`: positive cleanup evidence for the exact admitted token, with a weak admitted-token identity registry populated before admission exposes the token. It is true only when that weak marker exists and active membership is absent; unadmitted/copied tokens cannot gain it. Failed admission removes its weak marker before active membership; retirement itself only removes active membership. This proof grants no authority and does not unlock the owner.
- `CoordinatorBorrow.quarantine() -> None`: set a sticky source-only quarantine independent of normal closing, without releasing physical ownership. All current source operations check it after waits and before new commit/receipt; explicit retirement plus owner close/fresh lease/current generation/store reopen is required for recovery. New Python instances cannot clear it.
- Existing `is_owned/require_owned` continue to report actual held ownership while closing. `close()` itself atomically marks admission closing before checking the borrow count; with a live borrow it returns a fixed unavailable error, retains the descriptor, and never waits for database work. This is required even when called outside AgentRunService; the service’s earlier marker still protects its cleanup await.
- `AgentRunService.borrow_coordinator() -> tuple[CoordinatorBorrow, int]`: trusted internal accessor, only while the service/worker is available; no epoch resolution or model work.

- [ ] Write RED cases: two borrows; close rejects promptly and replacement lease fails; retirement of one cannot release the other; double retire does not underflow; new borrow after begin_close fails; physical ownership stays true for cleanup; final retirement does not automatically unlock; later close allows a fresh lease. Include same-thread reentrant close, cross-thread barriers and two admitted tokens where one quarantines the lease: the other source-use check and all new borrows fail, but physical ownership remains valid for cleanup.
- [ ] Add the service race: hold a source borrow, begin async close, prove new borrow admission closes before an existing cleanup await, prove provider cleanup still completes, then observe final close unavailable while borrow lives. Retire and call close again; restart succeeds. Source borrowing itself constructs no provider.
- [ ] Run the new file and observe actual missing-behavior failures.
- [ ] Implement with a short state mutex/count and one-shot tokens. Do not hold the mutex during store I/O or wait on it for the lifetime of a borrow. Mark lease admission closing at the start of service.close, before any await. Retain existing task cancellation/cleanup order.
- [ ] Run new tests plus all existing agent-run coordinator/cancellation/failure-fence tests. Run changed-file Ruff/check-format and diff checks.
- [ ] Commit this small user-attributed checkpoint and obtain independent shared-lifecycle review before Task 2. A failure here blocks subsequent source work.

## Task 2: Borrow a real conversation writer fence with one deadline

**Files:** store.py factory, new source_ownership.py and test_source_ownership.py.

**Interfaces:**
- `AgentRunStore.conversation_fence(*, borrow: CoordinatorBorrow, generation: int, monotonic: Callable[[], float] = time.monotonic) -> ConversationFence`: allocate an unacquired scope; no lookup or I/O in the factory.
- `ConversationFence.acquire(*, deadline: float) -> None`: verified connection and BEGIN IMMEDIATE under remaining monotonic budget.
- `ConversationFence.resolve(*, conversation_reference: str, connection_id: str, link_epoch: str, now: float) -> OwnedConversation`: called only after authority acquisition; returns immutable reference/revision/original-expiry/eligibility fields, never history.
- `ConversationFence.require_current(*, now: float) -> None`; `retire() -> None`: validate borrow/generation/file identity and retire the captured connection explicitly.

- [ ] Write RED tests for unknown/foreign/NULL-epoch and ineligible conversations, expired original lifetime, lost lease/generation, no history projection and no method use after retirement.
- [ ] Add actual separate-connection writer/schema contention: each acquire/PRAGMA consumes one deadline rather than receiving another three seconds. A held writer prevents cancellation from winning until this fence retires; after cancellation commits, fresh resolution fails.
- [ ] Implement a scope that owns its connection before opening/validation can fail, so failed cleanup remains recoverable by the operation owner. Preserve foreign-format checks before journal mutation and existing private-file/sidecar checks. Leave the old generic _connection default behavior intact.
- [ ] Recheck generation and expiry after all waits on the held connection; do not call store.read or an authority callback from resolve.
- [ ] Run new tests and the unchanged store/coordinator/continuation migration suites; verify the factory never recovers, advances generation or starts a provider. Commit and submit the narrow delta for review.

## Task 3: Bounded metadata schema and private reservation identity

**Files:** reservation_contracts.py, reservation_store.py, their two dedicated test files.

**Interfaces:**
- Frozen/slots `ReservationRequest(request_key: str, content_length: int, content_sha256: str, media_type: str = "text/csv", parser_profile: str = PARSER_PROFILE)`; no bytes/path/URL/epoch/fingerprint. Validate both constant fields exactly.
- Frozen `SourceOperatorContext(principal_reference: str)` is only a trusted-adapter selector, never proof by itself. Its string follows the resolved-identity bound and is repr-hidden.
- Frozen `ResolvedSourceAuthority(account_id: str, provider_connection_id: str, link_epoch: str, execution_target_id: str, target_fingerprint: str, purpose: Literal["operator_source_setup"], authorization_expires_at: int)`; fields are private/repr-hidden and come only from current adapter records.
- Private `ReservationNamespace` holds that binding plus conversation_reference, literal operation "upload", and request_key. The admitted conversation revision is recorded separately, not in the namespace.
- Frozen `ReservationReceipt(reservation_id: str, status: Literal["reserved"], admitted_at: int, upload_expires_at: int, prospective_source_expires_at: int)` is fully materialized. Use an independently random 32-lowercase-hex target-private ID from secrets.token_hex(16), not a provider-visible prefix. No binding, digest, storage occupancy or usable Source Reference escapes.
- `ReservationError` has fixed codes/messages: reservation_unavailable, reservation_expired, request_conflict, source_limit_exceeded, invalid_request. Raise without private parser/storage context.
- `ReservationStore(path, *, account_id, execution_target_id, create=False)` only validates and allocates. Explicit, single-attempt `open(*, deadline, monotonic=time.monotonic)` creates or verifies its private schema/owner and retains its setup scope before acquisition. A failed open never becomes ready, retries no initialization, and retains known setup commit evidence. `close()` explicitly retries any retained setup retirement; it never reclaims transaction scopes already handed to an operation owner. After failed open, reopening requires actual cleanup and a fresh store object. `transaction(*, monotonic=time.monotonic) -> ReservationTransaction` requires a ready store and allocates an unacquired scope with `acquire(deadline)`, explicit `commit()` and idempotent `retire()`. Acquisition checks only file/schema/owner identity, with reservation-row validation deferred to lookup/insert after authority.

- Private `ReservationRecord` wraps decoded fixed metadata and converts only to the receipt above. The transaction exposes `lookup(namespace: ReservationNamespace) -> ReservationRecord | None` and `insert(namespace, request, *, admitted_revision: int, admitted_at: int, upload_expires_at: int, prospective_source_expires_at: int) -> ReservationRecord`; both require its active acquired scope. The coordinator alone calls them after authority.

- [ ] Write RED tests for strict metadata types/bounds, bad Unicode/control characters, immutable bounded receipt projection, fixed canary-safe errors and unknown/corrupt stored JSON fields.
- [ ] Specify schema version 1 and SQLite application ID `0x53415352` (SASR), distinct from Agent Run storage. Persist the complete namespace and input identities as canonical fixed-key UTF-8 JSON; use private digests only for indexes and always compare decoded full identities. Use owner metadata plus reservation rows containing reservation_id, namespace_digest, input_digest, upload_expires_at, fixed-key JSON payload and metadata_bytes. Owner metadata and row logical bytes are counted; fixed-width integer accounting is an upper bound on persisted scalar encoding, while SQLite pages/index overhead remains separate. On the source-only connection, set SQLITE_LIMIT_LENGTH to 32 KiB and inspect stored field/payload byte lengths before materializing JSON; reject any payload/row above its 8 KiB logical limit. Decode strict fixed-key canonical JSON, revalidate hashes/bounds, and recompute logical accounting for the bounded retained rows rather than trusting metadata_bytes or a cached total. An oversized or counter-mismatched corrupt row makes the store unavailable before admission; no raw SQL/parser error escapes. Store no pickle, paths, SQL, rows or content blob.
- [ ] Implement a single metadata accounting function covering actual JSON bytes plus separately stored scalar/index/ID fields. Enforce 8 KiB per record, 4 MiB total, 1,024 retained records and two unexpired reservations before insertion. Identical replay checks precede capacity denial and do not insert/write another identity. Conflicts leave the original unchanged.
- [ ] Test exact serializer/accounting behavior, byte/count policy bounds with controlled small policy limits where the natural fixed-field profile makes a limit redundant, no extra record on conflict/retry, expired rows still counted, original times unchanged, owner/format/file replacement rejection, oversized stored payload/fields rejected before JSON materialization, understated/negative/mismatched accounting counters and rollback on SQL failure. Report logical versus physical SQLite bytes separately; do not claim disk quota.
- [ ] Prove construction performs no I/O, setup failure retains an explicitly retireable handle, failed open cannot become ready or retry, known commit evidence survives cleanup failure, and close leaves operation-owned transactions alone. Prove opening/acquisition never reads reservation rows, while post-authority lookup/insert still reject corrupt rows before use or admission.
- [ ] Run contract/store tests and existing CSV tests; commit the metadata-only checkpoint. No public API may bypass the operation coordinator to treat this store as authority.

## Task 4: One operation owner and real synthetic authority ordering

**Files:** reservations.py, test_reservations.py, reservation_fixtures.py; Task 1/2 interfaces remain unchanged unless separately reviewed.

**Interfaces:**
- `SourceAuthority.fence(operator_context: SourceOperatorContext, *, provider_connection_id: str, monotonic=time.monotonic, purpose: Literal['operator_source_setup']) -> AuthorityFence` returns an unacquired scope. No default implementation.
- `AuthorityFence.acquire(deadline)`, `resolve() -> ResolvedSourceAuthority`, `require_current(now)`, `retire()`: no store re-entry or network; preserve exclusion until actual retirement.
- `SourceReservationCoordinator(agent_runs: AgentRunService, store: ReservationStore, authority: SourceAuthority | None, *, expected_target_fingerprint: str, clock=time.time, monotonic=time.monotonic)`.
- `reserve(*, operator_context: SourceOperatorContext, provider_connection_id: str, conversation_reference: str, request: ReservationRequest) -> ReservationReceipt`.
- `recover(*, operator_context: SourceOperatorContext, provider_connection_id: str, conversation_reference: str, request_key: str) -> ReservationReceipt`.
- `close() -> None` retires captured scopes/borrows only; it cannot close the Agent Run owner's lease or silently reopen admission after uncertainty.

- [ ] Write one RED reservation/recovery tracer using the real Agent Run service/store with an already-waiting synthetic conversation. Capture provider/model call counts before reservation and assert unchanged afterward. Assert same key returns the same private ID and original times, with conversation revision/history/state byte-identical.
- [ ] Implement the disposable SQLite authority fixture: fresh process-owned connections, BEGIN IMMEDIATE held through the operation, fixture mutations through that same writer, no product-store access while holding authority. Its principal records are synthetic setup, not Auth0 evidence.
- [ ] Implement coordinator order exactly: borrow → Agent Run transaction → reservation transaction → authority → authority resolution and comparison to the constructor’s trusted target/key pin → conversation/identity lookup → lease/quarantine/generation/expiry checks → explicit source commit → materialized receipt → reverse retirement → token retirement. Allocate and retain every scope before acquisition. No implicit commit after leaving authority.
- [ ] The coordinator alone supplies the source transaction's private `_validate` pre-commit callback. After the transaction's owner/SQL checks, this callback rechecks only already-held guards, then samples UTC and monotonic time after every potentially waiting check, directly before the underlying COMMIT. It cannot be selected by request data or replace real authority exclusion. Expose separate `commit_attempted` and `committed` evidence so a callback denial before SQL can retire as an ordinary precommit denial; preserve post-commit and post-retirement expiry checks.
- [ ] Add actual two-process/connection ordering tests: invalidation first denies; source commit first persists then future operation denies. Include wrong principal/purpose/account/connection/epoch/target/key, missing adapter/outage, expired operator authorization, NULL epoch, changed-key conflict, independent conversations and no reference-existence leak. Pass the same monotonic dependency/deadline into all three scopes; reject nonfinite clock values as unavailable, not as an unlimited budget.
- [ ] Test cancelled/failed/completed/active conversation denial; continuation leaves reservation unchanged and makes recovery temporarily unavailable until the same owned conversation legitimately waits again. No source setup consumes clarification or increments revision.
- [ ] The final local deadline/expiry check occurs after successful context retirement and before acknowledgment; it uses the captured immutable result and clocks, not a reopened read or reused authority. Run the focused reservation/ownership suite plus relevant continuation/cancel tests. Commit and request independent ordering/privacy review before final failure qualification.

## Task 5: Expiry, uncertainty, retained ownership and process recovery

**Files:** test_reservation_recovery.py and only the preceding production files needed by observed failures.

- [ ] Reject copied source coordinators by PID before their state mutex. Reproduce interruption after final borrow retirement and before/after weak admission registration, and before/after actual retirement. Recognize completed cleanup only when all prior captured contexts retired and the exact token provides positive completion evidence; preserve control-flow propagation without fabricating an active borrow. Earlier uncertain retirement still retains/quarantines every remaining scope. Weak markers must not retain token tombstones or authorize copied/unadmitted tokens.

- [ ] Add RED controlled-clock tests after each acquisition wait, immediately before commit, after successful commit and during deliberately delayed retirement. Recheck the deadline/expiry after cleanup and immediately before acknowledgment; a result can be stale later in transit, but cleanup cannot silently skip this server-side check. Expired/deadline-crossed known commits remain stored/counting but produce no fresh-live acknowledgment. A valid subsequent same-key recovery is stable; expired records never get renewed.
- [ ] Inject real-commit-then-error and precommit rollback errors. Unknown outcome makes the instance unavailable and quarantines new source borrows on the shared lease; constructing a replacement coordinator cannot bypass it. Retain original identity/evidence/capacity.
- [ ] Inject authority/source/conversation retirement failure separately. Keep the exact captured handles and borrow; do not retire via unconditional finally. After actual successful retirement, require explicit owner close/restart and verified store reopen before recovery. Verify known-commit evidence is not overwritten by cleanup errors.
- [ ] Kill owned child processes before and after metadata commit, using fresh process-owned leases. Reopen with a fresh legitimate coordinator and recover the persisted same-key identity/expiry; prove rollback cases never produced an acknowledged reservation. No same-process/forked borrow state is used as cross-process authority.
- [ ] Verify no lazy scope/result use after retirement, no private metadata in repr/errors/logs, no byte/parser/model/tool calls, no source-family/public catalog change, and no pruning or automatic new-key retry.
- [ ] Run all agent-run/source-free/runtime, new reservation and CSV suites under the common supervisor; full Ruff/diff and exact source guards. Commit the final candidate with user identity.
- [ ] Independent exact-head source/failure review must pass before gh-only publication. Then run one fresh remote full backend suite, verify exact-head CI, guarded normal merge and focused fresh-main/source/CI gates. Do not count prior partial gates as a new full run.

## Plan self-review and handoff

The five review-focus risks map to explicit tests above. The plan changes only the named ownership/lifecycle seams and metadata package; no deferred receiver/source capability is implied. Actual production authority, physical storage quotas, hostile-storage termination and real client/deployment qualification remain open.

Implementation followed this independently reviewed serial plan in the existing worktree with the established reviewer. Local plan/spec files are not an authorization to deploy a new capability.

## Checkpoint qualification record

- The unchanged lifecycle baseline passed before implementation. Each stage preserved its expected RED evidence and independent review findings before repairs.
- Task 1: shared lease/shutdown checkpoint `68ec6de` passed independent review after the quarantine-latch repair; subsequent Task 5 retirement-proof refinements require the final combined review.
- Task 2: borrowed conversation fence `47d1b06` passed 162 author cases and 65 independent cases, including deadline/retirement faults.
- Task 3: bounded metadata store `d112f06` passed 149 author cases and 157 independent cases after repairing pre-authority record reads and retaining failed setup ownership.
- Task 4: operation coordinator `c67731a` passed 197 author cases. Independent qualification comprised 208 passing cases and two fresh-process ordering cases that passed after correcting the reviewer fixture cleanup. The initial fixture-failure receipt remains failed. The earlier error-response expiry gap was reproduced and repaired.
- Task 5: local qualification covers unknown COMMIT before/after durable effect, retained cleanup across replacement coordinator objects, fresh-process death before/after commit and after acknowledgment, acquisition/commit/retirement expiry, and concurrent owner shutdown. The frozen combined-candidate and independent exact-head gates are still pending at this checkpoint.
- Publication, fresh remote full backend regression, exact-head CI, normal merge and merged-main follow-through are pending. No production authority adapter, receiver, usable source, route or model admission is included.
