#!/usr/bin/env python3
"""Validate hosted MCP OAuth protected-resource metadata."""

import json
import sys

import httpx


def check_metadata(base_url: str) -> dict[str, object]:
    response = httpx.get(
        f"{base_url.rstrip('/')}/.well-known/oauth-protected-resource",
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()

    resource = base_url.rstrip("/")
    if payload.get("resource") != resource:
        raise RuntimeError(
            f"metadata resource mismatch: {payload.get('resource')} != {resource}"
        )
    if not payload.get("authorization_servers"):
        raise RuntimeError("metadata missing authorization_servers")

    return payload


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("usage: python scripts/check_provider_oauth_metadata.py <base_url>")
    payload = check_metadata(argv[1])
    print(f"metadata check passed for {argv[1]}")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv)
