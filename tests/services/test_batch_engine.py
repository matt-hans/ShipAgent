"""Tests for consolidated batch engine."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.batch_engine import BatchEngine


@pytest.fixture
def mock_ups_service():
    """Create mock UPSService."""
    svc = MagicMock()
    svc.create_shipment.return_value = {
        "success": True,
        "trackingNumbers": ["1Z999AA10123456784"],
        "labelData": ["base64data=="],
        "shipmentIdentificationNumber": "1Z999AA10123456784",
        "totalCharges": {"monetaryValue": "15.50", "currencyCode": "USD"},
    }
    svc.get_rate.return_value = {
        "success": True,
        "totalCharges": {"monetaryValue": "15.50", "amount": "15.50", "currencyCode": "USD"},
    }
    return svc


@pytest.fixture
def mock_db_session():
    """Create mock database session."""
    session = MagicMock()
    return session


class TestBatchEngineExecute:
    """Test batch execution."""

    async def test_processes_all_rows(self, mock_ups_service, mock_db_session):
        """Test all rows are processed successfully."""
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )

        rows = [
            MagicMock(
                id="row-1", row_number=1, status="pending",
                order_data=json.dumps({
                    "ship_to_name": "John", "ship_to_address1": "123 Main",
                    "ship_to_city": "LA", "ship_to_state": "CA",
                    "ship_to_postal_code": "90001", "weight": 2.0,
                }),
                cost_cents=0,
            ),
        ]

        shipper = {"name": "Store", "addressLine1": "456 Oak",
                   "city": "SF", "stateProvinceCode": "CA",
                   "postalCode": "94102", "countryCode": "US"}

        result = await engine.execute(
            job_id="job-1", rows=rows, shipper=shipper,
        )

        assert result["successful"] == 1
        assert result["failed"] == 0
        assert mock_ups_service.create_shipment.call_count == 1

    async def test_calls_progress_callback(self, mock_ups_service, mock_db_session):
        """Test on_progress callback is invoked."""
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )

        on_progress = AsyncMock()

        rows = [
            MagicMock(
                id="row-1", row_number=1, status="pending",
                order_data=json.dumps({
                    "ship_to_name": "John", "ship_to_address1": "123 Main",
                    "ship_to_city": "LA", "ship_to_state": "CA",
                    "ship_to_postal_code": "90001", "weight": 2.0,
                }),
                cost_cents=0,
            ),
        ]

        shipper = {"name": "Store", "addressLine1": "456 Oak",
                   "city": "SF", "stateProvinceCode": "CA",
                   "postalCode": "94102", "countryCode": "US"}

        await engine.execute(
            job_id="job-1", rows=rows, shipper=shipper,
            on_progress=on_progress,
        )

        assert on_progress.call_count >= 1

    async def test_handles_ups_error_per_row(self, mock_ups_service, mock_db_session):
        """Test UPS errors are recorded per row without stopping batch."""
        from src.services.ups_service import UPSServiceError

        mock_ups_service.create_shipment.side_effect = UPSServiceError(
            code="E-3003", message="Address invalid"
        )

        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )

        rows = [
            MagicMock(
                id="row-1", row_number=1, status="pending",
                order_data=json.dumps({
                    "ship_to_name": "John", "ship_to_address1": "123 Main",
                    "ship_to_city": "LA", "ship_to_state": "CA",
                    "ship_to_postal_code": "90001", "weight": 2.0,
                }),
                cost_cents=0,
            ),
        ]

        shipper = {"name": "Store", "addressLine1": "456 Oak",
                   "city": "SF", "stateProvinceCode": "CA",
                   "postalCode": "94102", "countryCode": "US"}

        result = await engine.execute(
            job_id="job-1", rows=rows, shipper=shipper,
        )

        assert result["failed"] == 1
        assert result["successful"] == 0


class TestBatchEnginePreview:
    """Test batch preview (rate quoting)."""

    async def test_returns_estimated_costs(self, mock_ups_service, mock_db_session):
        """Test preview returns cost estimates."""
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )

        rows = [
            MagicMock(
                id="row-1", row_number=1,
                order_data=json.dumps({
                    "ship_to_name": "John", "ship_to_address1": "123 Main",
                    "ship_to_city": "LA", "ship_to_state": "CA",
                    "ship_to_postal_code": "90001", "weight": 2.0,
                }),
            ),
        ]

        shipper = {"name": "Store", "addressLine1": "456 Oak",
                   "city": "SF", "stateProvinceCode": "CA",
                   "postalCode": "94102", "countryCode": "US"}

        result = await engine.preview(
            job_id="job-1", rows=rows, shipper=shipper,
        )

        assert result["total_estimated_cost_cents"] > 0
        assert mock_ups_service.get_rate.call_count == 1
