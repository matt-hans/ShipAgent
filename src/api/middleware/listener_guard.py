"""Per-request enforcement of the desktop non-loopback API-key gate.

Desktop/API-key security only (ADR 0001): hosted Auth0 identity is separate.
"""

from __future__ import annotations

import ipaddress
import logging

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from src.api.middleware.auth import _MIN_API_KEY_LENGTH, get_expected_api_key
from src.utils.network import is_loopback_host

logger = logging.getLogger(__name__)

_UNGUARDED_PATHS = ("/health", "/readyz")


def _is_non_loopback_ip(address: tuple | None) -> bool:
    """Return True if an ASGI (host, port) tuple holds a non-loopback IP literal."""
    if not address:
        return False
    host = str(address[0]).split("%", 1)[0].strip("[]")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False  # Non-IP peers (in-process test clients) are not sockets.
    return not is_loopback_host(host)


async def enforce_effective_listener_security(request: Request, call_next) -> Response:
    """Reject requests on non-loopback sockets unless a strong API key is set.

    Uses the socket addresses uvicorn reports (ASGI ``server``/``client``), so a
    direct ``uvicorn --host 0.0.0.0`` launch is gated without trusting env vars.
    """
    if request.url.path in _UNGUARDED_PATHS:
        return await call_next(request)
    scope = request.scope
    if _is_non_loopback_ip(scope.get("server")) or _is_non_loopback_ip(
        scope.get("client")
    ):
        if len(get_expected_api_key()) < _MIN_API_KEY_LENGTH:
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
