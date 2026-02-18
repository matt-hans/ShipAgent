"""Deterministic binding fingerprint helpers.

Pure helpers: callers pass explicit version material instead of importing
constants from unrelated modules.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def normalize_source_signature(source_signature: dict[str, Any] | None) -> dict[str, str]:
    """Normalize a source signature to a stable shape for hashing."""
    raw = source_signature or {}
    return {
        "source_type": str(raw.get("source_type", "")),
        "source_ref": str(raw.get("source_ref", "")),
        "schema_fingerprint": str(raw.get("schema_fingerprint", "")),
    }


def build_binding_fingerprint(
    source_signature: dict[str, Any] | None,
    compiler_version: str,
    mapping_version: str,
    normalizer_version: str,
) -> str:
    """Build a deterministic fingerprint for source+version bindings."""
    payload = {
        "source_signature": normalize_source_signature(source_signature),
        "compiler_version": str(compiler_version),
        "mapping_version": str(mapping_version),
        "normalizer_version": str(normalizer_version),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
