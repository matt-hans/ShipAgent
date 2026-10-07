"""Resolve the pinned UPS MCP contract from read-only installed resources.

The pinned fork ships all seven OpenAPI specs. Reusing those files preserves
auxiliary operations (including TimeInTransit) and works in a signed/read-only
PyInstaller bundle without writing a project-relative cache or placeholder.
"""

from __future__ import annotations

from importlib.resources import files

from ups_mcp.openapi_registry import DEFAULT_SPEC_FILES


def ensure_ups_specs_dir() -> str:
    """Return the complete installed UPS contract directory, failing closed."""
    specs_dir = files("ups_mcp").joinpath("specs")
    missing = [name for name in DEFAULT_SPEC_FILES if not specs_dir.joinpath(name).is_file()]
    if missing:
        raise RuntimeError("UPS MCP package is missing bundled specs: " + ", ".join(missing))
    return str(specs_dir)
