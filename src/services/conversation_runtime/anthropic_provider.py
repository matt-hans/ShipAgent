"""Anthropic Messages API adapter for the provider-neutral runtime.

Pure protocol translation over ``httpx``: neutral messages/tools in, Anthropic
Messages request out; Anthropic SSE events in, normalized stream events out.
No Claude Agent SDK, no shipping logic, no workflow-service imports. Failure
text yielded in ``PROVIDER_ERROR`` events is adapter-authored and safe to show
to users: it never includes response bodies, headers, or credentials.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

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

logger = logging.getLogger(__name__)

ANTHROPIC_API_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_API_VERSION = "2023-06-01"
ANTHROPIC_MESSAGES_PATH = "/v1/messages"
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_OUTPUT_TOKENS = 8192
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

PROTOCOL_ERROR_MESSAGE = (
    "Anthropic returned a response ShipAgent could not interpret (protocol "
    "error). Retry the request; if it persists, check the configured model."
)
EMPTY_RESPONSE_MESSAGE = (
    "Anthropic returned an empty response. Retry the request or choose a "
    "different model."
)
TRANSPORT_ERROR_MESSAGE = (
    "Could not reach the Anthropic API. Check network connectivity and retry."
)
_AUTH_MESSAGE = "Anthropic rejected the API key. Check ANTHROPIC_API_KEY in Settings."
_RATE_LIMIT_MESSAGE = "Anthropic rate limit reached. Wait a moment and retry."
_OVERLOADED_MESSAGE = "Anthropic is temporarily unavailable. Retry shortly."
_REQUEST_REJECTED_MESSAGE = (
    "Anthropic rejected the request. Check the configured model and runtime."
)


def resolve_anthropic_model(model: str | None) -> str:
    """Return the Anthropic model id for ``model`` (``anthropic:`` prefix ok)."""
    if model:
        normalized = model.strip()
        if normalized.lower().startswith("anthropic:"):
            normalized = normalized.split(":", 1)[1].strip()
        if normalized and normalized.lower() != "default":
            return normalized
    return DEFAULT_ANTHROPIC_MODEL


def model_not_found_message(model: str) -> str:
    return (
        f"Anthropic model '{model}' was not found or is not available to this "
        "API key. Check AGENT_MODEL."
    )


class AnthropicProviderClient:
    """Anthropic Messages (streaming) adapter for the shared runtime."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = ANTHROPIC_API_BASE_URL,
        max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        key = (api_key or os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not key:
            raise RuntimeError(
                "Anthropic API key is not configured. Add ANTHROPIC_API_KEY in "
                "Settings before sending shipping commands."
            )
        self._api_key = key
        self._model = resolve_anthropic_model(model)
        self._http_client = http_client
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens
        self._active_response: httpx.Response | None = None
        self._capabilities = ProviderCapabilities(
            provider="anthropic",
            model=self._model,
            supports_streaming_text=True,
            supports_streaming_tool_arguments=True,
            supports_parallel_tool_calls=True,
            supports_cancellation=True,
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

    async def cancel(self) -> None:
        response = self._active_response
        if response is not None:
            await response.aclose()

    async def _stream_turn(
        self,
        *,
        messages: list[ProviderInputMessage],
        system_instructions: list[ProviderSystemInstruction],
        tools: list[ProviderToolDeclaration],
    ) -> AsyncIterator[ProviderStreamEvent]:
        body = to_anthropic_request(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=messages,
            system_instructions=system_instructions,
            tools=tools,
        )
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        client = self._http_client or httpx.AsyncClient(timeout=_TIMEOUT)
        try:
            request = client.build_request(
                "POST",
                f"{self._base_url}{ANTHROPIC_MESSAGES_PATH}",
                headers=headers,
                json=body,
            )
            try:
                response = await client.send(request, stream=True)
            except httpx.HTTPError as exc:
                logger.warning(
                    "Anthropic request failed exception_type=%s", type(exc).__name__
                )
                yield _error_event(TRANSPORT_ERROR_MESSAGE)
                return
            self._active_response = response
            try:
                if response.status_code >= 400:
                    await response.aread()
                    yield _error_event(
                        _http_error_message(
                            response.status_code,
                            _error_type_from_body(response),
                            self._model,
                        )
                    )
                    return
                async for event in self._parse_stream(response):
                    yield event
            except httpx.HTTPError as exc:
                logger.warning(
                    "Anthropic stream failed exception_type=%s", type(exc).__name__
                )
                yield _error_event(TRANSPORT_ERROR_MESSAGE)
            finally:
                self._active_response = None
                await response.aclose()
        finally:
            if self._http_client is None:
                await client.aclose()

    async def _parse_stream(
        self, response: httpx.Response
    ) -> AsyncIterator[ProviderStreamEvent]:
        state = _StreamState(default_model=self._model)
        async for payload in _iter_sse_payloads(response):
            if payload is None:
                yield _error_event(PROTOCOL_ERROR_MESSAGE)
                return
            try:
                events, finished = state.consume(payload, self._model)
            except _ProtocolError as exc:
                yield _error_event(exc.message)
                return
            for event in events:
                yield event
            if finished:
                break

        if not state.message_stopped:
            yield _error_event(PROTOCOL_ERROR_MESSAGE)
            return
        if state.error_message is not None:
            yield _error_event(state.error_message)
            return
        if not state.text_parts and not state.emitted_tool_calls:
            yield _error_event(EMPTY_RESPONSE_MESSAGE)
            return
        yield ProviderStreamEvent(
            type=ProviderStreamEventType.RESULT_METADATA,
            metadata=state.metadata(),
        )
        text = "".join(state.text_parts)
        if text:
            yield ProviderStreamEvent(
                type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE, text=text
            )
        yield ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE)


class _ProtocolError(Exception):
    def __init__(self, message: str = PROTOCOL_ERROR_MESSAGE) -> None:
        super().__init__(message)
        self.message = message


class _StreamState:
    def __init__(self, *, default_model: str) -> None:
        self.model = default_model
        self.message_id: str | None = None
        self.stop_reason: str | None = None
        self.usage: dict[str, Any] = {}
        self.text_parts: list[str] = []
        self.blocks: dict[int, dict[str, Any]] = {}
        self.emitted_tool_calls: list[ProviderToolCall] = []
        self.message_started = False
        self.message_stopped = False
        self.error_message: str | None = None

    def metadata(self) -> ProviderResultMetadata:
        return ProviderResultMetadata(
            provider="anthropic",
            model=self.model,
            session_id=self.message_id,
            stop_reason=self.stop_reason,
            usage=dict(self.usage),
            raw_usage_provider=dict(self.usage),
        )

    def consume(
        self, payload: dict[str, Any], requested_model: str
    ) -> tuple[list[ProviderStreamEvent], bool]:
        """Apply one SSE payload; return (events, stream_finished)."""
        kind = payload.get("type")
        if kind == "ping":
            return [], False
        if kind == "error":
            error = payload.get("error")
            error_type = error.get("type") if isinstance(error, dict) else None
            self.error_message = _stream_error_message(
                error_type if isinstance(error_type, str) else None, requested_model
            )
            self.message_stopped = True
            return [], True
        if kind == "message_start":
            message = payload.get("message")
            if not isinstance(message, dict):
                raise _ProtocolError()
            self.message_started = True
            message_id = message.get("id")
            self.message_id = message_id if isinstance(message_id, str) else None
            model = message.get("model")
            if isinstance(model, str) and model:
                self.model = model
            self._merge_usage(message.get("usage"))
            return [], False
        if not self.message_started:
            raise _ProtocolError()
        if kind == "content_block_start":
            return self._block_start(payload), False
        if kind == "content_block_delta":
            return self._block_delta(payload), False
        if kind == "content_block_stop":
            return self._block_stop(payload), False
        if kind == "message_delta":
            delta = payload.get("delta")
            if isinstance(delta, dict):
                reason = delta.get("stop_reason")
                if isinstance(reason, str):
                    self.stop_reason = reason
            self._merge_usage(payload.get("usage"))
            return [], False
        if kind == "message_stop":
            if self.blocks:
                raise _ProtocolError()
            self.message_stopped = True
            return [], True
        # Unknown event types are ignored for forward compatibility.
        return [], False

    def _merge_usage(self, usage: Any) -> None:
        if isinstance(usage, dict):
            for key, value in usage.items():
                if isinstance(value, int | str):
                    self.usage[key] = value

    def _index(self, payload: dict[str, Any]) -> int:
        index = payload.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            raise _ProtocolError()
        return index

    def _block_start(self, payload: dict[str, Any]) -> list[ProviderStreamEvent]:
        index = self._index(payload)
        block = payload.get("content_block")
        if not isinstance(block, dict) or index in self.blocks:
            raise _ProtocolError()
        block_type = block.get("type")
        if block_type == "tool_use":
            call_id, name = block.get("id"), block.get("name")
            if not (isinstance(call_id, str) and call_id):
                raise _ProtocolError()
            if not (isinstance(name, str) and name):
                raise _ProtocolError()
            self.blocks[index] = {
                "type": "tool_use",
                "id": call_id,
                "name": name,
                "json": "",
            }
            return [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TOOL_CALL_STARTED,
                    tool_call=ProviderToolCall(
                        call_id=call_id,
                        tool_name=name,
                        parsed_input={},
                        metadata={"provider": "anthropic"},
                    ),
                )
            ]
        if block_type == "text":
            self.blocks[index] = {"type": "text"}
            initial = block.get("text")
            if isinstance(initial, str) and initial:
                self.text_parts.append(initial)
                return [
                    ProviderStreamEvent(
                        type=ProviderStreamEventType.TEXT_DELTA, text=initial
                    )
                ]
            return []
        # thinking / redacted_thinking / server tools: tracked but not surfaced.
        self.blocks[index] = {"type": "ignored"}
        return []

    def _block_delta(self, payload: dict[str, Any]) -> list[ProviderStreamEvent]:
        index = self._index(payload)
        block = self.blocks.get(index)
        delta = payload.get("delta")
        if block is None or not isinstance(delta, dict):
            raise _ProtocolError()
        delta_type = delta.get("type")
        if delta_type == "text_delta" and block["type"] == "text":
            text = delta.get("text")
            if not isinstance(text, str):
                raise _ProtocolError()
            if not text:
                return []
            self.text_parts.append(text)
            return [
                ProviderStreamEvent(type=ProviderStreamEventType.TEXT_DELTA, text=text)
            ]
        if delta_type == "input_json_delta" and block["type"] == "tool_use":
            fragment = delta.get("partial_json")
            if not isinstance(fragment, str):
                raise _ProtocolError()
            block["json"] += fragment
            if not fragment:
                return []
            return [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TOOL_ARGUMENTS_DELTA, text=fragment
                )
            ]
        if block["type"] == "ignored":
            return []
        raise _ProtocolError()

    def _block_stop(self, payload: dict[str, Any]) -> list[ProviderStreamEvent]:
        index = self._index(payload)
        block = self.blocks.pop(index, None)
        if block is None:
            raise _ProtocolError()
        if block["type"] != "tool_use":
            return []
        raw = block["json"]
        if raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                raise _ProtocolError() from None
            if not isinstance(parsed, dict):
                raise _ProtocolError()
        else:
            parsed = {}
        call = ProviderToolCall(
            call_id=block["id"],
            tool_name=block["name"],
            parsed_input=parsed,
            raw_arguments=raw or None,
            metadata={"provider": "anthropic"},
        )
        self.emitted_tool_calls.append(call)
        return [
            ProviderStreamEvent(
                type=ProviderStreamEventType.TOOL_CALL_COMPLETE, tool_call=call
            )
        ]


async def _iter_sse_payloads(
    response: httpx.Response,
) -> AsyncIterator[dict[str, Any] | None]:
    """Yield decoded SSE ``data`` objects; ``None`` marks undecodable data."""
    data_lines: list[str] = []

    def flush() -> tuple[bool, dict[str, Any] | None]:
        if not data_lines:
            return False, None
        raw = "\n".join(data_lines)
        data_lines.clear()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return True, None
        return True, value if isinstance(value, dict) else None

    async for line in response.aiter_lines():
        if line == "":
            has_data, payload = flush()
            if has_data:
                yield payload
        elif line.startswith("data:"):
            data_lines.append(line[5:].removeprefix(" "))
    has_data, payload = flush()
    if has_data:
        yield payload


def to_anthropic_tool(tool: ProviderToolDeclaration) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema or {"type": "object", "properties": {}},
    }


def to_anthropic_request(
    *,
    model: str,
    max_tokens: int,
    messages: list[ProviderInputMessage],
    system_instructions: list[ProviderSystemInstruction],
    tools: list[ProviderToolDeclaration],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "stream": True,
        "messages": to_anthropic_messages(messages),
    }
    system = "\n\n".join(i.content for i in system_instructions if i.content)
    if system:
        body["system"] = system
    if tools:
        body["tools"] = [to_anthropic_tool(tool) for tool in tools]
    return body


def to_anthropic_messages(
    messages: list[ProviderInputMessage],
) -> list[dict[str, Any]]:
    """Translate neutral messages; adjacent same-role turns are merged.

    Tool results ride in ``user`` messages as ``tool_result`` blocks, so all
    results for one assistant turn land together in a single user message.
    """
    out: list[dict[str, Any]] = []

    def append(role: str, blocks: list[dict[str, Any]]) -> None:
        if not blocks:
            return
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": list(blocks)})

    for message in messages:
        if message.role == "tool":
            if not message.tool_call_id:
                continue
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id,
                "content": _message_text(message),
            }
            if message.metadata.get("is_error"):
                block["is_error"] = True
            append("user", [block])
        elif message.role == "assistant":
            blocks: list[dict[str, Any]] = []
            for part in message.content:
                if part.type == "text" and part.text:
                    blocks.append({"type": "text", "text": part.text})
                elif part.type == "tool_call" and part.tool_call is not None:
                    call = part.tool_call
                    if call.call_id is None:
                        continue
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.call_id,
                            "name": call.tool_name,
                            "input": call.parsed_input,
                        }
                    )
            append("assistant", blocks)
        elif message.role == "user":
            text = _message_text(message)
            if text:
                append("user", [{"type": "text", "text": text}])
        # system/developer-role messages are carried via system_instructions.
    return out


def _message_text(message: ProviderInputMessage) -> str:
    return "".join(
        part.text
        for part in message.content
        if part.type == "text" and isinstance(part.text, str)
    )


def _error_event(message: str) -> ProviderStreamEvent:
    return ProviderStreamEvent(
        type=ProviderStreamEventType.PROVIDER_ERROR,
        error_message=message,
        safe_error_message=message,
    )


def _error_type_from_body(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except (ValueError, httpx.HTTPError):
        return None
    error = body.get("error") if isinstance(body, dict) else None
    error_type = error.get("type") if isinstance(error, dict) else None
    return error_type if isinstance(error_type, str) else None


def _http_error_message(status: int, error_type: str | None, model: str) -> str:
    if status in {401, 403}:
        return _AUTH_MESSAGE
    if status == 404 or error_type == "not_found_error":
        return model_not_found_message(model)
    if status == 429:
        return _RATE_LIMIT_MESSAGE
    if status >= 500:
        return _OVERLOADED_MESSAGE
    if status in {400, 413, 422}:
        return _REQUEST_REJECTED_MESSAGE
    return PROTOCOL_ERROR_MESSAGE


def _stream_error_message(error_type: str | None, model: str) -> str:
    mapping = {
        "authentication_error": _AUTH_MESSAGE,
        "permission_error": _AUTH_MESSAGE,
        "not_found_error": model_not_found_message(model),
        "rate_limit_error": _RATE_LIMIT_MESSAGE,
        "overloaded_error": _OVERLOADED_MESSAGE,
        "api_error": _OVERLOADED_MESSAGE,
        "invalid_request_error": _REQUEST_REJECTED_MESSAGE,
    }
    return mapping.get(error_type or "", PROTOCOL_ERROR_MESSAGE)
