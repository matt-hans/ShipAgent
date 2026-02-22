"""Optional API-key auth middleware for local/prod deployments.

Security note (F-11): This middleware provides API-key authentication
(shared secret) but not per-user authorization. All authenticated
requests share the same privilege level. For multi-user deployments,
add user-scoped tokens (e.g. JWT), enforce row-level access control
on Job/Session queries, and validate ownership before mutations.
"""

from __future__ import annotations

import hmac
import logging
import os
import threading
import time

from fastapi import Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

_PUBLIC_PATH_PREFIXES = (
    "/health",
    "/readyz",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/assets/",
    "/static/",
)

# --- Rate limiting for auth failures (F-6, CWE-307) ---
_AUTH_FAIL_MAX = 10  # Max failures per IP in the time window
_AUTH_FAIL_WINDOW_SECONDS = 300  # 5-minute sliding window
_auth_failures: dict[str, list[float]] = {}
_auth_lock = threading.Lock()  # Protects _auth_failures (B-1, CWE-362)

# --- Trusted proxy configuration (H-2, CWE-348) ---
# When SHIPAGENT_TRUST_PROXY is set to "1" or "true", X-Forwarded-For is used
# for client IP extraction. When unset or "0", only request.client.host is used,
# preventing attackers from spoofing IPs to bypass rate limiting.
_TRUST_PROXY = os.environ.get("SHIPAGENT_TRUST_PROXY", "").strip().lower() in ("1", "true")


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request.

    Only uses X-Forwarded-For when SHIPAGENT_TRUST_PROXY is enabled,
    preventing IP spoofing when not behind a trusted reverse proxy (CWE-348).
    """
    if _TRUST_PROXY:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_rate_limited(client_ip: str) -> bool:
    """Check if the client IP has exceeded the auth failure rate limit.

    Thread-safe via _auth_lock (B-1, CWE-362).

    Args:
        client_ip: Client IP address.

    Returns:
        True if the client should be blocked.
    """
    with _auth_lock:
        now = time.monotonic()
        timestamps = _auth_failures.get(client_ip, [])
        # Prune expired entries
        timestamps = [t for t in timestamps if now - t < _AUTH_FAIL_WINDOW_SECONDS]
        _auth_failures[client_ip] = timestamps
        return len(timestamps) >= _AUTH_FAIL_MAX


def _record_auth_failure(client_ip: str) -> None:
    """Record an auth failure for the given client IP.

    Thread-safe via _auth_lock (B-1, CWE-362).

    Args:
        client_ip: Client IP address.
    """
    with _auth_lock:
        now = time.monotonic()
        if client_ip not in _auth_failures:
            _auth_failures[client_ip] = []
        _auth_failures[client_ip].append(now)


def reset_rate_limiter() -> None:
    """Reset the rate limiter state. Used by tests."""
    with _auth_lock:
        _auth_failures.clear()


# --- Key strength validation ---
_MIN_API_KEY_LENGTH = 32


def validate_api_key_strength() -> None:
    """Validate that the configured API key meets minimum strength requirements.

    Called at startup. Raises ValueError if key is set but too short.

    Raises:
        ValueError: If SHIPAGENT_API_KEY is set but shorter than 32 characters.
    """
    key = os.environ.get("SHIPAGENT_API_KEY", "").strip()
    if key and len(key) < _MIN_API_KEY_LENGTH:
        raise ValueError(
            f"SHIPAGENT_API_KEY is too short ({len(key)} chars). "
            f"Minimum length is {_MIN_API_KEY_LENGTH} characters for security."
        )


def get_expected_api_key() -> str:
    """Return configured API key; empty string means auth disabled."""
    return os.environ.get("SHIPAGENT_API_KEY", "").strip()


def _is_public_path(path: str) -> bool:
    return path.startswith(_PUBLIC_PATH_PREFIXES)


def should_authenticate(path: str) -> bool:
    """Return True when this path should be protected by API-key auth."""
    if _is_public_path(path):
        return False
    return path.startswith("/api/")


async def maybe_require_api_key(request: Request, call_next) -> Response:
    """FastAPI middleware entrypoint for optional API-key auth.

    Includes in-process rate limiting (F-6): blocks client IPs that
    exceed _AUTH_FAIL_MAX failures within _AUTH_FAIL_WINDOW_SECONDS.
    """
    if request.method.upper() == "OPTIONS":
        return await call_next(request)

    expected_key = get_expected_api_key()
    if not expected_key or not should_authenticate(request.url.path):
        return await call_next(request)

    client_ip = _get_client_ip(request)

    # Check rate limit before processing the key
    if _is_rate_limited(client_ip):
        logger.warning("Auth rate limit exceeded for IP %s", client_ip)
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many authentication failures. Try again later."},
        )

    provided_key = request.headers.get("X-API-Key", "")
    if not provided_key or not hmac.compare_digest(provided_key, expected_key):
        _record_auth_failure(client_ip)
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing API key"},
        )
    return await call_next(request)
