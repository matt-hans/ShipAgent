"""Tests for durable write-back queue and worker.

Covers:
- Enqueueing write-back tasks
- Processing pending tasks
- Retry with incremented count
- Dead-letter after max retries
- Partial failure isolation (per-row independence)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.write_back_worker import (
    MAX_RETRIES,
    WriteBackTask,
    enqueue_write_back,
    process_write_back_queue,
)


def _mock_db() -> MagicMock:
    """Create a mock DB session with add/commit/query support."""
    db = MagicMock()
    db._tasks: list[WriteBackTask] = []

    def mock_add(task: WriteBackTask) -> None:
        db._tasks.append(task)

    db.add = mock_add

    def mock_query_filter(status: str = "pending") -> list[WriteBackTask]:
        return [t for t in db._tasks if t.status == status]

    db.mock_query_filter = mock_query_filter
    return db


class TestWriteBackQueue:
    """Verify enqueue and process operations."""

    def test_enqueue_creates_pending_task(self) -> None:
        """enqueue_write_back() creates a WriteBackTask with status=pending."""
        db = _mock_db()

        enqueue_write_back(
            db,
            job_id="job-abc",
            row_number=1,
            tracking_number="1Z999AA10000000001",
            shipped_at="2026-02-17T00:00:00Z",
        )

        assert len(db._tasks) == 1
        task = db._tasks[0]
        assert task.job_id == "job-abc"
        assert task.row_number == 1
        assert task.tracking_number == "1Z999AA10000000001"
        assert task.status == "pending"
        assert task.retry_count == 0
        db.commit.assert_called_once()

    def test_enqueue_multiple_tasks(self) -> None:
        """Multiple enqueue calls create independent tasks."""
        db = _mock_db()

        for i in range(1, 4):
            enqueue_write_back(
                db,
                job_id="job-abc",
                row_number=i,
                tracking_number=f"1Z{i:018d}",
                shipped_at="2026-02-17T00:00:00Z",
            )

        assert len(db._tasks) == 3
        row_numbers = {t.row_number for t in db._tasks}
        assert row_numbers == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_worker_processes_pending_tasks(self) -> None:
        """process_write_back_queue() sends tracking to gateway and marks completed."""
        gateway = AsyncMock()
        gateway.write_back_single = AsyncMock(return_value={"success": True})

        tasks = [
            WriteBackTask(
                job_id="job-abc",
                row_number=1,
                tracking_number="1Z001",
                shipped_at="2026-02-17T00:00:00Z",
            ),
            WriteBackTask(
                job_id="job-abc",
                row_number=2,
                tracking_number="1Z002",
                shipped_at="2026-02-17T00:00:00Z",
            ),
        ]

        db = MagicMock()

        result = await process_write_back_queue(db, gateway, tasks)

        assert result["processed"] == 2
        assert result["failed"] == 0
        assert result["dead_letter"] == 0
        assert tasks[0].status == "completed"
        assert tasks[1].status == "completed"

    @pytest.mark.asyncio
    async def test_worker_retries_failed_tasks(self) -> None:
        """Failed tasks stay pending with incremented retry_count."""
        gateway = AsyncMock()
        gateway.write_back_single = AsyncMock(
            side_effect=Exception("Network error"),
        )

        task = WriteBackTask(
            job_id="job-abc",
            row_number=1,
            tracking_number="1Z001",
            shipped_at="2026-02-17T00:00:00Z",
        )
        assert task.retry_count == 0

        db = MagicMock()

        result = await process_write_back_queue(db, gateway, [task])

        assert result["failed"] == 1
        assert task.retry_count == 1
        assert task.status == "pending"  # Still pending for retry

    @pytest.mark.asyncio
    async def test_worker_dead_letters_after_max_retries(self) -> None:
        """Tasks exceeding max_retries are marked as dead_letter."""
        gateway = AsyncMock()
        gateway.write_back_single = AsyncMock(
            side_effect=Exception("Persistent failure"),
        )

        task = WriteBackTask(
            job_id="job-abc",
            row_number=1,
            tracking_number="1Z001",
            shipped_at="2026-02-17T00:00:00Z",
        )
        task.retry_count = MAX_RETRIES - 1  # One more failure → dead letter

        db = MagicMock()

        result = await process_write_back_queue(db, gateway, [task])

        assert result["dead_letter"] == 1
        assert task.status == "dead_letter"
        assert task.retry_count == MAX_RETRIES

    @pytest.mark.asyncio
    async def test_partial_failure_processes_independently(self) -> None:
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

        tasks = [
            WriteBackTask(
                job_id="job-abc",
                row_number=i,
                tracking_number=f"1Z{i:03d}",
                shipped_at="2026-02-17T00:00:00Z",
            )
            for i in range(1, 4)
        ]

        db = MagicMock()

        result = await process_write_back_queue(db, gateway, tasks)

        assert result["processed"] == 2
        assert result["failed"] == 1
        assert tasks[0].status == "completed"
        assert tasks[1].status == "pending"  # Failed, still pending
        assert tasks[2].status == "completed"

    @pytest.mark.asyncio
    async def test_empty_queue_returns_zero_counts(self) -> None:
        """Processing empty queue returns all-zero counts."""
        gateway = AsyncMock()
        db = MagicMock()

        result = await process_write_back_queue(db, gateway, [])

        assert result["processed"] == 0
        assert result["failed"] == 0
        assert result["dead_letter"] == 0
