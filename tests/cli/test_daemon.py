"""Tests for daemon PID management."""

import os
from unittest.mock import patch

import pytest

from src.cli.daemon import (
    is_pid_alive,
    read_pid_file,
    remove_pid_file,
    start_daemon,
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
        mock_result = type(
            "Result", (), {"stdout": "python -m shipagent daemon start"}
        )()
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


def test_start_daemon_rejects_actual_public_bind_for_fake_local(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("SHIPAGENT_AUTH_MODE", "fake_local")
    monkeypatch.setenv("SHIPAGENT_ENVIRONMENT", "local")
    monkeypatch.delenv("SHIPAGENT_DATABASE_URL", raising=False)
    monkeypatch.delenv("SHIPAGENT_REDIS_URL", raising=False)
    pid_file = tmp_path / "daemon.pid"

    with patch("uvicorn.run") as uvicorn_run:
        with pytest.raises(RuntimeError, match="loopback"):
            start_daemon(host="0.0.0.0", port=8080, pid_file=str(pid_file))

    uvicorn_run.assert_not_called()
    assert not pid_file.exists()


def test_start_daemon_rejects_public_auth0_config_without_api_key(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("SHIPAGENT_AUTH_MODE", "auth0")
    monkeypatch.setenv("SHIPAGENT_ENVIRONMENT", "production")
    monkeypatch.setenv("SHIPAGENT_AUTH0_ISSUER", "https://issuer.example/")
    monkeypatch.setenv("SHIPAGENT_AUTH0_AUDIENCE", "shipagent")
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)
    pid_file = tmp_path / "daemon.pid"

    with patch("uvicorn.run") as uvicorn_run:
        with pytest.raises(RuntimeError, match="SHIPAGENT_API_KEY"):
            start_daemon(host="0.0.0.0", port=8080, pid_file=str(pid_file))

    uvicorn_run.assert_not_called()
    assert not pid_file.exists()


def test_start_daemon_rejects_public_listener_with_weak_api_key(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("SHIPAGENT_AUTH_MODE", "auth0")
    monkeypatch.setenv("SHIPAGENT_API_KEY", "too-short")
    pid_file = tmp_path / "daemon.pid"

    with patch("uvicorn.run") as uvicorn_run:
        with pytest.raises(ValueError, match="too short"):
            start_daemon(host="0.0.0.0", port=8080, pid_file=str(pid_file))

    uvicorn_run.assert_not_called()
    assert not pid_file.exists()


def test_start_daemon_accepts_public_listener_with_strong_api_key(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("SHIPAGENT_AUTH_MODE", "auth0")
    monkeypatch.setenv("SHIPAGENT_API_KEY", "s" * 64)
    pid_file = tmp_path / "daemon.pid"

    with patch("uvicorn.run") as uvicorn_run:
        start_daemon(host="0.0.0.0", port=8080, pid_file=str(pid_file))

    uvicorn_run.assert_called_once_with(
        "src.api.main:app",
        host="0.0.0.0",
        port=8080,
        workers=1,
        log_level="info",
        lifespan="on",
    )
    assert not pid_file.exists()


def test_start_daemon_keeps_loopback_usable_without_api_key(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("SHIPAGENT_AUTH_MODE", "auth0")
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)
    pid_file = tmp_path / "daemon.pid"

    with patch("uvicorn.run") as uvicorn_run:
        start_daemon(host="127.0.0.1", port=8080, pid_file=str(pid_file))

    uvicorn_run.assert_called_once()
    assert not pid_file.exists()
