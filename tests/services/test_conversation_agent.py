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
from src.services.conversation_runtime.fake_provider import FakeProviderClient


class StubRuntimeProvider(FakeProviderClient):
    def __init__(self, *, model: str | None = None, api_key: str | None = None):
        _ = model, api_key
        super().__init__(script=[])


def test_openai_model_creates_provider_runtime_in_auto_runtime(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", "auto")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(
        "src.services.conversation_runtime.openai_provider.OpenAIProviderClient",
        StubRuntimeProvider,
    )

    agent = create_conversation_agent(model="openai:default", session_id="openai-sess")

    assert agent.__class__.__name__ == "ConversationRuntimeSession"
    assert agent.emitter_bridge.session_id == "openai-sess"


def test_gemini_model_creates_provider_runtime_in_auto_runtime(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", "auto")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(
        "src.services.conversation_runtime.gemini_provider.GeminiProviderClient",
        StubRuntimeProvider,
    )

    agent = create_conversation_agent(model="gemini:default", session_id="gemini-sess")

    assert agent.__class__.__name__ == "ConversationRuntimeSession"
    assert agent.emitter_bridge.session_id == "gemini-sess"


@pytest.mark.parametrize(
    ("model", "key_name", "reason"),
    [
        ("openai:default", "OPENAI_API_KEY", "OpenAI API key is not configured"),
        ("gemini:default", "GEMINI_API_KEY", "Gemini API key is not configured"),
    ],
)
def test_provider_runtime_requires_matching_api_key(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    key_name: str,
    reason: str,
):
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", "auto")
    monkeypatch.delenv(key_name, raising=False)

    agent = create_conversation_agent(model=model)

    assert isinstance(agent, UnavailableConversationAgent)
    assert reason in agent.reason


def test_fake_runtime_creates_conversation_runtime_session(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", "fake")

    agent = create_conversation_agent(
        system_prompt="system",
        model="fake:default",
        interactive_shipping=False,
        session_id="fake-session",
    )

    assert agent.__class__.__name__ == "ConversationRuntimeSession"
    assert agent.emitter_bridge.session_id == "fake-session"


def test_provider_neutral_runtime_does_not_expose_raw_ups_mcp_tool(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", "fake")

    from src.services.conversation_runtime.tool_catalog import WorkflowToolCatalog

    for interactive in (False, True):
        catalog = WorkflowToolCatalog.for_mode(interactive_shipping=interactive)
        assert all(not tool.name.startswith("mcp__ups__") for tool in catalog.tools)


@pytest.mark.parametrize(
    ("runtime", "key_name", "patch_path"),
    [
        (
            "openai",
            "OPENAI_API_KEY",
            "src.services.conversation_runtime.openai_provider.OpenAIProviderClient",
        ),
        (
            "gemini",
            "GEMINI_API_KEY",
            "src.services.conversation_runtime.gemini_provider.GeminiProviderClient",
        ),
    ],
)
def test_explicit_provider_runtime_creates_provider_neutral_session(
    monkeypatch: pytest.MonkeyPatch,
    runtime: str,
    key_name: str,
    patch_path: str,
):
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", runtime)
    monkeypatch.setenv(key_name, "test-key")
    monkeypatch.setattr(patch_path, StubRuntimeProvider)

    agent = create_conversation_agent(model=f"{runtime}:default")

    assert agent.__class__.__name__ == "ConversationRuntimeSession"


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
