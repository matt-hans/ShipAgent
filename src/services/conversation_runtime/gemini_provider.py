from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

from src.services.conversation_runtime.models import (
    ProviderCapabilities,
    ProviderInputMessage,
    ProviderResultMetadata,
    ProviderStreamEvent,
    ProviderStreamEventType,
    ProviderSystemInstruction,
    ProviderToolCall,
    ProviderToolDeclaration,
)

try:
    from google import genai
    from google.genai import types
except (ImportError, ModuleNotFoundError) as exc:
    if getattr(exc, "name", None) not in {"google", "google.genai", None}:
        raise
    _GENAI_IMPORT_ERROR = exc
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]
else:
    _GENAI_IMPORT_ERROR = None

logger = logging.getLogger(__name__)

_DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def is_gemini_sdk_available() -> bool:
    return _GENAI_IMPORT_ERROR is None


def resolve_gemini_model(model: str | None) -> str:
    env_model = os.environ.get("GEMINI_MODEL", "").strip()
    if model:
        normalized = model.strip()
        if normalized.startswith("gemini:"):
            selected = normalized.split(":", 1)[1].strip()
            if selected and selected != "default":
                return selected
        elif normalized:
            return normalized
    return env_model or _DEFAULT_GEMINI_MODEL


class GeminiProviderClient:
    """Google Gen AI adapter for the provider-neutral runtime."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._model = resolve_gemini_model(model)
        if client is not None:
            self._client = client
        else:
            if genai is None:
                raise RuntimeError(
                    "Gemini runtime is not installed. Install the google-genai package."
                ) from _GENAI_IMPORT_ERROR
            self._client = genai.Client(
                api_key=api_key or os.environ.get("GEMINI_API_KEY") or None
            )
        self._capabilities = ProviderCapabilities(
            provider="gemini",
            model=self._model,
            supports_streaming_text=True,
            supports_parallel_tool_calls=True,
            supports_usage_metadata=True,
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def stream_turn(
        self,
        *,
        messages: list[ProviderInputMessage],
        system_instructions: list[ProviderSystemInstruction],
        tools: list[ProviderToolDeclaration],
    ) -> AsyncIterator[ProviderStreamEvent]:
        return self._stream_turn(
            messages=messages,
            system_instructions=system_instructions,
            tools=tools,
        )

    async def _stream_turn(
        self,
        *,
        messages: list[ProviderInputMessage],
        system_instructions: list[ProviderSystemInstruction],
        tools: list[ProviderToolDeclaration],
    ) -> AsyncIterator[ProviderStreamEvent]:
        contents = to_gemini_contents(messages)
        config = to_gemini_config(system_instructions, tools)
        text_parts: list[str] = []
        emitted_calls: set[tuple[str, str]] = set()
        last_chunk: Any | None = None

        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=contents,
                config=config,
            )
            async for chunk in stream:
                last_chunk = chunk
                text = _field(chunk, "text")
                if isinstance(text, str) and text:
                    text_parts.append(text)
                    yield ProviderStreamEvent(
                        type=ProviderStreamEventType.TEXT_DELTA,
                        text=text,
                    )
                for call in _tool_calls_from_gemini_chunk(chunk):
                    key = (call.tool_name, call.raw_arguments or "")
                    if key in emitted_calls:
                        continue
                    emitted_calls.add(key)
                    yield ProviderStreamEvent(
                        type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
                        tool_call=call,
                    )
        except Exception:
            logger.warning("Gemini content stream failed", exc_info=True)
            raise

        text = "".join(text_parts)
        if text:
            yield ProviderStreamEvent(
                type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                text=text,
            )
        yield ProviderStreamEvent(
            type=ProviderStreamEventType.RESULT_METADATA,
            metadata=_metadata_from_gemini_chunk(last_chunk, self._model),
        )
        yield ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE)

    async def cancel(self) -> None:
        return None


def to_gemini_contents(messages: list[ProviderInputMessage]) -> list[Any]:
    _require_types()
    contents: list[Any] = []
    for message in messages:
        parts: list[Any] = []
        for part in message.content:
            if part.type == "text" and part.text:
                parts.append(types.Part.from_text(text=part.text))
            elif part.type == "tool_call" and part.tool_call is not None:
                parts.append(
                    types.Part.from_function_call(
                        name=part.tool_call.tool_name,
                        args=dict(part.tool_call.parsed_input),
                    )
                )

        if message.role == "tool":
            tool_name = _tool_name_for_result(message)
            response = _function_response_payload(message)
            parts = [
                types.Part.from_function_response(
                    name=tool_name,
                    response=response,
                )
            ]
            contents.append(types.Content(role="tool", parts=parts))
        elif parts:
            role = "model" if message.role == "assistant" else "user"
            contents.append(types.Content(role=role, parts=parts))
    return contents


def to_gemini_config(
    system_instructions: list[ProviderSystemInstruction],
    tools: list[ProviderToolDeclaration],
) -> Any:
    _require_types()
    kwargs: dict[str, Any] = {}
    system_instruction = "\n\n".join(
        instruction.content
        for instruction in system_instructions
        if instruction.content
    )
    if system_instruction:
        kwargs["system_instruction"] = system_instruction
    declarations = [
        types.FunctionDeclaration(
            name=tool.name,
            description=tool.description,
            parameters_json_schema=tool.input_schema,
        )
        for tool in tools
    ]
    if declarations:
        kwargs["tools"] = [types.Tool(function_declarations=declarations)]
    return types.GenerateContentConfig(**kwargs)


def _tool_calls_from_gemini_chunk(chunk: Any) -> list[ProviderToolCall]:
    calls: list[ProviderToolCall] = []
    function_calls = _field(chunk, "function_calls") or []
    for function_call in function_calls:
        call = _tool_call_from_gemini_function_call(function_call)
        if call is not None:
            calls.append(call)
    if calls:
        return calls

    for part in _candidate_parts(chunk):
        function_call = _field(part, "function_call")
        call = _tool_call_from_gemini_function_call(function_call)
        if call is not None:
            calls.append(call)
    return calls


def _tool_call_from_gemini_function_call(function_call: Any) -> ProviderToolCall | None:
    if function_call is None:
        return None
    name = _field(function_call, "name")
    if not isinstance(name, str) or not name:
        return None
    args = _field(function_call, "args") or {}
    parsed_input = dict(args) if isinstance(args, dict) else {}
    raw_arguments = json.dumps(parsed_input, sort_keys=True)
    call_id = _field(function_call, "id")
    return ProviderToolCall(
        call_id=call_id if isinstance(call_id, str) and call_id else None,
        tool_name=name,
        parsed_input=parsed_input,
        raw_arguments=raw_arguments,
        metadata={"provider": "gemini", "function_name": name},
    )


def _candidate_parts(chunk: Any) -> list[Any]:
    parts: list[Any] = []
    for candidate in _field(chunk, "candidates") or []:
        content = _field(candidate, "content")
        parts.extend(_field(content, "parts") or [])
    return parts


def _metadata_from_gemini_chunk(
    chunk: Any | None, model: str
) -> ProviderResultMetadata:
    usage = _to_plain_dict(_field(chunk, "usage_metadata"))
    return ProviderResultMetadata(
        provider="gemini",
        model=model,
        usage=usage,
        raw_usage_provider=usage,
    )


def _tool_name_for_result(message: ProviderInputMessage) -> str:
    tool_name = message.metadata.get("tool_name")
    if isinstance(tool_name, str) and tool_name:
        return tool_name
    return "unknown_tool"


def _function_response_payload(message: ProviderInputMessage) -> dict[str, Any]:
    text = "".join(part.text for part in message.content if part.type == "text")
    structured_payload = message.metadata.get("structured_payload")
    if message.metadata.get("is_error") is True:
        return {"error": text or "Tool failed."}
    if isinstance(structured_payload, dict) and structured_payload:
        return {"content": text, "structured_payload": structured_payload}
    return {"content": text}


def _field(value: Any, key: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _to_plain_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _require_types() -> None:
    if types is None:
        raise RuntimeError(
            "Gemini runtime is not installed. Install the google-genai package."
        ) from _GENAI_IMPORT_ERROR
