"""In-process runner implementation of ShipAgentClient.

Runs the full agent stack directly without requiring a daemon.
Used for development, testing, and standalone deployments.
All execution and session logic calls shared services from
batch_executor and conversation_handler — no duplication.
"""

import logging
from typing import AsyncIterator
from uuid import uuid4

from src.cli.config import ShipAgentConfig
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


class InProcessRunner:
    """ShipAgentClient implementation that runs the agent stack in-process."""

    def __init__(self, config: ShipAgentConfig | None = None,
                 interactive_shipping: bool = False):
        """Initialize with optional config.

        Args:
            config: Loaded ShipAgent config. Uses defaults if None.
            interactive_shipping: Whether to enable interactive mode.
        """
        self._config = config
        self._interactive_shipping = interactive_shipping
        self._initialized = False
        self._session_manager = None

    async def __aenter__(self):
        """Initialize DB, MCP gateways, and agent session manager."""
        from src.db.connection import init_db
        from src.services.agent_session_manager import AgentSessionManager

        init_db()
        self._session_manager = AgentSessionManager()
        self._initialized = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Shut down MCP gateways."""
        if self._initialized:
            from src.services.gateway_provider import shutdown_gateways
            await shutdown_gateways()

    async def create_session(self, interactive: bool = False) -> str:
        """Create agent session in-process.

        Args:
            interactive: If True, creates an interactive shipping session.

        Returns:
            Session ID string.
        """
        session_id = str(uuid4())
        session = self._session_manager.get_or_create_session(session_id)
        session.interactive_shipping = interactive or self._interactive_shipping
        return session_id

    async def delete_session(self, session_id: str) -> None:
        """Delete agent session in-process.

        Args:
            session_id: The session to delete. No-op if not found.
        """
        session = self._session_manager.get_session(session_id)
        if session is not None:
            await self._session_manager.stop_session_agent(session_id)
            self._session_manager.remove_session(session_id)

    async def submit_file(self, file_path: str, command: str | None,
                          auto_confirm: bool) -> SubmitResult:
        """Import file and run agent command in-process.

        After the agent processes the command it creates a job in the
        database.  We capture the job ID by timestamping before processing
        and querying for any job created on or after that timestamp.

        Args:
            file_path: Path to CSV or Excel file.
            command: Agent command. Defaults to "Ship all orders".
            auto_confirm: Unused here — callers handle auto-confirm after
                receiving the real job_id via SubmitResult.

        Returns:
            SubmitResult with the real job ID (or session_id as fallback
            if the agent did not create a job).
        """
        from src.services.gateway_provider import get_data_gateway

        gw = await get_data_gateway()

        # Detect file type from extension
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else "csv"
        if ext in ("xlsx", "xls"):
            result = await gw.import_excel(file_path)
        else:
            result = await gw.import_csv(file_path)

        row_count = result.get("rows", 0) if isinstance(result, dict) else 0

        # Create session and send command
        session_id = await self.create_session(interactive=False)
        final_command = command or "Ship all orders"

        # Process through agent — consume all events and capture job_id from
        # the preview_ready event, which is the same deterministic source used
        # by HttpClient.  This avoids the timestamp-based DB query that was
        # race-prone under concurrent job creation against the same database.
        from src.services.conversation_handler import process_message

        session = self._session_manager.get_session(session_id)
        session.add_message("user", final_command)

        job_id = session_id  # fallback if agent did not create a job
        async for event in process_message(session, final_command):
            if event.get("event") == "preview_ready":
                captured = event.get("data", {}).get("job_id")
                if captured:
                    job_id = captured

        return SubmitResult(
            job_id=job_id,
            status="pending",
            row_count=row_count,
            message=f"File imported and command sent: {final_command}",
        )

    async def list_jobs(self, status: str | None = None) -> list[JobSummary]:
        """List jobs directly from database.

        Args:
            status: Optional status filter.

        Returns:
            List of JobSummary objects.
        """
        from src.db.connection import get_db
        from src.db.models import Job

        db = next(get_db())
        try:
            query = db.query(Job)
            if status:
                query = query.filter(Job.status == status)
            jobs = query.order_by(Job.created_at.desc()).all()

            return [
                JobSummary.from_api({
                    "id": j.id,
                    "name": j.name or "",
                    "status": j.status,
                    "total_rows": j.total_rows or 0,
                    "successful_rows": j.successful_rows or 0,
                    "failed_rows": j.failed_rows or 0,
                    "created_at": j.created_at or "",
                })
                for j in jobs
            ]
        finally:
            db.close()

    async def get_job(self, job_id: str) -> JobDetail:
        """Get job detail directly from database.

        Args:
            job_id: The job ID.

        Returns:
            JobDetail with all fields.

        Raises:
            ShipAgentClientError: If job not found.
        """
        from src.db.connection import get_db
        from src.db.models import Job

        db = next(get_db())
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job:
                raise ShipAgentClientError(
                    message=f"Job not found: {job_id}",
                    status_code=404,
                )

            return JobDetail.from_api({
                "id": job.id,
                "name": job.name or "",
                "status": job.status,
                "original_command": job.original_command or "",
                "total_rows": job.total_rows or 0,
                "processed_rows": job.processed_rows or 0,
                "successful_rows": job.successful_rows or 0,
                "failed_rows": job.failed_rows or 0,
                "total_cost_cents": job.total_cost_cents or 0,
                "created_at": job.created_at or "",
                "started_at": job.started_at,
                "completed_at": job.completed_at,
                "error_code": job.error_code,
                "error_message": job.error_message,
            })
        finally:
            db.close()

    async def get_job_rows(self, job_id: str) -> list[RowDetail]:
        """Get job rows directly from database.

        Args:
            job_id: The job ID.

        Returns:
            List of RowDetail objects.
        """
        from src.db.connection import get_db
        from src.db.models import JobRow

        db = next(get_db())
        try:
            rows = (
                db.query(JobRow)
                .filter(JobRow.job_id == job_id)
                .order_by(JobRow.row_number)
                .all()
            )

            return [
                RowDetail.from_api({
                    "id": str(r.id),
                    "row_number": r.row_number,
                    "status": r.status,
                    "tracking_number": r.tracking_number,
                    "cost_cents": r.cost_cents,
                    "error_code": r.error_code,
                    "error_message": r.error_message,
                    "order_data": r.order_data,
                })
                for r in rows
            ]
        finally:
            db.close()

    async def cancel_job(self, job_id: str) -> None:
        """Cancel job directly via database.

        Args:
            job_id: The job to cancel.

        Raises:
            ShipAgentClientError: If job not found or cannot be cancelled.
        """
        from src.db.connection import get_db
        from src.db.models import Job

        db = next(get_db())
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job:
                raise ShipAgentClientError(
                    message=f"Job not found: {job_id}",
                    status_code=404,
                )
            if job.status not in ("pending", "running"):
                raise ShipAgentClientError(
                    message=f"Cannot cancel job in {job.status} status",
                    status_code=400,
                )
            job.status = "cancelled"
            db.commit()
        finally:
            db.close()

    async def approve_job(self, job_id: str) -> None:
        """Approve job via shared batch execution service.

        Args:
            job_id: The job to approve and execute.
        """
        from src.db.connection import get_db
        from src.services.batch_executor import execute_batch

        db = next(get_db())
        try:
            await execute_batch(job_id, db, on_progress=self._log_progress)
        finally:
            db.close()

    async def _log_progress(self, event_type: str, **kwargs) -> None:
        """Log progress events for CLI feedback.

        Args:
            event_type: Type of progress event.
            **kwargs: Event-specific data.
        """
        if event_type == "row_completed":
            logger.info(
                "Row %d completed: tracking=%s cost=$%.2f",
                kwargs.get("row_number", 0),
                kwargs.get("tracking_number", ""),
                kwargs.get("cost_cents", 0) / 100,
            )
        elif event_type == "row_failed":
            logger.warning(
                "Row %d failed: %s — %s",
                kwargs.get("row_number", 0),
                kwargs.get("error_code", ""),
                kwargs.get("error_message", ""),
            )

    async def stream_progress(self, job_id: str) -> AsyncIterator[ProgressEvent]:
        """Stream progress in-process.

        Args:
            job_id: The job to stream progress for.

        Yields:
            ProgressEvent objects.
        """
        # In-process runner doesn't have SSE — poll job status instead
        detail = await self.get_job(job_id)
        yield ProgressEvent(
            job_id=job_id,
            event_type="status",
            row_number=detail.processed_rows,
            total_rows=detail.total_rows,
            tracking_number=None,
            message=f"Status: {detail.status}",
        )

    async def send_message(self, session_id: str,
                           content: str) -> AsyncIterator[AgentEvent]:
        """Send message via shared conversation handler.

        History write ownership: this method adds the user message
        before calling process_message(), matching the convention
        that callers own history writes.

        Args:
            session_id: The conversation session ID.
            content: The user message content.

        Yields:
            AgentEvent objects (deltas, tool calls, done).
        """
        from src.services.conversation_handler import process_message

        session = self._session_manager.get_session(session_id)
        if not session:
            raise ShipAgentClientError(
                message=f"Session not found: {session_id}",
                status_code=404,
            )

        # Caller-owned history write
        session.add_message("user", content)

        async for event in process_message(
            session, content, self._interactive_shipping
        ):
            data = event.get("data", {})
            yield AgentEvent(
                event_type=event.get("event", "unknown"),
                content=data.get("text"),
                tool_name=data.get("tool_name"),
                tool_input=data.get("tool_input"),
            )

    async def health(self) -> HealthStatus:
        """Report in-process health (always healthy if running).

        Returns:
            HealthStatus indicating healthy state.
        """
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
