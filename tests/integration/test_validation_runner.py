"""Failure-injection tests for the bounded synthetic-validation runner."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/validation/run_bounded.py"


def run_probe(tmp_path, code, *limits, ambient=None, cwd=ROOT, output=None):
    output = output or tmp_path / "receipts"
    env = dict(os.environ)
    env.update(ambient or {})
    command = [
        sys.executable,
        str(RUNNER),
        "--name",
        "selftest",
        "--cwd",
        str(cwd),
        "--output-dir",
        str(output),
        "--lock-file",
        str(tmp_path / "test.lock"),
        "--seconds",
        "10",
        "--rss-mib",
        "256",
        *limits,
        "--",
        sys.executable,
        "-c",
        code,
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=20, env=env
    )
    receipt = json.loads((output / "selftest.json").read_text())
    return result, receipt, (output / "selftest.log").read_text()


def test_clean_environment_exact_source_and_owned_home_cleanup(tmp_path):
    result, receipt, log = run_probe(
        tmp_path,
        """
import json, os, pathlib, src, sys
assert os.environ.get('OPENAI_API_KEY') is None
assert os.environ.get('HTTPS_PROXY') is None
assert 'shipagent_offline_guard' in sys.modules
assert pathlib.Path(sys.prefix) == pathlib.Path(os.environ['HOME']).parent / 'venv'
assert pathlib.Path(src.__file__).resolve().parent.parent == pathlib.Path.cwd()
print(json.dumps({'home': os.environ['HOME']}))
""",
        ambient={
            "OPENAI_API_KEY": "NEVER_PRINT_CREDENTIAL_CANARY",
            "HTTPS_PROXY": "http://proxy.invalid",
        },
    )
    assert result.returncode == 0, log
    assert receipt["root_exit"] == 0
    assert receipt["survivors"] == []
    assert receipt["forced_cleanup"] is False
    assert len(receipt["source"]["head"]) == 40
    assert len(receipt["source"]["file_manifest_sha256"]) == 64
    assert receipt["environment"]["python_version"]
    assert receipt["environment"]["packages"]["pytest"]
    assert len(receipt["cpu_affinity"]) <= 2
    assert receipt["runtime_directory_removed"] is True
    assert receipt["source_changed_during_run"] is False
    assert receipt["loaded_guard_mismatch"] is False
    assert receipt["loaded_python_guards"]
    assert (
        receipt["loaded_python_guards"][0]["sha256"]
        == receipt["environment"]["guard_sha256"]
    )
    assert not Path(json.loads(log)["home"]).exists()
    assert "NEVER_PRINT_CREDENTIAL_CANARY" not in log + json.dumps(receipt)


def test_guard_allows_loopback_and_blocks_external_python_socket_use(tmp_path):
    result, receipt, _ = run_probe(
        tmp_path,
        """
import socket
with socket.socket() as local:
    local.bind(('127.0.0.1', 0))
for action in (
    lambda: socket.create_connection(('192.0.2.1', 9)),
    lambda: socket.socket().bind(('0.0.0.0', 0)),
    lambda: socket.getaddrinfo('acceptance.example.invalid', 443),
    lambda: socket.gethostbyaddr('192.0.2.1'),
):
    try:
        action()
    except PermissionError:
        pass
    else:
        raise AssertionError('non-loopback operation was not blocked')
""",
    )
    assert result.returncode == 0
    assert receipt["survivors"] == []


def test_guard_is_inherited_but_stripped_environment_is_an_explicit_limit(tmp_path):
    result, receipt, log = run_probe(
        tmp_path,
        """
import subprocess, sys
probe = 'import sys; print(int("shipagent_offline_guard" in sys.modules))'
inherited = subprocess.check_output([sys.executable, '-c', probe], text=True)
stripped = subprocess.check_output([sys.executable, '-c', probe], text=True, env={})
no_site = subprocess.check_output([sys.executable, '-S', '-c', probe], text=True, env={})
assert inherited.strip() == '1', ('inherited', inherited)
# The disposable task-local venv hook survives a stripped environment.
assert stripped.strip() == '1', ('stripped', stripped)
assert no_site.strip() == '0', ('no-site', no_site)
""",
    )
    assert result.returncode == 0, log
    assert "stripped child environment" in receipt["limitations"]
    assert "not a kernel network sandbox" in receipt["limitations"]


def test_wall_timeout_is_failure_and_cleans_owned_descendants(tmp_path):
    result, receipt, _ = run_probe(
        tmp_path,
        """
import subprocess, sys, time
subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
time.sleep(60)
""",
        "--seconds",
        "0.6",
    )
    assert result.returncode != 0
    assert receipt["limit_failure"] == "wall_time_limit"
    assert receipt["forced_cleanup"] is True
    assert receipt["survivors"] == []


def test_orphaned_child_is_a_failure_even_when_root_exits_zero(tmp_path):
    result, receipt, _ = run_probe(
        tmp_path,
        """
import subprocess, sys
subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
""",
    )
    assert result.returncode != 0
    assert receipt["root_exit"] == 0
    assert receipt["forced_cleanup"] is True
    assert receipt["survivors"] == []


def test_sampled_aggregate_rss_limit_stops_a_retained_allocation(tmp_path):
    result, receipt, _ = run_probe(
        tmp_path,
        """
import time
retained = bytearray(80 * 1024 * 1024)
time.sleep(60)
""",
        "--rss-mib",
        "48",
    )
    assert result.returncode != 0
    assert receipt["limit_failure"] == "aggregate_rss_limit"
    assert receipt["peak_sampled_rss_mib"] > 48
    assert receipt["survivors"] == []
    assert "sampled RSS" in receipt["limitations"]


def test_nonzero_child_exit_remains_failure(tmp_path):
    result, receipt, _ = run_probe(tmp_path, "raise SystemExit(7)")
    assert result.returncode == 7
    assert receipt["root_exit"] == 7
    assert receipt["forced_cleanup"] is False
    assert receipt["survivors"] == []


def synthetic_checkout(tmp_path):
    checkout = tmp_path / "source"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    (checkout / "tracked.txt").write_text("before\n")
    subprocess.run(["git", "-C", str(checkout), "add", "tracked.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=Synthetic Acceptance",
            "-c",
            "user.email=acceptance@example.invalid",
            "commit",
            "-qm",
            "Synthetic baseline",
        ],
        check=True,
    )
    return checkout


def test_source_drift_fails_even_when_child_exits_zero(tmp_path):
    checkout = synthetic_checkout(tmp_path)
    result, receipt, _ = run_probe(
        tmp_path,
        "from pathlib import Path; Path('tracked.txt').write_text('after\\n')",
        cwd=checkout,
    )
    assert result.returncode != 0
    assert receipt["root_exit"] == 0
    assert receipt["source_changed_during_run"] is True
    assert (
        receipt["source"]["file_manifest_sha256"]
        != receipt["source_after"]["file_manifest_sha256"]
    )
    assert receipt["survivors"] == []


def test_runner_output_is_excluded_from_source_fingerprint(tmp_path):
    checkout = synthetic_checkout(tmp_path)
    result, receipt, log = run_probe(
        tmp_path,
        "print('safe synthetic output')",
        cwd=checkout,
        output=checkout / "receipts",
    )
    assert result.returncode == 0, log
    assert receipt["source_changed_during_run"] is False
    assert receipt["source"] == receipt["source_after"]


@pytest.mark.parametrize("location", ["ancestor", "protected-source"])
def test_output_cannot_hide_checkout_or_tracked_source(tmp_path, location):
    checkout = synthetic_checkout(tmp_path)
    protected = checkout / "protected"
    protected.mkdir()
    (protected / "module.py").write_text("version = 1\n")
    subprocess.run(
        ["git", "-C", str(checkout), "add", "protected/module.py"], check=True
    )
    output = tmp_path if location == "ancestor" else protected
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--name",
            "forbidden",
            "--cwd",
            str(checkout),
            "--output-dir",
            str(output),
            "--lock-file",
            str(tmp_path / "probe.lock"),
            "--",
            sys.executable,
            "-c",
            "from pathlib import Path; Path('ran.txt').write_text('ran')",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert not (checkout / "ran.txt").exists()
    assert "output" in result.stderr
