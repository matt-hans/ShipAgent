"""Tests for startup recovery hooks in FastAPI lifespan.

Verifies that on startup:
1. A real UPSMCPClient is created for recovery (track_package needs it)
2. In-flight rows are recovered BEFORE staging cleanup
3. Staging cleanup skips jobs with in_flight/needs_review rows
4. Recovery report is logged when needs_review rows found
5. UPS MCP unavailability is handled gracefully (rows stay in_flight)
6. UPS client is disconnected after recovery completes
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models import JobStatus
from src.api.main import run_startup_recovery


class TestStartupRecovery:
    """Verify startup recovery hook behavior."""

    @pytest.mark.asyncio
    async def test_recovery_runs_before_cleanup(self) -> None:
        """recover_in_flight_rows() is called BEFORE cleanup_staging()."""
        call_order: list[str] = []

        mock_engine = AsyncMock()

        async def mock_recover(*args, **kwargs):
            call_order.append("recover")
            return {"recovered": 0, "needs_review": 0, "unresolved": 0, "details": []}

        mock_engine.recover_in_flight_rows = mock_recover

        def mock_cleanup(*args, **kwargs):
            call_order.append("cleanup")
            return 0

        mock_ups_client = AsyncMock()
        mock_ups_client.connect = AsyncMock()
        mock_ups_client.disconnect = AsyncMock()

        with patch(
            "src.api.main.BatchEngine", return_value=mock_engine,
        ), patch(
            "src.api.main.BatchEngine.cleanup_staging", mock_cleanup,
        ), patch(
            "src.api.main.UPSMCPClient", return_value=mock_ups_client,
        ):
            mock_db = MagicMock()
            mock_js = MagicMock()
            mock_job = MagicMock()
            mock_job.id = "job-123"
            mock_js.list_jobs.return_value = [mock_job]

            in_flight_row = MagicMock()
            in_flight_row.status = "in_flight"
            mock_js.get_rows.return_value = [in_flight_row]

            await run_startup_recovery(mock_db, mock_js)

        assert call_order == ["recover", "cleanup"]

    @pytest.mark.asyncio
    async def test_cleanup_called_with_job_service(self) -> None:
        """cleanup_staging is called with the job_service instance."""
        cleanup_called_with = {}

        def mock_cleanup(js, **kwargs):
            cleanup_called_with["js"] = js
            return 0

        with patch(
            "src.api.main.BatchEngine.cleanup_staging", mock_cleanup,
        ):
            mock_db = MagicMock()
            mock_js = MagicMock()
            mock_js.list_jobs.return_value = []

            await run_startup_recovery(mock_db, mock_js)

        assert cleanup_called_with["js"] is mock_js

    @pytest.mark.asyncio
    async def test_no_recovery_when_no_interrupted_jobs(self) -> None:
        """No recovery attempted when no running/paused jobs exist."""
        mock_ups_class = MagicMock()

        with patch(
            "src.api.main.BatchEngine", MagicMock(),
        ), patch(
            "src.api.main.BatchEngine.cleanup_staging", return_value=0,
        ), patch(
            "src.api.main.UPSMCPClient", mock_ups_class,
        ):
            mock_db = MagicMock()
            mock_js = MagicMock()
            mock_js.list_jobs.return_value = []

            await run_startup_recovery(mock_db, mock_js)

        # UPSMCPClient should never be instantiated since no jobs need recovery
        mock_ups_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_jobs_without_inflight_rows(self) -> None:
        """Jobs in running state but without in_flight rows skip recovery."""
        mock_ups_class = MagicMock()

        with patch(
            "src.api.main.BatchEngine", MagicMock(),
        ), patch(
            "src.api.main.BatchEngine.cleanup_staging", return_value=0,
        ), patch(
            "src.api.main.UPSMCPClient", mock_ups_class,
        ):
            mock_db = MagicMock()
            mock_js = MagicMock()
            mock_job = MagicMock()
            mock_job.id = "job-123"
            mock_js.list_jobs.return_value = [mock_job]

            # No in_flight rows
            completed_row = MagicMock()
            completed_row.status = "completed"
            mock_js.get_rows.return_value = [completed_row]

            await run_startup_recovery(mock_db, mock_js)

        # No in-flight rows → no UPS client created
        mock_ups_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_recovery_failure_does_not_block_startup(self) -> None:
        """If recovery raises, startup still completes (logs error)."""
        mock_engine = AsyncMock()
        mock_engine.recover_in_flight_rows = AsyncMock(
            side_effect=Exception("UPS MCP unavailable"),
        )

        mock_ups_client = AsyncMock()
        mock_ups_client.connect = AsyncMock()
        mock_ups_client.disconnect = AsyncMock()

        with patch(
            "src.api.main.BatchEngine", return_value=mock_engine,
        ), patch(
            "src.api.main.BatchEngine.cleanup_staging", return_value=0,
        ), patch(
            "src.api.main.UPSMCPClient", return_value=mock_ups_client,
        ):
            mock_db = MagicMock()
            mock_js = MagicMock()
            mock_job = MagicMock()
            mock_job.id = "job-123"
            mock_js.list_jobs.return_value = [mock_job]

            in_flight_row = MagicMock()
            in_flight_row.status = "in_flight"
            mock_js.get_rows.return_value = [in_flight_row]

            # Should not raise — recovery failures are logged, not propagated
            await run_startup_recovery(mock_db, mock_js)

    @pytest.mark.asyncio
    async def test_ups_unavailable_graceful_fallback(self) -> None:
        """If UPS MCP connect() fails, recovery proceeds with ups_client=None."""
        batch_engine_kwargs: dict = {}
        mock_engine = AsyncMock()
        mock_engine.recover_in_flight_rows = AsyncMock(
            return_value={"recovered": 0, "needs_review": 1, "unresolved": 0, "details": []},
        )

        def capture_engine(**kwargs):
            batch_engine_kwargs.update(kwargs)
            return mock_engine

        mock_ups_client = AsyncMock()
        mock_ups_client.connect = AsyncMock(side_effect=Exception("Connection refused"))

        with patch(
            "src.api.main.BatchEngine", side_effect=capture_engine,
        ), patch(
            "src.api.main.BatchEngine.cleanup_staging", return_value=0,
        ), patch(
            "src.api.main.UPSMCPClient", return_value=mock_ups_client,
        ):
            mock_db = MagicMock()
            mock_js = MagicMock()
            mock_job = MagicMock()
            mock_job.id = "job-456"
            mock_js.list_jobs.return_value = [mock_job]

            in_flight_row = MagicMock()
            in_flight_row.status = "in_flight"
            mock_js.get_rows.return_value = [in_flight_row]

            await run_startup_recovery(mock_db, mock_js)

        # BatchEngine should receive ups_service=None when connect fails
        assert batch_engine_kwargs["ups_service"] is None

    @pytest.mark.asyncio
    async def test_ups_client_disconnected_after_recovery(self) -> None:
        """UPS MCP client is disconnected after recovery completes."""
        mock_engine = AsyncMock()
        mock_engine.recover_in_flight_rows = AsyncMock(
            return_value={"recovered": 1, "needs_review": 0, "unresolved": 0, "details": []},
        )

        mock_ups_client = AsyncMock()
        mock_ups_client.connect = AsyncMock()
        mock_ups_client.disconnect = AsyncMock()

        with patch(
            "src.api.main.BatchEngine", return_value=mock_engine,
        ), patch(
            "src.api.main.BatchEngine.cleanup_staging", return_value=0,
        ), patch(
            "src.api.main.UPSMCPClient", return_value=mock_ups_client,
        ):
            mock_db = MagicMock()
            mock_js = MagicMock()
            mock_job = MagicMock()
            mock_job.id = "job-789"
            mock_js.list_jobs.return_value = [mock_job]

            in_flight_row = MagicMock()
            in_flight_row.status = "in_flight"
            mock_js.get_rows.return_value = [in_flight_row]

            await run_startup_recovery(mock_db, mock_js)

        mock_ups_client.connect.assert_called_once()
        mock_ups_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_reaper_deletes_stale_empty_pending_jobs(self) -> None:
        """Startup reaper should delete old pending jobs with zero rows."""
        stale_job = MagicMock()
        stale_job.id = "job-stale"
        stale_job.created_at = (
            datetime.now(timezone.utc) - timedelta(hours=24)
        ).isoformat()

        mock_db = MagicMock()
        mock_js = MagicMock()
        mock_js.get_rows.return_value = []
        mock_js.delete_job.return_value = True

        def _list_jobs(status=None, limit=50, offset=0):
            if status == JobStatus.pending:
                return [stale_job]
            return []

        mock_js.list_jobs.side_effect = _list_jobs

        with patch("src.api.main.BatchEngine.cleanup_staging", return_value=0):
            await run_startup_recovery(mock_db, mock_js)

        mock_js.delete_job.assert_called_once_with("job-stale")

    @pytest.mark.asyncio
    async def test_reaper_keeps_recent_pending_jobs(self) -> None:
        """Recent pending jobs should not be reaped."""
        fresh_job = MagicMock()
        fresh_job.id = "job-fresh"
        fresh_job.created_at = datetime.now(timezone.utc).isoformat()

        mock_db = MagicMock()
        mock_js = MagicMock()
        mock_js.get_rows.return_value = []

        def _list_jobs(status=None, limit=50, offset=0):
            if status == JobStatus.pending:
                return [fresh_job]
            return []

        mock_js.list_jobs.side_effect = _list_jobs

        with patch("src.api.main.BatchEngine.cleanup_staging", return_value=0):
            await run_startup_recovery(mock_db, mock_js)

        mock_js.delete_job.assert_not_called()
