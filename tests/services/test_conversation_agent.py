"""Tests for provider-neutral conversation agent runtime selection."""

from __future__ import annotations

import builtins
from typing import Any
from unittest.mock import patch

import pytest

from src.services.conversation_agent import (
    UnavailableConversationAgent,
    create_conversation_agent,
)


def test_openai_model_fails_closed_in_auto_runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", "auto")

    agent = create_conversation_agent(model="openai:default")

    assert isinstance(agent, UnavailableConversationAgent)
    assert "Openai model runtime is not wired yet" in agent.reason


def test_gemini_model_fails_closed_in_auto_runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", "auto")

    agent = create_conversation_agent(model="gemini:default")

    assert isinstance(agent, UnavailableConversationAgent)
    assert "Gemini model runtime is not wired yet" in agent.reason


@pytest.mark.parametrize("runtime", ["openai", "gemini"])
def test_explicit_unwired_runtime_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    runtime: str,
):
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", runtime)

    agent = create_conversation_agent(model=f"{runtime}:default")

    assert isinstance(agent, UnavailableConversationAgent)
    assert f"{runtime.title()} model runtime is not wired yet" in agent.reason


@pytest.mark.parametrize("model", ["openai:default", "gemini:default"])
def test_claude_runtime_model_mismatch_fails_before_adapter_import(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
):
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", "claude")
    real_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "src.orchestrator.agent.client":
            raise AssertionError("Claude adapter should not be imported")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    agent = create_conversation_agent(model=model)

    assert isinstance(agent, UnavailableConversationAgent)
    assert "does not match selected model provider" in agent.reason


def test_claude_runtime_fails_closed_when_optional_sdk_unavailable(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", "claude")

    with patch(
        "src.orchestrator.agent.client.is_claude_sdk_available",
        return_value=False,
    ):
        agent = create_conversation_agent(model="claude-haiku-4-5-20251001")

    assert isinstance(agent, UnavailableConversationAgent)
    assert "Claude SDK runtime is not installed" in agent.reason
