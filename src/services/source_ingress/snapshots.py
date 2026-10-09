"""Internal synthetic chunk reception; no transport or production admission."""

from __future__ import annotations

import math
import os
import secrets
import threading
import time
import weakref
from contextlib import contextmanager

from src.services.agent_runs.coordinator import SourceWorkKind
from src.services.source_ingress.csv_snapshot import MAX_NORMALIZED_BYTES
from src.services.source_ingress.parser_owner import OwnedParser
from src.services.source_ingress.reservation_contracts import ReservationError
from src.services.source_ingress.snapshot_contracts import (
    AbortReceipt,
    SnapshotManifest,
    SnapshotReceipt,
    _SnapshotActionValue,
    require_private_id,
)
from src.services.source_ingress.snapshot_files import SnapshotFiles
from src.services.source_ingress.snapshot_store import SnapshotTransaction
from src.services.source_ingress.source_fences import SourceFenceExecutor


def _unavailable():
    return ReservationError("reservation_unavailable")


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise _unavailable()
    return value


def _read_clock(clock):
    try:
        return _number(clock())
    except Exception:
        raise _unavailable() from None


class _ParserBusy(Exception):
    pass


class _WorkPending(Exception):
    pass


class _RetirementProof:
    """Exact claim/token proof, minted only by its already admitted receiver."""

    def __init__(self, owner):
        self._self = weakref.ref(self)
        self._owner = owner
        self._token = owner._borrow
        self._attempt_id = owner._attempt.attempt_id
        self._generation = owner._generation

    def require(self, attempt, generation):
        owner = self._owner
        owner._identity()
        if (
            self._self() is not self
            or owner._proof is not self
            or owner._borrow is not self._token
            or not self._token.retirement_completed
            or self._attempt_id != attempt.attempt_id
            or self._generation != generation
            or generation != attempt.generation
            or owner._attempt.reservation_id != attempt.reservation_id
            or not owner._resources_retired
            or owner._uncertain
            or owner._fence is not None
            or owner._abort_fence is not None
            or owner._aborting
            or owner._retiring
            or owner._running
        ):
            raise _unavailable()
        if attempt.state == "complete":
            if not owner._published:
                raise _unavailable()
        elif attempt.state == "failed":
            if not owner._deleted:
                raise _unavailable()
        else:
            raise _unavailable()


class _PrivateRead:
    """A captured read lifetime spanning both fences and private materialization."""

    def __init__(self, manager, *, deadline, expiry, manifest):
        self._manager = manager
        self._self = weakref.ref(self)
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._running = True
        self._retiring = False
        self._borrow = None
        self._fence = None
        self._files = None
        self._generation = None
        self._binding = manager._binding
        self._deadline = deadline
        self._expiry = expiry
        self._manifest = manifest
        self._value = None
        self._retired = False

    def _identity(self):
        self._manager._identity()
        if self._pid != os.getpid() or self._self() is not self:
            raise _unavailable()

    def _response_time(self):
        now = _read_clock(self._manager._clock)
        mono = _read_clock(self._manager._monotonic)
        if (
            self._manager._closed
            or mono >= self._deadline
            or self._expiry is not None
            and now >= self._expiry
        ):
            raise _unavailable()

    def _retire(self):
        self._identity()
        with self._lock:
            if self._running or self._retiring:
                raise _WorkPending()
            self._retiring = True
        try:
            if self._fence is not None:
                self._fence.close()
                self._fence = None
            if self._files is not None:
                self._files.retire(remove_incomplete=False)
                self._files = None
            if not self._manager._root.retire_audit():
                raise _WorkPending()
            if self._manager._root._uncertain:
                raise _unavailable()
            if self._borrow is not None:
                try:
                    self._borrow.retire()
                except BaseException:
                    if self._borrow.retirement_completed:
                        self._borrow = None
                    raise
                self._borrow = None
        finally:
            with self._lock:
                self._retiring = False
                self._retired = all(
                    scope is None for scope in (self._fence, self._files, self._borrow)
                )


class ReceiverHandle:
    """Exact process-local owner; possession never replaces current authority."""

    def __init__(self, manager, *, connection, conversation, key, reservation_id):
        self._manager = manager
        self._self = weakref.ref(self)
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._running = False
        self._action_thread = None
        self._aborting = False
        self._retiring = False
        self._borrow = None
        self._generation = None
        self._fence = None
        self._ack_fence = None
        self._abort_fence = None
        self._files = None
        self._parser = None
        self._proof = None
        self._record = None
        self._attempt = None
        self._manifest = None
        self._connection = connection
        self._conversation = conversation
        self._key = key
        self._reservation_id = reservation_id
        self._grant_expiry = None
        self._whole_deadline = None
        self._idle_deadline = None
        self._offset = 0
        self._cancelled = False
        self._commit_admitted = False
        self._published = False
        self._protected = False
        self._uncertain = False
        self._resources_retired = False
        self._retirement_failed = False
        self._deleted = False
        self._last_commit = (False, False)
        self._response_expiry = None
        self._response_deadline = None

    def _identity(self):
        self._manager._identity()
        if self._pid != os.getpid() or self._self() is not self:
            raise _unavailable()
        if self not in self._manager._admitted:
            raise _unavailable()

    def _live(self):
        self._identity()
        self._borrow.require_source_usable()
        self._times_current()
        self._response_time()

    def _response_time(self):
        now = _read_clock(self._manager._clock)
        mono = _read_clock(self._manager._monotonic)
        if any(
            now >= value
            for value in (self._grant_expiry, self._response_expiry)
            if value is not None
        ) or any(
            mono >= value
            for value in (
                self._whole_deadline,
                self._idle_deadline,
                self._response_deadline,
            )
            if value is not None
        ):
            raise _unavailable()

    def _times_current(self):
        mono = _number(self._manager._monotonic())
        now = _number(self._manager._clock())
        if (
            self._cancelled
            or self._uncertain
            or self._manager._closed
            or self._resources_retired
            or self._whole_deadline is not None
            and mono >= self._whole_deadline
            or self._idle_deadline is not None
            and mono >= self._idle_deadline
            or self._grant_expiry is not None
            and now >= self._grant_expiry
        ):
            raise _unavailable()

    def _deadline(self):
        values = [_number(self._manager._monotonic()) + 2]
        values.extend(
            v for v in (self._whole_deadline, self._idle_deadline) if v is not None
        )
        return min(values)

    @contextmanager
    def _action(self):
        self._identity()
        with self._lock:
            if (
                self._running
                or self._aborting
                or self._retiring
                or self._resources_retired
                or self._manager._closed
            ):
                raise _unavailable()
            self._running = True
            self._action_thread = threading.get_ident()
            self._response_expiry = self._response_deadline = None
        try:
            yield
        finally:
            with self._lock:
                self._running = False
                self._action_thread = None

    def _cleanup(self):
        self._identity()
        with self._lock:
            if (
                self._aborting
                or self._retiring
                or self._running
                and self._action_thread != threading.get_ident()
            ):
                raise _WorkPending
            self._retiring = True
        try:
            self._retire_owned()
        finally:
            with self._lock:
                self._retiring = False

    def _retire_owned(self):
        if self._parser is not None:
            self._parser.close()
        for name in ("_fence", "_ack_fence", "_abort_fence"):
            scope = getattr(self, name)
            if scope is not None:
                scope.close()
                setattr(self, name, None)
        if self._files is not None:
            remove = not (self._protected or self._uncertain or self._published)
            self._files.retire(remove_incomplete=remove)
            self._deleted = remove
        if not self._manager._root.retire_audit():
            raise _WorkPending
        if self._manager._root._uncertain:
            raise _unavailable()
        if self._borrow is not None:
            try:
                self._borrow.retire()
            except BaseException:
                # Every earlier scope has retired. Preserve positive evidence
                # when the final token reports failure after its real effect.
                if self._borrow.retirement_completed:
                    self._resources_retired = True
                raise
            if not self._borrow.retirement_completed:
                raise _unavailable()
        self._resources_retired = True


class SourceSnapshotManager:
    def __init__(
        self,
        agent_runs,
        store,
        authority,
        root,
        *,
        expected_target_fingerprint,
        clock=time.time,
        monotonic=time.monotonic,
    ):
        self._agent = agent_runs
        self._store = store
        self._authority = authority
        self._root = SnapshotFiles(root)  # Capture before open effects.
        self._fingerprint = expected_target_fingerprint
        self._clock = clock
        self._monotonic = monotonic
        self._pid = os.getpid()
        self._self = weakref.ref(self)
        self._lock = threading.Lock()
        self._owners = set()
        self._reads = set()
        self._admitted = weakref.WeakSet()
        self._ready = False
        self._binding = None
        self._closed = False
        self._watchdog = None
        self._watchdog_exiting = False
        self._watchdog_starting = False
        self._watchdog_stop = threading.Event()

    def _identity(self):
        if self._pid != os.getpid() or self._self() is not self:
            raise _unavailable()

    def open(self):
        self._identity()
        if self._closed or self._ready:
            raise _unavailable()
        try:
            self._binding = self._agent.source_storage_binding()
            if (
                self._binding.store_path != self._store.path
                or self._binding.store_identity != self._store._identity
                or self._binding.root_path != self._root._root
            ):
                raise _unavailable()
            self._store._require_files()
            self._root.open_root()
            if self._root._root_identity != self._binding.root_identity:
                raise _unavailable()
            if self._agent.source_storage_binding() != self._binding:
                raise _unavailable()
            self._ready = True
        except Exception:
            raise _unavailable() from None

    def _executor(self):
        return SourceFenceExecutor(
            self._agent,
            self._store,
            self._authority,
            expected_target_fingerprint=self._fingerprint,
            clock=self._clock,
            monotonic=self._monotonic,
        )

    def _start_watchdog(self):
        with self._lock:
            if self._closed:
                raise _unavailable()
            if self._watchdog_starting or (
                self._watchdog is not None
                and self._watchdog.is_alive()
                and not self._watchdog_exiting
            ):
                return
            prior = self._watchdog
            self._watchdog_starting = True
        try:
            if prior is not None and prior.is_alive():
                prior.join(0.2)
                if prior.is_alive():
                    raise _unavailable()
            thread = threading.Thread(
                target=self._watch, name="private-source-watchdog", daemon=True
            )
            with self._lock:
                self._watchdog = thread
                self._watchdog_exiting = False
            thread.start()
        except BaseException:
            self._closed = True
            self._watchdog_stop.set()
            raise
        finally:
            with self._lock:
                self._watchdog_starting = False

    def _watch(self):
        while not self._watchdog_stop.wait(0.05):
            with self._lock:
                owners = tuple(self._owners)
            for owner in owners:
                if owner._borrow is None or owner._resources_retired:
                    continue
                try:
                    owner._times_current()
                except Exception:
                    with owner._lock:
                        owner._cancelled = True
                with owner._lock:
                    if (
                        not owner._cancelled
                        or owner._running
                        or owner._resources_retired
                        or owner._retirement_failed
                        or owner._aborting
                        or owner._retiring
                    ):
                        continue
                    owner._running = True
                    owner._action_thread = threading.get_ident()
                try:
                    # Captured file/process cleanup needs no fresh operator grant.
                    # Uncertain thread-confined SQL stays with its original caller.
                    if any(
                        scope is not None
                        for scope in (
                            owner._fence,
                            owner._ack_fence,
                            owner._abort_fence,
                        )
                    ):
                        raise _unavailable()
                    owner._cleanup()
                except _WorkPending:
                    pass
                except BaseException:
                    owner._retirement_failed = True
                    if not owner._borrow.retirement_completed:
                        owner._borrow.quarantine()
                finally:
                    with owner._lock:
                        owner._running = False
                        owner._action_thread = None
            with self._lock:
                if not any(
                    owner._borrow is not None and not owner._resources_retired
                    for owner in self._owners
                ):
                    self._watchdog_exiting = True
                    return

    def _fenced(self, owner, arguments, action, *, acknowledgment=False, abort=False):
        owner._identity()
        name = "_abort_fence" if abort else "_ack_fence" if acknowledgment else "_fence"
        if getattr(owner, name) is not None:
            raise _unavailable()
        executor = self._executor()
        setattr(owner, name, executor)

        def invoke(held):
            with owner._lock:
                expiry = min(
                    held.resolved.authorization_expires_at, held.owned.expires_at
                )
                owner._response_expiry = (
                    expiry
                    if owner._response_expiry is None
                    else min(expiry, owner._response_expiry)
                )
            record = held.source.lookup(held.namespace)
            if (
                record is None
                or record.receipt.reservation_id != owner._reservation_id
                or owner._record is not None
                and record != owner._record
                or held.namespace.provider_connection_id != owner._connection
                or held.namespace.conversation_reference != owner._conversation
            ):
                raise _unavailable()
            snapshot = SnapshotTransaction(held.source)
            inventory = snapshot.inventory(now=held.require_current())
            self._audit(owner, held, inventory)
            attempt = inventory.lifecycles.get(record.receipt.reservation_id)
            manifest = next(
                (
                    item
                    for item in inventory.manifests.values()
                    if item.reservation_id == record.receipt.reservation_id
                ),
                None,
            )
            owner._record = record
            expiry = (
                record.receipt.prospective_source_expires_at
                if manifest is not None
                else record.receipt.upload_expires_at
            )
            held.set_response_expiry(expiry)
            with owner._lock:
                owner._response_expiry = min(owner._response_expiry, expiry)
                if manifest is not None and owner._whole_deadline is None:
                    owner._response_deadline = held.deadline
            return action(held, snapshot, attempt, manifest)

        try:
            return executor._run_action(
                **arguments,
                request_key=owner._key,
                action=invoke,
                deadline=None if acknowledgment else owner._deadline(),
            )
        finally:
            if executor._operation is None:
                executor.close()
                setattr(owner, name, None)
            else:
                owner._uncertain = True
                if owner._borrow is not None and not owner._borrow.retirement_completed:
                    owner._borrow.quarantine()

    def _audit(self, owner, held, inventory):
        records, _ = held.source._records(_include_snapshots=False)
        records = {record.receipt.reservation_id: record for record in records}
        manifests = {
            value.reservation_id: value for value in inventory.manifests.values()
        }
        expected = {}
        for attempt in inventory.lifecycles.values():
            if attempt.state == "failed" and not attempt.cleanup_pending:
                continue
            identities = (attempt.raw_identity, attempt.normalized_identity)
            own = (
                owner is not None
                and owner._attempt is not None
                and owner._attempt.attempt_id == attempt.attempt_id
            )
            if (
                identities[0] is None
                and own
                and owner._files is not None
                and not owner._resources_retired
            ):
                identities = owner._files.identities()
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
                identities,
                caps,
                strict=True,
            ):
                required = (
                    identity is not None
                    and attempt.state != "failed"
                    and not (own and owner._deleted)
                )
                expected[name] = (
                    identity,
                    cap if manifest is not None else 0,
                    cap,
                    required,
                )
        self._root.audit(expected)

    @staticmethod
    def _value(owner, held, attempt, manifest):
        value = _SnapshotActionValue(owner._record, attempt, manifest)
        held.set_result(value)
        return value

    def _commit(self, owner, held, attempt, manifest=None, *, terminal=False):
        value = self._value(owner, held, attempt, manifest)
        try:
            held.commit(
                before_commit=(lambda: self._publish_gate(owner)) if terminal else None
            )
        finally:
            owner._last_commit = held.commit_facts
            if owner._last_commit[1]:
                owner._attempt = attempt
                if terminal:
                    owner._published = True
                    owner._manifest = manifest
            elif owner._last_commit[0]:
                owner._uncertain = True
        return value

    @staticmethod
    def _receipt(manifest):
        return SnapshotReceipt(
            manifest.snapshot_id,
            manifest.row_count,
            manifest.column_count,
            manifest.source_expires_at,
        )

    def begin_receive(
        self,
        *,
        operator_context,
        provider_connection_id,
        conversation_reference,
        request_key,
        reservation_id,
    ):
        self._identity()
        if not self._ready or self._closed:
            raise _unavailable()
        require_private_id(reservation_id)
        owner = ReceiverHandle(
            self,
            connection=provider_connection_id,
            conversation=conversation_reference,
            key=request_key,
            reservation_id=reservation_id,
        )
        with self._lock:
            self._admitted.add(owner)
            self._owners.add(owner)
        owner._running = True
        owner._action_thread = threading.get_ident()
        arguments = {
            "operator_context": operator_context,
            "provider_connection_id": provider_connection_id,
            "conversation_reference": conversation_reference,
        }
        try:
            owner._borrow, owner._generation = self._agent.borrow_coordinator(
                source_work=SourceWorkKind.RECEIVER, source_binding=self._binding
            )
            self._start_watchdog()

            def claim(held, snapshot, attempt, manifest):
                if manifest is not None:
                    owner._attempt, owner._manifest = attempt, manifest
                    return self._value(owner, held, attempt, manifest)
                if attempt is not None:
                    raise _unavailable()
                owner._live()
                now = held.require_current()
                candidate = snapshot.claim(
                    owner._record,
                    generation=owner._generation,
                    authorization_expires_at=held.resolved.authorization_expires_at,
                    now=now,
                )
                owner._grant_expiry = candidate.authorization_expires_at
                owner._whole_deadline = _number(self._monotonic()) + min(
                    300, owner._grant_expiry - now
                )
                owner._idle_deadline = _number(self._monotonic()) + 10
                result = self._commit(owner, held, candidate)
                owner._proof = _RetirementProof(owner)
                return result

            self._fenced(owner, arguments, claim)
            if owner._manifest is not None:
                owner._cleanup()
                owner._response_time()
                self._release(owner)
                return self._read_completed(
                    **arguments,
                    request_key=owner._key,
                    private_snapshot_id=owner._manifest.snapshot_id,
                    values=False,
                    deadline=owner._response_deadline,
                    expiry=owner._response_expiry,
                    manifest=owner._manifest,
                    binding=self._binding,
                )
            owner._files = self._root.allocate(owner._attempt)
            owner._files.create()

            def record_files(held, snapshot, attempt, manifest):
                owner._live()
                if attempt != owner._attempt or manifest is not None:
                    raise _unavailable()
                updated = snapshot.record_files(
                    attempt, identities=owner._files.identities()
                )
                return self._commit(owner, held, updated)

            self._fenced(owner, arguments, record_files)
            owner._live()
            return owner
        except BaseException as error:
            try:
                owner._cleanup()
            except _WorkPending:
                pass
            except BaseException:
                if owner._borrow is not None and not owner._borrow.retirement_completed:
                    owner._borrow.quarantine()
            if isinstance(error, Exception):
                raise _unavailable() from None
            raise
        finally:
            with owner._lock:
                owner._running = False
                owner._action_thread = None
            if owner._resources_retired:
                self._release(owner)

    def _check(self, owner, arguments):
        if type(owner) is not ReceiverHandle or owner._manager is not self:
            raise _unavailable()

        def read(held, _snapshot, attempt, manifest):
            owner._live()
            if attempt != owner._attempt or manifest is not None:
                raise _unavailable()
            return self._value(owner, held, attempt, manifest)

        self._fenced(owner, arguments, read)

    def append_chunk(self, handle, *, expected_offset, chunk, **arguments):
        authorized = False
        try:
            with handle._action():
                self._check(handle, arguments)
                authorized = True
                if (
                    handle._attempt.state != "receiving"
                    or type(chunk) is not bytes
                    or not 0 < len(chunk) <= 65536
                    or type(expected_offset) is not int
                    or expected_offset != handle._offset
                    or handle._offset + len(chunk)
                    > handle._record.request.content_length
                ):
                    raise ReservationError("request_conflict")
                handle._files.append(expected_offset=expected_offset, chunk=chunk)
                handle._live()
                handle._offset += len(chunk)
                handle._idle_deadline = _number(self._monotonic()) + 10
                handle._live()
        except BaseException as error:
            if authorized:
                self._failed_cleanup(handle, arguments)
                if (
                    isinstance(error, ReservationError)
                    and error.code == "request_conflict"
                ):
                    handle._response_time()
            if isinstance(error, ReservationError):
                raise
            if isinstance(error, Exception):
                raise _unavailable() from None
            raise

    def _phase(self, owner, arguments, expected, state):
        def change(held, snapshot, attempt, manifest):
            owner._live()
            if attempt != owner._attempt or manifest is not None:
                raise _unavailable()
            updated = snapshot.set_phase(attempt, expected=expected, state=state)
            return self._commit(owner, held, updated)

        self._fenced(owner, arguments, change)

    def _publish_gate(self, owner):
        owner._live()
        with owner._lock:
            owner._times_current()
            owner._response_time()
            if owner._commit_admitted:
                raise _unavailable()
            owner._files.protect_publication()
            owner._protected = owner._commit_admitted = True
            owner._times_current()
            owner._response_time()

    def _finish_admitted(self, handle, arguments):
        if handle._attempt.state == "receiving":
            handle._files.seal_raw(
                content_length=handle._record.request.content_length,
                content_sha256=handle._record.request.content_sha256,
            )
            self._phase(handle, arguments, "receiving", "sealed")
        if handle._attempt.state != "sealed":
            raise _unavailable()
        handle._parser = OwnedParser(
            agent_runs=self._agent,
            monotonic=self._monotonic,
            source_binding=self._binding,
        )
        parser_deadline = min(handle._whole_deadline, handle._idle_deadline)
        try:
            handle._parser.admit(deadline=parser_deadline)
        except ReservationError:
            if handle._parser._borrow is None and handle._parser._retired:
                handle._live()
                raise _ParserBusy from None
            raise
        self._phase(handle, arguments, "sealed", "parsing")
        facts = handle._parser.run(
            handle._files, handle._record.request, deadline=parser_deadline
        )
        attempt = handle._attempt
        candidate = SnapshotManifest(
            secrets.token_hex(16),
            attempt.reservation_id,
            attempt.attempt_id,
            attempt.generation,
            facts.raw_content_sha256,
            facts.normalized_sha256,
            facts.raw_length,
            facts.normalized_length,
            facts.row_count,
            facts.column_count,
            facts.parser_profile,
            attempt.raw_identity,
            attempt.normalized_identity,
            handle._record.receipt.prospective_source_expires_at,
        )
        handle._files.verify_and_sync(candidate)
        self._phase(handle, arguments, "parsing", "staged")

        def complete(held, snapshot, current, manifest):
            handle._live()
            if current != handle._attempt or manifest is not None:
                raise _unavailable()
            updated = snapshot.complete(current, candidate)
            return self._commit(handle, held, updated, candidate, terminal=True)

        self._fenced(handle, arguments, complete)
        handle._cleanup()

    def finish(self, handle, **arguments):
        authorized = False
        try:
            with handle._action():
                self._check(handle, arguments)
                authorized = True
                self._finish_admitted(handle, arguments)
        except _ParserBusy:
            raise _unavailable() from None
        except BaseException as error:
            if authorized:
                self._failed_cleanup(handle, arguments)
            if isinstance(error, Exception):
                raise _unavailable() from None
            raise
        self._acknowledge(handle, arguments)
        handle._response_time()
        self._release(handle)
        return self._receipt(handle._manifest)

    def abort(self, handle, **arguments):
        if type(handle) is not ReceiverHandle or handle._manager is not self:
            raise _unavailable()
        handle._identity()
        with handle._lock:
            if (
                handle._aborting
                or handle._retiring
                or handle._commit_admitted
                or handle._resources_retired
                or self._closed
            ):
                raise _unavailable()
            handle._aborting = True
            if not handle._running:
                handle._response_expiry = handle._response_deadline = None
        try:

            def cancel(held, _snapshot, attempt, manifest):
                handle._live()
                if attempt != handle._attempt or manifest is not None:
                    raise _unavailable()
                value = self._value(handle, held, attempt, manifest)
                with handle._lock:
                    handle._times_current()
                    if handle._commit_admitted:
                        raise _unavailable()
                    handle._cancelled = True
                return value

            self._fenced(handle, arguments, cancel, abort=True)
        finally:
            with handle._lock:
                handle._aborting = False
        with handle._lock:
            if handle._running:
                raise _unavailable()
        if not self._failed_cleanup(handle, arguments):
            raise _unavailable()
        handle._response_time()
        return AbortReceipt(handle._reservation_id)

    def _release(self, owner):
        if (
            owner._resources_retired
            and not owner._uncertain
            and owner._fence is None
            and owner._ack_fence is None
            and owner._abort_fence is None
            and not owner._aborting
            and not owner._retiring
        ):
            with self._lock:
                self._owners.discard(owner)

    def _failed_cleanup(self, owner, arguments):
        """Retire captured effects; fresh authority can only record that outcome."""
        owner._cancelled = True
        try:
            owner._cleanup()
            if owner._protected or owner._uncertain or owner._published:
                return False
            if (
                owner._grant_expiry is None
                or _number(self._clock()) >= owner._grant_expiry
            ):
                return False

            def failed(held, snapshot, attempt, manifest):
                if (
                    attempt is None
                    or manifest is not None
                    or attempt.attempt_id != owner._attempt.attempt_id
                ):
                    raise _unavailable()
                updated = (
                    attempt
                    if attempt.state == "failed"
                    else snapshot.mark_failed(attempt, cleanup_complete=False)
                )
                return self._commit(owner, held, updated)

            self._fenced(owner, arguments, failed)
            self._acknowledge(owner, arguments)
            self._release(owner)
            return True
        except _WorkPending:
            return False
        except BaseException as error:
            owner._retirement_failed = True
            if not owner._resources_retired and owner._borrow is not None:
                owner._borrow.quarantine()
            if not isinstance(error, Exception):
                raise
            return False

    def _acknowledge(self, owner, arguments):
        def acknowledge(held, snapshot, attempt, manifest):
            updated = snapshot.acknowledge_retirement(
                attempt, generation=owner._generation, retirement_proof=owner._proof
            )
            return self._commit(owner, held, updated, manifest)

        self._fenced(owner, arguments, acknowledge, acknowledgment=True)

    def describe_snapshot(
        self,
        *,
        operator_context,
        provider_connection_id,
        conversation_reference,
        request_key,
        private_snapshot_id,
    ):
        return self._read_completed(
            operator_context=operator_context,
            provider_connection_id=provider_connection_id,
            conversation_reference=conversation_reference,
            request_key=request_key,
            private_snapshot_id=private_snapshot_id,
            values=False,
        )

    def read_private_snapshot(
        self,
        *,
        operator_context,
        provider_connection_id,
        conversation_reference,
        request_key,
        private_snapshot_id,
    ):
        return self._read_completed(
            operator_context=operator_context,
            provider_connection_id=provider_connection_id,
            conversation_reference=conversation_reference,
            request_key=request_key,
            private_snapshot_id=private_snapshot_id,
            values=True,
        )

    def _read_fence(self, owner, arguments, *, second):
        executor = self._executor()
        owner._fence = executor

        def observe(held):
            owner._borrow.require_source_usable()
            if (
                held.generation != owner._generation
                or self._agent.source_storage_binding() != owner._binding
            ):
                raise _unavailable()
            expires = min(held.resolved.authorization_expires_at, held.owned.expires_at)
            owner._expiry = (
                expires if owner._expiry is None else min(owner._expiry, expires)
            )
            snapshot = SnapshotTransaction(held.source)
            inventory = snapshot.inventory(now=held.require_current())
            self._audit(None, held, inventory)
            manifest = snapshot.lookup_manifest(
                held.namespace, arguments["private_snapshot_id"]
            )
            if owner._manifest is not None and owner._manifest != manifest:
                raise _unavailable()
            owner._manifest = manifest
            owner._expiry = min(owner._expiry, manifest.source_expires_at)
            held.set_response_expiry(owner._expiry)
            value = _SnapshotActionValue(
                held.source.lookup(held.namespace),
                inventory.lifecycles[manifest.reservation_id],
                manifest,
            )
            if second:
                if value != owner._value or owner._files.identities() != (
                    manifest.raw_identity,
                    manifest.normalized_identity,
                ):
                    raise _unavailable()
            self._root._check_root()
            owner._response_time()
            held.set_result(value)
            return value

        try:
            result = executor._run_action(
                **{
                    key: value
                    for key, value in arguments.items()
                    if key != "private_snapshot_id"
                },
                action=observe,
                deadline=owner._deadline,
            )
            if not second:
                owner._value = result
        finally:
            if executor._operation is None:
                executor.close()
                owner._fence = None

    def _read_completed(
        self,
        *,
        operator_context,
        provider_connection_id,
        conversation_reference,
        request_key,
        private_snapshot_id,
        values,
        deadline=None,
        expiry=None,
        manifest=None,
        binding=None,
    ):
        self._identity()
        if (
            not self._ready
            or self._closed
            or binding is not None
            and binding != self._binding
        ):
            raise _unavailable()
        require_private_id(private_snapshot_id)
        original_deadline = _read_clock(self._monotonic) + 2
        if deadline is not None:
            original_deadline = min(original_deadline, _number(deadline))
        owner = _PrivateRead(
            self, deadline=original_deadline, expiry=expiry, manifest=manifest
        )
        with self._lock:
            self._reads.add(owner)
        error, snapshot = None, None
        arguments = {
            "operator_context": operator_context,
            "provider_connection_id": provider_connection_id,
            "conversation_reference": conversation_reference,
            "request_key": request_key,
            "private_snapshot_id": private_snapshot_id,
        }
        try:
            owner._response_time()
            owner._borrow, owner._generation = self._agent.borrow_coordinator(
                source_work=SourceWorkKind.PRIVATE_READ, source_binding=owner._binding
            )
            self._read_fence(owner, arguments, second=False)
            owner._files = self._root.allocate_complete(owner._manifest)
            owner._files.open_complete()
            snapshot = owner._files.read_complete()
            self._read_fence(owner, arguments, second=True)
        except BaseException as caught:
            error = _unavailable() if isinstance(caught, Exception) else caught
        finally:
            with owner._lock:
                owner._running = False
            try:
                owner._retire()
            except _WorkPending:
                if error is None or isinstance(error, Exception):
                    error = _unavailable()
            except BaseException as caught:
                if not owner._retired and owner._borrow is not None:
                    owner._borrow.quarantine()
                if (
                    not isinstance(caught, Exception)
                    or error is None
                    or isinstance(error, Exception)
                ):
                    error = _unavailable() if isinstance(caught, Exception) else caught
            if owner._retired:
                with self._lock:
                    self._reads.discard(owner)
        if error is not None and not isinstance(error, Exception):
            raise error
        owner._response_time()
        if error is not None:
            raise error from None
        return snapshot if values else self._receipt(owner._manifest)

    def close(self):
        self._identity()
        self._closed = True
        self._watchdog_stop.set()
        failed = False
        with self._lock:
            owners = tuple(self._owners)
            reads = tuple(self._reads)
        for read in reads:
            try:
                read._retire()
            except _WorkPending:
                failed = True
            except BaseException as error:
                if not read._retired and read._borrow is not None:
                    read._borrow.quarantine()
                if not isinstance(error, Exception):
                    raise
                failed = True
            finally:
                if read._retired:
                    with self._lock:
                        self._reads.discard(read)
        for owner in owners:
            with owner._lock:
                owner._cancelled = True
                if owner._running or owner._aborting or owner._retiring:
                    failed = True
                    continue
                owner._running = True
                owner._action_thread = threading.get_ident()
            try:
                owner._cleanup()
            except _WorkPending:
                failed = True
            except BaseException as error:
                failed = True
                owner._retirement_failed = True
                if owner._borrow is not None and not owner._borrow.retirement_completed:
                    owner._borrow.quarantine()
                if not isinstance(error, Exception):
                    raise
            finally:
                with owner._lock:
                    owner._running = False
                    owner._action_thread = None
        if self._watchdog is not None and self._watchdog.is_alive():
            self._watchdog.join(0.2)
            failed = failed or self._watchdog.is_alive()
        if failed:
            raise _unavailable()
        self._root.close()
