"""T0 wire acceptance: real MCP/runtime/storage; synthetic identity and providers.

These are generic protocol clients, not ChatGPT or Claude product clients. Only
the deliberately opted-in source-free submit/read/cancel catalog is exercised. Carrier
acquisition is counted and replaced at the external gateway boundary.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastmcp import Client
from fastmcp.exceptions import ToolError

from src.control_plane.auth.context import (
    AuthorizationContext,
    clear_authorization_context,
    set_authorization_context,
)
from src.control_plane.execution_targets import LoopbackExecutionTarget
from src.control_plane.request_controls import RequestControls
from src.hosted_mcp.execution_target_handlers import (
    build_execution_target_tool_handlers,
)
from src.hosted_mcp.server import build_server
from src.registry.tools.agent_runs import AGENT_RUN_TOOLS, RUN_RESULT_SCHEMA
from src.services.agent_runs.execution_target import AgentRunExecutionTarget
from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.conversation_runtime.models import (
    ProviderStreamEvent,
    ProviderStreamEventType,
    ProviderToolCall,
)

OWNER = AuthorizationContext(
    account_id="acceptance-account-a",
    provider_connection_id="acceptance-connection-a",
    provider_surface="chatgpt",
    subject="synthetic-owner",
    client_id="synthetic-client",
    scopes=frozenset({"shipagent.preview", "shipagent.status"}),
)
IDENTITIES = {
    "owner": OWNER,
    "status-only": replace(OWNER, scopes=frozenset({"shipagent.status"})),
    "other-connection": replace(
        OWNER, provider_connection_id="acceptance-connection-b"
    ),
    "other-account": replace(OWNER, account_id="acceptance-account-b"),
}
ARGS = {
    "task": "Help plan a shipment without reading any source or buying anything.",
    "mode": "source_free",
    "request_key": "acceptance-request-one",
}
CANARY = "PRIVATE_ACCEPTANCE_PROVIDER_CANARY"


def text_turn(*, complete=True):
    events = [
        ProviderStreamEvent(
            type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE, text=CANARY
        )
    ]
    if complete:
        events.append(ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE))
    return events


class SyntheticRedisCounters:
    """Only the Redis boundary is fake; production request controls still run."""

    def __init__(self):
        self.counts = Counter()

    async def eval(self, script, numkeys, *args):
        assert numkeys == 1
        assert "SA_RATE_LIMIT" in script or "SA_LOOP_GUARD" in script
        self.counts[args[0]] += 1
        return self.counts[args[0]]


@dataclass
class CarrierBoundary:
    acquisitions: int = 0
    calls: Counter = field(default_factory=Counter)

    async def acquire(self):
        self.acquisitions += 1
        return self

    async def create_shipment(self, request_body):
        self.calls["create_shipment"] += 1
        return {"status": "synthetic-only"}


@pytest.fixture
def carrier(monkeypatch):
    boundary = CarrierBoundary()
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway", boundary.acquire
    )
    return boundary


class WireProbe:
    """Count JSON-RPC requests and optionally lose one successful submit reply.

    A 503 substitutes for the real response only after the MCP server generated
    its successful result. The client never receives that accepted reference.
    This is a deterministic response-loss injection, not a TCP partition test.
    """

    def __init__(self, app, *, lose_submit_reply=False):
        self.app = app
        self.lose_submit_reply = lose_submit_reply
        self.methods = Counter()
        self.lost_result = None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        messages, body = [], b""
        while True:
            message = await receive()
            messages.append(message)
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        request = json.loads(body)
        method = request.get("method", "")
        self.methods[method] += 1
        tool = request.get("params", {}).get("name")
        should_lose = self.lose_submit_reply and tool == "submit_shipagent_task"
        if should_lose:
            self.lose_submit_reply = False

        async def replay():
            return messages.pop(0) if messages else await receive()

        if not should_lose:
            return await self.app(scope, replay, send)
        responses = []

        async def capture(message):
            responses.append(message)
            if message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                payload = json.loads(b"".join(m.get("body", b"") for m in responses))
                self.lost_result = payload["result"]["structuredContent"]
                assert not payload["result"].get("isError", False)
                await send(
                    {"type": "http.response.start", "status": 503, "headers": []}
                )
                await send(
                    {"type": "http.response.body", "body": b"Synthetic reply lost"}
                )

        await self.app(scope, replay, capture)


@asynccontextmanager
async def listen(app):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(32)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]})
    thread.start()
    try:
        async with asyncio.timeout(5):
            while not server.started:
                assert thread.is_alive(), "MCP listener exited before startup"
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}/mcp/"
    finally:
        server.should_exit = True
        await asyncio.to_thread(thread.join, 5)
        listener.close()
        assert not thread.is_alive(), "Owned MCP listener did not stop"


@asynccontextmanager
async def mcp_endpoint(
    path, provider_factory, *, default_catalog=False, lose_reply=False
):
    store = AgentRunStore(
        path,
        account_id=OWNER.account_id,
        execution_target_id="acceptance-target-a",
        create=not path.exists(),
    )
    service = AgentRunService(store=store, provider_factory=provider_factory)
    target = (
        LoopbackExecutionTarget()
        if default_catalog
        else AgentRunExecutionTarget(service)
    )
    options = (
        {}
        if default_catalog
        else {
            "tools": [
                tool.model_copy(
                    update={
                        "provider_export_enabled": True,
                        "hosted_readiness": "ready",
                    }
                )
                for tool in AGENT_RUN_TOOLS
            ]
        }
    )
    mcp = build_server(
        tool_handlers=build_execution_target_tool_handlers(
            target, include_agent_runs=True
        ),
        request_controls=RequestControls(SyntheticRedisCounters()),
        **options,
    )
    mcp_app = mcp.http_app(path="/", transport="streamable-http", json_response=True)

    @asynccontextmanager
    async def lifespan(app):
        async with mcp_app.lifespan(app):
            if not default_catalog:
                await service.start()
            try:
                yield
            finally:
                if not default_catalog:
                    await service.close()

    app = FastAPI(lifespan=lifespan)

    @app.middleware("http")
    async def synthetic_identity(request: Request, call_next):
        # Test boundary only: absent identity reaches the real MCP auth gate.
        key = request.headers.get("authorization", "").removeprefix("Bearer ")
        context = IDENTITIES.get(key)
        request.state.authorization = context
        token = set_authorization_context(context)
        try:
            return await call_next(request)
        finally:
            clear_authorization_context(token)

    app.mount("/mcp", mcp_app)
    probe = WireProbe(app, lose_submit_reply=lose_reply)
    async with listen(probe) as url:
        yield url, probe


async def terminal(client, reference):
    async with asyncio.timeout(10):
        while True:
            result = (
                await client.call_tool(
                    "read_shipagent_run", {"run_reference": reference}
                )
            ).structured_content
            assert set(result) == set(RUN_RESULT_SCHEMA["properties"])
            assert CANARY not in json.dumps(result)
            if result["state"] not in {"queued", "running"}:
                return result
            await asyncio.sleep(result["poll_after_seconds"])


async def test_default_wire_catalog_remains_status_only(tmp_path, carrier):
    def forbidden_provider(_):
        pytest.fail("Default status must not construct a model provider")

    async with mcp_endpoint(
        tmp_path / "runs.sqlite3", forbidden_provider, default_catalog=True
    ) as (url, probe):
        async with Client(url, auth="owner") as client:
            assert {tool.name for tool in await client.list_tools()} == {
                "get_shipagent_status"
            }
            result = await client.call_tool(
                "get_shipagent_status",
                {"correlation_id": "sa_correlation_0123456789abcdef0123456789abcdef"},
            )
            assert result.structured_content == {
                "status": "ready",
                "executionTarget": {"state": "ready", "capabilities": []},
            }
            with pytest.raises(ToolError):
                await client.call_tool("submit_shipagent_task", ARGS)
        assert probe.methods["initialize"] == 1
        assert probe.methods["tools/list"] >= 1
    assert carrier.acquisitions == 0


async def test_lost_reply_reconnect_and_reopen_keep_one_durable_run(
    tmp_path, carrier, caplog
):
    provider = FakeProviderClient(script=[text_turn()])
    path = tmp_path / "runs.sqlite3"
    async with mcp_endpoint(path, lambda _: provider, lose_reply=True) as (url, probe):
        with pytest.raises(httpx.HTTPStatusError) as lost:
            async with Client(url, auth="owner") as client:
                tools = {tool.name: tool for tool in await client.list_tools()}
                assert set(tools) == {
                    "submit_shipagent_task",
                    "read_shipagent_run",
                    "cancel_shipagent_run",
                }
                assert tools["submit_shipagent_task"].annotations.readOnlyHint is False
                assert tools["read_shipagent_run"].annotations.readOnlyHint is True
                assert tools["cancel_shipagent_run"].annotations.readOnlyHint is False
                async with asyncio.timeout(5):
                    await client.call_tool("submit_shipagent_task", ARGS)
        assert lost.value.response.status_code == 503
        assert probe.lost_result is not None
        async with Client(url, auth="owner") as reconnected:
            retry = (
                await reconnected.call_tool("submit_shipagent_task", ARGS)
            ).structured_content
            for key in ("run_reference", "conversation_reference", "expires_at"):
                assert retry[key] == probe.lost_result[key]
            done = await terminal(reconnected, retry["run_reference"])
            assert done["state"] == "completed"
            assert done["outcome"] == "planning_completed"
            with pytest.raises(ToolError):
                await reconnected.call_tool(
                    "submit_shipagent_task", {**ARGS, "task": "Conflicting key reuse"}
                )
        assert probe.methods["initialize"] == 2
    assert len(provider.requests) == 1
    assert provider.requests[0]["tools"] == []

    def no_replay(_):
        pytest.fail("Reading/retrying a completed run must not create a provider")

    async with mcp_endpoint(path, no_replay) as (url, _):
        async with Client(url, auth="owner") as client:
            replay = (
                await client.call_tool("submit_shipagent_task", ARGS)
            ).structured_content
            assert replay == done
            assert await terminal(client, replay["run_reference"]) == done
    assert carrier.acquisitions == 0
    assert sum(carrier.calls.values()) == 0
    assert CANARY not in caplog.text


async def test_wire_owner_scope_and_missing_context_denials_do_not_dispatch(
    tmp_path, carrier
):
    provider = FakeProviderClient(script=[text_turn()])
    async with mcp_endpoint(tmp_path / "runs.sqlite3", lambda _: provider) as (url, _):
        async with Client(url, auth="owner") as client:
            accepted = (
                await client.call_tool("submit_shipagent_task", ARGS)
            ).structured_content
            done = await terminal(client, accepted["run_reference"])
        for identity in (None, "status-only", "other-account"):
            async with Client(url, auth=identity) as client:
                with pytest.raises(ToolError):
                    await client.call_tool(
                        "submit_shipagent_task",
                        {**ARGS, "request_key": "denied-request-key"},
                    )
        for identity in (None, "other-account", "other-connection"):
            async with Client(url, auth=identity) as client:
                with pytest.raises(ToolError):
                    await client.call_tool(
                        "read_shipagent_run",
                        {"run_reference": accepted["run_reference"]},
                    )
        async with Client(url, auth="status-only") as client:
            assert await terminal(client, accepted["run_reference"]) == done
    assert len(provider.requests) == 1
    assert carrier.acquisitions == 0


@pytest.mark.parametrize(
    "complete", [True, False], ids=["terminal-proof", "clean-eof-without-proof"]
)
async def test_wire_completion_requires_real_fake_provider_terminal_proof(
    tmp_path, carrier, complete
):
    provider = FakeProviderClient(script=[text_turn(complete=complete)])
    async with mcp_endpoint(tmp_path / "runs.sqlite3", lambda _: provider) as (url, _):
        async with Client(url, auth="owner") as client:
            accepted = (
                await client.call_tool("submit_shipagent_task", ARGS)
            ).structured_content
            result = await terminal(client, accepted["run_reference"])
    assert result["state"] == ("completed" if complete else "failed")
    assert result["outcome"] == ("planning_completed" if complete else "interrupted")
    assert len(provider.requests) == 1
    assert carrier.acquisitions == 0


async def test_model_requested_purchase_is_denied_before_fake_carrier(
    tmp_path, carrier, caplog
):
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
                    tool_call=ProviderToolCall(
                        call_id="forbidden-purchase",
                        tool_name="batch_execute",
                        parsed_input={"approved": True, "job_id": "PRIVATE_JOB_CANARY"},
                    ),
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
            text_turn(),
        ]
    )
    async with mcp_endpoint(tmp_path / "runs.sqlite3", lambda _: provider) as (url, _):
        async with Client(url, auth="owner") as client:
            accepted = (
                await client.call_tool("submit_shipagent_task", ARGS)
            ).structured_content
            result = await terminal(client, accepted["run_reference"])
    assert result["state"] == "completed"
    assert len(provider.requests) == 2
    assert all(request["tools"] == [] for request in provider.requests)
    tool_messages = [
        message
        for message in provider.requests[1]["messages"]
        if message.role == "tool"
    ]
    assert len(tool_messages) == 1
    assert tool_messages[0].metadata["is_error"] is True
    assert "This tool is not admitted by the execution profile." in repr(tool_messages)
    assert carrier.acquisitions == 0
    assert carrier.calls == {}
    assert CANARY not in caplog.text
    assert "PRIVATE_JOB_CANARY" not in caplog.text


async def test_fake_carrier_counter_is_connected_to_real_gateway_boundary(carrier):
    from src.orchestrator.agent.tools.core import _get_ups_client

    client = await _get_ups_client()
    assert await client.create_shipment({"synthetic": True}) == {
        "status": "synthetic-only"
    }
    assert carrier.acquisitions == 1
    assert carrier.calls == {"create_shipment": 1}


async def test_default_control_plane_missing_bearer_is_http_401(monkeypatch):
    from src.control_plane.app import create_control_plane_app
    from src.control_plane.config import ControlPlaneSettings

    def no_db():
        pytest.fail("An unauthenticated MCP request must not touch a database")

    app = create_control_plane_app(
        settings=ControlPlaneSettings(
            public_base_url="https://mcp.example.invalid",
            auth0_issuer="https://identity.example.invalid/",
            auth0_audience="https://mcp.example.invalid/mcp",
        ),
        redis_client=SyntheticRedisCounters(),
        db_session_factory=no_db,
        execution_target=LoopbackExecutionTarget(),
    )
    async with listen(app) as url:
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.post(
                url,
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert "resource_metadata=" in response.headers["www-authenticate"]
