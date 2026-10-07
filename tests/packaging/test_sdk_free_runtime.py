"""Real entry-point checks with the agent SDK physically outside sys.path.

A fresh venv exposes individual existing dependencies, excluding the removed
SDK's code, distribution metadata and all .pth path injection. No SDK import
mock is used. Clean lockfile installation and frozen desktop release validation
are separate gates; this fast regression fixture is network-free.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sysconfig
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def sdk_free_python(tmp_path_factory):
    root = tmp_path_factory.mktemp("sdk-free-python")
    venv.EnvBuilder(with_pip=False, symlinks=True).create(root)
    python = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    purelib = subprocess.check_output(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        text=True,
    ).strip()
    target = Path(purelib)
    for source in Path(sysconfig.get_path("purelib")).iterdir():
        if (
            source.name.startswith(
                ("claude_agent_sdk", "__editable__", "shipagent", "__pycache__")
            )
            or source.suffix == ".pth"
        ):
            continue
        destination = target / source.name
        if not destination.exists():
            destination.symlink_to(source, target_is_directory=source.is_dir())
    return python


def _environment(tmp_path):
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(tmp_path),
        "PYTHONPATH": str(ROOT),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONNOUSERSITE": "1",
        "SHIPAGENT_DATA_DIR": str(tmp_path),
        "SHIPAGENT_KEYRING_DISABLED": "1",
        "SHIPAGENT_AUTH_MODE": "fake_local",
        "SHIPAGENT_ENVIRONMENT": "local",
        "SHIPAGENT_BIND_HOST": "127.0.0.1",
        "SHIPAGENT_CREDENTIAL_KEY": base64.urlsafe_b64encode(b"0" * 32).decode(),
        "FILTER_TOKEN_SECRET": "synthetic-filter-secret-for-offline-test-only",
        "ANTHROPIC_API_KEY": "synthetic-key-no-network",
        "AGENT_HIDE_TRANSIENT_CHAT": "false",
        "AGENT_AUDIT_ENABLED": "false",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    }


@pytest.mark.parametrize("surface", ["api", "settings", "cli"])
def test_sdk_absent_startup_and_deterministic_workflow(
    sdk_free_python, tmp_path, surface
):
    result = subprocess.run(
        [
            str(sdk_free_python),
            str(ROOT / "tests/packaging/sdk_free_probe.py"),
            surface,
        ],
        cwd=tmp_path,
        env=_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"SDK_FREE_{surface.upper()}_WORKFLOW_OK" in result.stdout


def test_sdk_absent_desktop_cli_entrypoint(sdk_free_python, tmp_path):
    result = subprocess.run(
        [str(sdk_free_python), "-m", "src.bundle_entry", "cli", "version"],
        cwd=tmp_path,
        env=_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ShipAgent-owned" in result.stdout


@pytest.mark.parametrize("entrypoint", ["sidecar", "development"])
def test_sdk_absent_server_entrypoint(sdk_free_python, tmp_path, entrypoint):
    """Start the actual desktop serve protocol or development shell launcher."""
    import re
    import signal
    import time

    import httpx

    environment = _environment(tmp_path)
    if entrypoint == "sidecar":
        command = [
            str(sdk_free_python),
            "-m",
            "src.bundle_entry",
            "serve",
            "--port",
            "0",
        ]
        pattern = r"SHIPAGENT_PORT=(\d+)"
    else:
        env_file = tmp_path / "synthetic.env"
        env_file.write_text(
            "# Isolated SDK-free startup fixture; no owner environment.\n"
        )
        environment.update(
            {
                "SHIPAGENT_PYTHON": str(sdk_free_python),
                "SHIPAGENT_ENV_FILE": str(env_file),
                "SHIPAGENT_PORT": "0",
            }
        )
        command = ["bash", str(ROOT / "scripts/start-backend.sh")]
        pattern = r"Uvicorn running on http://127\.0\.0\.1:(\d+)"
    log_path = tmp_path / "startup.log"
    with log_path.open("w") as log:
        process = subprocess.Popen(
            command,
            cwd=tmp_path,
            env=environment,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 20
            with httpx.Client(trust_env=False, timeout=1) as client:
                while time.monotonic() < deadline:
                    output = log_path.read_text()
                    assert process.poll() is None, output
                    match = re.search(pattern, output)
                    if match:
                        try:
                            response = client.get(f"http://127.0.0.1:{match[1]}/health")
                            if response.status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                    time.sleep(0.05)
                else:
                    pytest.fail(log_path.read_text())
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
