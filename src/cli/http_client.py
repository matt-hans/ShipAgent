"""HTTP client implementation of ShipAgentClient.

Thin wrapper around httpx that talks to the ShipAgent daemon API.
All methods map to existing REST endpoints. Error responses raise
ShipAgentClientError — never typer.Exit — so the client is reusable
for scripts, tests, and non-CLI consumers.
"""

import json
import logging
from typing import AsyncIterator

from src.cli.protocol import (
    AgentEvent,
    HealthStatus,
    JobDetail,
    JobSummary,
    ProgressEvent,
    RowDetail,
    ShipAgentClientError,
    SubmitResult,
)

logger = logging.getLogger(__name__)


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

    def _raise_for_status(self, resp) -> None:
        """Raise ShipAgentClientError on non-2xx responses.

        Args:
            resp: httpx.Response to check.

        Raises:
            ShipAgentClientError: On non-2xx status codes.
        """
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise ShipAgentClientError(
                message=str(detail),
                status_code=resp.status_code,
            )

    async def create_session(self, interactive: bool = False) -> str:
        """Create conversation session via POST /api/v1/conversations/.

        Args:
            interactive: If True, creates an interactive shipping session.

        Returns:
            Session ID string.
        """
        resp = await self._client.post(
            "/api/v1/conversations/",
            json={"interactive_shipping": interactive},
        )
        self._raise_for_status(resp)
        return resp.json()["session_id"]

    async def delete_session(self, session_id: str) -> None:
        """Delete conversation session via DELETE /api/v1/conversations/{id}.

        Args:
            session_id: The session to delete.
        """
        resp = await self._client.delete(f"/api/v1/conversations/{session_id}")
        # 404 is acceptable — session may already be gone
        if resp.status_code != 404:
            self._raise_for_status(resp)

    async def submit_file(self, file_path: str, command: str | None,
                          auto_confirm: bool) -> SubmitResult:
        """Submit file via POST /api/v1/data-sources/upload + agent message.

        Args:
            file_path: Path to CSV or Excel file.
            command: Agent command. Defaults to "Ship all orders" if None.
            auto_confirm: Whether to apply auto-confirm rules.

        Returns:
            SubmitResult with job ID and status.
        """
        import os

        # Step 1: Upload file to data source
        filename = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            resp = await self._client.post(
                "/api/v1/data-sources/upload",
                files={"file": (filename, f)},
            )
        self._raise_for_status(resp)
        upload_data = resp.json()

        # Step 2: Create a conversation session
        session_id = await self.create_session(interactive=False)

        # Step 3: Send the command to the agent
        final_command = command or "Ship all orders"
        resp = await self._client.post(
            f"/api/v1/conversations/{session_id}/messages",
            json={"content": final_command},
        )
        self._raise_for_status(resp)

        return SubmitResult(
            job_id=session_id,
            status="pending",
            row_count=upload_data.get("row_count", 0),
            message=f"File uploaded and command sent: {final_command}",
        )

    async def list_jobs(self, status: str | None = None) -> list[JobSummary]:
        """List jobs via GET /api/v1/jobs.

        Args:
            status: Optional status filter.

        Returns:
            List of JobSummary objects.
        """
        params = {}
        if status:
            params["status"] = status
        resp = await self._client.get("/api/v1/jobs", params=params)
        self._raise_for_status(resp)
        data = resp.json()
        jobs_data = data.get("jobs", data) if isinstance(data, dict) else data
        return [JobSummary.from_api(j) for j in jobs_data]

    async def get_job(self, job_id: str) -> JobDetail:
        """Get job detail via GET /api/v1/jobs/{id}.

        Args:
            job_id: The job ID.

        Returns:
            JobDetail with all fields.
        """
        resp = await self._client.get(f"/api/v1/jobs/{job_id}")
        self._raise_for_status(resp)
        return JobDetail.from_api(resp.json())

    async def get_job_rows(self, job_id: str) -> list[RowDetail]:
        """Get job rows via GET /api/v1/jobs/{id}/rows.

        Args:
            job_id: The job ID.

        Returns:
            List of RowDetail objects.
        """
        resp = await self._client.get(f"/api/v1/jobs/{job_id}/rows")
        self._raise_for_status(resp)
        data = resp.json()
        rows_data = data.get("rows", data) if isinstance(data, dict) else data
        return [RowDetail.from_api(r) for r in rows_data]

    async def cancel_job(self, job_id: str) -> None:
        """Cancel job via PATCH /api/v1/jobs/{id}/status.

        Args:
            job_id: The job to cancel.
        """
        resp = await self._client.patch(
            f"/api/v1/jobs/{job_id}/status",
            json={"status": "cancelled"},
        )
        self._raise_for_status(resp)

    async def approve_job(self, job_id: str) -> None:
        """Approve job via POST /api/v1/jobs/{id}/confirm.

        Args:
            job_id: The job to approve.
        """
        resp = await self._client.post(f"/api/v1/jobs/{job_id}/confirm")
        self._raise_for_status(resp)

    async def stream_progress(self, job_id: str) -> AsyncIterator[ProgressEvent]:
        """Stream progress via GET /api/v1/jobs/{id}/progress/stream.

        Parses SSE events into ProgressEvent objects.

        Args:
            job_id: The job to stream progress for.

        Yields:
            ProgressEvent objects as execution proceeds.
        """
        import httpx

        async with httpx.AsyncClient(base_url=self._base_url, timeout=None) as stream_client:
            async with stream_client.stream(
                "GET", f"/api/v1/jobs/{job_id}/progress/stream"
            ) as resp:
                if resp.status_code >= 400:
                    raise ShipAgentClientError(
                        message=f"Progress stream failed: HTTP {resp.status_code}",
                        status_code=resp.status_code,
                    )
                event_type = ""
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_str = line[5:].strip()
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        yield ProgressEvent(
                            job_id=job_id,
                            event_type=event_type or data.get("event_type", "unknown"),
                            row_number=data.get("row_number"),
                            total_rows=data.get("total_rows"),
                            tracking_number=data.get("tracking_number"),
                            message=data.get("message", ""),
                        )

    async def send_message(self, session_id: str,
                           content: str) -> AsyncIterator[AgentEvent]:
        """Send message and stream response via SSE.

        Args:
            session_id: The conversation session ID.
            content: The user message content.

        Yields:
            AgentEvent objects (deltas, tool calls, done).
        """
        import httpx

        # Send the message
        resp = await self._client.post(
            f"/api/v1/conversations/{session_id}/messages",
            json={"content": content},
        )
        self._raise_for_status(resp)

        # Stream the response
        async with httpx.AsyncClient(base_url=self._base_url, timeout=None) as stream_client:
            async with stream_client.stream(
                "GET", f"/api/v1/conversations/{session_id}/stream"
            ) as stream_resp:
                event_type = ""
                async for line in stream_resp.aiter_lines():
                    line = line.strip()
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_str = line[5:].strip()
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        yield AgentEvent(
                            event_type=event_type or data.get("event", "unknown"),
                            content=data.get("text") or data.get("content"),
                            tool_name=data.get("tool_name"),
                            tool_input=data.get("tool_input"),
                        )

    async def health(self) -> HealthStatus:
        """Check health via GET /health.

        Returns:
            HealthStatus with version, uptime, and component status.
        """
        try:
            resp = await self._client.get("/health")
            if resp.status_code == 200:
                data = resp.json()
                return HealthStatus(
                    healthy=True,
                    version=data.get("version", "unknown"),
                    uptime_seconds=data.get("uptime_seconds", 0),
                    active_jobs=data.get("active_jobs", 0),
                    watchdog_active=data.get("watchdog_active", False),
                    watch_folders=data.get("watch_folders", []),
                )
        except Exception:
            pass
        return HealthStatus(
            healthy=False,
            version="unknown",
            uptime_seconds=0,
            active_jobs=0,
            watchdog_active=False,
        )

    async def cleanup(self) -> None:
        """No-op for HTTP client (stateless)."""
        pass
