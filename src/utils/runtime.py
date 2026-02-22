"""Runtime environment detection for dev vs PyInstaller bundled mode."""

import sys
from pathlib import Path


def is_bundled() -> bool:
    """Return True when running from a PyInstaller bundle."""
    return getattr(sys, 'frozen', False)


def get_resource_dir() -> Path:
    """Return base directory for bundled resources.

    In dev mode, returns the project root (parent of src/).
    In PyInstaller one-folder mode, returns the directory containing
    the executable (where all extracted files live). We use one-folder
    (not one-file) to avoid _MEIPASS re-extraction penalty on every
    MCP subprocess spawn.
    """
    if is_bundled():
        # One-folder build: resources live next to the executable
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent
