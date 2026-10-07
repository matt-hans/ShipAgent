from __future__ import annotations

import asyncio
import itertools
import json
import logging
from collections.abc import AsyncIterator
from copy import copy
from dataclasses import asdict
from typing import Any

from src.orchestrator.agent.tools.core import EventEmitterBridge
from src.services.conversation_privacy import (
    TEXT_BLOCK_PRIVACY_ERROR,
    PublicTextBlock,
    TextBlockPrivacyError,
    provider_authored_text,
    provider_conversation_history,
)
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
from src.services.conversation_runtime.stream_cleanup import close_owned_stream
from src.services.conversation_runtime.tool_catalog import WorkflowToolCatalog

logger = logging.getLogger(__name__)
_GENERIC_PROVIDER_ERROR_MESSAGE = "Provider error"
_MAX_PROVIDER_HISTORY_MESSAGES = 30
_MAX_PROVIDER_HISTORY_CHARS = 16000
_HISTORY_ROLES = {"user", "assistant"}
CONFLICTING_TOOL_CALL_ID_MESSAGE = (
    "The model reused a tool call ID for a different request. The turn was "
    "stopped before running it; retry the request."
)
MISSING_TOOL_CALL_ID_MESSAGE = (
    "The model returned a tool request without a call ID. The turn was stopped "
    "before running it; retry the request."
)
REPLAYED_TOOL_CALL_ID_MESSAGE = (
    "The model repeated a tool call that already ran. The turn was stopped "
    "without running it again; retry the request."
)


def _call_fingerprint(call: ProviderToolCall) -> tuple[str, str]:
    return (
        call.tool_name,
        json.dumps(call.parsed_input, sort_keys=True, default=str),
    )


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
        self._provider_tasks: dict[int, asyncio.Task[None]] = {}
        self._interrupted_generations: set[int] = set()
        self.last_result_metadata: ProviderResultMetadata | None = None
        self.emitter_bridge = EventEmitterBridge()
        self.emitter_bridge.session_id = session_id
        self._history = _build_provider_history(
            prior_conversation,
            limit=_MAX_PROVIDER_HISTORY_MESSAGES,
        )

        self._history_omitted = len(self._history) < len(
            provider_conversation_history(prior_conversation)
        )

    async def start(self) -> None:
        if self._started:
            raise RuntimeError("Agent already started.")
        self._started = True

    async def stop(self, timeout: float = 5.0) -> None:
        self._started = False
        try:
            await asyncio.wait_for(self.interrupt(), timeout=timeout)
        except TimeoutError:
            logger.warning("Provider cancellation timed out")
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

        self._interrupted_generations.add(self._active_generation)
        old_request = self._provider_tasks.get(self._active_generation)
        if old_request is not None:
            old_request.cancel()
        generation = next(self._turn_generation)
        self._active_generation = generation
        self._last_turn_count = 0
        return self._process_message_stream(user_input, generation)

    async def _process_message_stream(
        self,
        user_input: str,
        generation: int,
    ) -> AsyncIterator[dict[str, Any]]:
        if self._is_generation_interrupted(generation):
            return
        # A late handler must keep its own generation callback, even if a new
        # turn starts before the old carrier/tool operation returns.
        bridge = copy(self.emitter_bridge)
        bridge.last_user_message = user_input
        frontend_events: list[dict[str, Any]] = []

        def capture_frontend_event(event_type: str, data: dict[str, Any]) -> None:
            if self._is_generation_interrupted(generation):
                return
            frontend_events.append({"event": event_type, "data": dict(data)})

        def drain_frontend_events() -> list[dict[str, Any]]:
            events = [*frontend_events]
            frontend_events.clear()
            return events

        bridge.callback = capture_frontend_event
        user_message = ProviderInputMessage(
            role="user",
            content=[ProviderContentPart(text=provider_authored_text(user_input))],
        )
        messages: list[ProviderInputMessage] = [*self._history, user_message]
        catalog = WorkflowToolCatalog.for_mode(
            interactive_shipping=self._interactive_shipping,
            bridge=bridge,
        )
        dispatcher = LocalToolDispatcher(
            catalog=catalog,
            policy=RuntimePolicyEngine(
                interactive_shipping=self._interactive_shipping,
            ),
            emit_frontend=capture_frontend_event,
        )
        system_instructions = [ProviderSystemInstruction(content=self._system_prompt)]
        if self._history_omitted:
            system_instructions.append(
                ProviderSystemInstruction(
                    content="Earlier conversation context was omitted to fit the history budget. Missing context never authorizes execution or retrying prior side effects."
                )
            )
        metadata_turn_count: int | None = None
        emitted_tool_call_ids: dict[str, tuple[str, str]] = {}
        turn_history_messages: list[ProviderInputMessage] = [user_message]
        authored_turn_messages: list[ProviderInputMessage] = [user_message]
        history_committed = False

        try:
            for _provider_turn in range(self._max_turns):
                if metadata_turn_count is None:
                    self._last_turn_count += 1
                assistant_parts: list[ProviderContentPart] = []
                tool_calls: list[ProviderToolCall] = []
                text_block = PublicTextBlock()
                stream = None
                try:
                    stream = self._provider_events(
                        generation=generation,
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
                            text_block.observe(event.text)
                        elif event.type == ProviderStreamEventType.TEXT_BLOCK_COMPLETE:
                            text, streamed = text_block.complete(event.text or "")
                            if not text:
                                continue
                            assistant_parts.append(ProviderContentPart(text=text))
                            authored_turn_messages.append(
                                ProviderInputMessage(
                                    role="assistant",
                                    content=[ProviderContentPart(text=text)],
                                )
                            )
                            if streamed:
                                yield {
                                    "event": "agent_message_delta",
                                    "data": {"text": text},
                                }
                            if self._is_generation_interrupted(generation):
                                return
                            yield {"event": "agent_message", "data": {"text": text}}
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
                            # Only adapter-vetted safe text may replace the
                            # generic message; error_message is never shown.
                            message = event.safe_error_message
                            yield {
                                "event": "error",
                                "data": {
                                    "message": (
                                        message
                                        if isinstance(message, str) and message
                                        else _GENERIC_PROVIDER_ERROR_MESSAGE
                                    )
                                },
                            }
                            return
                        elif event.type == ProviderStreamEventType.STREAM_COMPLETE:
                            break
                    if self._is_generation_interrupted(generation):
                        return
                    if text_block.length:
                        raise TextBlockPrivacyError(TEXT_BLOCK_PRIVACY_ERROR)
                except TextBlockPrivacyError:
                    await self.interrupt()
                    yield {
                        "event": "error",
                        "data": {"message": TEXT_BLOCK_PRIVACY_ERROR},
                    }
                    return
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

                finally:
                    await close_owned_stream(stream)

                if self._is_generation_interrupted(generation):
                    return

                # Nothing runs until every call in the batch is vetted: a call
                # without an ID cannot be paired with its result, a repeated ID
                # with a different request is ambiguous, and a repeat of a call
                # from an earlier turn must not run (or end the turn silently).
                # Exact repeats inside one batch are stream copies and skipped.
                unique_tool_calls: list[ProviderToolCall] = []
                batch_ids: dict[str, tuple[str, str]] = {}
                batch_error: str | None = None
                for call in tool_calls:
                    if not isinstance(call.call_id, str) or not call.call_id:
                        batch_error = MISSING_TOOL_CALL_ID_MESSAGE
                        break
                    fingerprint = _call_fingerprint(call)
                    earlier = emitted_tool_call_ids.get(call.call_id)
                    if earlier is not None:
                        batch_error = (
                            REPLAYED_TOOL_CALL_ID_MESSAGE
                            if earlier == fingerprint
                            else CONFLICTING_TOOL_CALL_ID_MESSAGE
                        )
                        break
                    known = batch_ids.get(call.call_id)
                    if known is not None:
                        if known != fingerprint:
                            batch_error = CONFLICTING_TOOL_CALL_ID_MESSAGE
                            break
                        continue
                    batch_ids[call.call_id] = fingerprint
                    unique_tool_calls.append(call)
                if batch_error is not None:
                    yield {"event": "error", "data": {"message": batch_error}}
                    return
                emitted_tool_call_ids.update(batch_ids)

                if not unique_tool_calls:
                    if assistant_parts:
                        assistant_message = ProviderInputMessage(
                            role="assistant",
                            content=assistant_parts,
                        )
                        messages.append(assistant_message)
                        turn_history_messages.append(assistant_message)
                    self._append_history(turn_history_messages)
                    history_committed = True
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
                        if self._is_generation_interrupted(generation):
                            return
                        yield frontend_event
                        if self._is_generation_interrupted(generation):
                            return

                    if self._is_generation_interrupted(generation):
                        return
                    result = await dispatcher.execute(call)
                    if self._is_generation_interrupted(generation):
                        frontend_events.clear()
                        return

                    for frontend_event in drain_frontend_events():
                        if self._is_generation_interrupted(generation):
                            return
                        yield frontend_event
                        if self._is_generation_interrupted(generation):
                            return

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

            self._append_history(turn_history_messages)
            history_committed = True
            yield {
                "event": "error",
                "data": {
                    "message": (
                        "Conversation exceeded the maximum provider turn count."
                    )
                },
            }
        finally:
            if not history_committed and generation == self._active_generation:
                # Retain completed authored text on errors/interruption without
                # introducing incomplete call/result protocol into the next turn.
                self._append_history(authored_turn_messages)
            bridge.callback = None

    async def _provider_events(
        self, *, generation: int, **kwargs: Any
    ) -> AsyncIterator[Any]:
        """Own the whole transport iteration in one cancellable task/context.

        Cancellation never reaches deterministic tool execution. Keeping one task
        for the entire stream also preserves adapter ContextVar cleanup ownership.
        """
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=1)

        async def read_request() -> None:
            stream = None
            try:
                stream = self._provider.stream_turn(**kwargs)
                async for event in stream:
                    await queue.put(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await queue.put(exc)
            finally:
                await close_owned_stream(stream)
                task = asyncio.current_task()
                if task is not None and task.cancelling():
                    if queue.empty():
                        queue.put_nowait(None)
                else:
                    await queue.put(None)

        request = asyncio.create_task(read_request())
        self._provider_tasks[generation] = request

        def wake_cancelled_reader(task: asyncio.Task[None]) -> None:
            if task.cancelled() and queue.empty():
                queue.put_nowait(None)

        request.add_done_callback(wake_cancelled_reader)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    return
                if isinstance(event, Exception):
                    raise event
                yield event
        finally:
            request.cancel()
            try:
                await request
            except asyncio.CancelledError:
                pass
            if self._provider_tasks.get(generation) is request:
                self._provider_tasks.pop(generation, None)

    async def interrupt(self) -> None:
        self._interrupted_generations.add(self._active_generation)
        request = self._provider_tasks.get(self._active_generation)
        if request is not None:
            request.cancel()

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
        return (
            generation != self._active_generation
            or generation in self._interrupted_generations
        )

    def _append_history(self, messages: list[ProviderInputMessage]) -> None:
        if not messages:
            return
        combined = [*self._history, *messages]
        self._history = _bounded_provider_history(
            combined, limit=_MAX_PROVIDER_HISTORY_MESSAGES
        )
        self._history_omitted |= len(self._history) < len(combined)


def _build_provider_history(
    prior_conversation: list[dict[str, Any]] | None,
    *,
    limit: int,
) -> list[ProviderInputMessage]:
    if not prior_conversation:
        return []

    history: list[ProviderInputMessage] = []
    for message in provider_conversation_history(prior_conversation):
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
    return _bounded_provider_history(history, limit=limit)


def _bounded_provider_history(
    history: list[ProviderInputMessage], *, limit: int
) -> list[ProviderInputMessage]:
    """Keep recent complete user turns within the existing 30-message/4K-token budget.

    Never retain an orphan tool result/private continuation. If even the newest
    completed turn exceeds the budget, omit that whole turn; its durable owner
    transcript and outcomes remain available through the conversation history.
    The active provider loop is not truncated between tool calls and results.
    """
    sizes = [len(json.dumps(asdict(message), default=str)) for message in history]
    start = 0
    while (
        len(history) - start > limit or sum(sizes[start:]) > _MAX_PROVIDER_HISTORY_CHARS
    ):
        next_user = next(
            (
                index
                for index in range(start + 1, len(history))
                if history[index].role == "user"
            ),
            None,
        )
        if next_user is None:
            return []
        start = next_user
    return history[start:]
