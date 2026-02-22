"""Optional API-key auth middleware for local/prod deployments.

Security note (F-1): This middleware provides API-key authentication
(shared secret) but not per-user authorization. All authenticated
requests share the same privilege level. For multi-user deployments,
add user-scoped tokens (e.g. JWT), enforce row-level access control
on Job/Session queries, and validate ownership before mutations.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Request
from fastapi.responses import JSONResponse, Response

_PUBLIC_PATH_PREFIXES = (
    "/health",
    "/readyz",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/assets/",
    "/static/",
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
    """FastAPI middleware entrypoint for optional API-key auth."""
    if request.method.upper() == "OPTIONS":
        return await call_next(request)

    expected_key = get_expected_api_key()
    if not expected_key or not should_authenticate(request.url.path):
        return await call_next(request)

    provided_key = request.headers.get("X-API-Key", "")
    if not provided_key or not hmac.compare_digest(provided_key, expected_key):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing API key"},
        )
    return await call_next(request)
