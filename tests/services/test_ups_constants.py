"""Tests for UPS constants module."""

from src.services.ups_constants import (
    DEFAULT_LABEL_FORMAT,
    DEFAULT_LABEL_HEIGHT,
    DEFAULT_LABEL_WIDTH,
    DEFAULT_ORIGIN_COUNTRY,
    DEFAULT_PACKAGE_WEIGHT_LBS,
    DEFAULT_PACKAGING_CODE,
    EU_MEMBER_STATES,
    FORMS_REQUIRING_PRODUCTS,
    GRAMS_PER_LB,
    INTERNATIONAL_FORM_TYPES,
    PACKAGING_ALIASES,
    REASON_FOR_EXPORT_VALUES,
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


class TestInternationalConstants:
    """Test international shipping constants."""

    def test_eu_member_states_has_27_members(self):
        """Test EU has exactly 27 member states (post-Brexit)."""
        assert len(EU_MEMBER_STATES) == 27

    def test_eu_includes_major_countries(self):
        """Test major EU countries are present."""
        for code in ("DE", "FR", "IT", "ES", "NL", "PL", "SE"):
            assert code in EU_MEMBER_STATES, f"{code} missing from EU_MEMBER_STATES"

    def test_eu_excludes_gb(self):
        """Test GB is not in EU (post-Brexit)."""
        assert "GB" not in EU_MEMBER_STATES

    def test_eu_excludes_non_eu_european(self):
        """Test non-EU European countries are excluded."""
        for code in ("NO", "CH"):
            assert code not in EU_MEMBER_STATES, f"{code} should not be in EU_MEMBER_STATES"

    def test_international_form_types_is_dict(self):
        """Test INTERNATIONAL_FORM_TYPES is a non-empty dict."""
        assert isinstance(INTERNATIONAL_FORM_TYPES, dict)
        assert len(INTERNATIONAL_FORM_TYPES) > 0

    def test_form_type_01_is_invoice(self):
        """Test form type 01 maps to Invoice."""
        assert "01" in INTERNATIONAL_FORM_TYPES
        assert "Invoice" in INTERNATIONAL_FORM_TYPES["01"]

    def test_reason_for_export_values_non_empty(self):
        """Test REASON_FOR_EXPORT_VALUES is a non-empty frozenset."""
        assert isinstance(REASON_FOR_EXPORT_VALUES, frozenset)
        assert "SALE" in REASON_FOR_EXPORT_VALUES
        assert "GIFT" in REASON_FOR_EXPORT_VALUES

    def test_forms_requiring_products_non_empty(self):
        """Test FORMS_REQUIRING_PRODUCTS includes invoice form type."""
        assert isinstance(FORMS_REQUIRING_PRODUCTS, frozenset)
        assert "01" in FORMS_REQUIRING_PRODUCTS


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


class TestUpgradeToInternational:
    """Test domestic→international service code auto-upgrade."""

    def test_ground_upgrades_to_standard_for_ca(self):
        """Ground (03) → UPS Standard (11) for CA/MX."""
        from src.services.ups_service_codes import upgrade_to_international
        assert upgrade_to_international("03", "US", "CA") == "11"
        assert upgrade_to_international("03", "US", "MX") == "11"

    def test_ground_upgrades_to_saver_for_global(self):
        """Ground (03) → Worldwide Saver (65) for non-CA/MX destinations."""
        from src.services.ups_service_codes import upgrade_to_international
        assert upgrade_to_international("03", "US", "GB") == "65"
        assert upgrade_to_international("03", "US", "DE") == "65"
        assert upgrade_to_international("03", "US", "JP") == "65"

    def test_next_day_air_upgrades_to_worldwide_express(self):
        """Next Day Air (01) → Worldwide Express (07) for international."""
        from src.services.ups_service_codes import upgrade_to_international
        assert upgrade_to_international("01", "US", "DE") == "07"

    def test_domestic_stays_unchanged(self):
        """Domestic shipments keep their service code."""
        from src.services.ups_service_codes import upgrade_to_international
        assert upgrade_to_international("03", "US", "US") == "03"

    def test_international_code_stays_unchanged(self):
        """Already-international codes are not changed."""
        from src.services.ups_service_codes import upgrade_to_international
        assert upgrade_to_international("07", "US", "GB") == "07"
        assert upgrade_to_international("11", "US", "CA") == "11"

    def test_second_day_air_am_upgrades_to_worldwide_expedited(self):
        """2nd Day Air A.M. (59) → Worldwide Expedited (08) for international."""
        from src.services.ups_service_codes import upgrade_to_international
        assert upgrade_to_international("59", "US", "GB") == "08"
        assert upgrade_to_international("59", "US", "CA") == "08"

    def test_all_domestic_codes_have_mapping(self):
        """Every domestic-only code has an international equivalent."""
        from src.services.ups_service_codes import DOMESTIC_TO_INTERNATIONAL, DOMESTIC_ONLY_SERVICES
        for code in DOMESTIC_ONLY_SERVICES:
            assert code in DOMESTIC_TO_INTERNATIONAL, f"No international mapping for {code}"


class TestBuildShipmentRequestUpgrade:
    """Test build_shipment_request auto-upgrades domestic service codes."""

    _SHIPPER = {
        "name": "Shipper",
        "addressLine1": "100 Main St",
        "city": "New York",
        "stateProvinceCode": "NY",
        "postalCode": "10001",
        "countryCode": "US",
    }

    def test_ground_auto_upgraded_for_gb(self, monkeypatch):
        """build_shipment_request upgrades Ground → Worldwide Saver for US→GB."""
        monkeypatch.setenv("INTERNATIONAL_ENABLED_LANES", "*")
        from src.services.ups_payload_builder import build_shipment_request

        order_data = {
            "ship_to_name": "Test",
            "ship_to_address1": "123 High St",
            "ship_to_city": "London",
            "ship_to_postal_code": "SW1A 1AA",
            "ship_to_country": "GB",
            "service_code": "03",
            "weight": 1.0,
        }
        result = build_shipment_request(order_data, self._SHIPPER, service_code="03")
        assert result["serviceCode"] == "65"

    def test_ground_auto_upgraded_for_ca(self, monkeypatch):
        """build_shipment_request upgrades Ground → Standard for US→CA."""
        monkeypatch.setenv("INTERNATIONAL_ENABLED_LANES", "*")
        from src.services.ups_payload_builder import build_shipment_request

        order_data = {
            "ship_to_name": "Test",
            "ship_to_address1": "123 Test St",
            "ship_to_city": "Toronto",
            "ship_to_state": "ON",
            "ship_to_postal_code": "M5V 2T6",
            "ship_to_country": "CA",
            "service_code": "03",
            "weight": 1.0,
        }
        result = build_shipment_request(order_data, self._SHIPPER, service_code="03")
        assert result["serviceCode"] == "11"

    def test_domestic_not_upgraded(self):
        """build_shipment_request keeps Ground for domestic US→US."""
        from src.services.ups_payload_builder import build_shipment_request

        order_data = {
            "ship_to_name": "Test",
            "ship_to_address1": "456 Elm St",
            "ship_to_city": "Chicago",
            "ship_to_state": "IL",
            "ship_to_postal_code": "60601",
            "ship_to_country": "US",
            "weight": 1.0,
        }
        result = build_shipment_request(order_data, self._SHIPPER, service_code="03")
        assert result["serviceCode"] == "03"


class TestLabelConstants:
    """Test label specification defaults."""

    def test_label_format_is_pdf(self):
        """Test default label format is PDF."""
        assert DEFAULT_LABEL_FORMAT == "PDF"

    def test_label_dimensions(self):
        """Test default label size is 6x4."""
        assert DEFAULT_LABEL_HEIGHT == "6"
        assert DEFAULT_LABEL_WIDTH == "4"


class TestCompatibilityMatrices:
    """Verify compatibility matrices match UPS spec."""

    def test_express_only_packaging_contains_letter(self):
        """UPS Letter is express-only."""
        from src.services.ups_constants import EXPRESS_ONLY_PACKAGING
        assert PackagingCode.LETTER.value in EXPRESS_ONLY_PACKAGING

    def test_express_only_packaging_contains_pak(self):
        """UPS PAK is express-only."""
        from src.services.ups_constants import EXPRESS_ONLY_PACKAGING
        assert PackagingCode.PAK.value in EXPRESS_ONLY_PACKAGING

    def test_express_only_packaging_contains_tube(self):
        """UPS Tube is express-only."""
        from src.services.ups_constants import EXPRESS_ONLY_PACKAGING
        assert PackagingCode.TUBE.value in EXPRESS_ONLY_PACKAGING

    def test_express_only_packaging_contains_all_express_box_variants(self):
        """All Express Box variants are express-only."""
        from src.services.ups_constants import EXPRESS_ONLY_PACKAGING
        assert PackagingCode.EXPRESS_BOX.value in EXPRESS_ONLY_PACKAGING
        assert PackagingCode.SMALL_EXPRESS_BOX.value in EXPRESS_ONLY_PACKAGING
        assert PackagingCode.MEDIUM_EXPRESS_BOX.value in EXPRESS_ONLY_PACKAGING
        assert PackagingCode.LARGE_EXPRESS_BOX.value in EXPRESS_ONLY_PACKAGING

    def test_customer_supplied_not_in_express_only(self):
        """Customer Supplied is universal — not express-only."""
        from src.services.ups_constants import EXPRESS_ONLY_PACKAGING
        assert PackagingCode.CUSTOMER_SUPPLIED.value not in EXPRESS_ONLY_PACKAGING

    def test_ground_not_in_express_class_services(self):
        """Ground (03) is not an express service."""
        from src.services.ups_constants import EXPRESS_CLASS_SERVICES
        assert "03" not in EXPRESS_CLASS_SERVICES

    def test_next_day_air_in_express_class(self):
        """Next Day Air (01) is express class."""
        from src.services.ups_constants import EXPRESS_CLASS_SERVICES
        assert "01" in EXPRESS_CLASS_SERVICES

    def test_worldwide_express_in_express_class(self):
        """Worldwide Express (07) is express class."""
        from src.services.ups_constants import EXPRESS_CLASS_SERVICES
        assert "07" in EXPRESS_CLASS_SERVICES

    def test_saturday_delivery_services_subset_of_express(self):
        """Saturday Delivery services are a subset of express services."""
        from src.services.ups_constants import EXPRESS_CLASS_SERVICES, SATURDAY_DELIVERY_SERVICES
        assert SATURDAY_DELIVERY_SERVICES.issubset(EXPRESS_CLASS_SERVICES)

    def test_international_only_packaging(self):
        """25kg and 10kg boxes are international-only."""
        from src.services.ups_constants import INTERNATIONAL_ONLY_PACKAGING
        assert PackagingCode.BOX_25KG.value in INTERNATIONAL_ONLY_PACKAGING
        assert PackagingCode.BOX_10KG.value in INTERNATIONAL_ONLY_PACKAGING

    def test_letter_weight_limit_reasonable(self):
        """Letter weight limit is between 1.0 and 1.5 lbs."""
        from src.services.ups_constants import LETTER_MAX_WEIGHT_LBS
        assert 1.0 < LETTER_MAX_WEIGHT_LBS < 1.5

    def test_all_services_have_weight_limits(self):
        """Common services have defined weight limits."""
        from src.services.ups_constants import SERVICE_WEIGHT_LIMITS_LBS
        for svc in ["01", "02", "03", "12", "13", "14", "59"]:
            assert svc in SERVICE_WEIGHT_LIMITS_LBS
