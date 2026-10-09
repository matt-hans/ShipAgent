#!/usr/bin/env python3
"""Validate hosted MCP OAuth protected-resource metadata."""

import json
import sys

import httpx

from src.control_plane.auth.oauth_contract import (
    PUBLIC_SCOPES,
    canonical_mcp_resource,
    resource_metadata_url,
)


def check_metadata(base_url: str) -> dict[str, object]:
    resource = canonical_mcp_resource(base_url)
    response = httpx.get(
        resource_metadata_url(resource),
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()

    if payload.get("resource") != resource:
        raise RuntimeError(
            f"metadata resource mismatch: {payload.get('resource')} != {resource}"
        )
    if not payload.get("authorization_servers"):
        raise RuntimeError("metadata missing authorization_servers")
    if sorted(payload.get("scopes_supported", [])) != sorted(PUBLIC_SCOPES):
        raise RuntimeError("metadata scopes_supported mismatch")

    return payload


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit(
            "usage: python scripts/check_provider_oauth_metadata.py <mcp_url>"
        )
    payload = check_metadata(argv[1])
    print(f"metadata check passed for {argv[1]}")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv)
