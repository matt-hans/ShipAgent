"""Smoke tests for contacts CLI sub-commands."""

from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()


def test_contacts_list_help():
    result = runner.invoke(app, ["contacts", "list", "--help"])
    assert result.exit_code == 0
    assert "List" in result.stdout or "list" in result.stdout


def test_commands_list_help():
    result = runner.invoke(app, ["commands", "list", "--help"])
    assert result.exit_code == 0
    assert "List" in result.stdout or "list" in result.stdout
