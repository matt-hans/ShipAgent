"""Integration tests for the CLI — end-to-end command execution."""

from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from src.cli.config import AutoConfirmRules, ShipAgentConfig
from src.cli.main import app
from src.cli.protocol import RowDetail, SubmitResult

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


class TestSubmitAutoConfirm:
    """Tests for CLI submit --auto-confirm rule evaluation flow."""

    def _make_mock_client(
        self, rows: list[RowDetail], approve_mock: AsyncMock | None = None
    ) -> MagicMock:
        """Build a mock ShipAgentClient with canned submit + rows responses."""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.submit_file = AsyncMock(return_value=SubmitResult(
            job_id="job-ac-test",
            status="pending",
            row_count=len(rows),
            message="File uploaded",
        ))
        mock_client.get_job_rows = AsyncMock(return_value=rows)
        mock_client.approve_job = approve_mock or AsyncMock()
        return mock_client

    def _make_config(self, rules: AutoConfirmRules) -> ShipAgentConfig:
        """Wrap AutoConfirmRules in a minimal ShipAgentConfig."""
        return ShipAgentConfig(auto_confirm=rules)

    def test_approved_when_rules_pass(self, tmp_path):
        """approve_job is called when all auto-confirm rules are satisfied."""
        csv_file = tmp_path / "orders.csv"
        csv_file.write_text("name\nAlice\n")

        rules = AutoConfirmRules(
            enabled=True,
            max_cost_cents=100_000,
            max_rows=500,
            max_cost_per_row_cents=5_000,
            # Conservative defaults block on address state; disable for this test.
            require_valid_addresses=False,
        )
        rows = [RowDetail(
            id="row-1", row_number=1, status="preview",
            tracking_number=None, cost_cents=500,
            error_code=None, error_message=None,
            order_data='{"service_code": "03"}',
        )]

        approve_mock = AsyncMock()
        mock_client = self._make_mock_client(rows, approve_mock)
        config = self._make_config(rules)

        with patch("src.cli.main.load_config", return_value=config), \
             patch("src.cli.main.get_client", return_value=mock_client):
            result = runner.invoke(app, ["submit", str(csv_file), "--auto-confirm"])

        assert result.exit_code == 0
        approve_mock.assert_called_once_with("job-ac-test")
        assert "executing" in result.stdout.lower() or "running" in result.stdout.lower()

    def test_blocked_when_cost_exceeds_limit(self, tmp_path):
        """approve_job is NOT called when total cost exceeds max_cost_cents."""
        csv_file = tmp_path / "orders.csv"
        csv_file.write_text("name\nBob\n")

        rules = AutoConfirmRules(
            enabled=True,
            max_cost_cents=100,  # Very low threshold
            require_valid_addresses=False,
        )
        rows = [RowDetail(
            id="row-1", row_number=1, status="preview",
            tracking_number=None, cost_cents=5_000,  # Exceeds the 100-cent limit
            error_code=None, error_message=None,
        )]

        approve_mock = AsyncMock()
        mock_client = self._make_mock_client(rows, approve_mock)
        config = self._make_config(rules)

        with patch("src.cli.main.load_config", return_value=config), \
             patch("src.cli.main.get_client", return_value=mock_client):
            result = runner.invoke(app, ["submit", str(csv_file), "--auto-confirm"])

        assert result.exit_code == 0
        approve_mock.assert_not_called()
        assert "blocked" in result.stdout.lower()

    def test_blocked_when_service_not_allowed(self, tmp_path):
        """approve_job is NOT called when the service code is not in allowed_services."""
        csv_file = tmp_path / "orders.csv"
        csv_file.write_text("name\nCarol\n")

        rules = AutoConfirmRules(
            enabled=True,
            allowed_services=["03"],  # Only UPS Ground
            require_valid_addresses=False,
        )
        rows = [RowDetail(
            id="row-1", row_number=1, status="preview",
            tracking_number=None, cost_cents=500,
            error_code=None, error_message=None,
            order_data='{"service_code": "01"}',  # UPS Next Day Air — not in whitelist
        )]

        approve_mock = AsyncMock()
        mock_client = self._make_mock_client(rows, approve_mock)
        config = self._make_config(rules)

        with patch("src.cli.main.load_config", return_value=config), \
             patch("src.cli.main.get_client", return_value=mock_client):
            result = runner.invoke(app, ["submit", str(csv_file), "--auto-confirm"])

        assert result.exit_code == 0
        approve_mock.assert_not_called()
        assert "blocked" in result.stdout.lower()
