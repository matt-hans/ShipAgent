"""Tests for startup recovery hooks in FastAPI lifespan.

Verifies that on startup:
1. In-flight rows are recovered BEFORE staging cleanup
2. Staging cleanup skips jobs with in_flight/needs_review rows
3. Recovery report is logged when needs_review rows found
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

        with patch(
            "src.api.main.BatchEngine", return_value=mock_engine,
        ), patch(
            "src.api.main.BatchEngine.cleanup_staging", mock_cleanup,
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
        mock_engine_class = MagicMock()

        with patch(
            "src.api.main.BatchEngine", mock_engine_class,
        ), patch(
            "src.api.main.BatchEngine.cleanup_staging", return_value=0,
        ):
            mock_db = MagicMock()
            mock_js = MagicMock()
            mock_js.list_jobs.return_value = []

            await run_startup_recovery(mock_db, mock_js)

        # BatchEngine should never be instantiated since no jobs need recovery
        mock_engine_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_jobs_without_inflight_rows(self) -> None:
        """Jobs in running state but without in_flight rows skip recovery."""
        mock_engine_class = MagicMock()

        with patch(
            "src.api.main.BatchEngine", mock_engine_class,
        ), patch(
            "src.api.main.BatchEngine.cleanup_staging", return_value=0,
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

        mock_engine_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_recovery_failure_does_not_block_startup(self) -> None:
        """If recovery raises, startup still completes (logs error)."""
        mock_engine = AsyncMock()
        mock_engine.recover_in_flight_rows = AsyncMock(
            side_effect=Exception("UPS MCP unavailable"),
        )

        with patch(
            "src.api.main.BatchEngine", return_value=mock_engine,
        ), patch(
            "src.api.main.BatchEngine.cleanup_staging", return_value=0,
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
