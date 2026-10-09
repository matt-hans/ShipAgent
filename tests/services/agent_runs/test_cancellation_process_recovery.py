"""Process death after committed cancellation cannot replay a model request."""

import asyncio
import json
import subprocess
import sys

import pytest

from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore

CANCEL_THEN_CRASH = r"""
import asyncio, json, os, sys
from pathlib import Path
from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from tests.services.conversation_acceptance import text_turn
root, phase = Path(sys.argv[1]), sys.argv[2]
class PausedProvider(FakeProviderClient):
    def __init__(self):
        super().__init__(script=[text_turn("PRIVATE_LATE_RESULT")])
        self.opened = asyncio.Event()
    def stream_turn(self, **kwargs):
        inner = super().stream_turn(**kwargs)
        with (root / "dispatches.txt").open("a") as file:
            file.write("dispatch\n")
            file.flush()
            os.fsync(file.fileno())
        async def events():
            self.opened.set()
            await asyncio.Event().wait()
            async for event in inner:
                yield event
        return events()
async def main():
    store = AgentRunStore(root / "runs.sqlite3", account_id="account-a", execution_target_id="target-a", create=True)
    provider = PausedProvider()
    service = AgentRunService(store=store, provider_factory=lambda _: provider)
    await service.start()
    accepted = service.submit(connection_id="connection-a", arguments={"task":"Plan", "mode":"source_free", "request_key":"crashed-cancel-key"})
    if phase == "running":
        await provider.opened.wait()
    cancelled = service.cancel(connection_id="connection-a", run_reference=accepted["run_reference"])
    with (root / "cancelled.json").open("w") as file:
        json.dump(cancelled, file)
        file.flush()
        os.fsync(file.fileno())
    os._exit(43)
asyncio.run(main())
"""


@pytest.mark.parametrize("phase", ["queued", "running"])
async def test_process_death_preserves_cancellation_and_request_identity(
    tmp_path, phase
):
    child = subprocess.run(
        [sys.executable, "-c", CANCEL_THEN_CRASH, str(tmp_path), phase],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert child.returncode == 43, child.stderr
    cancelled = json.loads((tmp_path / "cancelled.json").read_text())
    calls = []

    def no_replay(reference):
        calls.append(reference)
        raise AssertionError("Cancellation must not replay model work")

    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
    )
    service = AgentRunService(store=store, provider_factory=no_replay)
    await service.start()
    try:
        assert (
            service.read(
                connection_id="connection-a", run_reference=cancelled["run_reference"]
            )
            == cancelled
        )
        assert (
            service.submit(
                connection_id="connection-a",
                arguments={
                    "task": "Plan",
                    "mode": "source_free",
                    "request_key": "crashed-cancel-key",
                },
            )
            == cancelled
        )
        assert (
            service.cancel(
                connection_id="connection-a", run_reference=cancelled["run_reference"]
            )
            == cancelled
        )
        await asyncio.sleep(0)
        assert calls == []
        dispatches = tmp_path / "dispatches.txt"
        assert (
            dispatches.read_text().count("dispatch") if dispatches.exists() else 0
        ) == (1 if phase == "running" else 0)
    finally:
        await service.close()
