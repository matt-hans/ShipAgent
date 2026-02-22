"""Unified entry point for the bundled ShipAgent binary.

This module dispatches to the correct subsystem based on the first CLI argument:
  serve        — Start FastAPI server (default)
  mcp-data     — Data Source MCP server (stdio)
  mcp-ups      — UPS MCP server (stdio)
  mcp-external — External Sources MCP server (stdio)
  cli          — Typer CLI (daemon, submit, interact, job)

In PyInstaller bundles, MCP servers self-spawn this same binary with the
appropriate subcommand. See src/orchestrator/agent/config.py for dispatch.
"""

import argparse
import sys


VALID_COMMANDS = {'serve', 'mcp-data', 'mcp-ups', 'mcp-external', 'cli'}


def get_command() -> str:
    """Extract the subcommand from sys.argv, defaulting to 'serve'."""
    if len(sys.argv) < 2:
        return 'serve'
    return sys.argv[1]


def get_cli_args() -> list[str]:
    """Return args after 'cli' subcommand for Typer dispatch."""
    return sys.argv[2:]


def parse_serve_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse serve-mode arguments (host, port)."""
    parser = argparse.ArgumentParser(description='ShipAgent server')
    parser.add_argument('--host', default='127.0.0.1', help='Bind address')
    parser.add_argument('--port', type=int, default=0,
                        help='Listen port (0 = OS-assigned to avoid TOCTOU race)')
    return parser.parse_args(args)


def main() -> None:
    """Dispatch to the correct subsystem based on the subcommand."""
    command = get_command()

    if command == 'serve':
        serve_args = parse_serve_args(sys.argv[2:])
        import uvicorn

        # Use a custom server class to print the actual port after binding.
        # Tauri reads "SHIPAGENT_PORT=XXXXX" from stdout to learn the port.
        class PortReportingServer(uvicorn.Server):
            """Uvicorn server that reports the bound port to stdout."""

            def startup(self, sockets=None):
                """Start the server and print the port for Tauri to read."""
                result = super().startup(sockets)
                for server in self.servers:
                    for sock in server.sockets:
                        addr = sock.getsockname()
                        # Print port protocol line for Tauri to parse
                        print(f"SHIPAGENT_PORT={addr[1]}", flush=True)
                return result

        config = uvicorn.Config(
            "src.api.main:app",
            host=serve_args.host,
            port=serve_args.port,
            workers=1,
            log_level='info',
        )
        server = PortReportingServer(config)
        server.run()

    elif command == 'mcp-data':
        from src.mcp.data_source.server import main as mcp_main
        mcp_main()

    elif command == 'mcp-ups':
        from ups_mcp import main as ups_main
        ups_main()

    elif command == 'mcp-external':
        from src.mcp.external_sources.server import main as ext_main
        ext_main()

    elif command == 'cli':
        sys.argv = ['shipagent'] + get_cli_args()
        from src.cli.main import app as cli_app
        cli_app()

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(f"Valid commands: {', '.join(sorted(VALID_COMMANDS))}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
