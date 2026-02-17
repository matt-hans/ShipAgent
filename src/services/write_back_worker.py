"""Durable write-back worker for tracking number persistence.

Provides a queue-based approach to writing tracking numbers back to data
sources. Each successful shipment enqueues a WriteBackTask (ORM model);
the worker processes them with per-task retry and dead-letter semantics.

Tasks are DB-persisted, so they survive process crashes. On restart,
any pending tasks can be drained via process_write_back_queue().
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import WriteBackTask

logger = logging.getLogger(__name__)

# Maximum retry attempts before moving to dead letter
MAX_RETRIES = 3


def enqueue_write_back(
    db: Session,
    job_id: str,
    row_number: int,
    tracking_number: str,
    shipped_at: str,
) -> WriteBackTask:
    """Add a write-back task to the durable queue.

    Args:
        db: Database session for persistence.
        job_id: Job UUID.
        row_number: 1-based row number.
        tracking_number: UPS tracking number.
        shipped_at: ISO8601 timestamp.

    Returns:
        The created WriteBackTask ORM instance.
    """
    task = WriteBackTask(
        job_id=job_id,
        row_number=row_number,
        tracking_number=tracking_number,
        shipped_at=shipped_at,
        status="pending",
        retry_count=0,
    )
    db.add(task)
    db.commit()
    return task


def get_pending_tasks(db: Session, job_id: str | None = None) -> list[WriteBackTask]:
    """Query pending write-back tasks from the database.

    Args:
        db: Database session.
        job_id: Optional filter to get tasks for a specific job.

    Returns:
        List of WriteBackTask instances with status='pending'.
    """
    query = db.query(WriteBackTask).filter(WriteBackTask.status == "pending")
    if job_id is not None:
        query = query.filter(WriteBackTask.job_id == job_id)
    return query.all()


def mark_tasks_completed(db: Session, job_id: str) -> int:
    """Mark all pending write-back tasks for a job as completed.

    Used after successful bulk write-back to clear the queue.

    Args:
        db: Database session.
        job_id: Job UUID.

    Returns:
        Number of tasks marked completed.
    """
    count = (
        db.query(WriteBackTask)
        .filter(WriteBackTask.job_id == job_id, WriteBackTask.status == "pending")
        .update({"status": "completed"})
    )
    db.commit()
    return count


def mark_rows_completed(db: Session, job_id: str, row_numbers: list[int]) -> int:
    """Mark specific write-back tasks as completed by row number.

    Used after partial write-back success to mark only the rows that
    were written successfully, leaving failed rows as pending for retry.

    Args:
        db: Database session.
        job_id: Job UUID.
        row_numbers: List of 1-based row numbers to mark completed.

    Returns:
        Number of tasks marked completed.
    """
    if not row_numbers:
        return 0
    count = (
        db.query(WriteBackTask)
        .filter(
            WriteBackTask.job_id == job_id,
            WriteBackTask.status == "pending",
            WriteBackTask.row_number.in_(row_numbers),
        )
        .update({"status": "completed"}, synchronize_session="fetch")
    )
    db.commit()
    return count


async def process_write_back_queue(
    db: Session,
    gateway: Any,
    tasks: list[WriteBackTask],
) -> dict[str, int]:
    """Process pending write-back tasks.

    Each task is processed independently — a failure in one task does
    not affect others. Failed tasks have their retry_count incremented;
    tasks exceeding MAX_RETRIES are moved to dead_letter status.

    Args:
        db: Database session for state updates.
        gateway: Data source gateway with write_back_single() method.
        tasks: List of WriteBackTask instances to process.

    Returns:
        Dict with processed, failed, and dead_letter counts.
    """
    processed = 0
    failed = 0
    dead_letter = 0

    for task in tasks:
        try:
            await gateway.write_back_single(
                row_number=task.row_number,
                tracking_number=task.tracking_number,
                shipped_at=task.shipped_at,
            )
            task.status = "completed"
            processed += 1
        except Exception as e:
            task.retry_count = (task.retry_count or 0) + 1
            if task.retry_count >= MAX_RETRIES:
                task.status = "dead_letter"
                dead_letter += 1
                logger.warning(
                    "Write-back task dead-lettered: job=%s row=%d "
                    "tracking=%s retries=%d error=%s",
                    task.job_id, task.row_number, task.tracking_number,
                    task.retry_count, e,
                )
            else:
                failed += 1
                logger.info(
                    "Write-back task failed (will retry): job=%s row=%d "
                    "retry=%d/%d error=%s",
                    task.job_id, task.row_number,
                    task.retry_count, MAX_RETRIES, e,
                )

    db.commit()

    return {
        "processed": processed,
        "failed": failed,
        "dead_letter": dead_letter,
    }
