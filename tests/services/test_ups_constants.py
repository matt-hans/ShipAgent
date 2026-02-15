"""Tests for UPS constants module."""

from src.services.ups_constants import (
    DEFAULT_LABEL_FORMAT,
    DEFAULT_LABEL_HEIGHT,
    DEFAULT_LABEL_WIDTH,
    DEFAULT_ORIGIN_COUNTRY,
    DEFAULT_PACKAGE_WEIGHT_LBS,
    DEFAULT_PACKAGING_CODE,
    GRAMS_PER_LB,
    PACKAGING_ALIASES,
    SUPPORTED_SHIPPING_LANES,
    UPS_ADDRESS_MAX_LEN,
    UPS_DIMENSION_UNIT,
    UPS_PHONE_MAX_DIGITS,
    UPS_PHONE_MIN_DIGITS,
    UPS_REFERENCE_MAX_LEN,
    UPS_WEIGHT_UNIT,
    PackagingCode,
)


class TestPackagingCodeEnum:
    """Test PackagingCode enum members."""

    def test_all_codes_are_two_or_more_chars(self):
        """Test all enum codes are at least 2 characters."""
        for member in PackagingCode:
            assert len(member.value) >= 2, f"{member.name} has short code: {member.value}"

    def test_customer_supplied_is_02(self):
        """Test default packaging code is 02."""
        assert PackagingCode.CUSTOMER_SUPPLIED.value == "02"

    def test_default_matches_customer_supplied(self):
        """Test DEFAULT_PACKAGING_CODE is CUSTOMER_SUPPLIED."""
        assert DEFAULT_PACKAGING_CODE == PackagingCode.CUSTOMER_SUPPLIED

    def test_str_enum_mixin(self):
        """Test PackagingCode is a str enum (JSON serializable)."""
        assert isinstance(PackagingCode.LETTER, str)
        assert PackagingCode.LETTER == "01"


class TestPackagingAliases:
    """Test PACKAGING_ALIASES map."""

    def test_all_aliases_map_to_valid_codes(self):
        """Test every alias maps to a valid PackagingCode member."""
        for alias, code in PACKAGING_ALIASES.items():
            assert isinstance(code, PackagingCode), (
                f"Alias {alias!r} maps to {code!r}, not a PackagingCode"
            )

    def test_aliases_are_lowercase(self):
        """Test all alias keys are lowercase."""
        for alias in PACKAGING_ALIASES:
            assert alias == alias.lower(), f"Alias {alias!r} is not lowercase"

    def test_common_aliases_present(self):
        """Test common packaging name aliases are defined."""
        assert "customer supplied" in PACKAGING_ALIASES
        assert "pak" in PACKAGING_ALIASES
        assert "letter" in PACKAGING_ALIASES
        assert "tube" in PACKAGING_ALIASES
        assert "express box" in PACKAGING_ALIASES
        assert "pallet" in PACKAGING_ALIASES

    def test_ups_prefixed_aliases_present(self):
        """Test UPS-prefixed variants are defined."""
        assert "ups letter" in PACKAGING_ALIASES
        assert "ups pak" in PACKAGING_ALIASES
        assert "ups tube" in PACKAGING_ALIASES
        assert "ups express box" in PACKAGING_ALIASES


class TestSupportedShippingLanes:
    """Test SUPPORTED_SHIPPING_LANES."""

    def test_is_frozenset(self):
        """Test it's a frozenset (immutable)."""
        assert isinstance(SUPPORTED_SHIPPING_LANES, frozenset)

    def test_non_empty(self):
        """Test at least one lane is defined."""
        assert len(SUPPORTED_SHIPPING_LANES) > 0

    def test_contains_us_ca(self):
        """Test US-CA lane is supported."""
        assert "US-CA" in SUPPORTED_SHIPPING_LANES

    def test_contains_us_mx(self):
        """Test US-MX lane is supported."""
        assert "US-MX" in SUPPORTED_SHIPPING_LANES


class TestNumericConstants:
    """Test numeric constants have reasonable values."""

    def test_address_max_len_positive(self):
        """Test UPS address max length is positive."""
        assert UPS_ADDRESS_MAX_LEN > 0
        assert UPS_ADDRESS_MAX_LEN == 35

    def test_phone_limits_valid(self):
        """Test phone digit limits are valid."""
        assert UPS_PHONE_MIN_DIGITS < UPS_PHONE_MAX_DIGITS
        assert UPS_PHONE_MIN_DIGITS == 7
        assert UPS_PHONE_MAX_DIGITS == 15

    def test_reference_max_len_positive(self):
        """Test reference max length is positive."""
        assert UPS_REFERENCE_MAX_LEN > 0
        assert UPS_REFERENCE_MAX_LEN == 35

    def test_default_weight_positive(self):
        """Test default weight is positive."""
        assert DEFAULT_PACKAGE_WEIGHT_LBS > 0
        assert DEFAULT_PACKAGE_WEIGHT_LBS == 1.0

    def test_grams_per_lb_reasonable(self):
        """Test grams per lb conversion factor."""
        assert 453 < GRAMS_PER_LB < 454

    def test_weight_unit_is_lbs(self):
        """Test weight unit is LBS."""
        assert UPS_WEIGHT_UNIT == "LBS"

    def test_dimension_unit_is_in(self):
        """Test dimension unit is IN."""
        assert UPS_DIMENSION_UNIT == "IN"

    def test_default_origin_country(self):
        """Test default origin country is US."""
        assert DEFAULT_ORIGIN_COUNTRY == "US"


class TestLabelConstants:
    """Test label specification defaults."""

    def test_label_format_is_pdf(self):
        """Test default label format is PDF."""
        assert DEFAULT_LABEL_FORMAT == "PDF"

    def test_label_dimensions(self):
        """Test default label size is 6x4."""
        assert DEFAULT_LABEL_HEIGHT == "6"
        assert DEFAULT_LABEL_WIDTH == "4"
