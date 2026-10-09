"""Closed lease registration primitives; no fabricated reconciliation issuer."""

from dataclasses import replace

import pytest

from src.services.agent_runs import coordinator


class TrustedOwner:
    """Opaque identity for isolated primitive tests, never a source manager."""


def binding(tmp_path):
    model = getattr(coordinator, "SourceStorageBinding", None)
    assert model is not None, "lease-owned storage binding is missing"
    return model(
        account_id="account-a",
        execution_target_id="target-a",
        store_path=tmp_path / "sources.sqlite3",
        store_identity=(1, 2),
        generation=1,
        root_path=tmp_path / "content",
        root_identity=(1, 3),
    )


def test_registration_stays_pending_until_original_token_retires(tmp_path):
    value = binding(tmp_path)
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow()
    owner = TrustedOwner()
    try:
        with pytest.raises(RuntimeError):
            lease.source_storage_binding()
        registration = token.allocate_source_startup(owner=owner)
        registration.acquire()
        with pytest.raises(RuntimeError):
            registration.publish(value, owner=owner)
        for kind in coordinator.SourceWorkKind:
            for supplied in (None, value):
                with pytest.raises(RuntimeError):
                    lease.borrow(source_work=kind, source_binding=supplied)
        inner = lease.borrow()
        inner.retire()
        token.retire()
        registration.publish(value, owner=owner)
        assert lease.source_storage_binding() is value
        for kind in coordinator.SourceWorkKind:
            active = lease.borrow(source_work=kind, source_binding=value)
            active.require_source_usable()
            active.retire()
        assert lease.source_storage_binding() == value
    finally:
        for active in list(lease._borrows):
            active.retire()
        lease.close()


@pytest.mark.parametrize("tag", list(coordinator.SourceWorkKind))
def test_prior_tagged_helper_work_precludes_startup_even_after_retirement(
    tmp_path, tag
):
    binding(tmp_path)
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    try:
        helper = lease.borrow(source_work=tag)
        helper.retire()
        token = lease.borrow()
        registration = token.allocate_source_startup(owner=TrustedOwner())
        with pytest.raises(RuntimeError):
            registration.acquire()
        assert lease._source_startup is None
    finally:
        for active in list(lease._borrows):
            active.retire()
        lease.close()


@pytest.mark.parametrize("denial", ["closing", "quarantine", "failed"])
def test_retired_startup_never_publishes_after_admission_loss(tmp_path, denial):
    value = binding(tmp_path)
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow()
    owner = TrustedOwner()
    registration = token.allocate_source_startup(owner=owner)
    try:
        registration.acquire()
        token.retire()
        if denial == "closing":
            lease.begin_close()
        elif denial == "quarantine":
            inner = lease.borrow()
            inner.quarantine()
            inner.retire()
        else:
            registration.fail(owner=owner)
        with pytest.raises(RuntimeError):
            registration.publish(value, owner=owner)
        with pytest.raises(RuntimeError):
            lease.source_storage_binding()
        for kind in coordinator.SourceWorkKind:
            with pytest.raises(RuntimeError):
                lease.borrow(source_work=kind, source_binding=value)
    finally:
        token.retire()
        lease.close()


def test_ready_binding_requires_every_exact_pin_and_closed_argument_shape(tmp_path):
    value = binding(tmp_path)
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow()
    owner = TrustedOwner()
    registration = token.allocate_source_startup(owner=owner)
    try:
        registration.acquire()
        token.retire()
        registration.publish(value, owner=owner)
        for altered in (
            replace(value, account_id="other"),
            replace(value, execution_target_id="other"),
            replace(value, generation=2),
            replace(value, store_identity=(1, 4)),
            replace(value, root_identity=(1, 4)),
            replace(value, store_path=tmp_path / "other.sqlite3"),
            replace(value, root_path=tmp_path / "other"),
            None,
            {},
            True,
            object(),
        ):
            with pytest.raises(RuntimeError):
                lease.borrow(
                    source_work=coordinator.SourceWorkKind.RECEIVER,
                    source_binding=altered,
                )
        with pytest.raises(RuntimeError):
            lease.borrow(source_binding=value)
        assert not lease._borrows
    finally:
        token.retire()
        lease.close()


async def test_service_readiness_accessor_and_borrow_do_no_database_or_provider_work(
    tmp_path, monkeypatch
):
    from src.services.agent_runs.service import AgentRunService
    from src.services.agent_runs.store import AgentRunStore

    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("readiness transition must not use database or provider")

    service = AgentRunService(store=store, provider_factory=forbidden)
    await service.start()
    try:
        token, generation = service.borrow_coordinator()
        owner = TrustedOwner()
        registration = token.allocate_source_startup(owner=owner)
        registration.acquire()
        value = replace(binding(tmp_path), generation=generation)
        token.retire()
        registration.publish(value, owner=owner)
        with monkeypatch.context() as patch:
            patch.setattr(store, "is_current_generation", forbidden)
            assert service.source_storage_binding() is value
            active, current = service.borrow_coordinator(
                source_work=coordinator.SourceWorkKind.RECEIVER, source_binding=value
            )
            assert current == generation
            active.retire()
            with pytest.raises(RuntimeError):
                service.borrow_coordinator(
                    source_work=coordinator.SourceWorkKind.RECEIVER,
                    source_binding=replace(value, generation=generation + 1),
                )
    finally:
        for active in list(service._lease._borrows):
            active.retire()
        await service.close()


@pytest.mark.parametrize(
    "live_scope", ["borrow", "conversation", "transaction", "source", "root", "files"]
)
async def test_original_maintenance_proof_rejects_every_live_scope_and_copied_owner(
    tmp_path, live_scope
):
    from copy import copy

    from src.services.agent_runs.service import AgentRunService
    from src.services.agent_runs.store import AgentRunStore
    from src.services.source_ingress import source_store_owner
    from src.services.source_ingress.reservation_contracts import ReservationError
    from src.services.source_ingress.reservation_store import ReservationStore

    runs = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    service = AgentRunService(store=runs, provider_factory=lambda _: None)
    metadata = ReservationStore(
        tmp_path / "sources.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        coordinator_path=runs.path.with_suffix(".coordinator.lock"),
        create=True,
    )
    owner = source_store_owner.SourceStoreOwner(service, metadata)
    await service.start()
    token = None
    try:
        model = getattr(source_store_owner, "_StartupMaintenance", None)
        assert model is not None, "exact startup retirement proof is missing"
        owner.open()
        from src.services.source_ingress.snapshot_files import SnapshotFiles

        root_path = tmp_path / "content"
        root_path.mkdir(mode=0o700)
        root = SnapshotFiles(root_path)
        root.open_root()
        root.close()
        token, generation = service.borrow_coordinator()
        registration = token.allocate_source_startup(owner=owner)
        registration.acquire()
        token.retire()
        operation = model(
            original_token=token,
            registration=registration,
            original_root=root,
            binding=replace(
                binding(tmp_path),
                generation=generation,
                store_identity=metadata._identity,
                root_identity=root._root_identity,
            ),
        )
        owner._operation = operation
        # Even a trusted assertion of completed reconciliation cannot bypass
        # actual retained-scope checks or copied owner/operation identity.
        operation.reconciled = True
        setattr(
            operation, live_scope, [object()] if live_scope == "files" else object()
        )
        with pytest.raises(ReservationError):
            owner._publish_startup(operation)
        with pytest.raises(ReservationError):
            copy(owner)._publish_startup(operation)
        with pytest.raises(ReservationError):
            owner._publish_startup(copy(operation))
        with pytest.raises(RuntimeError):
            service._lease.source_storage_binding()
    finally:
        # Synthetic non-owners above performed no effects. This test never
        # supplies a positive factory or issues actual reconciliation readiness.
        owner._operation = None
        if token is not None:
            token.retire()
        owner.close()
        await service.close()


@pytest.mark.parametrize("phase", ["register", "publish"])
@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("control", [False, True])
def test_transition_interruption_latches_denial_and_preserves_owned_token(
    tmp_path, monkeypatch, phase, after, control
):
    value = binding(tmp_path)
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow()
    owner = TrustedOwner()
    registration = token.allocate_source_startup(owner=owner)
    method = "_register_locked" if phase == "register" else "_publish_locked"
    original = getattr(registration, method)
    if phase == "publish":
        registration.acquire()
        token.retire()

    def interrupted(*args):
        if after:
            original(*args)
        if control:
            raise KeyboardInterrupt("PRIVATE_STARTUP_CANARY")
        raise ValueError("PRIVATE_STARTUP_CANARY")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(registration, method, interrupted)
            with pytest.raises(
                KeyboardInterrupt if control else RuntimeError
            ) as caught:
                if phase == "register":
                    registration.acquire()
                else:
                    registration.publish(value, owner=owner)
        if not control:
            assert "PRIVATE_" not in str(caught.value)
        assert lease._source_startup is registration
        assert token.retirement_completed is (phase == "publish")
        assert lease.is_owned()
        for kind in coordinator.SourceWorkKind:
            for supplied in (None, value):
                with pytest.raises(RuntimeError):
                    lease.borrow(source_work=kind, source_binding=supplied)
        with pytest.raises(RuntimeError):
            lease.source_storage_binding()
        token.retire()
        registration.fail(owner=owner)
    finally:
        token.retire()
        lease.close()


def test_simultaneous_registration_has_one_exact_owner_and_no_replacement(tmp_path):
    import threading

    value = binding(tmp_path)
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    owners = [TrustedOwner(), TrustedOwner()]
    tokens = [lease.borrow(), lease.borrow()]
    registrations = [
        token.allocate_source_startup(owner=owner)
        for token, owner in zip(tokens, owners, strict=True)
    ]
    barrier = threading.Barrier(3)
    results = []

    def acquire(index):
        barrier.wait(timeout=2)
        try:
            registrations[index].acquire()
            results.append(index)
        except RuntimeError:
            pass

    threads = [threading.Thread(target=acquire, args=(index,)) for index in range(2)]
    try:
        for thread in threads:
            thread.start()
        barrier.wait(timeout=2)
        for thread in threads:
            thread.join(2)
            assert not thread.is_alive()
        assert len(results) == 1
        winner = results[0]
        for token in tokens:
            token.retire()
        registrations[winner].publish(value, owner=owners[winner])
        assert lease.source_storage_binding() is value
        with pytest.raises(RuntimeError):
            registrations[1 - winner].publish(value, owner=owners[1 - winner])
        assert lease.source_storage_binding() is value
    finally:
        for thread in threads:
            if thread.ident is not None:
                thread.join(2)
        for token in tokens:
            token.retire()
        lease.close()


def test_copied_registration_or_owner_cannot_publish_or_latch_original(tmp_path):
    from copy import copy

    value = binding(tmp_path)
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow()
    owner = TrustedOwner()
    registration = token.allocate_source_startup(owner=owner)
    try:
        registration.acquire()
        token.retire()
        for other, identity in (
            (copy(registration), owner),
            (registration, copy(owner)),
            (coordinator.CoordinatorSourceStartup(token, owner), owner),
        ):
            with pytest.raises(RuntimeError):
                other.publish(value, owner=identity)
            with pytest.raises(RuntimeError):
                other.fail(owner=identity)
        registration.publish(value, owner=owner)
        assert lease.source_storage_binding() is value
        registration.fail(owner=owner)
        with pytest.raises(RuntimeError):
            lease.source_storage_binding()
    finally:
        token.retire()
        lease.close()


@pytest.mark.parametrize("method", ["begin_close", "close"])
def test_close_wins_gap_after_final_retirement_before_ready(tmp_path, method):
    import threading

    value = binding(tmp_path)
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow()
    owner = TrustedOwner()
    registration = token.allocate_source_startup(owner=owner)
    registration.acquire()
    retired, closed = threading.Event(), threading.Event()

    def close():
        assert retired.wait(2)
        getattr(lease, method)()
        closed.set()

    thread = threading.Thread(target=close)
    try:
        thread.start()
        token.retire()
        retired.set()
        assert closed.wait(2)
        with pytest.raises(RuntimeError):
            registration.publish(value, owner=owner)
        registration.fail(owner=owner)
        with pytest.raises(RuntimeError):
            lease.source_storage_binding()
    finally:
        retired.set()
        thread.join(2)
        assert not thread.is_alive()
        token.retire()
        lease.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_id", ""),
        ("account_id", "x" * 257),
        ("account_id", "\ud800"),
        ("execution_target_id", True),
        ("execution_target_id", "a\0b"),
        ("generation", True),
        ("generation", 0),
        ("generation", 2**63),
        ("store_identity", [1, 2]),
        ("store_identity", (1, True)),
        ("root_identity", (-1, 2)),
        ("root_identity", (1, 2, 3)),
        ("root_identity", (1, 2**63)),
        ("root_path", "file:///content"),
    ],
)
def test_storage_binding_is_bounded_closed_data(tmp_path, field, value):
    with pytest.raises(RuntimeError, match="unavailable"):
        replace(binding(tmp_path), **{field: value})


@pytest.mark.parametrize("relative", [True, False])
def test_storage_binding_paths_are_absolute_bounded_and_never_resolved(
    tmp_path, monkeypatch, relative
):
    from pathlib import Path

    def forbidden(*args, **kwargs):
        raise AssertionError("binding construction must not resolve or inspect files")

    value = binding(tmp_path)
    monkeypatch.setattr(Path, "stat", forbidden)
    monkeypatch.setattr(Path, "resolve", forbidden)
    assert replace(value, root_path=tmp_path / "different")
    with pytest.raises(RuntimeError):
        replace(
            value,
            root_path=Path("relative") if relative else tmp_path / ".." / "different",
        )
    with pytest.raises(RuntimeError):
        replace(value, root_path=tmp_path / ("x" * 4096))


def test_copied_process_rejects_registration_before_inherited_mutex(tmp_path):
    import os
    import select
    import signal
    import time

    value = binding(tmp_path)
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow()
    owner = TrustedOwner()
    registration = token.allocate_source_startup(owner=owner)
    registration.acquire()
    reader, writer = os.pipe()
    lease._state_lock.acquire()
    pid = os.fork()
    if pid == 0:
        os.close(reader)
        try:
            for action in (
                registration.acquire,
                lambda: registration.publish(value, owner=owner),
                lambda: registration.fail(owner=owner),
                lease.source_storage_binding,
                lambda: token.allocate_source_startup(owner=owner),
            ):
                try:
                    action()
                except RuntimeError:
                    continue
                os._exit(3)
            os.write(writer, b"denied-before-mutex")
            os._exit(0)
        except BaseException:
            os._exit(4)
    os.close(writer)
    try:
        ready, _, _ = select.select([reader], [], [], 2)
        assert ready and os.read(reader, 64) == b"denied-before-mutex"
    finally:
        lease._state_lock.release()
        os.close(reader)
        deadline = time.monotonic() + 2
        observed, status = os.waitpid(pid, os.WNOHANG)
        while not observed and time.monotonic() < deadline:
            time.sleep(0.005)
            observed, status = os.waitpid(pid, os.WNOHANG)
        if not observed:
            # Only this exact test child is owned. Never reap or signal others.
            os.kill(pid, signal.SIGKILL)
            _, status = os.waitpid(pid, 0)
        token.retire()
        lease.close()
    assert os.waitstatus_to_exitcode(status) == 0


@pytest.mark.parametrize("after", [False, True])
async def test_interrupted_final_maintenance_retirement_does_not_issue_readiness(
    tmp_path, monkeypatch, after
):
    from src.services.agent_runs.service import AgentRunService
    from src.services.agent_runs.store import AgentRunStore
    from src.services.source_ingress.reservation_contracts import ReservationError
    from src.services.source_ingress.reservation_store import ReservationStore
    from src.services.source_ingress.source_store_owner import (
        SourceStoreOwner,
        _StartupMaintenance,
    )

    runs = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    service = AgentRunService(store=runs, provider_factory=lambda _: None)
    metadata = ReservationStore(
        tmp_path / "sources.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        coordinator_path=runs.path.with_suffix(".coordinator.lock"),
        create=True,
    )
    owner = SourceStoreOwner(service, metadata)
    await service.start()
    try:
        token, generation = service.borrow_coordinator()
        registration = token.allocate_source_startup(owner=owner)
        registration.acquire()
        operation = _StartupMaintenance(
            borrow=token,
            original_token=token,
            registration=registration,
            binding=replace(binding(tmp_path), generation=generation),
        )
        owner._operation = operation
        original = token.retire

        def interrupted():
            if after:
                original()
            raise KeyboardInterrupt("PRIVATE_FINAL_STARTUP_RETIRE")

        with monkeypatch.context() as patch:
            patch.setattr(token, "retire", interrupted)
            with pytest.raises(KeyboardInterrupt):
                operation.retire()
        assert token.retirement_completed is after
        assert (operation.borrow is None) is after
        owner._quarantine()
        with pytest.raises(ReservationError):
            owner._publish_startup(operation)
        with pytest.raises(RuntimeError):
            service.source_storage_binding()
        owner.close()
        assert token.retirement_completed
    finally:
        owner.close()
        await service.close()


@pytest.mark.parametrize("after", [False, True])
def test_failed_tag_admission_does_not_invent_startup_history(
    tmp_path, monkeypatch, after
):
    class Interrupted(BaseException):
        pass

    binding(tmp_path)
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    add = lease._registered_borrows.add

    def interrupted(token):
        if after:
            add(token)
        raise Interrupted

    try:
        with monkeypatch.context() as patch:
            patch.setattr(lease._registered_borrows, "add", interrupted)
            with pytest.raises(Interrupted):
                lease.borrow(source_work=coordinator.SourceWorkKind.PARSER)
        assert not lease._borrows and not lease._source_tagged_ever
        token = lease.borrow()
        registration = token.allocate_source_startup(owner=TrustedOwner())
        registration.acquire()
        assert lease._source_startup is registration
        token.retire()
    finally:
        for active in list(lease._borrows):
            active.retire()
        lease.close()


@pytest.mark.parametrize("tag", list(coordinator.SourceWorkKind))
def test_tagged_tokens_cannot_allocate_maintenance_registration(tmp_path, tag):
    binding(tmp_path)
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow(source_work=tag)
    try:
        with pytest.raises(RuntimeError):
            token.allocate_source_startup(owner=TrustedOwner())
        assert token._startup_registration is None and lease._source_startup is None
    finally:
        token.retire()
        lease.close()


async def test_captured_startup_scope_retires_real_resources_before_token_without_issuing_ready(
    tmp_path, monkeypatch
):
    import time

    from src.services.agent_runs.service import AgentRunService
    from src.services.agent_runs.store import AgentRunStore
    from src.services.source_ingress.reservation_contracts import ReservationError
    from src.services.source_ingress.reservation_store import ReservationStore
    from src.services.source_ingress.snapshot_contracts import (
        RESERVED_CONTENT_BYTES,
        SnapshotLifecycle,
    )
    from src.services.source_ingress.snapshot_files import SnapshotFiles
    from src.services.source_ingress.source_store_owner import (
        SourceStoreOwner,
        _StartupMaintenance,
    )

    runs = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    service = AgentRunService(store=runs, provider_factory=lambda _: None)
    metadata = ReservationStore(
        tmp_path / "sources.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        coordinator_path=runs.path.with_suffix(".coordinator.lock"),
        create=True,
    )
    owner = SourceStoreOwner(service, metadata)
    await service.start()
    try:
        owner.open()
        operation = _StartupMaintenance()
        owner._operation = operation
        operation.borrow, generation = service.borrow_coordinator()
        operation.original_token = operation.borrow
        operation.registration = operation.borrow.allocate_source_startup(owner=owner)
        operation.registration.acquire()
        deadline = time.monotonic() + 2
        operation.conversation = runs.conversation_fence(
            borrow=operation.borrow, generation=generation
        )
        operation.conversation.acquire(deadline=deadline)
        root_path = tmp_path / "content"
        root_path.mkdir(mode=0o700)
        operation.root = operation.original_root = SnapshotFiles(root_path)
        operation.root.open_root()
        operation.transaction = metadata.transaction(
            conversation=operation.conversation
        )
        operation.transaction.acquire(deadline=deadline)
        value = SnapshotLifecycle(
            "1" * 32,
            "2" * 32,
            generation,
            "receiving",
            int(time.time()) + 30,
            RESERVED_CONTENT_BYTES,
            "2" * 32 + ".raw",
            "2" * 32 + ".normalized",
        )
        files = operation.root.allocate(value)
        operation.files.append((files, True))
        files.create()
        order = []

        def track(scope, method, name):
            original = getattr(scope, method)

            def invoke(*args, **kwargs):
                original(*args, **kwargs)
                order.append(name)

            monkeypatch.setattr(scope, method, invoke)

        for scope, method, name in (
            (files, "retire", "files"),
            (operation.root, "close", "root"),
            (operation.transaction, "retire", "source"),
            (operation.conversation, "retire", "conversation"),
            (operation.borrow, "retire", "token"),
        ):
            track(scope, method, name)
        operation.retire()
        assert order == ["files", "root", "source", "conversation", "token"]
        assert operation.retired and operation.original_token.retirement_completed
        assert list(root_path.iterdir()) == []
        with pytest.raises(ReservationError):
            owner._publish_startup(operation)
        with pytest.raises(RuntimeError):
            service.source_storage_binding()
    finally:
        owner.close()
        await service.close()
