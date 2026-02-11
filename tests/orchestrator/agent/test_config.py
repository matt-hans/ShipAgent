"""Unit tests for src/orchestrator/agent/config.py.

Tests verify:
- MCP server configurations are correctly structured
- Data MCP config points to correct Python module
- Shopify MCP config uses npx with correct credentials
- Environment variables are properly passed through

Note: UPS integration is now a direct Python import (UPSService),
not a subprocess MCP server. See src/services/ups_service.py.
"""

from pathlib import Path

import pytest

from src.orchestrator.agent.config import (
    PROJECT_ROOT,
    create_mcp_servers_config,
    get_data_mcp_config,
    get_shopify_mcp_config,
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


class TestShopifyMCPConfig:
    """Tests for Shopify MCP configuration."""

    def test_command_is_npx(self):
        """Shopify MCP should use npx to run shopify-mcp."""
        config = get_shopify_mcp_config()
        assert config["command"] == "npx"

    def test_args_specify_shopify_mcp(self):
        """Args should specify shopify-mcp package."""
        config = get_shopify_mcp_config()
        assert "shopify-mcp" in config["args"]
        assert "--accessToken" in config["args"]
        assert "--domain" in config["args"]

    def test_config_has_required_keys(self):
        """Config should have command, args, and env keys."""
        config = get_shopify_mcp_config()
        assert "command" in config
        assert "args" in config
        assert "env" in config

    def test_env_passes_shopify_credentials(self):
        """Environment should pass Shopify credential env vars via args."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test_token_123")
            mp.setenv("SHOPIFY_STORE_DOMAIN", "test-store.myshopify.com")

            config = get_shopify_mcp_config()

            # Credentials are passed as args, not env vars
            assert "shpat_test_token_123" in config["args"]
            assert "test-store.myshopify.com" in config["args"]

    def test_env_has_path(self):
        """Environment should include PATH for npx to work."""
        config = get_shopify_mcp_config()
        assert "PATH" in config["env"]

    def test_missing_credentials_still_returns_config(self):
        """Config should still be returned even if credentials are missing."""
        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("SHOPIFY_ACCESS_TOKEN", raising=False)
            mp.delenv("SHOPIFY_STORE_DOMAIN", raising=False)

            config = get_shopify_mcp_config()

            # Should still return a valid config structure
            assert "command" in config
            assert "args" in config
            assert "env" in config

    def test_args_is_list(self):
        """Args should be a list."""
        config = get_shopify_mcp_config()
        assert isinstance(config["args"], list)

    def test_env_is_dict(self):
        """Env should be a dict."""
        config = get_shopify_mcp_config()
        assert isinstance(config["env"], dict)


class TestCreateMCPServersConfig:
    """Tests for the combined MCP servers configuration."""

    def test_returns_dict_with_all_servers(self):
        """Should return config for data, shopify, and external servers."""
        config = create_mcp_servers_config()
        assert isinstance(config, dict)
        assert "data" in config
        assert "shopify" in config
        assert "external" in config

    def test_data_config_is_valid(self):
        """Data config should have required keys."""
        config = create_mcp_servers_config()
        data_config = config["data"]
        assert "command" in data_config
        assert "args" in data_config
        assert "env" in data_config

    def test_external_config_is_valid(self):
        """External Sources config should have required keys."""
        config = create_mcp_servers_config()
        external_config = config["external"]
        assert "command" in external_config
        assert "args" in external_config
        assert "env" in external_config

    def test_data_uses_python3(self):
        """Data server should use python3 command."""
        config = create_mcp_servers_config()
        assert config["data"]["command"] == "python3"

    def test_external_uses_python3(self):
        """External Sources server should use python3 command."""
        config = create_mcp_servers_config()
        assert config["external"]["command"] == "python3"

    def test_shopify_uses_npx(self):
        """Shopify server should use npx command."""
        config = create_mcp_servers_config()
        assert config["shopify"]["command"] == "npx"

    def test_shopify_config_is_valid(self):
        """Shopify config should have required keys."""
        config = create_mcp_servers_config()
        shopify_config = config["shopify"]
        assert "command" in shopify_config
        assert "args" in shopify_config
        assert "env" in shopify_config

    def test_returns_new_dict_each_call(self):
        """Each call should return a fresh dict (not cached)."""
        config1 = create_mcp_servers_config()
        config2 = create_mcp_servers_config()
        assert config1 is not config2
