from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

ProviderRole = Literal["system", "developer", "user", "assistant", "tool"]


class ProviderStreamEventType(StrEnum):
    TEXT_DELTA = "text_delta"
    TEXT_BLOCK_COMPLETE = "text_block_complete"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_ARGUMENTS_DELTA = "tool_arguments_delta"
    TOOL_CALL_COMPLETE = "tool_call_complete"
    RESULT_METADATA = "result_metadata"
    PROVIDER_ERROR = "provider_error"
    STREAM_COMPLETE = "stream_complete"


@dataclass(frozen=True)
class ProviderContentPart:
    type: Literal["text"] = "text"
    text: str = ""


@dataclass(frozen=True)
class ProviderInputMessage:
    role: ProviderRole
    content: list[ProviderContentPart]
    tool_call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderSystemInstruction:
    content: str
    instruction_type: Literal["system", "developer"] = "system"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderToolDeclaration:
    name: str
    description: str
    input_schema: dict[str, Any]
    projection_hints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderCapabilities:
    provider: str
    model: str
    supports_streaming_text: bool = False
    supports_streaming_tool_arguments: bool = False
    supports_parallel_tool_calls: bool = False
    supports_cancellation: bool = False
    supports_usage_metadata: bool = False
    supports_stable_tool_call_ids: bool = False
    supports_provider_session_ids: bool = False


class ModelProviderClient(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def stream_turn(
        self,
        *,
        messages: list[ProviderInputMessage],
        system_instructions: list[ProviderSystemInstruction],
        tools: list[ProviderToolDeclaration],
    ) -> AsyncIterator[ProviderStreamEvent]: ...

    async def cancel(self) -> None: ...


@dataclass(frozen=True)
class ProviderToolResult:
    call_id: str | None
    tool_name: str
    content: str
    structured_payload: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    sanitized_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderToolCall:
    call_id: str | None
    tool_name: str
    parsed_input: dict[str, Any]
    raw_arguments: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResultMetadata:
    provider: str
    model: str
    session_id: str | None = None
    stop_reason: str | None = None
    result_subtype: str | None = None
    num_turns: int | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    total_cost_usd: float | None = None
    raw_usage_provider: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderFinalResult:
    text: str
    metadata: ProviderResultMetadata
    is_error: bool = False
    sanitized_error: str | None = None


@dataclass(frozen=True)
class ProviderStreamEvent:
    type: ProviderStreamEventType
    text: str | None = None
    tool_call: ProviderToolCall | None = None
    metadata: ProviderResultMetadata | None = None
    error_message: str | None = None
