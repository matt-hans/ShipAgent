"""Session-keyed attachment staging for document uploads.

Stores file data (base64-encoded) in memory, keyed by session_id.
Consumed once by the tool handler to prevent context bloat — the base64
content never enters the LLM conversation window.
"""

from typing import Any

_store: dict[str, dict[str, Any]] = {}


def stage(session_id: str, data: dict[str, Any]) -> None:
    """Stage an attachment for the next tool call.

    Overwrites any previously staged attachment for this session.

    Args:
        session_id: Conversation session ID.
        data: Attachment data dict (file_content_base64, file_name, etc.).
    """
    _store[session_id] = data


def consume(session_id: str) -> dict[str, Any] | None:
    """Pop and return the pending attachment (one-shot).

    Returns None if no attachment is staged for this session.

    Args:
        session_id: Conversation session ID.

    Returns:
        Attachment data dict, or None.
    """
    return _store.pop(session_id, None)


def clear(session_id: str) -> None:
    """Remove any staged attachment for a session without consuming it.

    Args:
        session_id: Conversation session ID.
    """
    _store.pop(session_id, None)
