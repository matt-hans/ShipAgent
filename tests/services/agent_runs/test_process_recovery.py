"""Real process death preserves acceptance and never replays charged work.

This checks process-crash recovery only, not power loss or restored old backups.
"""

import asyncio
import json
import subprocess
import sys

import pytest

from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from tests.services.conversation_acceptance import text_turn

CRASHING_TARGET = r"""
import asyncio, json, os, sys
from pathlib import Path
from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from tests.services.conversation_acceptance import text_turn
root, phase = Path(sys.argv[1]), sys.argv[2]
class CrashProvider(FakeProviderClient):
    def stream_turn(self, **kwargs):
        with (root / "model-dispatches.txt").open("a") as file:
            file.write("dispatch\n")
            file.flush()
            os.fsync(file.fileno())
        if phase == "running":
            os._exit(42)
        return super().stream_turn(**kwargs)
async def main():
    store = AgentRunStore(root / "runs.sqlite3", account_id="account-a", execution_target_id="target-a", create=True)
    service = AgentRunService(store=store, provider_factory=lambda _: CrashProvider(script=[text_turn("PRIVATE_CHILD_RESULT")]))
    await service.start()
    accepted = service.submit(connection_id="connection-a", arguments={"task":"Plan", "mode":"source_free", "request_key":"crashed-key"})
    (root / "accepted.json").write_text(json.dumps(accepted))
    if phase == "queued":
        os._exit(42)
    while service.read(connection_id="connection-a", run_reference=accepted["run_reference"])["state"] != "completed":
        await asyncio.sleep(0.01)
    os._exit(42)
asyncio.run(main())
"""


@pytest.mark.parametrize("phase", ["queued", "running", "completed"])
async def test_real_process_death_recovers_original_identity_without_charged_replay(
    tmp_path, phase
):
    child = subprocess.run(
        [sys.executable, "-c", CRASHING_TARGET, str(tmp_path), phase],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert child.returncode == 42, child.stderr
    original = json.loads((tmp_path / "accepted.json").read_text())
    provider = FakeProviderClient(script=[text_turn("PRIVATE_RECOVERY_RESULT")])
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
    )
    service = AgentRunService(store=store, provider_factory=lambda _: provider)
    await service.start()
    try:
        retry = service.submit(
            connection_id="connection-a",
            arguments={
                "task": "Plan",
                "mode": "source_free",
                "request_key": "crashed-key",
            },
        )
        assert retry["run_reference"] == original["run_reference"]
        assert retry["conversation_reference"] == original["conversation_reference"]
        assert retry["expires_at"] == original["expires_at"]
        async with asyncio.timeout(2):
            while True:
                result = service.read(
                    connection_id="connection-a",
                    run_reference=original["run_reference"],
                )
                if result["state"] not in {"queued", "running"}:
                    break
                await asyncio.sleep(0.01)
        if phase == "running":
            assert result["state"] == "failed"
            assert result["outcome"] == "interrupted"
        else:
            assert result["state"] == "completed"
        assert len(provider.requests) == (1 if phase == "queued" else 0)
        dispatches = tmp_path / "model-dispatches.txt"
        assert (
            dispatches.read_text().count("dispatch") if dispatches.exists() else 0
        ) == (0 if phase == "queued" else 1)
        assert "PRIVATE" not in repr(result)
    finally:
        await service.close()
