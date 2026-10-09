"""Shared public OAuth vocabulary and canonical endpoint identity."""

import re
from typing import Final
from urllib.parse import urlsplit, urlunsplit

from src.utils.network import is_loopback_host

PUBLIC_SCOPES: Final = (
    "shipagent.status",
    "shipagent.preview",
    "shipagent.execute",
    "shipagent.artifacts",
)
METADATA_PATH: Final = "/.well-known/oauth-protected-resource/mcp"
ROOT_METADATA_PATH: Final = "/.well-known/oauth-protected-resource"


def canonical_mcp_resource(public_base_url: str) -> str:
    """Resolve an origin or exact MCP endpoint without rewriting authority.

    The only mounted public MCP path is /mcp. Prefix deployments need an
    explicit routing contract rather than a silently invented metadata URL.
    HTTP is allowed solely for loopback synthetic development.
    """
    try:
        parsed = urlsplit(public_base_url)
        valid = (
            bool(parsed.hostname)
            and re.fullmatch(r"[A-Za-z0-9.\-:\[\]]+", parsed.netloc) is not None
            and not any(ord(char) <= 32 or ord(char) == 127 for char in public_base_url)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and "?" not in public_base_url
            and "#" not in public_base_url
            and parsed.path in {"", "/", "/mcp", "/mcp/"}
            and (
                parsed.scheme == "https"
                or (parsed.scheme == "http" and is_loopback_host(parsed.hostname))
            )
        )
        # Validate malformed ports even when this helper is called outside Settings.
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(
            "public MCP URL must be a secure origin or its exact /mcp endpoint"
        )
    return urlunsplit((parsed.scheme, parsed.netloc, "/mcp", "", ""))


def resource_metadata_url(public_base_url: str) -> str:
    """Return the RFC 9728 metadata URL for the configured MCP endpoint."""
    resource = canonical_mcp_resource(public_base_url)
    return f"{resource.removesuffix('/mcp')}{METADATA_PATH}"


def validate_resource_metadata_url(metadata_url: str) -> None:
    """Reject unsafe header values and mismatched discovery paths."""
    try:
        parsed = urlsplit(metadata_url)
        origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        expected = resource_metadata_url(origin)
    except (ValueError, TypeError):
        raise ValueError("invalid OAuth resource metadata URL") from None
    if metadata_url != expected:
        raise ValueError("invalid OAuth resource metadata URL")
