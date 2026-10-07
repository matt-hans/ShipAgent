"""Release commands must work with only the declared clean dependencies."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_release_pytest_arguments_are_supported_by_declared_dependencies(tmp_path):
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    test_step = next(
        step for step in workflow["jobs"]["test"]["steps"] if step.get("name") == "Test"
    )
    command = shlex.split(test_step["run"])
    # Parse exactly the workflow options, then collect a tiny isolated test.
    # --version would exit before argparse notices unsupported plugin flags.
    probe = tmp_path / "test_release_command.py"
    probe.write_text("def test_release_parser():\n    pass\n")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *command[1:], "--collect-only", "-q", str(probe)],
        cwd=tmp_path,
        env={**os.environ, "PYTEST_ADDOPTS": ""},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_macos_release_uses_the_linked_and_smoked_sidecar_build():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    steps = workflow["jobs"]["build-macos"]["steps"]
    bundled = [
        index
        for index, step in enumerate(steps)
        if "scripts/bundle_backend.sh" in step.get("run", "")
    ]
    assert len(bundled) == 1, "Release must use the shared frontend/link/freeze/smoke pipeline"
    signing = next(
        index for index, step in enumerate(steps)
        if step.get("name") == "Codesign sidecar binary"
    )
    assert bundled[0] < signing


def test_bundle_smoke_does_not_inherit_operator_settings_or_credentials(tmp_path):
    bundler = (ROOT / "scripts/bundle_backend.sh").read_text()
    # Execute the actual sidecar launch fragment against a harmless executable
    # that reports its environment. No application/provider code is mocked.
    launch = bundler.split("# SMOKE_LAUNCH_BEGIN\n")[1].split("# SMOKE_LAUNCH_END")[0]
    binary = tmp_path / "environment-probe"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, os\n"
        "print(json.dumps({**dict(os.environ), '__cwd__': os.getcwd()}))\n"
    )
    binary.chmod(0o755)
    home = tmp_path / "smoke-home"
    home.mkdir()
    result = subprocess.run(
        ["bash", "-c", launch + '\nwait "$PID"'],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path / "operator-home"),
            "BINARY": str(binary),
            "BINARY_DIR": str(tmp_path),
            "SMOKE_DATA_DIR": str(home),
            "ANTHROPIC_API_KEY": "synthetic-operator-canary",
            "SHIPAGENT_API_KEY": "synthetic-operator-canary",
            "AGENT_MODEL": "synthetic-operator-canary",
            "PYTHON_DOTENV_DISABLED": "0",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    environment = json.loads((tmp_path / ".smoke_stdout").read_text())
    assert environment["HOME"] == str(home)
    assert environment["__cwd__"] == str(home)
    assert environment["PYTHON_DOTENV_DISABLED"] == "1"
    assert environment["SHIPAGENT_KEYRING_DISABLED"] == "1"
    assert not {"ANTHROPIC_API_KEY", "SHIPAGENT_API_KEY", "AGENT_MODEL"} & environment.keys()


def test_macos_release_uses_available_architecture_matched_runners():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    matrix = workflow["jobs"]["build-macos"]["strategy"]["matrix"]["include"]
    # Standard GitHub-hosted labels verified 2026-10-07. macos-13 is retired.
    # Keep native x86_64 and arm64 builds distinct; do not silently cross-build.
    assert {entry["target"]: entry["runner"] for entry in matrix} == {
        "aarch64-apple-darwin": "macos-15",
        "x86_64-apple-darwin": "macos-15-intel",
    }
