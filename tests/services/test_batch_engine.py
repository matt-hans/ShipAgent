"""Tests for consolidated batch engine."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.batch_engine import BatchEngine


@pytest.fixture
def mock_ups_service():
    """Create mock async UPS client (UPSMCPClient interface)."""
    svc = MagicMock()
    svc.create_shipment = AsyncMock(
        return_value={
            "success": True,
            "trackingNumbers": ["1Z999AA10123456784"],
            "labelData": ["base64data=="],
            "shipmentIdentificationNumber": "1Z999AA10123456784",
            "totalCharges": {"monetaryValue": "15.50", "currencyCode": "USD"},
        }
    )
    svc.get_rate = AsyncMock(
        return_value={
            "success": True,
            "totalCharges": {
                "monetaryValue": "15.50",
                "amount": "15.50",
                "currencyCode": "USD",
            },
        }
    )
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
                id="row-1",
                row_number=1,
                status="pending",
                order_data=json.dumps(
                    {
                        "ship_to_name": "John",
                        "ship_to_address1": "123 Main",
                        "ship_to_city": "LA",
                        "ship_to_state": "CA",
                        "ship_to_postal_code": "90001",
                        "weight": 2.0,
                    }
                ),
                cost_cents=0,
            ),
        ]

        shipper = {
            "name": "Store",
            "addressLine1": "456 Oak",
            "city": "SF",
            "stateProvinceCode": "CA",
            "postalCode": "94102",
            "countryCode": "US",
        }

        result = await engine.execute(
            job_id="job-1",
            rows=rows,
            shipper=shipper,
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
                id="row-1",
                row_number=1,
                status="pending",
                order_data=json.dumps(
                    {
                        "ship_to_name": "John",
                        "ship_to_address1": "123 Main",
                        "ship_to_city": "LA",
                        "ship_to_state": "CA",
                        "ship_to_postal_code": "90001",
                        "weight": 2.0,
                    }
                ),
                cost_cents=0,
            ),
        ]

        shipper = {
            "name": "Store",
            "addressLine1": "456 Oak",
            "city": "SF",
            "stateProvinceCode": "CA",
            "postalCode": "94102",
            "countryCode": "US",
        }

        await engine.execute(
            job_id="job-1",
            rows=rows,
            shipper=shipper,
            on_progress=on_progress,
        )

        assert on_progress.call_count >= 1

    async def test_handles_ups_error_per_row(self, mock_ups_service, mock_db_session):
        """Test UPS errors are recorded per row without stopping batch."""
        from src.services.errors import UPSServiceError

        mock_ups_service.create_shipment = AsyncMock(
            side_effect=UPSServiceError(code="E-3003", message="Address invalid")
        )

        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )

        rows = [
            MagicMock(
                id="row-1",
                row_number=1,
                status="pending",
                order_data=json.dumps(
                    {
                        "ship_to_name": "John",
                        "ship_to_address1": "123 Main",
                        "ship_to_city": "LA",
                        "ship_to_state": "CA",
                        "ship_to_postal_code": "90001",
                        "weight": 2.0,
                    }
                ),
                cost_cents=0,
            ),
        ]

        shipper = {
            "name": "Store",
            "addressLine1": "456 Oak",
            "city": "SF",
            "stateProvinceCode": "CA",
            "postalCode": "94102",
            "countryCode": "US",
        }

        result = await engine.execute(
            job_id="job-1",
            rows=rows,
            shipper=shipper,
        )

        assert result["failed"] == 1
        assert result["successful"] == 0

    async def test_batch_write_back_persists_successful_subset(
        self,
        mock_ups_service,
        mock_db_session,
        monkeypatch,
    ):
        """Batch write-back runs once and only for successful shipment rows."""
        from src.services.errors import UPSServiceError

        monkeypatch.setenv("BATCH_CONCURRENCY", "1")

        mock_ups_service.create_shipment = AsyncMock(
            side_effect=[
                {
                    "success": True,
                    "trackingNumbers": ["1Z999AA10123456784"],
                    "labelData": ["base64data=="],
                    "shipmentIdentificationNumber": "1Z999AA10123456784",
                    "totalCharges": {"monetaryValue": "15.50", "currencyCode": "USD"},
                },
                UPSServiceError(code="E-3003", message="Address invalid"),
            ]
        )

        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )

        rows = [
            MagicMock(
                id="row-1",
                row_number=1,
                status="pending",
                order_data=json.dumps(
                    {
                        "ship_to_name": "John",
                        "ship_to_address1": "123 Main",
                        "ship_to_city": "LA",
                        "ship_to_state": "CA",
                        "ship_to_postal_code": "90001",
                        "weight": 2.0,
                    }
                ),
                cost_cents=0,
            ),
            MagicMock(
                id="row-2",
                row_number=2,
                status="pending",
                order_data=json.dumps(
                    {
                        "ship_to_name": "Jane",
                        "ship_to_address1": "456 Main",
                        "ship_to_city": "SF",
                        "ship_to_state": "CA",
                        "ship_to_postal_code": "94102",
                        "weight": 3.0,
                    }
                ),
                cost_cents=0,
            ),
        ]

        shipper = {
            "name": "Store",
            "addressLine1": "456 Oak",
            "city": "SF",
            "stateProvinceCode": "CA",
            "postalCode": "94102",
            "countryCode": "US",
        }

        with patch(
            "src.services.batch_engine.get_data_gateway",
            new_callable=AsyncMock,
        ) as mock_get_gw:
            mock_gw = AsyncMock()
            mock_gw.get_source_info.return_value = {"active": True, "source_type": "csv"}
            mock_gw.write_back_batch.return_value = {
                "success_count": 1,
                "failure_count": 0,
                "errors": [],
            }
            mock_get_gw.return_value = mock_gw

            result = await engine.execute(
                job_id="job-1",
                rows=rows,
                shipper=shipper,
            )

        assert result["successful"] == 1
        assert result["failed"] == 1
        assert result["write_back"]["status"] == "success"
        mock_gw.write_back_batch.assert_awaited_once()
        call_args = mock_gw.write_back_batch.await_args[0][0]
        assert 1 in call_args
        assert call_args[1]["tracking_number"] == "1Z999AA10123456784"
        assert "shipped_at" in call_args[1]

    async def test_batch_write_back_failure_does_not_lose_execution_results(
        self,
        mock_ups_service,
        mock_db_session,
    ):
        """Write-back failure is reported without mutating shipment outcome counts."""
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )

        rows = [
            MagicMock(
                id="row-1",
                row_number=1,
                status="pending",
                order_data=json.dumps(
                    {
                        "ship_to_name": "John",
                        "ship_to_address1": "123 Main",
                        "ship_to_city": "LA",
                        "ship_to_state": "CA",
                        "ship_to_postal_code": "90001",
                        "weight": 2.0,
                    }
                ),
                cost_cents=0,
            ),
        ]

        shipper = {
            "name": "Store",
            "addressLine1": "456 Oak",
            "city": "SF",
            "stateProvinceCode": "CA",
            "postalCode": "94102",
            "countryCode": "US",
        }

        with patch(
            "src.services.batch_engine.get_data_gateway",
            new_callable=AsyncMock,
        ) as mock_get_gw:
            mock_gw = AsyncMock()
            mock_gw.get_source_info.return_value = {"active": True, "source_type": "csv"}
            mock_gw.write_back_batch.return_value = {
                "success_count": 0,
                "failure_count": 1,
                "errors": [{"row_number": 1, "error": "write failed"}],
            }
            mock_get_gw.return_value = mock_gw

            result = await engine.execute(
                job_id="job-1",
                rows=rows,
                shipper=shipper,
            )

        assert result["successful"] == 1
        assert result["failed"] == 0
        assert result["write_back"]["status"] == "partial"


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
                id="row-1",
                row_number=1,
                order_data=json.dumps(
                    {
                        "ship_to_name": "John",
                        "ship_to_address1": "123 Main",
                        "ship_to_city": "LA",
                        "ship_to_state": "CA",
                        "ship_to_postal_code": "90001",
                        "weight": 2.0,
                    }
                ),
            ),
        ]

        shipper = {
            "name": "Store",
            "addressLine1": "456 Oak",
            "city": "SF",
            "stateProvinceCode": "CA",
            "postalCode": "94102",
            "countryCode": "US",
        }

        result = await engine.preview(
            job_id="job-1",
            rows=rows,
            shipper=shipper,
        )

        assert result["total_estimated_cost_cents"] > 0
        assert mock_ups_service.get_rate.call_count == 1

    async def test_preview_default_cap_is_50(
        self, mock_ups_service, mock_db_session, monkeypatch
    ):
        """Default preview cap rates only first 50 rows and estimates remaining."""
        monkeypatch.delenv("BATCH_PREVIEW_MAX_ROWS", raising=False)
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )

        rows = [
            MagicMock(
                id=f"row-{i}",
                row_number=i,
                order_data=json.dumps(
                    {
                        "ship_to_name": f"User {i}",
                        "ship_to_address1": "123 Main",
                        "ship_to_city": "LA",
                        "ship_to_state": "CA",
                        "ship_to_postal_code": "90001",
                        "weight": 2.0,
                    }
                ),
            )
            for i in range(1, 61)
        ]

        shipper = {
            "name": "Store",
            "addressLine1": "456 Oak",
            "city": "SF",
            "stateProvinceCode": "CA",
            "postalCode": "94102",
            "countryCode": "US",
        }

        result = await engine.preview(job_id="job-50", rows=rows, shipper=shipper)
        assert len(result["preview_rows"]) == 50
        assert result["additional_rows"] == 10
        assert mock_ups_service.get_rate.call_count == 50

    async def test_preview_unlimited_when_cap_zero(
        self, mock_ups_service, mock_db_session, monkeypatch
    ):
        """BATCH_PREVIEW_MAX_ROWS=0 rates all rows with no estimation remainder."""
        monkeypatch.setenv("BATCH_PREVIEW_MAX_ROWS", "0")
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )

        rows = [
            MagicMock(
                id=f"row-{i}",
                row_number=i,
                order_data=json.dumps(
                    {
                        "ship_to_name": f"User {i}",
                        "ship_to_address1": "123 Main",
                        "ship_to_city": "LA",
                        "ship_to_state": "CA",
                        "ship_to_postal_code": "90001",
                        "weight": 2.0,
                    }
                ),
            )
            for i in range(1, 13)
        ]
        shipper = {
            "name": "Store",
            "addressLine1": "456 Oak",
            "city": "SF",
            "stateProvinceCode": "CA",
            "postalCode": "94102",
            "countryCode": "US",
        }

        result = await engine.preview(job_id="job-all", rows=rows, shipper=shipper)
        assert len(result["preview_rows"]) == 12
        assert result["additional_rows"] == 0
        assert mock_ups_service.get_rate.call_count == 12

    async def test_preview_row_parse_error_becomes_warning_not_hard_fail(
        self,
        mock_ups_service,
        mock_db_session,
    ):
        """Malformed CSV row data should produce row warning, not fail preview."""
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )

        rows = [
            MagicMock(
                id="row-1",
                row_number=1,
                order_data="{not-json",
            ),
            MagicMock(
                id="row-2",
                row_number=2,
                order_data=json.dumps(
                    {
                        "ship_to_name": "Jane",
                        "ship_to_address1": "123 Main",
                        "ship_to_city": "LA",
                        "ship_to_state": "CA",
                        "ship_to_postal_code": "90001",
                        "weight": 2.0,
                    }
                ),
            ),
        ]

        shipper = {
            "name": "Store",
            "addressLine1": "456 Oak",
            "city": "SF",
            "stateProvinceCode": "CA",
            "postalCode": "94102",
            "countryCode": "US",
        }

        result = await engine.preview(job_id="job-warning", rows=rows, shipper=shipper)

        assert result["total_rows"] == 2
        assert len(result["preview_rows"]) == 2
        first = result["preview_rows"][0]
        assert first["row_number"] == 1
        assert first["estimated_cost_cents"] == 0
        assert "rate_error" in first
        # Second row still rated successfully.
        assert result["preview_rows"][1]["estimated_cost_cents"] > 0

    async def test_preview_invalid_concurrency_env_falls_back_to_default(
        self,
        mock_ups_service,
        mock_db_session,
        monkeypatch,
    ):
        """Invalid BATCH_CONCURRENCY should not crash preview."""
        monkeypatch.setenv("BATCH_CONCURRENCY", "not-an-int")
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )

        rows = [
            MagicMock(
                id="row-1",
                row_number=1,
                order_data=json.dumps(
                    {
                        "ship_to_name": "John",
                        "ship_to_address1": "123 Main",
                        "ship_to_city": "LA",
                        "ship_to_state": "CA",
                        "ship_to_postal_code": "90001",
                        "weight": 2.0,
                    }
                ),
            ),
        ]
        shipper = {
            "name": "Store",
            "addressLine1": "456 Oak",
            "city": "SF",
            "stateProvinceCode": "CA",
            "postalCode": "94102",
            "countryCode": "US",
        }

        result = await engine.preview(
            job_id="job-safe-conc", rows=rows, shipper=shipper
        )
        assert result["total_rows"] == 1
        assert len(result["preview_rows"]) == 1
