"""Source work is bounded by real lease tokens across every private owner."""

import pytest

from src.services.agent_runs import coordinator
from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore


def kinds():
    kind = getattr(coordinator, "SourceWorkKind", None)
    assert kind is not None, "closed source-work tags are not implemented"
    return kind


def test_receiver_cap_is_shared_but_inner_borrows_still_work(tmp_path):
    kind = kinds()
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    tokens = []
    try:
        tokens.extend(lease.borrow(source_work=kind.RECEIVER) for _ in range(2))
        with pytest.raises(RuntimeError, match="unavailable"):
            lease.borrow(source_work=kind.RECEIVER)
        tokens.append(lease.borrow())
        tokens.append(lease.borrow())
        tokens[0].retire()
        tokens[0].retire()
        tokens.append(lease.borrow(source_work=kind.RECEIVER))
        with pytest.raises(RuntimeError, match="unavailable"):
            lease.borrow(source_work=kind.RECEIVER)
        for token in tokens[1:]:
            token.require_source_usable()
    finally:
        for token in tokens:
            token.retire()
        lease.close()


async def test_service_work_borrow_keeps_database_and_provider_outside_admission(
    tmp_path, monkeypatch
):
    kind = kinds()
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("borrow must not perform SQL or provider work")

    service = AgentRunService(store=store, provider_factory=forbidden)
    await service.start()
    tokens = []
    try:
        with monkeypatch.context() as patch:
            patch.setattr(store, "is_current_generation", forbidden)
            tokens.extend(
                service.borrow_coordinator(source_work=kind.PARSER)[0] for _ in range(1)
            )
            with pytest.raises(RuntimeError, match="unavailable"):
                service.borrow_coordinator(source_work=kind.PARSER)
            token, generation = service.borrow_coordinator()
            tokens.append(token)
            assert generation > 0
    finally:
        for token in tokens:
            token.retire()
        await service.close()


@pytest.mark.parametrize(
    "name,cap", [("RECEIVER", 2), ("PARSER", 1), ("PRIVATE_READ", 1)]
)
def test_each_work_cap_is_shared_and_copied_retirement_cannot_release_it(
    tmp_path, name, cap
):
    from copy import copy

    kind = getattr(kinds(), name)
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    tokens = []
    try:
        tokens.extend(lease.borrow(source_work=kind) for _ in range(cap))
        other_owner = lease.borrow
        copy(tokens[0]).retire()
        coordinator.CoordinatorBorrow(lease, source_work=kind).retire()
        with pytest.raises(RuntimeError):
            other_owner(source_work=kind)
        tokens[0].retire()
        tokens.append(other_owner(source_work=kind))
        with pytest.raises(RuntimeError):
            other_owner(source_work=kind)
    finally:
        for token in tokens:
            token.retire()
        lease.close()


@pytest.mark.parametrize(
    "tag", ["receiver", "parser", "private_read", True, 1, object()]
)
def test_request_like_values_cannot_select_work_class(tmp_path, tag):
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    try:
        with pytest.raises(RuntimeError, match="unavailable"):
            lease.borrow(source_work=tag)
        assert not lease._borrows
    finally:
        lease.close()


def test_concurrent_last_parser_slot_has_exactly_one_owner(tmp_path):
    import threading

    kind = kinds()
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    barrier = threading.Barrier(5)
    results = []

    def contender():
        barrier.wait(timeout=2)
        try:
            results.append(lease.borrow(source_work=kind.PARSER))
        except RuntimeError:
            results.append(None)

    threads = [threading.Thread(target=contender) for _ in range(4)]
    try:
        for thread in threads:
            thread.start()
        barrier.wait(timeout=2)
        for thread in threads:
            thread.join(2)
            assert not thread.is_alive()
        assert len([token for token in results if token is not None]) == 1
    finally:
        for thread in threads:
            thread.join(2)
        for token in results:
            if token is not None:
                token.retire()
        lease.close()


def test_parser_pin_is_captured_before_duplicate_and_retirement_never_unlocks(tmp_path):
    import fcntl
    import os

    kind = kinds()
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow(source_work=kind.PARSER)
    pin = None
    try:
        assert hasattr(token, "allocate_process_pin"), (
            "owned parser descriptor pin is missing"
        )
        pin = token.allocate_process_pin()
        with pytest.raises(RuntimeError):
            token.retire()
        with pytest.raises(RuntimeError):
            _ = pin.child_fd
        pin.acquire()
        descriptor = pin.child_fd
        assert descriptor != lease._fd
        assert os.fstat(descriptor).st_ino == os.fstat(lease._fd).st_ino
        assert fcntl.fcntl(descriptor, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
        with pytest.raises(RuntimeError):
            token.retire()
        pin.retire()
        with pytest.raises(RuntimeError):
            _ = pin.child_fd
        token.require_owned()
        token.retire()
        with pytest.raises(RuntimeError, match="coordinator"):
            coordinator.CoordinatorLease(lease.path)
        assert lease.is_owned(), "pin cleanup must never LOCK_UN the shared description"
    finally:
        if pin is not None:
            pin.retire()
        token.retire()
        lease.close()


@pytest.mark.parametrize(
    "method", ["_duplicate_descriptor", "_adopt_descriptor", "_close_descriptor"]
)
@pytest.mark.parametrize("after_effect", [False, True])
@pytest.mark.parametrize("control_flow", [False, True])
def test_pin_effect_faults_retain_owner_for_explicit_cleanup(
    tmp_path, monkeypatch, method, after_effect, control_flow
):
    import os

    class Interrupted(BaseException):
        pass

    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow(source_work=kinds().PARSER)
    pin = None
    unrelated = None
    try:
        assert hasattr(token, "allocate_process_pin")
        pin = token.allocate_process_pin()
        if method == "_close_descriptor":
            pin.acquire()
            old_fd = pin.child_fd
        original = getattr(pin, method)

        def fail(*args):
            if after_effect:
                original(*args)
            if control_flow:
                raise Interrupted()
            raise OSError("PRIVATE_PIN_FAILURE_CANARY")

        with monkeypatch.context() as patch:
            patch.setattr(pin, method, fail)
            with pytest.raises(Interrupted if control_flow else RuntimeError) as error:
                pin.retire() if method == "_close_descriptor" else pin.acquire()
        assert "PRIVATE_" not in str(error.value)
        with pytest.raises(RuntimeError):
            token.retire()
        if method == "_close_descriptor" and after_effect:
            unrelated = os.open(tmp_path / "unrelated", os.O_RDWR | os.O_CREAT, 0o600)
            assert unrelated == old_fd, "fixture must reuse the just-closed descriptor"
        pin.retire()
        pin.retire()
        if unrelated is not None:
            os.fstat(unrelated)
        token.require_owned()
        token.retire()
        assert lease.is_owned()
    finally:
        if unrelated is not None:
            os.close(unrelated)
        if pin is not None:
            pin.retire()
        token.retire()
        lease.close()


@pytest.mark.parametrize("name", [None, "RECEIVER", "PRIVATE_READ"])
def test_only_exact_active_parser_token_may_allocate_one_pin(tmp_path, name):
    from copy import copy

    kind = kinds()
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow(source_work=getattr(kind, name) if name else None)
    parser = None
    pin = None
    try:
        assert hasattr(token, "allocate_process_pin")
        with pytest.raises(RuntimeError):
            token.allocate_process_pin()
        parser = lease.borrow(source_work=kind.PARSER)
        for invalid in (
            copy(parser),
            coordinator.CoordinatorBorrow(lease, source_work=kind.PARSER),
        ):
            with pytest.raises(RuntimeError):
                invalid.allocate_process_pin()
        pin = parser.allocate_process_pin()
        with pytest.raises(RuntimeError):
            parser.allocate_process_pin()
        pin.acquire()
        with pytest.raises(RuntimeError):
            copy(pin).retire()
        os_pin = pin.child_fd
        import os

        os.fstat(os_pin)
    finally:
        if pin is not None:
            pin.retire()
        if parser is not None:
            parser.retire()
        token.retire()
        lease.close()


@pytest.mark.parametrize("failure", ["adoption", "raw_close"])
def test_uncertain_fd_handoff_never_retries_reused_integer(tmp_path, failure):
    import subprocess
    import sys

    script = r"""
import os, sys
from pathlib import Path
from src.services.agent_runs.coordinator import CoordinatorLease, SourceWorkKind
path = Path(sys.argv[1])
lease = CoordinatorLease(path)
token = lease.borrow(source_work=SourceWorkKind.PARSER)
pin = token.allocate_process_pin()
real_close = os.close
if sys.argv[2] == 'adoption':
    def failed_adoption():
        fd = pin._opener(str(path), 0)
        real_close(fd)
        raise OSError('PRIVATE_CONSTRUCTOR_FAILURE')
    pin._adopt_descriptor = failed_adoption
    try:
        pin.acquire()
    except RuntimeError as error:
        assert 'PRIVATE_' not in str(error)
    else:
        raise AssertionError('adoption unexpectedly succeeded')
else:
    duplicate = pin._duplicate_descriptor
    def failed_return():
        duplicate()
        raise OSError('PRIVATE_OPENER_FAILURE')
    pin._duplicate_descriptor = failed_return
    try:
        pin.acquire()
    except RuntimeError:
        pass
    fd = pin._unadopted_fd
    def failed_close(value):
        assert value == fd
        real_close(value)
        raise OSError('PRIVATE_CLOSE_FAILURE')
    os.close = failed_close
    try:
        pin.retire()
    except RuntimeError as error:
        assert 'PRIVATE_' not in str(error)
    else:
        raise AssertionError('unknown raw close unexpectedly retired')
    finally:
        os.close = real_close
fd = pin._unadopted_fd
unrelated = os.open(path.with_suffix('.unrelated'), os.O_CREAT | os.O_RDWR, 0o600)
assert unrelated == fd
for action in (pin.retire, token.retire, lease.borrow, lease.close):
    try:
        action()
    except RuntimeError:
        pass
    else:
        raise AssertionError('uncertain owner admitted or retired')
os.fstat(unrelated)
real_close(unrelated)
assert lease.is_owned()
# Only process exit releases this genuinely uncertain synthetic ownership.
print('checked')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "owner.lock"), failure],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "checked"
    fresh = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    fresh.close()


def test_fixed_child_inherits_only_explicit_pin_and_parent_waits_before_retirement(
    tmp_path,
):
    import os
    import subprocess
    import sys

    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow(source_work=kinds().PARSER)
    pin = token.allocate_process_pin()
    process = None
    try:
        pin.acquire()
        fd = pin.child_fd
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import os,sys; fd=int(sys.argv[1]); print(os.fstat(fd).st_ino,flush=True); sys.stdin.read(1)",
                str(fd),
            ],
            pass_fds=(fd,),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.stdout.readline().strip() == str(os.fstat(fd).st_ino)
        assert process.poll() is None
        with pytest.raises(RuntimeError):
            lease.close()
        token.require_owned()
        process.communicate("x", timeout=5)
        assert process.returncode == 0
        pin.retire()
        token.retire()
        lease.close()
        fresh = coordinator.CoordinatorLease(lease.path)
        fresh.close()
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        pin.retire()
        token.retire()
        lease.close()


@pytest.mark.parametrize("boundary", ["closing", "quarantine", "identity_loss"])
def test_new_tagged_work_denies_after_admission_boundary(tmp_path, boundary):
    kind = kinds()
    path = tmp_path / "owner.lock"
    lease = coordinator.CoordinatorLease(path)
    token = lease.borrow()
    try:
        if boundary == "closing":
            lease.begin_close()
        elif boundary == "quarantine":
            token.quarantine()
        else:
            path.rename(tmp_path / "old.lock")
            path.touch(mode=0o600)
        for work in kind:
            with pytest.raises(RuntimeError):
                lease.borrow(source_work=work)
        token.retire()
    finally:
        token.retire()
        lease.close()


def test_inherited_pin_rejects_before_copied_mutex_and_preserves_parent_fd(tmp_path):
    import subprocess
    import sys

    script = r"""
import os, signal, sys
from pathlib import Path
from src.services.agent_runs.coordinator import CoordinatorLease, SourceWorkKind
lease = CoordinatorLease(Path(sys.argv[1]))
token = lease.borrow(source_work=SourceWorkKind.PARSER)
pin = token.allocate_process_pin()
pin.acquire()
lease._state_lock.acquire()
pid = os.fork()
if pid == 0:
    signal.alarm(2)
    for action in (pin.retire, pin.acquire, lambda: pin.child_fd, token.allocate_process_pin):
        try:
            action()
        except RuntimeError:
            pass
        else:
            os._exit(3)
    os._exit(0)
lease._state_lock.release()
assert os.waitpid(pid, 0)[1] == 0
os.fstat(pin.child_fd)
pin.retire()
token.retire()
lease.close()
print('checked')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "owner.lock")],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "checked"


@pytest.mark.parametrize("after_effect", [False, True])
def test_failed_tagged_admission_does_not_consume_parser_capacity(
    tmp_path, monkeypatch, after_effect
):
    class Interrupted(BaseException):
        pass

    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    kind = kinds()
    original = lease._registered_borrows.add
    captured = []

    def fail(token):
        captured.append(token)
        if after_effect:
            original(token)
        raise Interrupted()

    token = None
    try:
        with monkeypatch.context() as patch:
            patch.setattr(lease._registered_borrows, "add", fail)
            with pytest.raises(Interrupted):
                lease.borrow(source_work=kind.PARSER)
        assert len(captured) == 1 and not captured[0].retirement_completed
        token = lease.borrow(source_work=kind.PARSER)
        token.require_owned()
        with pytest.raises(RuntimeError):
            captured[0].allocate_process_pin()
    finally:
        if token is not None:
            token.retire()
        lease.close()


def test_pin_cleanup_uses_captured_owner_after_physical_identity_loss(tmp_path):
    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow(source_work=kinds().PARSER)
    pin = token.allocate_process_pin()
    try:
        pin.acquire()
        lease.path.rename(tmp_path / "old.lock")
        lease.path.touch(mode=0o600)
        with pytest.raises(RuntimeError):
            _ = pin.child_fd
        pin.retire()
        token.retire()
    finally:
        pin.retire()
        token.retire()
        lease.close()


@pytest.mark.parametrize("action_name", ["acquire", "retire"])
def test_stalled_pin_io_retains_ownership_without_blocking_shutdown(
    tmp_path, monkeypatch, action_name
):
    import threading

    lease = coordinator.CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow(source_work=kinds().PARSER)
    pin = token.allocate_process_pin()
    entered = threading.Event()
    release = threading.Event()
    shutdown_done = threading.Event()
    errors = []
    if action_name == "retire":
        pin.acquire()
    method = "_adopt_descriptor" if action_name == "acquire" else "_close_descriptor"
    original = getattr(pin, method)

    def blocked():
        entered.set()
        assert release.wait(3)
        original()

    def action():
        try:
            getattr(pin, action_name)()
        except BaseException as error:
            errors.append(error)

    def close():
        lease.begin_close()
        shutdown_done.set()

    worker = threading.Thread(target=action)
    closer = threading.Thread(target=close)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(pin, method, blocked)
            worker.start()
            assert entered.wait(1)
            closer.start()
            assert shutdown_done.wait(0.3), (
                "owned descriptor I/O blocked shutdown admission marker"
            )
            with pytest.raises(RuntimeError):
                lease.borrow()
            with pytest.raises(RuntimeError):
                lease.close()
            assert lease.is_owned()
            with pytest.raises(RuntimeError):
                pin.acquire()
            with pytest.raises(RuntimeError):
                pin.retire()
            with pytest.raises(RuntimeError):
                _ = pin.child_fd
            with pytest.raises(RuntimeError):
                token.retire()
            release.set()
            worker.join(2)
            closer.join(2)
            assert not worker.is_alive() and not closer.is_alive()
            assert not errors
        pin.retire()
        token.retire()
        lease.close()
        fresh = coordinator.CoordinatorLease(lease.path)
        fresh.close()
    finally:
        release.set()
        if worker.ident is not None:
            worker.join(3)
        if closer.ident is not None:
            closer.join(3)
        pin.retire()
        token.retire()
        lease.close()
