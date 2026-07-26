"""Crash recovery count invariants across resume/cancel, REST, and artifacts."""

import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.models import (
    ConversationMessage,
    ConversationSession,
    Job,
    JobRow,
    JobStatus,
    RowStatus,
)
from src.orchestrator.batch.recovery import RecoveryChoice, handle_recovery_choice
from src.services.batch_engine import BatchEngine
from src.services.batch_executor import execute_batch
from src.services.job_service import JobService

_JOB_ID = "22222222-2222-4222-8222-222222222222"


def _artifact_metadata(
    *,
    status: str,
    successful: int,
    failed: int,
    error_code: str,
) -> dict:
    cancelled = status == JobStatus.cancelled.value
    return {
        "type": "completion",
        "jobId": _JOB_ID,
        "action": "complete",
        "completion": {
            "status": status,
            "outcome": "failed",
            "hasWarnings": False,
            "cancelled": cancelled,
            "statusMessage": (
                "Batch cancelled. You can enter a new command."
                if cancelled
                else "Batch failed."
            ),
            "successful": successful,
            "failed": failed,
            "totalCostCents": 225 if successful else 0,
            "error": {
                "error_code": error_code,
                "error_category": ("ups_api" if error_code == "E-3001" else "system"),
                "message": (
                    "The carrier could not process this shipment."
                    if error_code == "E-3001"
                    else "The row could not be processed because of a system error."
                ),
            },
            "row_failures": [
                {
                    "row_number": 1,
                    "error_code": "E-4001",
                    "error_category": "system",
                    "message": (
                        "The row could not be processed because of a system error."
                    ),
                }
            ],
            "omitted_failure_count": 0,
        },
    }


def _seed_interrupted_job(test_db: Session, session_id: str) -> tuple[Job, JobRow]:
    job = Job(
        id=_JOB_ID,
        name="Recovery count fixture",
        original_command="Run the recovery count fixture",
        status=JobStatus.running.value,
        total_rows=2,
        processed_rows=0,
        successful_rows=0,
        failed_rows=0,
    )
    interrupted = JobRow(
        job_id=job.id,
        row_number=1,
        row_checksum="1" * 64,
        status=RowStatus.in_flight.value,
        idempotency_key="SAFE_INTERNAL_RECOVERY_KEY",
    )
    pending = JobRow(
        job_id=job.id,
        row_number=2,
        row_checksum="2" * 64,
        status=RowStatus.pending.value,
    )
    test_db.add_all(
        [
            ConversationSession(id=session_id, mode="batch"),
            job,
            interrupted,
            pending,
        ]
    )
    test_db.commit()
    return job, interrupted


@contextmanager
def _db_context(test_db: Session):
    yield test_db


@pytest.mark.asyncio
async def test_crash_recovery_resume_rest_and_artifact_share_exact_counts(
    client: TestClient,
    test_db: Session,
) -> None:
    session_id = "recovery-resume-session"
    job, interrupted = _seed_interrupted_job(test_db, session_id)
    recovery_engine = BatchEngine(
        ups_service=AsyncMock(),
        db_session=test_db,
        account_number="",
    )
    await recovery_engine.recover_in_flight_rows(job.id, [interrupted])
    assert interrupted.status == RowStatus.needs_review.value

    recovery_choice = handle_recovery_choice(
        RecoveryChoice.RESUME,
        job.id,
        JobService(test_db),
    )
    assert recovery_choice["action"] == "resume"

    credentials = MagicMock(
        client_id="SAFE_TEST_CLIENT_ID",
        client_secret="SAFE_TEST_CLIENT_SECRET",
        environment="test",
        account_number="SAFE_TEST_ACCOUNT",
    )
    ups_context = AsyncMock()
    ups_context.__aenter__.return_value = AsyncMock()
    execution_engine = AsyncMock()

    async def execute_pending(**kwargs):
        pending_row = kwargs["rows"][0]
        pending_row.status = RowStatus.completed.value
        pending_row.cost_cents = 225
        test_db.commit()
        return {
            "successful": 1,
            "failed": 0,
            "total_cost_cents": 225,
            "write_back": {"status": "skipped"},
        }

    execution_engine.execute.side_effect = execute_pending
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
            return_value=execution_engine,
        ),
        patch(
            "src.services.batch_executor.DecisionAuditService.resolve_run_id_for_job",
            return_value=None,
        ),
        patch(
            "src.services.batch_executor.DecisionAuditService.log_event",
        ),
    ):
        await execute_batch(job.id, test_db)

    progress_response = client.get(f"/api/v1/jobs/{job.id}/progress")
    assert progress_response.status_code == 200
    progress = progress_response.json()
    assert progress["successful_rows"] == 1
    assert progress["failed_rows"] == 1
    assert progress["failed_rows"] == (
        len(progress["row_failures"]) + progress["omitted_failure_count"]
    )

    with patch(
        "src.db.connection.get_db_context",
        lambda: _db_context(test_db),
    ):
        artifact_response = client.post(
            f"/api/v1/conversations/{session_id}/artifacts",
            json={
                "content": "",
                "metadata": _artifact_metadata(
                    status=JobStatus.failed.value,
                    successful=1,
                    failed=1,
                    error_code="E-3001",
                ),
            },
        )

    assert artifact_response.status_code == 201
    stored = (
        test_db.query(ConversationMessage)
        .filter(ConversationMessage.session_id == session_id)
        .one()
    )
    completion = json.loads(stored.metadata_json)["completion"]
    assert completion["failed"] == (
        len(completion["row_failures"]) + completion["omitted_failure_count"]
    )
    assert completion["successful"] == progress["successful_rows"]
    assert completion["failed"] == progress["failed_rows"]


@pytest.mark.asyncio
async def test_crash_recovery_cancel_rest_and_artifact_share_exact_counts(
    client: TestClient,
    test_db: Session,
) -> None:
    session_id = "recovery-cancel-session"
    job, interrupted = _seed_interrupted_job(test_db, session_id)
    recovery_engine = BatchEngine(
        ups_service=AsyncMock(),
        db_session=test_db,
        account_number="",
    )
    await recovery_engine.recover_in_flight_rows(job.id, [interrupted])

    recovery_choice = handle_recovery_choice(
        RecoveryChoice.CANCEL,
        job.id,
        JobService(test_db),
    )
    assert recovery_choice["action"] == "cancel"

    progress_response = client.get(f"/api/v1/jobs/{job.id}/progress")
    assert progress_response.status_code == 200
    progress = progress_response.json()
    assert progress["status"] == JobStatus.cancelled.value
    assert progress["successful_rows"] == 0
    assert progress["failed_rows"] == 1
    assert progress["failed_rows"] == (
        len(progress["row_failures"]) + progress["omitted_failure_count"]
    )

    with patch(
        "src.db.connection.get_db_context",
        lambda: _db_context(test_db),
    ):
        artifact_response = client.post(
            f"/api/v1/conversations/{session_id}/artifacts",
            json={
                "content": "",
                "metadata": _artifact_metadata(
                    status=JobStatus.cancelled.value,
                    successful=0,
                    failed=1,
                    error_code="E-4001",
                ),
            },
        )

    assert artifact_response.status_code == 201
    stored = (
        test_db.query(ConversationMessage)
        .filter(ConversationMessage.session_id == session_id)
        .one()
    )
    completion = json.loads(stored.metadata_json)["completion"]
    assert completion["status"] == JobStatus.cancelled.value
    assert completion["failed"] == (
        len(completion["row_failures"]) + completion["omitted_failure_count"]
    )
    assert completion["failed"] == progress["failed_rows"]
