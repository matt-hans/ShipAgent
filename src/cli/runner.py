"""In-process runner implementation of ShipAgentClient.

Runs the full agent stack directly without requiring a daemon.
Used for development, testing, and standalone deployments.
"""

from typing import AsyncIterator

from src.cli.config import ShipAgentConfig
from src.cli.protocol import (
    AgentEvent,
    HealthStatus,
    JobDetail,
    JobSummary,
    ProgressEvent,
    RowDetail,
    SubmitResult,
)


class InProcessRunner:
    """ShipAgentClient implementation that runs the agent stack in-process."""

    def __init__(self, config: ShipAgentConfig | None = None):
        """Initialize with optional config.

        Args:
            config: Loaded ShipAgent config. Uses defaults if None.
        """
        self._config = config
        self._initialized = False

    async def __aenter__(self):
        """Initialize DB, MCP gateways, and agent session manager."""
        from src.db.connection import init_db
        init_db()
        self._initialized = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Shut down MCP gateways."""
        if self._initialized:
            from src.services.gateway_provider import shutdown_gateways
            await shutdown_gateways()

    async def create_session(self, interactive: bool = False) -> str:
        """Create agent session in-process."""
        raise NotImplementedError("InProcessRunner.create_session — implemented in Task 11")

    async def delete_session(self, session_id: str) -> None:
        """Delete agent session in-process."""
        raise NotImplementedError("InProcessRunner.delete_session — implemented in Task 11")

    async def submit_file(self, file_path: str, command: str | None,
                          auto_confirm: bool) -> SubmitResult:
        """Import file and run agent command in-process."""
        raise NotImplementedError("InProcessRunner.submit_file — implemented in Task 11")

    async def list_jobs(self, status: str | None = None) -> list[JobSummary]:
        """List jobs directly from database."""
        raise NotImplementedError("InProcessRunner.list_jobs — implemented in Task 11")

    async def get_job(self, job_id: str) -> JobDetail:
        """Get job detail directly from database."""
        raise NotImplementedError("InProcessRunner.get_job — implemented in Task 11")

    async def get_job_rows(self, job_id: str) -> list[RowDetail]:
        """Get job rows directly from database."""
        raise NotImplementedError("InProcessRunner.get_job_rows — implemented in Task 11")

    async def cancel_job(self, job_id: str) -> None:
        """Cancel job directly via JobService."""
        raise NotImplementedError("InProcessRunner.cancel_job — implemented in Task 11")

    async def approve_job(self, job_id: str) -> None:
        """Approve job directly via batch execution."""
        raise NotImplementedError("InProcessRunner.approve_job — implemented in Task 11")

    async def stream_progress(self, job_id: str) -> AsyncIterator[ProgressEvent]:
        """Stream progress in-process."""
        raise NotImplementedError("InProcessRunner.stream_progress — implemented in Task 11")
        yield  # pragma: no cover

    async def send_message(self, session_id: str,
                           content: str) -> AsyncIterator[AgentEvent]:
        """Send message to agent in-process."""
        raise NotImplementedError("InProcessRunner.send_message — implemented in Task 11")
        yield  # pragma: no cover

    async def health(self) -> HealthStatus:
        """Report in-process health (always healthy if running)."""
        return HealthStatus(
            healthy=True,
            version="3.0.0",
            uptime_seconds=0,
            active_jobs=0,
            watchdog_active=False,
        )

    async def cleanup(self) -> None:
        """Shut down gateways."""
        from src.services.gateway_provider import shutdown_gateways
        await shutdown_gateways()
