"""SSE Progress Observer for real-time batch event streaming.

Provides a BatchEventObserver implementation that bridges batch events
to Server-Sent Events (SSE) connections for web clients.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SSEProgressObserver:
    """Observer that bridges batch events to SSE connections.

    Implements the BatchEventObserver protocol and maintains per-job
    asyncio.Queue instances for SSE event delivery. Web clients subscribe
    to a job's queue to receive real-time progress updates.

    Thread-safe for concurrent subscriptions and event emissions.
    """

    def __init__(self) -> None:
        """Initialize observer with empty subscription map."""
        self._queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}

    def subscribe(self, job_id: str) -> asyncio.Queue[dict[str, Any]]:
        """Create a queue for SSE events for a specific job.

        If a queue already exists for the job, returns the existing queue.
        This supports multiple browser tabs viewing the same job.

        Args:
            job_id: Unique identifier for the batch job.

        Returns:
            asyncio.Queue for receiving SSE events.
        """
        if job_id not in self._queues:
            self._queues[job_id] = asyncio.Queue()
            logger.debug("Created SSE subscription for job %s", job_id)
        return self._queues[job_id]

    def unsubscribe(self, job_id: str) -> None:
        """Remove queue when client disconnects.

        Safely removes the queue if it exists. No-op if job_id not found.

        Args:
            job_id: Unique identifier for the batch job.
        """
        if self._queues.pop(job_id, None) is not None:
            logger.debug("Removed SSE subscription for job %s", job_id)

    def has_subscribers(self, job_id: str) -> bool:
        """Check if a job has active SSE subscribers.

        Args:
            job_id: Unique identifier for the batch job.

        Returns:
            True if there are active subscribers for this job.
        """
        return job_id in self._queues

    async def _emit(self, job_id: str, event: str, data: dict[str, Any]) -> None:
        """Emit an event to the job's queue if subscribed.

        Args:
            job_id: Unique identifier for the batch job.
            event: Event type name.
            data: Event payload data.
        """
        if queue := self._queues.get(job_id):
            await queue.put({"event": event, "data": data})

    # BatchEventObserver protocol implementation

    async def on_batch_started(self, job_id: str, total_rows: int) -> None:
        """Handle batch started event.

        Args:
            job_id: Unique identifier for the batch job.
            total_rows: Total number of rows in the batch.
        """
        await self._emit(
            job_id,
            "batch_started",
            {"job_id": job_id, "total_rows": total_rows},
        )

    async def on_row_started(self, job_id: str, row_number: int) -> None:
        """Handle row started event.

        Args:
            job_id: Unique identifier for the batch job.
            row_number: 1-based row number being processed.
        """
        await self._emit(
            job_id,
            "row_started",
            {"job_id": job_id, "row_number": row_number},
        )

    async def on_row_completed(
        self,
        job_id: str,
        row_number: int,
        tracking_number: str,
        cost_cents: int,
    ) -> None:
        """Handle row completed event.

        Args:
            job_id: Unique identifier for the batch job.
            row_number: 1-based row number that completed.
            tracking_number: UPS tracking number for the shipment.
            cost_cents: Cost of the shipment in cents.
        """
        await self._emit(
            job_id,
            "row_completed",
            {
                "job_id": job_id,
                "row_number": row_number,
                "tracking_number": tracking_number,
                "cost_cents": cost_cents,
            },
        )

    async def on_row_failed(
        self,
        job_id: str,
        row_number: int,
        error_code: str,
        error_message: str,
    ) -> None:
        """Handle row failed event.

        Args:
            job_id: Unique identifier for the batch job.
            row_number: 1-based row number that failed.
            error_code: Error code from the error registry.
            error_message: Human-readable error description.
        """
        await self._emit(
            job_id,
            "row_failed",
            {
                "job_id": job_id,
                "row_number": row_number,
                "error_code": error_code,
                "error_message": error_message,
            },
        )

    async def on_batch_completed(
        self,
        job_id: str,
        total_rows: int,
        successful: int,
        total_cost_cents: int,
    ) -> None:
        """Handle batch completed event.

        Args:
            job_id: Unique identifier for the batch job.
            total_rows: Total number of rows in the batch.
            successful: Number of rows successfully processed.
            total_cost_cents: Total cost of all shipments in cents.
        """
        await self._emit(
            job_id,
            "batch_completed",
            {
                "job_id": job_id,
                "total_rows": total_rows,
                "successful": successful,
                "total_cost_cents": total_cost_cents,
            },
        )

    async def on_batch_failed(
        self,
        job_id: str,
        error_code: str,
        error_message: str,
        processed: int,
    ) -> None:
        """Handle batch failed event.

        Args:
            job_id: Unique identifier for the batch job.
            error_code: Error code from the error registry.
            error_message: Human-readable error description.
            processed: Number of rows processed before failure.
        """
        await self._emit(
            job_id,
            "batch_failed",
            {
                "job_id": job_id,
                "error_code": error_code,
                "error_message": error_message,
                "processed": processed,
            },
        )
