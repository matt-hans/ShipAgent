"""One-shot session-bound upload grants created by the user's upload form.

Attachment IDs bind the exact bytes and selected type without placing either
in model context. Replacing a file invalidates its prior ID; consuming removes
it before the carrier call, including when that call fails ambiguously.
"""
from copy import deepcopy
from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import uuid4

_ATTACHMENT_TTL_SECONDS = 600


@dataclass(frozen=True)
class _Attachment:
    attachment_id: str
    data: dict[str, Any]
    expires_at: float
    gateway: Any


_store: dict[str, _Attachment] = {}
_upload_requests: dict[str, str] = {}


class UploadUnavailableError(ValueError):
    """The upload was replaced or its conversation ended while connecting."""


def begin_upload(session_id: str) -> str:
    """Revoke previous grants and reserve this user gesture before any await."""
    clear(session_id)
    request_id = uuid4().hex
    _upload_requests[session_id] = request_id
    return request_id


def stage(session_id: str, data: dict[str, Any], *, gateway: Any = None) -> str:
    """Capture a user-approved upload and replace any older pending file."""
    attachment_id = uuid4().hex
    _store[session_id] = _Attachment(
        attachment_id,
        deepcopy(data),
        monotonic() + _ATTACHMENT_TTL_SECONDS,
        gateway,
    )
    return attachment_id


async def stage_for_upload(
    session_id: str, data: dict[str, Any], *, request_id: str
) -> str:
    """Bind the user's upload gesture to its original carrier connection."""
    from src.services.gateway_provider import get_ups_gateway

    gateway = await get_ups_gateway()
    if _upload_requests.get(session_id) != request_id:
        raise UploadUnavailableError("Upload was replaced or the conversation ended.")
    _upload_requests.pop(session_id)
    return stage(session_id, data, gateway=gateway)


def has_pending(session_id: str, attachment_id: str) -> bool:
    """Check a grant before acquiring a carrier connection; reveal no file data."""
    attachment = _store.get(session_id)
    return bool(
        attachment
        and attachment.attachment_id == attachment_id
        and attachment.expires_at > monotonic()
    )


def consume(
    session_id: str, attachment_id: str | None = None, *, gateway: Any = None
) -> dict[str, Any] | None:
    """Consume once; a wrong/old ID never consumes the replacement attachment."""
    attachment = _store.get(session_id)
    if attachment is None:
        return None
    if attachment.expires_at <= monotonic():
        clear(session_id)
        return None
    if attachment_id is not None and attachment.attachment_id != attachment_id:
        return None
    _store.pop(session_id)
    if gateway is not None and gateway is not attachment.gateway:
        return None
    return deepcopy(attachment.data)


def clear(session_id: str) -> None:
    """Revoke a pending upload, for example when its session is ended."""
    _store.pop(session_id, None)
    _upload_requests.pop(session_id, None)
