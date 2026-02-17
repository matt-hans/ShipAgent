"""Startup-time filter configuration validation.

Validates required filter configuration (FILTER_TOKEN_SECRET) at server
boot, failing fast before any requests can be processed. Called from
FastAPI lifespan in src/api/main.py.
"""

import os

from src.orchestrator.filter_resolver import FilterConfigError

_MIN_SECRET_LENGTH = 32


def validate_filter_config() -> None:
    """Validate required filter configuration at startup.

    Called from FastAPI lifespan to fail fast at server boot.
    Raises FilterConfigError if FILTER_TOKEN_SECRET is not set or too short.

    Raises:
        FilterConfigError: If FILTER_TOKEN_SECRET is missing or insufficient.
    """
    secret = os.environ.get("FILTER_TOKEN_SECRET", "")
    if not secret:
        raise FilterConfigError(
            "FILTER_TOKEN_SECRET env var is required. "
            "Set it to a stable secret (min 32 chars) for HMAC token signing."
        )
    if len(secret) < _MIN_SECRET_LENGTH:
        raise FilterConfigError(
            f"FILTER_TOKEN_SECRET must be at least {_MIN_SECRET_LENGTH} characters. "
            f"Current length: {len(secret)}. Use a cryptographically random value."
        )
