"""The suite must not depend on, or leak, ShipAgent process environment."""

import os
import secrets
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROBE_FILE = "tests/isolation_probe/probe_isolation.py"
SUBPROCESS_TIMEOUT_SECONDS = 120


def test_ambient_shipagent_environment_does_not_reach_tests():
    """A docker-style SHIPAGENT_* environment must not change test outcomes."""
    environment = dict(os.environ)
    environment["SHIPAGENT_API_KEY"] = secrets.token_hex(24)
    environment["SHIPAGENT_BIND_HOST"] = "0.0.0.0"
    environment["SHIPAGENT_AUTH_MODE"] = "auth0"

    result = subprocess.run(
        [sys.executable, "-m", "pytest", PROBE_FILE, "-q", "-p", "no:cacheprovider"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )

    assert result.returncode == 0, result.stdout[-2000:]


def test_explicit_shipagent_test_variables_are_preserved():
    """Opt-in inputs such as SHIPAGENT_TEST_DATABASE_URL must reach the tests."""
    environment = dict(os.environ)
    environment["SHIPAGENT_TEST_PROBE"] = "kept"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            f"{PROBE_FILE}::test_c_explicit_test_configuration_is_preserved",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )

    assert result.returncode == 0 and "1 passed" in result.stdout, result.stdout[-2000:]
