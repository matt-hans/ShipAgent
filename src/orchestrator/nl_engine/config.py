"""Configuration for the NL Engine.

This module provides configuration settings for the natural language
processing components, including LLM model selection.

Environment Variables:
    ANTHROPIC_MODEL: Claude model to use for NL processing.
        Defaults to "claude-sonnet-4-20250514".
        Options:
          - claude-sonnet-4-20250514 (default, best quality)
          - claude-haiku-4-5-20251001 (faster, cheaper)
"""

import os

# Default model - can be overridden via ANTHROPIC_MODEL env var
DEFAULT_MODEL = "claude-sonnet-4-20250514"


def get_model() -> str:
    """Get the Claude model to use for NL processing.

    Reads from ANTHROPIC_MODEL environment variable, falling back to
    the default Sonnet model if not set.

    Returns:
        Claude model identifier string.

    Example:
        >>> import os
        >>> os.environ["ANTHROPIC_MODEL"] = "claude-haiku-4-5-20250514"
        >>> get_model()
        'claude-haiku-4-5-20250514'
    """
    return os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
