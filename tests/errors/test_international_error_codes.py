"""Tests for international shipping error codes."""

from src.errors.registry import ErrorCategory, get_error


class TestInternationalErrorCodes:
    """Verify international error codes are registered and well-formed."""

    def test_e2013_missing_international_field(self):
        err = get_error("E-2013")
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert "{field_name}" in err.message_template
        assert err.is_retryable is False

    def test_e2014_invalid_hs_code(self):
        err = get_error("E-2014")
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert "{hs_code}" in err.message_template

    def test_e2015_unsupported_lane(self):
        err = get_error("E-2015")
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert "{origin}" in err.message_template
        assert "{destination}" in err.message_template

    def test_e2016_service_not_available_for_lane(self):
        err = get_error("E-2016")
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert "{service}" in err.message_template

    def test_e2017_currency_mismatch(self):
        err = get_error("E-2017")
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION

    def test_e3006_customs_validation_failed(self):
        err = get_error("E-3006")
        assert err is not None
        assert err.category == ErrorCategory.UPS_API
        assert "{ups_message}" in err.message_template

    def test_e2023_structural_fields_required(self):
        """Test E-2023 is registered for STRUCTURAL_FIELDS_REQUIRED."""
        err = get_error("E-2023")
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert "{ups_message}" in err.message_template
        assert err.is_retryable is False

    def test_all_international_codes_have_remediation(self):
        for code in ["E-2013", "E-2014", "E-2015", "E-2016", "E-2017", "E-2023", "E-3006"]:
            err = get_error(code)
            assert err is not None, f"{code} not registered"
            assert err.remediation, f"{code} missing remediation"
