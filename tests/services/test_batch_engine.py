"""Tests for consolidated batch engine."""

import asyncio
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

    async def test_preview_emits_partial_callback(
        self, mock_ups_service, mock_db_session
    ):
        """preview should stream partial rows through on_preview_partial."""
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
        partial_events: list[dict] = []

        result = await engine.preview(
            job_id="job-partial",
            rows=rows,
            shipper=shipper,
            on_preview_partial=lambda payload: partial_events.append(payload),
        )

        assert result["total_rows"] == 1
        assert len(partial_events) == 1
        assert partial_events[0]["job_id"] == "job-partial"
        assert partial_events[0]["rows_rated"] == 1
        assert partial_events[0]["total_rows"] == 1
        assert partial_events[0]["is_final"] is False

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

    async def test_preview_skips_commodity_prefetch_for_domestic_rows(
        self, mock_ups_service, mock_db_session
    ):
        """Domestic rows should not trigger commodity prefetch."""
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="ABC123",
        )
        engine._get_commodities_bulk = AsyncMock(return_value={})  # type: ignore[attr-defined]

        rows = [
            MagicMock(
                id="row-1",
                row_number=1,
                order_data=json.dumps(
                    {
                        "order_id": "1001",
                        "ship_to_name": "John",
                        "ship_to_address1": "123 Main",
                        "ship_to_city": "LA",
                        "ship_to_state": "CA",
                        "ship_to_postal_code": "90001",
                        "ship_to_country": "US",
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

        await engine.preview(job_id="job-domestic", rows=rows, shipper=shipper)
        engine._get_commodities_bulk.assert_not_called()  # type: ignore[attr-defined]

    async def test_preview_rate_timeout_degrades_to_warning(
        self, mock_ups_service, mock_db_session, monkeypatch
    ):
        """Slow UPS rate calls should timeout and return row warnings quickly."""
        monkeypatch.setenv("BATCH_PREVIEW_RATE_TIMEOUT_SECONDS", "0.01")

        async def _slow_rate(*args, **kwargs):
            await asyncio.sleep(0.05)
            return {
                "success": True,
                "totalCharges": {"monetaryValue": "15.50", "currencyCode": "USD"},
            }

        mock_ups_service.get_rate = AsyncMock(side_effect=_slow_rate)

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

        result = await engine.preview(job_id="job-timeout", rows=rows, shipper=shipper)
        first = result["preview_rows"][0]
        assert "rate_error" in first
        assert "timeout" in first["rate_error"].lower()


class TestBatchEngineExternalWriteBack:
    """Test external platform write-back routing in BatchEngine."""

    def _make_row(self, row_number: int, order_id: str | None = None) -> MagicMock:
        """Create a mock JobRow with order_data containing platform fields."""
        data = {
            "ship_to_name": f"Customer {row_number}",
            "ship_to_address1": f"{row_number} Main St",
            "ship_to_city": "LA",
            "ship_to_state": "CA",
            "ship_to_postal_code": "90001",
            "weight": 2.0,
        }
        if order_id is not None:
            data["order_id"] = order_id
        return MagicMock(
            id=f"row-{row_number}",
            row_number=row_number,
            status="pending",
            order_data=json.dumps(data),
            cost_cents=0,
        )

    def _make_shipper(self) -> dict:
        """Standard test shipper."""
        return {
            "name": "Store",
            "addressLine1": "456 Oak",
            "city": "SF",
            "stateProvinceCode": "CA",
            "postalCode": "94102",
            "countryCode": "US",
        }

    async def test_external_write_back_routes_to_platform(
        self, mock_ups_service, mock_db_session
    ):
        """Source type 'shopify' → ext.update_tracking() called, not gw.write_back_batch()."""
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="TEST",
        )
        rows = [self._make_row(1, order_id="SHP-1001")]

        mock_gw = AsyncMock()
        mock_gw.get_source_info = AsyncMock(
            return_value={"source_type": "shopify"}
        )
        mock_gw.write_back_batch = AsyncMock()

        mock_ext = AsyncMock()
        mock_ext.update_tracking = AsyncMock(
            return_value={"success": True}
        )

        with patch(
            "src.services.batch_engine.get_data_gateway",
            new_callable=AsyncMock, return_value=mock_gw,
        ), patch(
            "src.services.batch_engine.get_external_sources_client",
            new_callable=AsyncMock, return_value=mock_ext,
        ):
            result = await engine.execute(
                job_id="job-ext-1", rows=rows,
                shipper=self._make_shipper(),
                write_back_enabled=True,
            )

        assert result["successful"] == 1
        assert result["write_back"]["status"] == "success"
        mock_ext.update_tracking.assert_called_once()
        mock_gw.write_back_batch.assert_not_called()

    async def test_external_write_back_extracts_order_id(
        self, mock_ups_service, mock_db_session
    ):
        """order_id correctly parsed from order_data JSON."""
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="TEST",
        )
        rows = [self._make_row(1, order_id="SHOP-42")]

        mock_gw = AsyncMock()
        mock_gw.get_source_info = AsyncMock(
            return_value={"source_type": "shopify"}
        )

        mock_ext = AsyncMock()
        mock_ext.update_tracking = AsyncMock(
            return_value={"success": True}
        )

        with patch(
            "src.services.batch_engine.get_data_gateway",
            new_callable=AsyncMock, return_value=mock_gw,
        ), patch(
            "src.services.batch_engine.get_external_sources_client",
            new_callable=AsyncMock, return_value=mock_ext,
        ):
            await engine.execute(
                job_id="job-ext-2", rows=rows,
                shipper=self._make_shipper(),
                write_back_enabled=True,
            )

        call_kwargs = mock_ext.update_tracking.call_args[1]
        assert call_kwargs["order_id"] == "SHOP-42"
        assert call_kwargs["platform"] == "shopify"
        assert "tracking_number" in call_kwargs

    async def test_external_write_back_skips_missing_order_id(
        self, mock_ups_service, mock_db_session
    ):
        """Rows without order_id reported as failures, don't crash."""
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="TEST",
        )
        # No order_id in order_data
        rows = [self._make_row(1, order_id=None)]

        mock_gw = AsyncMock()
        mock_gw.get_source_info = AsyncMock(
            return_value={"source_type": "woocommerce"}
        )

        mock_ext = AsyncMock()
        mock_ext.update_tracking = AsyncMock()

        with patch(
            "src.services.batch_engine.get_data_gateway",
            new_callable=AsyncMock, return_value=mock_gw,
        ), patch(
            "src.services.batch_engine.get_external_sources_client",
            new_callable=AsyncMock, return_value=mock_ext,
        ):
            result = await engine.execute(
                job_id="job-ext-3", rows=rows,
                shipper=self._make_shipper(),
                write_back_enabled=True,
            )

        assert result["write_back"]["failure_count"] == 1
        assert result["write_back"]["status"] == "partial"
        mock_ext.update_tracking.assert_not_called()

    async def test_local_write_back_unchanged_for_csv(
        self, mock_ups_service, mock_db_session
    ):
        """Source type 'csv' → existing local path, no external routing."""
        engine = BatchEngine(
            ups_service=mock_ups_service,
            db_session=mock_db_session,
            account_number="TEST",
        )
        rows = [self._make_row(1)]

        mock_gw = AsyncMock()
        mock_gw.get_source_info = AsyncMock(
            return_value={"source_type": "csv", "file_path": "/tmp/test.csv"}
        )
        mock_gw.write_back_batch = AsyncMock(
            return_value={"success_count": 1, "failure_count": 0, "errors": []}
        )

        with patch(
            "src.services.batch_engine.get_data_gateway",
            new_callable=AsyncMock, return_value=mock_gw,
        ):
            result = await engine.execute(
                job_id="job-local-1", rows=rows,
                shipper=self._make_shipper(),
                write_back_enabled=True,
            )

        assert result["write_back"]["status"] == "success"
        mock_gw.write_back_batch.assert_called_once()

    async def test_shopify_idempotency_guard_skips_fulfilled_orders(self):
        """Already-fulfilled orders get tracking update, not duplicate fulfillment."""
        import httpx

        from src.mcp.external_sources.clients.shopify import ShopifyClient
        from src.mcp.external_sources.models import TrackingUpdate

        client = ShopifyClient()
        client._authenticated = True
        client._shop_domain = "test.myshopify.com"
        client._access_token = "test-token"
        client._api_version = "2024-01"

        update = TrackingUpdate(
            order_id="12345",
            tracking_number="1ZTEST",
            carrier="UPS",
        )

        # Mock httpx to return a fulfilled order
        mock_response_order = MagicMock(spec=httpx.Response)
        mock_response_order.status_code = 200
        mock_response_order.json.return_value = {
            "order": {
                "fulfillment_status": "fulfilled",
                "fulfillments": [{"id": 999}],
            }
        }

        mock_response_update = MagicMock(spec=httpx.Response)
        mock_response_update.status_code = 200

        mock_http_client = AsyncMock(spec=httpx.AsyncClient)
        mock_http_client.get = AsyncMock(return_value=mock_response_order)
        mock_http_client.put = AsyncMock(return_value=mock_response_update)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            result = await client.update_tracking(update)

        assert result is True
        # Should have called PUT (update) not POST (create)
        mock_http_client.put.assert_called_once()
        assert "fulfillments/999" in str(mock_http_client.put.call_args)
