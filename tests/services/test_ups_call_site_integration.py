"""Tests for UPS runtime call site integration."""

import os

import pytest


class TestGetUpsMcpConfig:
    """Tests for get_ups_mcp_config with typed credentials."""

    def test_config_with_credentials(self):
        """Typed credentials are used when provided."""
        from src.orchestrator.agent.config import get_ups_mcp_config
        from src.services.connection_types import UPSCredentials

        creds = UPSCredentials(
            client_id="typed_id",
            client_secret="typed_sec",
            environment="production",
            base_url="https://onlinetools.ups.com",
        )
        config = get_ups_mcp_config(credentials=creds)
        assert config is not None
        assert config["env"]["CLIENT_ID"] == "typed_id"
        assert config["env"]["CLIENT_SECRET"] == "typed_sec"
        assert config["env"]["ENVIRONMENT"] == "production"

    def test_config_returns_none_without_credentials(self):
        """Returns None when no credentials available."""
        from src.orchestrator.agent.config import get_ups_mcp_config

        # Clear env vars
        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET"):
            os.environ.pop(var, None)
        config = get_ups_mcp_config(credentials=None)
        assert config is None

    def test_config_env_fallback(self):
        """Falls back to env vars when credentials=None."""
        from src.orchestrator.agent.config import get_ups_mcp_config

        os.environ["UPS_CLIENT_ID"] = "env_id"
        os.environ["UPS_CLIENT_SECRET"] = "env_sec"
        try:
            config = get_ups_mcp_config(credentials=None)
            assert config is not None
            assert config["env"]["CLIENT_ID"] == "env_id"
        finally:
            os.environ.pop("UPS_CLIENT_ID", None)
            os.environ.pop("UPS_CLIENT_SECRET", None)


class TestCreateMcpServersConfig:
    """Tests for create_mcp_servers_config with ups_credentials."""

    def test_ups_key_omitted_when_no_creds(self):
        """UPS key omitted from config when no credentials."""
        from src.orchestrator.agent.config import create_mcp_servers_config

        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET"):
            os.environ.pop(var, None)
        configs = create_mcp_servers_config(ups_credentials=None)
        assert "ups" not in configs
        assert "data" in configs

    def test_ups_key_present_with_creds(self):
        """UPS key present when typed credentials provided."""
        from src.orchestrator.agent.config import create_mcp_servers_config
        from src.services.connection_types import UPSCredentials

        creds = UPSCredentials(
            client_id="id", client_secret="sec",
            environment="test", base_url="https://wwwcie.ups.com",
        )
        configs = create_mcp_servers_config(ups_credentials=creds)
        assert "ups" in configs


class TestGatewayProviderBuild:
    """Tests for _build_ups_gateway using runtime_credentials."""

    def test_build_ups_gateway_raises_without_creds(self):
        """_build_ups_gateway raises RuntimeError when no credentials."""
        from src.services.gateway_provider import _build_ups_gateway

        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET"):
            os.environ.pop(var, None)
        with pytest.raises(RuntimeError, match="No UPS credentials configured"):
            _build_ups_gateway()

    def test_build_ups_gateway_uses_env_fallback(self):
        """_build_ups_gateway uses env var fallback."""
        from src.services.gateway_provider import _build_ups_gateway

        os.environ["UPS_CLIENT_ID"] = "gw_id"
        os.environ["UPS_CLIENT_SECRET"] = "gw_sec"
        try:
            client = _build_ups_gateway()
            assert client is not None
        finally:
            os.environ.pop("UPS_CLIENT_ID", None)
            os.environ.pop("UPS_CLIENT_SECRET", None)
