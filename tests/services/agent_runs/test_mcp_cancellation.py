"""Actual loopback MCP cancellation reaches the durable target-owned run."""

import asyncio
import threading
from dataclasses import replace

import pytest
from fastmcp.exceptions import ToolError

from src.services.agent_runs.store import AgentRunStore
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.conversation_runtime.models import ProviderCapabilities
from tests.services.agent_runs.test_mcp_tracer import OWNER, synthetic_mcp
from tests.services.conversation_acceptance import text_turn


class WaitingProvider(FakeProviderClient):
    def __init__(self):
        super().__init__(
            script=[text_turn("PRIVATE_STALE_CANCELLED_OUTPUT")],
            capabilities=ProviderCapabilities(
                provider="fake", model="fake", supports_cancellation=True
            ),
        )
        self.opened = threading.Event()
        self.released = threading.Event()
        self.closed = threading.Event()

    def stream_turn(self, **kwargs):
        inner = super().stream_turn(**kwargs)

        async def events():
            try:
                self.opened.set()
                while not self.released.is_set():
                    await asyncio.sleep(0.005)
                async for event in inner:
                    yield event
            finally:
                self.closed.set()

        return events()


def _new_store(tmp_path):
    return AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )


async def _wait_flag(flag):
    async with asyncio.timeout(3):
        while not flag.is_set():
            await asyncio.sleep(0.005)


async def _call(client, name, arguments):
    return (await client.call_tool(name, arguments)).structured_content


async def test_http_cancel_queued_and_running_preserves_identity_after_reopen(tmp_path):
    store = _new_store(tmp_path)
    provider = WaitingProvider()
    factory_calls = []

    def factory(conversation):
        factory_calls.append(conversation)
        return provider

    first_args = {"task": "First", "mode": "source_free", "request_key": "cancel-first"}
    queued_args = {
        "task": "Queued",
        "mode": "source_free",
        "request_key": "cancel-queue",
    }
    try:
        async with synthetic_mcp(store, factory) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert tools["cancel_shipagent_run"].annotations.readOnlyHint is False
            first = await _call(client, "submit_shipagent_task", first_args)
            await _wait_flag(provider.opened)
            queued = await _call(client, "submit_shipagent_task", queued_args)
            assert queued["state"] == "queued"
            cancelled = []
            for accepted in (queued, first):
                result = await _call(
                    client,
                    "cancel_shipagent_run",
                    {
                        "run_reference": accepted["run_reference"],
                    },
                )
                assert result["state"] == result["outcome"] == "cancelled"
                assert result["expires_at"] == accepted["expires_at"]
                assert (
                    result["conversation_reference"]
                    == accepted["conversation_reference"]
                )
                assert result["poll_after_seconds"] == 0
                cancelled.append(result)
            await _wait_flag(provider.closed)
            assert len(factory_calls) == len(provider.requests) == 1
            assert provider.cancelled
    finally:
        provider.released.set()

    def no_model(_conversation):
        raise AssertionError("A cancelled run must not dispatch after reopening")

    reopened = AgentRunStore(
        store.path, account_id="account-a", execution_target_id="target-a"
    )
    async with synthetic_mcp(reopened, no_model) as client:
        for args, result in zip((queued_args, first_args), cancelled, strict=True):
            assert await _call(client, "submit_shipagent_task", args) == result
            for _ in range(5):
                assert (
                    await _call(
                        client,
                        "cancel_shipagent_run",
                        {
                            "run_reference": result["run_reference"],
                        },
                    )
                    == result
                )
            assert (
                await _call(
                    client,
                    "read_shipagent_run",
                    {
                        "run_reference": result["run_reference"],
                    },
                )
                == result
            )
            assert "PRIVATE" not in repr(result)
    assert len(factory_calls) == len(provider.requests) == 1


async def test_http_cancel_preserves_completed_turn_and_denies_foreign_authority(
    tmp_path,
):
    store = _new_store(tmp_path)
    provider = FakeProviderClient(script=[text_turn("Private completed result")])
    async with synthetic_mcp(store, lambda _: provider) as client:
        accepted = await _call(
            client,
            "submit_shipagent_task",
            {
                "task": "Plan",
                "mode": "source_free",
                "request_key": "complete-first",
            },
        )
        reference = {"run_reference": accepted["run_reference"]}
        async with asyncio.timeout(3):
            while True:
                completed = await _call(client, "read_shipagent_run", reference)
                if completed["state"] == "completed":
                    break
                await asyncio.sleep(0.02)
        assert await _call(client, "cancel_shipagent_run", reference) == completed
        with pytest.raises(ToolError):
            await client.call_tool(
                "cancel_shipagent_run", {**reference, "approved": True}
            )

    def no_model(_conversation):
        raise AssertionError(
            "Cancelling or reading terminal work must not invoke a model"
        )

    for unauthorized in (
        replace(OWNER, scopes=frozenset({"shipagent.status"})),
        replace(OWNER, account_id="account-b"),
        replace(OWNER, provider_connection_id="connection-b"),
    ):
        async with synthetic_mcp(store, no_model, context=unauthorized) as client:
            with pytest.raises(ToolError):
                await client.call_tool("cancel_shipagent_run", reference)
    assert (
        store.read(
            connection_id="connection-a", run_reference=accepted["run_reference"]
        ).public_result()
        == completed
    )
    assert len(provider.requests) == 1
