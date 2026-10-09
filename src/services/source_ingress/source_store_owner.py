"""Retained, thread-confined maintenance ownership before source disk effects.

Maintenance establishes target storage ownership only. It never resolves a
conversation or supplies operator authority. Every failed attempt retains its
captured scopes until explicit close; reopening requires a new owner/store.
"""

from __future__ import annotations

import math
import os
import threading
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field

from src.services.agent_runs.coordinator import (
    CoordinatorBorrow,
    CoordinatorSourceStartup,
    SourceStorageBinding,
)
from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.source_ownership import ConversationFence
from src.services.source_ingress.csv_snapshot import MAX_NORMALIZED_BYTES
from src.services.source_ingress.reservation_contracts import ReservationError
from src.services.source_ingress.reservation_store import (
    ReservationStore,
    ReservationTransaction,
)
from src.services.source_ingress.snapshot_files import OwnedSnapshotFiles, SnapshotFiles
from src.services.source_ingress.snapshot_store import SnapshotTransaction


@dataclass(repr=False)
class _Maintenance:
    borrow: CoordinatorBorrow | None = None
    conversation: ConversationFence | None = None
    source: ReservationStore | None = None
    transaction: ReservationTransaction | None = None

    def retire(self) -> None:
        if self.transaction is not None:
            self.transaction.retire()
            self.transaction = None
        if self.source is not None:
            self.source.close()
            self.source = None
        if self.conversation is not None:
            self.conversation.retire()
            self.conversation = None
        if self.borrow is not None:
            try:
                self.borrow.retire()
            except BaseException:
                if self.borrow.retirement_completed:
                    self.borrow = None
                raise
            self.borrow = None


@dataclass(repr=False)
class _StartupMaintenance(_Maintenance):
    """Captured startup resources retained through reconciliation and retirement."""

    registration: CoordinatorSourceStartup | None = None
    original_token: CoordinatorBorrow | None = None
    binding: SourceStorageBinding | None = None
    root: SnapshotFiles | None = None
    original_root: SnapshotFiles | None = None
    files: list[tuple[OwnedSnapshotFiles, bool]] = field(default_factory=list)
    reconciled: bool = False
    inventory: object | None = None
    inventory_audited: bool = False
    proofs: list = field(default_factory=list)
    commit_attempted: bool = False
    commit_known: bool = False

    def __post_init__(self) -> None:
        self._self = weakref.ref(self)
        self._pid = os.getpid()

    def require_identity(self) -> None:
        if self._pid != os.getpid() or self._self() is not self:
            raise ReservationError("reservation_unavailable")

    @property
    def retired(self) -> bool:
        self.require_identity()
        return not self.files and all(
            scope is None
            for scope in (
                self.root,
                self.transaction,
                self.source,
                self.conversation,
                self.borrow,
            )
        )

    def retire(self) -> None:
        self.require_identity()
        while self.files:
            owner, remove = self.files[-1]
            owner.retire(remove_incomplete=remove)
            self.files.pop()
        if self.root is not None:
            self.root.close()
            self.root = None
        super().retire()


class _StartupRecoveryProof:
    """One old row and original file owner under the retained startup writer."""

    def __init__(self, owner, operation, attempt, manifest, files):
        self._self = weakref.ref(self)
        self._owner, self._operation = owner, operation
        self._attempt, self._manifest, self._files = attempt, manifest, files
        self._token = operation.original_token
        self._transaction = operation.transaction

    def require(self, transaction, attempt):
        owner, operation, files = self._owner, self._operation, self._files
        owner._require_owner()
        operation.require_identity()
        if (
            self._self() is not self
            or owner._operation is not operation
            or not owner._running
            or self not in operation.proofs
            or operation.transaction is not transaction
            or transaction is not self._transaction
            or operation.borrow is not self._token
            or operation.original_token is not self._token
            or not operation.inventory_audited
            or operation.inventory.lifecycles.get(attempt.reservation_id) != attempt
            or attempt != self._attempt
            or operation.binding.generation <= attempt.generation
            or files._manager is not operation.original_root
            or not files._retired
            or not files._cleanup_finished
        ):
            raise ReservationError("reservation_unavailable")
        files._require_identity()
        self._token.require_source_usable()
        transaction._require_active()
        if self._manifest is not None:
            if (
                attempt.state != "complete"
                or files._value != self._manifest
                or files._verified_manifest != self._manifest
                or not files._protected
                or files._deletion_completed
            ):
                raise ReservationError("reservation_unavailable")
        elif (
            attempt.state == "complete"
            or files._value != attempt
            or not files._recovery
            or not files._deletion_completed
            or files._protected
        ):
            raise ReservationError("reservation_unavailable")


class SourceStoreOwner:
    def __init__(
        self,
        agent_runs: AgentRunService,
        store: ReservationStore,
        *,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            store.account_id != agent_runs.store.account_id
            or store.execution_target_id != agent_runs.store.execution_target_id
            or store.coordinator_path
            != agent_runs.store.path.with_suffix(".coordinator.lock")
        ):
            raise ReservationError("reservation_unavailable")
        self._agent_runs = agent_runs
        self._store = store
        self._clock = clock
        self._monotonic = monotonic
        self._pid = os.getpid()
        self._self = weakref.ref(self)
        self._thread = threading.get_ident()
        self._operation: _Maintenance | None = None
        self._attempted = False
        self._running = False
        self._closed = False
        self._failed = False
        self._opened = False
        self._startup_attempted = False
        self._store._claim_maintenance_owner(self)

    def _require_owner(self) -> None:
        if (
            self._pid != os.getpid()
            or self._self() is not self
            or self._store._maintenance_owner is not self
            or self._thread != threading.get_ident()
        ):
            raise ReservationError("reservation_unavailable")

    def _publish_startup(self, operation: _StartupMaintenance) -> None:
        """Private completion guard called only after real reconciliation retires."""
        self._require_owner()
        if (
            type(operation) is not _StartupMaintenance
            or self._operation is not operation
            or operation.reconciled is not True
            or not operation.retired
            or type(operation.binding) is not SourceStorageBinding
            or type(operation.registration) is not CoordinatorSourceStartup
            or operation.registration._owner is not self
            or operation.original_token is not operation.registration._borrow
            or not operation.original_token.retirement_completed
            or type(operation.original_root) is not SnapshotFiles
        ):
            raise ReservationError("reservation_unavailable")
        root, binding = operation.original_root, operation.binding
        root._require_identity()
        if (
            root._fd is not None
            or root._owners
            or root._scan is not None
            or root._ready
            or root._running
            or root._uncertain
            or not root._attempted
            or root._root_identity != binding.root_identity
            or root._root != binding.root_path
            or binding.account_id != self._store.account_id
            or binding.execution_target_id != self._store.execution_target_id
            or binding.store_path != self._store.path
            or binding.store_identity != self._store._identity
            or binding.generation != self._agent_runs._generation
        ):
            raise ReservationError("reservation_unavailable")
        try:
            operation.registration.publish(binding, owner=self)
        except BaseException as error:
            operation.registration.fail(owner=self)
            if isinstance(error, Exception):
                raise ReservationError("reservation_unavailable") from None
            raise

    def _now(self) -> float:
        value = self._monotonic()
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ReservationError("reservation_unavailable")
        return value

    def _quarantine(self) -> None:
        self._failed = True
        if (
            type(self._operation) is _StartupMaintenance
            and self._operation.registration is not None
            and self._operation.registration._borrow._lease._source_startup
            is self._operation.registration
        ):
            self._operation.registration.fail(owner=self)
        if self._operation is not None and self._operation.borrow is not None:
            self._operation.borrow.quarantine()

    def open(self) -> None:
        self._require_owner()
        if self._closed or self._attempted or self._operation is not None:
            raise ReservationError("reservation_unavailable")
        self._attempted = True
        self._run(upgrade=False)

    def upgrade_to_v2(self) -> None:
        self._require_owner()
        if (
            self._closed
            or self._failed
            or not self._opened
            or self._operation is not None
        ):
            raise ReservationError("reservation_unavailable")
        self._run(upgrade=True)

    def reconcile_snapshots(self, files: SnapshotFiles) -> None:
        """Reconcile once under physical ownership, then publish retired readiness."""
        self._require_owner()
        if (
            self._closed
            or self._failed
            or not self._opened
            or self._operation is not None
            or self._startup_attempted
            or type(files) is not SnapshotFiles
            or files._attempted
        ):
            raise ReservationError("reservation_unavailable")
        self._startup_attempted = True
        operation = _StartupMaintenance()
        self._operation = operation
        self._running = True
        try:
            deadline = self._now() + 2
            operation.borrow, generation = self._agent_runs.borrow_coordinator()
            operation.original_token = operation.borrow
            operation.registration = operation.borrow.allocate_source_startup(
                owner=self
            )
            operation.registration.acquire()
            operation.conversation = self._agent_runs.store.conversation_fence(
                borrow=operation.borrow,
                generation=generation,
                monotonic=self._monotonic,
            )
            operation.conversation.acquire(deadline=deadline)
            operation.root = operation.original_root = files
            files.open_root()
            operation.transaction = self._store.transaction(
                conversation=operation.conversation, monotonic=self._monotonic
            )
            operation.transaction.acquire(deadline=deadline)
            operation.binding = SourceStorageBinding(
                self._store.account_id,
                self._store.execution_target_id,
                self._store.path,
                self._store._identity,
                generation,
                files._root,
                files._root_identity,
            )
            self._reconcile_inventory(operation, deadline)
            operation.reconciled = True
            operation.retire()
            if self._now() >= deadline:
                raise ReservationError("reservation_unavailable")
            self._publish_startup(operation)
            if self._now() >= deadline:
                raise ReservationError("reservation_unavailable")
            self._operation = None
        except BaseException as error:
            installed = (
                operation.registration is not None
                and operation.registration._borrow._lease._source_startup
                is operation.registration
            )
            no_effects = (
                not installed
                and all(
                    scope is None
                    for scope in (
                        operation.original_root,
                        operation.conversation,
                        operation.source,
                        operation.transaction,
                    )
                )
                and not operation.files
            )
            if no_effects:
                self._failed = True
                try:
                    operation.retire()
                except BaseException as cleanup_error:
                    if not operation.retired:
                        self._quarantine()
                    if isinstance(error, Exception) or not isinstance(
                        cleanup_error, Exception
                    ):
                        error = cleanup_error
                if operation.retired:
                    self._operation = None
            else:
                self._quarantine()
            if isinstance(error, Exception):
                raise ReservationError("reservation_unavailable") from None
            raise error
        finally:
            self._running = False

    def _startup_current(self, operation, deadline):
        operation.original_token.require_source_usable()
        operation.conversation.require_storage_owner(
            account_id=self._store.account_id,
            execution_target_id=self._store.execution_target_id,
            coordinator_path=self._store.coordinator_path,
        )
        operation.original_root._check_root()
        if self._now() >= deadline:
            raise ReservationError("reservation_unavailable")

    def _startup_audit(self, operation, inventory):
        records, _ = operation.transaction._records(_include_snapshots=False)
        records = {item.receipt.reservation_id: item for item in records}
        manifests = {item.reservation_id: item for item in inventory.manifests.values()}
        expected = {}
        for attempt in inventory.lifecycles.values():
            if attempt.state == "failed" and not attempt.cleanup_pending:
                continue
            manifest = manifests.get(attempt.reservation_id)
            caps = (
                (manifest.raw_length, manifest.normalized_length)
                if manifest is not None
                else (
                    records[attempt.reservation_id].request.content_length,
                    MAX_NORMALIZED_BYTES,
                )
            )
            for name, identity, cap in zip(
                (attempt.raw_basename, attempt.normalized_basename),
                (attempt.raw_identity, attempt.normalized_identity),
                caps,
                strict=True,
            ):
                expected[name] = (
                    identity,
                    cap if manifest else 0,
                    cap,
                    manifest is not None,
                )
        operation.original_root.audit(expected)

    def _reconcile_inventory(self, operation, deadline):
        snapshot = SnapshotTransaction(operation.transaction)
        inventory = operation.inventory = snapshot.inventory(now=0)
        if any(
            item.generation >= operation.binding.generation
            for item in inventory.lifecycles.values()
        ):
            raise ReservationError("reservation_unavailable")
        self._startup_audit(operation, inventory)
        operation.inventory_audited = True
        manifests = {item.reservation_id: item for item in inventory.manifests.values()}
        changed = False
        for attempt in inventory.lifecycles.values():
            self._startup_current(operation, deadline)
            manifest = manifests.get(attempt.reservation_id)
            if manifest is None and not attempt.cleanup_pending:
                continue
            files = (
                operation.root.allocate_complete(manifest)
                if manifest is not None
                else operation.root.allocate_recovery(attempt)
            )
            # Capture before the first file-open effect, retaining even a partial acquisition.
            operation.files.append((files, False))
            if manifest is not None:
                files.open_complete()
            else:
                files.open_recovery()
                operation.files[-1] = (files, True)
            files.retire(remove_incomplete=manifest is None)
            if attempt.cleanup_pending:
                proof = _StartupRecoveryProof(self, operation, attempt, manifest, files)
                operation.proofs.append(proof)
                snapshot.reconcile_retirement(attempt, proof=proof)
                changed = True
        self._startup_audit(operation, snapshot.inventory(now=0))
        self._startup_current(operation, deadline)
        if changed:
            try:
                operation.transaction.commit(
                    _validate=lambda: self._startup_current(operation, deadline)
                )
            finally:
                operation.commit_attempted = operation.transaction.commit_attempted
                operation.commit_known = operation.transaction.committed

    def _run(self, *, upgrade: bool) -> None:
        operation = _Maintenance()
        self._operation = operation
        self._running = True
        try:
            deadline = self._now() + 2
            operation.borrow, generation = self._agent_runs.borrow_coordinator()
            operation.conversation = self._agent_runs.store.conversation_fence(
                borrow=operation.borrow,
                generation=generation,
                monotonic=self._monotonic,
            )
            operation.conversation.acquire(deadline=deadline)
            if upgrade:
                operation.transaction = self._store.transaction(
                    conversation=operation.conversation, monotonic=self._monotonic
                )
                operation.transaction.acquire(deadline=deadline)
                if operation.transaction.upgrade_schema():
                    operation.transaction.commit()
            else:
                operation.source = self._store
                self._store.open(
                    conversation=operation.conversation,
                    deadline=deadline,
                    monotonic=self._monotonic,
                )
                # Source open returned only after its own setup scope retired.
                operation.source = None
            operation.retire()
            self._operation = None
            if self._now() >= deadline:
                self._store.close()
                raise ReservationError("reservation_unavailable")
            self._opened = True
        except BaseException as error:
            self._quarantine()
            if isinstance(error, Exception):
                raise ReservationError("reservation_unavailable") from None
            raise
        finally:
            self._running = False

    def close(self) -> None:
        self._require_owner()
        if self._running:
            raise ReservationError("reservation_unavailable")
        self._closed = True
        try:
            if self._operation is not None:
                self._operation.retire()
                self._operation = None
            self._store.close()
        except BaseException as error:
            self._quarantine()
            if isinstance(error, Exception):
                raise ReservationError("reservation_unavailable") from None
            raise
