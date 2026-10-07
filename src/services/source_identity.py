"""Non-sensitive identity of one imported source and its stable row mapping."""

import base64
import hashlib
import json
from typing import Any


def source_binding_digest(info: dict[str, Any]) -> str:
    """Digest only identity/schema metadata, never imported row values.

    The import instance disambiguates re-imports of the same path with a new
    row mapping. Missing/legacy bindings are deliberately not replayable.
    """
    identity = {
        "type": info.get("source_type"),
        "reference": info.get("path") or info.get("query"),
        "sheet": info.get("sheet"),
        "schema": info.get("signature"),
        "row_keys": info.get("row_key_columns", []),
        "instance": info.get("source_instance"),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")
