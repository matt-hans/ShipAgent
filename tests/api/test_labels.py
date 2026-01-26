"""Tests for label download endpoints.

Tests the /api/v1/labels endpoints for downloading individual
shipping labels and bulk ZIP downloads.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.models import Job, JobRow, JobStatus, RowStatus


class TestGetLabel:
    """Tests for GET /api/v1/labels/{tracking_number} endpoint."""

    def test_get_label_not_found(self, client: TestClient):
        """Returns 404 for non-existent tracking number."""
        response = client.get("/api/v1/labels/NONEXISTENT123")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_label_no_label_path(
        self, client: TestClient, test_db: Session, sample_job: Job
    ):
        """Returns 404 when row exists but has no label."""
        row = JobRow(
            job_id=sample_job.id,
            row_number=1,
            row_checksum="test_checksum",
            status=RowStatus.completed.value,
            tracking_number="1Z999TEST123",
            label_path=None,  # No label
        )
        test_db.add(row)
        test_db.commit()

        response = client.get("/api/v1/labels/1Z999TEST123")

        assert response.status_code == 404
        assert "no label available" in response.json()["detail"].lower()

    def test_get_label_file_missing(
        self, client: TestClient, test_db: Session, sample_job: Job
    ):
        """Returns 404 when label path exists but file is missing."""
        row = JobRow(
            job_id=sample_job.id,
            row_number=1,
            row_checksum="test_checksum",
            status=RowStatus.completed.value,
            tracking_number="1Z999TEST456",
            label_path="/nonexistent/path/label.pdf",
        )
        test_db.add(row)
        test_db.commit()

        response = client.get("/api/v1/labels/1Z999TEST456")

        assert response.status_code == 404
        assert "file not found" in response.json()["detail"].lower()

    def test_get_label_returns_pdf(
        self,
        client: TestClient,
        test_db: Session,
        sample_job: Job,
        sample_label_file: Path,
    ):
        """Returns PDF file with correct content-type."""
        row = JobRow(
            job_id=sample_job.id,
            row_number=1,
            row_checksum="test_checksum",
            status=RowStatus.completed.value,
            tracking_number="1Z999AA10012345001",
            label_path=str(sample_label_file),
        )
        test_db.add(row)
        test_db.commit()

        response = client.get("/api/v1/labels/1Z999AA10012345001")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "1Z999AA10012345001.pdf" in response.headers.get(
            "content-disposition", ""
        )
        # Verify content is the PDF
        assert response.content.startswith(b"%PDF")


class TestDownloadLabelsZip:
    """Tests for GET /api/v1/jobs/{job_id}/labels/zip endpoint."""

    def test_get_labels_zip_job_not_found(self, client: TestClient):
        """Returns 404 for non-existent job."""
        response = client.get("/api/v1/jobs/nonexistent-job-id/labels/zip")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_labels_zip_no_labels(
        self, client: TestClient, test_db: Session, sample_job: Job
    ):
        """Returns 404 when job has no labels."""
        response = client.get(f"/api/v1/jobs/{sample_job.id}/labels/zip")

        assert response.status_code == 404
        assert "no labels available" in response.json()["detail"].lower()

    def test_get_labels_zip_returns_zip(
        self,
        client: TestClient,
        test_db: Session,
        sample_job: Job,
        temp_label_dir: Path,
    ):
        """Returns ZIP file with correct content-type."""
        # Create label files and rows
        for i in range(1, 3):
            label_path = temp_label_dir / f"1Z999TEST{i:03d}.pdf"
            label_path.write_bytes(b"%PDF-1.4\nLabel content\n%%EOF")

            row = JobRow(
                job_id=sample_job.id,
                row_number=i,
                row_checksum=f"checksum_{i}",
                status=RowStatus.completed.value,
                tracking_number=f"1Z999TEST{i:03d}",
                label_path=str(label_path),
            )
            test_db.add(row)

        test_db.commit()

        response = client.get(f"/api/v1/jobs/{sample_job.id}/labels/zip")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert "attachment" in response.headers.get("content-disposition", "")
        # ZIP files start with PK
        assert response.content[:2] == b"PK"

    def test_get_labels_zip_skips_missing_files(
        self,
        client: TestClient,
        test_db: Session,
        sample_job: Job,
        temp_label_dir: Path,
    ):
        """ZIP excludes rows with missing label files."""
        # Create one valid label
        valid_path = temp_label_dir / "1Z999VALID001.pdf"
        valid_path.write_bytes(b"%PDF-1.4\nValid label\n%%EOF")

        # Row with valid label
        row1 = JobRow(
            job_id=sample_job.id,
            row_number=1,
            row_checksum="checksum_1",
            status=RowStatus.completed.value,
            tracking_number="1Z999VALID001",
            label_path=str(valid_path),
        )
        test_db.add(row1)

        # Row with missing label file
        row2 = JobRow(
            job_id=sample_job.id,
            row_number=2,
            row_checksum="checksum_2",
            status=RowStatus.completed.value,
            tracking_number="1Z999INVALID",
            label_path="/nonexistent/label.pdf",
        )
        test_db.add(row2)
        test_db.commit()

        response = client.get(f"/api/v1/jobs/{sample_job.id}/labels/zip")

        # Should still return ZIP with the valid file
        assert response.status_code == 200
        assert response.content[:2] == b"PK"

    def test_get_labels_zip_all_files_missing(
        self,
        client: TestClient,
        test_db: Session,
        sample_job: Job,
    ):
        """Returns 404 when all label files are missing."""
        row = JobRow(
            job_id=sample_job.id,
            row_number=1,
            row_checksum="checksum_1",
            status=RowStatus.completed.value,
            tracking_number="1Z999MISSING",
            label_path="/nonexistent/label.pdf",
        )
        test_db.add(row)
        test_db.commit()

        response = client.get(f"/api/v1/jobs/{sample_job.id}/labels/zip")

        assert response.status_code == 404
        assert "no valid label files" in response.json()["detail"].lower()
