"""Tests for progress streaming endpoints.

Tests the /api/v1/jobs/{job_id}/progress endpoints for
SSE streaming and fallback progress retrieval.
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.routes.progress import _event_generator, sse_observer, stream_progress
from src.db.models import Job, JobRow, JobStatus, RowStatus
from src.errors.terminal_diagnostics import (
    MAX_TERMINAL_ROW_DIAGNOSTICS,
    MAX_TERMINAL_ROW_NUMBER,
)


class _ConnectedRequest:
    """Minimal request double whose client never disconnects."""

    async def is_disconnected(self) -> bool:
        return False


class TestProgressFallback:
    """Tests for GET /api/v1/jobs/{job_id}/progress endpoint (non-SSE)."""

    def test_progress_job_not_found(self, client: TestClient):
        """Returns 404 for non-existent job."""
        response = client.get("/api/v1/jobs/nonexistent-id/progress")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_progress_returns_current_state(self, client: TestClient, test_db: Session):
        """Returns current job progress state."""
        job = Job(
            name="Progress Test Job",
            original_command="Test command",
            status=JobStatus.running.value,
            total_rows=10,
            processed_rows=5,
            successful_rows=4,
            failed_rows=1,
            total_cost_cents=2500,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        response = client.get(f"/api/v1/jobs/{job.id}/progress")

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job.id
        assert data["status"] == "running"
        assert data["total_rows"] == 10
        assert data["processed_rows"] == 5
        assert data["successful_rows"] == 4
        assert data["failed_rows"] == 1
        assert data["total_cost_cents"] == 2500

    def test_progress_pending_job(self, client: TestClient, sample_job: Job):
        """Returns progress for pending job."""
        response = client.get(f"/api/v1/jobs/{sample_job.id}/progress")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["processed_rows"] == 0

    def test_progress_projects_persisted_row_failure_to_safe_diagnostic(
        self, client: TestClient, test_db: Session
    ):
        raw_carrier_text = (
            "carrier request recipient=Jane Doe address=1 Main St api_key=private-token"
        )
        job = Job(
            name="Progress diagnostics",
            original_command="Test command",
            status=JobStatus.failed.value,
            total_rows=1,
            processed_rows=1,
            failed_rows=1,
        )
        test_db.add(job)
        test_db.flush()
        test_db.add(
            JobRow(
                job_id=job.id,
                row_number=1,
                row_checksum="a" * 64,
                status=RowStatus.failed.value,
                error_code="E-3003",
                error_message=raw_carrier_text,
            )
        )
        test_db.commit()

        response = client.get(f"/api/v1/jobs/{job.id}/progress")

        assert response.status_code == 200
        assert response.json()["row_failures"] == [
            {
                "row_number": 1,
                "error_code": "E-3003",
                "error_category": "ups_api",
                "message": "The carrier could not process this shipment.",
            }
        ]
        assert response.json()["omitted_failure_count"] == 0
        assert raw_carrier_text not in response.text

    def test_progress_derives_counts_from_authoritative_recovered_row_state(
        self,
        client: TestClient,
        test_db: Session,
    ) -> None:
        job = Job(
            name="Recovered progress",
            original_command="Run the recovered progress fixture",
            status=JobStatus.cancelled.value,
            total_rows=2,
            processed_rows=0,
            successful_rows=0,
            failed_rows=0,
        )
        test_db.add(job)
        test_db.flush()
        test_db.add_all(
            [
                JobRow(
                    job_id=job.id,
                    row_number=1,
                    row_checksum="1" * 64,
                    status=RowStatus.completed.value,
                    cost_cents=125,
                ),
                JobRow(
                    job_id=job.id,
                    row_number=2,
                    row_checksum="2" * 64,
                    status=RowStatus.needs_review.value,
                    error_code="E-3001",
                    error_message="UNSAFE_STALE_RECOVERY_DETAIL",
                ),
            ]
        )
        test_db.commit()

        response = client.get(f"/api/v1/jobs/{job.id}/progress")

        assert response.status_code == 200
        payload = response.json()
        assert payload["processed_rows"] == 2
        assert payload["successful_rows"] == 1
        assert payload["failed_rows"] == 1
        assert payload["total_cost_cents"] == 125
        assert payload["failed_rows"] == (
            len(payload["row_failures"]) + payload["omitted_failure_count"]
        )
        assert "UNSAFE_STALE_RECOVERY_DETAIL" not in response.text

    def test_progress_omits_malformed_legacy_row_numbers_without_500(
        self,
        client: TestClient,
        test_db: Session,
    ) -> None:
        job = Job(
            name="Malformed legacy rows",
            original_command="Run the malformed row fixture",
            status=JobStatus.failed.value,
            total_rows=3,
            processed_rows=0,
            failed_rows=0,
        )
        test_db.add(job)
        test_db.flush()
        for index, row_number in enumerate(
            (0, -1, MAX_TERMINAL_ROW_NUMBER + 1),
            start=1,
        ):
            test_db.add(
                JobRow(
                    job_id=job.id,
                    row_number=row_number,
                    row_checksum=f"{index:064x}",
                    status=RowStatus.failed.value,
                    error_code="E-4001",
                    error_message="UNSAFE_MALFORMED_ROW_DETAIL",
                )
            )
        test_db.commit()

        response = client.get(f"/api/v1/jobs/{job.id}/progress")

        assert response.status_code == 200
        payload = response.json()
        assert payload["failed_rows"] == 3
        assert payload["row_failures"] == []
        assert payload["omitted_failure_count"] == 3
        assert payload["failed_rows"] == (
            len(payload["row_failures"]) + payload["omitted_failure_count"]
        )
        assert "UNSAFE_MALFORMED_ROW_DETAIL" not in response.text

    def test_progress_caps_row_diagnostics_and_reports_omitted_count(
        self, client: TestClient, test_db: Session
    ):
        job = Job(
            name="Progress cap",
            original_command="Test command",
            status=JobStatus.failed.value,
            total_rows=MAX_TERMINAL_ROW_DIAGNOSTICS + 2,
            processed_rows=MAX_TERMINAL_ROW_DIAGNOSTICS + 2,
            failed_rows=MAX_TERMINAL_ROW_DIAGNOSTICS + 2,
        )
        test_db.add(job)
        test_db.flush()
        for row_number in range(1, MAX_TERMINAL_ROW_DIAGNOSTICS + 3):
            test_db.add(
                JobRow(
                    job_id=job.id,
                    row_number=row_number,
                    row_checksum=f"{row_number:064x}",
                    status=RowStatus.failed.value,
                    error_code="E-3003",
                    error_message="recipient=Jane Doe request_body=oversized-token",
                )
            )
        test_db.commit()

        response = client.get(f"/api/v1/jobs/{job.id}/progress")

        assert response.status_code == 200
        data = response.json()
        assert len(data["row_failures"]) == MAX_TERMINAL_ROW_DIAGNOSTICS
        assert data["omitted_failure_count"] == 2
        assert data["failed_rows"] == (
            len(data["row_failures"]) + data["omitted_failure_count"]
        )
        assert "oversized-token" not in response.text

    def test_progress_completed_job(self, client: TestClient, test_db: Session):
        """Returns progress for completed job."""
        job = Job(
            name="Completed Job",
            original_command="Test command",
            status=JobStatus.completed.value,
            total_rows=10,
            processed_rows=10,
            successful_rows=10,
            failed_rows=0,
            total_cost_cents=5000,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        response = client.get(f"/api/v1/jobs/{job.id}/progress")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["processed_rows"] == data["total_rows"]


class TestProgressStream:
    """Tests for GET /api/v1/jobs/{job_id}/progress/stream SSE endpoint."""

    def test_stream_job_not_found(self, client: TestClient):
        """Returns 404 for non-existent job in SSE stream."""
        # For SSE, we need to handle the streaming response
        response = client.get("/api/v1/jobs/nonexistent-id/progress/stream")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    # The stream is open-ended by design: a sync TestClient only returns once the
    # response body completes, so a pending job would block it forever. These
    # tests drive the endpoint coroutine and its generator directly instead.

    @pytest.mark.asyncio
    async def test_stream_endpoint_returns_event_stream_response(
        self, test_db: Session, sample_job: Job
    ):
        """Endpoint returns an SSE response and subscribes the job's queue."""
        response = await stream_progress(_ConnectedRequest(), sample_job.id, db=test_db)
        try:
            assert response.status_code == 200
            assert "text/event-stream" in response.media_type
            assert sse_observer.has_subscribers(sample_job.id)
            await sse_observer.on_batch_started(sample_job.id, total_rows=5)
            await asyncio.wait_for(anext(response.body_iterator), timeout=5)
        finally:
            await response.body_iterator.aclose()

        # Closing a started stream releases the subscription (client disconnect).
        assert not sse_observer.has_subscribers(sample_job.id)

    @pytest.mark.asyncio
    async def test_stream_emits_json_message_events(
        self, test_db: Session, sample_job: Job
    ):
        """Batch events are delivered as unnamed SSE messages with a JSON body."""
        response = await stream_progress(_ConnectedRequest(), sample_job.id, db=test_db)
        try:
            await sse_observer.on_batch_started(sample_job.id, total_rows=5)
            event = await asyncio.wait_for(anext(response.body_iterator), timeout=5)
        finally:
            await response.body_iterator.aclose()

        payload = json.loads(event["data"])
        assert payload["event"] == "batch_started"
        assert payload["data"]["total_rows"] == 5
        assert "event" not in event


@pytest.mark.asyncio
async def test_sse_api_serializer_never_emits_raw_row_failure_text():
    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            return False

    job_id = "safe-sse-job"
    queue = sse_observer.subscribe(job_id)
    raw_carrier_text = "carrier response recipient=Jane Doe token=private"
    await sse_observer.on_row_failed(
        job_id,
        row_number=1,
        error_code="E-3003",
        error_message=raw_carrier_text,
    )
    generator = _event_generator(ConnectedRequest(), job_id, queue)

    event = await anext(generator)
    await generator.aclose()

    assert raw_carrier_text not in event["data"]
    assert '"diagnostic"' in event["data"]
    assert '"error_category": "ups_api"' in event["data"]
