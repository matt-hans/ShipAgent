"""Tests for needs_review and in_flight counts in job summary.

Verifies that get_job_summary() exposes:
- needs_review_count: rows in needs_review status
- in_flight_count: rows in in_flight status
- pending_count: excludes needs_review and in_flight rows
"""

from datetime import UTC
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Job, JobRow, JobStatus
from src.services.job_service import JobService


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite database with schema."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _create_job_with_rows(
    db_session,
    statuses: list[str],
) -> tuple[str, list[str]]:
    """Create a job with rows in the given statuses.

    Args:
        db_session: SQLAlchemy session.
        statuses: List of RowStatus values for each row.

    Returns:
        Tuple of (job_id, list of row_ids).
    """
    from datetime import datetime

    now = datetime.now(UTC).isoformat()
    job_id = str(uuid4())

    # Count completed and failed for processed_rows
    completed_count = statuses.count("completed")
    failed_count = statuses.count("failed")
    processed = completed_count + failed_count

    job = Job(
        id=job_id,
        name="Test Job",
        original_command="test",
        status=JobStatus.running.value,
        total_rows=len(statuses),
        processed_rows=processed,
        successful_rows=completed_count,
        failed_rows=failed_count,
        created_at=now,
        updated_at=now,
    )
    db_session.add(job)

    row_ids = []
    for i, status in enumerate(statuses, start=1):
        row_id = str(uuid4())
        row = JobRow(
            id=row_id,
            job_id=job_id,
            row_number=i,
            row_checksum=f"chk{i}",
            status=status,
        )
        db_session.add(row)
        row_ids.append(row_id)

    db_session.commit()
    return job_id, row_ids


class TestJobSummaryNeedsReview:
    """Verify needs_review_count and in_flight_count in job summary."""

    def test_summary_includes_needs_review_count(self, db_session) -> None:
        """get_job_summary() returns needs_review_count field."""
        job_id, _ = _create_job_with_rows(
            db_session,
            ["completed", "failed", "needs_review"],
        )
        svc = JobService(db_session)
        summary = svc.get_job_summary(job_id)

        assert "needs_review_count" in summary
        assert summary["needs_review_count"] == 1

    def test_summary_includes_in_flight_count(self, db_session) -> None:
        """get_job_summary() returns in_flight_count field."""
        job_id, _ = _create_job_with_rows(
            db_session,
            ["completed", "in_flight", "in_flight"],
        )
        svc = JobService(db_session)
        summary = svc.get_job_summary(job_id)

        assert "in_flight_count" in summary
        assert summary["in_flight_count"] == 2

    def test_pending_count_excludes_needs_review_and_in_flight(
        self, db_session,
    ) -> None:
        """pending_count = total - processed - needs_review - in_flight."""
        # 5 rows: 1 completed, 1 failed, 1 needs_review, 1 in_flight, 1 pending
        job_id, _ = _create_job_with_rows(
            db_session,
            ["completed", "failed", "needs_review", "in_flight", "pending"],
        )
        svc = JobService(db_session)
        summary = svc.get_job_summary(job_id)

        # total=5, processed=2 (completed+failed), needs_review=1, in_flight=1
        # pending_count = 5 - 2 - 1 - 1 = 1
        assert summary["pending_count"] == 1

    def test_zero_counts_when_no_special_statuses(self, db_session) -> None:
        """needs_review_count and in_flight_count are 0 when none exist."""
        job_id, _ = _create_job_with_rows(
            db_session,
            ["completed", "completed", "failed"],
        )
        svc = JobService(db_session)
        summary = svc.get_job_summary(job_id)

        assert summary["needs_review_count"] == 0
        assert summary["in_flight_count"] == 0

    def test_all_needs_review(self, db_session) -> None:
        """All rows in needs_review: pending_count is 0."""
        job_id, _ = _create_job_with_rows(
            db_session,
            ["needs_review", "needs_review", "needs_review"],
        )
        svc = JobService(db_session)
        summary = svc.get_job_summary(job_id)

        assert summary["needs_review_count"] == 3
        assert summary["in_flight_count"] == 0
        assert summary["pending_count"] == 0
