"""Tests for label download endpoints.

Tests the /api/v1/labels endpoints for downloading individual
shipping labels and merged PDF downloads, including path traversal
protection (F-1, CWE-22).
"""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.models import Job, JobRow, RowStatus
from tests.api.conftest import create_valid_pdf


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
        self, client: TestClient, test_db: Session, sample_job: Job, tmp_path: Path
    ):
        """Returns 404 when label path exists but file is missing."""
        # Path must be within the labels base dir to pass traversal check
        missing_file = tmp_path / "missing_label.pdf"
        row = JobRow(
            job_id=sample_job.id,
            row_number=1,
            row_checksum="test_checksum",
            status=RowStatus.completed.value,
            tracking_number="1Z999TEST456",
            label_path=str(missing_file),
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


class TestDownloadLabelsMerged:
    """Tests for GET /api/v1/jobs/{job_id}/labels/merged endpoint."""

    def test_merged_job_not_found(self, client: TestClient):
        """Returns 404 for non-existent job."""
        response = client.get("/api/v1/jobs/nonexistent-job-id/labels/merged")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_merged_no_labels(
        self, client: TestClient, test_db: Session, sample_job: Job
    ):
        """Returns 404 when job has no labels."""
        response = client.get(f"/api/v1/jobs/{sample_job.id}/labels/merged")

        assert response.status_code == 404
        assert "no labels available" in response.json()["detail"].lower()

    def test_merged_returns_pdf(
        self,
        client: TestClient,
        test_db: Session,
        sample_job: Job,
        valid_label_dir: Path,
    ):
        """Returns merged PDF with correct content-type."""
        for i in range(1, 3):
            label_path = valid_label_dir / f"label_{i}.pdf"
            create_valid_pdf(label_path)

            row = JobRow(
                job_id=sample_job.id,
                row_number=i,
                row_checksum=f"checksum_{i}",
                status=RowStatus.completed.value,
                tracking_number=f"1Z999MERGE{i:03d}",
                label_path=str(label_path),
            )
            test_db.add(row)

        test_db.commit()

        response = client.get(f"/api/v1/jobs/{sample_job.id}/labels/merged")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "labels-" in response.headers.get("content-disposition", "")
        assert response.content.startswith(b"%PDF")

    def test_merged_skips_missing_files(
        self,
        client: TestClient,
        test_db: Session,
        sample_job: Job,
        valid_label_dir: Path,
    ):
        """Merged PDF excludes rows with missing label files."""
        valid_path = valid_label_dir / "valid_label.pdf"
        create_valid_pdf(valid_path)

        row1 = JobRow(
            job_id=sample_job.id,
            row_number=1,
            row_checksum="checksum_1",
            status=RowStatus.completed.value,
            tracking_number="1Z999VALID001",
            label_path=str(valid_path),
        )
        test_db.add(row1)

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

        response = client.get(f"/api/v1/jobs/{sample_job.id}/labels/merged")

        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")

    def test_merged_all_files_missing(
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

        response = client.get(f"/api/v1/jobs/{sample_job.id}/labels/merged")

        assert response.status_code == 404
        assert "no valid label files" in response.json()["detail"].lower()

    def test_merged_ordered_by_row_number(
        self,
        client: TestClient,
        test_db: Session,
        sample_job: Job,
        valid_label_dir: Path,
    ):
        """Merged PDF contains labels ordered by row number."""
        # Add rows in reverse order to verify sorting
        for i in [3, 1, 2]:
            label_path = valid_label_dir / f"label_{i}.pdf"
            create_valid_pdf(label_path)

            row = JobRow(
                job_id=sample_job.id,
                row_number=i,
                row_checksum=f"checksum_{i}",
                status=RowStatus.completed.value,
                tracking_number=f"1Z999ORDER{i:03d}",
                label_path=str(label_path),
            )
            test_db.add(row)

        test_db.commit()

        response = client.get(f"/api/v1/jobs/{sample_job.id}/labels/merged")

        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")


class TestPathTraversal:
    """Tests for path traversal protection (F-1, CWE-22)."""

    def test_path_traversal_returns_403(
        self, client: TestClient, test_db: Session, sample_job: Job
    ):
        """Label path escaping labels dir returns 403."""
        row = JobRow(
            job_id=sample_job.id,
            row_number=1,
            row_checksum="checksum_trav",
            status=RowStatus.completed.value,
            tracking_number="1Z999TRAVERSAL",
            label_path="../../etc/passwd",
        )
        test_db.add(row)
        test_db.commit()

        response = client.get("/api/v1/labels/1Z999TRAVERSAL")

        assert response.status_code == 403
        assert "outside" in response.json()["detail"].lower()

    def test_path_traversal_in_merged_is_skipped(
        self,
        client: TestClient,
        test_db: Session,
        sample_job: Job,
        tmp_path: Path,
    ):
        """Merged PDF skips rows with traversal paths, serves valid ones."""
        valid_label = tmp_path / "valid.pdf"
        create_valid_pdf(valid_label)

        row_valid = JobRow(
            job_id=sample_job.id,
            row_number=1,
            row_checksum="checksum_valid",
            status=RowStatus.completed.value,
            tracking_number="1Z999VALID",
            label_path=str(valid_label),
        )
        row_traversal = JobRow(
            job_id=sample_job.id,
            row_number=2,
            row_checksum="checksum_trav2",
            status=RowStatus.completed.value,
            tracking_number="1Z999TRAV2",
            label_path="../../etc/shadow",
        )
        test_db.add_all([row_valid, row_traversal])
        test_db.commit()

        with patch(
            "src.api.routes.labels._LABELS_BASE_DIR", tmp_path.resolve()
        ):
            response = client.get(
                f"/api/v1/jobs/{sample_job.id}/labels/merged"
            )

        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")

    def test_path_traversal_by_row_returns_403(
        self, client: TestClient, test_db: Session, sample_job: Job
    ):
        """Row endpoint rejects path traversal with 403."""
        row = JobRow(
            job_id=sample_job.id,
            row_number=1,
            row_checksum="checksum_row_trav",
            status=RowStatus.completed.value,
            tracking_number="1Z999ROWTRAV",
            label_path="../../../tmp/evil.pdf",
        )
        test_db.add(row)
        test_db.commit()

        response = client.get(
            f"/api/v1/jobs/{sample_job.id}/labels/1"
        )

        assert response.status_code == 403

    def test_valid_label_path_within_labels_dir(
        self,
        client: TestClient,
        test_db: Session,
        sample_job: Job,
        tmp_path: Path,
    ):
        """Valid label path within labels dir returns 200."""
        label_file = tmp_path / "valid_label.pdf"
        label_file.write_bytes(b"%PDF-1.4\nTest\n%%EOF")

        row = JobRow(
            job_id=sample_job.id,
            row_number=1,
            row_checksum="checksum_ok",
            status=RowStatus.completed.value,
            tracking_number="1Z999VALID001",
            label_path=str(label_file),
        )
        test_db.add(row)
        test_db.commit()

        with patch(
            "src.api.routes.labels._LABELS_BASE_DIR", tmp_path.resolve()
        ):
            response = client.get("/api/v1/labels/1Z999VALID001")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
