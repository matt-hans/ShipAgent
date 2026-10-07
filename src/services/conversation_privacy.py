"""Shared visibility policy at conversation boundaries (ADR 0007).

User/assistant text is provider-originated. Local UI artifacts are not text
history, even when persisted with an assistant role. Local recipient data stays
available to deterministic handlers and the owner-facing UI.
"""

from typing import Any


def provider_conversation_history(
    messages: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """Project only authored conversation text, never artifact/private metadata."""
    return [
        {"role": message["role"], "content": message["content"]}
        for message in messages or []
        if message.get("role") in {"user", "assistant"}
        and message.get("message_type", "text") == "text"
        and isinstance(message.get("content"), str)
        and message["content"]
    ]
