"""Tests for durable write-back queue and worker.

Covers:
- Enqueueing write-back tasks (persisted to DB)
- Querying pending tasks
- Processing pending tasks
- Retry with incremented count
- Dead-letter after max retries
- Partial failure isolation (per-row independence)
- Marking tasks completed after bulk write-back
"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, Job, WriteBackTask
from src.services.write_back_worker import (
    MAX_RETRIES,
    enqueue_write_back,
    get_pending_tasks,
    mark_tasks_completed,
    process_write_back_queue,
)


@pytest.fixture
def db_session():
    """Create an in-memory SQLite DB with write_back_tasks table."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Create a parent job (FK constraint)
    job = Job(id="job-abc", name="Test Job", original_command="ship all", status="running")
    session.add(job)
    session.commit()

    yield session
    session.close()


class TestWriteBackQueue:
    """Verify enqueue and process operations."""

    def test_enqueue_creates_pending_task(self, db_session: Session) -> None:
        """enqueue_write_back() creates a WriteBackTask with status=pending."""
        task = enqueue_write_back(
            db_session,
            job_id="job-abc",
            row_number=1,
            tracking_number="1Z999AA10000000001",
            shipped_at="2026-02-17T00:00:00Z",
        )

        assert task.job_id == "job-abc"
        assert task.row_number == 1
        assert task.tracking_number == "1Z999AA10000000001"
        assert task.status == "pending"
        assert task.retry_count == 0
        assert task.id is not None  # UUID assigned

        # Verify persisted in DB
        from_db = db_session.query(WriteBackTask).filter_by(id=task.id).first()
        assert from_db is not None
        assert from_db.tracking_number == "1Z999AA10000000001"

    def test_enqueue_multiple_tasks(self, db_session: Session) -> None:
        """Multiple enqueue calls create independent tasks."""
        for i in range(1, 4):
            enqueue_write_back(
                db_session,
                job_id="job-abc",
                row_number=i,
                tracking_number=f"1Z{i:018d}",
                shipped_at="2026-02-17T00:00:00Z",
            )

        all_tasks = db_session.query(WriteBackTask).all()
        assert len(all_tasks) == 3
        row_numbers = {t.row_number for t in all_tasks}
        assert row_numbers == {1, 2, 3}

    def test_get_pending_tasks(self, db_session: Session) -> None:
        """get_pending_tasks returns only pending tasks."""
        enqueue_write_back(db_session, "job-abc", 1, "1Z001", "2026-02-17T00:00:00Z")
        enqueue_write_back(db_session, "job-abc", 2, "1Z002", "2026-02-17T00:00:00Z")

        # Mark one as completed
        tasks = db_session.query(WriteBackTask).all()
        tasks[0].status = "completed"
        db_session.commit()

        pending = get_pending_tasks(db_session)
        assert len(pending) == 1
        assert pending[0].row_number == 2

    def test_get_pending_tasks_by_job(self, db_session: Session) -> None:
        """get_pending_tasks filters by job_id."""
        # Create a second job
        job2 = Job(id="job-def", name="Job 2", original_command="ship CA", status="running")
        db_session.add(job2)
        db_session.commit()

        enqueue_write_back(db_session, "job-abc", 1, "1Z001", "2026-02-17T00:00:00Z")
        enqueue_write_back(db_session, "job-def", 1, "1Z002", "2026-02-17T00:00:00Z")

        pending_abc = get_pending_tasks(db_session, job_id="job-abc")
        assert len(pending_abc) == 1
        assert pending_abc[0].job_id == "job-abc"

    def test_mark_tasks_completed(self, db_session: Session) -> None:
        """mark_tasks_completed marks all pending tasks for a job."""
        enqueue_write_back(db_session, "job-abc", 1, "1Z001", "2026-02-17T00:00:00Z")
        enqueue_write_back(db_session, "job-abc", 2, "1Z002", "2026-02-17T00:00:00Z")

        count = mark_tasks_completed(db_session, "job-abc")
        assert count == 2

        pending = get_pending_tasks(db_session, job_id="job-abc")
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_worker_processes_pending_tasks(self, db_session: Session) -> None:
        """process_write_back_queue() sends tracking to gateway and marks completed."""
        gateway = AsyncMock()
        gateway.write_back_single = AsyncMock(return_value={"success": True})

        enqueue_write_back(db_session, "job-abc", 1, "1Z001", "2026-02-17T00:00:00Z")
        enqueue_write_back(db_session, "job-abc", 2, "1Z002", "2026-02-17T00:00:00Z")

        tasks = get_pending_tasks(db_session, job_id="job-abc")
        result = await process_write_back_queue(db_session, gateway, tasks)

        assert result["processed"] == 2
        assert result["failed"] == 0
        assert result["dead_letter"] == 0
        assert tasks[0].status == "completed"
        assert tasks[1].status == "completed"

    @pytest.mark.asyncio
    async def test_worker_retries_failed_tasks(self, db_session: Session) -> None:
        """Failed tasks stay pending with incremented retry_count."""
        gateway = AsyncMock()
        gateway.write_back_single = AsyncMock(
            side_effect=Exception("Network error"),
        )

        enqueue_write_back(db_session, "job-abc", 1, "1Z001", "2026-02-17T00:00:00Z")

        tasks = get_pending_tasks(db_session, job_id="job-abc")
        result = await process_write_back_queue(db_session, gateway, tasks)

        assert result["failed"] == 1
        assert tasks[0].retry_count == 1
        assert tasks[0].status == "pending"  # Still pending for retry

    @pytest.mark.asyncio
    async def test_worker_dead_letters_after_max_retries(self, db_session: Session) -> None:
        """Tasks exceeding max_retries are marked as dead_letter."""
        gateway = AsyncMock()
        gateway.write_back_single = AsyncMock(
            side_effect=Exception("Persistent failure"),
        )

        enqueue_write_back(db_session, "job-abc", 1, "1Z001", "2026-02-17T00:00:00Z")

        tasks = get_pending_tasks(db_session, job_id="job-abc")
        tasks[0].retry_count = MAX_RETRIES - 1  # One more failure → dead letter
        db_session.commit()

        result = await process_write_back_queue(db_session, gateway, tasks)

        assert result["dead_letter"] == 1
        assert tasks[0].status == "dead_letter"
        assert tasks[0].retry_count == MAX_RETRIES

    @pytest.mark.asyncio
    async def test_partial_failure_processes_independently(self, db_session: Session) -> None:
        """If row 2 fails, rows 1 and 3 still succeed."""
        call_count = 0

        async def selective_fail(**kwargs: object) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Row 2 failed")
            return {"success": True}

        gateway = AsyncMock()
        gateway.write_back_single = selective_fail

        for i in range(1, 4):
            enqueue_write_back(db_session, "job-abc", i, f"1Z{i:03d}", "2026-02-17T00:00:00Z")

        tasks = get_pending_tasks(db_session, job_id="job-abc")
        result = await process_write_back_queue(db_session, gateway, tasks)

        assert result["processed"] == 2
        assert result["failed"] == 1
        assert tasks[0].status == "completed"
        assert tasks[1].status == "pending"  # Failed, still pending
        assert tasks[2].status == "completed"

    @pytest.mark.asyncio
    async def test_empty_queue_returns_zero_counts(self, db_session: Session) -> None:
        """Processing empty queue returns all-zero counts."""
        gateway = AsyncMock()

        result = await process_write_back_queue(db_session, gateway, [])

        assert result["processed"] == 0
        assert result["failed"] == 0
        assert result["dead_letter"] == 0
