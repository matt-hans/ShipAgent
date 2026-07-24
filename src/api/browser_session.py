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
BROWSER_CSRF_HEADER = "X-CSRF-Token"

_CLOCK_SKEW_SECONDS = 60
_TOKEN_VERSION = "v1"
_SIGNATURE_BYTES = hashlib.sha256().digest_size
_MAX_TOKEN_LENGTH = 512
_CSRF_TOKEN_VERSION = "v1"
_CSRF_DOMAIN = b"shipagent.browser.csrf.v1\x00"
_MAX_CSRF_TOKEN_LENGTH = 64


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


def derive_browser_csrf_token(session_token: str, api_key: str) -> str:
    """Derive a bounded CSRF token bound to the complete signed session."""
    if (
        not isinstance(session_token, str)
        or not session_token
        or len(session_token) > _MAX_TOKEN_LENGTH
        or not api_key
    ):
        raise ValueError("CSRF derivation requires a bounded session and API key")

    digest = hmac.new(
        api_key.encode("utf-8"),
        _CSRF_DOMAIN + session_token.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{_CSRF_TOKEN_VERSION}.{_encode(digest)}"


def verify_browser_csrf_token(
    candidate: str | None,
    session_token: str | None,
    api_key: str,
) -> bool:
    """Constant-time verify a CSRF token against the exact browser session."""
    if (
        not isinstance(candidate, str)
        or not candidate
        or len(candidate) > _MAX_CSRF_TOKEN_LENGTH
        or not isinstance(session_token, str)
    ):
        return False

    try:
        expected = derive_browser_csrf_token(session_token, api_key)
    except (UnicodeEncodeError, ValueError):
        return False
    return hmac.compare_digest(candidate, expected)
