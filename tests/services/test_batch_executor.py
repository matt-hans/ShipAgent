"""Tests for shared batch execution service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Job, JobRow, JobStatus, RowStatus
from src.services.batch_executor import execute_batch, get_shipper_for_job


class TestGetShipperForJob:
    """Tests for shipper resolution logic.

    get_shipper_for_job() is async (Shopify fallback requires MCP call),
    so all tests use async def + await.
    """

    @pytest.mark.asyncio
    async def test_uses_persisted_shipper_json(self):
        """Returns persisted shipper when job has shipper_json."""
        job = MagicMock()
        job.shipper_json = '{"name": "Acme Corp", "city": "LA"}'
        result = await get_shipper_for_job(job)
        assert result["name"] == "Acme Corp"

    @pytest.mark.asyncio
    async def test_falls_back_to_env_shipper(self, monkeypatch):
        """Falls back to env-based shipper when no shipper_json."""
        job = MagicMock()
        job.shipper_json = None
        monkeypatch.setenv("SHIPPER_NAME", "Env Corp")

        mock_gw = AsyncMock()
        mock_gw.get_source_info = AsyncMock(return_value={"source_type": "csv"})

        with patch(
            "src.services.gateway_provider.get_data_gateway",
            new_callable=AsyncMock,
            return_value=mock_gw,
        ):
            result = await get_shipper_for_job(job)
            # Should not raise; returns a dict
            assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_terminal_write_back_failure_persists_and_logs_only_safe_diagnostic(
    caplog,
):
    marker = "UNSAFE_EXECUTOR_WRITE_BACK_DETAIL"
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    job = Job(
        name="Example",
        original_command="Example",
        status=JobStatus.running.value,
        total_rows=1,
    )
    db.add(job)
    db.flush()
    db.add(
        JobRow(
            job_id=job.id,
            row_number=1,
            row_checksum="1" * 64,
            status=RowStatus.pending.value,
        )
    )
    db.commit()

    credentials = MagicMock(
        client_id="SAFE_TEST_CLIENT_ID",
        client_secret="SAFE_TEST_CLIENT_SECRET",
        environment="test",
        account_number="SAFE_TEST_ACCOUNT",
    )
    ups_context = AsyncMock()
    ups_context.__aenter__.return_value = AsyncMock()
    batch_engine = AsyncMock()
    batch_engine.execute.return_value = {
        "successful": 1,
        "failed": 0,
        "total_cost_cents": 125,
        "write_back": {
            "status": "error",
            "message": marker,
            "errors": [{"detail": marker}],
        },
    }

    with (
        patch(
            "src.services.batch_executor.get_shipper_for_job",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "src.services.runtime_credentials.resolve_ups_credentials",
            return_value=credentials,
        ),
        patch(
            "src.services.batch_executor.UPSMCPClient",
            return_value=ups_context,
        ),
        patch(
            "src.services.batch_executor.BatchEngine",
            return_value=batch_engine,
        ),
        patch(
            "src.services.batch_executor.DecisionAuditService.resolve_run_id_for_job",
            return_value=None,
        ),
        patch(
            "src.services.batch_executor.DecisionAuditService.log_event",
        ),
    ):
        result = await execute_batch(job.id, db)

    db.refresh(job)
    assert result["status"] == JobStatus.completed_with_warnings.value
    assert job.error_code == "E-4001"
    assert (
        job.error_message == "The row could not be processed because of a system error."
    )
    assert marker not in repr(result)
    assert marker not in caplog.text
    db.close()


@pytest.mark.asyncio
async def test_resume_reconciles_preexisting_needs_review_row_counts():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    job = Job(
        name="Resume projection",
        original_command="Run the resume projection fixture",
        status=JobStatus.running.value,
        total_rows=2,
        processed_rows=0,
        successful_rows=0,
        failed_rows=0,
    )
    db.add(job)
    db.flush()
    db.add_all(
        [
            JobRow(
                job_id=job.id,
                row_number=1,
                row_checksum="1" * 64,
                status=RowStatus.needs_review.value,
                error_code="E-3001",
            ),
            JobRow(
                job_id=job.id,
                row_number=2,
                row_checksum="2" * 64,
                status=RowStatus.pending.value,
            ),
        ]
    )
    db.commit()

    credentials = MagicMock(
        client_id="SAFE_TEST_CLIENT_ID",
        client_secret="SAFE_TEST_CLIENT_SECRET",
        environment="test",
        account_number="SAFE_TEST_ACCOUNT",
    )
    ups_context = AsyncMock()
    ups_context.__aenter__.return_value = AsyncMock()
    batch_engine = AsyncMock()

    async def execute_pending(**kwargs):
        pending_row = kwargs["rows"][0]
        pending_row.status = RowStatus.completed.value
        pending_row.cost_cents = 225
        db.commit()
        return {
            "successful": 1,
            "failed": 0,
            "total_cost_cents": 225,
            "write_back": {"status": "skipped"},
        }

    batch_engine.execute.side_effect = execute_pending

    with (
        patch(
            "src.services.batch_executor.get_shipper_for_job",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "src.services.runtime_credentials.resolve_ups_credentials",
            return_value=credentials,
        ),
        patch(
            "src.services.batch_executor.UPSMCPClient",
            return_value=ups_context,
        ),
        patch(
            "src.services.batch_executor.BatchEngine",
            return_value=batch_engine,
        ),
        patch(
            "src.services.batch_executor.DecisionAuditService.resolve_run_id_for_job",
            return_value=None,
        ),
        patch(
            "src.services.batch_executor.DecisionAuditService.log_event",
        ),
    ):
        result = await execute_batch(job.id, db)

    db.refresh(job)
    assert result == {
        "successful": 1,
        "failed": 1,
        "total_cost_cents": 225,
        "status": JobStatus.failed.value,
        "international_row_count": 0,
        "total_duties_taxes_cents": 0,
    }
    assert job.processed_rows == 2
    assert job.successful_rows == 1
    assert job.failed_rows == 1
    assert job.total_cost_cents == 225
    assert job.status == JobStatus.failed.value
    db.close()
