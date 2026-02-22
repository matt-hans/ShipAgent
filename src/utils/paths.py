"""Production file path resolution using platformdirs.

In dev mode (not bundled), paths resolve relative to the project root.
In bundled mode (PyInstaller), paths use platform-appropriate directories:
  macOS: ~/Library/Application Support/com.shipagent.app/
  Windows: %LOCALAPPDATA%/ShipAgent/  (future)
  Linux: ~/.local/share/shipagent/  (future)
"""

from pathlib import Path

import platformdirs

from src.utils.runtime import is_bundled

APP_NAME = "ShipAgent"
APP_AUTHOR = "ShipAgent"
# Bundle identifier for macOS (used by platformdirs when roaming=False)
_BUNDLE_ID = "com.shipagent.app"


def get_data_dir() -> Path:
    """Return the directory for persistent data (DB, config).

    In dev mode: project root (where shipagent.db lives today).
    In bundled mode: platform user data dir.
    """
    if is_bundled():
        return Path(platformdirs.user_data_dir(_BUNDLE_ID, appauthor=False))
    # Dev mode: project root
    return Path(__file__).resolve().parent.parent.parent


def get_labels_dir() -> Path:
    """Return the directory for label PDF storage."""
    data = get_data_dir()
    return data / "labels"


def get_log_dir() -> Path:
    """Return the directory for application logs.

    In dev mode: project root.
    In bundled mode: platform log dir (macOS: ~/Library/Logs/com.shipagent.app/).
    """
    if is_bundled():
        return Path(platformdirs.user_log_dir(_BUNDLE_ID, appauthor=False))
    return Path(__file__).resolve().parent.parent.parent


def get_default_db_path() -> Path:
    """Return the default SQLite database file path."""
    return get_data_dir() / "shipagent.db"


def ensure_dirs_exist() -> None:
    """Create all required directories if they don't exist."""
    for d in [get_data_dir(), get_labels_dir(), get_log_dir()]:
        d.mkdir(parents=True, exist_ok=True)
