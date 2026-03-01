"""In-process runner implementation of ShipAgentClient.

Runs the full agent stack directly without requiring a daemon.
Used for development, testing, and standalone deployments.
All execution and session logic calls shared services from
batch_executor and conversation_handler — no duplication.
"""

import logging
from collections.abc import AsyncIterator
from uuid import uuid4

from src.cli.config import ShipAgentConfig
from src.cli.protocol import (
    AgentEvent,
    DataSourceStatus,
    HealthStatus,
    JobDetail,
    JobSummary,
    ProgressEvent,
    RowDetail,
    SavedSourceSummary,
    ShipAgentClientError,
    SourceSchemaColumn,
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

    async def get_source_status(self) -> DataSourceStatus:
        """Get current data source connection status via DataSourceMCPClient.

        Raises:
            ShipAgentClientError: If the gateway cannot be reached or queried.
        """
        from src.services.gateway_provider import get_data_gateway

        try:
            gw = await get_data_gateway()
        except Exception as e:
            logger.error("Failed to initialize data gateway: %s", e)
            raise ShipAgentClientError(
                f"Cannot reach data source gateway: {e}"
            ) from e

        try:
            info = await gw.get_source_info()
        except Exception as e:
            logger.error("Failed to query source info from gateway: %s", e)
            raise ShipAgentClientError(
                f"Data source query failed: {e}"
            ) from e

        if info is None:
            return DataSourceStatus(connected=False)

        columns_raw = info.get("columns", [])
        col_names = [
            c["name"] if isinstance(c, dict) else str(c)
            for c in columns_raw
        ]
        return DataSourceStatus(
            connected=True,
            source_type=info.get("source_type"),
            file_path=info.get("path"),
            row_count=info.get("row_count"),
            column_count=len(col_names),
            columns=col_names,
        )

    async def connect_source(self, file_path: str) -> DataSourceStatus:
        """Import a local file as the active data source."""
        from src.services.gateway_provider import get_data_gateway

        try:
            gw = await get_data_gateway()
        except Exception as e:
            logger.error("Failed to initialize data gateway: %s", e)
            raise ShipAgentClientError(f"Cannot reach data source gateway: {e}") from e

        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else "csv"
        try:
            if ext in ("xlsx", "xls"):
                await gw.import_excel(file_path)
            else:
                await gw.import_csv(file_path)
        except Exception as e:
            logger.error("Failed to import file %s: %s", file_path, e)
            raise ShipAgentClientError(f"Failed to import file: {e}") from e
        return await self.get_source_status()

    async def connect_db(
        self, connection_string: str, query: str
    ) -> DataSourceStatus:
        """Import from a database using connection string and query."""
        from src.services.gateway_provider import get_data_gateway

        try:
            gw = await get_data_gateway()
        except Exception as e:
            logger.error("Failed to initialize data gateway: %s", e)
            raise ShipAgentClientError(f"Cannot reach data source gateway: {e}") from e

        try:
            await gw.import_database(connection_string=connection_string, query=query)
        except Exception as e:
            logger.error("Failed to import from database: %s", e)
            raise ShipAgentClientError(f"Failed to import from database: {e}") from e
        return await self.get_source_status()

    async def disconnect_source(self) -> None:
        """Disconnect the current data source."""
        from src.services.gateway_provider import get_data_gateway

        gw = await get_data_gateway()
        await gw.disconnect()

    async def list_saved_sources(self) -> list[SavedSourceSummary]:
        """List saved data source profiles from database."""
        from src.db.connection import get_db_context
        from src.services.saved_data_source_service import SavedDataSourceService

        with get_db_context() as db:
            sources = SavedDataSourceService.list_sources(db)
            return [
                SavedSourceSummary(
                    id=s.id,
                    name=s.name or "",
                    source_type=s.source_type or "",
                    file_path=s.file_path,
                    last_connected=s.last_used_at,
                    row_count=s.row_count,
                )
                for s in sources
            ]

    async def reconnect_saved_source(
        self, identifier: str, by_name: bool = True
    ) -> DataSourceStatus:
        """Reconnect a saved source by name or ID.

        Looks up the source, then reimports via gateway.
        """
        from src.db.connection import get_db_context
        from src.services.gateway_provider import get_data_gateway
        from src.services.saved_data_source_service import SavedDataSourceService

        with get_db_context() as db:
            if by_name:
                sources = SavedDataSourceService.list_sources(db)
                source = next(
                    (s for s in sources if s.name == identifier), None
                )
            else:
                source = SavedDataSourceService.get_source(db, identifier)

            if not source:
                raise ShipAgentClientError(
                    f"Saved source not found: {identifier}"
                )

            gw = await get_data_gateway()
            if source.source_type == "csv" and source.file_path:
                await gw.import_csv(file_path=source.file_path)
            elif source.source_type == "excel" and source.file_path:
                await gw.import_excel(
                    file_path=source.file_path, sheet=source.sheet_name
                )
            else:
                raise ShipAgentClientError(
                    f"Cannot auto-reconnect {source.source_type} source. "
                    "Database sources require a connection_string."
                )

            SavedDataSourceService.touch(db, source.id)
            db.commit()

        return await self.get_source_status()

    async def get_source_schema(self) -> list[SourceSchemaColumn]:
        """Get schema of current data source from gateway."""
        from src.services.gateway_provider import get_data_gateway

        gw = await get_data_gateway()
        info = await gw.get_source_info()
        if info is None:
            raise ShipAgentClientError("No data source connected")
        columns_raw = info.get("columns", [])
        return [
            SourceSchemaColumn(
                name=c["name"] if isinstance(c, dict) else str(c),
                type=c.get("type", "VARCHAR") if isinstance(c, dict) else "VARCHAR",
                nullable=c.get("nullable", True) if isinstance(c, dict) else True,
            )
            for c in columns_raw
        ]

    async def connect_platform(self, platform: str) -> DataSourceStatus:
        """Connect an env-configured external platform (Shopify only).

        Reads credentials from environment variables and validates
        them via the ExternalSourcesMCPClient, mirroring the HTTP path
        through GET /api/v1/platforms/shopify/env-status.

        Args:
            platform: Platform name (only "shopify" supported).

        Raises:
            ShipAgentClientError: If platform unsupported or credentials missing/invalid.
        """
        import os

        if platform.lower() != "shopify":
            raise ShipAgentClientError(
                f"Only 'shopify' supports env-based auto-connect. "
                f"Use the agent conversation for {platform}."
            )

        access_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
        store_domain = os.environ.get("SHOPIFY_STORE_DOMAIN")
        if not access_token or not store_domain:
            raise ShipAgentClientError(
                "SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN environment "
                "variables must be set for Shopify auto-connect."
            )

        from src.services.gateway_provider import get_external_sources_client

        client = await get_external_sources_client()
        result = await client.connect_platform(
            platform="shopify",
            credentials={"access_token": access_token},
            store_url=store_domain,
        )
        if isinstance(result, dict) and not result.get("valid", True):
            raise ShipAgentClientError(
                result.get("error", "Shopify credential validation failed")
            )
        return await self.get_source_status()

    async def cleanup(self) -> None:
        """Shut down gateways."""
        from src.services.gateway_provider import shutdown_gateways
        await shutdown_gateways()

    async def get_job_audit_events(self, job_id: str, limit: int = 200) -> list[dict]:
        """Get centralized decision audit events for a job."""
        from src.services.decision_audit_service import DecisionAuditService

        payload = DecisionAuditService.list_events_for_job(
            job_id=job_id,
            limit=limit,
            offset=0,
        )
        events = payload.get("events", [])
        return events if isinstance(events, list) else []
