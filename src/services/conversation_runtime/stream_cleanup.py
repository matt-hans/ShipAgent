"""Best-effort closure of one request-owned stream, never a reusable client."""

from __future__ import annotations

import inspect
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def close_owned_stream(stream: Any) -> None:
    """Close an async generator or SDK stream without masking request failures."""
    close = getattr(stream, "aclose", None) or getattr(stream, "close", None)
    if not callable(close):
        return
    try:
        result = close()
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        logger.warning(
            "Provider stream close failed exception_type=%s", type(exc).__name__
        )
