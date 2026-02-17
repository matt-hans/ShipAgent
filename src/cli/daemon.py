"""Daemon management — start, stop, status.

Wraps uvicorn.run() programmatically with PID file management
for clean start/stop/status lifecycle.
"""

import logging
import os
import signal
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def write_pid_file(pid_file: str, pid: int) -> None:
    """Write the current process PID to a file.

    Args:
        pid_file: Path to PID file. Parent dirs created if needed.
        pid: Process ID to write.
    """
    path = Path(pid_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid))


def read_pid_file(pid_file: str) -> int | None:
    """Read PID from a file.

    Args:
        pid_file: Path to PID file.

    Returns:
        The PID as int, or None if file doesn't exist or is invalid.
    """
    path = Path(pid_file).expanduser()
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return None


def remove_pid_file(pid_file: str) -> None:
    """Remove the PID file.

    Args:
        pid_file: Path to PID file. No-op if file doesn't exist.
    """
    path = Path(pid_file).expanduser()
    if path.exists():
        path.unlink()


def is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running.

    Uses os.kill(pid, 0) for existence check, then verifies the process
    command line contains 'shipagent' or 'uvicorn' to avoid targeting
    a reused PID from an unrelated process.

    Args:
        pid: Process ID to check.

    Returns:
        True if process exists and is accessible.
    """
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False

    # Verify process identity via ps
    try:
        import subprocess
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=2,
        )
        cmdline = result.stdout.strip().lower()
        return any(marker in cmdline for marker in ["shipagent", "uvicorn", "src.api.main"])
    except Exception:
        # If ps fails, fall back to existence-only
        return True


def start_daemon(
    host: str = "127.0.0.1",
    port: int = 8000,
    pid_file: str = "~/.shipagent/daemon.pid",
    log_level: str = "info",
) -> None:
    """Start the ShipAgent daemon using uvicorn.

    Args:
        host: Bind address.
        port: Bind port.
        pid_file: Path to write PID file.
        log_level: Logging level for uvicorn.
    """
    import uvicorn

    # Check for stale PID
    existing_pid = read_pid_file(pid_file)
    if existing_pid is not None:
        if is_pid_alive(existing_pid):
            logger.error(
                "Daemon already running (PID %d). Use 'shipagent daemon stop' first.",
                existing_pid,
            )
            sys.exit(1)
        else:
            logger.warning("Removing stale PID file (PID %d no longer running)", existing_pid)
            remove_pid_file(pid_file)

    # Write current PID
    write_pid_file(pid_file, os.getpid())
    logger.info("Daemon starting on %s:%d (PID %d)", host, port, os.getpid())

    try:
        uvicorn.run(
            "src.api.main:app",
            host=host,
            port=port,
            workers=1,
            log_level=log_level,
            lifespan="on",
        )
    finally:
        remove_pid_file(pid_file)


def stop_daemon(pid_file: str = "~/.shipagent/daemon.pid") -> bool:
    """Stop the ShipAgent daemon by sending SIGTERM.

    Args:
        pid_file: Path to PID file.

    Returns:
        True if signal was sent successfully, False if daemon not running.
    """
    pid = read_pid_file(pid_file)
    if pid is None:
        logger.info("No PID file found — daemon may not be running")
        return False

    if not is_pid_alive(pid):
        logger.warning("PID %d not running — cleaning up stale PID file", pid)
        remove_pid_file(pid_file)
        return False

    logger.info("Sending SIGTERM to daemon (PID %d)", pid)
    os.kill(pid, signal.SIGTERM)

    # Wait for process to exit (up to 10s) before removing PID file
    import time as _time
    for _ in range(20):
        _time.sleep(0.5)
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            break  # Process exited

    remove_pid_file(pid_file)
    return True


def daemon_status(
    pid_file: str = "~/.shipagent/daemon.pid",
    base_url: str = "http://127.0.0.1:8000",
) -> dict:
    """Check daemon status.

    Args:
        pid_file: Path to PID file.
        base_url: Daemon HTTP base URL for health check.

    Returns:
        Dict with pid, alive, healthy keys.
    """
    pid = read_pid_file(pid_file)
    alive = pid is not None and is_pid_alive(pid)

    result = {"pid": pid, "alive": alive, "healthy": False}

    if alive:
        try:
            import httpx
            resp = httpx.get(f"{base_url}/health", timeout=5.0)
            result["healthy"] = resp.status_code == 200
        except Exception:
            result["healthy"] = False

    return result
