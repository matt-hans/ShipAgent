"""Unit tests for src/orchestrator/agent/config.py.

Tests verify:
- MCP server configurations are correctly structured
- Data MCP config points to correct Python module
- Shopify MCP config uses npx with correct credentials
- UPS MCP config uses uvx with correct credentials and environment derivation
- Environment variables are properly passed through
"""

from pathlib import Path

import pytest

from src.orchestrator.agent.config import (
    PROJECT_ROOT,
    _get_python_command,
    create_mcp_servers_config,
    get_data_mcp_config,
    get_ups_mcp_config,
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

    def test_command_uses_preferred_python(self):
        """Data MCP should use the preferred Python interpreter."""
        config = get_data_mcp_config()
        assert config["command"] == _get_python_command()

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

    def test_env_has_path(self):
        """Environment should include PATH for subprocess execution."""
        config = get_data_mcp_config()
        assert "PATH" in config["env"]

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

    @pytest.fixture(autouse=True)
    def _set_ups_env(self, monkeypatch):
        """Provide UPS credentials so get_ups_mcp_config returns a config."""
        monkeypatch.setenv("UPS_CLIENT_ID", "test_id")
        monkeypatch.setenv("UPS_CLIENT_SECRET", "test_secret")

    def test_command_is_python_interpreter(self):
        """UPS MCP should use a valid Python interpreter."""
        config = get_ups_mcp_config()
        cmd = config["command"]
        # Must be either the venv python or sys.executable fallback
        assert "python" in cmd, f"Expected a python interpreter, got: {cmd}"
        assert cmd == _get_python_command()

    def test_args_run_as_module(self):
        """Args should run ups_mcp as a Python module."""
        config = get_ups_mcp_config()
        assert config["args"] == ["-m", "ups_mcp"]

    def test_config_has_required_keys(self):
        """Config should have command, args, and env keys."""
        config = get_ups_mcp_config()
        assert "command" in config
        assert "args" in config
        assert "env" in config

    def test_env_has_ups_credentials(self):
        """Environment should include CLIENT_ID and CLIENT_SECRET."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("UPS_CLIENT_ID", "test_client_id")
            mp.setenv("UPS_CLIENT_SECRET", "test_client_secret")

            config = get_ups_mcp_config()

            assert config["env"]["CLIENT_ID"] == "test_client_id"
            assert config["env"]["CLIENT_SECRET"] == "test_client_secret"

    def test_env_derives_test_environment(self):
        """Should derive 'test' environment from wwwcie base URL."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("UPS_CLIENT_ID", "id")
            mp.setenv("UPS_CLIENT_SECRET", "sec")
            mp.setenv("UPS_BASE_URL", "https://wwwcie.ups.com")

            config = get_ups_mcp_config()
            assert config["env"]["ENVIRONMENT"] == "test"

    def test_env_derives_production_environment(self):
        """Should derive 'production' environment from production base URL."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("UPS_CLIENT_ID", "id")
            mp.setenv("UPS_CLIENT_SECRET", "sec")
            mp.setenv("UPS_BASE_URL", "https://onlinetools.ups.com")

            config = get_ups_mcp_config()
            assert config["env"]["ENVIRONMENT"] == "production"

    def test_env_defaults_to_test(self):
        """Should default to test environment when UPS_BASE_URL is not set."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("UPS_CLIENT_ID", "id")
            mp.setenv("UPS_CLIENT_SECRET", "sec")
            mp.delenv("UPS_BASE_URL", raising=False)

            config = get_ups_mcp_config()
            assert config["env"]["ENVIRONMENT"] == "test"

    def test_env_has_path(self):
        """Environment should include PATH for uvx to work."""
        config = get_ups_mcp_config()
        assert "PATH" in config["env"]

    def test_missing_credentials_returns_none(self):
        """Returns None when UPS credentials are missing."""
        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("UPS_CLIENT_ID", raising=False)
            mp.delenv("UPS_CLIENT_SECRET", raising=False)

            config = get_ups_mcp_config()
            assert config is None

    def test_missing_credentials_logs_warning(self, caplog):
        """Should log a warning when UPS credentials are missing."""
        import logging

        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("UPS_CLIENT_ID", raising=False)
            mp.delenv("UPS_CLIENT_SECRET", raising=False)

            with caplog.at_level(logging.WARNING, logger="src.orchestrator.agent.config"):
                get_ups_mcp_config()

            assert "No UPS credentials available" in caplog.text

    def test_args_is_list(self):
        """Args should be a list."""
        config = get_ups_mcp_config()
        assert isinstance(config["args"], list)

    def test_env_is_dict(self):
        """Env should be a dict."""
        config = get_ups_mcp_config()
        assert isinstance(config["env"], dict)


class TestCreateMCPServersConfig:
    """Tests for the combined MCP servers configuration."""

    def test_returns_dict_with_data_and_external(self):
        """Should always return config for data and external servers."""
        config = create_mcp_servers_config()
        assert isinstance(config, dict)
        assert "data" in config
        assert "external" in config

    def test_includes_ups_when_credentials_available(self, monkeypatch):
        """Should include UPS config when credentials are set."""
        monkeypatch.setenv("UPS_CLIENT_ID", "id")
        monkeypatch.setenv("UPS_CLIENT_SECRET", "sec")
        config = create_mcp_servers_config()
        assert "ups" in config

    def test_omits_ups_when_no_credentials(self, monkeypatch):
        """Should omit UPS config when no credentials are available."""
        monkeypatch.delenv("UPS_CLIENT_ID", raising=False)
        monkeypatch.delenv("UPS_CLIENT_SECRET", raising=False)
        config = create_mcp_servers_config()
        assert "ups" not in config

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

    def test_data_uses_preferred_python(self):
        """Data server should use the preferred Python command."""
        config = create_mcp_servers_config()
        assert config["data"]["command"] == _get_python_command()

    def test_external_uses_preferred_python(self):
        """External Sources server should use the preferred Python command."""
        config = create_mcp_servers_config()
        assert config["external"]["command"] == _get_python_command()

    def test_ups_uses_preferred_python(self, monkeypatch):
        """UPS server should use the preferred Python command."""
        monkeypatch.setenv("UPS_CLIENT_ID", "id")
        monkeypatch.setenv("UPS_CLIENT_SECRET", "sec")
        config = create_mcp_servers_config()
        assert config["ups"]["command"] == _get_python_command()

    def test_ups_config_is_valid(self, monkeypatch):
        """UPS config should have required keys."""
        monkeypatch.setenv("UPS_CLIENT_ID", "id")
        monkeypatch.setenv("UPS_CLIENT_SECRET", "sec")
        config = create_mcp_servers_config()
        ups_config = config["ups"]
        assert "command" in ups_config
        assert "args" in ups_config
        assert "env" in ups_config

    def test_returns_new_dict_each_call(self):
        """Each call should return a fresh dict (not cached)."""
        config1 = create_mcp_servers_config()
        config2 = create_mcp_servers_config()
        assert config1 is not config2


class TestUPSMCPConfigAccountNumber:
    """Tests for UPS_ACCOUNT_NUMBER in MCP subprocess config."""

    def test_ups_mcp_config_includes_account_number(self, monkeypatch):
        """UPS MCP subprocess env must include UPS_ACCOUNT_NUMBER."""
        monkeypatch.setenv("UPS_CLIENT_ID", "test-id")
        monkeypatch.setenv("UPS_CLIENT_SECRET", "test-secret")
        monkeypatch.setenv("UPS_ACCOUNT_NUMBER", "ABC123")
        config = get_ups_mcp_config()
        assert config["env"]["UPS_ACCOUNT_NUMBER"] == "ABC123"

    def test_ups_mcp_config_account_number_defaults_empty(self, monkeypatch):
        """UPS_ACCOUNT_NUMBER defaults to empty string when not set."""
        monkeypatch.setenv("UPS_CLIENT_ID", "test-id")
        monkeypatch.setenv("UPS_CLIENT_SECRET", "test-secret")
        monkeypatch.delenv("UPS_ACCOUNT_NUMBER", raising=False)
        config = get_ups_mcp_config()
        assert config["env"]["UPS_ACCOUNT_NUMBER"] == ""
