"""One provider-neutral turn script rendered onto every provider's wire format.

A scenario is a list of turns; each turn is a list of ``Say`` / ``Call`` /
``Reason`` items. ``build_provider`` renders the same script for the scripted
fake, the Anthropic Messages adapter (httpx ``MockTransport``), the OpenAI SDK
(Responses SSE over ``MockTransport``) and the Gemini SDK (``alt=sse`` over
``MockTransport``), so the acceptance scenarios can assert identical observable
behavior. Only the transport is mocked: the real adapters and SDK clients parse
the bytes. ``Rendered.requests`` holds the JSON bodies the adapter put on the
wire (empty for the scripted fake, which records requests itself).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.services.conversation_runtime.anthropic_provider import (
    AnthropicProviderClient,
)
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.conversation_runtime.gemini_provider import GeminiProviderClient
from src.services.conversation_runtime.models import (
    ProviderStreamEvent,
    ProviderStreamEventType,
    ProviderToolCall,
)
from src.services.conversation_runtime.openai_provider import OpenAIProviderClient

SYNTHETIC_KEY = "sk-synthetic-provider-canary"
PROVIDERS = ("scripted", "anthropic", "openai", "gemini")
# Gemini API function calls normally carry no call id (Call.wire_id opts in,
# as Vertex-style ids do) and never stream partial JSON: args always arrive as
# one complete object per functionCall (``will_continue`` is unsupported by the
# Gemini API), so there is no fragmentation scenario for it.
ID_PROVIDERS = ("scripted", "anthropic", "openai")
FRAGMENTING_PROVIDERS = ("anthropic", "openai")


@dataclass(frozen=True)
class Say:
    text: str


@dataclass(frozen=True)
class Reason:
    """OpenAI reasoning item that must round-trip with its function call."""

    item_id: str = "rs_1"


@dataclass(frozen=True)
class Think:
    """Gemini thought part (never user text), optionally signed."""

    text: str = "private reasoning"
    signature: str | None = None


@dataclass(frozen=True)
class Signed:
    """Gemini signature-only trailing part (empty text + thoughtSignature)."""

    signature: str


@dataclass(frozen=True)
class Call:
    call_id: str
    name: str
    # dict -> valid arguments; str -> raw (possibly malformed) JSON text.
    args: dict[str, Any] | str = field(default_factory=dict)
    fragment_size: int = 9
    # Gemini only: send ``call_id`` as the functionCall id (default: id-less).
    wire_id: bool = False
    # Gemini only: base64 thoughtSignature carried on this call's part.
    signature: str | None = None
    # OpenAI only: arguments in the completed response when they differ from
    # what was streamed (None = identical).
    completed_args: str | None = None
    # OpenAI only: drop the function name on the wire ("both" = streamed events
    # and completed output, "completed" = completed output only).
    nameless: str | None = None
    # Scripted only: hand the runtime a call whose call_id is None.
    no_id: bool = False

    def raw(self) -> str:
        return self.args if isinstance(self.args, str) else json.dumps(self.args)

    def fragments(self) -> list[str]:
        raw = self.raw()
        return [
            raw[i : i + self.fragment_size]
            for i in range(0, len(raw), self.fragment_size)
        ] or [""]


Turn = list[Say | Reason | Call | Think | Signed]


@dataclass
class Rendered:
    provider: Any
    # JSON request bodies actually sent (HTTP providers); empty for scripted.
    requests: list[dict[str, Any]]


def build_provider(
    kind: str, turns: list[Turn | Callable[[dict[str, Any]], Turn]]
) -> Rendered:
    if kind == "scripted":
        if not any(callable(turn) for turn in turns):
            return Rendered(FakeProviderClient(script=_scripted(turns)), [])

        class AdaptiveFake(FakeProviderClient):
            def __init__(self):
                super().__init__(script=[])
                self.turns = list(turns)

            def stream_turn(self, **kwargs):
                turn = self.turns.pop(0)
                self._script.extend(
                    _scripted([turn(kwargs) if callable(turn) else turn])
                )
                return super().stream_turn(**kwargs)

        return Rendered(AdaptiveFake(), [])
    renderers = {
        "anthropic": (_anthropic_body, _anthropic_client),
        "openai": (_openai_body, _openai_client),
        "gemini": (_gemini_body, _gemini_client),
    }
    render, make_client = renderers[kind]
    queue = list(turns)
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        turn = queue.pop(0)
        return httpx.Response(
            200,
            content=render(turn(body) if callable(turn) else turn),
            headers={"content-type": "text/event-stream"},
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Rendered(make_client(http_client), requests)


# ---- scripted ---------------------------------------------------------------


def _scripted(turns: list[Turn]) -> list[list[ProviderStreamEvent]]:
    script: list[list[ProviderStreamEvent]] = []
    for turn in turns:
        events: list[ProviderStreamEvent] = []
        for item in turn:
            if isinstance(item, Say):
                events.append(
                    ProviderStreamEvent(
                        type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                        text=item.text,
                    )
                )
            elif isinstance(item, Call):
                events.append(
                    ProviderStreamEvent(
                        type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
                        tool_call=ProviderToolCall(
                            call_id=None if item.no_id else item.call_id,
                            tool_name=item.name,
                            parsed_input=item.args
                            if isinstance(item.args, dict)
                            else {},
                            raw_arguments=item.raw(),
                        ),
                    )
                )
        events.append(ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE))
        script.append(events)
    return script


# ---- anthropic --------------------------------------------------------------


def _anthropic_client(http_client: httpx.AsyncClient) -> AnthropicProviderClient:
    return AnthropicProviderClient(
        model="claude-haiku-4-5-20251001",
        api_key=SYNTHETIC_KEY,
        http_client=http_client,
    )


def _anthropic_body(turn: Turn) -> bytes:
    events: list[tuple[str, dict[str, Any]]] = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "model": "claude-haiku-4-5-20251001",
                    "usage": {"input_tokens": 11, "output_tokens": 1},
                },
            },
        )
    ]

    def block(index: int, content_block: dict[str, Any]) -> None:
        events.append(
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": content_block,
                },
            )
        )

    def delta(index: int, payload: dict[str, Any]) -> None:
        events.append(
            (
                "content_block_delta",
                {"type": "content_block_delta", "index": index, "delta": payload},
            )
        )

    def stop(index: int) -> None:
        events.append(
            ("content_block_stop", {"type": "content_block_stop", "index": index})
        )

    index = 0
    has_call = False
    for item in turn:
        if isinstance(item, Say):
            block(index, {"type": "text", "text": ""})
            delta(index, {"type": "text_delta", "text": item.text})
            stop(index)
            index += 1
        elif isinstance(item, Call):
            has_call = True
            block(
                index,
                {
                    "type": "tool_use",
                    "id": item.call_id,
                    "name": item.name,
                    "input": {},
                },
            )
            for fragment in item.fragments():
                delta(index, {"type": "input_json_delta", "partial_json": fragment})
            stop(index)
            index += 1
    events.append(
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use" if has_call else "end_turn"},
                "usage": {"output_tokens": 7},
            },
        )
    )
    events.append(("message_stop", {"type": "message_stop"}))
    return _sse(events)


# ---- openai -----------------------------------------------------------------


def _openai_client(http_client: httpx.AsyncClient) -> OpenAIProviderClient:
    from openai import AsyncOpenAI

    return OpenAIProviderClient(
        model="openai:gpt-5-mini",
        client=AsyncOpenAI(api_key=SYNTHETIC_KEY, http_client=http_client),
    )


def _openai_body(turn: Turn) -> bytes:
    response_base = {
        "id": "resp_1",
        "object": "response",
        "model": "gpt-5-mini",
        "created_at": 0,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }
    events: list[dict[str, Any]] = [
        {
            "type": "response.created",
            "response": {**response_base, "status": "in_progress", "output": []},
        }
    ]
    output: list[dict[str, Any]] = []
    for position, item in enumerate(turn):
        if isinstance(item, Reason):
            output.append(
                {"id": item.item_id, "type": "reasoning", "summary": [], "content": []}
            )
        elif isinstance(item, Say):
            events.append(
                {
                    "type": "response.output_text.delta",
                    "item_id": f"msg_{position}",
                    "output_index": position,
                    "content_index": 0,
                    "delta": item.text,
                }
            )
            output.append(
                {
                    "id": f"msg_{position}",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": item.text, "annotations": []}
                    ],
                }
            )
        elif isinstance(item, Call):
            item_id = f"fc_{item.call_id}"
            base = {
                "type": "function_call",
                "id": item_id,
                "call_id": item.call_id,
                "name": item.name,
            }
            streamed_base = (
                {k: v for k, v in base.items() if k != "name"}
                if item.nameless == "both"
                else base
            )
            if item.nameless:
                base = {k: v for k, v in base.items() if k != "name"}
            events.append(
                {
                    "type": "response.output_item.added",
                    "output_index": position,
                    "item": {**streamed_base, "arguments": "", "status": "in_progress"},
                }
            )
            for fragment in item.fragments():
                events.append(
                    {
                        "type": "response.function_call_arguments.delta",
                        "item_id": item_id,
                        "output_index": position,
                        "delta": fragment,
                    }
                )
            events.append(
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": item_id,
                    "output_index": position,
                    **({} if item.nameless == "both" else {"name": item.name}),
                    "arguments": item.raw(),
                }
            )
            output.append(
                {
                    **base,
                    "arguments": item.raw()
                    if item.completed_args is None
                    else item.completed_args,
                    "status": "completed",
                }
            )
    events.append(
        {
            "type": "response.completed",
            "response": {
                **response_base,
                "status": "completed",
                "output": output,
                "usage": {
                    "input_tokens": 11,
                    "output_tokens": 7,
                    "total_tokens": 18,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        }
    )
    for sequence, event in enumerate(events):
        event["sequence_number"] = sequence
    return _sse([(event["type"], event) for event in events])


# ---- gemini -----------------------------------------------------------------


def _gemini_client(http_client: httpx.AsyncClient) -> GeminiProviderClient:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=SYNTHETIC_KEY,
        http_options=types.HttpOptions(httpx_async_client=http_client),
    )
    return GeminiProviderClient(
        model="gemini:gemini-2.5-flash", client=client, http_client=http_client
    )


def _gemini_body(turn: Turn) -> bytes:
    chunks: list[dict[str, Any]] = []
    for item in turn:
        if isinstance(item, Say):
            parts = [{"text": item.text}]
        elif isinstance(item, Think):
            part: dict[str, Any] = {"text": item.text, "thought": True}
            if item.signature:
                part["thoughtSignature"] = item.signature
            parts = [part]
        elif isinstance(item, Signed):
            parts = [{"text": "", "thoughtSignature": item.signature}]
        elif isinstance(item, Call):
            # Malformed values are embedded as-is when they are valid JSON.
            args = item.args if isinstance(item.args, dict) else json.loads(item.args)
            function_call: dict[str, Any] = {"name": item.name, "args": args}
            if item.wire_id:
                function_call["id"] = item.call_id
            part = {"functionCall": function_call}
            if item.signature:
                part["thoughtSignature"] = item.signature
            parts = [part]
        else:
            continue
        chunks.append({"candidates": [{"content": {"role": "model", "parts": parts}}]})
    chunks.append(
        {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": ""}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 11,
                "candidatesTokenCount": 7,
                "totalTokenCount": 18,
            },
        }
    )
    return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks).encode()


def _sse(events: list[tuple[str, dict[str, Any]]]) -> bytes:
    return "".join(
        f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events
    ).encode()


# ---- wire inspection --------------------------------------------------------


def wire_tool_results(kind: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    """Tool results in a provider request body, in order, as ``{key, content}``.

    ``key`` is the call id where the wire carries one, else the function name.
    """
    results: list[dict[str, Any]] = []
    if kind == "anthropic":
        for message in body["messages"]:
            for block in message["content"]:
                if block["type"] == "tool_result":
                    content = block["content"]
                    text = (
                        content
                        if isinstance(content, str)
                        else "".join(part.get("text", "") for part in content)
                    )
                    results.append(
                        {
                            "key": block["tool_use_id"],
                            "content": text,
                            "is_error": bool(block.get("is_error")),
                        }
                    )
    elif kind == "openai":
        for item in body["input"]:
            if item.get("type") == "function_call_output":
                results.append({"key": item["call_id"], "content": item["output"]})
    elif kind == "gemini":
        for content in body["contents"]:
            for part in content["parts"]:
                response = part.get("functionResponse")
                if response:
                    results.append(
                        {
                            "key": response.get("id") or response["name"],
                            "content": json.dumps(response["response"]),
                        }
                    )
    return results
