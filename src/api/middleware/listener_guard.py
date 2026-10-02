"""Per-request enforcement of the desktop non-loopback API-key gate.

Desktop/API-key security only (ADR 0001): hosted Auth0 identity is separate.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from src.api.middleware.auth import get_expected_api_key, is_strong_api_key
from src.utils.network import is_non_loopback_peer

logger = logging.getLogger(__name__)

# Minimal liveness/readiness probes stay reachable. They return only a binary
# status to unauthenticated or keyless-remote callers (see main._is_request_authenticated).
_PROBE_PATHS = ("/health", "/readyz")


def is_remote_scope(scope: dict) -> bool:
    """Return True if the ASGI server or client socket address is non-loopback."""
    return is_non_loopback_peer(scope.get("server")) or is_non_loopback_peer(
        scope.get("client")
    )


async def enforce_effective_listener_security(request: Request, call_next) -> Response:
    """Reject requests on non-loopback sockets unless a strong API key is set.

    Uses the socket addresses uvicorn reports (ASGI ``server``/``client``), so a
    direct ``uvicorn --host 0.0.0.0`` launch is gated without trusting env vars.
    """
    if request.url.path in _PROBE_PATHS:
        return await call_next(request)
    if is_remote_scope(request.scope) and not is_strong_api_key(get_expected_api_key()):
        logger.error(
            "listener_guard_rejected reason=non_loopback_without_strong_api_key"
        )
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Non-loopback listeners require a strong SHIPAGENT_API_KEY. "
                    "Set one (32+ characters) or bind to 127.0.0.1."
                )
            },
        )
    return await call_next(request)
