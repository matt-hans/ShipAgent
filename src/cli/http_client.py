"""HTTP client implementation of ShipAgentClient.

Thin wrapper around httpx that talks to the ShipAgent daemon API.
All methods map to existing REST endpoints.
"""

from typing import AsyncIterator

from src.cli.protocol import (
    AgentEvent,
    HealthStatus,
    JobDetail,
    JobSummary,
    ProgressEvent,
    RowDetail,
    SubmitResult,
)


class HttpClient:
    """ShipAgentClient implementation that talks to the daemon over HTTP."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        """Initialize with daemon base URL.

        Args:
            base_url: The daemon's HTTP base URL.
        """
        self._base_url = base_url
        self._client = None

    async def __aenter__(self):
        """Open httpx async client."""
        import httpx
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close httpx async client."""
        if self._client:
            await self._client.aclose()

    async def create_session(self, interactive: bool = False) -> str:
        """Create conversation session via POST /api/v1/conversations/."""
        raise NotImplementedError("HttpClient.create_session — implemented in Task 8")

    async def delete_session(self, session_id: str) -> None:
        """Delete conversation session via DELETE /api/v1/conversations/{id}."""
        raise NotImplementedError("HttpClient.delete_session — implemented in Task 8")

    async def submit_file(self, file_path: str, command: str | None,
                          auto_confirm: bool) -> SubmitResult:
        """Submit file via POST /api/v1/data-sources/import + agent message."""
        raise NotImplementedError("HttpClient.submit_file — implemented in Task 8")

    async def list_jobs(self, status: str | None = None) -> list[JobSummary]:
        """List jobs via GET /api/v1/jobs."""
        raise NotImplementedError("HttpClient.list_jobs — implemented in Task 8")

    async def get_job(self, job_id: str) -> JobDetail:
        """Get job detail via GET /api/v1/jobs/{id}."""
        raise NotImplementedError("HttpClient.get_job — implemented in Task 8")

    async def get_job_rows(self, job_id: str) -> list[RowDetail]:
        """Get job rows via GET /api/v1/jobs/{id}/rows."""
        raise NotImplementedError("HttpClient.get_job_rows — implemented in Task 8")

    async def cancel_job(self, job_id: str) -> None:
        """Cancel job via PATCH /api/v1/jobs/{id}/status."""
        raise NotImplementedError("HttpClient.cancel_job — implemented in Task 8")

    async def approve_job(self, job_id: str) -> None:
        """Approve job via POST /api/v1/jobs/{id}/confirm."""
        raise NotImplementedError("HttpClient.approve_job — implemented in Task 8")

    async def stream_progress(self, job_id: str) -> AsyncIterator[ProgressEvent]:
        """Stream progress via GET /api/v1/jobs/{id}/progress/stream."""
        raise NotImplementedError("HttpClient.stream_progress — implemented in Task 8")
        yield  # pragma: no cover

    async def send_message(self, session_id: str,
                           content: str) -> AsyncIterator[AgentEvent]:
        """Send message via POST /api/v1/conversations/{id}/messages."""
        raise NotImplementedError("HttpClient.send_message — implemented in Task 8")
        yield  # pragma: no cover

    async def health(self) -> HealthStatus:
        """Check health via GET /health."""
        raise NotImplementedError("HttpClient.health — implemented in Task 8")

    async def cleanup(self) -> None:
        """No-op for HTTP client (stateless)."""
        pass
