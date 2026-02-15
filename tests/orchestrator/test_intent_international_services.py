"""Tests for international service code support."""

from src.orchestrator.models.intent import (
    ServiceCode,
    SERVICE_ALIASES,
    CODE_TO_SERVICE,
)


class TestInternationalServiceCodes:
    """Verify international services are in the enum."""

    def test_worldwide_express(self):
        assert ServiceCode.WORLDWIDE_EXPRESS.value == "07"

    def test_worldwide_expedited(self):
        assert ServiceCode.WORLDWIDE_EXPEDITED.value == "08"

    def test_ups_standard(self):
        assert ServiceCode.UPS_STANDARD.value == "11"

    def test_worldwide_express_plus(self):
        assert ServiceCode.WORLDWIDE_EXPRESS_PLUS.value == "54"

    def test_worldwide_saver(self):
        assert ServiceCode.WORLDWIDE_SAVER.value == "65"


class TestInternationalServiceAliases:
    """Verify international aliases map correctly."""

    def test_worldwide_express_alias(self):
        assert SERVICE_ALIASES["worldwide express"] == ServiceCode.WORLDWIDE_EXPRESS

    def test_international_express_alias(self):
        assert SERVICE_ALIASES["international express"] == ServiceCode.WORLDWIDE_EXPRESS

    def test_worldwide_expedited_alias(self):
        assert SERVICE_ALIASES["worldwide expedited"] == ServiceCode.WORLDWIDE_EXPEDITED

    def test_worldwide_saver_alias(self):
        assert SERVICE_ALIASES["worldwide saver"] == ServiceCode.WORLDWIDE_SAVER

    def test_express_plus_alias(self):
        assert SERVICE_ALIASES["express plus"] == ServiceCode.WORLDWIDE_EXPRESS_PLUS

    def test_standard_alias_not_present(self):
        """P1: bare 'standard' must NOT map to international service 11."""
        assert "standard" not in SERVICE_ALIASES

    def test_ups_standard_alias(self):
        assert SERVICE_ALIASES["ups standard"] == ServiceCode.UPS_STANDARD

    def test_international_standard_alias(self):
        assert SERVICE_ALIASES["international standard"] == ServiceCode.UPS_STANDARD

    def test_code_to_service_reverse_mapping(self):
        assert CODE_TO_SERVICE["07"] == ServiceCode.WORLDWIDE_EXPRESS
        assert CODE_TO_SERVICE["08"] == ServiceCode.WORLDWIDE_EXPEDITED
        assert CODE_TO_SERVICE["11"] == ServiceCode.UPS_STANDARD
        assert CODE_TO_SERVICE["54"] == ServiceCode.WORLDWIDE_EXPRESS_PLUS
        assert CODE_TO_SERVICE["65"] == ServiceCode.WORLDWIDE_SAVER
