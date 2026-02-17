"""Integration tests for the CLI — end-to-end command execution."""

from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()


class TestCLICommands:
    """Tests for CLI command invocation."""

    def test_version(self):
        """Version command prints version string."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "ShipAgent" in result.stdout

    def test_help(self):
        """Help shows available commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "daemon" in result.stdout
        assert "job" in result.stdout
        assert "submit" in result.stdout
        assert "interact" in result.stdout

    def test_config_validate_no_file(self):
        """Config validate fails when no config file exists."""
        result = runner.invoke(app, ["config", "validate"])
        assert result.exit_code == 1

    def test_config_validate_with_file(self, tmp_path):
        """Config validate succeeds with valid YAML."""
        config_file = tmp_path / "shipagent.yaml"
        config_file.write_text("daemon:\n  port: 9000\n")
        result = runner.invoke(app, ["config", "validate", "--config", str(config_file)])
        assert result.exit_code == 0
        assert "valid" in result.stdout.lower()

    def test_daemon_status_not_running(self):
        """Daemon status reports not running when no PID file."""
        result = runner.invoke(app, ["daemon", "status"])
        assert result.exit_code == 0
        assert "not running" in result.stdout.lower()

    def test_submit_missing_file(self):
        """Submit fails with clear error for missing file."""
        result = runner.invoke(app, ["submit", "/nonexistent/file.csv"])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()

    def test_job_list_standalone(self):
        """Job list in standalone mode returns empty list."""
        result = runner.invoke(app, ["--standalone", "job", "list"])
        assert result.exit_code == 0
