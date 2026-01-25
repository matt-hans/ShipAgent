"""Observer pattern for batch lifecycle events.

Provides the BatchEventObserver protocol and BatchEventEmitter class
for notifying observers of batch processing progress.
"""

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class BatchEventObserver(Protocol):
    """Observer protocol for batch lifecycle events.

    Implementations can subscribe to batch events via BatchEventEmitter
    to track progress, update UI, or log activity.
    """

    async def on_batch_started(self, job_id: str, total_rows: int) -> None:
        """Called when a batch begins execution.

        Args:
            job_id: Unique identifier for the batch job.
            total_rows: Total number of rows in the batch.
        """
        ...

    async def on_row_started(self, job_id: str, row_number: int) -> None:
        """Called when processing begins for a row.

        Args:
            job_id: Unique identifier for the batch job.
            row_number: 1-based row number being processed.
        """
        ...

    async def on_row_completed(
        self,
        job_id: str,
        row_number: int,
        tracking_number: str,
        cost_cents: int,
    ) -> None:
        """Called when a row is successfully processed.

        Args:
            job_id: Unique identifier for the batch job.
            row_number: 1-based row number that completed.
            tracking_number: UPS tracking number for the shipment.
            cost_cents: Cost of the shipment in cents.
        """
        ...

    async def on_row_failed(
        self,
        job_id: str,
        row_number: int,
        error_code: str,
        error_message: str,
    ) -> None:
        """Called when a row fails processing.

        Args:
            job_id: Unique identifier for the batch job.
            row_number: 1-based row number that failed.
            error_code: Error code from the error registry.
            error_message: Human-readable error description.
        """
        ...

    async def on_batch_completed(
        self,
        job_id: str,
        total_rows: int,
        successful: int,
        total_cost_cents: int,
    ) -> None:
        """Called when a batch completes successfully.

        Args:
            job_id: Unique identifier for the batch job.
            total_rows: Total number of rows in the batch.
            successful: Number of rows successfully processed.
            total_cost_cents: Total cost of all shipments in cents.
        """
        ...

    async def on_batch_failed(
        self,
        job_id: str,
        error_code: str,
        error_message: str,
        processed: int,
    ) -> None:
        """Called when a batch fails (fail-fast).

        Args:
            job_id: Unique identifier for the batch job.
            error_code: Error code from the error registry.
            error_message: Human-readable error description.
            processed: Number of rows processed before failure.
        """
        ...


class BatchEventEmitter:
    """Emits batch lifecycle events to registered observers.

    Implements the publisher side of the Observer pattern. Observers
    register via add_observer() and receive async callbacks for each
    batch event.

    Exceptions from individual observers are caught and logged to prevent
    one broken observer from stopping event delivery to others.
    """

    def __init__(self) -> None:
        """Initialize emitter with empty observer list."""
        self._observers: list[BatchEventObserver] = []

    def add_observer(self, observer: BatchEventObserver) -> None:
        """Register an observer to receive batch events.

        Args:
            observer: Observer implementing BatchEventObserver protocol.
        """
        self._observers.append(observer)

    def remove_observer(self, observer: BatchEventObserver) -> None:
        """Unregister an observer.

        Args:
            observer: Observer to remove from notification list.
        """
        self._observers.remove(observer)

    async def emit_batch_started(self, job_id: str, total_rows: int) -> None:
        """Emit batch started event to all observers.

        Args:
            job_id: Unique identifier for the batch job.
            total_rows: Total number of rows in the batch.
        """
        for observer in self._observers:
            try:
                await observer.on_batch_started(job_id, total_rows)
            except Exception as e:
                logger.error(
                    "Observer %s failed on_batch_started: %s",
                    type(observer).__name__,
                    e,
                )

    async def emit_row_started(self, job_id: str, row_number: int) -> None:
        """Emit row started event to all observers.

        Args:
            job_id: Unique identifier for the batch job.
            row_number: 1-based row number being processed.
        """
        for observer in self._observers:
            try:
                await observer.on_row_started(job_id, row_number)
            except Exception as e:
                logger.error(
                    "Observer %s failed on_row_started: %s",
                    type(observer).__name__,
                    e,
                )

    async def emit_row_completed(
        self,
        job_id: str,
        row_number: int,
        tracking_number: str,
        cost_cents: int,
    ) -> None:
        """Emit row completed event to all observers.

        Args:
            job_id: Unique identifier for the batch job.
            row_number: 1-based row number that completed.
            tracking_number: UPS tracking number for the shipment.
            cost_cents: Cost of the shipment in cents.
        """
        for observer in self._observers:
            try:
                await observer.on_row_completed(
                    job_id, row_number, tracking_number, cost_cents
                )
            except Exception as e:
                logger.error(
                    "Observer %s failed on_row_completed: %s",
                    type(observer).__name__,
                    e,
                )

    async def emit_row_failed(
        self,
        job_id: str,
        row_number: int,
        error_code: str,
        error_message: str,
    ) -> None:
        """Emit row failed event to all observers.

        Args:
            job_id: Unique identifier for the batch job.
            row_number: 1-based row number that failed.
            error_code: Error code from the error registry.
            error_message: Human-readable error description.
        """
        for observer in self._observers:
            try:
                await observer.on_row_failed(
                    job_id, row_number, error_code, error_message
                )
            except Exception as e:
                logger.error(
                    "Observer %s failed on_row_failed: %s",
                    type(observer).__name__,
                    e,
                )

    async def emit_batch_completed(
        self,
        job_id: str,
        total_rows: int,
        successful: int,
        total_cost_cents: int,
    ) -> None:
        """Emit batch completed event to all observers.

        Args:
            job_id: Unique identifier for the batch job.
            total_rows: Total number of rows in the batch.
            successful: Number of rows successfully processed.
            total_cost_cents: Total cost of all shipments in cents.
        """
        for observer in self._observers:
            try:
                await observer.on_batch_completed(
                    job_id, total_rows, successful, total_cost_cents
                )
            except Exception as e:
                logger.error(
                    "Observer %s failed on_batch_completed: %s",
                    type(observer).__name__,
                    e,
                )

    async def emit_batch_failed(
        self,
        job_id: str,
        error_code: str,
        error_message: str,
        processed: int,
    ) -> None:
        """Emit batch failed event to all observers.

        Args:
            job_id: Unique identifier for the batch job.
            error_code: Error code from the error registry.
            error_message: Human-readable error description.
            processed: Number of rows processed before failure.
        """
        for observer in self._observers:
            try:
                await observer.on_batch_failed(
                    job_id, error_code, error_message, processed
                )
            except Exception as e:
                logger.error(
                    "Observer %s failed on_batch_failed: %s",
                    type(observer).__name__,
                    e,
                )
