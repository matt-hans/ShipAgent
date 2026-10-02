"""Real-socket regression for the direct-uvicorn non-loopback bypass (issue #48).

Starts ``uvicorn src.api.main:app --host 0.0.0.0`` as a subprocess against an
isolated temporary database and synthetic credentials, then connects through a
non-loopback interface address of this machine. All data here is synthetic.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

_CANARY = "CANARY-SYNTHETIC-DO-NOT-LEAK"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _lan_ip() -> str | None:
    """Return a non-loopback local IPv4 address, or None if the host has none."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1: no packet is sent for UDP
        ip = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return None if ip.startswith("127.") else ip


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def keyless_wildcard_server(tmp_path):
    """Yield ``(port)`` for a keyless direct-uvicorn process bound to 0.0.0.0."""
    port = _free_port()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SHIPAGENT_DB_PATH": str(tmp_path / "isolated.db"),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
        "FILTER_TOKEN_SECRET": _CANARY * 2,
        "UPS_CLIENT_ID": _CANARY,
        "UPS_CLIENT_SECRET": _CANARY,
        "UPS_ACCOUNT_NUMBER": "000000",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.api.main:app",
         "--host", "0.0.0.0", "--port", str(port), "--log-level", "warning"],
        cwd=_REPO_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail("uvicorn exited before accepting connections")
            try:
                httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
                break
            except httpx.TransportError:
                time.sleep(0.25)
        else:
            pytest.fail("uvicorn did not become ready in 45s")
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_keyless_wildcard_listener_is_closed_to_lan_clients(keyless_wildcard_server):
    lan = _lan_ip()
    if lan is None:
        pytest.skip("no non-loopback interface available")
    base = f"http://{lan}:{keyless_wildcard_server}"

    assert httpx.get(f"{base}/api/v1/jobs", timeout=5).status_code == 503
    for path in ("/health", "/readyz"):
        body = httpx.get(f"{base}{path}", timeout=10).json()
        assert set(body) == {"status"}, f"{path} leaked {sorted(body)}"
        assert _CANARY not in str(body)

    local = f"http://127.0.0.1:{keyless_wildcard_server}"
    assert "uptime_seconds" in httpx.get(f"{local}/health", timeout=5).json()
