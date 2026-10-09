"""Owned source work pins the real coordinator through shutdown and retirement."""

import asyncio
import os
import sqlite3
import subprocess
import sys
import threading
import weakref
from contextlib import suppress
from copy import copy

import pytest

from src.services.agent_runs.coordinator import CoordinatorBorrow, CoordinatorLease
from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.conversation_runtime.models import ProviderCapabilities
from tests.services.conversation_acceptance import text_turn


def test_retirement_proof_belongs_only_to_exact_admitted_token(tmp_path):
    lease = CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow()
    copied = copy(token)
    unadmitted = CoordinatorBorrow(lease)
    try:
        assert not token.retirement_completed
        for other in (copied, unadmitted):
            other.retire()
            assert not other.retirement_completed
        token.require_owned()
        token.retire()
        assert token.retirement_completed
        assert not copy(token).retirement_completed
        assert not lease._borrows
        reference = weakref.ref(token)
        del token
        assert reference() is None, (
            "retirement evidence must not retain token tombstones"
        )
    finally:
        # The local name may already be deleted after the successful proof.
        for active in list(lease._borrows):
            active.retire()
        lease.close()


@pytest.mark.parametrize("effect", ["before", "after"])
def test_failed_admission_cannot_leave_a_retirement_proof(
    tmp_path, monkeypatch, effect
):
    class InterruptedAdmission(BaseException):
        pass

    lease = CoordinatorLease(tmp_path / "owner.lock")
    captured = []
    try:
        assert hasattr(lease, "_registered_borrows")
        add = lease._registered_borrows.add

        def interrupted_add(token):
            captured.append(token)
            if effect == "after":
                add(token)
            raise InterruptedAdmission

        with monkeypatch.context() as fault:
            fault.setattr(lease._registered_borrows, "add", interrupted_add)
            with pytest.raises(InterruptedAdmission):
                lease.borrow()
        assert len(captured) == 1
        assert not captured[0].retirement_completed
        with pytest.raises(RuntimeError):
            captured[0].require_owned()
        captured[0].retire()
        assert not captured[0].retirement_completed
        assert not lease._borrows
        assert not lease._registered_borrows
        token = lease.borrow()
        token.require_owned()
        token.retire()
        assert token.retirement_completed
    finally:
        for token in list(lease._borrows):
            token.retire()
        lease.close()


def test_close_retains_all_borrows_and_requires_later_explicit_close(tmp_path):
    path = tmp_path / "owner.lock"
    lease = CoordinatorLease(path)
    tokens = []
    try:
        tokens.extend([lease.borrow(), lease.borrow()])
        with pytest.raises(RuntimeError, match="unavailable"):
            lease.close()
        assert lease.is_owned()
        with pytest.raises(RuntimeError):
            lease.borrow()
        with pytest.raises(RuntimeError, match="coordinator"):
            CoordinatorLease(path)
        tokens[0].retire()
        tokens[0].retire()
        with pytest.raises(RuntimeError):
            tokens[0].require_owned()
        tokens[1].require_owned()
        with pytest.raises(RuntimeError):
            lease.close()
        tokens[1].retire()
        assert lease.is_owned(), "last retirement must not unlock automatically"
        with pytest.raises(RuntimeError):
            CoordinatorLease(path)
        lease.close()
        assert not lease.is_owned()
        with pytest.raises(RuntimeError):
            lease.borrow()
        replacement = CoordinatorLease(path)
        replacement.close()
    finally:
        for token in tokens:
            token.retire()
        lease.close()


def test_begin_close_rejects_new_work_but_preserves_admitted_ownership(tmp_path):
    lease = CoordinatorLease(tmp_path / "owner.lock")
    token = None
    try:
        token = lease.borrow()
        lease.begin_close()
        lease.begin_close()
        with pytest.raises(RuntimeError):
            lease.borrow()
        lease.require_owned()
        token.require_owned()
        token.require_source_usable()
    finally:
        if token is not None:
            token.retire()
        lease.close()


def test_source_quarantine_is_shared_sticky_and_not_physical_lease_loss(tmp_path):
    path = tmp_path / "owner.lock"
    lease = CoordinatorLease(path)
    tokens = []
    try:
        tokens.extend([lease.borrow(), lease.borrow()])
        tokens[0].quarantine()
        tokens[0].quarantine()
        for token in tokens:
            token.require_owned()
            with pytest.raises(RuntimeError):
                token.require_source_usable()
        with pytest.raises(RuntimeError):
            lease.borrow()
        for token in tokens:
            token.retire()
        with pytest.raises(RuntimeError):
            lease.borrow()
        assert lease.is_owned()
        lease.close()
        fresh = CoordinatorLease(path)
        try:
            new = fresh.borrow()
            new.require_source_usable()
            new.retire()
        finally:
            fresh.close()
    finally:
        for token in tokens:
            token.retire()
        lease.close()


def test_admitted_quarantine_survives_transient_ownership_check_failure(
    tmp_path, monkeypatch
):
    lease = CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow()

    def file_check_unavailable(*args, **kwargs):
        raise OSError("SYNTHETIC_FILE_CHECK_OUTAGE")

    try:
        with monkeypatch.context() as fault:
            fault.setattr(
                "src.services.agent_runs.coordinator.require_private_file",
                file_check_unavailable,
            )
            with pytest.raises(RuntimeError, match="unavailable"):
                token.require_owned()
            token.quarantine()
        token.require_owned()
        with pytest.raises(RuntimeError, match="unavailable"):
            lease.borrow()
        with pytest.raises(RuntimeError, match="unavailable"):
            token.require_source_usable()
    finally:
        token.retire()
        lease.close()


def test_cross_thread_close_does_not_wait_or_unlock_under_borrow(tmp_path):
    lease = CoordinatorLease(tmp_path / "owner.lock")
    token = None
    thread = None
    finished = threading.Event()
    results = []

    def attempt_close():
        try:
            lease.close()
        except RuntimeError:
            results.append("unavailable")
        else:
            results.append("closed")
        finally:
            finished.set()

    try:
        token = lease.borrow()
        thread = threading.Thread(target=attempt_close, daemon=True)
        thread.start()
        assert finished.wait(1), "close must not wait for the borrow lifetime"
        assert results == ["unavailable"]
        token.require_owned()
        with pytest.raises(RuntimeError):
            lease.borrow()
    finally:
        if token is not None:
            token.retire()
        if thread is not None:
            thread.join(1)
            assert not thread.is_alive()
        lease.close()


async def test_service_borrow_does_not_open_database_or_construct_provider(
    tmp_path, monkeypatch
):
    def forbidden_provider(_):
        raise AssertionError("borrowing must not construct a provider")

    def forbidden_database(*args, **kwargs):
        raise AssertionError("borrowing must not open a database")

    service = AgentRunService(
        store=AgentRunStore(
            tmp_path / "runs.sqlite3",
            account_id="account-a",
            execution_target_id="target-a",
            create=True,
        ),
        provider_factory=forbidden_provider,
    )
    token = None
    with pytest.raises(RuntimeError, match="unavailable"):
        service.borrow_coordinator()
    await service.start()
    try:
        with monkeypatch.context() as guard:
            guard.setattr(sqlite3, "connect", forbidden_database)
            token, generation = service.borrow_coordinator()
            assert type(generation) is int and generation > 0
            token.require_owned()
        assert service.store.is_current_generation(generation)
    finally:
        if token is not None:
            token.retire()
        await service.close()
    with pytest.raises(RuntimeError, match="unavailable"):
        service.borrow_coordinator()


async def test_service_closes_borrow_admission_before_cleanup_await(tmp_path):
    started = asyncio.Event()
    release = asyncio.Event()
    token = None
    close_task = None

    class HeldCleanup(FakeProviderClient):
        async def cancel(self):
            started.set()
            while not release.is_set():
                with suppress(asyncio.CancelledError):
                    await release.wait()
            token.require_owned()
            self.cancelled = True

    provider = HeldCleanup(
        script=[text_turn("Private plan")],
        capabilities=ProviderCapabilities(
            provider="fake", model="fake", supports_cancellation=True
        ),
    )
    service = AgentRunService(
        store=AgentRunStore(
            tmp_path / "runs.sqlite3",
            account_id="account-a",
            execution_target_id="target-a",
            create=True,
        ),
        provider_factory=lambda _: provider,
    )
    await service.start()
    lease = service._lease
    try:
        token, _ = service.borrow_coordinator()
        service.submit(
            connection_id="connection-a",
            arguments={"task": "Plan", "request_key": "first", "mode": "source_free"},
        )
        async with asyncio.timeout(2):
            await started.wait()
        close_task = asyncio.create_task(service.close())
        await asyncio.sleep(0)
        assert not close_task.done()
        with pytest.raises(RuntimeError):
            lease.borrow()
        with pytest.raises(RuntimeError):
            service.borrow_coordinator()
        token.require_owned()
        release.set()
        with pytest.raises(RuntimeError, match="unavailable"):
            await close_task
        assert provider.cancelled
        assert len(provider.requests) == 1
        token.require_owned()
        token.retire()
        await service.close()
        await service.start()
    finally:
        release.set()
        if close_task is not None:
            with suppress(RuntimeError):
                await close_task
        if token is not None:
            token.retire()
        await service.close()


def test_unadmitted_token_cannot_prove_ownership_or_retire_another_borrow(tmp_path):
    lease = CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow()
    try:
        for unadmitted in (CoordinatorBorrow(lease), copy(token)):
            with pytest.raises(RuntimeError):
                unadmitted.require_owned()
            with pytest.raises(RuntimeError):
                unadmitted.quarantine()
            unadmitted.retire()
        with pytest.raises(RuntimeError):
            lease.close()
        token.require_owned()
    finally:
        token.retire()
        lease.close()


def test_concurrent_borrow_and_close_have_one_admission_order(tmp_path):
    for index in range(20):
        lease = CoordinatorLease(tmp_path / f"owner-{index}.lock")
        ready = threading.Barrier(3, timeout=2)
        tokens, outcomes = [], []

        def borrow(owner, barrier, accepted, result):
            barrier.wait()
            try:
                accepted.append(owner.borrow())
            except RuntimeError:
                result.append("borrow-denied")

        def close(owner, barrier, result):
            barrier.wait()
            try:
                owner.close()
            except RuntimeError:
                result.append("close-pinned")
            else:
                result.append("closed")

        threads = [
            threading.Thread(target=borrow, args=(lease, ready, tokens, outcomes)),
            threading.Thread(target=close, args=(lease, ready, outcomes)),
        ]
        try:
            for thread in threads:
                thread.start()
            ready.wait()
            for thread in threads:
                thread.join(2)
                assert not thread.is_alive()
            if tokens:
                assert outcomes == ["close-pinned"]
                tokens[0].require_owned()
            else:
                assert sorted(outcomes) == ["borrow-denied", "closed"]
            with pytest.raises(RuntimeError):
                lease.borrow()
        finally:
            for thread in threads:
                thread.join(2)
            for token in tokens:
                token.retire()
            lease.close()


def test_wrong_process_identity_rejects_before_touching_inherited_mutex(
    tmp_path, monkeypatch
):
    lease = CoordinatorLease(tmp_path / "owner.lock")
    token = lease.borrow()
    pid = os.getpid()
    try:
        # This is a unit check of the PID guard, not a claim that copied Python
        # state coordinates processes. Fresh-process flock coverage is below.
        with lease._state_lock, monkeypatch.context() as guard:
            guard.setattr(os, "getpid", lambda: pid + 1)
            assert not lease.is_owned()
            for operation in (
                lease.require_owned,
                lease.begin_close,
                lease.borrow,
                lease.close,
                token.require_owned,
                token.require_source_usable,
                token.quarantine,
                token.retire,
            ):
                with pytest.raises(RuntimeError, match="unavailable"):
                    operation()
        token.require_source_usable()
    finally:
        token.retire()
        lease.close()


def test_fresh_process_cannot_replace_until_retirement_and_explicit_close(tmp_path):
    path = tmp_path / "owner.lock"
    lease = CoordinatorLease(path)
    token = lease.borrow()

    def fresh_process_owns():
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; "
                "from src.services.agent_runs.coordinator import CoordinatorLease\n"
                "try: lease = CoordinatorLease(Path(sys.argv[1]))\n"
                "except RuntimeError: print('unavailable')\n"
                "else:\n"
                "    token = lease.borrow(); token.require_source_usable()\n"
                "    token.retire(); lease.close(); print('owned')\n",
                str(path),
            ],
            text=True,
            capture_output=True,
            timeout=5,
            check=True,
        )
        return result.stdout.strip()

    try:
        with pytest.raises(RuntimeError):
            lease.close()
        assert fresh_process_owns() == "unavailable"
        token.retire()
        assert fresh_process_owns() == "unavailable"
        lease.close()
        assert fresh_process_owns() == "owned"
    finally:
        token.retire()
        lease.close()
