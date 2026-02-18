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

        Streams the agent SSE response until "done" so the job created by
        the agent is visible before we query for its ID.  We snapshot
        existing job IDs before sending the command and diff afterwards to
        isolate the new job.

        Args:
            file_path: Path to CSV or Excel file.
            command: Agent command. Defaults to "Ship all orders" if None.
            auto_confirm: Unused here — callers handle auto-confirm after
                receiving the real job_id via SubmitResult.

        Returns:
            SubmitResult with the real job ID (or session_id as fallback
            if the agent did not create a job).
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

        # Step 2: Snapshot existing job IDs so we can identify the new one
        existing_ids: set[str] = set()
        try:
            existing_jobs = await self.list_jobs()
            existing_ids = {j.id for j in existing_jobs}
        except Exception:
            pass  # Non-fatal — worst case we fall back to session_id

        # Step 3: Create a conversation session
        session_id = await self.create_session(interactive=False)

        # Step 4: Send the command to the agent
        final_command = command or "Ship all orders"
        resp = await self._client.post(
            f"/api/v1/conversations/{session_id}/messages",
            json={"content": final_command},
        )
        self._raise_for_status(resp)

        # Step 5: Stream SSE; capture job_id from preview_ready event
        streamed_job_id = await self._drain_session_stream(session_id)

        # Step 6: Delete the conversation session — job is now the handle
        try:
            await self.delete_session(session_id)
        except Exception:
            pass  # Non-fatal: session will expire eventually

        # Step 7: Resolve job_id — event-sourced ID is preferred; fall back
        # to list diff only when the preview_ready event was not observed
        # (e.g., the agent returned an error before creating the job).
        if streamed_job_id:
            job_id = streamed_job_id
        else:
            job_id = session_id  # last-resort fallback
            try:
                new_jobs = await self.list_jobs()
                for job in new_jobs:
                    if job.id not in existing_ids:
                        job_id = job.id
                        break
            except Exception:
                pass  # Non-fatal fallback to session_id

        return SubmitResult(
            job_id=job_id,
            status="pending",
            row_count=upload_data.get("row_count", 0),
            message=f"File uploaded and command sent: {final_command}",
        )

    async def _drain_session_stream(self, session_id: str) -> str | None:
        """Stream the agent SSE response until the "done" event.

        Captures the job_id from any ``preview_ready`` event so callers
        can identify the created job deterministically without resorting
        to a list diff, which is inherently race-prone under concurrent
        job creation.

        Args:
            session_id: The conversation session to drain.

        Returns:
            The job_id extracted from the ``preview_ready`` event, or
            ``None`` if the event was not observed before "done".
        """
        import httpx

        captured_job_id: str | None = None
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=120.0
            ) as stream_client:
                async with stream_client.stream(
                    "GET", f"/api/v1/conversations/{session_id}/stream"
                ) as stream_resp:
                    async for line in stream_resp.aiter_lines():
                        line = line.strip()
                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            event = data.get("event")
                            if event == "preview_ready":
                                job_id = data.get("data", {}).get("job_id")
                                if job_id:
                                    captured_job_id = job_id
                            elif event == "done":
                                return captured_job_id
        except Exception as exc:
            logger.warning("Session stream drain failed for %s: %s", session_id, exc)
        return captured_job_id

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
                        # SSE payload is envelope-shaped: {"event": "...", "data": {...}}
                        inner = data.get("data", {})
                        yield ProgressEvent(
                            job_id=job_id,
                            event_type=event_type or data.get("event", "unknown"),
                            row_number=inner.get("row_number"),
                            total_rows=inner.get("total_rows"),
                            tracking_number=inner.get("tracking_number"),
                            message=inner.get("message", ""),
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
                        # SSE payload is envelope-shaped: {"event": "...", "data": {...}}
                        inner = data.get("data", {})
                        yield AgentEvent(
                            event_type=event_type or data.get("event", "unknown"),
                            content=inner.get("text") or inner.get("content"),
                            tool_name=inner.get("tool_name"),
                            tool_input=inner.get("tool_input"),
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
