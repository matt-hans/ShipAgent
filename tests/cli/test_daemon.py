"""Tests for daemon PID management."""

import os
import signal

from src.cli.daemon import (
    read_pid_file,
    write_pid_file,
    is_pid_alive,
    remove_pid_file,
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
        """Current process PID is alive."""
        assert is_pid_alive(os.getpid()) is True

    def test_is_pid_alive_nonexistent(self):
        """Non-existent PID is not alive."""
        # PID 999999 is unlikely to exist
        assert is_pid_alive(999999) is False

    def test_write_creates_parent_dirs(self, tmp_path):
        """Writing PID file creates parent directories."""
        pid_file = str(tmp_path / "nested" / "dir" / "test.pid")
        write_pid_file(pid_file, 12345)
        assert read_pid_file(pid_file) == 12345
