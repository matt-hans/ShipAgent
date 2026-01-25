"""Unit tests for src/orchestrator/agent/config.py.

Tests verify:
- MCP server configurations are correctly structured
- Data MCP config points to correct Python module
- UPS MCP config points to correct Node.js entry point
- Environment variables are properly passed through
"""

import os
from pathlib import Path

import pytest

from src.orchestrator.agent.config import (
    PROJECT_ROOT,
    get_data_mcp_config,
    get_ups_mcp_config,
    create_mcp_servers_config,
)


class TestProjectRoot:
    """Tests for PROJECT_ROOT constant."""

    def test_project_root_is_path(self):
        """PROJECT_ROOT should be a Path object."""
        assert isinstance(PROJECT_ROOT, Path)

    def test_project_root_exists(self):
        """PROJECT_ROOT should point to an existing directory."""
        assert PROJECT_ROOT.exists()
        assert PROJECT_ROOT.is_dir()

    def test_project_root_contains_src(self):
        """PROJECT_ROOT should contain src/ directory."""
        assert (PROJECT_ROOT / "src").exists()


class TestDataMCPConfig:
    """Tests for Data MCP configuration."""

    def test_command_is_python3(self):
        """Data MCP should use Python3 interpreter."""
        config = get_data_mcp_config()
        assert config["command"] == "python3"

    def test_args_specify_module(self):
        """Args should specify the server module."""
        config = get_data_mcp_config()
        assert "-m" in config["args"]
        assert "src.mcp.data_source.server" in config["args"]

    def test_env_has_pythonpath(self):
        """Environment should include PYTHONPATH."""
        config = get_data_mcp_config()
        assert "PYTHONPATH" in config["env"]
        assert str(PROJECT_ROOT) in config["env"]["PYTHONPATH"]

    def test_config_has_required_keys(self):
        """Config should have command, args, and env keys."""
        config = get_data_mcp_config()
        assert "command" in config
        assert "args" in config
        assert "env" in config

    def test_args_is_list(self):
        """Args should be a list."""
        config = get_data_mcp_config()
        assert isinstance(config["args"], list)

    def test_env_is_dict(self):
        """Env should be a dict."""
        config = get_data_mcp_config()
        assert isinstance(config["env"], dict)


class TestUPSMCPConfig:
    """Tests for UPS MCP configuration."""

    def test_command_is_node(self):
        """UPS MCP should use Node.js."""
        config = get_ups_mcp_config()
        assert config["command"] == "node"

    def test_args_specify_dist_path(self):
        """Args should specify the dist/index.js path."""
        config = get_ups_mcp_config()
        assert len(config["args"]) >= 1
        assert "ups-mcp" in config["args"][0]
        assert "dist" in config["args"][0]
        assert "index.js" in config["args"][0]

    def test_env_passes_ups_credentials(self):
        """Environment should pass UPS credential env vars."""
        # Set test env vars
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("UPS_CLIENT_ID", "test-client-id")
            mp.setenv("UPS_CLIENT_SECRET", "test-secret")
            mp.setenv("UPS_ACCOUNT_NUMBER", "123456")

            config = get_ups_mcp_config()

            assert "UPS_CLIENT_ID" in config["env"]
            assert "UPS_CLIENT_SECRET" in config["env"]
            assert "UPS_ACCOUNT_NUMBER" in config["env"]
            assert config["env"]["UPS_CLIENT_ID"] == "test-client-id"
            assert config["env"]["UPS_CLIENT_SECRET"] == "test-secret"
            assert config["env"]["UPS_ACCOUNT_NUMBER"] == "123456"

    def test_env_has_labels_output_dir(self):
        """Environment should include labels output directory."""
        config = get_ups_mcp_config()
        assert "UPS_LABELS_OUTPUT_DIR" in config["env"]

    def test_missing_credentials_still_returns_config(self):
        """Config should still be returned even if credentials are missing."""
        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("UPS_CLIENT_ID", raising=False)
            mp.delenv("UPS_CLIENT_SECRET", raising=False)
            mp.delenv("UPS_ACCOUNT_NUMBER", raising=False)

            config = get_ups_mcp_config()

            # Should still return a valid config structure
            assert "command" in config
            assert "args" in config
            assert "env" in config

    def test_labels_dir_default(self):
        """Labels dir should default to PROJECT_ROOT/labels."""
        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("UPS_LABELS_OUTPUT_DIR", raising=False)

            config = get_ups_mcp_config()

            expected_path = str(PROJECT_ROOT / "labels")
            assert config["env"]["UPS_LABELS_OUTPUT_DIR"] == expected_path

    def test_labels_dir_override(self):
        """Labels dir should use UPS_LABELS_OUTPUT_DIR env var if set."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("UPS_LABELS_OUTPUT_DIR", "/custom/labels/path")

            config = get_ups_mcp_config()

            assert config["env"]["UPS_LABELS_OUTPUT_DIR"] == "/custom/labels/path"


class TestCreateMCPServersConfig:
    """Tests for the combined MCP servers configuration."""

    def test_returns_dict_with_both_servers(self):
        """Should return config for both data and ups servers."""
        config = create_mcp_servers_config()
        assert isinstance(config, dict)
        assert "data" in config
        assert "ups" in config

    def test_data_config_is_valid(self):
        """Data config should have required keys."""
        config = create_mcp_servers_config()
        data_config = config["data"]
        assert "command" in data_config
        assert "args" in data_config
        assert "env" in data_config

    def test_ups_config_is_valid(self):
        """UPS config should have required keys."""
        config = create_mcp_servers_config()
        ups_config = config["ups"]
        assert "command" in ups_config
        assert "args" in ups_config
        assert "env" in ups_config

    def test_data_uses_python3(self):
        """Data server should use python3 command."""
        config = create_mcp_servers_config()
        assert config["data"]["command"] == "python3"

    def test_ups_uses_node(self):
        """UPS server should use node command."""
        config = create_mcp_servers_config()
        assert config["ups"]["command"] == "node"

    def test_returns_new_dict_each_call(self):
        """Each call should return a fresh dict (not cached)."""
        config1 = create_mcp_servers_config()
        config2 = create_mcp_servers_config()
        assert config1 is not config2
