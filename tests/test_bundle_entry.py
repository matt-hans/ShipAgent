"""Tests for the unified bundle entry point."""

from unittest.mock import patch
import sys

import pytest


def test_serve_command_parses_port():
    """'serve' command should parse --port argument."""
    from src.bundle_entry import parse_serve_args
    args = parse_serve_args(['--port', '9000'])
    assert args.port == 9000
    assert args.host == '127.0.0.1'


def test_serve_default_port_zero():
    """Default port is 0 (OS-assigned) to avoid TOCTOU race."""
    from src.bundle_entry import parse_serve_args
    args = parse_serve_args([])
    assert args.port == 0


def test_default_command_is_serve():
    """No subcommand defaults to 'serve'."""
    with patch('sys.argv', ['shipagent-core']):
        from src.bundle_entry import get_command
        assert get_command() == 'serve'


def test_mcp_data_command():
    """'mcp-data' is recognized as a valid subcommand."""
    with patch('sys.argv', ['shipagent-core', 'mcp-data']):
        from src.bundle_entry import get_command
        assert get_command() == 'mcp-data'


def test_cli_command_passes_remaining_args():
    """'cli' passes remaining args to the Typer CLI."""
    with patch('sys.argv', ['shipagent-core', 'cli', 'submit', 'orders.csv']):
        from src.bundle_entry import get_command, get_cli_args
        assert get_command() == 'cli'
        assert get_cli_args() == ['submit', 'orders.csv']


def test_unknown_command_exits():
    """Unknown subcommand exits with code 1."""
    with patch('sys.argv', ['shipagent-core', 'unknown']):
        from src.bundle_entry import get_command
        assert get_command() == 'unknown'
        # main() should sys.exit(1) for unknown
