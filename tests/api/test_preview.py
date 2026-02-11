"""Tests for preview and confirmation endpoints.

Tests the /api/v1/jobs/{job_id}/preview and /api/v1/jobs/{job_id}/confirm
endpoints for batch preview and execution confirmation.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.models import Job, JobRow, JobStatus, RowStatus


class TestGetPreview:
    """Tests for GET /api/v1/jobs/{job_id}/preview endpoint."""

    def test_preview_job_not_found(self, client: TestClient):
        """Returns 404 for non-existent job."""
        response = client.get("/api/v1/jobs/nonexistent-id/preview")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_preview_no_rows(
        self, client: TestClient, sample_job: Job
    ):
        """Returns 400 when job has no rows."""
        response = client.get(f"/api/v1/jobs/{sample_job.id}/preview")

        assert response.status_code == 400
        assert "no rows" in response.json()["detail"].lower()

    def test_preview_returns_data(
        self, client: TestClient, job_with_rows: Job
    ):
        """Returns BatchPreviewResponse with preview data."""
        response = client.get(f"/api/v1/jobs/{job_with_rows.id}/preview")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert data["job_id"] == job_with_rows.id
        assert data["total_rows"] == 5
        assert "preview_rows" in data
        assert "total_estimated_cost_cents" in data
        assert "rows_with_warnings" in data

    def test_preview_returns_all_rows(
        self, client: TestClient, test_db: Session
    ):
        """Preview returns all rows for full scrollable display."""
        job = Job(
            name="Large Job",
            original_command="Test command",
            status=JobStatus.pending.value,
            total_rows=20,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        # Add 20 rows
        for i in range(1, 21):
            row = JobRow(
                job_id=job.id,
                row_number=i,
                row_checksum=f"checksum_{i}",
                status=RowStatus.pending.value,
                cost_cents=1000,
            )
            test_db.add(row)
        test_db.commit()

        response = client.get(f"/api/v1/jobs/{job.id}/preview")

        assert response.status_code == 200
        data = response.json()
        assert len(data["preview_rows"]) == 20
        assert data["additional_rows"] == 0

    def test_preview_row_structure(
        self, client: TestClient, job_with_rows: Job
    ):
        """Preview rows have correct structure."""
        response = client.get(f"/api/v1/jobs/{job_with_rows.id}/preview")

        assert response.status_code == 200
        data = response.json()

        # Check first preview row structure
        row = data["preview_rows"][0]
        assert "row_number" in row
        assert "recipient_name" in row
        assert "city_state" in row
        assert "service" in row
        assert "estimated_cost_cents" in row
        assert "warnings" in row
        assert isinstance(row["warnings"], list)

    def test_preview_calculates_total_cost(
        self, client: TestClient, job_with_rows: Job
    ):
        """Total estimated cost is sum of all row costs."""
        response = client.get(f"/api/v1/jobs/{job_with_rows.id}/preview")

        assert response.status_code == 200
        data = response.json()

        # Costs were 1100, 1200, 1300, 1400, 1500 (from fixture)
        expected_total = 1100 + 1200 + 1300 + 1400 + 1500
        assert data["total_estimated_cost_cents"] == expected_total


class TestConfirmJob:
    """Tests for POST /api/v1/jobs/{job_id}/confirm endpoint."""

    def test_confirm_job_not_found(self, client: TestClient):
        """Returns 404 for non-existent job."""
        response = client.post("/api/v1/jobs/nonexistent-id/confirm")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_confirm_pending_job(
        self, client: TestClient, test_db: Session, sample_job: Job
    ):
        """Confirming pending job updates status to running."""
        response = client.post(f"/api/v1/jobs/{sample_job.id}/confirm")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "confirmed"
        assert "confirmed" in data["message"].lower()

        # Verify status updated in database
        test_db.refresh(sample_job)
        assert sample_job.status == "running"

    def test_confirm_already_running(
        self, client: TestClient, test_db: Session
    ):
        """Returns 400 when job is already running."""
        job = Job(
            name="Running Job",
            original_command="Test command",
            status=JobStatus.running.value,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        response = client.post(f"/api/v1/jobs/{job.id}/confirm")

        assert response.status_code == 400
        assert "cannot be confirmed" in response.json()["detail"].lower()
        assert "running" in response.json()["detail"].lower()

    def test_confirm_completed_job(
        self, client: TestClient, test_db: Session
    ):
        """Returns 400 when job is already completed."""
        job = Job(
            name="Completed Job",
            original_command="Test command",
            status=JobStatus.completed.value,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        response = client.post(f"/api/v1/jobs/{job.id}/confirm")

        assert response.status_code == 400
        assert "cannot be confirmed" in response.json()["detail"].lower()

    def test_confirm_failed_job(
        self, client: TestClient, test_db: Session
    ):
        """Returns 400 when job has failed."""
        job = Job(
            name="Failed Job",
            original_command="Test command",
            status=JobStatus.failed.value,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        response = client.post(f"/api/v1/jobs/{job.id}/confirm")

        assert response.status_code == 400
        assert "cannot be confirmed" in response.json()["detail"].lower()

    def test_confirm_response_format(
        self, client: TestClient, sample_job: Job
    ):
        """Confirm response has correct format."""
        response = client.post(f"/api/v1/jobs/{sample_job.id}/confirm")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "message" in data
        assert data["status"] == "confirmed"
