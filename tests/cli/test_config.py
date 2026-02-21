"""Tests for CLI configuration loading and validation."""


import yaml

from src.cli.config import (
    AutoConfirmRules,
    DaemonConfig,
    WatchFolderConfig,
    load_config,
    resolve_env_vars,
)


class TestDaemonConfig:
    """Tests for DaemonConfig defaults and validation."""

    def test_defaults(self):
        """All defaults are sensible for single-worker SQLite."""
        cfg = DaemonConfig()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8000
        assert cfg.workers == 1
        assert cfg.log_level == "info"
        assert cfg.log_format == "text"
        assert cfg.log_file is None

    def test_custom_values(self):
        """Custom values override defaults."""
        cfg = DaemonConfig(host="0.0.0.0", port=9000, log_level="debug")
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 9000
        assert cfg.log_level == "debug"


class TestAutoConfirmRules:
    """Tests for auto-confirm rule defaults and validation."""

    def test_defaults_are_conservative(self):
        """Default auto-confirm is disabled with safe thresholds."""
        rules = AutoConfirmRules()
        assert rules.enabled is False
        assert rules.max_cost_cents == 50000
        assert rules.max_rows == 500
        assert rules.max_cost_per_row_cents == 5000
        assert rules.allowed_services == []
        assert rules.require_valid_addresses is True
        assert rules.allow_warnings is False

    def test_custom_rules(self):
        """Custom rules override defaults."""
        rules = AutoConfirmRules(
            enabled=True,
            max_cost_cents=100000,
            allowed_services=["03", "02"],
        )
        assert rules.enabled is True
        assert rules.max_cost_cents == 100000
        assert rules.allowed_services == ["03", "02"]


class TestWatchFolderConfig:
    """Tests for watch folder configuration."""

    def test_required_fields(self):
        """Path and command are required."""
        cfg = WatchFolderConfig(path="./inbox", command="Ship all orders")
        assert cfg.path == "./inbox"
        assert cfg.command == "Ship all orders"
        assert cfg.auto_confirm is False
        assert cfg.file_types == [".csv", ".xlsx"]

    def test_per_folder_overrides(self):
        """Per-folder overrides inherit None for global fallback."""
        cfg = WatchFolderConfig(
            path="./inbox/priority",
            command="Ship via Next Day Air",
            auto_confirm=True,
            max_cost_cents=100000,
        )
        assert cfg.auto_confirm is True
        assert cfg.max_cost_cents == 100000
        assert cfg.max_rows is None  # inherits global


class TestResolveEnvVars:
    """Tests for ${VAR} resolution in config values."""

    def test_resolves_env_var(self, monkeypatch):
        """${VAR} syntax resolves from environment."""
        monkeypatch.setenv("TEST_SECRET", "my-secret-key")
        assert resolve_env_vars("${TEST_SECRET}") == "my-secret-key"

    def test_passthrough_no_vars(self):
        """Strings without ${} pass through unchanged."""
        assert resolve_env_vars("plain-value") == "plain-value"

    def test_missing_env_var_returns_empty(self):
        """Missing env vars resolve to empty string."""
        result = resolve_env_vars("${DEFINITELY_NOT_SET_XYZ}")
        assert result == ""

    def test_mixed_content(self, monkeypatch):
        """${VAR} embedded in other text resolves correctly."""
        monkeypatch.setenv("MY_HOST", "localhost")
        assert resolve_env_vars("http://${MY_HOST}:8000") == "http://localhost:8000"


class TestLoadConfig:
    """Tests for YAML config file loading."""

    def test_load_from_explicit_path(self, tmp_path):
        """Load config from explicit --config path."""
        config_data = {
            "daemon": {"port": 9000},
            "auto_confirm": {"enabled": True, "max_rows": 100},
        }
        config_file = tmp_path / "shipagent.yaml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(config_path=str(config_file))
        assert cfg is not None
        assert cfg.daemon.port == 9000
        assert cfg.auto_confirm.enabled is True
        assert cfg.auto_confirm.max_rows == 100

    def test_returns_none_when_no_config(self, tmp_path, monkeypatch):
        """Returns None when no config file is found."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        cfg = load_config()
        assert cfg is None

    def test_env_var_override(self, tmp_path, monkeypatch):
        """SHIPAGENT_ env vars override YAML values."""
        config_data = {"daemon": {"port": 8000}}
        config_file = tmp_path / "shipagent.yaml"
        config_file.write_text(yaml.dump(config_data))
        monkeypatch.setenv("SHIPAGENT_DAEMON_PORT", "9999")

        cfg = load_config(config_path=str(config_file))
        assert cfg is not None
        assert cfg.daemon.port == 9999

    def test_dollar_var_resolution(self, tmp_path, monkeypatch):
        """${VAR} in YAML values resolve from environment."""
        monkeypatch.setenv("MY_UPS_KEY", "secret-123")
        config_data = {"ups": {"client_id": "${MY_UPS_KEY}"}}
        config_file = tmp_path / "shipagent.yaml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(config_path=str(config_file))
        assert cfg is not None
        assert cfg.ups is not None
        assert cfg.ups.client_id == "secret-123"

    def test_watch_folders(self, tmp_path):
        """Watch folders parse correctly from YAML."""
        config_data = {
            "watch_folders": [
                {
                    "path": "./inbox/priority",
                    "command": "Ship via Next Day Air",
                    "auto_confirm": True,
                    "file_types": [".csv"],
                }
            ]
        }
        config_file = tmp_path / "shipagent.yaml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(config_path=str(config_file))
        assert cfg is not None
        assert len(cfg.watch_folders) == 1
        assert cfg.watch_folders[0].command == "Ship via Next Day Air"
        assert cfg.watch_folders[0].auto_confirm is True

    def test_full_config(self, tmp_path, monkeypatch):
        """Full config with all sections parses correctly."""
        monkeypatch.setenv("UPS_ACCT", "ABC123")
        config_data = {
            "daemon": {"host": "0.0.0.0", "port": 9000, "log_format": "json"},
            "auto_confirm": {
                "enabled": True,
                "max_cost_cents": 100000,
                "allowed_services": ["03", "02"],
            },
            "watch_folders": [
                {"path": "./inbox", "command": "Ship all orders"}
            ],
            "shipper": {
                "name": "Acme Corp",
                "address_line": "123 Main St",
                "city": "Los Angeles",
                "state": "CA",
                "postal_code": "90001",
                "country_code": "US",
                "phone": "5551234567",
            },
            "ups": {"account_number": "${UPS_ACCT}"},
        }
        config_file = tmp_path / "shipagent.yaml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(config_path=str(config_file))
        assert cfg is not None
        assert cfg.daemon.host == "0.0.0.0"
        assert cfg.auto_confirm.allowed_services == ["03", "02"]
        assert cfg.shipper is not None
        assert cfg.shipper.name == "Acme Corp"
        assert cfg.ups is not None
        assert cfg.ups.account_number == "ABC123"
