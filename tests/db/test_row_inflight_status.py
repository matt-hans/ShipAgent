"""Tests for in_flight row status and idempotency columns."""

from sqlalchemy import inspect

from src.db.models import JobRow, RowStatus


class TestRowStatusInFlight:
    """Verify in_flight and needs_review statuses exist and processing is removed."""

    def test_in_flight_status_exists(self) -> None:
        """in_flight status is available on RowStatus enum."""
        assert hasattr(RowStatus, "in_flight")
        assert RowStatus.in_flight.value == "in_flight"

    def test_needs_review_status_exists(self) -> None:
        """needs_review status is available on RowStatus enum."""
        assert hasattr(RowStatus, "needs_review")
        assert RowStatus.needs_review.value == "needs_review"

    def test_processing_status_removed(self) -> None:
        """processing status is removed — no alternate lifecycle can bypass
        the deterministic in_flight state machine."""
        assert not hasattr(RowStatus, "processing")

    def test_start_row_removed(self) -> None:
        """start_row() is removed — rows transition via in_flight, not processing."""
        from src.services.job_service import JobService

        assert not hasattr(JobService, "start_row")


class TestIdempotencyColumns:
    """Verify idempotency columns exist on JobRow model."""

    def test_idempotency_key_column_exists(self) -> None:
        """JobRow has idempotency_key column."""
        mapper = inspect(JobRow)
        col_names = {c.key for c in mapper.column_attrs}
        assert "idempotency_key" in col_names

    def test_ups_shipment_id_column_exists(self) -> None:
        """JobRow has ups_shipment_id column."""
        mapper = inspect(JobRow)
        col_names = {c.key for c in mapper.column_attrs}
        assert "ups_shipment_id" in col_names

    def test_ups_tracking_number_column_exists(self) -> None:
        """JobRow has ups_tracking_number column."""
        mapper = inspect(JobRow)
        col_names = {c.key for c in mapper.column_attrs}
        assert "ups_tracking_number" in col_names

    def test_recovery_attempt_count_column_exists(self) -> None:
        """JobRow has recovery_attempt_count column with default 0."""
        mapper = inspect(JobRow)
        col_names = {c.key for c in mapper.column_attrs}
        assert "recovery_attempt_count" in col_names

    def test_all_row_statuses(self) -> None:
        """RowStatus contains exactly the expected values."""
        expected = {"pending", "in_flight", "completed", "failed", "skipped", "needs_review"}
        actual = {s.value for s in RowStatus}
        assert actual == expected
