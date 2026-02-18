"""UPS MCP OpenAPI spec path helpers.

Ensures the UPS MCP server can load required OpenAPI files even when the
installed ups_mcp package does not ship its bundled docs directory.
"""

from __future__ import annotations

from pathlib import Path

# Project root is parent of src/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SOURCE_DOCS_DIR = _PROJECT_ROOT / "docs"
_RUNTIME_SPECS_DIR = _PROJECT_ROOT / ".cache" / "ups_mcp_specs"

# Minimal placeholder so ups_mcp can initialize if its optional transit
# spec is absent. Transit operations are not used in the batch preview flow.
_TIME_IN_TRANSIT_PLACEHOLDER = """openapi: 3.0.3
info:
  title: UPS Time In Transit (Placeholder)
  version: "1.0"
paths: {}
"""


def _first_existing(*candidate_paths: Path) -> Path | None:
    """Return the first existing path from candidates."""
    for path in candidate_paths:
        if path.exists():
            return path
    return None


def ensure_ups_specs_dir() -> str:
    """Prepare and return a UPS_MCP_SPECS_DIR-compatible directory path."""
    _RUNTIME_SPECS_DIR.mkdir(parents=True, exist_ok=True)

    mapping = {
        "Rating.yaml": (
            _SOURCE_DOCS_DIR / "rating.yaml",
            _SOURCE_DOCS_DIR / "Rating.yaml",
        ),
        "Shipping.yaml": (
            _SOURCE_DOCS_DIR / "shipping.yaml",
            _SOURCE_DOCS_DIR / "Shipping.yaml",
        ),
        # Optional specs — skipped if source file doesn't exist
        "LandedCost.yaml": (
            _SOURCE_DOCS_DIR / "landed_cost.yaml",
            _SOURCE_DOCS_DIR / "LandedCost.yaml",
        ),
        "Paperless.yaml": (
            _SOURCE_DOCS_DIR / "paperless.yaml",
            _SOURCE_DOCS_DIR / "Paperless.yaml",
        ),
        "Locator.yaml": (
            _SOURCE_DOCS_DIR / "locator.yaml",
            _SOURCE_DOCS_DIR / "Locator.yaml",
        ),
        "Pickup.yaml": (
            _SOURCE_DOCS_DIR / "pickup.yaml",
            _SOURCE_DOCS_DIR / "Pickup.yaml",
        ),
    }
    for target_name, source_candidates in mapping.items():
        source_path = _first_existing(*source_candidates)
        if source_path is None:
            continue
        target_path = _RUNTIME_SPECS_DIR / target_name
        source_text = source_path.read_text()
        if not target_path.exists() or target_path.read_text() != source_text:
            target_path.write_text(source_text)

    transit_path = _RUNTIME_SPECS_DIR / "TimeInTransit.yaml"
    if not transit_path.exists():
        transit_path.write_text(_TIME_IN_TRANSIT_PLACEHOLDER)

    return str(_RUNTIME_SPECS_DIR)
