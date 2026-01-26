"""Tests for progress streaming endpoints.

Tests the /api/v1/jobs/{job_id}/progress endpoints for
SSE streaming and fallback progress retrieval.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.models import Job, JobStatus


class TestProgressFallback:
    """Tests for GET /api/v1/jobs/{job_id}/progress endpoint (non-SSE)."""

    def test_progress_job_not_found(self, client: TestClient):
        """Returns 404 for non-existent job."""
        response = client.get("/api/v1/jobs/nonexistent-id/progress")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_progress_returns_current_state(
        self, client: TestClient, test_db: Session
    ):
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

    def test_progress_pending_job(
        self, client: TestClient, sample_job: Job
    ):
        """Returns progress for pending job."""
        response = client.get(f"/api/v1/jobs/{sample_job.id}/progress")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["processed_rows"] == 0

    def test_progress_completed_job(
        self, client: TestClient, test_db: Session
    ):
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

    def test_stream_endpoint_exists(
        self, client: TestClient, sample_job: Job
    ):
        """SSE endpoint accepts connection for valid job."""
        # Start the SSE connection but close immediately
        # We can't fully test SSE with sync TestClient, but we can verify
        # the endpoint responds correctly
        response = client.get(
            f"/api/v1/jobs/{sample_job.id}/progress/stream",
            headers={"Accept": "text/event-stream"},
        )

        # Should return event stream content type
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

    def test_stream_returns_event_format(
        self, client: TestClient, sample_job: Job
    ):
        """SSE stream returns properly formatted events."""
        # Note: Full SSE testing requires async client or special handling
        # This test verifies the endpoint is configured for SSE
        response = client.get(
            f"/api/v1/jobs/{sample_job.id}/progress/stream",
            headers={"Accept": "text/event-stream"},
        )

        assert response.status_code == 200
        # EventSourceResponse should set the correct content type
        assert "text/event-stream" in response.headers.get("content-type", "")
