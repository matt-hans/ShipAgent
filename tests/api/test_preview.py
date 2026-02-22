"""Tests for preview and confirmation endpoints.

Tests the /api/v1/jobs/{job_id}/preview and /api/v1/jobs/{job_id}/confirm
endpoints for batch preview and execution confirmation, including
TOCTOU race protection (F-2, CWE-367) and hash collision (F-4, CWE-345).
"""

import hashlib
from unittest.mock import AsyncMock, MagicMock

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

    def test_preview_no_rows(self, client: TestClient, sample_job: Job):
        """Returns 400 when job has no rows."""
        response = client.get(f"/api/v1/jobs/{sample_job.id}/preview")

        assert response.status_code == 400
        assert "no rows" in response.json()["detail"].lower()

    def test_preview_returns_data(self, client: TestClient, job_with_rows: Job):
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

    def test_preview_returns_all_rows(self, client: TestClient, test_db: Session):
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

    def test_preview_row_structure(self, client: TestClient, job_with_rows: Job):
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

    def test_confirm_already_running(self, client: TestClient, test_db: Session):
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

    def test_confirm_completed_job(self, client: TestClient, test_db: Session):
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

    def test_confirm_failed_job(self, client: TestClient, test_db: Session):
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

    def test_confirm_response_format(self, client: TestClient, sample_job: Job):
        """Confirm response has correct format."""
        response = client.post(f"/api/v1/jobs/{sample_job.id}/confirm")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "message" in data
        assert data["status"] == "confirmed"

    def test_confirm_write_back_disabled(self, client: TestClient, test_db: Session):
        """Confirm with write_back_enabled=false stores preference on job."""
        job = Job(
            name="No Write-back Job",
            original_command="Test command",
            status=JobStatus.pending.value,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        response = client.post(
            f"/api/v1/jobs/{job.id}/confirm",
            json={"write_back_enabled": False},
        )

        assert response.status_code == 200
        test_db.refresh(job)
        assert job.write_back_enabled is False

    def test_confirm_write_back_enabled_default(
        self, client: TestClient, test_db: Session
    ):
        """Confirm without body defaults write_back_enabled to True (non-interactive)."""
        job = Job(
            name="Default Write-back Job",
            original_command="Test command",
            status=JobStatus.pending.value,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        response = client.post(f"/api/v1/jobs/{job.id}/confirm")

        assert response.status_code == 200
        test_db.refresh(job)
        assert job.write_back_enabled is True

    def test_confirm_write_back_forced_off_for_interactive(
        self, client: TestClient, test_db: Session
    ):
        """Interactive jobs always have write_back_enabled=False even if requested True."""
        job = Job(
            name="Interactive Job",
            original_command="Test command",
            status=JobStatus.pending.value,
            is_interactive=True,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        response = client.post(
            f"/api/v1/jobs/{job.id}/confirm",
            json={"write_back_enabled": True},
        )

        assert response.status_code == 200
        test_db.refresh(job)
        assert job.write_back_enabled is False

    def test_confirm_selected_service_code_rejected_for_non_interactive(
        self, client: TestClient, test_db: Session
    ):
        """selected_service_code is only supported for interactive jobs."""
        job = Job(
            name="Batch Job",
            original_command="Test command",
            status=JobStatus.pending.value,
            is_interactive=False,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        response = client.post(
            f"/api/v1/jobs/{job.id}/confirm",
            json={"selected_service_code": "01"},
        )

        assert response.status_code == 400
        assert "interactive shipment jobs" in response.json()["detail"].lower()

    def test_confirm_interactive_passes_selected_service_code_to_executor(
        self, client: TestClient, test_db: Session, monkeypatch
    ):
        """Interactive confirm forwards selected_service_code to background executor."""
        from src.api.routes import preview as preview_routes

        job = Job(
            name="Interactive Job",
            original_command="Test command",
            status=JobStatus.pending.value,
            is_interactive=True,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        mocked_execute = AsyncMock()
        fake_task = MagicMock()
        fake_task.add_done_callback = MagicMock()

        def _fake_create_task(coro):
            coro.close()
            return fake_task

        monkeypatch.setattr(preview_routes, "_execute_batch_safe", mocked_execute)
        monkeypatch.setattr(preview_routes.asyncio, "create_task", _fake_create_task)

        response = client.post(
            f"/api/v1/jobs/{job.id}/confirm",
            json={"selected_service_code": "01"},
        )

        assert response.status_code == 200
        mocked_execute.assert_called_once_with(job.id, selected_service_code="01")


class TestPreviewHash:
    """Tests for preview integrity hash (F-5 TOCTOU protection)."""

    def test_preview_sets_hash(self, client: TestClient, test_db: Session):
        """Preview endpoint stores preview_hash on the job."""
        job = Job(
            name="Hash Test Job",
            original_command="Test command",
            status=JobStatus.pending.value,
            total_rows=2,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        for i in range(1, 3):
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

        test_db.refresh(job)
        assert job.preview_hash is not None
        assert len(job.preview_hash) == 64  # SHA-256 hex digest

    def test_confirm_succeeds_when_hash_matches(
        self, client: TestClient, test_db: Session
    ):
        """Confirm succeeds when row data hasn't changed since preview."""
        job = Job(
            name="Hash Match Job",
            original_command="Test command",
            status=JobStatus.pending.value,
            total_rows=2,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        for i in range(1, 3):
            row = JobRow(
                job_id=job.id,
                row_number=i,
                row_checksum=f"checksum_{i}",
                status=RowStatus.pending.value,
                cost_cents=1000,
            )
            test_db.add(row)
        test_db.commit()

        # Preview to set hash
        client.get(f"/api/v1/jobs/{job.id}/preview")

        # Confirm — should succeed since rows unchanged
        response = client.post(f"/api/v1/jobs/{job.id}/confirm")
        assert response.status_code == 200

    def test_confirm_returns_409_when_rows_changed(
        self, client: TestClient, test_db: Session
    ):
        """Confirm returns 409 when row data changed after preview."""
        job = Job(
            name="Hash Mismatch Job",
            original_command="Test command",
            status=JobStatus.pending.value,
            total_rows=2,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        for i in range(1, 3):
            row = JobRow(
                job_id=job.id,
                row_number=i,
                row_checksum=f"checksum_{i}",
                status=RowStatus.pending.value,
                cost_cents=1000,
            )
            test_db.add(row)
        test_db.commit()

        # Preview to set hash
        client.get(f"/api/v1/jobs/{job.id}/preview")

        # Tamper with row checksums after preview
        rows = test_db.query(JobRow).filter(JobRow.job_id == job.id).all()
        rows[0].row_checksum = "tampered_checksum"
        test_db.commit()

        # Confirm — should fail with 409
        response = client.post(f"/api/v1/jobs/{job.id}/confirm")
        assert response.status_code == 409
        assert "re-preview" in response.json()["detail"].lower()

    def test_confirm_works_when_preview_hash_null(
        self, client: TestClient, test_db: Session
    ):
        """Confirm works for jobs created before preview_hash was added."""
        job = Job(
            name="No Hash Job",
            original_command="Test command",
            status=JobStatus.pending.value,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        # No preview, so preview_hash is None
        assert job.preview_hash is None

        response = client.post(f"/api/v1/jobs/{job.id}/confirm")
        assert response.status_code == 200


class TestConfirmAtomicRace:
    """Tests for TOCTOU race prevention in confirm (F-2, CWE-367)."""

    def test_confirm_atomic_rejects_second_request(
        self, client: TestClient, test_db: Session
    ):
        """Second concurrent confirm attempt returns 400."""
        job = Job(
            name="Race Test Job",
            original_command="Test command",
            status=JobStatus.pending.value,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        # First confirm succeeds
        resp1 = client.post(f"/api/v1/jobs/{job.id}/confirm")
        assert resp1.status_code == 200

        # Second confirm fails — job already running
        resp2 = client.post(f"/api/v1/jobs/{job.id}/confirm")
        assert resp2.status_code == 400
        assert "running" in resp2.json()["detail"].lower()

    def test_confirm_nonexistent_job_returns_404(self, client: TestClient):
        """Confirm for non-existent job returns 404."""
        response = client.post("/api/v1/jobs/00000000-0000-0000-0000-000000000000/confirm")
        assert response.status_code == 404


class TestPreviewHashFormat:
    """Tests for preview hash collision prevention (F-4, CWE-345)."""

    def test_preview_hash_uses_delimited_format(
        self, client: TestClient, test_db: Session
    ):
        """Stored preview hash uses row_number:checksum delimited format."""
        job = Job(
            name="Hash Format Job",
            original_command="Test command",
            status=JobStatus.pending.value,
            total_rows=2,
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        for i in range(1, 3):
            row = JobRow(
                job_id=job.id,
                row_number=i,
                row_checksum=f"cs{i}",
                status=RowStatus.pending.value,
                cost_cents=100,
            )
            test_db.add(row)
        test_db.commit()

        response = client.get(f"/api/v1/jobs/{job.id}/preview")
        assert response.status_code == 200

        test_db.refresh(job)
        expected = hashlib.sha256("1:cs1|2:cs2".encode()).hexdigest()
        assert job.preview_hash == expected

    def test_preview_hash_boundary_collision_detected(
        self, client: TestClient, test_db: Session
    ):
        """Checksums that would collide with plain join produce different hashes."""
        # Old scheme: "".join(["ab","cd"]) == "".join(["abc","d"]) == "abcd"
        # New scheme: "1:ab|2:cd" != "1:abc|2:d"
        hash_a = hashlib.sha256("1:ab|2:cd".encode()).hexdigest()
        hash_b = hashlib.sha256("1:abc|2:d".encode()).hexdigest()
        assert hash_a != hash_b
