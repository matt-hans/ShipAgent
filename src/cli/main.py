"""ShipAgent CLI — headless automation suite.

Unified entry point for daemon management, job control,
file submission, and conversational shipping.

Usage:
    shipagent daemon start     Start the ShipAgent daemon
    shipagent job list         List all jobs
    shipagent submit file.csv  Submit a file for processing
    shipagent interact         Start conversational REPL
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console

from src.cli.config import load_config
from src.cli.factory import get_client
from src.cli.output import format_job_detail, format_job_table, format_rows_table
from src.cli.protocol import ShipAgentClientError

app = typer.Typer(
    name="shipagent",
    help="AI-native shipping automation — headless CLI",
    no_args_is_help=True,
)
daemon_app = typer.Typer(help="Manage the ShipAgent daemon")
job_app = typer.Typer(help="Manage shipping jobs")
config_app = typer.Typer(help="Configuration management")

app.add_typer(daemon_app, name="daemon")
app.add_typer(job_app, name="job")
app.add_typer(config_app, name="config")

console = Console()

# --- Global state ---
_standalone: bool = False
_config_path: str | None = None


@app.callback()
def main(
    standalone: bool = typer.Option(
        False, "--standalone", help="Run in-process without daemon"
    ),
    config: Optional[str] = typer.Option(
        None, "--config", help="Path to shipagent.yaml config file"
    ),
):
    """ShipAgent CLI — AI-native shipping automation."""
    global _standalone, _config_path
    _standalone = standalone
    _config_path = config


# --- Version ---


@app.command()
def version():
    """Show ShipAgent version and dependency info."""
    from importlib.metadata import version as pkg_version
    try:
        v = pkg_version("shipagent")
    except Exception:
        v = "unknown"
    console.print(f"[bold]ShipAgent[/bold] v{v}")
    console.print("  CLI: headless automation suite")
    try:
        import claude_agent_sdk
        console.print(f"  Agent SDK: {getattr(claude_agent_sdk, '__version__', 'unknown')}")
    except ImportError:
        console.print("  Agent SDK: [red]not installed[/red]")


# --- Config commands ---


@config_app.command("show")
def config_show():
    """Display resolved configuration (secrets masked)."""
    cfg = load_config(config_path=_config_path)
    if cfg is None:
        console.print("[yellow]No config file found.[/yellow]")
        console.print("Searched: ./shipagent.yaml, ~/.shipagent/config.yaml")
        raise typer.Exit(1)

    console.print("[bold]Daemon:[/bold]")
    console.print(f"  host: {cfg.daemon.host}")
    console.print(f"  port: {cfg.daemon.port}")
    console.print(f"  log_level: {cfg.daemon.log_level}")

    console.print("\n[bold]Auto-Confirm:[/bold]")
    console.print(f"  enabled: {cfg.auto_confirm.enabled}")
    console.print(f"  max_cost: ${cfg.auto_confirm.max_cost_cents / 100:.2f}")
    console.print(f"  max_rows: {cfg.auto_confirm.max_rows}")

    if cfg.watch_folders:
        console.print(f"\n[bold]Watch Folders ({len(cfg.watch_folders)}):[/bold]")
        for wf in cfg.watch_folders:
            console.print(f"  {wf.path} → \"{wf.command}\"")

    if cfg.ups:
        console.print("\n[bold]UPS:[/bold]")
        acct = cfg.ups.account_number
        console.print(f"  account: {'***' + acct[-4:] if len(acct) > 4 else '***'}")


@config_app.command("validate")
def config_validate(
    config: Optional[str] = typer.Option(None, "--config", help="Config file path"),
):
    """Validate a config file without starting the daemon."""
    path = config or _config_path
    try:
        cfg = load_config(config_path=path)
        if cfg is None:
            console.print("[red]No config file found.[/red]")
            raise typer.Exit(1)
        console.print("[green]Config is valid.[/green]")
        console.print(f"  Watch folders: {len(cfg.watch_folders)}")
        console.print(f"  Auto-confirm: {'enabled' if cfg.auto_confirm.enabled else 'disabled'}")
    except Exception as e:
        console.print(f"[red]Config validation failed:[/red] {e}")
        raise typer.Exit(1)


# --- Job commands ---


@job_app.command("list")
def job_list(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List all shipping jobs."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        async with client:
            jobs = await client.list_jobs(status=status)
            output = format_job_table(jobs, as_json=json_output)
            console.print(output)

    asyncio.run(_run())


@job_app.command("inspect")
def job_inspect(
    job_id: str = typer.Argument(help="Job ID to inspect"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show detailed information about a specific job."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        async with client:
            detail = await client.get_job(job_id)
            output = format_job_detail(detail, as_json=json_output)
            console.print(output)

    asyncio.run(_run())


@job_app.command("rows")
def job_rows(
    job_id: str = typer.Argument(help="Job ID"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show rows for a specific job."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        async with client:
            rows = await client.get_job_rows(job_id)
            output = format_rows_table(rows, as_json=json_output)
            console.print(output)

    asyncio.run(_run())


@job_app.command("approve")
def job_approve(
    job_id: str = typer.Argument(help="Job ID to approve"),
):
    """Manually approve a job blocked by auto-confirm rules."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        async with client:
            await client.approve_job(job_id)
            console.print(f"[green]Job {job_id} approved and queued for execution.[/green]")

    asyncio.run(_run())


@job_app.command("cancel")
def job_cancel(
    job_id: str = typer.Argument(help="Job ID to cancel"),
):
    """Cancel a pending or running job."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        try:
            async with client:
                await client.cancel_job(job_id)
                console.print(f"[yellow]Job {job_id} cancelled.[/yellow]")
        except ShipAgentClientError as e:
            console.print(f"[red]Error:[/red] {e.message}")
            raise typer.Exit(1)

    asyncio.run(_run())


@job_app.command("logs")
def job_logs(
    job_id: str = typer.Argument(help="Job ID to stream logs for"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow/stream progress in real-time"),
):
    """Stream progress events for a job.

    Use -f to follow in real-time (reconnects on daemon restart with backoff).
    Without -f, prints current progress snapshot and exits.
    """
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        try:
            async with client:
                if follow:
                    # Stream with reconnect on daemon restart
                    retry_delay = 1.0
                    max_retry_delay = 30.0
                    while True:
                        try:
                            async for event in client.stream_progress(job_id):
                                retry_delay = 1.0  # Reset on success
                                status_color = "green" if event.event_type == "row_completed" else "red"
                                row_info = f"Row {event.row_number}/{event.total_rows}" if event.row_number else ""
                                tracking = f" → {event.tracking_number}" if event.tracking_number else ""
                                console.print(
                                    f"[{status_color}]{event.event_type}[/{status_color}] "
                                    f"{row_info}{tracking} {event.message}"
                                )
                            break  # Stream ended normally (job completed)
                        except ShipAgentClientError:
                            console.print(f"[yellow]Connection lost. Retrying in {retry_delay:.0f}s...[/yellow]")
                            import asyncio as _asyncio
                            await _asyncio.sleep(retry_delay)
                            retry_delay = min(retry_delay * 2, max_retry_delay)
                else:
                    # Snapshot: just show current job status
                    detail = await client.get_job(job_id)
                    output = format_job_detail(detail, as_json=False)
                    console.print(output)
        except ShipAgentClientError as e:
            console.print(f"[red]Error:[/red] {e.message}")
            raise typer.Exit(1)

    asyncio.run(_run())


# --- Submit command ---


@app.command()
def submit(
    file: Path = typer.Argument(help="Path to CSV or Excel file"),
    command: Optional[str] = typer.Option(
        None, "--command", "-c", help='Agent command (default: "Ship all orders")'
    ),
    service: Optional[str] = typer.Option(
        None, "--service", "-s", help="Service shorthand (e.g., 'UPS Ground')"
    ),
    auto_confirm: bool = typer.Option(
        False, "--auto-confirm", help="Apply auto-confirm rules"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Submit a file for shipping processing."""
    if not file.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    # Build command from --service shorthand if provided
    if command is None and service:
        command = f"Ship all orders using {service}"
    elif command is None:
        command = "Ship all orders"

    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        async with client:
            result = await client.submit_file(
                file_path=str(file.resolve()),
                command=command,
                auto_confirm=auto_confirm,
            )
            if json_output:
                import dataclasses, json
                console.print(json.dumps(dataclasses.asdict(result), indent=2))
            else:
                console.print(f"[green]Job submitted:[/green] {result.job_id}")
                console.print(f"  Status: {result.status}")
                console.print(f"  Rows: {result.row_count}")
                console.print(f"  {result.message}")

    asyncio.run(_run())


# --- Daemon commands ---


@daemon_app.command("start")
def daemon_start_cmd(
    host: Optional[str] = typer.Option(None, "--host", help="Bind address"),
    port: Optional[int] = typer.Option(None, "--port", help="Bind port"),
):
    """Start the ShipAgent daemon (FastAPI + Watchdog)."""
    import os

    from src.cli.daemon import start_daemon

    cfg = load_config(config_path=_config_path)
    final_host = host or (cfg.daemon.host if cfg else "127.0.0.1")
    final_port = port or (cfg.daemon.port if cfg else 8000)
    pid_file = cfg.daemon.pid_file if cfg else "~/.shipagent/daemon.pid"
    log_level = cfg.daemon.log_level if cfg else "info"

    # Propagate config path to API startup via env var so that
    # startup_event() loads the same config as the CLI.
    if _config_path:
        os.environ["SHIPAGENT_CONFIG_PATH"] = str(_config_path)

    console.print(f"[bold]Starting ShipAgent daemon on {final_host}:{final_port}[/bold]")
    start_daemon(host=final_host, port=final_port, pid_file=pid_file, log_level=log_level)


@daemon_app.command("stop")
def daemon_stop_cmd():
    """Stop the ShipAgent daemon."""
    from src.cli.daemon import stop_daemon

    cfg = load_config(config_path=_config_path)
    pid_file = cfg.daemon.pid_file if cfg else "~/.shipagent/daemon.pid"

    if stop_daemon(pid_file=pid_file):
        console.print("[green]Daemon stopped.[/green]")
    else:
        console.print("[yellow]Daemon is not running.[/yellow]")


@daemon_app.command("status")
def daemon_status_cmd():
    """Check daemon status."""
    from src.cli.daemon import daemon_status as check_status

    cfg = load_config(config_path=_config_path)
    pid_file = cfg.daemon.pid_file if cfg else "~/.shipagent/daemon.pid"
    base_url = f"http://{cfg.daemon.host}:{cfg.daemon.port}" if cfg else "http://127.0.0.1:8000"

    status = check_status(pid_file=pid_file, base_url=base_url)
    if status["alive"] and status["healthy"]:
        console.print(f"[green]Daemon running[/green] (PID {status['pid']}) — healthy")
    elif status["alive"]:
        console.print(f"[yellow]Daemon running[/yellow] (PID {status['pid']}) — unhealthy")
    else:
        console.print("[red]Daemon not running[/red]")


# --- Interact command ---


@app.command()
def interact(
    session: Optional[str] = typer.Option(
        None, "--session", help="Resume existing session ID"
    ),
):
    """Start a conversational shipping REPL."""
    from src.cli.repl import run_repl

    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)
    asyncio.run(run_repl(client, session_id=session))
