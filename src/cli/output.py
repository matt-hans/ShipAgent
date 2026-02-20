"""CLI output formatters for Rich tables and JSON.

Provides human-readable Rich table output (default) and machine-parseable
JSON output (--json flag). All formatting goes through these functions
so the CLI commands stay clean.
"""

import dataclasses
import json

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.cli.protocol import (
    DataSourceStatus,
    JobDetail,
    JobSummary,
    RowDetail,
    SavedSourceSummary,
    SourceSchemaColumn,
)

console = Console()

# Status color map (matches web UI domain colors)
STATUS_COLORS = {
    "pending": "yellow",
    "running": "blue",
    "completed": "green",
    "failed": "red",
    "cancelled": "dim",
    "paused": "yellow",
}


def format_cost(cents: int | None) -> str:
    """Format cost in cents as a dollar string.

    Args:
        cents: Cost in cents, or None.

    Returns:
        Formatted string like "$12.50" or "—" for None.
    """
    if cents is None:
        return "—"
    return f"${cents / 100:,.2f}"


def format_job_table(jobs: list[JobSummary], as_json: bool = False) -> str:
    """Format a list of jobs as a Rich table or JSON.

    Args:
        jobs: List of job summaries to display.
        as_json: If True, return JSON string instead of Rich table.

    Returns:
        Formatted string output.
    """
    if as_json:
        return json.dumps(
            [dataclasses.asdict(j) for j in jobs], indent=2
        )

    if not jobs:
        return "No jobs found."

    table = Table(title="Jobs", show_lines=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="white")
    table.add_column("Status")
    table.add_column("Rows", justify="right")
    table.add_column("OK", justify="right", style="green")
    table.add_column("Fail", justify="right", style="red")
    table.add_column("Created")

    for job in jobs:
        status_color = STATUS_COLORS.get(job.status, "white")
        table.add_row(
            job.id[:12],
            job.name or "—",
            f"[{status_color}]{job.status}[/{status_color}]",
            str(job.total_rows),
            str(job.successful_rows),
            str(job.failed_rows),
            job.created_at[:19] if job.created_at else "—",
        )

    # Render to string
    with console.capture() as capture:
        console.print(table)
    return capture.get()


def format_job_detail(detail: JobDetail, as_json: bool = False) -> str:
    """Format a single job's full detail as a Rich panel or JSON.

    Args:
        detail: Full job detail to display.
        as_json: If True, return JSON string instead of Rich panel.

    Returns:
        Formatted string output.
    """
    if as_json:
        return json.dumps(dataclasses.asdict(detail), indent=2)

    status_color = STATUS_COLORS.get(detail.status, "white")

    lines = [
        f"[bold]Job ID:[/bold]    {detail.id}",
        f"[bold]Name:[/bold]      {detail.name}",
        f"[bold]Status:[/bold]    [{status_color}]{detail.status}[/{status_color}]",
        f"[bold]Command:[/bold]   {detail.original_command}",
        "",
        f"[bold]Rows:[/bold]      {detail.processed_rows}/{detail.total_rows} processed",
        f"[bold]Success:[/bold]   [green]{detail.successful_rows}[/green]",
        f"[bold]Failed:[/bold]    [red]{detail.failed_rows}[/red]",
        f"[bold]Cost:[/bold]      {format_cost(detail.total_cost_cents)}",
        "",
        f"[bold]Created:[/bold]   {detail.created_at[:19] if detail.created_at else '—'}",
        f"[bold]Started:[/bold]   {detail.started_at[:19] if detail.started_at else '—'}",
        f"[bold]Completed:[/bold] {detail.completed_at[:19] if detail.completed_at else '—'}",
    ]

    if detail.error_code:
        lines.append("")
        lines.append(f"[bold red]Error:[/bold red] {detail.error_code}: {detail.error_message}")

    if detail.auto_confirm_violations:
        lines.append("")
        lines.append("[bold yellow]Auto-Confirm Violations:[/bold yellow]")
        for v in detail.auto_confirm_violations:
            lines.append(f"  - {v.get('message', v.get('rule', 'Unknown'))}")

    content = "\n".join(lines)

    with console.capture() as capture:
        console.print(Panel(content, title="Job Detail", border_style="cyan"))
    return capture.get()


def format_rows_table(rows: list[RowDetail], as_json: bool = False) -> str:
    """Format job rows as a Rich table or JSON.

    Args:
        rows: List of row details to display.
        as_json: If True, return JSON string instead of Rich table.

    Returns:
        Formatted string output.
    """
    if as_json:
        return json.dumps(
            [dataclasses.asdict(r) for r in rows], indent=2
        )

    if not rows:
        return "No rows found."

    table = Table(title="Job Rows", show_lines=True)
    table.add_column("#", justify="right")
    table.add_column("Status")
    table.add_column("Tracking", style="cyan")
    table.add_column("Cost", justify="right")
    table.add_column("Error")

    for row in rows:
        status_color = STATUS_COLORS.get(row.status, "white")
        table.add_row(
            str(row.row_number),
            f"[{status_color}]{row.status}[/{status_color}]",
            row.tracking_number or "—",
            format_cost(row.cost_cents),
            row.error_message[:40] if row.error_message else "—",
        )

    with console.capture() as capture:
        console.print(table)
    return capture.get()


def format_source_status(status: DataSourceStatus) -> str:
    """Format data source status as a Rich panel.

    Args:
        status: Current data source connection status.

    Returns:
        Formatted string output.
    """
    if not status.connected:
        panel = Panel(
            "[dim]No data source connected[/dim]",
            title="Data Source",
            border_style="dim",
        )
        with console.capture() as capture:
            console.print(panel)
        return capture.get()

    table = Table(show_header=False, box=None)
    table.add_row("Type:", status.source_type or "unknown")
    if status.file_path:
        table.add_row("Path:", status.file_path)
    if status.row_count is not None:
        table.add_row("Rows:", str(status.row_count))
    if status.column_count is not None:
        table.add_row("Columns:", str(status.column_count))
    panel = Panel(table, title="[bold]Data Source[/bold]", border_style="green")
    with console.capture() as capture:
        console.print(panel)
    return capture.get()


def format_saved_sources(sources: list[SavedSourceSummary]) -> str:
    """Format saved data sources as a Rich table.

    Args:
        sources: List of saved source summaries.

    Returns:
        Formatted string output.
    """
    if not sources:
        return "No saved sources found."

    table = Table(title="Saved Data Sources")
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Last Connected")
    for s in sources:
        table.add_row(
            s.id[:8], s.name, s.source_type, s.last_connected or "never"
        )
    with console.capture() as capture:
        console.print(table)
    return capture.get()


def format_schema(columns: list[SourceSchemaColumn]) -> str:
    """Format data source schema as a Rich table.

    Args:
        columns: List of column metadata.

    Returns:
        Formatted string output.
    """
    if not columns:
        return "No columns found."

    table = Table(title="Source Schema")
    table.add_column("Column", style="bold")
    table.add_column("Type")
    table.add_column("Nullable")
    for col in columns:
        table.add_row(col.name, col.type, "yes" if col.nullable else "no")
    with console.capture() as capture:
        console.print(table)
    return capture.get()
