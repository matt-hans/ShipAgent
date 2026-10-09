"""Real HTTP MCP reaches the canonical runtime and durable target-owned state."""

import asyncio
import socket
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastmcp import Client

from src.control_plane.auth.context import (
    AuthorizationContext,
    clear_authorization_context,
    set_authorization_context,
)
from src.control_plane.request_controls import RequestControls
from src.hosted_mcp.execution_target_handlers import (
    build_execution_target_tool_handlers,
)
from src.hosted_mcp.server import build_server
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from tests.control_plane.relay.test_routes import FakeRedis
from tests.services.conversation_acceptance import text_turn

OWNER = AuthorizationContext(
    account_id="account-a",
    provider_connection_id="connection-a",
    provider_surface="chatgpt",
    subject="synthetic-owner",
    client_id="chatgpt-client",
    scopes=frozenset({"shipagent.preview", "shipagent.status"}),
)


@asynccontextmanager
async def synthetic_mcp(
    store, provider_factory, *, context=OWNER, controls_now=None, connection_epoch=None
):
    from src.registry.tools.agent_runs import AGENT_RUN_TOOLS
    from src.services.agent_runs.execution_target import AgentRunExecutionTarget
    from src.services.agent_runs.service import AgentRunService

    service = AgentRunService(
        store=store,
        provider_factory=provider_factory,
        connection_epoch=connection_epoch,
    )
    target = AgentRunExecutionTarget(service)
    mcp = build_server(
        tool_handlers=build_execution_target_tool_handlers(
            target, include_agent_runs=True
        ),
        tools=[
            tool.model_copy(
                update={"provider_export_enabled": True, "hosted_readiness": "ready"}
            )
            for tool in AGENT_RUN_TOOLS
        ],
        request_controls=RequestControls(FakeRedis(), now_fn=controls_now),
    )
    mcp_app = mcp.http_app(path="/", transport="streamable-http")

    @asynccontextmanager
    async def lifespan(app):
        async with mcp_app.lifespan(app):
            await service.start()
            try:
                yield
            finally:
                await service.close()

    app = FastAPI(lifespan=lifespan)

    @app.middleware("http")
    async def synthetic_identity(request: Request, call_next):
        # Only the external identity-provider boundary is scripted. The actual
        # MCP gate, target service, run store and conversation runtime are real.
        assert request.headers.get("authorization") == "Bearer synthetic-owner"
        request.state.authorization = context
        token = set_authorization_context(context)
        try:
            return await call_next(request)
        finally:
            clear_authorization_context(token)

    app.mount("/mcp", mcp_app)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    try:
        async with asyncio.timeout(5):
            while not server.started:
                assert thread.is_alive()
                await asyncio.sleep(0.01)
        async with Client(
            f"http://127.0.0.1:{listener.getsockname()[1]}/mcp/", auth="synthetic-owner"
        ) as client:
            yield client
    finally:
        server.should_exit = True
        await asyncio.to_thread(thread.join, 5)
        listener.close()
        assert not thread.is_alive()


async def test_real_mcp_submit_runs_canonical_agent_and_completed_result_survives_reopen(
    tmp_path,
):
    from src.services.agent_runs.store import AgentRunStore

    path = tmp_path / "agent-runs.sqlite3"
    provider = FakeProviderClient(script=[text_turn("PRIVATE_INNER_REPLY_CANARY")])
    store = AgentRunStore(
        path, account_id="account-a", execution_target_id="target-a", create=True
    )
    async with synthetic_mcp(store, lambda _conversation: provider) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert set(tools) == {
            "submit_shipagent_task",
            "continue_shipagent_task",
            "read_shipagent_run",
            "cancel_shipagent_run",
        }
        assert tools["submit_shipagent_task"].annotations.readOnlyHint is False
        assert tools["read_shipagent_run"].annotations.readOnlyHint is True
        accepted = (
            await client.call_tool(
                "submit_shipagent_task",
                {
                    "task": "Help me plan a shipment",
                    "mode": "source_free",
                    "request_key": "request-one",
                },
            )
        ).structured_content
        assert accepted["state"] == "queued"
        assert accepted["run_reference"].startswith("sa_agent_run_")
        assert accepted["conversation_reference"].startswith("sa_conversation_")
        async with asyncio.timeout(5):
            while True:
                completed = (
                    await client.call_tool(
                        "read_shipagent_run",
                        {
                            "run_reference": accepted["run_reference"],
                        },
                    )
                ).structured_content
                if completed["state"] == "completed":
                    break
                await asyncio.sleep(0.05)
        assert completed["outcome"] == "planning_completed"
        assert "PRIVATE_INNER_REPLY_CANARY" not in repr(completed)
        assert len(provider.requests) == 1
        assert provider.requests[0]["tools"] == []

    def no_new_model(_conversation):
        raise AssertionError("Reading a recovered completed run must not open a model")

    reopened = AgentRunStore(
        path, account_id="account-a", execution_target_id="target-a"
    )
    async with synthetic_mcp(reopened, no_new_model) as client:
        recovered = (
            await client.call_tool(
                "read_shipagent_run",
                {
                    "run_reference": accepted["run_reference"],
                },
            )
        ).structured_content
    assert recovered == completed


async def test_concurrent_duplicate_submit_recovers_one_run_and_conflicting_reuse_fails(
    tmp_path,
):
    import pytest
    from fastmcp.exceptions import ToolError

    from src.services.agent_runs.store import AgentRunStore

    provider = FakeProviderClient(script=[text_turn("One model turn")])
    path = tmp_path / "agent-runs.sqlite3"
    store = AgentRunStore(
        path, account_id="account-a", execution_target_id="target-a", create=True
    )
    arguments = {
        "task": "Plan one shipment",
        "mode": "source_free",
        "request_key": "stable-key",
    }
    async with synthetic_mcp(store, lambda _conversation: provider) as client:
        first, duplicate = await asyncio.gather(
            client.call_tool("submit_shipagent_task", arguments),
            client.call_tool("submit_shipagent_task", arguments),
        )
        original = first.structured_content
        assert (
            duplicate.structured_content["run_reference"] == original["run_reference"]
        )
        assert (
            duplicate.structured_content["conversation_reference"]
            == original["conversation_reference"]
        )
        assert duplicate.structured_content["expires_at"] == original["expires_at"]
        with pytest.raises(ToolError):
            await client.call_tool(
                "submit_shipagent_task", {**arguments, "task": "A different request"}
            )
        async with asyncio.timeout(5):
            while len(provider.requests) == 0:
                await asyncio.sleep(0.01)
        assert len(provider.requests) == 1

    def no_new_provider(_conversation):
        raise AssertionError("An accepted retry cannot create another model run")

    reopened = AgentRunStore(
        path, account_id="account-a", execution_target_id="target-a"
    )
    async with synthetic_mcp(reopened, no_new_provider) as client:
        retried = (
            await client.call_tool("submit_shipagent_task", arguments)
        ).structured_content
    assert retried["run_reference"] == original["run_reference"]
    assert retried["expires_at"] == original["expires_at"]


async def test_status_only_and_foreign_owners_cannot_start_or_read_another_run(
    tmp_path,
):
    from dataclasses import replace

    import pytest
    from fastmcp.exceptions import ToolError

    from src.services.agent_runs.store import AgentRunStore

    provider = FakeProviderClient(script=[text_turn("One safe run")])
    path = tmp_path / "agent-runs.sqlite3"
    store = AgentRunStore(
        path, account_id="account-a", execution_target_id="target-a", create=True
    )
    arguments = {"task": "Plan", "mode": "source_free", "request_key": "owned-run"}
    async with synthetic_mcp(store, lambda _: provider) as client:
        accepted = (
            await client.call_tool("submit_shipagent_task", arguments)
        ).structured_content
        with pytest.raises(ToolError):
            await client.call_tool(
                "submit_shipagent_task", {**arguments, "approved": True}
            )

    read_only = replace(OWNER, scopes=frozenset({"shipagent.status"}))
    async with synthetic_mcp(store, lambda _: provider, context=read_only) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "submit_shipagent_task", {**arguments, "request_key": "read-only-run"}
            )
        result = (
            await client.call_tool(
                "read_shipagent_run", {"run_reference": accepted["run_reference"]}
            )
        ).structured_content
        assert result["run_reference"] == accepted["run_reference"]

    for foreign in (
        replace(OWNER, provider_connection_id="connection-b"),
        replace(OWNER, account_id="account-b"),
    ):
        async with synthetic_mcp(store, lambda _: provider, context=foreign) as client:
            with pytest.raises(ToolError):
                await client.call_tool(
                    "read_shipagent_run", {"run_reference": accepted["run_reference"]}
                )
    with pytest.raises(PermissionError):
        AgentRunStore(
            path, account_id="account-a", execution_target_id="target-replacement"
        )
    assert len(provider.requests) == 1


async def test_safe_poll_and_accepted_replay_do_not_trip_model_loop_guard(tmp_path):
    from src.services.agent_runs.store import AgentRunStore

    clock = [1000.0]
    provider = FakeProviderClient(script=[text_turn("Private answer")])
    store = AgentRunStore(
        tmp_path / "agent-runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    arguments = {"task": "Plan", "mode": "source_free", "request_key": "poll-safe-key"}
    async with synthetic_mcp(
        store, lambda _: provider, controls_now=lambda: clock[0]
    ) as client:
        original = (
            await client.call_tool("submit_shipagent_task", arguments)
        ).structured_content
        for _ in range(6):
            clock[0] += 2
            read = (
                await client.call_tool(
                    "read_shipagent_run", {"run_reference": original["run_reference"]}
                )
            ).structured_content
            replay = (
                await client.call_tool("submit_shipagent_task", arguments)
            ).structured_content
            assert (
                read["run_reference"]
                == replay["run_reference"]
                == original["run_reference"]
            )
            assert read["expires_at"] == replay["expires_at"] == original["expires_at"]
    assert len(provider.requests) == 1


async def test_invented_paid_call_and_private_results_never_cross_public_boundary(
    tmp_path,
):
    from src.services.agent_runs.store import AgentRunStore
    from tests.services.conversation_acceptance import tool_call_turn

    provider = FakeProviderClient(
        script=[
            tool_call_turn(
                "invented-paid",
                "batch_execute",
                {"approved": True, "job_id": "PRIVATE_JOB_CANARY"},
            ),
            text_turn("PRIVATE_RESULT_CANARY"),
        ]
    )
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    async with synthetic_mcp(store, lambda _: provider) as client:
        accepted = (
            await client.call_tool(
                "submit_shipagent_task",
                {
                    "task": "Plan only",
                    "mode": "source_free",
                    "request_key": "safe-public-key",
                },
            )
        ).structured_content
        async with asyncio.timeout(5):
            while True:
                result = (
                    await client.call_tool(
                        "read_shipagent_run",
                        {"run_reference": accepted["run_reference"]},
                    )
                ).structured_content
                if result["state"] not in {"queued", "running"}:
                    break
                await asyncio.sleep(0.1)
        assert result["state"] == "completed"
        assert "PRIVATE" not in repr(result)
        assert len(provider.requests) == 2
        assert provider.requests[0]["tools"] == []
        assert "This tool is not admitted by the execution profile." in repr(
            provider.requests[1]["messages"]
        )
