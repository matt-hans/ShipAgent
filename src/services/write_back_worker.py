"""Durable write-back worker for tracking number persistence.

Provides a queue-based approach to writing tracking numbers back to data
sources. Each successful shipment enqueues a WriteBackTask; the worker
processes them with per-task retry and dead-letter semantics.

This replaces the fire-and-forget bulk write-back at the end of
BatchEngine.execute() with a crash-safe, retry-capable queue.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Maximum retry attempts before moving to dead letter
MAX_RETRIES = 3


@dataclass
class WriteBackTask:
    """A single write-back task in the durable queue.

    Attributes:
        job_id: Job UUID this task belongs to.
        row_number: 1-based row number within the job.
        tracking_number: UPS tracking number to write back.
        shipped_at: ISO8601 timestamp of when the shipment was created.
        status: Task status (pending, completed, dead_letter).
        retry_count: Number of failed attempts so far.
    """

    job_id: str
    row_number: int
    tracking_number: str
    shipped_at: str
    status: str = "pending"
    retry_count: int = 0


def enqueue_write_back(
    db: Any,
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
        The created WriteBackTask.
    """
    task = WriteBackTask(
        job_id=job_id,
        row_number=row_number,
        tracking_number=tracking_number,
        shipped_at=shipped_at,
    )
    db.add(task)
    db.commit()
    return task


async def process_write_back_queue(
    db: Any,
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
            task.retry_count += 1
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
