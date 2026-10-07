"""Provider-neutral conversation agent boundary."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# These historical selectors remain configuration aliases only. Every real
# provider runs in the ShipAgent-owned runtime.
_ANTHROPIC_MESSAGES_RUNTIMES = {"anthropic", "anthropic_messages", "anthropic-messages"}
_DEPRECATED_CLAUDE_RUNTIMES = {"claude", "claude_sdk"}


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


def resolve_conversation_model(model: str | None, runtime: str) -> str | None:
    """Snapshot provider defaults before any asynchronous lifecycle work."""
    provider = _infer_model_provider(model)
    if provider == "openai" or (model is None and runtime == "openai"):
        from src.services.conversation_runtime.openai_provider import (
            resolve_openai_model,
        )

        return "openai:" + resolve_openai_model(model)
    if provider == "gemini" or (model is None and runtime == "gemini"):
        from src.services.conversation_runtime.gemini_provider import (
            resolve_gemini_model,
        )

        return "gemini:" + resolve_gemini_model(model)
    if model is None and runtime in (
        {"", "auto"} | _ANTHROPIC_MESSAGES_RUNTIMES | _DEPRECATED_CLAUDE_RUNTIMES
    ):
        from src.services.conversation_runtime.anthropic_provider import (
            resolve_anthropic_model,
        )

        return "anthropic:" + resolve_anthropic_model(None)
    return model


def create_conversation_agent(
    *,
    system_prompt: str | None = None,
    max_turns: int = 50,
    model: str | None = None,
    runtime: str | None = None,
    interactive_shipping: bool = False,
    session_id: str | None = None,
    prior_conversation: list[dict[str, Any]] | None = None,
) -> ConversationAgent:
    """Create the configured conversation runtime behind a neutral interface."""
    runtime = (
        (
            runtime
            if runtime is not None
            else os.environ.get("SHIPAGENT_AGENT_RUNTIME", "auto")
        )
        .strip()
        .lower()
    )
    model = model or os.environ.get("AGENT_MODEL") or os.environ.get("ANTHROPIC_MODEL")
    model_provider = _infer_model_provider(model)
    if runtime == "fake":
        from src.services.conversation_runtime.fake_provider import FakeProviderClient
        from src.services.conversation_runtime.runtime_session import (
            ConversationRuntimeSession,
        )

        return ConversationRuntimeSession(
            provider=FakeProviderClient(script=[]),
            system_prompt=system_prompt,
            interactive_shipping=interactive_shipping,
            session_id=session_id,
            max_turns=max_turns,
            prior_conversation=prior_conversation,
        )

    if runtime in _DEPRECATED_CLAUDE_RUNTIMES:
        logger.warning(
            "Runtime selector '%s' is deprecated; use 'anthropic' or 'auto'.", runtime
        )

    provider_name = None
    if runtime in {"", "auto"}:
        provider_name = model_provider if model else "anthropic"
    elif runtime in _ANTHROPIC_MESSAGES_RUNTIMES | _DEPRECATED_CLAUDE_RUNTIMES:
        if model and model_provider != "anthropic":
            if model_provider is not None and runtime in _DEPRECATED_CLAUDE_RUNTIMES:
                return _runtime_model_mismatch(
                    runtime=runtime,
                    model_provider=model_provider,
                    session_id=session_id,
                    model=model,
                )
            return _anthropic_model_mismatch(
                runtime=runtime, session_id=session_id, model=model
            )
        provider_name = "anthropic"
    elif runtime in {"openai", "gemini"}:
        if model and model_provider != runtime:
            return _runtime_model_mismatch(
                runtime=runtime,
                model_provider=model_provider,
                session_id=session_id,
                model=model,
            )
        provider_name = runtime

    factories = {
        "anthropic": _create_anthropic_conversation_agent,
        "openai": _create_openai_conversation_agent,
        "gemini": _create_gemini_conversation_agent,
    }
    factory = factories.get(provider_name)
    if factory is not None:
        return factory(
            system_prompt=system_prompt,
            interactive_shipping=interactive_shipping,
            session_id=session_id,
            max_turns=max_turns,
            prior_conversation=prior_conversation,
            model=model,
        )

    logger.warning("No supported model runtime configured")
    return UnavailableConversationAgent(
        reason=(
            "No supported model runtime is configured. Choose a supported "
            "AGENT_MODEL and matching SHIPAGENT_AGENT_RUNTIME before sending "
            "shipping commands."
        ),
        session_id=session_id,
        model=model,
    )


def _create_openai_conversation_agent(
    *,
    system_prompt: str | None,
    interactive_shipping: bool,
    session_id: str | None,
    max_turns: int,
    prior_conversation: list[dict[str, Any]] | None,
    model: str | None,
) -> ConversationAgent:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return UnavailableConversationAgent(
            reason=(
                "OpenAI API key is not configured. Add OPENAI_API_KEY in "
                "Settings before sending shipping commands."
            ),
            session_id=session_id,
            model=model,
        )
    try:
        from src.services.conversation_runtime.openai_provider import (
            OpenAIProviderClient,
        )
        from src.services.conversation_runtime.runtime_session import (
            ConversationRuntimeSession,
        )

        provider = OpenAIProviderClient(model=model, api_key=api_key)
    except RuntimeError as exc:
        return UnavailableConversationAgent(
            reason=str(exc),
            session_id=session_id,
            model=model,
        )

    return ConversationRuntimeSession(
        provider=provider,
        system_prompt=system_prompt,
        interactive_shipping=interactive_shipping,
        session_id=session_id,
        max_turns=max_turns,
        prior_conversation=prior_conversation,
    )


def _create_anthropic_conversation_agent(
    *,
    system_prompt: str | None,
    interactive_shipping: bool,
    session_id: str | None,
    max_turns: int,
    prior_conversation: list[dict[str, Any]] | None,
    model: str | None,
) -> ConversationAgent:
    from src.services.conversation_runtime.anthropic_provider import (
        AnthropicProviderClient,
    )
    from src.services.conversation_runtime.runtime_session import (
        ConversationRuntimeSession,
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    try:
        provider = AnthropicProviderClient(model=model, api_key=api_key)
    except RuntimeError as exc:
        return UnavailableConversationAgent(
            reason=str(exc),
            session_id=session_id,
            model=model,
        )

    return ConversationRuntimeSession(
        provider=provider,
        system_prompt=system_prompt,
        interactive_shipping=interactive_shipping,
        session_id=session_id,
        max_turns=max_turns,
        prior_conversation=prior_conversation,
    )


def _create_gemini_conversation_agent(
    *,
    system_prompt: str | None,
    interactive_shipping: bool,
    session_id: str | None,
    max_turns: int,
    prior_conversation: list[dict[str, Any]] | None,
    model: str | None,
) -> ConversationAgent:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return UnavailableConversationAgent(
            reason=(
                "Gemini API key is not configured. Add GEMINI_API_KEY in "
                "Settings before sending shipping commands."
            ),
            session_id=session_id,
            model=model,
        )
    try:
        from src.services.conversation_runtime.gemini_provider import (
            GeminiProviderClient,
        )
        from src.services.conversation_runtime.runtime_session import (
            ConversationRuntimeSession,
        )

        provider = GeminiProviderClient(model=model, api_key=api_key)
    except RuntimeError as exc:
        return UnavailableConversationAgent(
            reason=str(exc),
            session_id=session_id,
            model=model,
        )

    return ConversationRuntimeSession(
        provider=provider,
        system_prompt=system_prompt,
        interactive_shipping=interactive_shipping,
        session_id=session_id,
        max_turns=max_turns,
        prior_conversation=prior_conversation,
    )


def _runtime_model_mismatch(
    *,
    runtime: str,
    model_provider: str | None,
    session_id: str | None,
    model: str | None,
) -> ConversationAgent:
    return UnavailableConversationAgent(
        reason=(
            f"Configured runtime '{runtime}' does not match selected "
            f"model provider '{model_provider}'. Choose a matching "
            "runtime before sending shipping commands."
        ),
        session_id=session_id,
        model=model,
    )


def _anthropic_model_mismatch(
    *,
    runtime: str,
    session_id: str | None,
    model: str,
) -> ConversationAgent:
    """Actionable error for a non-Claude or alias model under the Anthropic runtime.

    ``model`` is operator configuration (Settings/AGENT_MODEL), never a secret.
    """
    return UnavailableConversationAgent(
        reason=(
            f"Configured runtime '{runtime}' requires a full Claude model id "
            f"(for example 'claude-haiku-4-5-20251001'), but the configured "
            f"model is '{model}'. Aliases such as 'haiku' or 'sonnet' and "
            "other providers' models are not supported by this runtime. Update "
            "the agent model in Settings or AGENT_MODEL."
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
