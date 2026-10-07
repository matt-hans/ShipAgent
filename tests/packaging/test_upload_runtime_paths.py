"""API and real MCP child must agree on writable isolated upload storage."""

import subprocess
import sys
from pathlib import Path

import pytest

from tests.packaging.test_sdk_free_runtime import _environment

ROOT = Path(__file__).resolve().parents[2]


def test_configured_data_directory_hosts_real_uploads_without_expanding_access(tmp_path):
    environment = _environment(tmp_path)
    environment["SHIPAGENT_TEST_LOCAL_DATA_SOURCE"] = "1"
    result = subprocess.run(
        [sys.executable, str(ROOT / "tests/packaging/upload_path_probe.py")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ISOLATED_UPLOAD_MCP_AND_PATH_DENIALS_OK" in result.stdout


@pytest.mark.parametrize("frozen", [False, True])
@pytest.mark.parametrize("relative", [False, True])
def test_both_data_source_launchers_pass_the_resolved_data_directory(tmp_path, monkeypatch, frozen, relative):
    from src.orchestrator.agent.config import get_data_mcp_config
    from src.services.data_source_mcp_client import DataSourceMCPClient

    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SHIPAGENT_DATA_DIR", "app-data" if relative else str(tmp_path / "app-data"))
    expected = str((tmp_path / "app-data").resolve())
    assert get_data_mcp_config()["env"]["SHIPAGENT_DATA_DIR"] == expected
    assert DataSourceMCPClient()._build_server_params().env["SHIPAGENT_DATA_DIR"] == expected
