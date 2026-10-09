"""Real HTTP accepts only the exact current trusted planning follow-up."""

import asyncio
import json
import sqlite3
from dataclasses import replace

import pytest
from fastmcp.exceptions import ToolError

from src.services.agent_runs.store import AgentRunStore
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from tests.services.agent_runs.test_mcp_tracer import OWNER, synthetic_mcp
from tests.services.conversation_acceptance import text_turn


def store_at(path, *, create=False):
    return AgentRunStore(
        path, account_id="account-a", execution_target_id="target-a", create=create
    )


async def call(client, name, arguments):
    return (await client.call_tool(name, arguments)).structured_content


async def stopped(client, reference):
    async with asyncio.timeout(4):
        while True:
            result = await call(
                client, "read_shipagent_run", {"run_reference": reference}
            )
            if result["state"] not in {"queued", "running"}:
                return result
            await asyncio.sleep(0.02)


def history_row(path, reference):
    with sqlite3.connect(path) as db:
        return db.execute(
            "SELECT * FROM agent_runs WHERE run_reference = ?", (reference,)
        ).fetchone()


async def test_http_clarify_continue_retry_and_reopen_are_durable_and_private(tmp_path):
    providers = [
        FakeProviderClient(
            script=[text_turn('{"clarification_code":"package_scope"}')]
        ),
        FakeProviderClient(script=[text_turn("PRIVATE_CONTINUATION_PLAN_CANARY")]),
    ]
    pending = iter(providers)
    path = tmp_path / "runs.sqlite3"
    store = store_at(path, create=True)
    epochs = {"connection-a": "trusted-link-a"}
    async with synthetic_mcp(
        store, lambda _: next(pending), connection_epoch=epochs.get
    ) as client:
        assert "continue_shipagent_task" in {
            tool.name for tool in await client.list_tools()
        }
        first = await call(
            client,
            "submit_shipagent_task",
            {
                "task": "Plan a shipment",
                "mode": "source_free",
                "request_key": "mcp-first-key",
            },
        )
        waiting = await stopped(client, first["run_reference"])
        assert waiting["state"] == waiting["conversation_state"] == "waiting_for_input"
        assert waiting["clarification"] == {
            "code": "package_scope",
            "question": "Are you planning one package or multiple packages?",
        }
        original = history_row(path, first["run_reference"])
        args = {
            "conversation_reference": first["conversation_reference"],
            "run_reference": first["run_reference"],
            "expected_revision": 1,
            "task": "One package",
            "request_key": "mcp-follow-up-key",
        }
        for invalid in (
            {**args, "expected_revision": 2},
            {**args, "run_reference": "sa_agent_run_" + "f" * 32},
            {**args, "conversation_reference": "sa_conversation_" + "f" * 32},
            {**args, "link_epoch": "model-chosen-authority"},
            {**args, "approved": True},
        ):
            with pytest.raises(ToolError):
                await client.call_tool("continue_shipagent_task", invalid)
        assert sum(len(p.requests) for p in providers) == 1
        accepted = await call(client, "continue_shipagent_task", args)
        assert accepted["run_reference"] != first["run_reference"]
        assert accepted["revision"] == accepted["conversation_revision"] == 2
        assert accepted["expires_at"] == first["expires_at"]
        done = await stopped(client, accepted["run_reference"])
        assert done["state"] == "completed"
        assert await call(client, "continue_shipagent_task", args) == done
        with pytest.raises(ToolError):
            await client.call_tool(
                "continue_shipagent_task", {**args, "task": "Changed answer"}
            )
        old = await call(
            client, "read_shipagent_run", {"run_reference": first["run_reference"]}
        )
        assert old["state"] == "waiting_for_input" and old["revision"] == 1
        assert (
            old["conversation_revision"] == 2
            and old["conversation_state"] == "completed"
        )
        assert "clarification" not in old
        assert history_row(path, first["run_reference"]) == original
        assert "CANARY" not in json.dumps([waiting, done, old])
        assert "trusted-link-a" not in json.dumps([waiting, done, old])
    assert sum(len(p.requests) for p in providers) == 2
    assert all(request["tools"] == [] for p in providers for request in p.requests)

    def no_replay(_):
        pytest.fail("A durable retry must not construct another provider")

    async with synthetic_mcp(
        store_at(path), no_replay, connection_epoch=epochs.get
    ) as client:
        assert await call(client, "continue_shipagent_task", args) == done
        assert await stopped(client, done["run_reference"]) == done
        epochs["connection-a"] = "replacement-link"
        with pytest.raises(ToolError):
            await client.call_tool("continue_shipagent_task", args)
        with pytest.raises(ToolError):
            await client.call_tool(
                "read_shipagent_run", {"run_reference": done["run_reference"]}
            )


async def test_http_quiescent_cancel_invalidates_only_current_follow_up(tmp_path):
    path = tmp_path / "runs.sqlite3"
    provider = FakeProviderClient(
        script=[text_turn('{"clarification_code":"shipping_goal"}')]
    )
    store = store_at(path, create=True)

    def epoch(_):
        return "trusted-link-a"

    async with synthetic_mcp(
        store, lambda _: provider, connection_epoch=epoch
    ) as client:
        accepted = await call(
            client,
            "submit_shipagent_task",
            {
                "task": "Help",
                "mode": "source_free",
                "request_key": "cancel-wait-key",
            },
        )
        waiting = await stopped(client, accepted["run_reference"])
        original = history_row(path, accepted["run_reference"])
        ref = {"run_reference": accepted["run_reference"]}
        cancelled = await call(client, "cancel_shipagent_run", ref)
        assert cancelled["state"] == waiting["state"] == "waiting_for_input"
        assert cancelled["conversation_state"] == "cancelled"
        assert "clarification" not in cancelled
        assert await call(client, "cancel_shipagent_run", ref) == cancelled
        with pytest.raises(ToolError):
            await client.call_tool(
                "continue_shipagent_task",
                {
                    **ref,
                    "conversation_reference": accepted["conversation_reference"],
                    "expected_revision": 1,
                    "task": "Too late",
                    "request_key": "cancel-too-late",
                },
            )
        assert history_row(path, accepted["run_reference"]) == original
        assert len(provider.requests) == 1


@pytest.mark.parametrize(
    "context",
    [
        replace(OWNER, scopes=frozenset({"shipagent.status"})),
        replace(OWNER, account_id="account-b"),
        replace(OWNER, provider_connection_id="connection-b"),
    ],
)
async def test_http_foreign_or_status_only_continuation_never_dispatches(
    tmp_path, context
):
    path = tmp_path / "runs.sqlite3"
    provider = FakeProviderClient(
        script=[text_turn('{"clarification_code":"shipping_goal"}')]
    )
    store = store_at(path, create=True)

    def epoch(_):
        return "trusted-link-a"

    async with synthetic_mcp(
        store, lambda _: provider, connection_epoch=epoch
    ) as client:
        accepted = await call(
            client,
            "submit_shipagent_task",
            {
                "task": "Help",
                "mode": "source_free",
                "request_key": "foreign-first-key",
            },
        )
        await stopped(client, accepted["run_reference"])

    def no_dispatch(_):
        pytest.fail("Denied continuation must never construct a provider")

    async with synthetic_mcp(
        store_at(path), no_dispatch, context=context, connection_epoch=epoch
    ) as client:
        assert "continue_shipagent_task" in {
            tool.name for tool in await client.list_tools()
        }
        with pytest.raises(ToolError):
            await client.call_tool(
                "continue_shipagent_task",
                {
                    "conversation_reference": accepted["conversation_reference"],
                    "run_reference": accepted["run_reference"],
                    "expected_revision": 1,
                    "task": "Denied",
                    "request_key": "foreign-follow-key",
                },
            )
    assert len(provider.requests) == 1


async def test_http_unbound_legacy_run_cannot_gain_follow_up_authority(tmp_path):
    provider = FakeProviderClient(script=[text_turn("Private legacy plan")])
    async with synthetic_mcp(
        store_at(tmp_path / "runs.sqlite3", create=True), lambda _: provider
    ) as client:
        accepted = await call(
            client,
            "submit_shipagent_task",
            {
                "task": "Legacy planning",
                "mode": "source_free",
                "request_key": "legacy-first-key",
            },
        )
        completed = await stopped(client, accepted["run_reference"])
        assert "conversation_revision" not in completed
        assert "clarification" not in completed
        assert "continue_shipagent_task" in {
            tool.name for tool in await client.list_tools()
        }
        with pytest.raises(ToolError):
            await client.call_tool(
                "continue_shipagent_task",
                {
                    "conversation_reference": accepted["conversation_reference"],
                    "run_reference": accepted["run_reference"],
                    "expected_revision": 1,
                    "task": "Invent follow-up authority",
                    "request_key": "legacy-follow-key",
                },
            )
        assert len(provider.requests) == 1
