"""Tests for international fields in preview route responses."""

import json
import uuid

from fastapi.testclient import TestClient

from src.api.main import app
from src.services.ups_service_codes import SERVICE_CODE_NAMES
from src.api.schemas import PreviewRowResponse, BatchPreviewResponse
from src.db.connection import get_db
from src.db.models import Job, JobRow


class TestServiceCodeNames:
    """Verify SERVICE_CODE_NAMES includes international services."""

    def test_worldwide_express(self):
        assert "07" in SERVICE_CODE_NAMES
        assert "Worldwide Express" in SERVICE_CODE_NAMES["07"]

    def test_worldwide_expedited(self):
        assert "08" in SERVICE_CODE_NAMES

    def test_ups_standard(self):
        assert "11" in SERVICE_CODE_NAMES

    def test_worldwide_express_plus(self):
        assert "54" in SERVICE_CODE_NAMES

    def test_worldwide_saver(self):
        assert "65" in SERVICE_CODE_NAMES

    def test_domestic_services_unchanged(self):
        assert SERVICE_CODE_NAMES["03"] == "UPS Ground"
        assert SERVICE_CODE_NAMES["01"] == "UPS Next Day Air"
        assert SERVICE_CODE_NAMES["02"] == "UPS 2nd Day Air"


class TestPreviewRowResponseInternationalFields:
    """P1: Verify PreviewRowResponse includes actual international fields."""

    def test_destination_country_field_exists(self):
        row = PreviewRowResponse(
            row_number=1, recipient_name="Jane Doe",
            city_state="Toronto, ON", service="UPS Standard",
            estimated_cost_cents=4550,
            destination_country="CA",
        )
        assert row.destination_country == "CA"

    def test_duties_taxes_cents_field_exists(self):
        row = PreviewRowResponse(
            row_number=1, recipient_name="Jane Doe",
            city_state="Toronto, ON", service="UPS Standard",
            estimated_cost_cents=4550,
            duties_taxes_cents=1200,
        )
        assert row.duties_taxes_cents == 1200

    def test_charge_breakdown_field_exists(self):
        breakdown = {
            "version": "1.0",
            "transportationCharges": {"monetaryValue": "45.50", "currencyCode": "USD"},
            "dutiesAndTaxes": {"monetaryValue": "12.00", "currencyCode": "USD"},
        }
        row = PreviewRowResponse(
            row_number=1, recipient_name="Jane Doe",
            city_state="Toronto, ON", service="UPS Standard",
            estimated_cost_cents=4550,
            charge_breakdown=breakdown,
        )
        assert row.charge_breakdown["version"] == "1.0"
        assert row.charge_breakdown["dutiesAndTaxes"]["monetaryValue"] == "12.00"

    def test_domestic_row_has_none_international_fields(self):
        row = PreviewRowResponse(
            row_number=1, recipient_name="John Doe",
            city_state="Los Angeles, CA", service="UPS Ground",
            estimated_cost_cents=1550,
        )
        assert row.destination_country is None
        assert row.duties_taxes_cents is None
        assert row.charge_breakdown is None


class TestBatchPreviewResponseInternationalAggregates:
    """P1: Verify BatchPreviewResponse includes international aggregates."""

    def test_total_duties_taxes_cents_field(self):
        resp = BatchPreviewResponse(
            job_id="test-123",
            total_rows=5,
            preview_rows=[],
            total_estimated_cost_cents=10000,
            total_duties_taxes_cents=2400,
            international_row_count=2,
        )
        assert resp.total_duties_taxes_cents == 2400
        assert resp.international_row_count == 2

    def test_domestic_only_batch_no_international_aggregates(self):
        resp = BatchPreviewResponse(
            job_id="test-456",
            total_rows=3,
            preview_rows=[],
            total_estimated_cost_cents=5000,
        )
        assert resp.total_duties_taxes_cents is None
        assert resp.international_row_count == 0


class TestPreviewRouteInternationalWiring:
    """P1: True route-level test — seeds DB rows with international data
    and asserts the /jobs/{id}/preview response contains them."""

    def setup_method(self):
        self.client = TestClient(app)
        self.db = next(get_db())
        self.job_id = str(uuid.uuid4())

        # Seed a job
        job = Job(
            id=self.job_id, name="intl-test", original_command="test",
            status="pending",
        )
        self.db.add(job)

        # Seed a domestic row
        domestic_row = JobRow(
            job_id=self.job_id, row_number=1, row_checksum="abc1",
            status="pending", cost_cents=1550,
            order_data=json.dumps({
                "ship_to_name": "John Doe",
                "ship_to_city": "Los Angeles", "ship_to_state": "CA",
                "service_code": "03",
            }),
        )
        self.db.add(domestic_row)

        # Seed an international row with charge_breakdown
        intl_breakdown = json.dumps({
            "version": "1.0",
            "transportationCharges": {"monetaryValue": "45.50", "currencyCode": "USD"},
            "dutiesAndTaxes": {"monetaryValue": "12.00", "currencyCode": "USD"},
        })
        intl_row = JobRow(
            job_id=self.job_id, row_number=2, row_checksum="abc2",
            status="pending", cost_cents=5750,
            destination_country="CA", duties_taxes_cents=1200,
            charge_breakdown=intl_breakdown,
            order_data=json.dumps({
                "ship_to_name": "Jane Doe",
                "ship_to_city": "Toronto", "ship_to_state": "ON",
                "service_code": "11",
            }),
        )
        self.db.add(intl_row)
        self.db.commit()

    def teardown_method(self):
        self.db.query(JobRow).filter(JobRow.job_id == self.job_id).delete()
        self.db.query(Job).filter(Job.id == self.job_id).delete()
        self.db.commit()
        self.db.close()

    def test_preview_returns_international_fields(self):
        """GET /jobs/{id}/preview must include destination_country, duties, breakdown."""
        resp = self.client.get(f"/api/v1/jobs/{self.job_id}/preview")
        assert resp.status_code == 200
        data = resp.json()

        # Row 1: domestic — no international fields
        row1 = data["preview_rows"][0]
        assert row1["row_number"] == 1
        assert row1.get("destination_country") is None
        assert row1.get("duties_taxes_cents") is None
        assert row1.get("charge_breakdown") is None

        # Row 2: international — all fields present
        row2 = data["preview_rows"][1]
        assert row2["row_number"] == 2
        assert row2["destination_country"] == "CA"
        assert row2["duties_taxes_cents"] == 1200
        assert row2["charge_breakdown"]["version"] == "1.0"
        assert row2["charge_breakdown"]["dutiesAndTaxes"]["monetaryValue"] == "12.00"

    def test_preview_returns_international_aggregates(self):
        """Batch-level aggregates must include duties total and intl count."""
        resp = self.client.get(f"/api/v1/jobs/{self.job_id}/preview")
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_duties_taxes_cents"] == 1200
        assert data["international_row_count"] == 1
