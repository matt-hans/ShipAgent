"""Process crashes preserve each accepted turn and never replay dispatched work."""

import json
import subprocess
import sys

import pytest

from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from tests.services.agent_runs.test_continuation import terminal
from tests.services.conversation_acceptance import text_turn

CHILD = r"""
import asyncio, json, os, sys
from pathlib import Path
from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from tests.services.conversation_acceptance import text_turn
root, phase = Path(sys.argv[1]), sys.argv[2]
providers = []
class Provider(FakeProviderClient):
    def stream_turn(self, **kwargs):
        with (root / "dispatches.txt").open("a") as handle:
            handle.write("dispatch\n")
            handle.flush()
            os.fsync(handle.fileno())
        if len(providers) == 2 and phase == "running":
            os._exit(42)
        return super().stream_turn(**kwargs)
def factory(_):
    text = '{"clarification_code":"package_scope"}' if not providers else 'PRIVATE_FINAL_PLAN'
    provider = Provider(script=[text_turn(text)])
    providers.append(provider)
    return provider
async def main():
    store = AgentRunStore(root / "runs.sqlite3", account_id="account-a", execution_target_id="target-a", create=True)
    service = AgentRunService(store=store, provider_factory=factory, connection_epoch=lambda _: "link-a")
    await service.start()
    first = service.submit(connection_id="connection-a", arguments={"task":"Plan", "mode":"source_free", "request_key":"first-key"})
    while service.read(connection_id="connection-a", run_reference=first["run_reference"])["state"] != "waiting_for_input":
        await asyncio.sleep(0.005)
    arguments = {"conversation_reference":first["conversation_reference"], "run_reference":first["run_reference"], "expected_revision":1, "task":"One package", "request_key":"reply-key"}
    second = service.continue_turn(connection_id="connection-a", arguments=arguments)
    (root / "accepted.json").write_text(json.dumps({"first":first, "second":second, "arguments":arguments}))
    if phase == "queued":
        os._exit(42)
    while service.read(connection_id="connection-a", run_reference=second["run_reference"])["state"] != "completed":
        await asyncio.sleep(0.005)
    os._exit(42)
asyncio.run(main())
"""


@pytest.mark.parametrize("phase", ["queued", "running", "completed"])
async def test_accepted_continuation_recovers_without_replaying_dispatch(
    tmp_path, phase
):
    child = subprocess.run(
        [sys.executable, "-c", CHILD, str(tmp_path), phase],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert child.returncode == 42, child.stderr
    saved = json.loads((tmp_path / "accepted.json").read_text())
    provider = FakeProviderClient(script=[text_turn("PRIVATE_RECOVERY_PLAN")])
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
    )
    service = AgentRunService(
        store=store,
        provider_factory=lambda _: provider,
        connection_epoch=lambda _: "link-a",
    )
    await service.start()
    try:
        retry = service.continue_turn(
            connection_id="connection-a", arguments=saved["arguments"]
        )
        assert retry["run_reference"] == saved["second"]["run_reference"]
        assert retry["revision"] == 2
        assert retry["expires_at"] == saved["first"]["expires_at"]
        result = await terminal(service, retry["run_reference"])
        expected = "failed" if phase == "running" else "completed"
        assert result["state"] == expected
        assert result["conversation_state"] == expected
        if phase == "running":
            assert result["outcome"] == "interrupted"
        old = service.read(
            connection_id="connection-a", run_reference=saved["first"]["run_reference"]
        )
        assert old["state"] == "waiting_for_input" and old["revision"] == 1
        assert old["conversation_revision"] == 2 and "clarification" not in old
        assert len(provider.requests) == (1 if phase == "queued" else 0)
        assert (tmp_path / "dispatches.txt").read_text().count("dispatch") == (
            1 if phase == "queued" else 2
        )
        assert "PRIVATE" not in repr(result)
    finally:
        await service.close()
