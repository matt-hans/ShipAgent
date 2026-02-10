"""Tests for UPS payload builder."""

import pytest

from src.services.ups_payload_builder import (
    build_packages,
    build_ship_to,
    build_shipment_request,
    build_shipper_from_env,
    build_shipper_from_shop,
    get_service_code,
    normalize_phone,
    normalize_zip,
    truncate_address,
)


class TestNormalizePhone:
    """Test phone number normalization."""

    def test_strips_formatting(self):
        """Test formatting characters are removed."""
        assert normalize_phone("(555) 123-4567") == "5551234567"
        assert normalize_phone("555.123.4567") == "5551234567"
        assert normalize_phone("555 123 4567") == "5551234567"

    def test_handles_international_format(self):
        """Test international phone numbers."""
        assert normalize_phone("+1 555-123-4567") == "15551234567"

    def test_returns_default_for_short_numbers(self):
        """Test short numbers return default."""
        assert normalize_phone("123") == "5555555555"
        assert normalize_phone("") == "5555555555"

    def test_returns_default_for_none(self):
        """Test None returns default."""
        assert normalize_phone(None) == "5555555555"

    def test_truncates_to_15_digits(self):
        """Test very long numbers are truncated."""
        long_number = "123456789012345678901234567890"
        result = normalize_phone(long_number)
        assert len(result) == 15


class TestNormalizeZip:
    """Test ZIP code normalization."""

    def test_five_digit_zip(self):
        """Test 5-digit ZIP codes pass through."""
        assert normalize_zip("90210") == "90210"
        assert normalize_zip("  90210  ") == "90210"

    def test_zip_plus_four(self):
        """Test ZIP+4 codes are formatted correctly."""
        assert normalize_zip("902101234") == "90210-1234"
        assert normalize_zip("90210-1234") == "90210-1234"

    def test_returns_empty_for_none(self):
        """Test None returns empty string."""
        assert normalize_zip(None) == ""

    def test_handles_short_codes(self):
        """Test short codes returned as-is (international)."""
        assert normalize_zip("1234") == "1234"

    def test_handles_extra_digits(self):
        """Test extra digits are ignored."""
        assert normalize_zip("9021012345678") == "90210-1234"


class TestTruncateAddress:
    """Test address truncation."""

    def test_short_addresses_unchanged(self):
        """Test short addresses are not modified."""
        assert truncate_address("123 Main St") == "123 Main St"

    def test_truncates_at_word_boundary(self):
        """Test long addresses are truncated at word boundary."""
        address = "1234 North Very Long Street Name Avenue Suite 100"
        result = truncate_address(address, 35)
        assert len(result) <= 35
        assert not result.endswith(" ")

    def test_custom_max_length(self):
        """Test custom max length is respected."""
        result = truncate_address("This is a longer address", 15)
        assert len(result) <= 15

    def test_returns_empty_for_none(self):
        """Test None returns empty string."""
        assert truncate_address(None) == ""

    def test_handles_single_long_word(self):
        """Test single word longer than max falls back to hard truncate."""
        result = truncate_address("ABCDEFGHIJKLMNOPQRSTUVWXYZ12345678901234567890", 35)
        assert len(result) == 35


class TestBuildShipperFromShop:
    """Test shipper building from Shopify shop data."""

    def test_builds_shipper_from_full_shop_info(self):
        """Test complete shipper from full shop data."""
        shop_info = {
            "name": "My Store",
            "phone": "555-123-4567",
            "address1": "123 Main St",
            "address2": "Suite 100",
            "city": "Los Angeles",
            "province_code": "CA",
            "zip": "90001",
            "country_code": "US",
        }

        shipper = build_shipper_from_shop(shop_info)

        assert shipper["name"] == "My Store"
        assert shipper["phone"] == "5551234567"
        assert shipper["addressLine1"] == "123 Main St"
        assert shipper["addressLine2"] == "Suite 100"
        assert shipper["city"] == "Los Angeles"
        assert shipper["stateProvinceCode"] == "CA"
        assert shipper["postalCode"] == "90001"
        assert shipper["countryCode"] == "US"

    def test_handles_missing_fields(self):
        """Test shipper falls back to env vars for missing required fields."""
        shop_info = {
            "name": "My Store",
            "city": "Los Angeles",
        }

        shipper = build_shipper_from_shop(shop_info)

        assert shipper["name"] == "My Store"
        assert shipper["phone"] == "5555555555"  # Default
        # Missing addressLine1 falls back to env var (SHIPPER_ADDRESS1 or default)
        assert shipper["addressLine1"] != ""
        assert shipper["city"] == "Los Angeles"  # Provided
        assert shipper["countryCode"] == "US"  # Default

    def test_truncates_long_names(self):
        """Test long store names are truncated."""
        shop_info = {
            "name": "The Absolutely Incredibly Long Store Name That Exceeds UPS Limits",
        }

        shipper = build_shipper_from_shop(shop_info)

        assert len(shipper["name"]) <= 35


class TestBuildShipperFromEnv:
    """Test shipper building from environment variables."""

    def test_uses_env_vars(self):
        """Test shipper uses environment variables."""
        import os
        from unittest.mock import patch

        env_vars = {
            "SHIPPER_NAME": "Test Shipper",
            "SHIPPER_PHONE": "555-999-8888",
            "SHIPPER_ADDRESS1": "456 Oak Ave",
            "SHIPPER_CITY": "San Francisco",
            "SHIPPER_STATE": "CA",
            "SHIPPER_ZIP": "94102",
            "SHIPPER_COUNTRY": "US",
        }

        with patch.dict(os.environ, env_vars):
            shipper = build_shipper_from_env()

        assert shipper["name"] == "Test Shipper"
        assert shipper["phone"] == "5559998888"
        assert shipper["addressLine1"] == "456 Oak Ave"
        assert shipper["city"] == "San Francisco"
        assert shipper["stateProvinceCode"] == "CA"
        assert shipper["postalCode"] == "94102"
        assert shipper["countryCode"] == "US"

    def test_uses_defaults_when_missing(self):
        """Test default values when env vars not set."""
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {}, clear=True):
            shipper = build_shipper_from_env()

        assert shipper["name"] == "ShipAgent Default"
        assert shipper["addressLine1"] == "123 Main St"
        assert shipper["city"] == "Los Angeles"
        assert shipper["stateProvinceCode"] == "CA"
        assert shipper["postalCode"] == "90001"


class TestBuildShipTo:
    """Test ship-to address building."""

    def test_builds_ship_to_from_order_data(self):
        """Test complete ship-to from order data."""
        order_data = {
            "ship_to_name": "John Doe",
            "ship_to_company": "Acme Inc",
            "ship_to_phone": "555-111-2222",
            "ship_to_address1": "789 Elm St",
            "ship_to_address2": "Apt 3",
            "ship_to_city": "Chicago",
            "ship_to_state": "IL",
            "ship_to_postal_code": "60601",
            "ship_to_country": "US",
        }

        ship_to = build_ship_to(order_data)

        assert ship_to["name"] == "John Doe"
        assert ship_to["attentionName"] == "Acme Inc"
        assert ship_to["phone"] == "5551112222"
        assert ship_to["addressLine1"] == "789 Elm St"
        assert ship_to["addressLine2"] == "Apt 3"
        assert ship_to["city"] == "Chicago"
        assert ship_to["stateProvinceCode"] == "IL"
        assert ship_to["postalCode"] == "60601"
        assert ship_to["countryCode"] == "US"

    def test_builds_name_from_first_last(self):
        """Test name is built from first/last name fields."""
        order_data = {
            "ship_to_first_name": "Jane",
            "ship_to_last_name": "Smith",
            "ship_to_city": "Seattle",
            "ship_to_state": "WA",
        }

        ship_to = build_ship_to(order_data)

        assert ship_to["name"] == "Jane Smith"

    def test_uses_default_name(self):
        """Test default name when missing."""
        order_data = {
            "ship_to_city": "Portland",
            "ship_to_state": "OR",
        }

        ship_to = build_ship_to(order_data)

        assert ship_to["name"] == "Recipient"


class TestBuildPackages:
    """Test package building."""

    def test_single_package_from_order_level_weight(self):
        """Test single package from order-level weight."""
        order_data = {
            "weight": 2.5,
        }

        packages = build_packages(order_data)

        assert len(packages) == 1
        assert packages[0]["weight"] == 2.5
        assert packages[0]["packagingType"] == "02"

    def test_single_package_with_dimensions(self):
        """Test single package with dimensions."""
        order_data = {
            "weight": 3.0,
            "length": 12,
            "width": 8,
            "height": 6,
        }

        packages = build_packages(order_data)

        assert len(packages) == 1
        assert packages[0]["weight"] == 3.0
        assert packages[0]["length"] == 12.0
        assert packages[0]["width"] == 8.0
        assert packages[0]["height"] == 6.0

    def test_multiple_packages_from_array(self):
        """Test multiple packages from packages array."""
        order_data = {
            "packages": [
                {"weight": 1.0, "length": 10, "width": 8, "height": 6},
                {"weight": 2.5, "length": 12, "width": 10, "height": 8},
            ]
        }

        packages = build_packages(order_data)

        assert len(packages) == 2
        assert packages[0]["weight"] == 1.0
        assert packages[1]["weight"] == 2.5

    def test_default_weight_when_missing(self):
        """Test default weight of 1.0 when not specified."""
        order_data = {}

        packages = build_packages(order_data)

        assert len(packages) == 1
        assert packages[0]["weight"] == 1.0


class TestGetServiceCode:
    """Test service code extraction."""

    def test_explicit_service_code(self):
        """Test explicit service_code field is used."""
        order_data = {"service_code": "01"}
        assert get_service_code(order_data) == "01"

    def test_service_name_mapping_ground(self):
        """Test 'ground' maps to '03'."""
        assert get_service_code({"service": "ground"}) == "03"
        assert get_service_code({"service": "UPS Ground"}) == "03"

    def test_service_name_mapping_next_day(self):
        """Test 'next day' maps to '01'."""
        assert get_service_code({"service": "next day air"}) == "01"
        assert get_service_code({"service": "overnight"}) == "01"

    def test_service_name_mapping_2nd_day(self):
        """Test '2nd day' maps to '02'."""
        assert get_service_code({"service": "2nd day air"}) == "02"
        assert get_service_code({"service": "2 day"}) == "02"

    def test_default_service_code(self):
        """Test default service code when not specified."""
        assert get_service_code({}) == "03"

    def test_custom_default(self):
        """Test custom default can be provided."""
        assert get_service_code({}, default="01") == "01"


class TestBuildShipmentRequest:
    """Test complete shipment request building."""

    def test_builds_complete_request(self):
        """Test complete shipment request structure."""
        order_data = {
            "order_number": "1001",
            "ship_to_name": "John Doe",
            "ship_to_phone": "555-123-4567",
            "ship_to_address1": "123 Main St",
            "ship_to_city": "Los Angeles",
            "ship_to_state": "CA",
            "ship_to_postal_code": "90001",
            "weight": 2.0,
            "service_code": "03",
        }

        shipper = {
            "name": "Test Store",
            "phone": "5559998888",
            "addressLine1": "456 Oak Ave",
            "city": "San Francisco",
            "stateProvinceCode": "CA",
            "postalCode": "94102",
            "countryCode": "US",
        }

        request = build_shipment_request(order_data, shipper)

        assert request["shipper"]["name"] == "Test Store"
        assert request["shipTo"]["name"] == "John Doe"
        assert request["packages"][0]["weight"] == 2.0
        assert request["serviceCode"] == "03"
        assert request["reference"] == "1001"
        assert request["description"] == "Order #1001"

    def test_removes_none_values(self):
        """Test None values are removed from output."""
        order_data = {
            "ship_to_name": "John Doe",
            "ship_to_city": "LA",
            "ship_to_state": "CA",
        }

        shipper = {
            "name": "Store",
            "addressLine2": None,  # Should be removed
            "city": "SF",
        }

        request = build_shipment_request(order_data, shipper)

        assert "addressLine2" not in request["shipper"]

    def test_uses_env_shipper_when_none_provided(self):
        """Test falls back to env vars when shipper not provided."""
        import os
        from unittest.mock import patch

        order_data = {
            "ship_to_name": "John Doe",
            "ship_to_city": "LA",
            "ship_to_state": "CA",
        }

        with patch.dict(os.environ, {"SHIPPER_NAME": "Env Store"}, clear=True):
            request = build_shipment_request(order_data)

        assert request["shipper"]["name"] == "Env Store"

    def test_service_code_override(self):
        """Test service_code parameter overrides order data."""
        order_data = {
            "ship_to_name": "John Doe",
            "ship_to_city": "LA",
            "ship_to_state": "CA",
            "service_code": "03",
        }

        request = build_shipment_request(order_data, service_code="01")

        assert request["serviceCode"] == "01"

    def test_default_description(self):
        """Test default description when reference missing."""
        order_data = {
            "ship_to_name": "John Doe",
            "ship_to_city": "LA",
            "ship_to_state": "CA",
        }

        request = build_shipment_request(order_data)

        assert request["description"] == "Shipment"


# ── Tests for UPS API payload transformation ──────────────────────


from src.services.ups_payload_builder import build_ups_api_payload, build_ups_rate_payload


class TestBuildUpsApiPayload:
    """Test simplified → UPS API format transformation."""

    def test_produces_shipment_request_wrapper(self):
        """Test output has ShipmentRequest at top level."""
        simplified = {
            "shipper": {
                "name": "Test Store",
                "phone": "5559998888",
                "addressLine1": "456 Oak Ave",
                "city": "San Francisco",
                "stateProvinceCode": "CA",
                "postalCode": "94102",
                "countryCode": "US",
            },
            "shipTo": {
                "name": "John Doe",
                "addressLine1": "123 Main St",
                "city": "Los Angeles",
                "stateProvinceCode": "CA",
                "postalCode": "90001",
                "countryCode": "US",
            },
            "packages": [{"weight": 2.0}],
            "serviceCode": "03",
        }

        result = build_ups_api_payload(simplified, account_number="ABC123")

        assert "ShipmentRequest" in result
        shipment = result["ShipmentRequest"]["Shipment"]
        assert shipment["Shipper"]["Name"] == "Test Store"
        assert shipment["Shipper"]["ShipperNumber"] == "ABC123"
        assert shipment["ShipTo"]["Name"] == "John Doe"
        assert shipment["ShipTo"]["Address"]["City"] == "Los Angeles"
        assert shipment["Service"]["Code"] == "03"
        assert shipment["Package"][0]["PackageWeight"]["Weight"] == "2.0"

    def test_includes_label_specification(self):
        """Test PDF label specification is included."""
        simplified = {
            "shipper": {"name": "S", "addressLine1": "A", "city": "C",
                        "stateProvinceCode": "CA", "postalCode": "90001",
                        "countryCode": "US"},
            "shipTo": {"name": "R", "addressLine1": "B", "city": "D",
                       "stateProvinceCode": "NY", "postalCode": "10001",
                       "countryCode": "US"},
            "packages": [{"weight": 1.0}],
            "serviceCode": "03",
        }

        result = build_ups_api_payload(simplified, account_number="X")
        label_spec = result["ShipmentRequest"]["LabelSpecification"]
        assert label_spec["LabelImageFormat"]["Code"] == "PDF"

    def test_fails_without_account_number(self):
        """Test raises ValueError when account_number missing."""
        simplified = {
            "shipper": {"name": "S", "addressLine1": "A", "city": "C",
                        "stateProvinceCode": "CA", "postalCode": "90001",
                        "countryCode": "US"},
            "shipTo": {"name": "R", "addressLine1": "B", "city": "D",
                       "stateProvinceCode": "NY", "postalCode": "10001",
                       "countryCode": "US"},
            "packages": [{"weight": 1.0}],
            "serviceCode": "03",
        }

        with pytest.raises(ValueError, match="account_number"):
            build_ups_api_payload(simplified, account_number="")

    def test_includes_dimensions_when_present(self):
        """Test package dimensions are included when provided."""
        simplified = {
            "shipper": {"name": "S", "addressLine1": "A", "city": "C",
                        "stateProvinceCode": "CA", "postalCode": "90001",
                        "countryCode": "US"},
            "shipTo": {"name": "R", "addressLine1": "B", "city": "D",
                       "stateProvinceCode": "NY", "postalCode": "10001",
                       "countryCode": "US"},
            "packages": [{"weight": 5.0, "length": 12, "width": 8, "height": 6}],
            "serviceCode": "03",
        }

        result = build_ups_api_payload(simplified, account_number="X")
        pkg = result["ShipmentRequest"]["Shipment"]["Package"][0]
        assert pkg["Dimensions"]["Length"] == "12"
        assert pkg["Dimensions"]["Width"] == "8"
        assert pkg["Dimensions"]["Height"] == "6"

    def test_includes_reference_when_present(self):
        """Test ReferenceNumber is included when reference provided."""
        simplified = {
            "shipper": {"name": "S", "addressLine1": "A", "city": "C",
                        "stateProvinceCode": "CA", "postalCode": "90001",
                        "countryCode": "US"},
            "shipTo": {"name": "R", "addressLine1": "B", "city": "D",
                       "stateProvinceCode": "NY", "postalCode": "10001",
                       "countryCode": "US"},
            "packages": [{"weight": 1.0}],
            "serviceCode": "03",
            "reference": "ORD-1001",
        }

        result = build_ups_api_payload(simplified, account_number="X")
        shipment = result["ShipmentRequest"]["Shipment"]
        assert shipment["ReferenceNumber"]["Value"] == "ORD-1001"


class TestBuildUpsRatePayload:
    """Test simplified → UPS Rate API format."""

    def test_produces_rate_request_wrapper(self):
        """Test output has RateRequest at top level."""
        simplified = {
            "shipper": {"name": "S", "addressLine1": "A", "city": "C",
                        "stateProvinceCode": "CA", "postalCode": "90001",
                        "countryCode": "US"},
            "shipTo": {"name": "R", "addressLine1": "B", "city": "D",
                       "stateProvinceCode": "NY", "postalCode": "10001",
                       "countryCode": "US"},
            "packages": [{"weight": 1.0}],
            "serviceCode": "03",
        }

        result = build_ups_rate_payload(simplified, account_number="X")

        assert "RateRequest" in result
        shipment = result["RateRequest"]["Shipment"]
        assert shipment["Service"]["Code"] == "03"
        assert shipment["Shipper"]["ShipperNumber"] == "X"
