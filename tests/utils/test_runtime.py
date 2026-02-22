"""Tests for runtime environment detection."""

import sys
from unittest.mock import patch

from src.utils.runtime import is_bundled, get_resource_dir


def test_is_bundled_false_in_dev():
    """Dev mode: sys.frozen is absent."""
    # In normal dev mode, sys.frozen does not exist
    frozen_backup = getattr(sys, 'frozen', None)
    if hasattr(sys, 'frozen'):
        delattr(sys, 'frozen')
    try:
        assert is_bundled() is False
    finally:
        if frozen_backup is not None:
            sys.frozen = frozen_backup


def test_is_bundled_true_when_frozen():
    """PyInstaller sets sys.frozen = True."""
    with patch.object(sys, 'frozen', True, create=True):
        assert is_bundled() is True


def test_get_resource_dir_dev_mode():
    """In dev mode, returns project root."""
    result = get_resource_dir()
    # Should be the project root (where pyproject.toml lives)
    assert (result / "pyproject.toml").exists()


def test_get_resource_dir_bundled_mode():
    """In bundled mode (one-folder), returns parent of sys.executable."""
    with patch.object(sys, 'frozen', True, create=True):
        with patch.object(sys, 'executable', '/app/dist/shipagent-core/shipagent-core'):
            result = get_resource_dir()
            from pathlib import Path
            # One-folder build: resources are next to the executable
            assert result == Path('/app/dist/shipagent-core')
