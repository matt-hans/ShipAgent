"""A failed durable publication fences admission before async cleanup starts."""

import asyncio
import sqlite3
from contextlib import suppress

import pytest

from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.conversation_runtime.models import ProviderCapabilities
from tests.services.conversation_acceptance import text_turn


async def test_failed_terminal_write_fences_admission_while_cleanup_is_pending(
    tmp_path,
):
    class FailingStore(AgentRunStore):
        def finish(self, *args, **kwargs):
            raise sqlite3.OperationalError("PRIVATE_STORAGE_FAILURE")

    class PendingCleanup(FakeProviderClient):
        def __init__(self):
            super().__init__(
                script=[text_turn("Private planning result")],
                capabilities=ProviderCapabilities(
                    provider="fake", model="fake", supports_cancellation=True
                ),
            )
            self.cleaning = asyncio.Event()
            self.release = asyncio.Event()

        async def cancel(self):
            self.cleaning.set()
            await self.release.wait()
            await super().cancel()

    store = FailingStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    provider = PendingCleanup()
    service = AgentRunService(store=store, provider_factory=lambda _: provider)
    await service.start()
    accepted = service.submit(
        connection_id="connection-a",
        arguments={"task": "Plan", "mode": "source_free", "request_key": "first-key"},
    )
    try:
        await asyncio.wait_for(provider.cleaning.wait(), 1)
        # Cleanup deliberately remains blocked: no scheduler sleep can make the
        # worker-done callback establish the required admission fence.
        with pytest.raises(RuntimeError, match="unavailable"):
            service.submit(
                connection_id="connection-a",
                arguments={
                    "task": "New",
                    "mode": "source_free",
                    "request_key": "second-key",
                },
            )
        with pytest.raises(RuntimeError, match="unavailable"):
            service.read(
                connection_id="connection-a", run_reference=accepted["run_reference"]
            )
        assert (
            store.read(
                connection_id="connection-a", run_reference=accepted["run_reference"]
            ).state
            == "running"
        )
        assert len(provider.requests) == 1
    finally:
        provider.release.set()
        with suppress(Exception):
            await service.close()
