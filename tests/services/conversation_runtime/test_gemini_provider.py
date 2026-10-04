from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.services.conversation_runtime.gemini_provider import (
    GeminiProviderClient,
    to_gemini_config,
    to_gemini_contents,
)
from src.services.conversation_runtime.models import (
    ProviderContentPart,
    ProviderInputMessage,
    ProviderStreamEventType,
    ProviderSystemInstruction,
    ProviderToolCall,
    ProviderToolDeclaration,
)


class FakePart:
    def __init__(
        self,
        *,
        kind: str,
        text: str | None = None,
        name: str | None = None,
        args: dict | None = None,
        response: dict | None = None,
    ) -> None:
        self.kind = kind
        self.text = text
        self.name = name
        self.args = args
        self.response = response

    @classmethod
    def from_text(cls, *, text: str):
        return cls(kind="text", text=text)

    @classmethod
    def from_function_call(cls, *, name: str, args: dict):
        return cls(kind="function_call", name=name, args=args)

    @classmethod
    def from_function_response(cls, *, name: str, response: dict):
        return cls(kind="function_response", name=name, response=response)


class FakeContent:
    def __init__(self, *, role: str, parts: list[FakePart]) -> None:
        self.role = role
        self.parts = parts


class FakeFunctionDeclaration:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class FakeTool:
    def __init__(self, *, function_declarations: list[FakeFunctionDeclaration]):
        self.function_declarations = function_declarations


class FakeGenerateContentConfig:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


@pytest.fixture
def fake_gemini_types(monkeypatch: pytest.MonkeyPatch):
    from src.services.conversation_runtime import gemini_provider

    fake_types = SimpleNamespace(
        Part=FakePart,
        Content=FakeContent,
        FunctionDeclaration=FakeFunctionDeclaration,
        Tool=FakeTool,
        GenerateContentConfig=FakeGenerateContentConfig,
    )
    monkeypatch.setattr(gemini_provider, "types", fake_types)
    return fake_types


def test_gemini_contents_pair_model_function_call_with_tool_response(
    fake_gemini_types,
) -> None:
    _ = fake_gemini_types
    call = ProviderToolCall(
        call_id=None,
        tool_name="get_schema",
        parsed_input={"source": "orders"},
    )

    contents = to_gemini_contents(
        [
            ProviderInputMessage(
                role="user",
                content=[ProviderContentPart(text="Show schema")],
            ),
            ProviderInputMessage(
                role="assistant",
                content=[ProviderContentPart(type="tool_call", tool_call=call)],
            ),
            ProviderInputMessage(
                role="tool",
                content=[ProviderContentPart(text="Schema ready")],
                metadata={
                    "tool_name": "get_schema",
                    "structured_payload": {"columns": ["sku"]},
                    "is_error": False,
                },
            ),
        ]
    )

    assert [(content.role, content.parts[0].kind) for content in contents] == [
        ("user", "text"),
        ("model", "function_call"),
        ("user", "function_response"),
    ]
    assert contents[1].parts[0].name == "get_schema"
    assert contents[1].parts[0].args == {"source": "orders"}
    assert contents[2].parts[0].response == {
        "content": "Schema ready",
        "structured_payload": {"columns": ["sku"]},
    }


def test_gemini_config_declares_function_tools(fake_gemini_types) -> None:
    _ = fake_gemini_types

    config = to_gemini_config(
        [ProviderSystemInstruction(content="system")],
        [
            ProviderToolDeclaration(
                name="get_schema",
                description="Read schema",
                input_schema={"type": "object"},
            )
        ],
    )

    assert config.kwargs["system_instruction"] == "system"
    declaration = config.kwargs["tools"][0].function_declarations[0]
    assert declaration.kwargs == {
        "name": "get_schema",
        "description": "Read schema",
        "parameters_json_schema": {"type": "object"},
    }


@pytest.mark.asyncio
async def test_gemini_stream_normalizes_text_and_function_call(
    fake_gemini_types,
) -> None:
    _ = fake_gemini_types

    class FakeStream:
        async def __aiter__(self):
            yield SimpleNamespace(
                text="",
                function_calls=[
                    SimpleNamespace(name="get_schema", args={"source": "orders"})
                ],
            )
            yield SimpleNamespace(text="Done", function_calls=[])

    class FakeModels:
        async def generate_content_stream(self, **kwargs):
            self.kwargs = kwargs
            return FakeStream()

    fake_models = FakeModels()
    client = SimpleNamespace(aio=SimpleNamespace(models=fake_models))
    provider = GeminiProviderClient(model="gemini:gemini-2.5-flash", client=client)

    events = [
        event
        async for event in provider.stream_turn(
            messages=[
                ProviderInputMessage(
                    role="user",
                    content=[ProviderContentPart(text="Show schema")],
                )
            ],
            system_instructions=[],
            tools=[],
        )
    ]

    tool_event = next(
        event
        for event in events
        if event.type == ProviderStreamEventType.TOOL_CALL_COMPLETE
    )
    text_event = next(
        event
        for event in events
        if event.type == ProviderStreamEventType.TEXT_BLOCK_COMPLETE
    )
    assert tool_event.tool_call.tool_name == "get_schema"
    assert tool_event.tool_call.parsed_input == {"source": "orders"}
    assert text_event.text == "Done"
    assert fake_models.kwargs["model"] == "gemini-2.5-flash"


# ---- real SDK types: continuation, grouping, malformed calls -------------------


def _real_stream_client(chunks: list):
    class Stream:
        async def __aiter__(self):
            for chunk in chunks:
                yield chunk

    class Models:
        async def generate_content_stream(self, **kwargs):
            return Stream()

    return GeminiProviderClient(
        model="gemini:gemini-2.5-flash",
        client=SimpleNamespace(aio=SimpleNamespace(models=Models())),
    )


async def _drain_gemini(provider: GeminiProviderClient) -> list:
    return [
        event
        async for event in provider.stream_turn(
            messages=[
                ProviderInputMessage(
                    role="user", content=[ProviderContentPart(text="hi")]
                )
            ],
            system_instructions=[],
            tools=[],
        )
    ]


def _chunk(*parts: dict) -> SimpleNamespace:
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=list(parts)))]
    )


@pytest.mark.parametrize(
    "args", [[1, 2], "text", 7, ("a",)], ids=["list", "str", "int", "tuple"]
)
async def test_non_object_function_arguments_end_in_safe_error_without_a_call(
    args,
) -> None:
    from src.services.conversation_runtime.gemini_provider import (
        MALFORMED_ARGUMENTS_MESSAGE,
    )

    provider = _real_stream_client(
        [
            _chunk(
                {"function_call": {"name": "ok", "args": {"a": 1}}},
                {"function_call": {"name": "get_platform_status", "args": args}},
            )
        ]
    )

    events = await _drain_gemini(provider)

    assert events[-1].type == ProviderStreamEventType.PROVIDER_ERROR
    assert events[-1].safe_error_message == MALFORMED_ARGUMENTS_MESSAGE
    assert ProviderStreamEventType.STREAM_COMPLETE not in {e.type for e in events}


@pytest.mark.parametrize(
    "function_call",
    [
        {"name": "", "args": {}},
        {"args": {}},
        {"name": "x", "args": {}, "will_continue": True},
        {"name": "x", "partial_args": [{"json_path": "$.a", "string_value": "p"}]},
    ],
    ids=["empty-name", "no-name", "partial-call", "partial-args"],
)
async def test_incomplete_function_calls_fail_closed(function_call: dict) -> None:
    provider = _real_stream_client([_chunk({"function_call": function_call})])

    events = await _drain_gemini(provider)

    assert events[-1].type == ProviderStreamEventType.PROVIDER_ERROR
    assert all(e.tool_call is None for e in events[:-1] if e.tool_call)


async def test_absent_function_arguments_still_mean_empty_input() -> None:
    provider = _real_stream_client(
        [_chunk({"function_call": {"name": "get_platform_status"}})]
    )

    events = await _drain_gemini(provider)

    [call] = [e.tool_call for e in events if e.tool_call is not None]
    assert call.parsed_input == {}


async def test_signed_parts_survive_stream_to_request_as_exact_bytes() -> None:
    from google.genai import types

    signature = b"\x00\xff\x10opaque-signature\x80"
    provider = _real_stream_client(
        [
            _chunk(
                types.Part(text="plan", thought=True, thought_signature=b"t-sig"),
            ),
            _chunk(types.Part(text="Looking.")),
            _chunk(
                types.Part(
                    function_call=types.FunctionCall(name="a", args={"n": 1}),
                    thought_signature=signature,
                ),
                types.Part(function_call=types.FunctionCall(name="a", args={"n": 1})),
            ),
        ]
    )

    events = await _drain_gemini(provider)

    # Thought text is never surfaced as user text.
    texts = [e.text for e in events if e.type == ProviderStreamEventType.TEXT_DELTA]
    assert texts == ["Looking."]
    calls = [e.tool_call for e in events if e.tool_call is not None]
    # Two id-less identical calls stay two distinct calls with distinct ids.
    assert len({c.call_id for c in calls}) == 2
    items = [e.provider_output_item for e in events if e.provider_output_item]
    assert [i.provider for i in items] == ["gemini"]

    assistant = ProviderInputMessage(
        role="assistant",
        content=[
            ProviderContentPart(
                type="provider_output_item", provider_output_item=items[0]
            ),
            ProviderContentPart(text="Looking."),
            *(ProviderContentPart(type="tool_call", tool_call=c) for c in calls),
        ],
    )
    results = [
        ProviderInputMessage(
            role="tool",
            tool_call_id=c.call_id,
            content=[ProviderContentPart(text="r")],
            metadata={"tool_name": "a"},
        )
        for c in calls
    ]

    contents = to_gemini_contents([assistant, *results])

    assert [c.role for c in contents] == ["model", "user"]
    model_parts = contents[0].parts
    assert [bool(p.thought) for p in model_parts] == [True, False, False, False]
    assert model_parts[0].thought_signature == b"t-sig"
    assert model_parts[2].thought_signature == signature
    assert model_parts[3].thought_signature is None
    assert [p.text for p in model_parts if p.text] == ["plan", "Looking."]
    assert len(contents[1].parts) == 2


def test_replay_omits_a_call_the_runtime_did_not_dispatch() -> None:
    from google.genai import types

    item_parts = [
        {"function_call": {"id": "g1", "name": "a", "args": {}}},
        {"function_call": {"id": "g2", "name": "a", "args": {}}},
    ]
    from src.services.conversation_runtime.models import ProviderOutputItem

    kept = ProviderToolCall(
        call_id="g2",
        tool_name="a",
        parsed_input={},
        metadata={"provider_call_id": "g2"},
    )
    assistant = ProviderInputMessage(
        role="assistant",
        content=[
            ProviderContentPart(
                type="provider_output_item",
                provider_output_item=ProviderOutputItem(
                    provider="gemini",
                    item={"parts": item_parts, "call_ids": ["g1", "g2"]},
                ),
            ),
            ProviderContentPart(type="tool_call", tool_call=kept),
        ],
    )
    tool = ProviderInputMessage(
        role="tool",
        tool_call_id="g2",
        content=[ProviderContentPart(text="r")],
        metadata={"tool_name": "a"},
    )

    contents = to_gemini_contents([assistant, tool])

    assert [p.function_call.id for p in contents[0].parts] == ["g2"]
    assert contents[1].parts[0].function_response.id == "g2"
    assert isinstance(contents[0].parts[0], types.Part)


async def test_stream_failure_logs_only_the_exception_type(caplog) -> None:
    canary = "CANARY-ACCT-0042-jane@example.com"

    class Models:
        async def generate_content_stream(self, **_kwargs):
            raise RuntimeError(canary)

    provider = GeminiProviderClient(
        model="gemini:gemini-2.5-flash",
        client=SimpleNamespace(aio=SimpleNamespace(models=Models())),
    )

    with caplog.at_level("WARNING"), pytest.raises(RuntimeError):
        await _drain_gemini(provider)

    assert "RuntimeError" in caplog.text
    assert canary not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
