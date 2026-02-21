"""Tests for label staging directory with atomic promote."""

import base64
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.services.batch_engine import BatchEngine


@pytest.fixture()
def engine(tmp_path: Path) -> BatchEngine:
    """Create BatchEngine with temp labels directory."""
    return BatchEngine(
        ups_service=MagicMock(),
        db_session=MagicMock(),
        account_number="TEST",
        labels_dir=str(tmp_path / "labels"),
    )


@pytest.fixture()
def sample_label_b64() -> str:
    """Base64-encoded sample PDF content."""
    return base64.b64encode(b"%PDF-1.4 sample label content").decode()


class TestLabelStaging:
    """Verify label staging, promote, and cleanup behavior."""

    def test_save_label_staged_writes_to_staging_dir(
        self, engine: BatchEngine, sample_label_b64: str, tmp_path: Path,
    ) -> None:
        """Label is saved to labels/staging/{job_id}/, not final path."""
        path = engine._save_label_staged(
            "1Z999", sample_label_b64, job_id="job-abc", row_number=1,
        )
        assert "/staging/" in path
        assert "job-abc" in path
        assert os.path.exists(path)
        # Verify it's NOT in the final labels dir root
        assert not (tmp_path / "labels" / Path(path).name).exists()

    def test_promote_label_moves_to_final_path(
        self, engine: BatchEngine, sample_label_b64: str,
    ) -> None:
        """After promote, label exists at final path and staging file is gone."""
        staging_path = engine._save_label_staged(
            "1Z999", sample_label_b64, job_id="job-abc", row_number=1,
        )
        assert os.path.exists(staging_path)

        final_path = engine._promote_label(staging_path)
        assert os.path.exists(final_path)
        assert not os.path.exists(staging_path)
        assert "/staging/" not in final_path

    def test_promote_label_preserves_content(
        self, engine: BatchEngine, sample_label_b64: str,
    ) -> None:
        """Promoted label has same content as staged."""
        staging_path = engine._save_label_staged(
            "1Z999", sample_label_b64, job_id="job-abc", row_number=1,
        )
        original_content = Path(staging_path).read_bytes()

        final_path = engine._promote_label(staging_path)
        assert Path(final_path).read_bytes() == original_content

    def test_crash_before_promote_leaves_orphan_in_staging(
        self, engine: BatchEngine, sample_label_b64: str,
    ) -> None:
        """If promote never runs, staging file exists but final path does not."""
        staging_path = engine._save_label_staged(
            "1Z999", sample_label_b64, job_id="job-abc", row_number=1,
        )
        # Simulate crash: never call _promote_label
        assert os.path.exists(staging_path)
        labels_root = Path(engine._labels_dir)
        # No file in root labels dir
        root_files = list(labels_root.glob("*.pdf"))
        assert len(root_files) == 0

    def test_cleanup_staging_removes_orphans_for_completed_jobs(
        self, engine: BatchEngine, sample_label_b64: str, tmp_path: Path,
    ) -> None:
        """cleanup_staging removes staging dirs for jobs with no unresolved rows."""
        # Create a staged label
        engine._save_label_staged(
            "1Z999", sample_label_b64, job_id="completed-job", row_number=1,
        )
        staging_dir = Path(engine._labels_dir) / "staging" / "completed-job"
        assert staging_dir.exists()

        # Mock DB: job has no in_flight or needs_review rows
        MagicMock()
        mock_row = MagicMock()
        mock_row.status = "completed"
        mock_js = MagicMock()
        mock_js.get_rows.return_value = [mock_row]

        count = BatchEngine.cleanup_staging(
            mock_js, labels_dir=str(tmp_path / "labels"),
        )
        assert count == 1
        assert not staging_dir.exists()

    def test_cleanup_staging_skips_jobs_with_in_flight_rows(
        self, engine: BatchEngine, sample_label_b64: str, tmp_path: Path,
    ) -> None:
        """cleanup_staging does NOT delete staging files for jobs with in_flight rows."""
        engine._save_label_staged(
            "1Z999", sample_label_b64, job_id="inflight-job", row_number=1,
        )
        staging_dir = Path(engine._labels_dir) / "staging" / "inflight-job"
        assert staging_dir.exists()

        # Mock DB: job has an in_flight row
        mock_row = MagicMock()
        mock_row.status = "in_flight"
        mock_js = MagicMock()
        mock_js.get_rows.return_value = [mock_row]

        count = BatchEngine.cleanup_staging(
            mock_js, labels_dir=str(tmp_path / "labels"),
        )
        assert count == 0
        assert staging_dir.exists()

    def test_cleanup_staging_skips_jobs_with_needs_review_rows(
        self, engine: BatchEngine, sample_label_b64: str, tmp_path: Path,
    ) -> None:
        """cleanup_staging preserves staging files for needs_review rows."""
        engine._save_label_staged(
            "1Z999", sample_label_b64, job_id="review-job", row_number=1,
        )
        staging_dir = Path(engine._labels_dir) / "staging" / "review-job"
        assert staging_dir.exists()

        mock_row = MagicMock()
        mock_row.status = "needs_review"
        mock_js = MagicMock()
        mock_js.get_rows.return_value = [mock_row]

        count = BatchEngine.cleanup_staging(
            mock_js, labels_dir=str(tmp_path / "labels"),
        )
        assert count == 0
        assert staging_dir.exists()

    def test_cleanup_staging_returns_zero_when_no_staging_dir(
        self, tmp_path: Path,
    ) -> None:
        """cleanup_staging returns 0 when staging directory doesn't exist."""
        mock_js = MagicMock()
        count = BatchEngine.cleanup_staging(
            mock_js, labels_dir=str(tmp_path / "nonexistent"),
        )
        assert count == 0
