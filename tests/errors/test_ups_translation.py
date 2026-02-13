"""Tests for UPS error code translation to ShipAgent E-codes.

Covers new MCP preflight error codes (ELICITATION_UNSUPPORTED, INCOMPLETE_SHIPMENT,
MALFORMED_REQUEST, ELICITATION_DECLINED, ELICITATION_CANCELLED,
ELICITATION_INVALID_RESPONSE) and regressions for existing mappings.
"""

from src.errors.ups_translation import translate_ups_error


class TestMCPPreflightCodeMapping:
    """MCP preflight error codes map to correct ShipAgent E-codes."""

    def test_elicitation_unsupported_maps_to_e2010(self):
        """ELICITATION_UNSUPPORTED -> E-2010."""
        code, msg, _ = translate_ups_error(
            "ELICITATION_UNSUPPORTED",
            "Missing 5 required field(s)",
            context={"count": "5", "fields": "Shipper name, Recipient city"},
        )
        assert code == "E-2010"

    def test_incomplete_shipment_maps_to_e2010(self):
        """INCOMPLETE_SHIPMENT -> E-2010."""
        code, _, _ = translate_ups_error(
            "INCOMPLETE_SHIPMENT",
            "User filled form but some fields still empty",
            context={"count": "2", "fields": "Weight, Service code"},
        )
        assert code == "E-2010"

    def test_malformed_request_maps_to_e2011(self):
        """MALFORMED_REQUEST -> E-2011."""
        code, _, _ = translate_ups_error(
            "MALFORMED_REQUEST",
            "Ambiguous payer configuration",
        )
        assert code == "E-2011"

    def test_elicitation_declined_maps_to_e2012(self):
        """ELICITATION_DECLINED -> E-2012."""
        code, _, _ = translate_ups_error(
            "ELICITATION_DECLINED",
            "User declined the form",
        )
        assert code == "E-2012"

    def test_elicitation_cancelled_maps_to_e2012(self):
        """ELICITATION_CANCELLED -> E-2012."""
        code, _, _ = translate_ups_error(
            "ELICITATION_CANCELLED",
            "User cancelled the form",
        )
        assert code == "E-2012"

    def test_elicitation_invalid_response_maps_to_e4010(self):
        """ELICITATION_INVALID_RESPONSE -> E-4010."""
        code, _, _ = translate_ups_error(
            "ELICITATION_INVALID_RESPONSE",
            "Rehydration error: field conflict",
        )
        assert code == "E-4010"


class TestTemplateFormatting:
    """Context dict fills message template placeholders correctly."""

    def test_e2010_template_with_count_and_fields(self):
        """E-2010 template fills {count} and {fields} from context."""
        code, msg, remediation = translate_ups_error(
            "ELICITATION_UNSUPPORTED",
            "Missing required fields",
            context={"count": "3", "fields": "Shipper name, Recipient city, Weight"},
        )
        assert code == "E-2010"
        assert "3" in msg
        assert "Shipper name" in msg
        assert "Recipient city" in msg
        assert "Weight" in msg
        assert "missing" in remediation.lower() or "provide" in remediation.lower()

    def test_e2011_template_with_ups_message(self):
        """E-2011 template fills {ups_message}."""
        _, msg, _ = translate_ups_error(
            "MALFORMED_REQUEST",
            "Ambiguous payer configuration",
        )
        assert "Ambiguous payer configuration" in msg

    def test_e2012_template_with_ups_message(self):
        """E-2012 template fills {ups_message}."""
        _, msg, _ = translate_ups_error(
            "ELICITATION_DECLINED",
            "User declined the form",
        )
        assert "User declined the form" in msg


class TestRegressionExistingMappings:
    """Existing UPS error code mappings are unaffected by new additions."""

    def test_120100_maps_to_e3003(self):
        """UPS address validation error still maps to E-3003."""
        code, _, _ = translate_ups_error("120100", "Address validation failed")
        assert code == "E-3003"

    def test_111030_maps_to_e3004(self):
        """UPS service unavailable still maps to E-3004."""
        code, _, _ = translate_ups_error("111030", "Service not available")
        assert code == "E-3004"

    def test_250001_maps_to_e5001(self):
        """UPS auth failure still maps to E-5001."""
        code, _, _ = translate_ups_error("250001", "Invalid credentials")
        assert code == "E-5001"

    def test_190001_maps_to_e3001(self):
        """UPS system unavailable still maps to E-3001."""
        code, _, _ = translate_ups_error("190001", "System unavailable")
        assert code == "E-3001"

    def test_unknown_code_falls_to_e3005(self):
        """Unrecognized codes still fall through to E-3005."""
        code, _, _ = translate_ups_error("999999", "Something unusual happened")
        assert code == "E-3005"


class TestRegressionMessagePatterns:
    """Existing message pattern matching is unaffected."""

    def test_invalid_zip_pattern(self):
        """Pattern 'invalid zip' still maps to E-2001."""
        code, _, _ = translate_ups_error(None, "Invalid zip code format")
        assert code == "E-2001"

    def test_service_unavailable_pattern(self):
        """Pattern 'service unavailable' still maps to E-3001."""
        code, _, _ = translate_ups_error(None, "Service unavailable temporarily")
        assert code == "E-3001"

    def test_rate_limit_pattern(self):
        """Pattern 'rate limit' still maps to E-3002."""
        code, _, _ = translate_ups_error(None, "Rate limit exceeded for account")
        assert code == "E-3002"
