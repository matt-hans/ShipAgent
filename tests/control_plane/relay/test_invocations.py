from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.control_plane.relay.invocations import (
    NoLiveRelaySession,
    RelayInvocationBroker,
    RelayInvocationTimeout,
)
from src.control_plane.relay.protocol import (
    RelayInvocationEnvelope,
    RelayInvocationResultFrame,
)


class FakeRelayWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_broker_sends_invocation_to_live_session_and_resolves_matching_result() -> (
    None
):
    websocket = FakeRelayWebSocket()
    broker = RelayInvocationBroker()
    await broker.register("relay-session-1", websocket)

    invocation_task = asyncio.create_task(
        broker.invoke(
            relay_session_id="relay-session-1",
            tool_name="get_shipagent_status",
            arguments={"correlation_id": "corr-1"},
            audit_correlation_id="corr-1",
            timeout_seconds=1,
        )
    )
    for _ in range(20):
        if websocket.sent:
            break
        await asyncio.sleep(0)
    assert websocket.sent
    invocation = RelayInvocationEnvelope.model_validate(websocket.sent[0])

    await broker.accept_result(
        RelayInvocationResultFrame(
            type="invocation_result",
            relay_session_id="relay-session-1",
            relay_invocation_id=invocation.relay_invocation_id,
            status="ok",
            result={"status": "ok"},
        )
    )

    result = await invocation_task

    assert invocation.relay_session_id == "relay-session-1"
    assert invocation.sequence == 1
    assert invocation.tool_name == "get_shipagent_status"
    assert invocation.arguments == {"correlation_id": "corr-1"}
    assert invocation.input_hash
    assert invocation.idempotency_key
    assert result.result == {"status": "ok"}


@pytest.mark.asyncio
async def test_broker_unregister_rejects_pending_invocations_with_domain_error() -> (
    None
):
    websocket = FakeRelayWebSocket()
    broker = RelayInvocationBroker()
    await broker.register("relay-session-1", websocket)

    invocation_task = asyncio.create_task(
        broker.invoke(
            relay_session_id="relay-session-1",
            tool_name="get_shipagent_status",
            arguments={},
            audit_correlation_id="corr-1",
            timeout_seconds=10,
        )
    )
    for _ in range(20):
        if websocket.sent:
            break
        await asyncio.sleep(0)
    assert websocket.sent

    await broker.unregister("relay-session-1")

    with pytest.raises(NoLiveRelaySession, match="disconnected"):
        await invocation_task


@pytest.mark.asyncio
async def test_broker_sends_strictly_increasing_per_session_sequences() -> None:
    websocket = FakeRelayWebSocket()
    broker = RelayInvocationBroker()
    await broker.register("relay-session-1", websocket)

    first_task = asyncio.create_task(
        broker.invoke(
            relay_session_id="relay-session-1",
            tool_name="get_shipagent_status",
            arguments={},
            audit_correlation_id="corr-1",
            timeout_seconds=1,
        )
    )
    for _ in range(20):
        if len(websocket.sent) == 1:
            break
        await asyncio.sleep(0)
    first_invocation = RelayInvocationEnvelope.model_validate(websocket.sent[0])
    await broker.accept_result(
        RelayInvocationResultFrame(
            type="invocation_result",
            relay_session_id="relay-session-1",
            relay_invocation_id=first_invocation.relay_invocation_id,
            status="ok",
            result={"status": "ok"},
        )
    )
    await first_task

    second_task = asyncio.create_task(
        broker.invoke(
            relay_session_id="relay-session-1",
            tool_name="get_shipagent_status",
            arguments={},
            audit_correlation_id="corr-2",
            timeout_seconds=1,
        )
    )
    for _ in range(20):
        if len(websocket.sent) == 2:
            break
        await asyncio.sleep(0)
    second_invocation = RelayInvocationEnvelope.model_validate(websocket.sent[1])
    await broker.accept_result(
        RelayInvocationResultFrame(
            type="invocation_result",
            relay_session_id="relay-session-1",
            relay_invocation_id=second_invocation.relay_invocation_id,
            status="ok",
            result={"status": "ok"},
        )
    )
    await second_task

    assert first_invocation.sequence == 1
    assert second_invocation.sequence == 2


@pytest.mark.asyncio
async def test_broker_unregister_clears_session_sequence_state() -> None:
    first_websocket = FakeRelayWebSocket()
    broker = RelayInvocationBroker()
    await broker.register("relay-session-1", first_websocket)

    first_task = asyncio.create_task(
        broker.invoke(
            relay_session_id="relay-session-1",
            tool_name="get_shipagent_status",
            arguments={},
            audit_correlation_id="corr-1",
            timeout_seconds=1,
        )
    )
    for _ in range(20):
        if first_websocket.sent:
            break
        await asyncio.sleep(0)
    first_invocation = RelayInvocationEnvelope.model_validate(first_websocket.sent[0])
    await broker.accept_result(
        RelayInvocationResultFrame(
            type="invocation_result",
            relay_session_id="relay-session-1",
            relay_invocation_id=first_invocation.relay_invocation_id,
            status="ok",
            result={"status": "ok"},
        )
    )
    await first_task
    await broker.unregister("relay-session-1")

    second_websocket = FakeRelayWebSocket()
    await broker.register("relay-session-1", second_websocket)
    second_task = asyncio.create_task(
        broker.invoke(
            relay_session_id="relay-session-1",
            tool_name="get_shipagent_status",
            arguments={},
            audit_correlation_id="corr-2",
            timeout_seconds=1,
        )
    )
    for _ in range(20):
        if second_websocket.sent:
            break
        await asyncio.sleep(0)
    second_invocation = RelayInvocationEnvelope.model_validate(second_websocket.sent[0])
    await broker.accept_result(
        RelayInvocationResultFrame(
            type="invocation_result",
            relay_session_id="relay-session-1",
            relay_invocation_id=second_invocation.relay_invocation_id,
            status="ok",
            result={"status": "ok"},
        )
    )
    await second_task

    assert first_invocation.sequence == 1
    assert second_invocation.sequence == 1


@pytest.mark.asyncio
async def test_broker_rejects_invocation_without_live_session() -> None:
    broker = RelayInvocationBroker()

    with pytest.raises(NoLiveRelaySession):
        await broker.invoke(
            relay_session_id="relay-session-1",
            tool_name="get_shipagent_status",
            arguments={},
            audit_correlation_id="corr-1",
            timeout_seconds=1,
        )


@pytest.mark.asyncio
async def test_broker_ignores_nonmatching_result_and_times_out_cleanly() -> None:
    websocket = FakeRelayWebSocket()
    broker = RelayInvocationBroker()
    await broker.register("relay-session-1", websocket)

    invocation_task = asyncio.create_task(
        broker.invoke(
            relay_session_id="relay-session-1",
            tool_name="get_shipagent_status",
            arguments={},
            audit_correlation_id="corr-1",
            timeout_seconds=0.01,
        )
    )
    for _ in range(20):
        if websocket.sent:
            break
        await asyncio.sleep(0)
    assert websocket.sent
    invocation = RelayInvocationEnvelope.model_validate(websocket.sent[0])
    await broker.accept_result(
        RelayInvocationResultFrame(
            type="invocation_result",
            relay_session_id="relay-session-1",
            relay_invocation_id=f"{invocation.relay_invocation_id}-wrong",
            status="ok",
            result={"status": "ok"},
        )
    )

    with pytest.raises(RelayInvocationTimeout):
        await invocation_task
