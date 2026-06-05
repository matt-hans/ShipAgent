from __future__ import annotations

import itertools
import logging
from collections.abc import AsyncIterator
from typing import Any

from src.orchestrator.agent.tools.core import EventEmitterBridge
from src.services.conversation_runtime.dispatcher import LocalToolDispatcher
from src.services.conversation_runtime.models import (
    ModelProviderClient,
    ProviderContentPart,
    ProviderInputMessage,
    ProviderResultMetadata,
    ProviderStreamEventType,
    ProviderSystemInstruction,
    ProviderToolCall,
)
from src.services.conversation_runtime.policy import RuntimePolicyEngine
from src.services.conversation_runtime.tool_catalog import WorkflowToolCatalog

logger = logging.getLogger(__name__)
_GENERIC_PROVIDER_ERROR_MESSAGE = "Provider error"
_MAX_PROVIDER_HISTORY_MESSAGES = 30
_HISTORY_ROLES = {"user", "assistant"}


class ConversationRuntimeSession:
    def __init__(
        self,
        *,
        provider: ModelProviderClient,
        system_prompt: str | None,
        interactive_shipping: bool,
        session_id: str | None,
        max_turns: int = 50,
        prior_conversation: list[dict[str, Any]] | None = None,
    ) -> None:
        self._provider = provider
        self._system_prompt = system_prompt or ""
        self._interactive_shipping = interactive_shipping
        self._max_turns = max_turns
        self._started = False
        self._last_turn_count = 0
        self._turn_generation = itertools.count(1)
        self._active_generation = 0
        self._interrupted_generations: set[int] = set()
        self.last_result_metadata: ProviderResultMetadata | None = None
        self.emitter_bridge = EventEmitterBridge()
        self.emitter_bridge.session_id = session_id
        self._history = _build_provider_history(
            prior_conversation,
            limit=_MAX_PROVIDER_HISTORY_MESSAGES,
        )

    async def start(self) -> None:
        if self._started:
            raise RuntimeError("Agent already started.")
        self._started = True

    async def stop(self, timeout: float = 5.0) -> None:
        _ = timeout
        self._started = False
        self._interrupted_generations.add(self._active_generation)
        self.emitter_bridge.callback = None

    async def process_command(self, user_input: str) -> str:
        parts: list[str] = []
        async for event in self.process_message_stream(user_input):
            if event.get("event") == "agent_message":
                text = event.get("data", {}).get("text", "")
                if isinstance(text, str):
                    parts.append(text)
            elif event.get("event") == "error":
                message = event.get("data", {}).get(
                    "message",
                    _GENERIC_PROVIDER_ERROR_MESSAGE,
                )
                if not isinstance(message, str):
                    message = _GENERIC_PROVIDER_ERROR_MESSAGE
                return f"[Error: {message}]"
        return "".join(parts)

    def process_message_stream(self, user_input: str) -> AsyncIterator[dict[str, Any]]:
        if not self._started:
            raise RuntimeError("Agent not started. Call start() first.")

        generation = next(self._turn_generation)
        self._active_generation = generation
        self._last_turn_count = 0
        return self._process_message_stream(user_input, generation)

    async def _process_message_stream(
        self,
        user_input: str,
        generation: int,
    ) -> AsyncIterator[dict[str, Any]]:
        self.emitter_bridge.last_user_message = user_input
        frontend_events: list[dict[str, Any]] = []

        def capture_frontend_event(event_type: str, data: dict[str, Any]) -> None:
            if self._is_generation_interrupted(generation):
                return
            frontend_events.append({"event": event_type, "data": dict(data)})

        def drain_frontend_events() -> list[dict[str, Any]]:
            events = [*frontend_events]
            frontend_events.clear()
            return events

        self.emitter_bridge.callback = capture_frontend_event
        user_message = ProviderInputMessage(
            role="user",
            content=[ProviderContentPart(text=user_input)],
        )
        messages: list[ProviderInputMessage] = [*self._history, user_message]
        catalog = WorkflowToolCatalog.for_mode(
            interactive_shipping=self._interactive_shipping,
            bridge=self.emitter_bridge,
        )
        dispatcher = LocalToolDispatcher(
            catalog=catalog,
            policy=RuntimePolicyEngine(
                interactive_shipping=self._interactive_shipping,
            ),
            emit_frontend=capture_frontend_event,
        )
        system_instructions = [ProviderSystemInstruction(content=self._system_prompt)]
        metadata_turn_count: int | None = None
        emitted_tool_call_ids: set[str] = set()
        turn_history_messages: list[ProviderInputMessage] = [user_message]

        try:
            for _provider_turn in range(self._max_turns):
                assistant_parts: list[ProviderContentPart] = []
                tool_calls: list[ProviderToolCall] = []
                try:
                    stream = self._provider.stream_turn(
                        messages=messages,
                        system_instructions=system_instructions,
                        tools=catalog.provider_declarations(),
                    )
                    async for event in stream:
                        if self._is_generation_interrupted(generation):
                            return

                        if (
                            event.type == ProviderStreamEventType.TEXT_DELTA
                            and event.text
                        ):
                            yield {
                                "event": "agent_message_delta",
                                "data": {"text": event.text},
                            }
                        elif (
                            event.type == ProviderStreamEventType.TEXT_BLOCK_COMPLETE
                            and event.text
                        ):
                            if metadata_turn_count is None:
                                self._last_turn_count += 1
                            assistant_parts.append(ProviderContentPart(text=event.text))
                            yield {
                                "event": "agent_message",
                                "data": {"text": event.text},
                            }
                        elif (
                            event.type == ProviderStreamEventType.PROVIDER_OUTPUT_ITEM
                            and event.provider_output_item
                        ):
                            assistant_parts.append(
                                ProviderContentPart(
                                    type="provider_output_item",
                                    provider_output_item=event.provider_output_item,
                                )
                            )
                        elif (
                            event.type == ProviderStreamEventType.TOOL_CALL_COMPLETE
                            and event.tool_call
                        ):
                            tool_calls.append(event.tool_call)
                        elif (
                            event.type == ProviderStreamEventType.RESULT_METADATA
                            and event.metadata
                        ):
                            self.last_result_metadata = event.metadata
                            if event.metadata.num_turns is not None:
                                metadata_turn_count = event.metadata.num_turns
                                self._last_turn_count = event.metadata.num_turns
                        elif event.type == ProviderStreamEventType.PROVIDER_ERROR:
                            yield {
                                "event": "error",
                                "data": {"message": _GENERIC_PROVIDER_ERROR_MESSAGE},
                            }
                            return
                        elif event.type == ProviderStreamEventType.STREAM_COMPLETE:
                            break
                except Exception as exc:
                    if self._is_generation_interrupted(generation):
                        return

                    logger.warning(
                        "Conversation provider stream failed for provider=%s "
                        "exception_type=%s",
                        self._provider.capabilities.provider,
                        type(exc).__name__,
                    )
                    yield {
                        "event": "error",
                        "data": {
                            "message": _GENERIC_PROVIDER_ERROR_MESSAGE,
                        },
                    }
                    return

                unique_tool_calls: list[ProviderToolCall] = []
                for call in tool_calls:
                    if call.call_id is not None:
                        if call.call_id in emitted_tool_call_ids:
                            continue
                        emitted_tool_call_ids.add(call.call_id)
                    unique_tool_calls.append(call)

                if not unique_tool_calls:
                    if assistant_parts:
                        assistant_message = ProviderInputMessage(
                            role="assistant",
                            content=assistant_parts,
                        )
                        messages.append(assistant_message)
                        turn_history_messages.append(assistant_message)
                    self._append_history(turn_history_messages)
                    return

                assistant_message = ProviderInputMessage(
                    role="assistant",
                    content=[
                        *assistant_parts,
                        *(
                            ProviderContentPart(
                                type="tool_call",
                                tool_call=call,
                            )
                            for call in unique_tool_calls
                        ),
                    ],
                )
                messages.append(assistant_message)
                turn_history_messages.append(assistant_message)

                for call in unique_tool_calls:
                    if self._is_generation_interrupted(generation):
                        return

                    dispatcher.emit_tool_call(call)
                    for frontend_event in drain_frontend_events():
                        yield frontend_event

                    result = await dispatcher.execute(call)
                    if self._is_generation_interrupted(generation):
                        frontend_events.clear()
                        return

                    for frontend_event in drain_frontend_events():
                        yield frontend_event

                    tool_result_message = ProviderInputMessage(
                        role="tool",
                        content=[ProviderContentPart(text=result.content)],
                        tool_call_id=result.call_id,
                        metadata={
                            "tool_name": result.tool_name,
                            "structured_payload": result.structured_payload,
                            "is_error": result.is_error,
                        },
                    )
                    messages.append(tool_result_message)
                    turn_history_messages.append(tool_result_message)

            yield {
                "event": "error",
                "data": {
                    "message": (
                        "Conversation exceeded the maximum provider turn count."
                    )
                },
            }
        finally:
            if self.emitter_bridge.callback is capture_frontend_event:
                self.emitter_bridge.callback = None

    async def interrupt(self) -> None:
        self._interrupted_generations.add(self._active_generation)
        if self._provider.capabilities.supports_cancellation:
            try:
                await self._provider.cancel()
            except Exception as exc:
                logger.warning(
                    "Provider cancel failed for provider=%s exception_type=%s",
                    self._provider.capabilities.provider,
                    type(exc).__name__,
                )

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def last_turn_count(self) -> int:
        return self._last_turn_count

    def _is_generation_interrupted(self, generation: int) -> bool:
        return generation in self._interrupted_generations

    def _append_history(self, messages: list[ProviderInputMessage]) -> None:
        if not messages:
            return
        self._history = [
            *self._history,
            *messages,
        ][-_MAX_PROVIDER_HISTORY_MESSAGES:]


def _build_provider_history(
    prior_conversation: list[dict[str, Any]] | None,
    *,
    limit: int,
) -> list[ProviderInputMessage]:
    if not prior_conversation:
        return []

    history: list[ProviderInputMessage] = []
    for message in prior_conversation:
        role = message.get("role")
        content = message.get("content")
        if role not in _HISTORY_ROLES or not isinstance(content, str) or not content:
            continue
        history.append(
            ProviderInputMessage(
                role=role,
                content=[ProviderContentPart(text=content)],
            )
        )
    return history[-limit:]
