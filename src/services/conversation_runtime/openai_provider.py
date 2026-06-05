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
    from openai import AsyncOpenAI
except ModuleNotFoundError as exc:
    if exc.name != "openai":
        raise
    _OPENAI_IMPORT_ERROR = exc
    AsyncOpenAI = None  # type: ignore[assignment]
else:
    _OPENAI_IMPORT_ERROR = None

logger = logging.getLogger(__name__)

_DEFAULT_OPENAI_MODEL = "gpt-5-mini"


def is_openai_sdk_available() -> bool:
    return _OPENAI_IMPORT_ERROR is None


def resolve_openai_model(model: str | None) -> str:
    env_model = os.environ.get("OPENAI_MODEL", "").strip()
    if model:
        normalized = model.strip()
        if normalized.startswith("openai:"):
            selected = normalized.split(":", 1)[1].strip()
            if selected and selected != "default":
                return selected
        elif normalized:
            return normalized
    return env_model or _DEFAULT_OPENAI_MODEL


class OpenAIProviderClient:
    """OpenAI Responses API adapter for the provider-neutral runtime."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._model = resolve_openai_model(model)
        if client is not None:
            self._client = client
        else:
            if AsyncOpenAI is None:
                raise RuntimeError(
                    "OpenAI runtime is not installed. Install the openai package."
                ) from _OPENAI_IMPORT_ERROR
            self._client = AsyncOpenAI(
                api_key=api_key or os.environ.get("OPENAI_API_KEY") or None
            )
        self._capabilities = ProviderCapabilities(
            provider="openai",
            model=self._model,
            supports_streaming_text=True,
            supports_streaming_tool_arguments=True,
            supports_parallel_tool_calls=True,
            supports_usage_metadata=True,
            supports_stable_tool_call_ids=True,
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
        input_items = to_openai_input(messages)
        instructions = _join_instructions(system_instructions)
        openai_tools = [to_openai_tool(tool) for tool in tools]
        text_parts: list[str] = []
        pending_calls: dict[str, dict[str, Any]] = {}
        emitted_call_ids: set[str] = set()
        completed_response: Any | None = None

        try:
            stream = await self._client.responses.create(
                model=self._model,
                input=input_items,
                instructions=instructions or None,
                tools=openai_tools or None,
                stream=True,
            )
            async for event in stream:
                event_type = _field(event, "type")
                if event_type == "response.output_text.delta":
                    delta = _field(event, "delta") or ""
                    if isinstance(delta, str) and delta:
                        text_parts.append(delta)
                        yield ProviderStreamEvent(
                            type=ProviderStreamEventType.TEXT_DELTA,
                            text=delta,
                        )
                elif event_type == "response.output_item.added":
                    item = _field(event, "item")
                    if _field(item, "type") == "function_call":
                        pending = {
                            "item": item,
                            "arguments": _field(item, "arguments") or "",
                        }
                        for key in _event_call_keys(event, item):
                            pending_calls[key] = pending
                elif event_type == "response.function_call_arguments.delta":
                    key = _event_call_key(event)
                    delta = _field(event, "delta") or ""
                    if isinstance(delta, str) and delta:
                        pending_calls.setdefault(key, {"arguments": ""})
                        pending_calls[key]["arguments"] += delta
                        yield ProviderStreamEvent(
                            type=ProviderStreamEventType.TOOL_ARGUMENTS_DELTA,
                            text=delta,
                        )
                elif event_type == "response.function_call_arguments.done":
                    call = _tool_call_from_openai_event(event, pending_calls)
                    if call is not None and call.call_id not in emitted_call_ids:
                        if call.call_id is not None:
                            emitted_call_ids.add(call.call_id)
                        yield ProviderStreamEvent(
                            type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
                            tool_call=call,
                        )
                elif event_type == "response.completed":
                    completed_response = _field(event, "response")
                elif event_type in {"response.failed", "response.incomplete"}:
                    yield ProviderStreamEvent(
                        type=ProviderStreamEventType.PROVIDER_ERROR,
                        error_message="Provider error",
                    )
                    return
        except Exception:
            logger.warning("OpenAI response stream failed", exc_info=True)
            raise

        if completed_response is not None:
            for call in _tool_calls_from_openai_response(completed_response):
                if call.call_id is not None and call.call_id in emitted_call_ids:
                    continue
                if call.call_id is not None:
                    emitted_call_ids.add(call.call_id)
                yield ProviderStreamEvent(
                    type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
                    tool_call=call,
                )
            if not text_parts:
                response_text = _field(completed_response, "output_text")
                if isinstance(response_text, str) and response_text:
                    text_parts.append(response_text)
            metadata = _metadata_from_openai_response(completed_response, self._model)
            yield ProviderStreamEvent(
                type=ProviderStreamEventType.RESULT_METADATA,
                metadata=metadata,
            )

        text = "".join(text_parts)
        if text:
            yield ProviderStreamEvent(
                type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                text=text,
            )
        yield ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE)

    async def cancel(self) -> None:
        return None


def to_openai_tool(tool: ProviderToolDeclaration) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.input_schema,
        "strict": False,
    }


def to_openai_input(messages: list[ProviderInputMessage]) -> list[dict[str, Any]]:
    input_items: list[dict[str, Any]] = []
    for message in messages:
        text = _message_text(message)
        if message.role == "tool":
            if message.tool_call_id:
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id,
                        "output": text,
                    }
                )
            continue

        if text:
            input_items.append({"role": message.role, "content": text})

        if message.role == "assistant":
            for part in message.content:
                if part.type != "tool_call" or part.tool_call is None:
                    continue
                call = part.tool_call
                item: dict[str, Any] = {
                    "type": "function_call",
                    "call_id": call.call_id,
                    "name": call.tool_name,
                    "arguments": call.raw_arguments
                    or json.dumps(call.parsed_input, sort_keys=True),
                }
                item_id = call.metadata.get("provider_item_id") or call.metadata.get(
                    "id"
                )
                if isinstance(item_id, str) and item_id:
                    item["id"] = item_id
                input_items.append(item)
    return input_items


def _join_instructions(
    system_instructions: list[ProviderSystemInstruction],
) -> str:
    return "\n\n".join(
        instruction.content
        for instruction in system_instructions
        if instruction.content
    )


def _message_text(message: ProviderInputMessage) -> str:
    return "".join(
        part.text
        for part in message.content
        if part.type == "text" and isinstance(part.text, str)
    )


def _tool_call_from_openai_event(
    event: Any,
    pending_calls: dict[str, dict[str, Any]],
) -> ProviderToolCall | None:
    key = _event_call_key(event)
    pending = pending_calls.get(key, {})
    item = pending.get("item")
    raw_arguments = _field(event, "arguments") or pending.get("arguments") or ""
    name = _field(event, "name") or _field(item, "name")
    call_id = _field(event, "call_id") or _field(item, "call_id")
    item_id = _field(event, "item_id") or _field(item, "id")
    if not isinstance(name, str) or not name:
        return None
    parsed_input = _parse_json_object(raw_arguments)
    return ProviderToolCall(
        call_id=call_id if isinstance(call_id, str) and call_id else None,
        tool_name=name,
        parsed_input=parsed_input,
        raw_arguments=raw_arguments if isinstance(raw_arguments, str) else None,
        metadata={
            "provider": "openai",
            "provider_item_id": item_id if isinstance(item_id, str) else None,
        },
    )


def _tool_calls_from_openai_response(response: Any) -> list[ProviderToolCall]:
    calls: list[ProviderToolCall] = []
    for item in _field(response, "output") or []:
        if _field(item, "type") != "function_call":
            continue
        name = _field(item, "name")
        if not isinstance(name, str) or not name:
            continue
        raw_arguments = _field(item, "arguments") or ""
        call_id = _field(item, "call_id")
        item_id = _field(item, "id")
        calls.append(
            ProviderToolCall(
                call_id=call_id if isinstance(call_id, str) and call_id else None,
                tool_name=name,
                parsed_input=_parse_json_object(raw_arguments),
                raw_arguments=raw_arguments if isinstance(raw_arguments, str) else None,
                metadata={
                    "provider": "openai",
                    "provider_item_id": item_id if isinstance(item_id, str) else None,
                },
            )
        )
    return calls


def _metadata_from_openai_response(response: Any, model: str) -> ProviderResultMetadata:
    usage = _to_plain_dict(_field(response, "usage"))
    return ProviderResultMetadata(
        provider="openai",
        model=_field(response, "model") or model,
        session_id=_field(response, "id"),
        stop_reason=_field(response, "status"),
        usage=usage,
        raw_usage_provider=usage,
    )


def _parse_json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _event_call_key(event: Any, item: Any | None = None) -> str:
    return _event_call_keys(event, item)[0]


def _event_call_keys(event: Any, item: Any | None = None) -> list[str]:
    keys: list[str] = []
    for candidate in (
        _field(event, "item_id"),
        _field(event, "output_index"),
        _field(item, "id") if item is not None else None,
        _field(item, "call_id") if item is not None else None,
    ):
        if candidate is not None:
            keys.append(str(candidate))
    return keys or ["default"]


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
