"""Tests for in-flight state machine in BatchEngine.execute()."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.batch_engine import BatchEngine
from src.services.errors import UPSServiceError
from src.services.mcp_client import MCPConnectionError


def _make_row(
    row_number: int = 1,
    status: str = "pending",
    row_checksum: str = "abc123",
    job_id: str = "job-test-1234",
) -> MagicMock:
    """Create a mock JobRow with standard fields."""
    row = MagicMock()
    row.row_number = row_number
    row.status = status
    row.row_checksum = row_checksum
    row.job_id = job_id
    row.order_data = json.dumps({
        "ship_to_name": "John Doe",
        "ship_to_address1": "123 Main St",
        "ship_to_city": "Los Angeles",
        "ship_to_state": "CA",
        "ship_to_postal_code": "90001",
        "ship_to_country": "US",
        "weight": 2.0,
    })
    row.idempotency_key = None
    row.ups_shipment_id = None
    row.ups_tracking_number = None
    row.tracking_number = None
    row.label_path = None
    row.cost_cents = None
    row.error_code = None
    row.error_message = None
    row.processed_at = None
    row.destination_country = None
    row.duties_taxes_cents = None
    row.charge_breakdown = None
    row.recovery_attempt_count = 0
    return row


def _make_ups_result(
    tracking: str = "1Z999AA10000000001",
    shipment_id: str = "SHIP123",
    cost: str = "12.50",
) -> dict:
    """Create a mock UPS create_shipment result."""
    return {
        "trackingNumbers": [tracking],
        "shipmentIdentificationNumber": shipment_id,
        "labelData": [""],  # Empty label data for tests
        "totalCharges": {"monetaryValue": cost},
    }


@pytest.fixture()
def engine(tmp_path: Path) -> BatchEngine:
    """Create a BatchEngine with mocked UPS client."""
    ups = AsyncMock()
    ups.create_shipment = AsyncMock(return_value=_make_ups_result())
    db = MagicMock()
    return BatchEngine(
        ups_service=ups,
        db_session=db,
        account_number="TEST123",
        labels_dir=str(tmp_path / "labels"),
    )


class TestInFlightStateMachine:
    """Verify the two-phase commit state machine in _process_row."""

    @pytest.mark.asyncio
    async def test_row_transitions_to_in_flight_before_ups_call(
        self, engine: BatchEngine, tmp_path: Path,
    ) -> None:
        """Row status is 'in_flight' with idempotency_key set BEFORE create_shipment."""
        row = _make_row()
        statuses_at_ups_call: list[str] = []

        original_create = engine._ups.create_shipment

        async def capture_status(*args, **kwargs):
            statuses_at_ups_call.append(row.status)
            return await original_create(*args, **kwargs)

        engine._ups.create_shipment = capture_status

        shipper = {"name": "S", "addressLine1": "A", "city": "C",
                   "stateProvinceCode": "CA", "postalCode": "90001",
                   "countryCode": "US"}

        await engine.execute(
            job_id="job-test-1234", rows=[row], shipper=shipper,
        )

        assert statuses_at_ups_call[0] == "in_flight"
        assert row.idempotency_key is not None
        assert row.idempotency_key.startswith("job-test-1234:")

    @pytest.mark.asyncio
    async def test_row_transitions_to_completed_after_ups_success(
        self, engine: BatchEngine,
    ) -> None:
        """After successful create_shipment, row is 'completed'."""
        row = _make_row()
        shipper = {"name": "S", "addressLine1": "A", "city": "C",
                   "stateProvinceCode": "CA", "postalCode": "90001",
                   "countryCode": "US"}

        await engine.execute(
            job_id="job-test-1234", rows=[row], shipper=shipper,
        )

        assert row.status == "completed"
        assert row.tracking_number == "1Z999AA10000000001"
        assert row.ups_shipment_id == "SHIP123"
        assert row.ups_tracking_number == "1Z999AA10000000001"
        assert row.cost_cents == 1250

    @pytest.mark.asyncio
    async def test_row_transitions_to_failed_on_ups_hard_rejection(
        self, engine: BatchEngine,
    ) -> None:
        """UPSServiceError (hard rejection) marks row 'failed'."""
        engine._ups.create_shipment = AsyncMock(
            side_effect=UPSServiceError(code="E-3001", message="Invalid address"),
        )
        row = _make_row()
        shipper = {"name": "S", "addressLine1": "A", "city": "C",
                   "stateProvinceCode": "CA", "postalCode": "90001",
                   "countryCode": "US"}

        await engine.execute(
            job_id="job-test-1234", rows=[row], shipper=shipper,
        )

        assert row.status == "failed"
        assert row.error_code == "E-3001"

    @pytest.mark.asyncio
    async def test_mcp_connection_error_marks_row_failed(
        self, engine: BatchEngine,
    ) -> None:
        """MCPConnectionError marks row 'failed' (no side effect possible)."""
        engine._ups.create_shipment = AsyncMock(
            side_effect=MCPConnectionError("ups-mcp", "Server unreachable"),
        )
        row = _make_row()
        shipper = {"name": "S", "addressLine1": "A", "city": "C",
                   "stateProvinceCode": "CA", "postalCode": "90001",
                   "countryCode": "US"}

        await engine.execute(
            job_id="job-test-1234", rows=[row], shipper=shipper,
        )

        assert row.status == "failed"

    @pytest.mark.asyncio
    async def test_transport_timeout_marks_needs_review(
        self, engine: BatchEngine,
    ) -> None:
        """Generic transport error (TimeoutError) marks row 'needs_review'."""
        engine._ups.create_shipment = AsyncMock(
            side_effect=TimeoutError("Connection timed out"),
        )
        row = _make_row()
        shipper = {"name": "S", "addressLine1": "A", "city": "C",
                   "stateProvinceCode": "CA", "postalCode": "90001",
                   "countryCode": "US"}

        await engine.execute(
            job_id="job-test-1234", rows=[row], shipper=shipper,
        )

        assert row.status == "needs_review"
        assert "Ambiguous" in (row.error_message or "")

    @pytest.mark.asyncio
    async def test_pre_phase1_error_marks_pending_row_failed(
        self, engine: BatchEngine,
    ) -> None:
        """Parse/validation error before in_flight commit marks row 'failed'."""
        row = _make_row()
        row.order_data = "{{invalid json"
        shipper = {"name": "S", "addressLine1": "A", "city": "C",
                   "stateProvinceCode": "CA", "postalCode": "90001",
                   "countryCode": "US"}

        await engine.execute(
            job_id="job-test-1234", rows=[row], shipper=shipper,
        )

        assert row.status == "failed"

    @pytest.mark.asyncio
    async def test_ups_call_succeeded_always_bound(
        self, engine: BatchEngine,
    ) -> None:
        """ups_call_succeeded is initialized at top — never causes UnboundLocalError."""
        # Trigger an error BEFORE the UPS call
        row = _make_row()
        row.order_data = "{{invalid"
        shipper = {"name": "S", "addressLine1": "A", "city": "C",
                   "stateProvinceCode": "CA", "postalCode": "90001",
                   "countryCode": "US"}

        # Should not raise UnboundLocalError
        result = await engine.execute(
            job_id="job-test-1234", rows=[row], shipper=shipper,
        )
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_pending_to_completed_must_go_through_in_flight(
        self, engine: BatchEngine,
    ) -> None:
        """Row goes through in_flight before reaching completed."""
        row = _make_row()
        status_history: list[str] = []

        # Track all status changes
        original_status = row.status

        class StatusTracker:
            def __set_name__(self, owner, name):
                self.name = name

            def __get__(self, obj, type=None):
                return obj.__dict__.get("_status", original_status)

            def __set__(self, obj, value):
                status_history.append(value)
                obj.__dict__["_status"] = value

        # Monkey-patch status tracking
        def status_setter(val):
            status_history.append(val)

        original_setattr = type(row).__setattr__

        def tracking_setattr(self, name, value):
            if name == "status":
                status_history.append(value)
            original_setattr(self, name, value)

        type(row).__setattr__ = tracking_setattr

        shipper = {"name": "S", "addressLine1": "A", "city": "C",
                   "stateProvinceCode": "CA", "postalCode": "90001",
                   "countryCode": "US"}
        try:
            await engine.execute(
                job_id="job-test-1234", rows=[row], shipper=shipper,
            )
        finally:
            type(row).__setattr__ = original_setattr

        # Should see in_flight before completed
        assert "in_flight" in status_history
        in_flight_idx = status_history.index("in_flight")
        completed_idx = status_history.index("completed")
        assert in_flight_idx < completed_idx
