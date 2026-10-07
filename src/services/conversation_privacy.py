"""Shared visibility policy at conversation boundaries (ADR 0007).

User/assistant text is provider-originated. Local UI artifacts are not text
history, even when persisted with an assistant role. Local recipient data stays
available to deterministic handlers and the owner-facing UI.
"""

from typing import Any

from src.utils.redaction import sanitize_error_message


def provider_authored_text(value: str) -> str:
    """Keep permitted authored addresses, excluding explicitly labeled secrets."""
    return sanitize_error_message(value, max_length=max(len(value), 1)) or ""


def provider_conversation_history(
    messages: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """Project only authored conversation text, never artifact/private metadata."""
    return [
        {"role": message["role"], "content": provider_authored_text(message["content"])}
        for message in messages or []
        if message.get("role") in {"user", "assistant"}
        and message.get("message_type", "text") == "text"
        and isinstance(message.get("content"), str)
        and message["content"]
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
