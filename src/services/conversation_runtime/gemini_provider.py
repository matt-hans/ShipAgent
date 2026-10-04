from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from itertools import count
from typing import Any

from src.services.conversation_runtime.models import (
    ProviderCapabilities,
    ProviderInputMessage,
    ProviderOutputItem,
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
MALFORMED_ARGUMENTS_MESSAGE = (
    "Gemini returned a tool request ShipAgent could not interpret (malformed "
    "arguments). Retry the request; if it persists, check the configured model."
)
_PROVIDER = "gemini"


class _MalformedToolCall(Exception):
    """A function call is not a complete named call with object arguments."""


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
        # Gemini calls usually carry no id; ShipAgent assigns one per call so
        # results pair and replays dedupe. Unique for the life of this client.
        self._call_sequence = count(1)
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
        # Model parts exactly as streamed (thought signatures included), kept
        # private so the next request can replay them unmodified.
        raw_parts: list[dict[str, Any]] = []
        raw_call_ids: list[str] = []
        native_call_ids: dict[str, tuple[str, str]] = {}
        last_chunk: Any | None = None

        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=contents,
                config=config,
            )
            async for chunk in stream:
                last_chunk = chunk
                for kind, value in _chunk_items(chunk):
                    if kind == "text":
                        text_parts.append(value)
                        yield ProviderStreamEvent(
                            type=ProviderStreamEventType.TEXT_DELTA,
                            text=value,
                        )
                    elif kind == "raw":
                        raw_parts.append(value)
                    else:
                        part_dict, function_call = value
                        call = self._tool_call(function_call)
                        native = call.metadata.get("provider_call_id")
                        if native is not None:
                            fingerprint = (
                                call.tool_name,
                                call.raw_arguments or "",
                            )
                            seen = native_call_ids.get(native)
                            if seen is not None:
                                if seen != fingerprint:
                                    raise _MalformedToolCall
                                # Same call replayed within the stream.
                                continue
                            native_call_ids[native] = fingerprint
                        if part_dict is not None:
                            raw_parts.append(part_dict)
                            raw_call_ids.append(call.call_id or "")
                        yield ProviderStreamEvent(
                            type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
                            tool_call=call,
                        )
        except _MalformedToolCall:
            yield ProviderStreamEvent(
                type=ProviderStreamEventType.PROVIDER_ERROR,
                error_message="Malformed tool call",
                safe_error_message=MALFORMED_ARGUMENTS_MESSAGE,
            )
            return
        except Exception:
            logger.warning("Gemini content stream failed", exc_info=True)
            raise

        if _needs_private_continuation(raw_parts):
            yield ProviderStreamEvent(
                type=ProviderStreamEventType.PROVIDER_OUTPUT_ITEM,
                provider_output_item=ProviderOutputItem(
                    provider=_PROVIDER,
                    item={"parts": raw_parts, "call_ids": raw_call_ids},
                ),
            )
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

    def _tool_call(self, function_call: Any) -> ProviderToolCall:
        name = _field(function_call, "name")
        if not isinstance(name, str) or not name:
            raise _MalformedToolCall
        if _field(function_call, "will_continue") is True:
            # Partial (streamed) arguments are never dispatched.
            raise _MalformedToolCall
        args = _field(function_call, "args")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise _MalformedToolCall
        parsed_input = dict(args)
        provider_id = _field(function_call, "id")
        native = provider_id if isinstance(provider_id, str) and provider_id else None
        return ProviderToolCall(
            call_id=native or f"gemini_call_{next(self._call_sequence)}",
            tool_name=name,
            parsed_input=parsed_input,
            raw_arguments=json.dumps(parsed_input, sort_keys=True),
            metadata={
                "provider": _PROVIDER,
                "function_name": name,
                "provider_call_id": native,
            },
        )

    async def cancel(self) -> None:
        return None


def to_gemini_contents(messages: list[ProviderInputMessage]) -> list[Any]:
    _require_types()
    contents: list[Any] = []
    # ShipAgent call id -> id Gemini itself issued (absent for id-less calls).
    provider_call_ids: dict[str, str] = {}
    pending_responses: list[Any] = []

    def flush_responses() -> None:
        # Parallel calls are answered by one content holding every response
        # part, in call order (the SDK's own function-calling loop does this).
        if pending_responses:
            contents.append(types.Content(role="user", parts=[*pending_responses]))
            pending_responses.clear()

    for message in messages:
        if message.role == "tool":
            pending_responses.append(
                _function_response_part(message, provider_call_ids)
            )
            continue
        flush_responses()

        for part in message.content:
            call = part.tool_call
            if part.type == "tool_call" and call is not None and call.call_id:
                native = call.metadata.get("provider_call_id")
                if isinstance(native, str) and native:
                    provider_call_ids[call.call_id] = native

        replayed = (
            _replayed_model_parts(message) if message.role == "assistant" else None
        )
        if replayed is not None:
            contents.append(types.Content(role="model", parts=replayed))
            continue

        parts: list[Any] = []
        for part in message.content:
            if part.type == "text" and part.text:
                parts.append(types.Part.from_text(text=part.text))
            elif part.type == "tool_call" and part.tool_call is not None:
                parts.append(_function_call_part(part.tool_call))
        if parts:
            role = "model" if message.role == "assistant" else "user"
            contents.append(types.Content(role=role, parts=parts))
    flush_responses()
    return contents


def _function_call_part(call: ProviderToolCall) -> Any:
    native = call.metadata.get("provider_call_id")
    if isinstance(native, str) and native:
        return types.Part(
            function_call=types.FunctionCall(
                id=native, name=call.tool_name, args=dict(call.parsed_input)
            )
        )
    return types.Part.from_function_call(
        name=call.tool_name, args=dict(call.parsed_input)
    )


def _function_response_part(
    message: ProviderInputMessage, provider_call_ids: dict[str, str]
) -> Any:
    name = _tool_name_for_result(message)
    response = _function_response_payload(message)
    native = provider_call_ids.get(message.tool_call_id or "")
    if native:
        return types.Part(
            function_response=types.FunctionResponse(
                id=native, name=name, response=response
            )
        )
    return types.Part.from_function_response(name=name, response=response)


def _replayed_model_parts(message: ProviderInputMessage) -> list[Any] | None:
    """Rebuild a model turn from the adapter-owned parts, byte-exact.

    Returns ``None`` when the message holds no Gemini continuation item (for
    example history seeded from persisted text), so the caller falls back to
    the normalized parts.
    """
    item = next(
        (
            part.provider_output_item
            for part in message.content
            if part.type == "provider_output_item"
            and part.provider_output_item is not None
            and part.provider_output_item.provider == _PROVIDER
        ),
        None,
    )
    if item is None:
        return None
    raw_parts = item.item.get("parts")
    call_ids = item.item.get("call_ids")
    if not isinstance(raw_parts, list) or not isinstance(call_ids, list):
        return None
    # A call the runtime refused to dispatch (replayed id) must not appear
    # without a matching response, or Gemini rejects the turn.
    kept = {
        part.tool_call.call_id
        for part in message.content
        if part.type == "tool_call" and part.tool_call is not None
    }
    remaining_ids = iter(call_ids)
    parts: list[Any] = []
    for raw in raw_parts:
        if not isinstance(raw, dict):
            return None
        if (
            raw.get("function_call") is not None
            and next(remaining_ids, None) not in kept
        ):
            continue
        parts.append(types.Part.model_validate(raw))
    return parts or None


def _chunk_items(chunk: Any) -> list[tuple[str, Any]]:
    """Ordered ``text`` / ``raw`` / ``call`` items of a chunk's first candidate.

    Chunks without candidate parts (the SDK's convenience view only) fall back
    to ``text`` and ``function_calls``; those carry nothing to replay.
    """
    parts = _candidate_parts(chunk)
    items: list[tuple[str, Any]] = []
    if not parts:
        text = _field(chunk, "text")
        if isinstance(text, str) and text:
            items.append(("text", text))
        for function_call in _field(chunk, "function_calls") or []:
            items.append(("call", (None, function_call)))
        return items
    for part in parts:
        function_call = _field(part, "function_call")
        text = _field(part, "text")
        plain = _plain_part(part)
        if function_call is not None:
            items.append(("call", (plain, function_call)))
        elif _field(part, "thought") is True:
            items.append(("raw", plain))
        elif isinstance(text, str) and text:
            items.append(("text", text))
            items.append(("raw", plain))
        elif _field(part, "thought_signature"):
            # Signature-only/empty-text part: opaque but required for replay.
            items.append(("raw", plain))
    return items


def _plain_part(part: Any) -> dict[str, Any]:
    if isinstance(part, dict):
        return {key: value for key, value in part.items() if value is not None}
    dump = getattr(part, "model_dump", None)
    if callable(dump):
        return dump(mode="json", exclude_none=True)
    return {}


def _needs_private_continuation(raw_parts: list[dict[str, Any]]) -> bool:
    return any(
        part.get("function_call") is not None
        or part.get("thought_signature") is not None
        or part.get("thought") is True
        for part in raw_parts
    )


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


def _candidate_parts(chunk: Any) -> list[Any]:
    parts: list[Any] = []
    candidates = _field(chunk, "candidates") or []
    if candidates:  # only the first candidate is ever replayed
        parts.extend(_field(_field(candidates[0], "content"), "parts") or [])
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
