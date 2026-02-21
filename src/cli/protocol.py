"""ShipAgentClient protocol and CLI data models.

Defines the abstract interface that both HttpClient and InProcessRunner
implement. The CLI commands call protocol methods without knowing which
backend is active.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SubmitResult:
    """Result of submitting a file for processing."""

    job_id: str
    status: str
    row_count: int
    message: str


@dataclass
class JobSummary:
    """Lightweight job data for list views.

    Aligned with src/api/schemas.py:JobSummaryResponse (lines 125-146).
    Extra fields from API response are accepted and ignored via from_api().
    """

    id: str
    name: str
    status: str
    original_command: str
    total_rows: int
    processed_rows: int
    successful_rows: int
    failed_rows: int
    total_cost_cents: int
    created_at: str
    is_interactive: bool = False

    @classmethod
    def from_api(cls, data: dict) -> "JobSummary":
        """Construct from API JSON, tolerating extra fields."""
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            status=data["status"],
            original_command=data.get("original_command", ""),
            total_rows=data.get("total_rows", 0),
            processed_rows=data.get("processed_rows", 0),
            successful_rows=data.get("successful_rows", 0),
            failed_rows=data.get("failed_rows", 0),
            total_cost_cents=data.get("total_cost_cents", 0),
            created_at=data.get("created_at", ""),
            is_interactive=data.get("is_interactive", False),
        )


@dataclass
class JobDetail:
    """Full job detail with all fields.

    Aligned with src/api/schemas.py:JobResponse (lines 93-124).
    Includes international and interactive fields.
    Extra fields from API response are accepted and ignored via from_api().
    """

    id: str
    name: str
    status: str
    original_command: str
    total_rows: int
    processed_rows: int
    successful_rows: int
    failed_rows: int
    total_cost_cents: int
    created_at: str
    started_at: str | None
    completed_at: str | None
    error_code: str | None
    error_message: str | None
    description: str | None = None
    mode: str = "confirm"
    is_interactive: bool = False
    total_duties_taxes_cents: int = 0
    international_row_count: int = 0
    auto_confirm_violations: list[dict] | None = None

    @classmethod
    def from_api(cls, data: dict) -> "JobDetail":
        """Construct from API JSON, tolerating extra fields."""
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            status=data["status"],
            original_command=data.get("original_command", ""),
            total_rows=data.get("total_rows", 0),
            processed_rows=data.get("processed_rows", 0),
            successful_rows=data.get("successful_rows", 0),
            failed_rows=data.get("failed_rows", 0),
            total_cost_cents=data.get("total_cost_cents", 0),
            created_at=data.get("created_at", ""),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
            description=data.get("description"),
            mode=data.get("mode", "confirm"),
            is_interactive=data.get("is_interactive", False),
            total_duties_taxes_cents=data.get("total_duties_taxes_cents", 0),
            international_row_count=data.get("international_row_count", 0),
        )


@dataclass
class RowDetail:
    """Per-row outcome data.

    Aligned with src/api/schemas.py:JobRowResponse (lines 55-92).
    """

    id: str
    row_number: int
    status: str
    tracking_number: str | None
    cost_cents: int | None
    error_code: str | None
    error_message: str | None
    destination_country: str | None = None
    duties_taxes_cents: int | None = None
    order_data: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> "RowDetail":
        """Construct from API JSON, tolerating extra fields."""
        return cls(
            id=data["id"],
            row_number=data.get("row_number", 0),
            status=data["status"],
            tracking_number=data.get("tracking_number"),
            cost_cents=data.get("cost_cents"),
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
            destination_country=data.get("destination_country"),
            duties_taxes_cents=data.get("duties_taxes_cents"),
            order_data=data.get("order_data"),
        )


@dataclass
class HealthStatus:
    """Daemon health report."""

    healthy: bool
    version: str
    uptime_seconds: int
    active_jobs: int
    watchdog_active: bool
    watch_folders: list[str] = field(default_factory=list)


@dataclass
class ProgressEvent:
    """Streaming progress event from batch execution."""

    job_id: str
    event_type: str
    row_number: int | None
    total_rows: int | None
    tracking_number: str | None = None
    message: str = ""


@dataclass
class AgentEvent:
    """Streaming event from agent conversation."""

    event_type: str
    content: str | None = None
    tool_name: str | None = None
    tool_input: str | None = None


@dataclass
class DataSourceStatus:
    """Current data source connection status."""

    connected: bool
    source_type: str | None = None
    file_path: str | None = None
    row_count: int | None = None
    column_count: int | None = None
    columns: list[str] = field(default_factory=list)


@dataclass
class SavedSourceSummary:
    """Saved data source profile summary."""

    id: str
    name: str
    source_type: str
    file_path: str | None = None
    last_connected: str | None = None
    row_count: int | None = None

    @classmethod
    def from_api(cls, data: dict) -> "SavedSourceSummary":
        """Construct from API JSON, tolerating extra fields."""
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            source_type=data.get("source_type", ""),
            file_path=data.get("file_path"),
            last_connected=data.get("last_connected"),
            row_count=data.get("row_count"),
        )


@dataclass
class SourceSchemaColumn:
    """Column metadata from current data source."""

    name: str
    type: str
    nullable: bool = True
    sample_values: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> "SourceSchemaColumn":
        """Construct from API JSON, tolerating extra fields."""
        if isinstance(data, str):
            return cls(name=data, type="VARCHAR")
        return cls(
            name=data["name"],
            type=data.get("type", "VARCHAR"),
            nullable=data.get("nullable", True),
            sample_values=data.get("sample_values", []),
        )


class ShipAgentClientError(Exception):
    """Transport-neutral error raised by ShipAgentClient implementations.

    HttpClient raises this on HTTP errors; InProcessRunner raises this
    on service-level failures. CLI commands catch this and convert to
    user-friendly Rich error messages + typer.Exit(1).
    """

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ShipAgentClient(Protocol):
    """Protocol defining the interface for CLI backends.

    Both HttpClient (daemon mode) and InProcessRunner (standalone mode)
    implement this protocol. CLI commands are written against this
    abstraction and never know which backend is active.
    """

    async def __aenter__(self) -> "ShipAgentClient":
        """Initialize resources (HTTP session or service stack)."""
        ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Release resources on exit."""
        ...

    async def create_session(self, interactive: bool = False) -> str:
        """Create a new agent conversation session.

        Args:
            interactive: If True, creates an interactive shipping session.

        Returns:
            Session ID string.
        """
        ...

    async def delete_session(self, session_id: str) -> None:
        """Delete an agent conversation session.

        Args:
            session_id: The session to delete.
        """
        ...

    async def submit_file(
        self, file_path: str, command: str | None, auto_confirm: bool
    ) -> SubmitResult:
        """Import a file and submit it for agent processing.

        Args:
            file_path: Path to CSV or Excel file.
            command: Agent command (e.g. "Ship all orders via UPS Ground").
                     Defaults to "Ship all orders" if None.
            auto_confirm: Whether to apply auto-confirm rules.

        Returns:
            SubmitResult with job ID and status.
        """
        ...

    async def list_jobs(self, status: str | None = None) -> list[JobSummary]:
        """List jobs with optional status filter.

        Args:
            status: Filter by status (pending, running, completed, etc.)

        Returns:
            List of JobSummary objects.
        """
        ...

    async def get_job(self, job_id: str) -> JobDetail:
        """Get full detail for a specific job.

        Args:
            job_id: The job ID.

        Returns:
            JobDetail with all fields.
        """
        ...

    async def get_job_rows(self, job_id: str) -> list[RowDetail]:
        """Get all rows for a job.

        Args:
            job_id: The job ID.

        Returns:
            List of RowDetail objects.
        """
        ...

    async def cancel_job(self, job_id: str) -> None:
        """Cancel a pending or running job.

        Args:
            job_id: The job to cancel.
        """
        ...

    async def approve_job(self, job_id: str) -> None:
        """Manually approve a job blocked by auto-confirm rules.

        Args:
            job_id: The job to approve.
        """
        ...

    async def stream_progress(self, job_id: str) -> AsyncIterator[ProgressEvent]:
        """Stream real-time progress events for a job.

        Args:
            job_id: The job to stream progress for.

        Yields:
            ProgressEvent objects as execution proceeds.
        """
        ...

    async def send_message(
        self, session_id: str, content: str
    ) -> AsyncIterator[AgentEvent]:
        """Send a message to an agent session and stream the response.

        Args:
            session_id: The conversation session ID.
            content: The user message content.

        Yields:
            AgentEvent objects (deltas, tool calls, previews, done).
        """
        ...

    async def health(self) -> HealthStatus:
        """Check daemon health status.

        Returns:
            HealthStatus with version, uptime, and component status.
        """
        ...

    async def cleanup(self) -> None:
        """Clean up resources (close connections, stop MCP clients)."""
        ...

    async def get_job_audit_events(
        self,
        job_id: str,
        limit: int = 200,
    ) -> list[dict]:
        """Get centralized agent audit events for a job."""
        ...

    async def get_source_status(self) -> DataSourceStatus:
        """Get current data source connection status."""
        ...

    async def connect_source(self, file_path: str) -> DataSourceStatus:
        """Import a local file as the active data source."""
        ...

    async def connect_db(self, connection_string: str, query: str) -> DataSourceStatus:
        """Import from a database using connection string and query.

        Both parameters are required — the backend rejects DB imports
        without a query.
        """
        ...

    async def disconnect_source(self) -> None:
        """Disconnect the current data source."""
        ...

    async def list_saved_sources(self) -> list[SavedSourceSummary]:
        """List saved data source profiles."""
        ...

    async def reconnect_saved_source(
        self, identifier: str, by_name: bool = True
    ) -> DataSourceStatus:
        """Reconnect a saved source by name or ID."""
        ...

    async def get_source_schema(self) -> list[SourceSchemaColumn]:
        """Get schema of current data source."""
        ...

    async def connect_platform(self, platform: str) -> DataSourceStatus:
        """Connect an env-configured external platform."""
        ...
