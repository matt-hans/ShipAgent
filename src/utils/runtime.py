"""Runtime environment detection for dev vs PyInstaller bundled mode."""

import os
import sys
from pathlib import Path


def get_default_port() -> int:
    """Return the default backend port from SHIPAGENT_PORT env var, or 8080."""
    return int(os.environ.get("SHIPAGENT_PORT", "8080"))


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


def bundled_mcp_command(subcommand: str) -> tuple[str, list[str]] | None:
    """Return ``(command, args)`` that spawn this binary as an MCP server.

    In a PyInstaller bundle ``sys.executable`` is the shipagent-core binary,
    which only understands the ``mcp-*`` subcommands (not ``-m <module>``).
    Returns None in dev mode so callers fall back to ``python -m <module>``.
    """
    if not is_bundled():
        return None
    return sys.executable, [subcommand]
