"""Tests for interactive shipment preview pipeline.

Covers the preview_interactive_shipment tool, persisted shipper execution,
write-back guarding, account masking, ship_from key normalization,
migration idempotency, orphan cleanup, and state transitions.
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models import JobStatus


# ---------------------------------------------------------------------------
# Helpers under test
# ---------------------------------------------------------------------------


class TestNormalizeShipFrom:
    """Tests for _normalize_ship_from() key/value normalization."""

    def test_normalizes_agent_facing_keys(self):
        """Agent-facing keys (address1, state, zip) map to canonical keys."""
        from src.orchestrator.agent.tools.interactive import _normalize_ship_from

        raw = {
            "address1": "789 Broadway",
            "city": "New York",
            "state": "NY",
            "zip": "10003",
        }
        result = _normalize_ship_from(raw)
        assert result == {
            "addressLine1": "789 Broadway",
            "city": "New York",
            "stateProvinceCode": "NY",
            "postalCode": "10003",
        }

    def test_drops_unknown_keys(self):
        """Unknown keys are silently dropped."""
        from src.orchestrator.agent.tools.interactive import _normalize_ship_from

        raw = {"foo": "bar", "baz": "qux", "city": "Austin"}
        result = _normalize_ship_from(raw)
        assert result == {"city": "Austin"}

    def test_skips_empty_values(self):
        """Empty string values don't override env defaults."""
        from src.orchestrator.agent.tools.interactive import _normalize_ship_from

        raw = {"city": "", "state": "TX", "zip": ""}
        result = _normalize_ship_from(raw)
        assert result == {"stateProvinceCode": "TX"}

    def test_skips_invalid_phone(self):
        """Short phone numbers that normalize to placeholder are dropped."""
        from src.orchestrator.agent.tools.interactive import _normalize_ship_from

        raw = {"phone": "123"}
        result = _normalize_ship_from(raw)
        assert "phone" not in result

    def test_normalizes_phone_and_zip(self):
        """Phone and ZIP values are normalized like env-derived shipper."""
        from src.orchestrator.agent.tools.interactive import _normalize_ship_from

        raw = {"phone": "(555) 123-4567", "zip": "90001-1234"}
        result = _normalize_ship_from(raw)
        assert result["phone"] == "5551234567"
        assert result["postalCode"] == "90001-1234"

    def test_coerces_numeric_values(self):
        """Numeric values (int/float) are coerced to str before normalization."""
        from src.orchestrator.agent.tools.interactive import _normalize_ship_from

        raw = {"zip": 90001, "phone": 5551234567}
        result = _normalize_ship_from(raw)
        assert result["postalCode"] == "90001"
        assert result["phone"] == "5551234567"


class TestMaskAccount:
    """Tests for _mask_account() helper."""

    def test_masks_normal_account(self):
        """Normal-length account shows first 2 and last 2 chars."""
        from src.orchestrator.agent.tools.interactive import _mask_account

        assert _mask_account("AB1234CD") == "AB****CD"

    def test_masks_short_account(self):
        """Accounts <= 4 chars return all stars."""
        from src.orchestrator.agent.tools.interactive import _mask_account

        assert _mask_account("AB") == "****"
        assert _mask_account("ABCD") == "****"

    def test_masks_six_char_account(self):
        """Six-char account masks middle 2."""
        from src.orchestrator.agent.tools.interactive import _mask_account

        assert _mask_account("123456") == "12**56"


# ---------------------------------------------------------------------------
# State transition
# ---------------------------------------------------------------------------


class TestPendingToFailedTransition:
    """Verify pending -> failed is now allowed."""

    def test_pending_to_failed_transition_allowed(self):
        """JobService state machine allows pending -> failed."""
        from src.services.job_service import VALID_TRANSITIONS

        assert JobStatus.failed in VALID_TRANSITIONS[JobStatus.pending]


# ---------------------------------------------------------------------------
# Migration idempotency
# ---------------------------------------------------------------------------


class TestEnsureColumnsExist:
    """Tests for _ensure_columns_exist() startup migration."""

    def test_idempotent_run(self, tmp_path):
        """Running _ensure_columns_exist twice doesn't error."""
        from sqlalchemy import create_engine, text

        from src.db.connection import _ensure_columns_exist
        from src.db.models import Base

        db_path = tmp_path / "test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(bind=engine)

        with engine.begin() as conn:
            _ensure_columns_exist(conn)
        # Second call should be a no-op
        with engine.begin() as conn:
            _ensure_columns_exist(conn)

        # Verify columns exist
        with engine.begin() as conn:
            result = conn.execute(text("PRAGMA table_info(jobs)"))
            columns = {row[1] for row in result.fetchall()}
        assert "shipper_json" in columns
        assert "is_interactive" in columns


# ---------------------------------------------------------------------------
# Preview tool integration tests
# ---------------------------------------------------------------------------


class TestPreviewInteractiveShipment:
    """Tests for preview_interactive_shipment_tool."""

    def _base_args(self, **overrides):
        """Build minimal valid tool args."""
        args = {
            "ship_to_name": "John Smith",
            "ship_to_address1": "456 Oak Ave",
            "ship_to_city": "Austin",
            "ship_to_state": "TX",
            "ship_to_zip": "78701",
            "service": "UPS Ground",
            "weight": 1.0,
            "command": "Ship to John Smith",
        }
        args.update(overrides)
        return args

    @pytest.mark.asyncio
    async def test_fails_without_account_number(self):
        """Early error when UPS_ACCOUNT_NUMBER is empty/missing."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        env = {
            "UPS_ACCOUNT_NUMBER": "",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
        }
        with patch.dict(os.environ, env, clear=False):
            result = await preview_interactive_shipment_tool(self._base_args())
        assert result["isError"] is True
        assert "UPS_ACCOUNT_NUMBER" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_none_required_fields_treated_as_missing(self):
        """None values in required fields are treated as empty, not 'None'."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        args = self._base_args()
        args["ship_to_name"] = None
        result = await preview_interactive_shipment_tool(args)
        assert result["isError"] is True
        assert "Missing required" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_missing_service_is_rejected(self):
        """Service is required and must be explicitly provided."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        result = await preview_interactive_shipment_tool(self._base_args(service=""))
        assert result["isError"] is True
        assert "service" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_missing_weight_is_rejected(self):
        """Weight is required and must be explicitly provided."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        result = await preview_interactive_shipment_tool(self._base_args(weight=None))
        assert result["isError"] is True
        assert "weight" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_international_gb_missing_state_is_blocked_before_preview(self):
        """GB shipments require recipient state/province before preview creation."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
            "SHIPPER_COUNTRY": "US",
            "SHIPPER_ATTENTION_NAME": "Warehouse Desk",
            "SHIPPER_PHONE": "12125551234",
            "INTERNATIONAL_ENABLED_LANES": "US-GB",
        }

        args = self._base_args(
            ship_to_state="",
            ship_to_country="GB",
            ship_to_phone="442079430800",
            ship_to_attention_name="Elizabeth Taylor",
            service="UPS Worldwide Saver",
            shipment_description="Books",
            commodities=[
                {
                    "description": "Books",
                    "commodity_code": "490199",
                    "origin_country": "US",
                    "quantity": 1,
                    "unit_value": "75.00",
                }
            ],
        )

        with patch.dict(os.environ, env, clear=False):
            result = await preview_interactive_shipment_tool(args)

        assert result["isError"] is True
        assert "state/province code is required" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_international_service_requires_explicit_country(self):
        """Worldwide/international services must provide destination country."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
        }

        args = self._base_args(
            ship_to_state="",
            service="UPS Worldwide Express",
        )

        with patch.dict(os.environ, env, clear=False):
            result = await preview_interactive_shipment_tool(args)

        assert result["isError"] is True
        assert "ship_to_country is required" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_uk_alias_normalizes_to_gb_for_state_validation(self):
        """Country alias 'UK' is normalized to GB before recipient-state checks."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
            "SHIPPER_COUNTRY": "US",
            "SHIPPER_ATTENTION_NAME": "Warehouse Desk",
            "SHIPPER_PHONE": "12125551234",
            "INTERNATIONAL_ENABLED_LANES": "US-GB",
        }

        args = self._base_args(
            ship_to_state="",
            ship_to_country="UK",
            ship_to_phone="442079430800",
            ship_to_attention_name="Elizabeth Taylor",
            service="UPS Worldwide Saver",
            shipment_description="Books",
            commodities=[
                {
                    "description": "Books",
                    "commodity_code": "490199",
                    "origin_country": "US",
                    "quantity": 1,
                    "unit_value": "75.00",
                }
            ],
        )

        with patch.dict(os.environ, env, clear=False):
            result = await preview_interactive_shipment_tool(args)

        assert result["isError"] is True
        assert "to GB" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_gb_state_cannot_match_postal_code(self):
        """Preview rejects GB addresses where state is copied from postal code."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
            "SHIPPER_COUNTRY": "US",
            "SHIPPER_ATTENTION_NAME": "Warehouse Desk",
            "SHIPPER_PHONE": "12125551234",
            "INTERNATIONAL_ENABLED_LANES": "US-GB",
        }

        args = self._base_args(
            ship_to_city="London",
            ship_to_country="GB",
            ship_to_state="W1J 7NT",
            ship_to_zip="W1J 7NT",
            ship_to_phone="+44 20 7493 0800",
            ship_to_attention_name="Elizabeth Taylor",
            service="UPS Worldwide Saver",
            shipment_description="Books",
            commodities=[
                {
                    "description": "Books",
                    "commodity_code": "490199",
                    "origin_country": "US",
                    "quantity": 1,
                    "unit_value": "75.00",
                }
            ],
        )

        with patch.dict(os.environ, env, clear=False):
            result = await preview_interactive_shipment_tool(args)

        assert result["isError"] is True
        assert "matches the postal code" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_includes_available_services_from_shop_discovery(self):
        """Interactive preview includes UPS Shop-discovered service options."""
        from src.orchestrator.agent.tools.core import EventEmitterBridge
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        mock_preview_result = {
            "job_id": "svc-discovery-test",
            "total_rows": 1,
            "preview_rows": [
                {
                    "row_number": 1,
                    "recipient_name": "John Smith",
                    "city_state": "Austin, TX",
                    "estimated_cost_cents": 1500,
                    "warnings": [],
                }
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 1500,
        }

        created_job = MagicMock()
        created_job.id = "svc-discovery-test"
        mock_job_service = MagicMock()
        mock_job_service.create_job.return_value = created_job
        mock_job_service.create_rows.return_value = [MagicMock()]
        mock_job_service.get_rows.return_value = [MagicMock()]

        mock_engine = AsyncMock()
        mock_engine.preview.return_value = mock_preview_result

        mock_ups = AsyncMock()
        mock_ups.get_rate.return_value = {
            "ratedShipments": [
                {
                    "serviceCode": "03",
                    "serviceName": "UPS Ground",
                    "totalCharges": {"monetaryValue": "15.00", "currencyCode": "USD"},
                },
                {
                    "serviceCode": "12",
                    "serviceName": "UPS 3 Day Select",
                    "totalCharges": {"monetaryValue": "22.00", "currencyCode": "USD"},
                },
            ]
        }
        bridge = EventEmitterBridge()
        emitted_events = []
        bridge.callback = lambda event_type, data: emitted_events.append((event_type, data))

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("src.orchestrator.agent.tools.interactive.get_db_context") as mock_db_ctx,
            patch("src.orchestrator.agent.tools.interactive._get_ups_client", return_value=mock_ups),
            patch("src.orchestrator.agent.tools.interactive.JobService", return_value=mock_job_service),
            patch("src.services.batch_engine.BatchEngine.preview", new=mock_engine.preview),
            patch("src.services.batch_engine.BatchEngine.__init__", return_value=None),
        ):
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = await preview_interactive_shipment_tool(self._base_args(), bridge=bridge)

        assert result["isError"] is False
        assert emitted_events
        event_type, event_data = emitted_events[0]
        assert event_type == "preview_ready"
        assert len(event_data.get("available_services", [])) == 2
        assert event_data["available_services"][0]["code"] == "03"
        assert event_data["available_services"][0]["selected"] is True

    @pytest.mark.asyncio
    async def test_explicit_unavailable_service_returns_error_with_options(self):
        """Explicit service is rejected when UPS Shop says it is unavailable."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        mock_ups = AsyncMock()
        mock_ups.get_rate.return_value = {
            "ratedShipments": [
                {
                    "serviceCode": "03",
                    "serviceName": "UPS Ground",
                    "totalCharges": {"monetaryValue": "15.00", "currencyCode": "USD"},
                },
                {
                    "serviceCode": "12",
                    "serviceName": "UPS 3 Day Select",
                    "totalCharges": {"monetaryValue": "22.00", "currencyCode": "USD"},
                },
            ]
        }

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("src.orchestrator.agent.tools.interactive._get_ups_client", return_value=mock_ups),
        ):
            result = await preview_interactive_shipment_tool(
                self._base_args(service="Next Day Air")
            )

        assert result["isError"] is True
        assert "Requested service" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_none_optional_fields_not_polluted(self):
        """None in optional fields becomes empty string, not 'None'."""
        from src.orchestrator.agent.tools.core import EventEmitterBridge
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        mock_preview_result = {
            "job_id": "none-opt-test",
            "total_rows": 1,
            "preview_rows": [
                {
                    "row_number": 1,
                    "recipient_name": "John Smith",
                    "city_state": "Austin, TX",
                    "estimated_cost_cents": 1500,
                    "warnings": [],
                }
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 1500,
        }

        created_job = MagicMock()
        created_job.id = "none-opt-test"
        mock_job_service = MagicMock()
        mock_job_service.create_job.return_value = created_job
        mock_job_service.create_rows.return_value = [MagicMock()]
        mock_job_service.get_rows.return_value = [MagicMock()]

        mock_engine = AsyncMock()
        mock_engine.preview.return_value = mock_preview_result

        bridge = EventEmitterBridge()
        emitted_events: list[tuple] = []
        bridge.callback = lambda et, d: emitted_events.append((et, d))

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
        }

        args = self._base_args(ship_to_phone=None, ship_to_address2=None)

        with (
            patch.dict(os.environ, env, clear=False),
            patch("src.orchestrator.agent.tools.interactive.get_db_context") as mock_db_ctx,
            patch("src.orchestrator.agent.tools.interactive._get_ups_client", return_value=AsyncMock()),
            patch("src.orchestrator.agent.tools.interactive.JobService", return_value=mock_job_service),
            patch("src.services.batch_engine.BatchEngine.preview", new=mock_engine.preview),
            patch("src.services.batch_engine.BatchEngine.__init__", return_value=None),
        ):
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = await preview_interactive_shipment_tool(args, bridge=bridge)

        assert result["isError"] is False
        # ship_to metadata is on the SSE event, not the slim LLM response
        _, event_data = emitted_events[0]
        ship_to = event_data["ship_to"]
        assert ship_to["phone"] == ""
        assert ship_to["address2"] == ""

    @pytest.mark.asyncio
    async def test_fails_on_invalid_weight_string(self):
        """Non-numeric weight returns structured error, not uncaught exception."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        result = await preview_interactive_shipment_tool(
            self._base_args(weight="abc")
        )
        assert result["isError"] is True
        assert "Invalid weight" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_fails_on_negative_weight(self):
        """Negative weight returns structured error."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        result = await preview_interactive_shipment_tool(
            self._base_args(weight=-2.5)
        )
        assert result["isError"] is True
        assert "positive" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_non_string_packaging_type_does_not_crash(self):
        """Non-string packaging_type (int, dict) is coerced, not crash."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        mock_preview_result = {
            "job_id": "pkg-int-test",
            "total_rows": 1,
            "preview_rows": [
                {
                    "row_number": 1,
                    "recipient_name": "John Smith",
                    "city_state": "Austin, TX",
                    "estimated_cost_cents": 1500,
                    "warnings": [],
                }
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 1500,
        }

        created_job = MagicMock()
        created_job.id = "pkg-int-test"
        mock_job_service = MagicMock()
        mock_job_service.create_job.return_value = created_job
        mock_job_service.create_rows.return_value = [MagicMock()]
        mock_job_service.get_rows.return_value = [MagicMock()]

        mock_engine = AsyncMock()
        mock_engine.preview.return_value = mock_preview_result

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("src.orchestrator.agent.tools.interactive.get_db_context") as mock_db_ctx,
            patch("src.orchestrator.agent.tools.interactive._get_ups_client", return_value=AsyncMock()),
            patch("src.orchestrator.agent.tools.interactive.JobService", return_value=mock_job_service),
            patch("src.services.batch_engine.BatchEngine.preview", new=mock_engine.preview),
            patch("src.services.batch_engine.BatchEngine.__init__", return_value=None),
        ):
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            # Integer packaging_type — should coerce to "2", not crash
            result = await preview_interactive_shipment_tool(
                self._base_args(packaging_type=2)
            )

        assert result["isError"] is False

    @pytest.mark.asyncio
    async def test_explicit_service_is_passed_to_preview_engine(self):
        """Explicit service preference resolves to service_code for preview()."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        mock_preview_result = {
            "job_id": "svc-test",
            "total_rows": 1,
            "preview_rows": [
                {
                    "row_number": 1,
                    "recipient_name": "John Smith",
                    "city_state": "Austin, TX",
                    "estimated_cost_cents": 1500,
                    "warnings": [],
                }
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 1500,
        }

        created_job = MagicMock()
        created_job.id = "svc-test"
        mock_job_service = MagicMock()
        mock_job_service.create_job.return_value = created_job
        mock_job_service.create_rows.return_value = [MagicMock()]
        mock_job_service.get_rows.return_value = [MagicMock()]

        mock_engine = AsyncMock()
        mock_engine.preview.return_value = mock_preview_result

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("src.orchestrator.agent.tools.interactive.get_db_context") as mock_db_ctx,
            patch("src.orchestrator.agent.tools.interactive._get_ups_client", return_value=AsyncMock()),
            patch("src.orchestrator.agent.tools.interactive.JobService", return_value=mock_job_service),
            patch("src.services.batch_engine.BatchEngine.preview", new=mock_engine.preview),
            patch("src.services.batch_engine.BatchEngine.__init__", return_value=None),
        ):
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = await preview_interactive_shipment_tool(
                self._base_args(service="Next Day Air")
            )

        assert result["isError"] is False
        assert mock_engine.preview.await_args.kwargs["service_code"] == "01"

    @pytest.mark.asyncio
    async def test_international_fields_added_to_order_data(self):
        """Interactive args include commodity/invoice/export fields on stored row data."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        mock_preview_result = {
            "job_id": "intl-fields-test",
            "total_rows": 1,
            "preview_rows": [
                {
                    "row_number": 1,
                    "recipient_name": "John Smith",
                    "city_state": "Toronto, ON",
                    "estimated_cost_cents": 2500,
                    "warnings": [],
                }
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 2500,
        }

        created_job = MagicMock()
        created_job.id = "intl-fields-test"
        mock_job_service = MagicMock()
        mock_job_service.create_job.return_value = created_job
        mock_job_service.create_rows.return_value = [MagicMock()]
        mock_job_service.get_rows.return_value = [MagicMock()]

        mock_engine = AsyncMock()
        mock_engine.preview.return_value = mock_preview_result

        commodities = [
            {
                "description": "Coffee Beans",
                "commodity_code": "090111",
                "origin_country": "CO",
                "quantity": 2,
                "unit_value": "25.00",
            }
        ]

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
            "SHIPPER_ATTENTION_NAME": "Warehouse Desk",
            "SHIPPER_PHONE": "2125557890",
            "INTERNATIONAL_ENABLED_LANES": "US-CA",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("src.orchestrator.agent.tools.interactive.get_db_context") as mock_db_ctx,
            patch("src.orchestrator.agent.tools.interactive._get_ups_client", return_value=AsyncMock()),
            patch("src.orchestrator.agent.tools.interactive.JobService", return_value=mock_job_service),
            patch("src.services.batch_engine.BatchEngine.preview", new=mock_engine.preview),
            patch("src.services.batch_engine.BatchEngine.__init__", return_value=None),
            patch(
                "src.orchestrator.agent.tools.interactive._build_job_row_data",
                side_effect=lambda rows: rows,
            ) as mock_build,
        ):
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = await preview_interactive_shipment_tool(
                self._base_args(
                    ship_to_country="ca",
                    ship_to_attention_name="Jane Doe",
                    ship_to_phone="4165551234",
                    service="UPS Standard",
                    shipment_description="Coffee beans for resale",
                    commodities=commodities,
                    invoice_currency_code="usd",
                    invoice_monetary_value="50.00",
                    invoice_number="CI-2026-0009",
                    reason_for_export="sale",
                )
            )

        assert result["isError"] is False
        order_data = mock_build.call_args[0][0][0]
        assert order_data["ship_to_country"] == "CA"
        assert order_data["commodities"] == commodities
        assert order_data["invoice_currency_code"] == "USD"
        assert order_data["invoice_monetary_value"] == "50.00"
        assert order_data["invoice_number"] == "CI-2026-0009"
        assert order_data["reason_for_export"] == "SALE"
        assert order_data["shipper_attention_name"] == "Warehouse Desk"
        assert order_data["shipper_phone"] == "2125557890"

    @pytest.mark.asyncio
    async def test_international_attention_defaults_to_recipient_name(self):
        """When attention is omitted, interactive flow defaults it to ship_to_name."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        mock_preview_result = {
            "job_id": "intl-attn-default-test",
            "total_rows": 1,
            "preview_rows": [
                {
                    "row_number": 1,
                    "recipient_name": "Franz Becker",
                    "city_state": "Berlin, BE",
                    "estimated_cost_cents": 4100,
                    "warnings": [],
                }
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 4100,
        }

        created_job = MagicMock()
        created_job.id = "intl-attn-default-test"
        mock_job_service = MagicMock()
        mock_job_service.create_job.return_value = created_job
        mock_job_service.create_rows.return_value = [MagicMock()]
        mock_job_service.get_rows.return_value = [MagicMock()]

        mock_engine = AsyncMock()
        mock_engine.preview.return_value = mock_preview_result

        mock_ups = AsyncMock()
        mock_ups.get_rate.return_value = {
            "ratedShipments": [
                {
                    "serviceCode": "65",
                    "serviceName": "UPS Worldwide Saver",
                    "totalCharges": {"monetaryValue": "41.00", "currencyCode": "USD"},
                }
            ]
        }

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
            "SHIPPER_COUNTRY": "US",
            "SHIPPER_ATTENTION_NAME": "Warehouse Desk",
            "SHIPPER_PHONE": "2125557890",
            "INTERNATIONAL_ENABLED_LANES": "US-DE",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("src.orchestrator.agent.tools.interactive.get_db_context") as mock_db_ctx,
            patch("src.orchestrator.agent.tools.interactive._get_ups_client", return_value=mock_ups),
            patch("src.orchestrator.agent.tools.interactive.JobService", return_value=mock_job_service),
            patch("src.services.batch_engine.BatchEngine.preview", new=mock_engine.preview),
            patch("src.services.batch_engine.BatchEngine.__init__", return_value=None),
            patch(
                "src.orchestrator.agent.tools.interactive._build_job_row_data",
                side_effect=lambda rows: rows,
            ) as mock_build,
        ):
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = await preview_interactive_shipment_tool(
                self._base_args(
                    ship_to_name="Franz Becker",
                    ship_to_city="Berlin",
                    ship_to_state="BE",
                    ship_to_zip="10117",
                    ship_to_country="DE",
                    ship_to_phone="+49 30 1234 5678",
                    service="UPS Worldwide Saver",
                    shipment_description="Mechanical parts",
                    commodities=[{
                        "description": "Mechanical parts",
                        "commodity_code": "848790",
                        "origin_country": "US",
                        "quantity": 1,
                        "unit_value": "150.00",
                    }],
                )
            )

        assert result["isError"] is False
        order_data = mock_build.call_args[0][0][0]
        assert order_data["ship_to_attention_name"] == "Franz Becker"

    @pytest.mark.asyncio
    async def test_creates_job_with_interactive_flag(self):
        """Job created with is_interactive=True and shipper_json set."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        mock_preview_result = {
            "job_id": "test-job-id",
            "total_rows": 1,
            "preview_rows": [
                {
                    "row_number": 1,
                    "recipient_name": "John Smith",
                    "city_state": "Austin, TX",
                    "estimated_cost_cents": 1500,
                    "warnings": [],
                }
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 1500,
        }

        created_job = MagicMock()
        created_job.id = "test-job-id"
        created_job.is_interactive = False
        created_job.shipper_json = None

        mock_job_service = MagicMock()
        mock_job_service.create_job.return_value = created_job
        mock_job_service.create_rows.return_value = [MagicMock()]
        mock_job_service.get_rows.return_value = [MagicMock()]

        mock_engine = AsyncMock()
        mock_engine.preview.return_value = mock_preview_result

        mock_ups = AsyncMock()

        env = {
            "UPS_ACCOUNT_NUMBER": "AB1234CD",
            "SHIPPER_NAME": "Test Shipper",
            "SHIPPER_ADDRESS1": "123 Main St",
            "SHIPPER_CITY": "Los Angeles",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("src.orchestrator.agent.tools.interactive.get_db_context") as mock_db_ctx,
            patch("src.orchestrator.agent.tools.interactive._get_ups_client", return_value=mock_ups),
            patch("src.orchestrator.agent.tools.interactive.JobService", return_value=mock_job_service),
            patch("src.services.batch_engine.BatchEngine.preview", new=mock_engine.preview),
            patch("src.services.batch_engine.BatchEngine.__init__", return_value=None),
        ):
            mock_db = MagicMock()
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = await preview_interactive_shipment_tool(self._base_args())

        assert result["isError"] is False
        # Verify is_interactive and shipper_json were set on the job
        assert created_job.is_interactive is True
        assert created_job.shipper_json is not None
        shipper_data = json.loads(created_job.shipper_json)
        assert shipper_data["name"] == "Test Shipper"

    @pytest.mark.asyncio
    async def test_uses_env_shipper_defaults(self):
        """Shipper comes from env vars when no ship_from override."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        mock_preview_result = {
            "job_id": "test-job-id",
            "total_rows": 1,
            "preview_rows": [
                {
                    "row_number": 1,
                    "recipient_name": "John Smith",
                    "city_state": "Austin, TX",
                    "estimated_cost_cents": 1500,
                    "warnings": [],
                }
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 1500,
        }

        created_job = MagicMock()
        created_job.id = "test-job-id"

        mock_job_service = MagicMock()
        mock_job_service.create_job.return_value = created_job
        mock_job_service.create_rows.return_value = [MagicMock()]
        mock_job_service.get_rows.return_value = [MagicMock()]

        mock_engine = AsyncMock()
        mock_engine.preview.return_value = mock_preview_result

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Env Shipper",
            "SHIPPER_ADDRESS1": "999 Env St",
            "SHIPPER_CITY": "Denver",
            "SHIPPER_STATE": "CO",
            "SHIPPER_ZIP": "80201",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("src.orchestrator.agent.tools.interactive.get_db_context") as mock_db_ctx,
            patch("src.orchestrator.agent.tools.interactive._get_ups_client", return_value=AsyncMock()),
            patch("src.orchestrator.agent.tools.interactive.JobService", return_value=mock_job_service),
            patch("src.services.batch_engine.BatchEngine.preview", new=mock_engine.preview),
            patch("src.services.batch_engine.BatchEngine.__init__", return_value=None),
        ):
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = await preview_interactive_shipment_tool(self._base_args())

        assert result["isError"] is False
        # Verify the shipper_json was set with env values
        shipper_data = json.loads(created_job.shipper_json)
        assert shipper_data["name"] == "Env Shipper"
        assert shipper_data["city"] == "Denver"

    @pytest.mark.asyncio
    async def test_merges_ship_from_override(self):
        """ship_from override normalizes keys and merges onto env defaults."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        mock_preview_result = {
            "job_id": "test-job-id",
            "total_rows": 1,
            "preview_rows": [
                {
                    "row_number": 1,
                    "recipient_name": "John Smith",
                    "city_state": "Austin, TX",
                    "estimated_cost_cents": 1500,
                    "warnings": [],
                }
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 1500,
        }

        created_job = MagicMock()
        created_job.id = "test-job-id"

        mock_job_service = MagicMock()
        mock_job_service.create_job.return_value = created_job
        mock_job_service.create_rows.return_value = [MagicMock()]
        mock_job_service.get_rows.return_value = [MagicMock()]

        mock_engine = AsyncMock()
        mock_engine.preview.return_value = mock_preview_result

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Env Shipper",
            "SHIPPER_ADDRESS1": "999 Env St",
            "SHIPPER_CITY": "Denver",
            "SHIPPER_STATE": "CO",
            "SHIPPER_ZIP": "80201",
        }

        args = self._base_args(
            ship_from={
                "address1": "789 Broadway",
                "city": "New York",
                "state": "NY",
                "zip": "10003",
            }
        )

        with (
            patch.dict(os.environ, env, clear=False),
            patch("src.orchestrator.agent.tools.interactive.get_db_context") as mock_db_ctx,
            patch("src.orchestrator.agent.tools.interactive._get_ups_client", return_value=AsyncMock()),
            patch("src.orchestrator.agent.tools.interactive.JobService", return_value=mock_job_service),
            patch("src.services.batch_engine.BatchEngine.preview", new=mock_engine.preview),
            patch("src.services.batch_engine.BatchEngine.__init__", return_value=None),
        ):
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = await preview_interactive_shipment_tool(args)

        assert result["isError"] is False
        shipper_data = json.loads(created_job.shipper_json)
        # Override values take precedence
        assert shipper_data["addressLine1"] == "789 Broadway"
        assert shipper_data["city"] == "New York"
        assert shipper_data["stateProvinceCode"] == "NY"
        assert shipper_data["postalCode"] == "10003"
        # Env values fill gaps
        assert shipper_data["name"] == "Env Shipper"

    @pytest.mark.asyncio
    async def test_emits_interactive_flag(self):
        """SSE event includes interactive=True in result."""
        from src.orchestrator.agent.tools.core import EventEmitterBridge
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        mock_preview_result = {
            "job_id": "test-job-id",
            "total_rows": 1,
            "preview_rows": [
                {
                    "row_number": 1,
                    "recipient_name": "John Smith",
                    "city_state": "Austin, TX",
                    "estimated_cost_cents": 1500,
                    "warnings": [],
                }
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 1500,
        }

        created_job = MagicMock()
        created_job.id = "test-job-id"
        mock_job_service = MagicMock()
        mock_job_service.create_job.return_value = created_job
        mock_job_service.create_rows.return_value = [MagicMock()]
        mock_job_service.get_rows.return_value = [MagicMock()]

        mock_engine = AsyncMock()
        mock_engine.preview.return_value = mock_preview_result

        bridge = EventEmitterBridge()
        emitted_events = []
        bridge.callback = lambda event_type, data: emitted_events.append((event_type, data))

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("src.orchestrator.agent.tools.interactive.get_db_context") as mock_db_ctx,
            patch("src.orchestrator.agent.tools.interactive._get_ups_client", return_value=AsyncMock()),
            patch("src.orchestrator.agent.tools.interactive.JobService", return_value=mock_job_service),
            patch("src.services.batch_engine.BatchEngine.preview", new=mock_engine.preview),
            patch("src.services.batch_engine.BatchEngine.__init__", return_value=None),
        ):
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            await preview_interactive_shipment_tool(self._base_args(), bridge=bridge)

        assert len(emitted_events) == 1
        event_type, event_data = emitted_events[0]
        assert event_type == "preview_ready"
        assert event_data.get("interactive") is True

    @pytest.mark.asyncio
    async def test_includes_resolved_payload(self):
        """Result includes resolved_payload for expandable view."""
        from src.orchestrator.agent.tools.core import EventEmitterBridge
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        mock_preview_result = {
            "job_id": "test-job-id",
            "total_rows": 1,
            "preview_rows": [
                {
                    "row_number": 1,
                    "recipient_name": "John Smith",
                    "city_state": "Austin, TX",
                    "estimated_cost_cents": 1500,
                    "warnings": [],
                }
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 1500,
        }

        created_job = MagicMock()
        created_job.id = "test-job-id"
        mock_job_service = MagicMock()
        mock_job_service.create_job.return_value = created_job
        mock_job_service.create_rows.return_value = [MagicMock()]
        mock_job_service.get_rows.return_value = [MagicMock()]

        mock_engine = AsyncMock()
        mock_engine.preview.return_value = mock_preview_result

        bridge = EventEmitterBridge()
        emitted_events = []
        bridge.callback = lambda et, d: emitted_events.append((et, d))

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("src.orchestrator.agent.tools.interactive.get_db_context") as mock_db_ctx,
            patch("src.orchestrator.agent.tools.interactive._get_ups_client", return_value=AsyncMock()),
            patch("src.orchestrator.agent.tools.interactive.JobService", return_value=mock_job_service),
            patch("src.services.batch_engine.BatchEngine.preview", new=mock_engine.preview),
            patch("src.services.batch_engine.BatchEngine.__init__", return_value=None),
        ):
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            await preview_interactive_shipment_tool(self._base_args(), bridge=bridge)

        _, event_data = emitted_events[0]
        assert "resolved_payload" in event_data
        assert isinstance(event_data["resolved_payload"], dict)

    @pytest.mark.asyncio
    async def test_stores_raw_packaging_type_in_order_data(self):
        """order_data stores raw packaging_type, not pre-resolved code.

        This prevents double-resolution that corrupts alphanumeric codes
        like '2a' (small express box) → '02' (customer supplied).
        """
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        mock_preview_result = {
            "job_id": "pkg-test",
            "total_rows": 1,
            "preview_rows": [
                {
                    "row_number": 1,
                    "recipient_name": "John Smith",
                    "city_state": "Austin, TX",
                    "estimated_cost_cents": 1500,
                    "warnings": [],
                }
            ],
            "additional_rows": 0,
            "total_estimated_cost_cents": 1500,
        }

        created_job = MagicMock()
        created_job.id = "pkg-test"
        mock_job_service = MagicMock()
        mock_job_service.create_job.return_value = created_job
        mock_job_service.create_rows.return_value = [MagicMock()]
        mock_job_service.get_rows.return_value = [MagicMock()]

        mock_engine = AsyncMock()
        mock_engine.preview.return_value = mock_preview_result

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("src.orchestrator.agent.tools.interactive.get_db_context") as mock_db_ctx,
            patch("src.orchestrator.agent.tools.interactive._get_ups_client", return_value=AsyncMock()),
            patch("src.orchestrator.agent.tools.interactive.JobService", return_value=mock_job_service),
            patch("src.services.batch_engine.BatchEngine.preview", new=mock_engine.preview),
            patch("src.services.batch_engine.BatchEngine.__init__", return_value=None),
            patch(
                "src.orchestrator.agent.tools.interactive._build_job_row_data",
                side_effect=lambda rows: rows,
            ) as mock_build,
        ):
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            await preview_interactive_shipment_tool(
                self._base_args(packaging_type="small express box")
            )

        # _build_job_row_data receives order_data with raw packaging_type
        call_args = mock_build.call_args[0][0]
        assert call_args[0]["packaging_type"] == "small express box"

    @pytest.mark.asyncio
    async def test_cleans_up_orphan_job_on_row_failure(self):
        """When create_rows fails, orphan job is deleted."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        created_job = MagicMock()
        created_job.id = "orphan-job"

        mock_job_service = MagicMock()
        mock_job_service.create_job.return_value = created_job
        mock_job_service.create_rows.side_effect = RuntimeError("row insert failed")

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("src.orchestrator.agent.tools.interactive.get_db_context") as mock_db_ctx,
            patch("src.orchestrator.agent.tools.interactive._get_ups_client", return_value=AsyncMock()),
            patch("src.orchestrator.agent.tools.interactive.JobService", return_value=mock_job_service),
        ):
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = await preview_interactive_shipment_tool(self._base_args())

        assert result["isError"] is True
        assert "Failed to create shipment row" in result["content"][0]["text"]
        mock_job_service.delete_job.assert_called_once_with("orphan-job")

    @pytest.mark.asyncio
    async def test_marks_job_failed_on_rate_error(self):
        """When BatchEngine.preview() raises, job transitions to failed."""
        from src.orchestrator.agent.tools.interactive import preview_interactive_shipment_tool

        created_job = MagicMock()
        created_job.id = "rate-fail-job"

        mock_job_service = MagicMock()
        mock_job_service.create_job.return_value = created_job
        mock_job_service.create_rows.return_value = [MagicMock()]
        mock_job_service.get_rows.return_value = [MagicMock()]

        mock_engine = AsyncMock()
        mock_engine.preview.side_effect = RuntimeError("UPS API timeout")

        env = {
            "UPS_ACCOUNT_NUMBER": "TEST123",
            "SHIPPER_NAME": "Test",
            "SHIPPER_ADDRESS1": "123 Main",
            "SHIPPER_CITY": "LA",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "90001",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch("src.orchestrator.agent.tools.interactive.get_db_context") as mock_db_ctx,
            patch("src.orchestrator.agent.tools.interactive._get_ups_client", return_value=AsyncMock()),
            patch("src.orchestrator.agent.tools.interactive.JobService", return_value=mock_job_service),
            patch("src.services.batch_engine.BatchEngine.preview", new=mock_engine.preview),
            patch("src.services.batch_engine.BatchEngine.__init__", return_value=None),
        ):
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = await preview_interactive_shipment_tool(self._base_args())

        assert result["isError"] is True
        assert "Rating failed" in result["content"][0]["text"]
        mock_job_service.update_status.assert_called_once_with(
            "rate-fail-job", JobStatus.failed
        )


# ---------------------------------------------------------------------------
# Execution path tests
# ---------------------------------------------------------------------------


class TestExecutionUsesPersistedShipper:
    """Tests for _execute_batch shipper resolution via mocked execution path.

    These test the actual runtime branch in preview.py (line 226) that
    selects between persisted shipper_json, env shipper, and Shopify shipper.
    """

    def _make_mock_db(self, mock_job):
        """Build a mock DB session with proper query chaining."""
        mock_db = MagicMock()
        # db.query(Job).filter(...).first() → mock_job
        query_chain = MagicMock()
        query_chain.filter.return_value.first.return_value = mock_job
        # db.query(JobRow).filter(...).order_by(...).all() → []
        query_chain.filter.return_value.order_by.return_value.all.return_value = []
        mock_db.query.return_value = query_chain
        return mock_db

    @pytest.mark.asyncio
    async def test_execute_uses_persisted_shipper(self):
        """When job.shipper_json is set, execution uses it instead of env."""
        from src.db.models import Job, JobRow

        persisted = {
            "name": "Persisted Shipper",
            "addressLine1": "789 Broadway",
            "city": "New York",
            "stateProvinceCode": "NY",
            "postalCode": "10003",
            "countryCode": "US",
        }

        mock_job = MagicMock(spec=Job)
        mock_job.id = "persisted-test"
        mock_job.shipper_json = json.dumps(persisted)
        mock_job.is_interactive = True

        mock_db = self._make_mock_db(mock_job)

        mock_ups_cm = AsyncMock()
        mock_ups_cm.__aenter__ = AsyncMock(return_value=mock_ups_cm)
        mock_ups_cm.__aexit__ = AsyncMock(return_value=False)

        mock_be_instance = MagicMock()
        mock_be_instance.execute = AsyncMock(return_value={
            "successful": 0, "failed": 0, "total_cost_cents": 0,
            "write_back": {"status": "skipped", "message": "No rows"},
        })

        def mock_get_db():
            yield mock_db

        with (
            patch("src.api.routes.preview._get_sse_observer", return_value=AsyncMock()),
            patch("src.db.connection.get_db", mock_get_db),
            patch("src.services.batch_executor.UPSMCPClient", return_value=mock_ups_cm),
            patch("src.services.batch_executor.BatchEngine", return_value=mock_be_instance),
            patch.dict(os.environ, {
                "UPS_ACCOUNT_NUMBER": "X",
                "UPS_BASE_URL": "https://wwwcie.ups.com",
                "UPS_CLIENT_ID": "test",
                "UPS_CLIENT_SECRET": "test",
            }),
        ):
            from src.api.routes.preview import _execute_batch

            await _execute_batch("persisted-test")

            # Assert BatchEngine.execute received the persisted shipper
            mock_be_instance.execute.assert_awaited_once()
            call_kwargs = mock_be_instance.execute.call_args.kwargs
            assert call_kwargs["shipper"] == persisted

    @pytest.mark.asyncio
    async def test_falls_back_on_malformed_shipper_json(self):
        """Invalid JSON in shipper_json falls back to build_shipper()."""
        from src.db.models import Job, JobRow

        env_shipper = {"name": "Env Shipper", "addressLine1": "100 Main St"}

        mock_job = MagicMock(spec=Job)
        mock_job.id = "malformed-test"
        mock_job.shipper_json = "not valid json {"
        mock_job.is_interactive = True

        mock_db = self._make_mock_db(mock_job)

        mock_ups_cm = AsyncMock()
        mock_ups_cm.__aenter__ = AsyncMock(return_value=mock_ups_cm)
        mock_ups_cm.__aexit__ = AsyncMock(return_value=False)

        mock_be_instance = MagicMock()
        mock_be_instance.execute = AsyncMock(return_value={
            "successful": 0, "failed": 0, "total_cost_cents": 0,
            "write_back": {"status": "skipped", "message": "No rows"},
        })

        def mock_get_db():
            yield mock_db

        with (
            patch("src.api.routes.preview._get_sse_observer", return_value=AsyncMock()),
            patch("src.db.connection.get_db", mock_get_db),
            patch("src.services.batch_executor.UPSMCPClient", return_value=mock_ups_cm),
            patch("src.services.batch_executor.BatchEngine", return_value=mock_be_instance),
            patch("src.services.ups_payload_builder.build_shipper", return_value=env_shipper) as mock_env,
            patch.dict(os.environ, {
                "UPS_ACCOUNT_NUMBER": "X",
                "UPS_BASE_URL": "https://wwwcie.ups.com",
                "UPS_CLIENT_ID": "test",
                "UPS_CLIENT_SECRET": "test",
            }),
        ):
            from src.api.routes.preview import _execute_batch

            await _execute_batch("malformed-test")

            # Assert fallback to build_shipper was called
            mock_env.assert_called_once()
            # Assert BatchEngine.execute received the env shipper
            call_kwargs = mock_be_instance.execute.call_args.kwargs
            assert call_kwargs["shipper"] == env_shipper


class TestWriteBackGuard:
    """Tests for write_back_enabled parameter on BatchEngine.execute()."""

    @pytest.mark.asyncio
    async def test_writeback_skipped_when_disabled(self):
        """Write-back is skipped when write_back_enabled=False."""
        from src.services.batch_engine import BatchEngine

        engine = BatchEngine.__new__(BatchEngine)
        engine._ups = AsyncMock()
        engine._db = MagicMock()
        engine._account_number = "TEST123"
        engine._labels_dir = "/tmp/labels"

        # No rows to process — just verify the parameter is accepted
        result = await engine.execute(
            job_id="test-job",
            rows=[],
            shipper={"name": "Test"},
            write_back_enabled=False,
        )
        assert result["write_back"]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_writeback_enabled_by_default(self):
        """Write-back is enabled by default (write_back_enabled=True)."""
        from src.services.batch_engine import BatchEngine

        engine = BatchEngine.__new__(BatchEngine)
        engine._ups = AsyncMock()
        engine._db = MagicMock()
        engine._account_number = "TEST123"
        engine._labels_dir = "/tmp/labels"

        result = await engine.execute(
            job_id="test-job",
            rows=[],
            shipper={"name": "Test"},
        )
        # No rows processed, so write-back has "no updates" message
        assert result["write_back"]["status"] == "skipped"
        assert "No successful" in result["write_back"]["message"]


# ---------------------------------------------------------------------------
# Hook enforcement
# ---------------------------------------------------------------------------


class TestHookDeniesCreateShipmentInteractive:
    """Verify create_shipment is denied in interactive mode."""

    @pytest.mark.asyncio
    async def test_hook_denies_create_shipment_in_interactive_mode(self):
        """Hook returns deny with correct message for interactive mode."""
        from src.orchestrator.agent.hooks import create_shipping_hook

        hook = create_shipping_hook(interactive_shipping=True)
        result = await hook(
            {"tool_name": "mcp__ups__create_shipment", "tool_input": {"request_body": {}}},
            "test-id",
            None,
        )
        assert "deny" in str(result)
        assert "preview_interactive_shipment" in str(result)
