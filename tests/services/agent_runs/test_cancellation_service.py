"""Cancellation commits before returning and only stops its owned model turn."""

import asyncio

from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.conversation_runtime.models import ProviderCapabilities
from tests.services.conversation_acceptance import text_turn


class PausedProvider(FakeProviderClient):
    def __init__(self):
        super().__init__(
            script=[text_turn("STALE_PRIVATE_OUTPUT")],
            capabilities=ProviderCapabilities(
                provider="fake", model="fake", supports_cancellation=True
            ),
        )
        self.opened = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = asyncio.Event()

    def stream_turn(self, **kwargs):
        inner = super().stream_turn(**kwargs)

        async def events():
            try:
                self.opened.set()
                await self.release.wait()
                async for event in inner:
                    yield event
            finally:
                self.closed.set()

        return events()


class StubbornCloseProvider(PausedProvider):
    def __init__(self):
        super().__init__()
        self.cleanup_started = asyncio.Event()
        self.cleanup_release = asyncio.Event()

    def stream_turn(self, **kwargs):
        inner = super().stream_turn(**kwargs)

        async def events():
            try:
                async for event in inner:
                    yield event
            finally:
                self.cleanup_started.set()
                while not self.cleanup_release.is_set():
                    try:
                        await self.cleanup_release.wait()
                    except asyncio.CancelledError:
                        pass

        return events()


def new_store(tmp_path):
    return AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )


def submit(service, key):
    return service.submit(
        connection_id="connection-a",
        arguments={"task": "Plan safely", "mode": "source_free", "request_key": key},
    )


def read(service, result):
    return service.read(
        connection_id="connection-a", run_reference=result["run_reference"]
    )


async def terminal(service, result):
    async with asyncio.timeout(2):
        while True:
            latest = read(service, result)
            if latest["state"] not in {"queued", "running"}:
                return latest
            await asyncio.sleep(0.005)


async def test_running_cancel_closes_its_model_without_cancelling_next_run(tmp_path):
    first = PausedProvider()
    second = FakeProviderClient(script=[text_turn("Safe next run")])
    providers = iter([first, second])
    service = AgentRunService(
        store=new_store(tmp_path), provider_factory=lambda _: next(providers)
    )
    await service.start()
    try:
        accepted = submit(service, "cancel-first")
        await asyncio.wait_for(first.opened.wait(), 2)
        cancelled = service.cancel(
            connection_id="connection-a", run_reference=accepted["run_reference"]
        )
        assert cancelled["state"] == "cancelled"
        assert cancelled["outcome"] == "cancelled"
        assert cancelled["expires_at"] == accepted["expires_at"]
        assert cancelled["poll_after_seconds"] == 0
        await asyncio.wait_for(first.closed.wait(), 2)
        next_run = submit(service, "next-request")
        assert (await terminal(service, next_run))["state"] == "completed"
        assert read(service, accepted) == cancelled
        assert submit(service, "cancel-first") == cancelled
        assert first.cancelled
        assert len(first.requests) == len(second.requests) == 1
        assert not second.cancelled
        assert "STALE_PRIVATE_OUTPUT" not in repr(cancelled)
    finally:
        first.release.set()
        await service.close()


async def test_noncooperative_cleanup_is_bounded_quarantined_and_keeps_lease(tmp_path):
    import pytest

    provider = StubbornCloseProvider()
    store = new_store(tmp_path)
    service = AgentRunService(store=store, provider_factory=lambda _: provider)
    replacement = AgentRunService(
        store=store,
        provider_factory=lambda _: FakeProviderClient(script=[text_turn("Safe")]),
    )
    await service.start()
    close_task = None
    try:
        accepted = submit(service, "stubborn-close")
        await asyncio.wait_for(provider.opened.wait(), 2)
        cancelled = service.cancel(
            connection_id="connection-a", run_reference=accepted["run_reference"]
        )
        await asyncio.wait_for(provider.cleanup_started.wait(), 2)
        close_task = asyncio.create_task(service.close())
        done, _ = await asyncio.wait({close_task}, timeout=2.5)
        assert close_task in done, "close() must not await hostile cleanup indefinitely"
        with pytest.raises(RuntimeError, match="unavailable"):
            await close_task
        assert read(service, accepted) == cancelled
        with pytest.raises(RuntimeError, match="unavailable"):
            submit(service, "blocked-new-run")
        with pytest.raises(RuntimeError, match="coordinator"):
            await replacement.start()
        assert len(provider.requests) == 1
    finally:
        # The test owns the scripted provider release. Never leave a deliberately
        # noncooperative task for pytest or the process supervisor to kill.
        provider.release.set()
        provider.cleanup_release.set()
        if close_task is not None:
            await asyncio.gather(close_task, return_exceptions=True)
        await service.close()
        await replacement.close()

    await replacement.start()
    try:
        assert read(replacement, accepted) == cancelled
    finally:
        await replacement.close()


async def test_terminal_provider_cleanup_times_out_without_starting_queued_work(
    tmp_path,
):
    import pytest

    class StubbornCancelProvider(FakeProviderClient):
        def __init__(self):
            super().__init__(
                script=[text_turn("Completed private result")],
                capabilities=ProviderCapabilities(
                    provider="fake", model="fake", supports_cancellation=True
                ),
            )
            self.cleanup_started = asyncio.Event()
            self.cleanup_release = asyncio.Event()

        async def cancel(self):
            self.cleanup_started.set()
            while not self.cleanup_release.is_set():
                try:
                    await self.cleanup_release.wait()
                except asyncio.CancelledError:
                    pass

    first = StubbornCancelProvider()
    second = PausedProvider()
    providers = iter([first, second])
    store = new_store(tmp_path)
    service = AgentRunService(store=store, provider_factory=lambda _: next(providers))
    replacement = AgentRunService(store=store, provider_factory=lambda _: second)
    await service.start()
    try:
        accepted = submit(service, "completed-run")
        await asyncio.wait_for(first.cleanup_started.wait(), 2)
        completed = read(service, accepted)
        assert completed["state"] == "completed"
        queued = submit(service, "queued-behind-cleanup")
        await asyncio.sleep(1.2)
        with pytest.raises(RuntimeError, match="unavailable"):
            submit(service, "denied-after-cleanup-deadline")
        assert second.requests == []
        with pytest.raises(RuntimeError, match="unavailable"):
            read(service, queued)
        assert (
            service.cancel(
                connection_id="connection-a", run_reference=accepted["run_reference"]
            )
            == completed
        )
        with pytest.raises(RuntimeError, match="unavailable"):
            await service.close()
        with pytest.raises(RuntimeError, match="coordinator"):
            await replacement.start()
    finally:
        first.cleanup_release.set()
        second.release.set()
        await service.close()
        await replacement.close()


async def test_model_timeout_quarantines_noncooperative_stream_without_user_cancel(
    tmp_path,
):
    import pytest

    provider = StubbornCloseProvider()
    service = AgentRunService(
        store=new_store(tmp_path),
        provider_factory=lambda _: provider,
        model_timeout_seconds=0.05,
    )
    await service.start()
    try:
        accepted = submit(service, "noncooperative-timeout")
        await asyncio.wait_for(provider.cleanup_started.wait(), 2)
        await asyncio.sleep(1.2)
        with pytest.raises(RuntimeError, match="unavailable"):
            submit(service, "denied-after-model-deadline")
        result = read(service, accepted)
        assert result["state"] == "failed"
        assert result["outcome"] == "model_timeout"
        assert len(provider.requests) == 1
    finally:
        provider.release.set()
        provider.cleanup_release.set()
        await service.close()


async def test_caller_disconnect_after_durable_cancel_does_not_own_cleanup(tmp_path):
    provider = PausedProvider()
    service = AgentRunService(
        store=new_store(tmp_path), provider_factory=lambda _: provider
    )
    committed = asyncio.Event()
    await service.start()
    try:
        accepted = submit(service, "disconnect-run")
        await asyncio.wait_for(provider.opened.wait(), 2)

        async def request():
            service.cancel(
                connection_id="connection-a", run_reference=accepted["run_reference"]
            )
            committed.set()
            # Simulate a disconnected transport after durable acceptance but
            # before it can deliver the response to its client.
            await asyncio.Event().wait()

        caller = asyncio.create_task(request())
        await asyncio.wait_for(committed.wait(), 2)
        caller.cancel()
        await asyncio.gather(caller, return_exceptions=True)
        await asyncio.wait_for(provider.closed.wait(), 2)
        assert read(service, accepted)["state"] == "cancelled"
        assert service.cancel(
            connection_id="connection-a", run_reference=accepted["run_reference"]
        ) == read(service, accepted)
        assert len(provider.requests) == 1
    finally:
        provider.release.set()
        await service.close()


async def test_delayed_duplicate_cancel_cannot_interrupt_a_later_active_run(tmp_path):
    class DelayedCancelProvider(PausedProvider):
        def __init__(self):
            super().__init__()
            self.cleanup_started = asyncio.Event()
            self.cleanup_release = asyncio.Event()

        async def cancel(self):
            self.cleanup_started.set()
            await self.cleanup_release.wait()
            await super().cancel()

    first, second = DelayedCancelProvider(), PausedProvider()
    providers = iter([first, second])
    service = AgentRunService(
        store=new_store(tmp_path), provider_factory=lambda _: next(providers)
    )
    await service.start()
    try:
        original = submit(service, "original-run")
        await asyncio.wait_for(first.opened.wait(), 2)
        cancelled = service.cancel(
            connection_id="connection-a", run_reference=original["run_reference"]
        )
        await asyncio.wait_for(first.cleanup_started.wait(), 2)
        later = submit(service, "later-run")
        await asyncio.sleep(0)
        assert not second.opened.is_set()
        first.cleanup_release.set()
        await asyncio.wait_for(second.opened.wait(), 2)
        assert first.closed.is_set()
        # This retry arrives only after the coordinator has moved to another
        # run. It must never resolve the newer active task for old cleanup.
        assert (
            service.cancel(
                connection_id="connection-a", run_reference=original["run_reference"]
            )
            == cancelled
        )
        await asyncio.sleep(0)
        assert not second.cancelled
        assert not second.closed.is_set()
        assert read(service, later)["state"] == "running"
        second.release.set()
        assert (await terminal(service, later))["state"] == "completed"
        assert read(service, original) == cancelled
    finally:
        first.cleanup_release.set()
        first.release.set()
        second.release.set()
        await service.close()


async def test_provider_cancel_failure_is_bounded_and_does_not_leak_exception(
    tmp_path, caplog
):
    class FailedCancelProvider(PausedProvider):
        async def cancel(self):
            raise RuntimeError("PRIVATE_CANCEL_FAILURE_CANARY")

    first = FailedCancelProvider()
    second = FakeProviderClient(script=[text_turn("Safe next run")])
    providers = iter([first, second])
    service = AgentRunService(
        store=new_store(tmp_path), provider_factory=lambda _: next(providers)
    )
    await service.start()
    try:
        accepted = submit(service, "cancel-error-run")
        await asyncio.wait_for(first.opened.wait(), 2)
        cancelled = service.cancel(
            connection_id="connection-a", run_reference=accepted["run_reference"]
        )
        await asyncio.wait_for(first.closed.wait(), 2)
        assert cancelled["state"] == "cancelled"
        assert (await terminal(service, submit(service, "next-after-error")))[
            "state"
        ] == "completed"
        assert "PRIVATE_CANCEL_FAILURE_CANARY" not in repr(cancelled) + caplog.text
    finally:
        first.release.set()
        await service.close()


async def test_failed_cancel_commit_does_not_signal_or_cancel_the_owned_turn(tmp_path):
    import sqlite3

    import pytest

    provider = PausedProvider()
    store = new_store(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute("""CREATE TRIGGER fail_cancel BEFORE UPDATE OF state ON agent_runs
            WHEN NEW.state = 'cancelled'
            BEGIN SELECT RAISE(ABORT, 'PRIVATE_CANCEL_STORE_FAILURE'); END""")
    service = AgentRunService(store=store, provider_factory=lambda _: provider)
    await service.start()
    try:
        accepted = submit(service, "commit-failure")
        await asyncio.wait_for(provider.opened.wait(), 2)
        with pytest.raises(sqlite3.DatabaseError):
            service.cancel(
                connection_id="connection-a", run_reference=accepted["run_reference"]
            )
        await asyncio.sleep(0)
        assert not provider.closed.is_set()
        assert not provider.cancelled
        assert read(service, accepted)["state"] == "running"
        provider.release.set()
        assert (await terminal(service, accepted))["state"] == "completed"
        assert len(provider.requests) == 1
    finally:
        provider.release.set()
        await service.close()


async def test_stream_close_failure_stays_bounded_and_private(tmp_path, caplog):
    class FailedStreamCloseProvider(PausedProvider):
        def stream_turn(self, **kwargs):
            inner = super().stream_turn(**kwargs)

            async def events():
                try:
                    async for event in inner:
                        yield event
                finally:
                    raise RuntimeError("PRIVATE_STREAM_CLOSE_CANARY")

            return events()

    provider = FailedStreamCloseProvider()
    service = AgentRunService(
        store=new_store(tmp_path), provider_factory=lambda _: provider
    )
    await service.start()
    try:
        accepted = submit(service, "stream-close-failure")
        await asyncio.wait_for(provider.opened.wait(), 2)
        cancelled = service.cancel(
            connection_id="connection-a", run_reference=accepted["run_reference"]
        )
        await asyncio.wait_for(provider.closed.wait(), 2)
        await service.close()
        assert read(service, accepted) == cancelled
        assert "PRIVATE_STREAM_CLOSE_CANARY" not in repr(cancelled) + caplog.text
    finally:
        provider.release.set()
        await service.close()


async def test_late_failed_worker_observer_cannot_poison_restarted_service(tmp_path):
    import sqlite3

    store = new_store(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute("""CREATE TRIGGER fail_finish BEFORE UPDATE OF state ON agent_runs
            WHEN NEW.state IN ('completed', 'failed')
            BEGIN SELECT RAISE(ABORT, 'SYNTHETIC_FINISH_FAILURE'); END""")
    providers = iter(
        [
            FakeProviderClient(script=[text_turn("First result")]),
            FakeProviderClient(script=[text_turn("New owner result")]),
        ]
    )
    service = AgentRunService(store=store, provider_factory=lambda _: next(providers))
    await service.start()
    try:
        original = submit(service, "failing-worker")
        async with asyncio.timeout(2):
            while True:
                try:
                    read(service, original)
                except RuntimeError:
                    break
                # Observe worker failure as soon as it is public, before queued
                # done callbacks necessarily run. Reopening must be safe here.
                await asyncio.sleep(0)
        with sqlite3.connect(store.path) as db:
            db.execute("DROP TRIGGER fail_finish")
        await service.close()
        await service.start()
        later = submit(service, "restarted-worker")
        assert (await terminal(service, later))["state"] == "completed"
        assert read(service, original)["outcome"] == "interrupted"
    finally:
        await service.close()
