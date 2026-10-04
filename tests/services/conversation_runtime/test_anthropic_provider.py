"""Adapter-only contract tests for the Anthropic Messages provider."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.services.conversation_runtime.anthropic_provider import (
    EMPTY_RESPONSE_MESSAGE,
    PROTOCOL_ERROR_MESSAGE,
    TRANSPORT_ERROR_MESSAGE,
    AnthropicProviderClient,
    resolve_anthropic_model,
    to_anthropic_messages,
)
from src.services.conversation_runtime.models import (
    ProviderContentPart,
    ProviderInputMessage,
    ProviderStreamEvent,
    ProviderStreamEventType,
    ProviderSystemInstruction,
    ProviderToolCall,
    ProviderToolDeclaration,
)

SECRET = "sk-ant-SECRET-canary"
T = ProviderStreamEventType


def sse(*events: tuple[str, dict[str, Any]]) -> bytes:
    return "".join(
        f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events
    ).encode()


def message_start(usage: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    return (
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "model": "claude-haiku-4-5-20251001",
                "usage": usage or {"input_tokens": 11, "output_tokens": 1},
            },
        },
    )


def block_start(index: int, block: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return (
        "content_block_start",
        {"type": "content_block_start", "index": index, "content_block": block},
    )


def delta(index: int, d: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return (
        "content_block_delta",
        {"type": "content_block_delta", "index": index, "delta": d},
    )


def text_delta(index: int, text: str) -> tuple[str, dict[str, Any]]:
    return delta(index, {"type": "text_delta", "text": text})


def json_delta(index: int, fragment: str) -> tuple[str, dict[str, Any]]:
    return delta(index, {"type": "input_json_delta", "partial_json": fragment})


def stop(index: int) -> tuple[str, dict[str, Any]]:
    return ("content_block_stop", {"type": "content_block_stop", "index": index})


def message_end(reason: str = "end_turn", out: int = 7) -> list[tuple[str, dict]]:
    return [
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": reason},
                "usage": {"output_tokens": out},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]


TEXT_BLOCK = block_start(0, {"type": "text", "text": ""})
TOOL_BLOCK = block_start(
    1, {"type": "tool_use", "id": "toolu_1", "name": "get_schema", "input": {}}
)


def make_client(
    handler, *, model: str | None = None
) -> tuple[AnthropicProviderClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = AnthropicProviderClient(
        model=model,
        api_key=SECRET,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(wrapped)),
    )
    return client, seen


def ok(body: bytes) -> Any:
    return lambda _r: httpx.Response(
        200, content=body, headers={"content-type": "text/event-stream"}
    )


async def collect(
    client: AnthropicProviderClient,
    messages: list[ProviderInputMessage] | None = None,
    tools: list[ProviderToolDeclaration] | None = None,
) -> list[ProviderStreamEvent]:
    return [
        event
        async for event in client.stream_turn(
            messages=messages
            or [
                ProviderInputMessage(
                    role="user", content=[ProviderContentPart(text="hi")]
                )
            ],
            system_instructions=[ProviderSystemInstruction(content="be brief")],
            tools=tools or [],
        )
    ]


def types(events: list[ProviderStreamEvent]) -> list[ProviderStreamEventType]:
    return [e.type for e in events]


def user(text: str) -> ProviderInputMessage:
    return ProviderInputMessage(role="user", content=[ProviderContentPart(text=text)])


# ---- request translation ----------------------------------------------------


async def test_request_carries_auth_system_history_and_tools() -> None:
    client, seen = make_client(
        ok(
            sse(
                message_start(),
                TEXT_BLOCK,
                text_delta(0, "ok"),
                stop(0),
                *message_end(),
            )
        )
    )
    tool = ProviderToolDeclaration(
        name="get_schema",
        description="Schema",
        input_schema={"type": "object", "properties": {"s": {"type": "string"}}},
    )
    await collect(
        client,
        messages=[
            user("first"),
            ProviderInputMessage(
                role="assistant", content=[ProviderContentPart(text="a")]
            ),
            user("second"),
        ],
        tools=[tool],
    )

    [request] = seen
    assert request.url == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == SECRET
    assert request.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(request.content)
    assert body["stream"] is True
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert body["max_tokens"] > 0
    assert body["system"] == "be brief"
    assert body["tools"] == [
        {
            "name": "get_schema",
            "description": "Schema",
            "input_schema": {"type": "object", "properties": {"s": {"type": "string"}}},
        }
    ]
    assert body["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "first"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "a"}]},
        {"role": "user", "content": [{"type": "text", "text": "second"}]},
    ]


def test_tool_use_and_results_translate_with_matching_ids_and_merge() -> None:
    def call(cid: str) -> ProviderContentPart:
        return ProviderContentPart(
            type="tool_call",
            tool_call=ProviderToolCall(
                call_id=cid, tool_name="t", parsed_input={"k": cid}
            ),
        )

    def result(cid: str, err: bool = False) -> ProviderInputMessage:
        return ProviderInputMessage(
            role="tool",
            content=[ProviderContentPart(text=f"r-{cid}")],
            tool_call_id=cid,
            metadata={"is_error": err},
        )

    out = to_anthropic_messages(
        [
            user("go"),
            ProviderInputMessage(
                role="assistant",
                content=[ProviderContentPart(text="calling"), call("a"), call("b")],
            ),
            result("a"),
            result("b", err=True),
        ]
    )

    assert out[1]["content"][1:] == [
        {"type": "tool_use", "id": "a", "name": "t", "input": {"k": "a"}},
        {"type": "tool_use", "id": "b", "name": "t", "input": {"k": "b"}},
    ]
    assert out[2] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "a", "content": "r-a"},
            {
                "type": "tool_result",
                "tool_use_id": "b",
                "content": "r-b",
                "is_error": True,
            },
        ],
    }


def test_empty_text_and_idless_calls_are_not_sent() -> None:
    out = to_anthropic_messages(
        [
            ProviderInputMessage(role="user", content=[ProviderContentPart(text="")]),
            user("real"),
            ProviderInputMessage(
                role="assistant",
                content=[
                    ProviderContentPart(text=""),
                    ProviderContentPart(
                        type="tool_call",
                        tool_call=ProviderToolCall(
                            call_id=None, tool_name="t", parsed_input={}
                        ),
                    ),
                ],
            ),
        ]
    )
    assert out == [{"role": "user", "content": [{"type": "text", "text": "real"}]}]


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (None, "claude-haiku-4-5-20251001"),
        ("anthropic:default", "claude-haiku-4-5-20251001"),
        ("anthropic:claude-sonnet-5-5", "claude-sonnet-5-5"),
        ("claude-opus-5-5", "claude-opus-5-5"),
    ],
)
def test_model_resolution(given: str | None, expected: str) -> None:
    assert resolve_anthropic_model(given) == expected


def test_missing_api_key_is_actionable_and_does_not_read_ambient_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicProviderClient(model=None, api_key=None)


# ---- stream normalization ---------------------------------------------------


async def test_text_stream_normalizes_deltas_completion_stop_reason_and_usage() -> None:
    client, _ = make_client(
        ok(
            sse(
                message_start(),
                ("ping", {"type": "ping"}),
                TEXT_BLOCK,
                text_delta(0, "Hel"),
                text_delta(0, "lo"),
                stop(0),
                *message_end("end_turn", out=9),
            )
        )
    )

    events = await collect(client)

    assert types(events) == [
        T.TEXT_DELTA,
        T.TEXT_DELTA,
        T.RESULT_METADATA,
        T.TEXT_BLOCK_COMPLETE,
        T.STREAM_COMPLETE,
    ]
    assert [e.text for e in events[:2]] == ["Hel", "lo"]
    assert events[3].text == "Hello"
    meta = events[2].metadata
    assert meta.provider == "anthropic"
    assert meta.session_id == "msg_1"
    assert meta.stop_reason == "end_turn"
    assert meta.usage["input_tokens"] == 11
    assert meta.usage["output_tokens"] == 9  # cumulative from message_delta


async def test_tool_use_assembles_fragmented_json_with_stable_id() -> None:
    client, _ = make_client(
        ok(
            sse(
                message_start(),
                TOOL_BLOCK,
                json_delta(1, ""),
                json_delta(1, '{"sour'),
                json_delta(1, 'ce": "ord'),
                json_delta(1, 'ers"}'),
                stop(1),
                *message_end("tool_use"),
            )
        )
    )

    events = await collect(client)

    [started] = [e for e in events if e.type == T.TOOL_CALL_STARTED]
    [done] = [e for e in events if e.type == T.TOOL_CALL_COMPLETE]
    assert started.tool_call.call_id == "toolu_1"
    assert done.tool_call.call_id == "toolu_1"
    assert done.tool_call.tool_name == "get_schema"
    assert done.tool_call.parsed_input == {"source": "orders"}
    assert done.tool_call.raw_arguments == '{"source": "orders"}'
    meta = next(e for e in events if e.type == T.RESULT_METADATA).metadata
    assert meta.stop_reason == "tool_use"
    assert events[-1].type == T.STREAM_COMPLETE
    assert not any(e.type == T.TEXT_BLOCK_COMPLETE for e in events)


async def test_text_then_multiple_tool_calls_preserve_order_and_ids() -> None:
    client, _ = make_client(
        ok(
            sse(
                message_start(),
                TEXT_BLOCK,
                text_delta(0, "Checking"),
                stop(0),
                block_start(
                    1, {"type": "tool_use", "id": "toolu_a", "name": "a", "input": {}}
                ),
                json_delta(1, '{"x":1}'),
                block_start(
                    2, {"type": "tool_use", "id": "toolu_b", "name": "b", "input": {}}
                ),
                json_delta(2, "{}"),
                stop(1),
                stop(2),
                *message_end("tool_use"),
            )
        )
    )

    events = await collect(client)

    calls = [e.tool_call for e in events if e.type == T.TOOL_CALL_COMPLETE]
    assert [(c.call_id, c.tool_name, c.parsed_input) for c in calls] == [
        ("toolu_a", "a", {"x": 1}),
        ("toolu_b", "b", {}),
    ]
    assert any(e.type == T.TEXT_BLOCK_COMPLETE and e.text == "Checking" for e in events)


async def test_tool_use_without_arguments_yields_empty_object() -> None:
    client, _ = make_client(
        ok(sse(message_start(), TOOL_BLOCK, stop(1), *message_end("tool_use")))
    )
    events = await collect(client)
    [done] = [e for e in events if e.type == T.TOOL_CALL_COMPLETE]
    assert done.tool_call.parsed_input == {}


async def test_thinking_blocks_are_not_surfaced() -> None:
    client, _ = make_client(
        ok(
            sse(
                message_start(),
                block_start(0, {"type": "thinking", "thinking": ""}),
                delta(0, {"type": "thinking_delta", "thinking": "secret thoughts"}),
                delta(0, {"type": "signature_delta", "signature": "sig"}),
                stop(0),
                block_start(1, {"type": "text", "text": ""}),
                text_delta(1, "answer"),
                stop(1),
                *message_end(),
            )
        )
    )
    events = await collect(client)
    assert "secret thoughts" not in repr(events)
    assert [e.text for e in events if e.type == T.TEXT_BLOCK_COMPLETE] == ["answer"]


# ---- empty responses and protocol errors -----------------------------------


async def test_empty_response_is_an_actionable_provider_error() -> None:
    client, _ = make_client(ok(sse(message_start(), *message_end("end_turn", out=0))))
    events = await collect(client)
    assert types(events) == [T.PROVIDER_ERROR]
    assert events[0].safe_error_message == EMPTY_RESPONSE_MESSAGE


async def test_empty_text_block_only_is_empty_response() -> None:
    client, _ = make_client(
        ok(sse(message_start(), TEXT_BLOCK, stop(0), *message_end()))
    )
    events = await collect(client)
    assert [e.safe_error_message for e in events] == [EMPTY_RESPONSE_MESSAGE]


@pytest.mark.parametrize(
    "body",
    [
        # malformed tool arguments are rejected before any call is emitted
        sse(
            message_start(),
            TOOL_BLOCK,
            json_delta(1, '{"a": '),
            stop(1),
            *message_end(),
        ),
        # arguments that are valid JSON but not an object
        sse(message_start(), TOOL_BLOCK, json_delta(1, "[1]"), stop(1), *message_end()),
        # delta for a block that never started
        sse(message_start(), text_delta(3, "x"), *message_end()),
        # text delta on a tool block
        sse(message_start(), TOOL_BLOCK, text_delta(1, "x"), stop(1), *message_end()),
        # tool_use block with no id
        sse(
            message_start(),
            block_start(1, {"type": "tool_use", "name": "t", "input": {}}),
            stop(1),
            *message_end(),
        ),
        # content before message_start
        sse(TEXT_BLOCK, text_delta(0, "x")),
        # stream truncated before message_stop
        sse(message_start(), TEXT_BLOCK, text_delta(0, "partial")),
        # message_stop with an unclosed block
        sse(
            message_start(),
            TEXT_BLOCK,
            text_delta(0, "x"),
            ("message_stop", {"type": "message_stop"}),
        ),
        # undecodable event data
        b"event: message_start\ndata: {not json\n\n",
        # empty body
        b"",
    ],
)
async def test_protocol_errors_end_in_safe_provider_error(body: bytes) -> None:
    client, _ = make_client(ok(body))
    events = await collect(client)
    assert events[-1].type == T.PROVIDER_ERROR
    assert events[-1].safe_error_message == PROTOCOL_ERROR_MESSAGE
    assert not any(e.type == T.TOOL_CALL_COMPLETE for e in events)
    assert not any(e.type == T.STREAM_COMPLETE for e in events)


@pytest.mark.parametrize(
    ("error_type", "needle"),
    [
        ("overloaded_error", "temporarily unavailable"),
        ("rate_limit_error", "rate limit"),
        ("authentication_error", "ANTHROPIC_API_KEY"),
        ("invalid_request_error", "rejected the request"),
        ("something_new", "protocol error"),
    ],
)
async def test_stream_error_event_maps_to_safe_message(
    error_type: str, needle: str
) -> None:
    leaky = f"internal detail {SECRET}"
    client, _ = make_client(
        ok(
            sse(
                message_start(),
                TEXT_BLOCK,
                text_delta(0, "partial"),
                (
                    "error",
                    {"type": "error", "error": {"type": error_type, "message": leaky}},
                ),
            )
        )
    )
    events = await collect(client)
    assert events[-1].type == T.PROVIDER_ERROR
    assert needle in events[-1].safe_error_message
    assert leaky not in repr(events)
    assert SECRET not in repr(events)
    assert not any(e.type == T.STREAM_COMPLETE for e in events)


# ---- HTTP / transport failures ---------------------------------------------


@pytest.mark.parametrize(
    ("status", "error_type", "needle"),
    [
        (401, "authentication_error", "ANTHROPIC_API_KEY"),
        (403, "permission_error", "ANTHROPIC_API_KEY"),
        (404, "not_found_error", "claude-haiku-4-5-20251001"),
        (400, "invalid_request_error", "rejected the request"),
        (429, "rate_limit_error", "rate limit"),
        (500, "api_error", "temporarily unavailable"),
        (529, "overloaded_error", "temporarily unavailable"),
    ],
)
async def test_http_errors_are_safe_and_actionable(
    status: int, error_type: str, needle: str
) -> None:
    leaky = f"echo of key {SECRET} and prompt body"
    client, _ = make_client(
        lambda _r: httpx.Response(
            status,
            json={"type": "error", "error": {"type": error_type, "message": leaky}},
        )
    )
    events = await collect(client)
    assert types(events) == [T.PROVIDER_ERROR]
    assert needle in events[0].safe_error_message
    assert SECRET not in repr(events)
    assert "prompt body" not in repr(events)


async def test_non_json_http_error_body_is_safe() -> None:
    client, _ = make_client(
        lambda _r: httpx.Response(502, text=f"<html>{SECRET}</html>")
    )
    events = await collect(client)
    assert types(events) == [T.PROVIDER_ERROR]
    assert SECRET not in repr(events)


async def test_connect_failure_is_transport_error_without_fallback() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect {SECRET}", request=request)

    client, seen = make_client(boom)
    events = await collect(client)
    assert types(events) == [T.PROVIDER_ERROR]
    assert events[0].safe_error_message == TRANSPORT_ERROR_MESSAGE
    assert SECRET not in repr(events)
    assert len(seen) == 1  # no retry against another host/provider


async def test_mid_stream_disconnect_is_transport_error() -> None:
    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield sse(message_start(), TEXT_BLOCK, text_delta(0, "par"))
            raise httpx.ReadError("connection reset")

    client, _ = make_client(lambda _r: httpx.Response(200, stream=Broken()))
    events = await collect(client)
    assert events[-1].type == T.PROVIDER_ERROR
    assert events[-1].safe_error_message == TRANSPORT_ERROR_MESSAGE


async def test_cancel_with_no_active_stream_is_a_noop() -> None:
    client, _ = make_client(ok(b""))
    await client.cancel()
    assert client.capabilities.supports_cancellation is True


async def test_cancel_mid_stream_closes_response_and_emits_no_later_deltas() -> None:
    first = sse(message_start(), TEXT_BLOCK, text_delta(0, "early"))
    late = sse(text_delta(0, "LATE"), stop(0), *message_end())
    closed = asyncio.Event()
    release_late = asyncio.Event()

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield first
            await release_late.wait()
            yield late

        async def aclose(self) -> None:
            closed.set()

    client, _ = make_client(
        lambda _r: httpx.Response(
            200, stream=Body(), headers={"content-type": "text/event-stream"}
        )
    )
    stream = client.stream_turn(
        messages=[
            ProviderInputMessage(role="user", content=[ProviderContentPart(text="hi")])
        ],
        system_instructions=[],
        tools=[],
    )
    seen: list[ProviderStreamEvent] = []
    async with asyncio.timeout(5):
        async for event in stream:
            seen.append(event)
            if event.type == T.TEXT_DELTA:
                await client.cancel()
                assert closed.is_set()  # response really closed, not just flagged
                release_late.set()  # the transport would now deliver more data
    assert [e.text for e in seen if e.type == T.TEXT_DELTA] == ["early"]
    assert not any(e.type == T.STREAM_COMPLETE for e in seen)
    assert all(e.text != "LATE" for e in seen)
    assert client._active_response is None


async def test_max_tokens_stop_reason_is_metadata_only_like_other_providers() -> None:
    # Contract (see _parse_stream): truncation is surfaced via ResultMetadata
    # stop_reason, not a new UI event; the OpenAI adapter does the same.
    client, _ = make_client(
        ok(
            sse(
                message_start(),
                TEXT_BLOCK,
                text_delta(0, "cut off"),
                stop(0),
                *message_end("max_tokens"),
            )
        )
    )

    events = await collect(client)

    meta = next(e.metadata for e in events if e.type == T.RESULT_METADATA)
    assert meta.stop_reason == "max_tokens"
    assert events[-1].type == T.STREAM_COMPLETE


# ---- boundary ---------------------------------------------------------------


def test_adapter_imports_no_sdk_workflow_or_carrier_modules() -> None:
    code = (
        "import sys\n"
        "import src.services.conversation_runtime.anthropic_provider\n"
        "bad = [m for m in sys.modules if m.split('.')[0] == 'claude_agent_sdk' "
        "or m.startswith(('src.orchestrator', 'src.services.batch', "
        "'src.services.ups', 'src.mcp'))]\n"
        "print(bad)\n"
        "sys.exit(1 if bad else 0)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[3],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_core_workflow_services_do_not_import_anthropic_transport() -> None:
    root = Path(__file__).resolve().parents[3] / "src"
    allowed = {root / "services/conversation_runtime/anthropic_provider.py"}
    offenders = []
    for path in root.rglob("*.py"):
        if path in allowed:
            continue
        text = path.read_text()
        if "anthropic_provider" in text and path.name != "conversation_agent.py":
            offenders.append(str(path))
    assert offenders == []
