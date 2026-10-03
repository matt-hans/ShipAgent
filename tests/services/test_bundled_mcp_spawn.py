"""Programmatic MCP clients must self-spawn the frozen binary with mcp-* subcommands.

In a PyInstaller bundle ``sys.executable`` is shipagent-core, which rejects
``-m <module>``; the clients previously always used ``-m`` and so every
bundled data-source/platform/UPS connect died with "Connection closed".
"""

import sys
from unittest.mock import patch

import pytest

from src.services.data_source_mcp_client import DataSourceMCPClient
from src.services.external_sources_mcp_client import ExternalSourcesMCPClient
from src.services.ups_mcp_client import UPSMCPClient
from src.utils.runtime import bundled_mcp_command

CLIENTS = [
    (
        lambda: DataSourceMCPClient()._build_server_params(),
        "mcp-data",
        "src.mcp.data_source.server",
    ),
    (
        lambda: ExternalSourcesMCPClient()._build_server_params(),
        "mcp-external",
        "src.mcp.external_sources.server",
    ),
    (
        lambda: UPSMCPClient("id", "secret", "000000")._build_server_params(),
        "mcp-ups",
        "ups_mcp",
    ),
]


def test_bundled_mcp_command_is_none_outside_a_bundle():
    with patch("src.utils.runtime.is_bundled", return_value=False):
        assert bundled_mcp_command("mcp-data") is None


def test_bundled_mcp_command_spawns_the_frozen_binary():
    with patch("src.utils.runtime.is_bundled", return_value=True):
        assert bundled_mcp_command("mcp-data") == (sys.executable, ["mcp-data"])


@pytest.mark.parametrize(("build", "subcommand", "module"), CLIENTS)
def test_clients_use_bundled_subcommand_when_frozen(build, subcommand, module):
    with patch("src.utils.runtime.is_bundled", return_value=True):
        params = build()

    assert params.command == sys.executable
    assert params.args == [subcommand]


@pytest.mark.parametrize(("build", "subcommand", "module"), CLIENTS)
def test_clients_use_python_module_in_dev(build, subcommand, module):
    with patch("src.utils.runtime.is_bundled", return_value=False):
        params = build()

    assert params.args == ["-m", module]
