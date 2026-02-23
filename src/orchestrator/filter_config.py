"""Startup-time filter configuration validation.

Validates filter configuration (FILTER_TOKEN_SECRET) at server boot.
Logs warnings instead of raising so the server can start in dev/test
environments without explicit configuration. Called from FastAPI lifespan
in src/api/main.py.
"""

import logging
import os

_MIN_SECRET_LENGTH = 32
logger = logging.getLogger(__name__)


def validate_filter_config() -> None:
    """Validate filter configuration at startup.

    Called from FastAPI lifespan. Logs warnings if FILTER_TOKEN_SECRET
    is missing or too short, but does not raise — the filter resolver
    falls back to an ephemeral in-process secret when the env var is
    absent.
    """
    secret = os.environ.get("FILTER_TOKEN_SECRET", "")
    if not secret:
        logger.warning(
            "FILTER_TOKEN_SECRET not set; using ephemeral fallback. "
            "Set it to a stable secret (min 32 chars) for production."
        )
        return
    if len(secret) < _MIN_SECRET_LENGTH:
        logger.warning(
            "FILTER_TOKEN_SECRET shorter than %d chars (current: %d). "
            "Consider using a cryptographically random value.",
            _MIN_SECRET_LENGTH,
            len(secret),
        )
