"""Closed source-free control messages; model prose never becomes host output."""

import json
from collections.abc import AsyncIterator

from src.services.conversation_runtime.models import (
    ModelProviderClient,
    ProviderCapabilities,
    ProviderInputMessage,
    ProviderStreamEvent,
    ProviderStreamEventType,
    ProviderSystemInstruction,
    ProviderToolDeclaration,
)
from src.services.conversation_runtime.stream_cleanup import close_owned_stream

CLARIFICATION_QUESTIONS = {
    "shipping_goal": "What shipping task would you like to plan?",
    "package_scope": "Are you planning one package or multiple packages?",
    "service_preference": "What delivery speed would you like to plan for?",
}


def clarification_code(blocks: list[str]) -> str | None:
    """Return a known complete control object, or keep plain prose private."""
    if len(blocks) != 1:
        raise ValueError("Planning output is unavailable.")
    text = blocks[0]
    if not text.lstrip().startswith("{"):
        return None
    if len(text) > 256:
        raise ValueError("Planning output is unavailable.")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Planning output is unavailable.")
            result[key] = value
        return result

    value = json.loads(text, object_pairs_hook=unique_object)
    if (
        not isinstance(value, dict)
        or set(value) != {"clarification_code"}
        or not isinstance(value["clarification_code"], str)
        or value["clarification_code"] not in CLARIFICATION_QUESTIONS
    ):
        raise ValueError("Planning output is unavailable.")
    return value["clarification_code"]


def public_clarification(code: str) -> dict[str, str]:
    return {"code": code, "question": CLARIFICATION_QUESTIONS[code]}


class ClarificationProvider:
    """Validate the raw control block before ordinary privacy text projection.

    Projection may normalize JSON or suppress malformed structured text. Neither
    operation is allowed to repair a control message into follow-up authority.
    The shared runtime still owns generation, dispatch, terminal proof and stop;
    this decorator only validates events and forwards cancellation to its owner.
    """

    def __init__(self, provider: ModelProviderClient) -> None:
        self._provider = provider
        self._blocks = 0
        self.clarification: str | None = None

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._provider.capabilities

    async def stream_turn(
        self,
        *,
        messages: list[ProviderInputMessage],
        system_instructions: list[ProviderSystemInstruction],
        tools: list[ProviderToolDeclaration],
    ) -> AsyncIterator[ProviderStreamEvent]:
        stream = self._provider.stream_turn(
            messages=messages, system_instructions=system_instructions, tools=tools
        )
        try:
            async for event in stream:
                if event.type == ProviderStreamEventType.TEXT_BLOCK_COMPLETE:
                    self._blocks += 1
                    if self._blocks > 1:
                        raise ValueError("Planning output is unavailable.")
                    self.clarification = clarification_code([event.text or ""])
                yield event
        finally:
            await close_owned_stream(stream)

    async def cancel(self) -> None:
        await self._provider.cancel()
