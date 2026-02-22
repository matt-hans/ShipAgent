"""Tests for production file path resolution."""

import os
from pathlib import Path
from unittest.mock import patch

from src.utils.paths import get_data_dir, get_log_dir, get_default_db_path, get_labels_dir


def test_get_data_dir_returns_path():
    """Data dir should be a valid Path."""
    result = get_data_dir()
    assert isinstance(result, Path)


def test_get_data_dir_bundled_uses_platformdirs():
    """In bundled mode, data dir uses platformdirs."""
    import sys
    with patch.object(sys, 'frozen', True, create=True):
        result = get_data_dir()
        # On macOS: ~/Library/Application Support/com.shipagent.app
        assert 'shipagent' in str(result).lower() or 'ShipAgent' in str(result)


def test_get_data_dir_dev_uses_cwd():
    """In dev mode, data dir is the project root."""
    result = get_data_dir()
    # Should be near the project root
    assert result.exists() or result == Path('.')


def test_get_default_db_path():
    """Default DB path combines data dir + shipagent.db."""
    result = get_default_db_path()
    assert result.name == 'shipagent.db'


def test_env_var_overrides_data_dir():
    """DATABASE_URL env var takes priority over platformdirs."""
    with patch.dict(os.environ, {'DATABASE_URL': 'sqlite:///custom/path.db'}):
        from src.db.connection import get_database_url
        assert get_database_url() == 'sqlite:///custom/path.db'


def test_get_labels_dir_bundled():
    """Labels dir uses platformdirs in bundled mode."""
    import sys
    with patch.object(sys, 'frozen', True, create=True):
        result = get_labels_dir()
        assert isinstance(result, Path)


def test_get_log_dir():
    """Log dir returns a valid path."""
    result = get_log_dir()
    assert isinstance(result, Path)


def test_wal_mode_enabled():
    """SQLite WAL mode is set on engine connect for concurrency."""
    from sqlalchemy import text

    from src.db.connection import engine
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA journal_mode;")).scalar()
        assert result == "wal", f"Expected WAL mode, got {result}"
