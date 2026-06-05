"""Provider-neutral conversation agent boundary."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class ConversationAgent(Protocol):
    """Runtime-agnostic interface used by conversation sessions."""

    emitter_bridge: Any

    async def start(self) -> None:
        """Start any runtime resources required by the agent."""

    async def stop(self, timeout: float = 5.0) -> None:
        """Stop runtime resources."""

    async def process_command(self, user_input: str) -> str:
        """Process one message and return a complete response."""

    async def process_message_stream(
        self,
        user_input: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Process one message and stream SSE-compatible events."""

    async def interrupt(self) -> None:
        """Interrupt in-flight work if supported."""

    @property
    def is_started(self) -> bool:
        """Whether the agent has started."""

    @property
    def last_turn_count(self) -> int:
        """Assistant turns from the last request."""


@dataclass
class ConversationEventBridge:
    """Minimal bridge shape shared by runtime adapters and SSE routes."""

    session_id: str | None = None
    callback: Any | None = None
    last_user_message: str | None = None
    last_shipping_command: str | None = None
    confirmed_resolutions: dict[str, Any] = field(default_factory=dict)

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an artifact/tool event when a route callback is attached."""
        if self.callback is not None:
            self.callback(event_type, data)


class UnavailableConversationAgent:
    """Agent used when no supported model runtime is configured."""

    def __init__(
        self,
        *,
        reason: str,
        session_id: str | None = None,
        model: str | None = None,
    ) -> None:
        self.reason = reason
        self._model = model
        self.emitter_bridge = ConversationEventBridge(session_id=session_id)
        self._started = False

    async def start(self) -> None:
        self._started = True

    async def stop(self, timeout: float = 5.0) -> None:
        self._started = False

    async def process_command(self, user_input: str) -> str:
        return self.reason

    async def process_message_stream(
        self,
        user_input: str,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"event": "error", "data": {"message": self.reason}}

    async def interrupt(self) -> None:
        return None

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def last_turn_count(self) -> int:
        return 0


def create_conversation_agent(
    *,
    system_prompt: str | None = None,
    max_turns: int = 50,
    permission_mode: str = "acceptEdits",
    model: str | None = None,
    interactive_shipping: bool = False,
    session_id: str | None = None,
) -> ConversationAgent:
    """Create the configured conversation runtime behind a neutral interface."""
    runtime = os.environ.get("SHIPAGENT_AGENT_RUNTIME", "auto").strip().lower()
    model_provider = _infer_model_provider(model)
    if runtime in {"", "auto"} and model_provider in {"openai", "gemini"}:
        return UnavailableConversationAgent(
            reason=(
                f"{model_provider.title()} model runtime is not wired yet. "
                "Choose a configured runtime before sending shipping commands."
            ),
            session_id=session_id,
            model=model,
        )
    if runtime in {"openai", "gemini"}:
        return UnavailableConversationAgent(
            reason=(
                f"{runtime.title()} model runtime is not wired yet. "
                "Choose a configured runtime before sending shipping commands."
            ),
            session_id=session_id,
            model=model,
        )

    if runtime in {"", "auto", "claude", "claude_sdk", "anthropic"}:
        if runtime not in {"", "auto"} and model_provider in {"openai", "gemini"}:
            return UnavailableConversationAgent(
                reason=(
                    f"Configured runtime '{runtime}' does not match selected "
                    f"model provider '{model_provider}'. Choose a matching "
                    "runtime before sending shipping commands."
                ),
                session_id=session_id,
                model=model,
            )

        from src.orchestrator.agent.client import (
            OrchestrationAgent,
            is_claude_sdk_available,
        )

        if is_claude_sdk_available():
            return OrchestrationAgent(
                system_prompt=system_prompt,
                max_turns=max_turns,
                permission_mode=permission_mode,
                model=model,
                interactive_shipping=interactive_shipping,
                session_id=session_id,
            )
        if runtime not in {"", "auto"}:
            return UnavailableConversationAgent(
                reason=(
                    "Claude SDK runtime is not installed. Install the optional "
                    "Claude adapter or choose another configured model runtime."
                ),
                session_id=session_id,
                model=model,
            )

    logger.warning("No supported model runtime configured for model=%s", model)
    return UnavailableConversationAgent(
        reason=(
            "No supported model runtime is configured. Configure a model "
            "provider before sending shipping commands."
        ),
        session_id=session_id,
        model=model,
    )


def _infer_model_provider(model: str | None) -> str | None:
    if not model:
        return None
    normalized = model.strip().lower()
    if normalized.startswith("openai:"):
        return "openai"
    if normalized.startswith("gemini:"):
        return "gemini"
    if normalized.startswith("anthropic:") or normalized.startswith("claude-"):
        return "anthropic"
    return None
