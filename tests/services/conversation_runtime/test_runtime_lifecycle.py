"""Request ownership and cancellation at the public runtime boundary."""

import asyncio

import pytest

from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.conversation_runtime.models import (
    ProviderStreamEvent,
    ProviderStreamEventType,
)
from src.services.conversation_runtime.runtime_session import ConversationRuntimeSession
from tests.services.conversation_acceptance import text_turn


def runtime(provider, **kwargs):
    return ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="lifecycle",
        **kwargs,
    )


async def collect(stream):
    return [event async for event in stream]


async def test_superseded_unstarted_generator_never_opens_transport_or_replaces_history():
    provider = FakeProviderClient(
        script=[text_turn("New answer!"), text_turn("OLD ANSWER!")]
    )
    agent = runtime(provider)
    await agent.start()
    old = agent.process_message_stream("Old request!")
    new = agent.process_message_stream("New request!")
    assert await collect(new) == [
        {"event": "agent_message", "data": {"text": "New answer!"}}
    ]
    assert await collect(old) == []
    assert len(provider.requests) == 1


class OpeningProvider(FakeProviderClient):
    def __init__(self):
        super().__init__(script=[])
        self.opened = asyncio.Event()
        self.closed = asyncio.Event()
        self.release = asyncio.Event()

    async def stream_turn(self, **kwargs):
        try:
            self.opened.set()
            await self.release.wait()
            yield ProviderStreamEvent(
                type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE, text="Late response!"
            )
        finally:
            self.closed.set()


@pytest.mark.parametrize("action", ["stop", "interrupt"])
async def test_cancel_closes_owned_opening_request_without_waiting_for_provider_bytes(
    action,
):
    provider = OpeningProvider()
    agent = runtime(provider)
    await agent.start()
    task = asyncio.create_task(collect(agent.process_message_stream("Wait for model!")))
    await provider.opened.wait()
    try:
        await getattr(agent, action)()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert provider.closed.is_set()
        assert await task == []
    finally:
        provider.release.set()
        await task


async def test_old_tool_artifact_cannot_enter_new_generation(monkeypatch):
    from src.services.conversation_runtime.tool_catalog import (
        SideEffectClass,
        ToolMode,
        WorkflowToolCatalog,
        WorkflowToolDefinition,
    )
    from tests.services.conversation_acceptance import tool_call_turn

    old_started, new_started, release_old, release_new = (
        asyncio.Event() for _ in range(4)
    )

    async def handler(args, bridge):
        old = args["turn"] == "old"
        (old_started if old else new_started).set()
        await (release_old if old else release_new).wait()
        bridge.emit(
            "tracking_result",
            {"tracking_number": "STALE-OLD" if old else "CURRENT-NEW"},
        )
        return {"content": [{"type": "text", "text": "{}"}]}

    def catalog(cls, *, interactive_shipping, bridge):
        return WorkflowToolCatalog(
            [
                WorkflowToolDefinition(
                    name="track_package",
                    description="track",
                    input_schema={"type": "object"},
                    handler=lambda args: handler(args, bridge),
                    mode=ToolMode.BOTH,
                    side_effect_class=SideEffectClass.READ_ONLY,
                )
            ]
        )

    monkeypatch.setattr(WorkflowToolCatalog, "for_mode", classmethod(catalog))
    provider = FakeProviderClient(
        script=[
            tool_call_turn("old", "track_package", {"turn": "old"}),
            tool_call_turn("new", "track_package", {"turn": "new"}),
            text_turn("Done"),
        ]
    )
    agent = runtime(provider)
    await agent.start()
    old_task = asyncio.create_task(collect(agent.process_message_stream("old")))
    await old_started.wait()
    new_task = asyncio.create_task(collect(agent.process_message_stream("new")))
    await new_started.wait()
    release_old.set()
    old_events = await old_task
    release_new.set()
    new_events = await new_task
    assert "STALE-OLD" not in str(new_events + old_events)
    assert "CURRENT-NEW" in str(new_events)


async def test_turn_limit_retains_completed_tool_results_without_reexecuting(
    monkeypatch,
):
    from src.services.conversation_runtime.tool_catalog import (
        SideEffectClass,
        ToolMode,
        WorkflowToolCatalog,
        WorkflowToolDefinition,
    )
    from tests.services.conversation_acceptance import tool_call_turn

    calls = []

    async def handler(args):
        calls.append(args)
        return {"content": [{"type": "text", "text": "{}"}]}

    def catalog(cls, **kwargs):
        return WorkflowToolCatalog(
            [
                WorkflowToolDefinition(
                    name="get_schema",
                    description="schema",
                    input_schema={"type": "object"},
                    handler=handler,
                    mode=ToolMode.BOTH,
                    side_effect_class=SideEffectClass.READ_ONLY,
                )
            ]
        )

    monkeypatch.setattr(WorkflowToolCatalog, "for_mode", classmethod(catalog))
    provider = FakeProviderClient(
        script=[tool_call_turn("accepted", "get_schema", {}), text_turn("Recovered")]
    )
    agent = runtime(provider, max_turns=1)
    await agent.start()
    first = await collect(agent.process_message_stream("First request"))
    assert first[-1]["event"] == "error"
    assert agent.last_turn_count == 1
    await collect(agent.process_message_stream("Continue"))
    roles = [message.role for message in provider.requests[1]["messages"]]
    assert roles == ["user", "assistant", "tool", "user"]
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["anthropic", "openai", "gemini"])
@pytest.mark.parametrize("phase", ["opening", "streaming"])
async def test_real_adapter_cancellation_is_request_local_on_borrowed_http_client(
    kind, phase
):
    import httpx

    from tests.services import provider_scenarios as scenarios

    opened = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]
    closed = [asyncio.Event(), asyncio.Event()]
    count = 0
    render = getattr(scenarios, f"_{kind}_body")
    make_client = getattr(scenarios, f"_{kind}_client")

    class ResponseBody(httpx.AsyncByteStream):
        def __init__(self, index):
            self.index = index

        async def __aiter__(self):
            if phase == "streaming":
                opened[self.index].set()
                await release[self.index].wait()
            yield render([scenarios.Say("Owned response")])

        async def aclose(self):
            closed[self.index].set()

    async def handler(request):
        nonlocal count
        index = count
        count += 1
        if phase == "opening":
            opened[index].set()
            try:
                await release[index].wait()
            except asyncio.CancelledError:
                closed[index].set()
                raise
        return httpx.Response(
            200,
            stream=ResponseBody(index),
            headers={"content-type": "text/event-stream"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        first = runtime(make_client(http))
        second = runtime(make_client(http))
        await first.start()
        await second.start()
        first_task = asyncio.create_task(collect(first.process_message_stream("first")))
        await opened[0].wait()
        second_task = asyncio.create_task(
            collect(second.process_message_stream("second"))
        )
        await opened[1].wait()
        try:
            await first.stop()
            await asyncio.wait_for(closed[0].wait(), 1)
            assert not closed[1].is_set() and not http.is_closed
            assert await asyncio.wait_for(first_task, 1) == []
            release[1].set()
            events = await asyncio.wait_for(second_task, 1)
            assert any(
                e["event"] == "agent_message" and e["data"]["text"] == "Owned response"
                for e in events
            )
        finally:
            for gate in release:
                gate.set()
            await asyncio.gather(first_task, second_task, return_exceptions=True)


async def test_history_budget_retains_whole_tool_turns(monkeypatch):
    from src.services.conversation_runtime.tool_catalog import (
        SideEffectClass,
        ToolMode,
        WorkflowToolCatalog,
        WorkflowToolDefinition,
    )
    from tests.services.conversation_acceptance import tool_call_turn

    async def handler(args):
        return {"content": [{"type": "text", "text": "{}"}]}

    def catalog(cls, **kwargs):
        return WorkflowToolCatalog(
            [
                WorkflowToolDefinition(
                    name="get_schema",
                    description="schema",
                    input_schema={"type": "object"},
                    handler=handler,
                    mode=ToolMode.BOTH,
                    side_effect_class=SideEffectClass.READ_ONLY,
                )
            ]
        )

    monkeypatch.setattr(WorkflowToolCatalog, "for_mode", classmethod(catalog))
    script = []
    for index in range(9):
        script.extend(
            [
                tool_call_turn(f"call-{index}", "get_schema", {}),
                text_turn(f"answer-{index}"),
            ]
        )
    script.append(text_turn("Final"))
    provider = FakeProviderClient(script=script)
    agent = runtime(provider)
    await agent.start()
    for index in range(10):
        await collect(agent.process_message_stream(f"request-{index}"))
    messages = provider.requests[-1]["messages"]
    assert len(messages) <= 31
    assert messages[0].role == "user"
    assert messages[0].content[0].text == "request-2"
    calls = {
        part.tool_call.call_id
        for message in messages
        for part in message.content
        if part.tool_call
    }
    results = {message.tool_call_id for message in messages if message.role == "tool"}
    assert calls == results == {f"call-{index}" for index in range(2, 9)}


async def test_manager_stop_invalidates_session_generation_and_revokes_pending_authority():
    from src.services.agent_session_manager import AgentSessionManager

    manager = AgentSessionManager()
    session = manager.get_or_create_session("stopped")
    generation = session.begin_turn_generation()
    session.agent = runtime(FakeProviderClient(script=[]))
    await session.agent.start()
    await manager.stop_session_agent("stopped")
    assert not session.is_turn_generation_active(generation)
    assert session.agent is None


async def test_interrupt_retains_completed_authored_text_without_unfinished_tool_protocol():
    from tests.services.conversation_acceptance import tool_call_turn

    provider = FakeProviderClient(
        script=[
            [
                *text_turn("Completed visible block")[:-1],
                *tool_call_turn("pending", "get_schema", {}),
            ],
            text_turn("Next answer"),
        ]
    )
    agent = runtime(provider)
    await agent.start()
    stream = agent.process_message_stream("Interrupted request")
    assert (await anext(stream))["data"]["text"] == "Completed visible block"
    await agent.interrupt()
    assert await collect(stream) == []
    await collect(agent.process_message_stream("Next request"))
    messages = provider.requests[-1]["messages"]
    assert [(m.role, "".join(p.text for p in m.content)) for m in messages] == [
        ("user", "Interrupted request"),
        ("assistant", "Completed visible block"),
        ("user", "Next request"),
    ]
    assert all(
        part.tool_call is None for message in messages for part in message.content
    )
