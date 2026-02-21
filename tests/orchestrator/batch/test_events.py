"""Unit tests for batch event observer pattern.

Tests cover:
- Observer registration
- Event emission to multiple observers
- Exception handling in observers
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator.batch.events import BatchEventEmitter


class MockObserver:
    """Mock observer for testing event emission."""

    def __init__(self) -> None:
        """Initialize mock observer with tracking attributes."""
        self.batch_started_calls: list[tuple[str, int]] = []
        self.row_started_calls: list[tuple[str, int]] = []
        self.row_completed_calls: list[tuple[str, int, str, int]] = []
        self.row_failed_calls: list[tuple[str, int, str, str]] = []
        self.batch_completed_calls: list[tuple[str, int, int, int]] = []
        self.batch_failed_calls: list[tuple[str, str, str, int]] = []

    async def on_batch_started(self, job_id: str, total_rows: int) -> None:
        """Record batch started event."""
        self.batch_started_calls.append((job_id, total_rows))

    async def on_row_started(self, job_id: str, row_number: int) -> None:
        """Record row started event."""
        self.row_started_calls.append((job_id, row_number))

    async def on_row_completed(
        self,
        job_id: str,
        row_number: int,
        tracking_number: str,
        cost_cents: int,
    ) -> None:
        """Record row completed event."""
        self.row_completed_calls.append(
            (job_id, row_number, tracking_number, cost_cents)
        )

    async def on_row_failed(
        self,
        job_id: str,
        row_number: int,
        error_code: str,
        error_message: str,
    ) -> None:
        """Record row failed event."""
        self.row_failed_calls.append((job_id, row_number, error_code, error_message))

    async def on_batch_completed(
        self,
        job_id: str,
        total_rows: int,
        successful: int,
        total_cost_cents: int,
    ) -> None:
        """Record batch completed event."""
        self.batch_completed_calls.append(
            (job_id, total_rows, successful, total_cost_cents)
        )

    async def on_batch_failed(
        self,
        job_id: str,
        error_code: str,
        error_message: str,
        processed: int,
    ) -> None:
        """Record batch failed event."""
        self.batch_failed_calls.append((job_id, error_code, error_message, processed))


class TestBatchEventEmitter:
    """Tests for BatchEventEmitter class."""

    def test_add_observer(self) -> None:
        """Test that observers can be added."""
        emitter = BatchEventEmitter()
        observer = MockObserver()

        emitter.add_observer(observer)

        assert observer in emitter._observers

    def test_remove_observer(self) -> None:
        """Test that observers can be removed."""
        emitter = BatchEventEmitter()
        observer = MockObserver()

        emitter.add_observer(observer)
        emitter.remove_observer(observer)

        assert observer not in emitter._observers

    def test_remove_observer_not_present_raises(self) -> None:
        """Test that removing non-existent observer raises ValueError."""
        emitter = BatchEventEmitter()
        observer = MockObserver()

        with pytest.raises(ValueError):
            emitter.remove_observer(observer)

    @pytest.mark.asyncio
    async def test_emit_batch_started_calls_observers(self) -> None:
        """Test that emit_batch_started calls all observers."""
        emitter = BatchEventEmitter()
        observer1 = MockObserver()
        observer2 = MockObserver()

        emitter.add_observer(observer1)
        emitter.add_observer(observer2)

        await emitter.emit_batch_started("job-123", 100)

        assert observer1.batch_started_calls == [("job-123", 100)]
        assert observer2.batch_started_calls == [("job-123", 100)]

    @pytest.mark.asyncio
    async def test_emit_row_started_calls_observers(self) -> None:
        """Test that emit_row_started calls all observers."""
        emitter = BatchEventEmitter()
        observer = MockObserver()
        emitter.add_observer(observer)

        await emitter.emit_row_started("job-123", 5)

        assert observer.row_started_calls == [("job-123", 5)]

    @pytest.mark.asyncio
    async def test_emit_row_completed_calls_observers(self) -> None:
        """Test that emit_row_completed calls all observers."""
        emitter = BatchEventEmitter()
        observer = MockObserver()
        emitter.add_observer(observer)

        await emitter.emit_row_completed("job-123", 5, "1Z999", 1250)

        assert observer.row_completed_calls == [("job-123", 5, "1Z999", 1250)]

    @pytest.mark.asyncio
    async def test_emit_row_failed_calls_observers(self) -> None:
        """Test that emit_row_failed calls all observers."""
        emitter = BatchEventEmitter()
        observer = MockObserver()
        emitter.add_observer(observer)

        await emitter.emit_row_failed("job-123", 5, "E-3001", "UPS API error")

        assert observer.row_failed_calls == [
            ("job-123", 5, "E-3001", "UPS API error")
        ]

    @pytest.mark.asyncio
    async def test_emit_batch_completed_calls_observers(self) -> None:
        """Test that emit_batch_completed calls all observers."""
        emitter = BatchEventEmitter()
        observer = MockObserver()
        emitter.add_observer(observer)

        await emitter.emit_batch_completed("job-123", 100, 98, 125000)

        assert observer.batch_completed_calls == [("job-123", 100, 98, 125000)]

    @pytest.mark.asyncio
    async def test_emit_batch_failed_calls_observers(self) -> None:
        """Test that emit_batch_failed calls all observers."""
        emitter = BatchEventEmitter()
        observer = MockObserver()
        emitter.add_observer(observer)

        await emitter.emit_batch_failed("job-123", "E-3001", "UPS API error", 47)

        assert observer.batch_failed_calls == [
            ("job-123", "E-3001", "UPS API error", 47)
        ]

    @pytest.mark.asyncio
    async def test_observer_exception_doesnt_stop_others(self) -> None:
        """Test that exception in one observer doesn't prevent others from being called."""
        emitter = BatchEventEmitter()

        # First observer raises exception
        failing_observer = MagicMock()
        failing_observer.on_batch_started = AsyncMock(
            side_effect=RuntimeError("Observer error")
        )

        # Second observer is healthy
        healthy_observer = MockObserver()

        emitter.add_observer(failing_observer)
        emitter.add_observer(healthy_observer)

        # Should not raise, and healthy observer should still be called
        await emitter.emit_batch_started("job-123", 100)

        assert healthy_observer.batch_started_calls == [("job-123", 100)]

    @pytest.mark.asyncio
    async def test_multiple_events_in_sequence(self) -> None:
        """Test emitting multiple events in sequence."""
        emitter = BatchEventEmitter()
        observer = MockObserver()
        emitter.add_observer(observer)

        await emitter.emit_batch_started("job-123", 100)
        await emitter.emit_row_started("job-123", 1)
        await emitter.emit_row_completed("job-123", 1, "1Z999", 1250)
        await emitter.emit_row_started("job-123", 2)
        await emitter.emit_row_failed("job-123", 2, "E-3001", "API error")
        await emitter.emit_batch_failed("job-123", "E-3001", "API error", 2)

        assert len(observer.batch_started_calls) == 1
        assert len(observer.row_started_calls) == 2
        assert len(observer.row_completed_calls) == 1
        assert len(observer.row_failed_calls) == 1
        assert len(observer.batch_failed_calls) == 1

    @pytest.mark.asyncio
    async def test_no_observers_doesnt_raise(self) -> None:
        """Test that emitting with no observers doesn't raise."""
        emitter = BatchEventEmitter()

        # Should not raise
        await emitter.emit_batch_started("job-123", 100)
        await emitter.emit_row_started("job-123", 1)
        await emitter.emit_row_completed("job-123", 1, "1Z999", 1250)
        await emitter.emit_row_failed("job-123", 2, "E-3001", "error")
        await emitter.emit_batch_completed("job-123", 100, 99, 123000)
        await emitter.emit_batch_failed("job-123", "E-3001", "error", 50)
