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
import logging
import sys
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console

from src.cli.config import load_config
from src.cli.factory import get_client
from src.cli.output import (
    format_job_detail,
    format_job_table,
    format_rows_table,
    format_saved_sources,
    format_schema,
    format_source_status,
)
from src.cli.protocol import ShipAgentClientError, SubmitResult

_log = logging.getLogger(__name__)

app = typer.Typer(
    name="shipagent",
    help="AI-native shipping automation — headless CLI",
    no_args_is_help=True,
)
daemon_app = typer.Typer(help="Manage the ShipAgent daemon")
job_app = typer.Typer(help="Manage shipping jobs")
config_app = typer.Typer(help="Configuration management")
data_source_app = typer.Typer(help="Manage data sources")
contacts_app = typer.Typer(help="Manage address book contacts")
commands_app = typer.Typer(help="Manage custom /commands")

app.add_typer(daemon_app, name="daemon")
app.add_typer(job_app, name="job")
app.add_typer(config_app, name="config")
app.add_typer(data_source_app, name="data-source")
app.add_typer(contacts_app, name="contacts")
app.add_typer(commands_app, name="commands")

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
    except FileNotFoundError as e:
        console.print(f"[red]Config file not found:[/red] {e}")
        raise typer.Exit(1)
    except (ValueError, TypeError) as e:
        console.print(f"[red]Config validation failed:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Config loading error ({type(e).__name__}):[/red] {e}")
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


@job_app.command("audit")
def job_audit(
    job_id: str = typer.Argument(help="Job ID to inspect decision audit events"),
    limit: int = typer.Option(200, "--limit", "-n", help="Maximum events to fetch"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show centralized agent decision audit events for a job."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        async with client:
            events = await client.get_job_audit_events(job_id=job_id, limit=limit)
            if json_output:
                import json

                console.print(json.dumps(events, indent=2, default=str))
                return
            if not events:
                console.print("[yellow]No audit events found for this job.[/yellow]")
                return
            for event in events:
                console.print(
                    f"{event.get('timestamp', '')} "
                    f"[{event.get('phase', '')}] "
                    f"{event.get('event_name', '')} "
                    f"(seq={event.get('seq', '')})"
                )

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

            # Apply auto-confirm rules after we have the real job_id.
            # Config is available here; backends do not need to carry it.
            if auto_confirm and result.job_id:
                from src.cli.auto_confirm import evaluate_auto_confirm
                from src.cli.config import AutoConfirmRules

                ac_rules = cfg.auto_confirm if cfg else AutoConfirmRules()
                try:
                    import json as _json

                    rows = await client.get_job_rows(result.job_id)

                    # Use per-row cost estimates (populated at preview time).
                    # job.total_cost_cents is only written during execution,
                    # so it is 0 before confirmation.
                    row_costs = [r.cost_cents or 0 for r in rows]
                    total_cost_from_rows = sum(row_costs)
                    max_row_cost = max(row_costs, default=0)

                    # Extract real service codes from row order_data.
                    service_codes: list[str] = []
                    _parse_failures = 0
                    for r in rows:
                        if r.order_data:
                            try:
                                sc = _json.loads(r.order_data).get("service_code")
                                if sc:
                                    service_codes.append(sc)
                            except (_json.JSONDecodeError, AttributeError):
                                _parse_failures += 1
                    if _parse_failures > 0:
                        _log.warning(
                            "Auto-confirm: %d/%d rows had unparseable order_data; "
                            "service_code checks may be incomplete",
                            _parse_failures, len(rows),
                        )

                    # Address validation state is not re-persisted on rows
                    # after preview (the agent validates at preview time only).
                    # Use conservative defaults so require_valid_addresses=true
                    # (the default) blocks auto-confirm unless the operator
                    # explicitly sets require_valid_addresses=false in config.
                    preview_data = {
                        "total_rows": len(rows),
                        "total_cost_cents": total_cost_from_rows,
                        "max_row_cost_cents": max_row_cost,
                        "service_codes": service_codes,
                        "service_parse_failures": _parse_failures,
                        "all_addresses_valid": False,
                        "has_address_warnings": True,
                    }
                    ac_result = evaluate_auto_confirm(ac_rules, preview_data)
                    if ac_result.approved:
                        await client.approve_job(result.job_id)
                        result = SubmitResult(
                            job_id=result.job_id,
                            status="running",
                            row_count=result.row_count,
                            message="Auto-confirmed and executing",
                        )
                    else:
                        violation_msgs = "; ".join(
                            v.message for v in ac_result.violations
                        )
                        result = SubmitResult(
                            job_id=result.job_id,
                            status=result.status,
                            row_count=result.row_count,
                            message=f"Auto-confirm blocked: {violation_msgs}",
                        )
                except ShipAgentClientError as e:
                    console.print(
                        f"[yellow]Auto-confirm skipped:[/yellow] {e.message}"
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


# --- Data source commands ---


@data_source_app.command("status")
def data_source_status():
    """Show current data source connection status."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        try:
            async with client:
                status = await client.get_source_status()
                console.print(format_source_status(status))
        except ShipAgentClientError as e:
            console.print(f"[red]Error:[/red] {e.message}")
            raise typer.Exit(1)

    asyncio.run(_run())


@data_source_app.command("connect")
def data_source_connect(
    file: Optional[str] = typer.Argument(None, help="Path to CSV or Excel file"),
    db: Optional[str] = typer.Option(None, "--db", help="Database connection string"),
    query: Optional[str] = typer.Option(None, "--query", help="SQL query (required with --db)"),
    platform: Optional[str] = typer.Option(None, "--platform", help="Platform name (shopify)"),
):
    """Connect a data source (file, database, or platform)."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        try:
            async with client:
                if platform:
                    if platform.lower() != "shopify":
                        console.print(
                            f"[red]Only 'shopify' supports env-based auto-connect. "
                            f"Use the agent conversation for {platform}.[/red]"
                        )
                        raise typer.Exit(1)
                    status = await client.connect_platform(platform)
                elif db:
                    if not query:
                        console.print(
                            "[red]--query is required with --db. "
                            "Example: --db 'postgresql://...' --query 'SELECT * FROM orders'[/red]"
                        )
                        raise typer.Exit(1)
                    status = await client.connect_db(db, query)
                elif file:
                    status = await client.connect_source(file)
                else:
                    console.print(
                        "[red]Specify a file path, --db + --query, or --platform shopify[/red]"
                    )
                    raise typer.Exit(1)
                console.print(format_source_status(status))
        except ShipAgentClientError as e:
            console.print(f"[red]Error:[/red] {e.message}")
            raise typer.Exit(1)

    asyncio.run(_run())


@data_source_app.command("disconnect")
def data_source_disconnect():
    """Disconnect the current data source."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        try:
            async with client:
                await client.disconnect_source()
                console.print("[green]Data source disconnected.[/green]")
        except ShipAgentClientError as e:
            console.print(f"[red]Error:[/red] {e.message}")
            raise typer.Exit(1)

    asyncio.run(_run())


@data_source_app.command("list-saved")
def data_source_list_saved():
    """List saved data source profiles."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        try:
            async with client:
                sources = await client.list_saved_sources()
                console.print(format_saved_sources(sources))
        except ShipAgentClientError as e:
            console.print(f"[red]Error:[/red] {e.message}")
            raise typer.Exit(1)

    asyncio.run(_run())


@data_source_app.command("reconnect")
def data_source_reconnect(
    identifier: str = typer.Argument(help="Saved source name or ID"),
    by_id: bool = typer.Option(False, "--id", help="Treat identifier as UUID"),
):
    """Reconnect a previously saved data source."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        try:
            async with client:
                status = await client.reconnect_saved_source(
                    identifier, by_name=not by_id
                )
                console.print(format_source_status(status))
        except ShipAgentClientError as e:
            console.print(f"[red]Error:[/red] {e.message}")
            raise typer.Exit(1)

    asyncio.run(_run())


@data_source_app.command("schema")
def data_source_schema():
    """Show schema of the currently connected data source."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        try:
            async with client:
                columns = await client.get_source_schema()
                console.print(format_schema(columns))
        except ShipAgentClientError as e:
            console.print(f"[red]Error:[/red] {e.message}")
            raise typer.Exit(1)

    asyncio.run(_run())


# --- Interact command ---


@app.command()
def interact(
    session: Optional[str] = typer.Option(
        None, "--session", help="Resume existing session ID"
    ),
    file: Optional[str] = typer.Option(
        None, "--file", help="Load file as data source before REPL"
    ),
    source: Optional[str] = typer.Option(
        None, "--source", help="Reconnect saved source before REPL"
    ),
    platform: Optional[str] = typer.Option(
        None, "--platform", help="Connect platform before REPL (shopify)"
    ),
):
    """Start a conversational shipping REPL.

    Optional pre-loading: --file, --source, or --platform connect a data
    source before entering the REPL so it's immediately available to the agent.
    """
    from src.cli.repl import run_repl

    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        async with client:
            try:
                if file:
                    await client.connect_source(file)
                    console.print(f"[green]Loaded: {file}[/green]")
                elif source:
                    await client.reconnect_saved_source(source)
                    console.print(f"[green]Reconnected: {source}[/green]")
                elif platform:
                    await client.connect_platform(platform)
                    console.print(f"[green]Connected: {platform}[/green]")
            except ShipAgentClientError as e:
                console.print(f"[red]Failed to pre-load data source:[/red] {e.message}")
                raise typer.Exit(1)
            # Enter REPL — pass already-open client
            await _run_repl_in_context(client, session_id=session)

    asyncio.run(_run())


async def _run_repl_in_context(
    client, session_id: str | None = None
) -> None:
    """Run the REPL loop using an already-open client context.

    This is used when pre-loading a data source before entering the REPL,
    since the client is already opened by the interact command.
    """
    from rich.panel import Panel as _Panel

    from src.cli.protocol import AgentEvent

    if session_id is None:
        session_id = await client.create_session(interactive=False)
        console.print(f"[dim]Session: {session_id}[/dim]")

    console.print()
    console.print("[bold]ShipAgent[/bold] v3.0 — Interactive Mode")
    console.print("Type your shipping commands. Ctrl+D to exit.")
    console.print()

    try:
        while True:
            try:
                user_input = console.input("[bold green]> [/bold green]")
            except EOFError:
                break
            if not user_input.strip():
                continue
            message_buffer = []
            try:
                async for event in client.send_message(session_id, user_input):
                    if event.event_type == "agent_message_delta" and event.content:
                        message_buffer.append(event.content)
                    elif event.event_type == "done":
                        break
            except ShipAgentClientError as e:
                console.print(f"[red]Error:[/red] {e.message}")
                continue
            if message_buffer:
                console.print("".join(message_buffer))
            console.print()
    finally:
        try:
            await client.delete_session(session_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to clean up session %s: %s", session_id, e
            )


# --- Contacts CLI ---


@contacts_app.command("list")
def contacts_list():
    """List all saved contacts."""
    from src.db.connection import get_db_context
    from src.services.contact_service import ContactService

    with get_db_context() as db:
        svc = ContactService(db)
        contacts = svc.list_contacts()
        if not contacts:
            console.print("[dim]No contacts saved.[/dim]")
            return
        from rich.table import Table
        table = Table(title="Address Book")
        table.add_column("Handle", style="cyan")
        table.add_column("Name")
        table.add_column("City")
        table.add_column("State")
        table.add_column("Country")
        for c in contacts:
            table.add_row(f"@{c.handle}", c.display_name, c.city, c.state_province, c.country_code)
        console.print(table)


@contacts_app.command("add")
def contacts_add(
    handle: Optional[str] = typer.Option(None, "--handle", "-h", help="@mention handle"),
    name: str = typer.Option(..., "--name", "-n", help="Display name"),
    address: str = typer.Option(..., "--address", "-a", help="Street address"),
    city: str = typer.Option(..., "--city", "-c", help="City"),
    state: str = typer.Option(..., "--state", "-s", help="State/province"),
    zip_code: str = typer.Option(..., "--zip", "-z", help="Postal/ZIP code"),
    country: str = typer.Option("US", "--country", help="Country code"),
    phone: Optional[str] = typer.Option(None, "--phone", "-p", help="Phone number"),
    company: Optional[str] = typer.Option(None, "--company", help="Company name"),
):
    """Add a new contact to the address book."""
    from src.db.connection import get_db_context
    from src.services.contact_service import ContactService

    with get_db_context() as db:
        svc = ContactService(db)
        try:
            contact = svc.create_contact(
                handle=handle, display_name=name, address_line_1=address,
                city=city, state_province=state, postal_code=zip_code,
                country_code=country, phone=phone, company=company,
            )
            db.commit()
            console.print(f"[green]Created contact @{contact.handle}[/green]")
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(code=1)


@contacts_app.command("show")
def contacts_show(handle: str = typer.Argument(..., help="Contact handle (with or without @)")):
    """Show details for a contact."""
    from src.db.connection import get_db_context
    from src.services.contact_service import ContactService

    with get_db_context() as db:
        svc = ContactService(db)
        contact = svc.get_by_handle(handle)
        if not contact:
            console.print(f"[red]Contact @{handle.lstrip('@')} not found[/red]")
            raise typer.Exit(code=1)
        from rich.panel import Panel
        lines = [
            f"Handle:   @{contact.handle}",
            f"Name:     {contact.display_name}",
            f"Company:  {contact.company or '—'}",
            f"Address:  {contact.address_line_1}",
            f"          {contact.address_line_2 or ''}".rstrip(),
            f"City:     {contact.city}, {contact.state_province} {contact.postal_code}",
            f"Country:  {contact.country_code}",
            f"Phone:    {contact.phone or '—'}",
            f"Email:    {contact.email or '—'}",
            f"Use as:   {'ShipTo' if contact.use_as_ship_to else ''} {'Shipper' if contact.use_as_shipper else ''} {'ThirdParty' if contact.use_as_third_party else ''}".strip(),
            f"Tags:     {', '.join(contact.tag_list) if contact.tag_list else '—'}",
        ]
        console.print(Panel("\n".join(lines), title=f"@{contact.handle}"))


@contacts_app.command("delete")
def contacts_delete(
    handle: str = typer.Argument(..., help="Contact handle"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a contact from the address book."""
    from rich.prompt import Confirm

    from src.db.connection import get_db_context
    from src.services.contact_service import ContactService

    clean = handle.lstrip("@")
    if not yes:
        if not Confirm.ask(f"Delete contact @{clean}?"):
            console.print("[dim]Cancelled[/dim]")
            return

    with get_db_context() as db:
        svc = ContactService(db)
        contact = svc.get_by_handle(clean)
        if not contact:
            console.print(f"[red]Contact @{clean} not found[/red]")
            raise typer.Exit(code=1)
        svc.delete_contact(contact.id)
        db.commit()
        console.print(f"[green]Deleted contact @{clean}[/green]")


@contacts_app.command("export")
def contacts_export(
    output: str = typer.Option("contacts.json", "--output", "-o", help="Output file path"),
):
    """Export all contacts to JSON."""
    import json as _json

    from src.db.connection import get_db_context
    from src.services.contact_service import ContactService

    with get_db_context() as db:
        svc = ContactService(db)
        contacts = svc.list_contacts()
        data = []
        for c in contacts:
            data.append({
                "handle": c.handle,
                "display_name": c.display_name,
                "attention_name": c.attention_name,
                "company": c.company,
                "phone": c.phone,
                "email": c.email,
                "address_line_1": c.address_line_1,
                "address_line_2": c.address_line_2,
                "city": c.city,
                "state_province": c.state_province,
                "postal_code": c.postal_code,
                "country_code": c.country_code,
                "use_as_ship_to": c.use_as_ship_to,
                "use_as_shipper": c.use_as_shipper,
                "use_as_third_party": c.use_as_third_party,
                "tags": c.tag_list,
                "notes": c.notes,
            })
        Path(output).write_text(_json.dumps(data, indent=2))
        console.print(f"[green]Exported {len(data)} contacts to {output}[/green]")


@contacts_app.command("import")
def contacts_import(file_path: str = typer.Argument(..., help="JSON file to import")):
    """Import contacts from JSON."""
    import json as _json

    from src.db.connection import get_db_context
    from src.services.contact_service import ContactService

    data = _json.loads(Path(file_path).read_text())
    if not isinstance(data, list):
        console.print("[red]Expected a JSON array of contact objects[/red]")
        raise typer.Exit(code=1)

    with get_db_context() as db:
        svc = ContactService(db)
        created = 0
        updated = 0
        for item in data:
            try:
                # Idempotent import: upsert on handle (DB perf optimization).
                # If handle exists, update fields instead of failing.
                handle = item.get("handle", "").lstrip("@").lower().strip()
                existing = svc.get_by_handle(handle) if handle else None
                if existing:
                    update_fields = {k: v for k, v in item.items() if k != "handle" and v is not None}
                    svc.update_contact(existing.id, **update_fields)
                    updated += 1
                else:
                    svc.create_contact(**item)
                    created += 1
            except ValueError as e:
                console.print(f"[yellow]Skipped: {e}[/yellow]")
        db.commit()
        console.print(f"[green]Imported {created} new, {updated} updated / {len(data)} total[/green]")


# --- Commands CLI ---


@commands_app.command("list")
def commands_list():
    """List all custom commands."""
    from src.db.connection import get_db_context
    from src.services.custom_command_service import CustomCommandService

    with get_db_context() as db:
        svc = CustomCommandService(db)
        commands = svc.list_commands()
        if not commands:
            console.print("[dim]No custom commands defined.[/dim]")
            return
        from rich.table import Table
        table = Table(title="Custom Commands")
        table.add_column("Command", style="cyan")
        table.add_column("Description")
        table.add_column("Body", max_width=60)
        for c in commands:
            table.add_row(f"/{c.name}", c.description or "—", c.body[:60])
        console.print(table)


@commands_app.command("add")
def commands_add(
    name: str = typer.Option(..., "--name", "-n", help="Command name without /"),
    body: str = typer.Option(..., "--body", "-b", help="Instruction text"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Description"),
):
    """Add a new custom command."""
    from src.db.connection import get_db_context
    from src.services.custom_command_service import CustomCommandService

    with get_db_context() as db:
        svc = CustomCommandService(db)
        try:
            cmd = svc.create_command(name=name, body=body, description=description)
            db.commit()
            console.print(f"[green]Created command /{cmd.name}[/green]")
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(code=1)


@commands_app.command("show")
def commands_show(name: str = typer.Argument(..., help="Command name (with or without /)")):
    """Show a command's body."""
    from src.db.connection import get_db_context
    from src.services.custom_command_service import CustomCommandService

    with get_db_context() as db:
        svc = CustomCommandService(db)
        cmd = svc.get_by_name(name)
        if not cmd:
            console.print(f"[red]Command /{name.lstrip('/')} not found[/red]")
            raise typer.Exit(code=1)
        from rich.panel import Panel
        console.print(Panel(
            f"[bold]/{cmd.name}[/bold]\n{cmd.description or ''}\n\n{cmd.body}",
            title=f"/{cmd.name}",
        ))


@commands_app.command("delete")
def commands_delete(
    name: str = typer.Argument(..., help="Command name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a custom command."""
    from rich.prompt import Confirm

    from src.db.connection import get_db_context
    from src.services.custom_command_service import CustomCommandService

    clean = name.lstrip("/")
    if not yes:
        if not Confirm.ask(f"Delete command /{clean}?"):
            console.print("[dim]Cancelled[/dim]")
            return

    with get_db_context() as db:
        svc = CustomCommandService(db)
        cmd = svc.get_by_name(clean)
        if not cmd:
            console.print(f"[red]Command /{clean} not found[/red]")
            raise typer.Exit(code=1)
        svc.delete_command(cmd.id)
        db.commit()
        console.print(f"[green]Deleted command /{clean}[/green]")
