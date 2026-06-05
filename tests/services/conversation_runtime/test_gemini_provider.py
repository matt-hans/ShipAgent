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
        ("tool", "function_response"),
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
