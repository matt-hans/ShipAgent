"""Tests for service override auto-reset in core.py."""

import json

from src.orchestrator.agent.tools.core import _build_job_row_data_with_metadata


class TestServiceOverrideAutoReset:
    """Auto-reset packaging when service override creates incompatibility."""

    def test_letter_reset_to_customer_supplied_on_ground_override(self):
        """UPS Letter packaging auto-resets to Customer Supplied for Ground."""
        rows = [{"ship_to_name": "Test", "packaging_type": "01", "weight": "0.5"}]
        result, _ = _build_job_row_data_with_metadata(rows, service_code_override="03")
        order_data = json.loads(result[0]["order_data"])
        assert order_data.get("packaging_type") != "01"
        assert order_data.get("_packaging_auto_reset") is not None

    def test_customer_supplied_unchanged_on_ground_override(self):
        """Customer Supplied packaging is not touched on Ground override."""
        rows = [{"ship_to_name": "Test", "packaging_type": "02", "weight": "5.0"}]
        result, _ = _build_job_row_data_with_metadata(rows, service_code_override="03")
        order_data = json.loads(result[0]["order_data"])
        assert "_packaging_auto_reset" not in order_data

    def test_saturday_delivery_stripped_for_ground(self):
        """Saturday Delivery flag is stripped when overriding to Ground."""
        rows = [{"ship_to_name": "Test", "saturday_delivery": "true"}]
        result, _ = _build_job_row_data_with_metadata(rows, service_code_override="03")
        order_data = json.loads(result[0]["order_data"])
        assert not order_data.get("saturday_delivery")
