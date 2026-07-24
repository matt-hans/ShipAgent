"""Signed, short-lived browser sessions for API-key deployments."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import time

BROWSER_SESSION_COOKIE = "shipagent_browser_session"
BROWSER_SESSION_TTL_SECONDS = 8 * 60 * 60

_CLOCK_SKEW_SECONDS = 60
_TOKEN_VERSION = "v1"
_SIGNATURE_BYTES = hashlib.sha256().digest_size
_MAX_TOKEN_LENGTH = 512


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def issue_browser_session(api_key: str, now: int | None = None) -> str:
    """Issue a key-bound browser session token with a fixed eight-hour lifetime."""
    if not api_key:
        raise ValueError("browser sessions require a configured API key")

    issued_at = int(time.time()) if now is None else now
    expires_at = issued_at + BROWSER_SESSION_TTL_SECONDS
    nonce = secrets.token_urlsafe(18)
    payload = f"{_TOKEN_VERSION}.{issued_at}.{expires_at}.{nonce}"
    signature = hmac.new(
        api_key.encode("utf-8"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{payload}.{_encode(signature)}"


def verify_browser_session(
    token: str | None,
    api_key: str,
    now: int | None = None,
) -> bool:
    """Return whether an untrusted token is valid for the configured API key."""
    if (
        not isinstance(token, str)
        or not token
        or not api_key
        or len(token) > _MAX_TOKEN_LENGTH
    ):
        return False

    try:
        version, issued_raw, expires_raw, nonce, signature_raw = token.split(".")
        issued_at = int(issued_raw)
        expires_at = int(expires_raw)
        signature = _decode(signature_raw)
    except (binascii.Error, TypeError, ValueError):
        return False

    current = int(time.time()) if now is None else now
    if (
        version != _TOKEN_VERSION
        or not nonce
        or issued_at < 0
        or issued_at > current + _CLOCK_SKEW_SECONDS
        or expires_at <= current
        or expires_at - issued_at != BROWSER_SESSION_TTL_SECONDS
        or len(signature) != _SIGNATURE_BYTES
    ):
        return False

    payload = f"{version}.{issued_at}.{expires_at}.{nonce}"
    expected_signature = hmac.new(
        api_key.encode("utf-8"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return hmac.compare_digest(signature, expected_signature)
