"""Shared visibility policy at conversation boundaries (ADR 0007).

User/assistant text is provider-originated. Local UI artifacts are not text
history, even when persisted with an assistant role. Local recipient data stays
available to deterministic handlers and the owner-facing UI.
"""

from typing import Any

from src.utils.redaction import project_public_artifact


def provider_authored_text(value: str) -> str:
    """Keep permitted authored addresses, excluding explicitly labeled secrets."""
    return project_public_artifact(value)


def provider_conversation_history(
    messages: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """Project only authored conversation text, never artifact/private metadata."""

    def turn_metadata(message: dict[str, Any]) -> dict[str, Any]:
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            return {}
        turn_id = metadata.get("conversation_turn_id")
        if not isinstance(turn_id, str):
            return {}
        return metadata

    # Physical persistence order follows ingress arrival, which can precede the
    # previous turn's answer. Restore authored order by trusted turn identity.
    # Legacy records remain in their original order. Artifacts never participate.
    authored = [
        message
        for message in messages or []
        if message.get("role") in {"user", "assistant"}
        and message.get("message_type", "text") == "text"
        and isinstance(message.get("content"), str)
        and message["content"]
    ]
    linked: dict[str, list[dict[str, Any]]] = {}
    user_ids = {
        turn_metadata(m).get("conversation_turn_id")
        for m in authored
        if m.get("role") == "user" and isinstance(m.get("metadata"), dict)
    }
    for message in authored:
        meta = turn_metadata(message)
        turn_id = meta.get("conversation_turn_id")
        if message["role"] == "assistant" and turn_id in user_ids and turn_id:
            linked.setdefault(turn_id, []).append(message)
    ordered = []
    for message in authored:
        meta = turn_metadata(message)
        turn_id = meta.get("conversation_turn_id")
        if meta.get("conversation_turn_state") == "queued":
            continue
        if message["role"] == "assistant" and turn_id in linked:
            continue
        ordered.append(message)
        if message["role"] == "user" and turn_id:
            ordered.extend(linked.get(turn_id, []))
    return [
        {"role": m["role"], "content": provider_authored_text(m["content"])}
        for m in ordered
    ]


# Only trusted workflow code selects these codes. A handler's exception text or
# a model-supplied origin/error marker never becomes user-visible safe text.
SAFE_TOOL_ERROR_MESSAGES = {
    "CONTACT_NOT_FOUND": "Contact not found. Choose a saved contact in the address book or provide an explicit address.",
    "CONTACT_EXACT_HANDLE_REQUIRED": "Use an exact handle from the address book; a prefix cannot select a shipment recipient.",
    "CONTACT_ADDRESS_CONFLICT": "Provide either ship_to_handle or an explicit recipient address, not both.",
    "CONTACT_ROLE_INVALID": "This contact is not enabled as a shipment recipient. Choose another contact in the address book.",
    "CONTACT_LOOKUP_FAILED": "The saved contact could not be loaded. Check the address book and retry.",
}

MAX_PUBLIC_TEXT_BLOCK_CHARS = 65536
TEXT_BLOCK_PRIVACY_ERROR = "The provider returned an incomplete or oversized text block. Retry with a shorter request."


class TextBlockPrivacyError(ValueError):
    """A provider block cannot be safely released to public output."""


class PublicTextBlock:
    """Hold publication until a complete block can be projected safely.

    Adapters already assemble complete text, so this guard retains only the
    accumulated length, never a second raw copy. Tool/progress events are
    independent. Partial text is discarded on failure or interruption.
    """

    def __init__(self) -> None:
        self.length = 0

    def observe(self, delta: str) -> None:
        self.length += len(delta)
        if self.length > MAX_PUBLIC_TEXT_BLOCK_CHARS:
            raise TextBlockPrivacyError(TEXT_BLOCK_PRIVACY_ERROR)

    def complete(self, text: str) -> tuple[str, bool]:
        if len(text) > MAX_PUBLIC_TEXT_BLOCK_CHARS:
            raise TextBlockPrivacyError(TEXT_BLOCK_PRIVACY_ERROR)
        streamed = self.length > 0
        self.length = 0
        return provider_authored_text(text), streamed
