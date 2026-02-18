"""Shared intent-detection heuristics for conversation and tool routing."""

import re

from src.services.filter_constants import STATE_ABBREVIATIONS

_BATCH_SCOPE_PATTERN = re.compile(
    r"\b(all|every|\d+)\s+(orders|rows|shipments|packages)\b",
)
_BATCH_TARGET_PATTERN = re.compile(r"\b(orders|rows|shipments|packages)\b")
_BATCH_FILTER_CUES = (
    " where ",
    " unfulfilled ",
    " fulfilled ",
    " pending ",
    " company ",
    " companies ",
    " customer ",
    " customers ",
    " northeast ",
    " midwest ",
    " southwest ",
    " southeast ",
    " west coast ",
    " east coast ",
)
_STATE_NAME_CUES = tuple(
    f" {name.lower()} "
    for name in STATE_ABBREVIATIONS.keys()
)
_EXPLORATORY_PREFIXES = (
    "show",
    "list",
    "find",
    "count",
    "how many",
    "which",
    "what",
)


def is_confirmation_response(message: str | None) -> bool:
    """True for short confirmation replies (yes/proceed/confirm)."""
    if not message:
        return False
    text = message.strip().lower()
    return text in {"yes", "y", "ok", "okay", "confirm", "proceed", "continue", "go ahead"}


def is_shipping_request(message: str | None) -> bool:
    """Heuristic for shipment-execution requests."""
    if not message:
        return False
    text = message.strip().lower()
    if not text or text.startswith("[document_attached"):
        return False
    if "ship" not in text and "shipment" not in text:
        return False
    if "do not ship" in text or "don't ship" in text:
        return False
    return not any(text.startswith(prefix) for prefix in _EXPLORATORY_PREFIXES)


def is_batch_shipping_request(message: str | None) -> bool:
    """Heuristic for batch shipping commands that require filter tools."""
    if not is_shipping_request(message):
        return False
    text = " ".join(str(message).strip().lower().replace("-", " ").split())
    padded = f" {text} "
    if not _BATCH_TARGET_PATTERN.search(text):
        return False

    has_scope = text.startswith(("ship all ", "ship every ")) or bool(
        _BATCH_SCOPE_PATTERN.search(text),
    )
    has_filter_cue = any(cue in padded for cue in _BATCH_FILTER_CUES)
    has_state_name = any(cue in padded for cue in _STATE_NAME_CUES)
    return has_scope or has_filter_cue or has_state_name
