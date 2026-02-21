"""Tests for daemon PID management."""

import os
from unittest.mock import patch

from src.cli.daemon import (
    is_pid_alive,
    read_pid_file,
    remove_pid_file,
    write_pid_file,
)


class TestPidFile:
    """Tests for PID file read/write/cleanup."""

    def test_write_and_read(self, tmp_path):
        """Write PID file and read it back."""
        pid_file = str(tmp_path / "test.pid")
        write_pid_file(pid_file, 12345)
        assert read_pid_file(pid_file) == 12345

    def test_read_missing_file(self, tmp_path):
        """Reading missing PID file returns None."""
        pid_file = str(tmp_path / "missing.pid")
        assert read_pid_file(pid_file) is None

    def test_remove_pid_file(self, tmp_path):
        """Remove PID file cleans up."""
        pid_file = str(tmp_path / "test.pid")
        write_pid_file(pid_file, 12345)
        remove_pid_file(pid_file)
        assert read_pid_file(pid_file) is None

    def test_is_pid_alive_current_process(self):
        """Current process PID is alive when it matches daemon markers."""
        mock_result = type("Result", (), {"stdout": "python -m shipagent daemon start"})()
        with patch("subprocess.run", return_value=mock_result):
            assert is_pid_alive(os.getpid()) is True

    def test_is_pid_alive_non_daemon_process(self):
        """Non-daemon process PID returns False (correct behavior)."""
        # Current pytest process doesn't match daemon markers
        assert is_pid_alive(os.getpid()) is False

    def test_is_pid_alive_nonexistent(self):
        """Non-existent PID is not alive."""
        # PID 999999 is unlikely to exist
        assert is_pid_alive(999999) is False

    def test_write_creates_parent_dirs(self, tmp_path):
        """Writing PID file creates parent directories."""
        pid_file = str(tmp_path / "nested" / "dir" / "test.pid")
        write_pid_file(pid_file, 12345)
        assert read_pid_file(pid_file) == 12345
