from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy

from src.services.conversation_runtime.models import (
    ProviderCapabilities,
    ProviderInputMessage,
    ProviderStreamEvent,
    ProviderSystemInstruction,
    ProviderToolDeclaration,
)


class FakeProviderClient:
    def __init__(
        self,
        *,
        script: list[list[ProviderStreamEvent]],
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        self._script = [list(batch) for batch in script]
        self._capabilities = capabilities or ProviderCapabilities(
            provider="fake",
            model="fake-model",
            supports_streaming_text=True,
            supports_stable_tool_call_ids=True,
            supports_usage_metadata=True,
        )
        self.requests: list[dict[str, object]] = []
        self.cancelled = False

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
        if not self._script:
            raise RuntimeError(
                "FakeProviderClient script exhausted; add a script batch for "
                "this stream_turn call."
            )

        self.requests.append(
            {
                "messages": deepcopy(messages),
                "system_instructions": deepcopy(system_instructions),
                "tools": deepcopy(tools),
            }
        )
        batch = self._script.pop(0)

        async def _stream_events() -> AsyncIterator[ProviderStreamEvent]:
            for event in batch:
                yield event

        return _stream_events()

    async def cancel(self) -> None:
        self.cancelled = True
