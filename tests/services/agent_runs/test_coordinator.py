"""A target has one explicit coordinator; opening storage is never recovery."""

import pytest

from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.conversation_runtime.fake_provider import FakeProviderClient


async def test_second_coordinator_cannot_take_over_a_live_store(tmp_path):
    path = tmp_path / "agent-runs.sqlite3"
    first = AgentRunService(
        store=AgentRunStore(
            path, account_id="account-a", execution_target_id="target-a", create=True
        ),
        provider_factory=lambda _: FakeProviderClient(script=[]),
    )
    second = AgentRunService(
        store=AgentRunStore(
            path, account_id="account-a", execution_target_id="target-a"
        ),
        provider_factory=lambda _: FakeProviderClient(script=[]),
    )
    await first.start()
    try:
        with pytest.raises(RuntimeError, match="coordinator"):
            await second.start()
    finally:
        await second.close()
        await first.close()
    await second.start()
    await second.close()


async def test_completion_storage_failure_cleans_owned_runtime_and_denies_new_work(
    tmp_path,
):
    import asyncio
    import sqlite3
    from contextlib import suppress

    from src.services.conversation_runtime.models import ProviderCapabilities
    from tests.services.conversation_acceptance import text_turn

    path = tmp_path / "agent-runs.sqlite3"
    store = AgentRunStore(
        path, account_id="account-a", execution_target_id="target-a", create=True
    )
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TRIGGER fail_terminal BEFORE UPDATE OF state ON agent_runs
            WHEN NEW.state IN ('completed', 'failed')
            BEGIN SELECT RAISE(ABORT, 'SYNTHETIC_STORAGE_FAILURE'); END""")
    provider = FakeProviderClient(
        script=[text_turn("Private result")],
        capabilities=ProviderCapabilities(
            provider="fake", model="fake", supports_cancellation=True
        ),
    )
    service = AgentRunService(store=store, provider_factory=lambda _: provider)
    await service.start()
    accepted = service.submit(
        connection_id="connection-a",
        arguments={
            "task": "Plan",
            "mode": "source_free",
            "request_key": "first-key",
        },
    )
    try:
        async with asyncio.timeout(2):
            while not provider.cancelled:
                await asyncio.sleep(0.01)
        with pytest.raises(RuntimeError, match="unavailable"):
            service.submit(
                connection_id="connection-a",
                arguments={
                    "task": "Another",
                    "mode": "source_free",
                    "request_key": "second-key",
                },
            )
        assert (
            store.read(
                connection_id="connection-a", run_reference=accepted["run_reference"]
            ).state
            == "running"
        )
        assert len(provider.requests) == 1
    finally:
        with suppress(Exception):
            await service.close()


async def test_lease_loss_fences_recovery_and_stops_new_model_dispatch(tmp_path):
    import asyncio
    import os

    from tests.services.conversation_acceptance import text_turn, tool_call_turn

    class PausedProvider(FakeProviderClient):
        def __init__(self):
            super().__init__(
                script=[
                    tool_call_turn("one", "get_schema", {}),
                    text_turn("STALE_COMPLETION_CANARY"),
                ]
            )
            self.opened = asyncio.Event()
            self.release = asyncio.Event()

        def stream_turn(self, **kwargs):
            inner = super().stream_turn(**kwargs)
            first = len(self.requests) == 1

            async def events():
                if first:
                    self.opened.set()
                    await self.release.wait()
                async for event in inner:
                    yield event

            return events()

    path = tmp_path / "agent-runs.sqlite3"
    store = AgentRunStore(
        path, account_id="account-a", execution_target_id="target-a", create=True
    )
    provider = PausedProvider()
    first = AgentRunService(store=store, provider_factory=lambda _: provider)
    recovered_model_calls = []

    def no_replay(reference):
        recovered_model_calls.append(reference)
        raise AssertionError("An interrupted charged turn must not replay")

    second = AgentRunService(
        store=AgentRunStore(
            path, account_id="account-a", execution_target_id="target-a"
        ),
        provider_factory=no_replay,
    )
    await first.start()
    accepted = first.submit(
        connection_id="connection-a",
        arguments={
            "task": "Plan",
            "mode": "source_free",
            "request_key": "fenced-run",
        },
    )
    await asyncio.wait_for(provider.opened.wait(), 2)
    try:
        lock_path = path.with_suffix(".coordinator.lock")
        lock_path.rename(tmp_path / "retired-coordinator.lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        await second.start()
        with pytest.raises(RuntimeError, match="unavailable"):
            first.submit(
                connection_id="connection-a",
                arguments={
                    "task": "Another",
                    "mode": "source_free",
                    "request_key": "stale-worker-key",
                },
            )
        provider.release.set()
        await asyncio.sleep(0.05)
        result = second.read(
            connection_id="connection-a", run_reference=accepted["run_reference"]
        )
        assert result["state"] == "failed"
        assert result["outcome"] == "interrupted"
        assert result["expires_at"] == accepted["expires_at"]
        assert len(provider.requests) == 1
        assert recovered_model_calls == []
        assert "STALE_COMPLETION_CANARY" not in repr(result)
    finally:
        provider.release.set()
        await first.close()
        await second.close()


async def test_model_deadline_ends_owned_work_without_replaying_an_accepted_key(
    tmp_path,
):
    import asyncio

    from src.services.conversation_runtime.models import (
        ProviderStreamEvent,
        ProviderStreamEventType,
    )

    class BlockedProvider(FakeProviderClient):
        def __init__(self):
            super().__init__(script=[])
            self.closed = asyncio.Event()

        def stream_turn(self, **kwargs):
            self.requests.append(kwargs)

            async def events():
                try:
                    await asyncio.Event().wait()
                    yield ProviderStreamEvent(
                        type=ProviderStreamEventType.STREAM_COMPLETE
                    )
                finally:
                    self.closed.set()

            return events()

    provider = BlockedProvider()
    store = AgentRunStore(
        tmp_path / "agent-runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    service = AgentRunService(
        store=store, provider_factory=lambda _: provider, model_timeout_seconds=0.1
    )
    await service.start()
    arguments = {"task": "Plan", "mode": "source_free", "request_key": "deadline-run"}
    try:
        accepted = service.submit(connection_id="connection-a", arguments=arguments)
        async with asyncio.timeout(2):
            while True:
                result = service.read(
                    connection_id="connection-a",
                    run_reference=accepted["run_reference"],
                )
                if result["state"] == "failed":
                    break
                await asyncio.sleep(0.01)
        assert result["outcome"] == "model_timeout"
        assert provider.closed.is_set()
        retry = service.submit(connection_id="connection-a", arguments=arguments)
        assert retry == result
        assert len(provider.requests) == 1
    finally:
        await service.close()


async def test_stale_generation_cannot_accept_or_publish_after_replacement(tmp_path):
    from src.services.agent_runs.coordinator import CoordinatorLease

    store = AgentRunStore(
        tmp_path / "agent-runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    lease = CoordinatorLease(store.path.with_suffix(".coordinator.lock"))
    try:
        first_generation = store.begin_coordinator(lease=lease)
        second_generation = store.begin_coordinator(lease=lease)
        with pytest.raises(RuntimeError, match="unavailable"):
            store.accept(
                connection_id="connection-a",
                task="Stale task",
                mode="source_free",
                request_key="stale-accept",
                generation=first_generation,
            )
        assert store.claim_next(generation=second_generation) is None
    finally:
        lease.close()


async def test_partial_text_then_transient_authority_failure_is_not_completion(
    tmp_path,
):
    import asyncio
    import sqlite3

    from tests.services.conversation_acceptance import text_turn, tool_call_turn

    class FailOneReadStore(AgentRunStore):
        fail_next_check = False
        failure_seen = False

        def is_active(self, run):
            if self.fail_next_check:
                self.fail_next_check = False
                self.failure_seen = True
                raise sqlite3.OperationalError("SYNTHETIC_TRANSIENT_READ_FAILURE")
            return super().is_active(run)

    store = FailOneReadStore(
        tmp_path / "agent-runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )

    class PartialProvider(FakeProviderClient):
        def stream_turn(self, **kwargs):
            inner = super().stream_turn(**kwargs)

            async def events():
                async for event in inner:
                    yield event
                # The single-event runtime queue ensures the first block has
                # been consumed before this final batch boundary is reached.
                store.fail_next_check = True

            return events()

    provider = PartialProvider(
        script=[
            [
                text_turn("Partial planning text")[0],
                *tool_call_turn("one", "get_schema", {}),
            ],
            text_turn("UNWANTED_FINAL_CANARY"),
        ]
    )
    service = AgentRunService(store=store, provider_factory=lambda _: provider)
    await service.start()
    try:
        accepted = service.submit(
            connection_id="connection-a",
            arguments={
                "task": "Plan",
                "mode": "source_free",
                "request_key": "partial-result",
            },
        )
        async with asyncio.timeout(2):
            while True:
                result = service.read(
                    connection_id="connection-a",
                    run_reference=accepted["run_reference"],
                )
                if result["state"] not in {"queued", "running"}:
                    break
                await asyncio.sleep(0.01)
        assert store.failure_seen
        assert result["state"] == "failed"
        assert result["outcome"] == "interrupted"
        assert len(provider.requests) == 1
    finally:
        await service.close()


async def test_provider_instance_cannot_be_shared_across_accepted_conversations(
    tmp_path,
):
    import asyncio

    from tests.services.conversation_acceptance import text_turn

    provider = FakeProviderClient(
        script=[
            text_turn("First private conversation"),
            text_turn("LEAKED_SECOND_CONVERSATION"),
        ]
    )
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    service = AgentRunService(store=store, provider_factory=lambda _: provider)
    await service.start()
    try:
        first = service.submit(
            connection_id="connection-a",
            arguments={
                "task": "First",
                "mode": "source_free",
                "request_key": "first-request",
            },
        )
        async with asyncio.timeout(2):
            while service.read(
                connection_id="connection-a", run_reference=first["run_reference"]
            )["state"] in {"queued", "running"}:
                await asyncio.sleep(0.01)
        second = service.submit(
            connection_id="connection-b",
            arguments={
                "task": "Second",
                "mode": "source_free",
                "request_key": "second-request",
            },
        )
        async with asyncio.timeout(2):
            while True:
                result = service.read(
                    connection_id="connection-b", run_reference=second["run_reference"]
                )
                if result["state"] not in {"queued", "running"}:
                    break
                await asyncio.sleep(0.01)
        assert (
            service.read(
                connection_id="connection-a", run_reference=first["run_reference"]
            )["state"]
            == "completed"
        )
        assert result["state"] == "failed"
        assert result["outcome"] == "provider_failed"
        assert len(provider.requests) == 1
    finally:
        await service.close()


async def test_error_stream_closes_in_owned_context_before_next_conversation(tmp_path):
    import asyncio

    from src.services.agent_session_manager import current_conversation_turn
    from src.services.conversation_runtime.models import (
        ProviderStreamEvent,
        ProviderStreamEventType,
    )
    from tests.services.conversation_acceptance import text_turn

    contexts = []

    def factory(_):
        contexts.append(current_conversation_turn.get())
        script = (
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.PROVIDER_ERROR,
                    error_message="PRIVATE_FAILURE_CANARY",
                )
            ]
            if len(contexts) == 1
            else text_turn("Safe next turn")
        )
        return FakeProviderClient(script=[script])

    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    service = AgentRunService(store=store, provider_factory=factory)
    await service.start()
    try:
        for index, expected in enumerate(("failed", "completed")):
            accepted = service.submit(
                connection_id="connection-a",
                arguments={
                    "task": "Plan",
                    "mode": "source_free",
                    "request_key": f"context-{index}",
                },
            )
            async with asyncio.timeout(2):
                while True:
                    result = service.read(
                        connection_id="connection-a",
                        run_reference=accepted["run_reference"],
                    )
                    if result["state"] not in {"queued", "running"}:
                        break
                    await asyncio.sleep(0.01)
            assert result["state"] == expected
        assert contexts == [None, None]
    finally:
        await service.close()


async def test_truncated_provider_stream_cannot_publish_completion(tmp_path):
    import asyncio

    from tests.services.conversation_acceptance import text_turn

    # A complete authored block is not the provider's terminal stream event.
    provider = FakeProviderClient(script=[[text_turn("Partial private text")[0]]])
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    service = AgentRunService(store=store, provider_factory=lambda _: provider)
    await service.start()
    try:
        accepted = service.submit(
            connection_id="connection-a",
            arguments={
                "task": "Plan",
                "mode": "source_free",
                "request_key": "truncated-key",
            },
        )
        async with asyncio.timeout(2):
            while True:
                result = service.read(
                    connection_id="connection-a",
                    run_reference=accepted["run_reference"],
                )
                if result["state"] not in {"queued", "running"}:
                    break
                await asyncio.sleep(0.01)
        assert result["state"] == "failed"
        assert result["outcome"] == "interrupted"
        assert len(provider.requests) == 1
    finally:
        await service.close()
