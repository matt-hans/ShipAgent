"""Tests for prior conversation injection in system prompt."""

from src.orchestrator.agent.system_prompt import build_system_prompt


def test_no_prior_conversation_by_default():
    prompt = build_system_prompt()
    assert "Prior Conversation" not in prompt


def test_prior_conversation_injected():
    history = [
        {"role": "user", "content": "Ship CA orders via Ground"},
        {"role": "assistant", "content": "I'll help with that."},
    ]
    prompt = build_system_prompt(prior_conversation=history)
    assert "Prior Conversation" in prompt
    assert "Ship CA orders via Ground" in prompt
    assert "I'll help with that." in prompt


def test_prior_conversation_truncation():
    history = [
        {"role": "user", "content": f"Message {i}"}
        for i in range(50)
    ]
    prompt = build_system_prompt(prior_conversation=history)
    # Should truncate to most recent messages (capped by count + token budget)
    assert "Message 49" in prompt
    assert "Message 0" not in prompt
    assert "earlier messages omitted" in prompt


def test_prior_conversation_token_budget():
    """Long messages should be limited by token budget, not just count."""
    history = [
        {"role": "user", "content": "x" * 2000}  # ~500 tokens each
        for _ in range(30)
    ]
    prompt = build_system_prompt(prior_conversation=history)
    assert "Prior Conversation" in prompt
    # Token budget (~4000 tokens) should cap inclusion before all 30 fit
    assert "earlier messages omitted" in prompt


def test_prior_conversation_empty_list():
    prompt = build_system_prompt(prior_conversation=[])
    assert "Prior Conversation" not in prompt
