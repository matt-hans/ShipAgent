"""Shared exact-origin policy for credentialed browser transports."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from fastapi import Request

type NormalizedBrowserOrigin = tuple[str, str, int | None]

_DEFAULT_ORIGIN_PORTS = {"http": 80, "https": 443}
_SUPPORTED_ORIGIN_SCHEMES = frozenset({*_DEFAULT_ORIGIN_PORTS, "tauri"})


def parse_allowed_origins() -> list[str]:
    """Parse the comma-separated first-party browser origin configuration."""
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if not raw:
        return []
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def normalize_browser_origin(origin: str) -> NormalizedBrowserOrigin | None:
    """Normalize an untrusted serialized browser origin for exact comparison."""
    try:
        parsed = urlsplit(origin)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
    except (AttributeError, ValueError):
        return None

    if (
        scheme not in _SUPPORTED_ORIGIN_SCHEMES
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return None

    return (
        scheme,
        hostname.lower().rstrip("."),
        port if port is not None else _DEFAULT_ORIGIN_PORTS.get(scheme),
    )


def configured_browser_origins() -> frozenset[NormalizedBrowserOrigin]:
    """Return valid, normalized members of the configured origin allowlist."""
    normalized = (
        normalize_browser_origin(origin) for origin in parse_allowed_origins()
    )
    return frozenset(origin for origin in normalized if origin is not None)


def _request_origin(request: Request) -> NormalizedBrowserOrigin | None:
    scheme = request.url.scheme.lower()
    hostname = request.url.hostname
    if scheme not in _DEFAULT_ORIGIN_PORTS or not hostname:
        return None
    try:
        port = request.url.port
    except ValueError:
        return None
    return (
        scheme,
        hostname.lower().rstrip("."),
        port if port is not None else _DEFAULT_ORIGIN_PORTS[scheme],
    )


def is_trusted_browser_origin(request: Request) -> bool:
    """Return whether the request carries a same/configured first-party Origin."""
    serialized_origin = request.headers.get("Origin")
    if not serialized_origin:
        return False

    origin = normalize_browser_origin(serialized_origin)
    if origin is None:
        return False
    return origin == _request_origin(request) or origin in configured_browser_origins()
