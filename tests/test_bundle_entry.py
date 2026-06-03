"""Tests for the unified bundle entry point."""

import sys
import types
from unittest.mock import patch

import pytest


def test_serve_command_parses_port():
    """'serve' command should parse --port argument."""
    from src.bundle_entry import parse_serve_args

    args = parse_serve_args(["--port", "9000"])
    assert args.port == 9000
    assert args.host == "127.0.0.1"


def test_serve_default_port_zero():
    """Default port is 0 (OS-assigned) to avoid TOCTOU race."""
    from src.bundle_entry import parse_serve_args

    args = parse_serve_args([])
    assert args.port == 0


def test_default_command_is_serve():
    """No subcommand defaults to 'serve'."""
    with patch("sys.argv", ["shipagent-core"]):
        from src.bundle_entry import get_command

        assert get_command() == "serve"


def test_mcp_data_command():
    """'mcp-data' is recognized as a valid subcommand."""
    with patch("sys.argv", ["shipagent-core", "mcp-data"]):
        from src.bundle_entry import get_command

        assert get_command() == "mcp-data"


def test_cli_command_passes_remaining_args():
    """'cli' passes remaining args to the Typer CLI."""
    with patch("sys.argv", ["shipagent-core", "cli", "submit", "orders.csv"]):
        from src.bundle_entry import get_cli_args, get_command

        assert get_command() == "cli"
        assert get_cli_args() == ["submit", "orders.csv"]


def test_unknown_command_exits():
    """Unknown subcommand exits with code 1."""
    with patch("sys.argv", ["shipagent-core", "unknown"]):
        from src.bundle_entry import get_command

        assert get_command() == "unknown"
        # main() should sys.exit(1) for unknown


def test_data_source_server_main_runs_stdio(monkeypatch):
    import src.mcp.data_source.server as server

    called = {}

    def fake_run(**kwargs):
        called["kwargs"] = kwargs

    monkeypatch.setattr(server.mcp, "run", fake_run)

    server.main()

    assert called["kwargs"] == {"transport": "stdio"}


def test_external_sources_server_main_runs_stdio(monkeypatch):
    import src.mcp.external_sources.server as server

    called = {}

    def fake_run(**kwargs):
        called["kwargs"] = kwargs

    monkeypatch.setattr(server.mcp, "run", fake_run)

    server.main()

    assert called["kwargs"] == {"transport": "stdio"}


def test_bundle_entry_dispatches_mcp_data(monkeypatch):
    import src.bundle_entry as bundle_entry

    called = {"value": False}

    def fake_main():
        called["value"] = True

    monkeypatch.setattr("src.mcp.data_source.server.main", fake_main)
    monkeypatch.setattr(bundle_entry.sys, "argv", ["shipagent-core", "mcp-data"])

    bundle_entry.main()

    assert called["value"] is True


def test_bundle_entry_dispatches_mcp_external(monkeypatch):
    import src.bundle_entry as bundle_entry

    called = {"value": False}

    def fake_main():
        called["value"] = True

    monkeypatch.setattr("src.mcp.external_sources.server.main", fake_main)
    monkeypatch.setattr(bundle_entry.sys, "argv", ["shipagent-core", "mcp-external"])

    bundle_entry.main()

    assert called["value"] is True


def test_bundle_entry_dispatches_mcp_ups_primary_server(monkeypatch):
    import src.bundle_entry as bundle_entry

    calls = []
    ups_package = types.ModuleType("ups_mcp")
    ups_package.__path__ = []
    server_module = types.ModuleType("ups_mcp.server")

    def server_main():
        calls.append("server")

    def legacy_main():
        calls.append("legacy")

    server_module.main = server_main
    ups_package.main = legacy_main
    monkeypatch.setitem(sys.modules, "ups_mcp", ups_package)
    monkeypatch.setitem(sys.modules, "ups_mcp.server", server_module)
    monkeypatch.setattr(bundle_entry.sys, "argv", ["shipagent-core", "mcp-ups"])

    bundle_entry.main()

    assert calls == ["server"]


def test_bundle_entry_dispatches_mcp_ups_legacy_fallback(monkeypatch):
    import src.bundle_entry as bundle_entry

    calls = []
    ups_package = types.ModuleType("ups_mcp")
    ups_package.__path__ = []

    def legacy_main():
        calls.append("legacy")

    ups_package.main = legacy_main
    monkeypatch.setitem(sys.modules, "ups_mcp", ups_package)
    monkeypatch.delitem(sys.modules, "ups_mcp.server", raising=False)
    monkeypatch.setattr(bundle_entry.sys, "argv", ["shipagent-core", "mcp-ups"])

    bundle_entry.main()

    assert calls == ["legacy"]


def test_bundle_entry_reraises_unrelated_mcp_ups_import_error(monkeypatch, tmp_path):
    import src.bundle_entry as bundle_entry

    package_dir = tmp_path / "ups_mcp"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("def main():\n    pass\n")
    (package_dir / "server.py").write_text(
        "import missing_ups_dependency\n\ndef main():\n    pass\n"
    )

    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "ups_mcp", raising=False)
    monkeypatch.delitem(sys.modules, "ups_mcp.server", raising=False)
    monkeypatch.setattr(bundle_entry.sys, "argv", ["shipagent-core", "mcp-ups"])

    with pytest.raises(ModuleNotFoundError) as exc_info:
        bundle_entry.main()

    assert exc_info.value.name == "missing_ups_dependency"


def test_bundle_entry_reraises_existing_mcp_ups_server_import_error(
    monkeypatch, tmp_path
):
    import src.bundle_entry as bundle_entry

    package_dir = tmp_path / "ups_mcp"
    server_file = package_dir / "server.py"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("def main():\n    pass\n")
    server_file.write_text(
        "raise ImportError(\n"
        "    'broken primary server import',\n"
        "    name='ups_mcp.server',\n"
        "    path=__file__,\n"
        ")\n"
    )

    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "ups_mcp", raising=False)
    monkeypatch.delitem(sys.modules, "ups_mcp.server", raising=False)
    monkeypatch.setattr(bundle_entry.sys, "argv", ["shipagent-core", "mcp-ups"])

    with pytest.raises(ImportError) as exc_info:
        bundle_entry.main()

    assert exc_info.value.name == "ups_mcp.server"
    assert exc_info.value.path == str(server_file)
