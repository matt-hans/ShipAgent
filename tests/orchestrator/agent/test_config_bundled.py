"""Tests for MCP config in bundled mode."""

import sys
from unittest.mock import patch

from src.orchestrator.agent.config import (
    get_data_mcp_config,
    get_external_sources_mcp_config,
)


def test_data_mcp_config_bundled_uses_self_executable():
    """In bundled mode, MCP spawns self with subcommand."""
    with patch.object(sys, 'frozen', True, create=True):
        with patch.object(sys, 'executable', '/app/shipagent-core'):
            config = get_data_mcp_config()
            assert config["command"] == "/app/shipagent-core"
            assert config["args"] == ["mcp-data"]


def test_data_mcp_config_dev_uses_python_module():
    """In dev mode, MCP uses python -m module pattern."""
    frozen_backup = getattr(sys, 'frozen', None)
    if hasattr(sys, 'frozen'):
        delattr(sys, 'frozen')
    try:
        config = get_data_mcp_config()
        assert "-m" in config["args"]
        assert "src.mcp.data_source.server" in config["args"]
    finally:
        if frozen_backup is not None:
            sys.frozen = frozen_backup


def test_external_mcp_config_bundled():
    """In bundled mode, external MCP uses self with subcommand."""
    with patch.object(sys, 'frozen', True, create=True):
        with patch.object(sys, 'executable', '/app/shipagent-core'):
            config = get_external_sources_mcp_config()
            assert config["command"] == "/app/shipagent-core"
            assert config["args"] == ["mcp-external"]
