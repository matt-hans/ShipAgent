"""Tests for UPS payload builder."""

from typing import Any

import pytest

from src.services.ups_payload_builder import (
    build_international_forms,
    build_packages,
    build_ship_to,
    build_shipment_request,
    build_shipper,
    build_ups_api_payload,
    build_ups_rate_payload,
    get_service_code,
    normalize_phone,
    normalize_zip,
    resolve_packaging_code,
    resolve_service_code,
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

    def test_returns_empty_for_short_numbers(self):
        """Test short numbers return empty string."""
        assert normalize_phone("123") == ""
        assert normalize_phone("") == ""

    def test_returns_empty_for_none(self):
        """Test None returns empty string."""
        assert normalize_phone(None) == ""

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
    """Test shipper building from Shopify shop data overlay."""

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

        shipper = build_shipper(shop_info)

        assert shipper["name"] == "My Store"
        assert shipper["phone"] == "5551234567"
        assert shipper["addressLine1"] == "123 Main St"
        assert shipper["addressLine2"] == "Suite 100"
        assert shipper["city"] == "Los Angeles"
        assert shipper["stateProvinceCode"] == "CA"
        assert shipper["postalCode"] == "90001"
        assert shipper["countryCode"] == "US"

    def test_handles_missing_fields_with_env_vars(self):
        """Test shipper falls back to env vars for missing shop fields."""
        import os
        from unittest.mock import patch

        shop_info = {
            "name": "My Store",
            "city": "Los Angeles",
        }

        with patch.dict(os.environ, {"SHIPPER_ADDRESS1": "456 Oak Ave"}, clear=True):
            shipper = build_shipper(shop_info)

        assert shipper["name"] == "My Store"
        assert shipper["phone"] == ""  # No phone provided, no placeholder
        assert shipper["addressLine1"] == "456 Oak Ave"  # From env var
        assert shipper["city"] == "Los Angeles"  # Provided by shop
        assert shipper["countryCode"] == "US"  # Default

    def test_handles_missing_fields_no_env_vars(self):
        """Test shipper returns empty strings when no shop or env data."""
        import os
        from unittest.mock import patch

        shop_info = {
            "name": "My Store",
            "city": "Los Angeles",
        }

        with patch.dict(os.environ, {}, clear=True):
            shipper = build_shipper(shop_info)

        assert shipper["name"] == "My Store"
        assert shipper["addressLine1"] == ""  # No dummy address
        assert shipper["city"] == "Los Angeles"
        assert shipper["countryCode"] == "US"  # Default origin country

    def test_truncates_long_names(self):
        """Test long store names are truncated."""
        shop_info = {
            "name": "The Absolutely Incredibly Long Store Name That Exceeds UPS Limits",
        }

        shipper = build_shipper(shop_info)

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
            shipper = build_shipper()

        assert shipper["name"] == "Test Shipper"
        assert shipper["phone"] == "5559998888"
        assert shipper["addressLine1"] == "456 Oak Ave"
        assert shipper["city"] == "San Francisco"
        assert shipper["stateProvinceCode"] == "CA"
        assert shipper["postalCode"] == "94102"
        assert shipper["countryCode"] == "US"

    def test_returns_empty_fields_when_missing(self):
        """Test empty strings (no dummy addresses) when env vars not set."""
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {}, clear=True):
            shipper = build_shipper()

        assert shipper["name"] == ""
        assert shipper["addressLine1"] == ""
        assert shipper["city"] == ""
        assert shipper["stateProvinceCode"] == ""
        assert shipper["postalCode"] == ""
        assert shipper["countryCode"] == "US"  # Only country has a default


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

    def test_prefers_ship_to_attention_name_over_company(self):
        """ship_to_attention_name should take precedence over company mapping."""
        order_data = {
            "ship_to_name": "Maria Garcia",
            "ship_to_attention_name": "Maria Garcia",
            "ship_to_company": "Legacy Company",
            "ship_to_city": "Miami",
            "ship_to_state": "FL",
            "ship_to_postal_code": "33139",
            "ship_to_country": "US",
        }

        ship_to = build_ship_to(order_data)

        assert ship_to["attentionName"] == "Maria Garcia"


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


class TestResolvePackagingCode:
    """Test packaging type name-to-code resolution."""

    def test_numeric_codes_pass_through(self):
        """Test numeric codes are returned as-is."""
        assert resolve_packaging_code("02") == "02"
        assert resolve_packaging_code("01") == "01"
        assert resolve_packaging_code("04") == "04"

    def test_single_digit_zero_padded(self):
        """Test single digit codes are zero-padded."""
        assert resolve_packaging_code("2") == "02"
        assert resolve_packaging_code("1") == "01"

    def test_human_readable_customer_supplied(self):
        """Test 'Customer Supplied' maps to '02'."""
        assert resolve_packaging_code("Customer Supplied") == "02"
        assert resolve_packaging_code("Customer Supplied Package") == "02"
        assert resolve_packaging_code("customer supplied") == "02"

    def test_human_readable_pak(self):
        """Test 'PAK' maps to '04'."""
        assert resolve_packaging_code("PAK") == "04"
        assert resolve_packaging_code("pak") == "04"
        assert resolve_packaging_code("UPS PAK") == "04"

    def test_human_readable_letter(self):
        """Test 'UPS Letter' maps to '01'."""
        assert resolve_packaging_code("UPS Letter") == "01"
        assert resolve_packaging_code("Letter") == "01"

    def test_human_readable_tube(self):
        """Test 'Tube' maps to '03'."""
        assert resolve_packaging_code("Tube") == "03"
        assert resolve_packaging_code("UPS Tube") == "03"

    def test_human_readable_express_box(self):
        """Test 'Express Box' maps to '21'."""
        assert resolve_packaging_code("UPS Express Box") == "21"
        assert resolve_packaging_code("Express Box") == "21"

    def test_none_returns_default(self):
        """Test None returns default '02'."""
        assert resolve_packaging_code(None) == "02"

    def test_empty_string_returns_default(self):
        """Test empty string returns default '02'."""
        assert resolve_packaging_code("") == "02"

    def test_unknown_name_returns_default(self):
        """Test unknown packaging name returns default '02'."""
        assert resolve_packaging_code("Unknown Box Type") == "02"

    def test_whitespace_handling(self):
        """Test whitespace is stripped before matching."""
        assert resolve_packaging_code("  PAK  ") == "04"
        assert resolve_packaging_code(" Customer Supplied ") == "02"

    def test_case_insensitive(self):
        """Test matching is case-insensitive."""
        assert resolve_packaging_code("CUSTOMER SUPPLIED") == "02"
        assert resolve_packaging_code("Pak") == "04"
        assert resolve_packaging_code("ups letter") == "01"


class TestBuildPackagesWithNames:
    """Test build_packages resolves human-readable packaging names."""

    def test_single_package_with_name(self):
        """Test single package with human-readable packaging type."""
        order_data = {
            "weight": 2.5,
            "packaging_type": "Customer Supplied",
        }
        packages = build_packages(order_data)
        assert packages[0]["packagingType"] == "02"

    def test_single_package_with_pak(self):
        """Test single package with PAK type."""
        order_data = {
            "weight": 1.0,
            "packaging_type": "PAK",
        }
        packages = build_packages(order_data)
        assert packages[0]["packagingType"] == "04"

    def test_multi_package_with_names(self):
        """Test multi-package array with human-readable names."""
        order_data = {
            "packages": [
                {"weight": 1.0, "packaging_type": "UPS Letter"},
                {"weight": 2.5, "packaging_type": "Customer Supplied"},
            ]
        }
        packages = build_packages(order_data)
        assert packages[0]["packagingType"] == "01"
        assert packages[1]["packagingType"] == "02"

    def test_multi_package_with_numeric_codes(self):
        """Test multi-package array with numeric codes still works."""
        order_data = {
            "packages": [
                {"weight": 1.0, "packaging_type": "04"},
                {"weight": 2.5, "packaging_type": "02"},
            ]
        }
        packages = build_packages(order_data)
        assert packages[0]["packagingType"] == "04"
        assert packages[1]["packagingType"] == "02"


class TestResolvePackagingCodeAlphanumeric:
    """Test alphanumeric UPS packaging codes (2a/2b/2c) pass through correctly."""

    def test_2a_small_express_box_code(self):
        """Code '2a' passes through without falling back to '02'."""
        assert resolve_packaging_code("2a") == "2a"

    def test_2b_medium_express_box_code(self):
        """Code '2b' passes through."""
        assert resolve_packaging_code("2b") == "2b"

    def test_2c_large_express_box_code(self):
        """Code '2c' passes through."""
        assert resolve_packaging_code("2c") == "2c"

    def test_2a_case_insensitive(self):
        """Code '2A' normalizes to '2a'."""
        assert resolve_packaging_code("2A") == "2a"

    def test_small_express_box_name_resolves_to_2a(self):
        """Name 'small express box' still resolves to '2a'."""
        assert resolve_packaging_code("small express box") == "2a"

    def test_non_string_int_coerced(self):
        """Integer packaging value coerced to string."""
        assert resolve_packaging_code(2) == "02"

    def test_non_string_dict_returns_default(self):
        """Dict packaging value coerced to string, falls back to default."""
        assert resolve_packaging_code({}) == "02"


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
        assert request["shipTo"]["attentionName"] == "John Doe"
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

    def test_domestic_payload_includes_attention_name_from_order_data(self):
        """Domestic payload should carry ShipTo.AttentionName from ship_to_attention_name."""
        order_data = {
            "ship_to_name": "Maria Garcia",
            "ship_to_attention_name": "Maria Garcia",
            "ship_to_phone": "10012345667",
            "ship_to_address1": "123 Ocean Drive",
            "ship_to_city": "Miami",
            "ship_to_state": "FL",
            "ship_to_postal_code": "33139",
            "ship_to_country": "US",
            "service_code": "14",
            "weight": 5.0,
        }
        simplified = build_shipment_request(order_data)
        full = build_ups_api_payload(simplified, account_number="ABC123")
        ship_to = full["ShipmentRequest"]["Shipment"]["ShipTo"]
        assert ship_to["AttentionName"] == "Maria Garcia"

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

    def test_reference_not_included_at_shipment_level(self):
        """Test ReferenceNumber is NOT included at shipment level.

        UPS Ground domestic rejects shipment-level reference numbers.
        """
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
        assert "ReferenceNumber" not in shipment


    def test_packaging_key_name(self):
        """Test package uses 'Packaging' key (not 'PackagingType')."""
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
        pkg = result["ShipmentRequest"]["Shipment"]["Package"][0]
        assert "Packaging" in pkg
        assert "PackagingType" not in pkg
        assert pkg["Packaging"]["Code"] == "02"

    def test_shipment_charge_is_array(self):
        """Test ShipmentCharge is wrapped in an array per UPS schema."""
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

        result = build_ups_api_payload(simplified, account_number="ABC")
        payment = result["ShipmentRequest"]["Shipment"]["PaymentInformation"]
        assert isinstance(payment["ShipmentCharge"], list)
        assert len(payment["ShipmentCharge"]) == 1
        assert payment["ShipmentCharge"][0]["Type"] == "01"
        assert payment["ShipmentCharge"][0]["BillShipper"]["AccountNumber"] == "ABC"

    def test_reference_numbers_omitted(self):
        """Test reference numbers are not included at shipment level.

        UPS rejects shipment-level ReferenceNumber for certain services.
        """
        simplified = {
            "shipper": {"name": "S", "addressLine1": "A", "city": "C",
                        "stateProvinceCode": "CA", "postalCode": "90001",
                        "countryCode": "US"},
            "shipTo": {"name": "R", "addressLine1": "B", "city": "D",
                       "stateProvinceCode": "NY", "postalCode": "10001",
                       "countryCode": "US"},
            "packages": [{"weight": 1.0}],
            "serviceCode": "03",
            "reference": "REF-001",
            "reference2": "REF-002",
        }

        result = build_ups_api_payload(simplified, account_number="X")
        shipment = result["ShipmentRequest"]["Shipment"]
        assert "ReferenceNumber" not in shipment
        assert "ReferenceNumber2" not in shipment

    def test_includes_transaction_reference_when_idempotency_key_provided(self):
        """When idempotency_key is provided, payload includes TransactionReference."""
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

        result = build_ups_api_payload(
            simplified, account_number="X", idempotency_key="job:1:hash"
        )
        ref = result["ShipmentRequest"]["Request"]["TransactionReference"]
        assert ref["CustomerContext"] == "job:1:hash"

    def test_omits_transaction_reference_when_no_idempotency_key(self):
        """When no idempotency_key, no TransactionReference in payload."""
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
        assert "TransactionReference" not in result["ShipmentRequest"]["Request"]


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

    def test_rate_packaging_key_name(self):
        """Rate payload uses 'Packaging' key (not 'PackagingType')."""
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
        pkg = result["RateRequest"]["Shipment"]["Package"][0]
        assert "Packaging" in pkg
        assert "PackagingType" not in pkg
        assert pkg["Packaging"]["Code"] == "02"

    def test_shop_request_option_supported(self):
        """Rate payload can emit Shop request option for service discovery."""
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
        result = build_ups_rate_payload(
            simplified,
            account_number="X",
            request_option="Shop",
            include_service=False,
        )
        request = result["RateRequest"]["Request"]
        shipment = result["RateRequest"]["Shipment"]
        assert request["RequestOption"] == "Shop"
        assert "Service" not in shipment


# ── Helper to build minimal simplified payloads ──


def _minimal_simplified(**overrides: Any) -> dict[str, Any]:
    """Build a minimal simplified payload for tests."""
    base = {
        "shipper": {
            "name": "S", "addressLine1": "A", "city": "C",
            "stateProvinceCode": "CA", "postalCode": "90001",
            "countryCode": "US",
        },
        "shipTo": {
            "name": "R", "addressLine1": "B", "city": "D",
            "stateProvinceCode": "NY", "postalCode": "10001",
            "countryCode": "US",
        },
        "packages": [{"weight": 1.0}],
        "serviceCode": "03",
    }
    base.update(overrides)
    return base


# ── Tests for resolve_service_code ──


class TestResolveServiceCode:
    """Test service code name-to-code resolution."""

    def test_numeric_codes_pass_through(self):
        """Test numeric codes returned as-is."""
        assert resolve_service_code("03") == "03"
        assert resolve_service_code("01") == "01"
        assert resolve_service_code("14") == "14"

    def test_ground_aliases(self):
        """Test Ground service aliases."""
        assert resolve_service_code("ground") == "03"
        assert resolve_service_code("UPS Ground") == "03"

    def test_next_day_air_aliases(self):
        """Test NDA aliases."""
        assert resolve_service_code("next day air") == "01"
        assert resolve_service_code("overnight") == "01"
        assert resolve_service_code("NDA") == "01"

    def test_2nd_day_aliases(self):
        """Test 2nd Day Air aliases."""
        assert resolve_service_code("2nd day air") == "02"
        assert resolve_service_code("2 day") == "02"
        assert resolve_service_code("two day") == "02"

    def test_3_day_select(self):
        """Test 3 Day Select aliases."""
        assert resolve_service_code("3 day select") == "12"
        assert resolve_service_code("3 day") == "12"

    def test_nda_saver(self):
        """Test NDA Saver aliases."""
        assert resolve_service_code("next day air saver") == "13"
        assert resolve_service_code("NDA Saver") == "13"
        assert resolve_service_code("saver") == "13"

    def test_nda_early(self):
        """Test NDA Early aliases."""
        assert resolve_service_code("next day air early") == "14"
        assert resolve_service_code("early am") == "14"

    def test_2nd_day_air_am(self):
        """Test 2nd Day Air AM aliases."""
        assert resolve_service_code("2nd day air am") == "59"
        assert resolve_service_code("2 day am") == "59"

    def test_none_returns_default(self):
        """Test None returns default."""
        assert resolve_service_code(None) == "03"
        assert resolve_service_code(None, "01") == "01"

    def test_empty_returns_default(self):
        """Test empty string returns default."""
        assert resolve_service_code("") == "03"

    def test_unknown_returns_default(self):
        """Test unknown name returns default."""
        assert resolve_service_code("Super Fast Shipping") == "03"

    def test_case_insensitive(self):
        """Test matching is case-insensitive."""
        assert resolve_service_code("GROUND") == "03"
        assert resolve_service_code("Next Day Air") == "01"


class TestGetServiceCodeResolvesNames:
    """Test get_service_code resolves names in both service_code and service fields."""

    def test_resolves_name_in_service_code_field(self):
        """Test human name in service_code field is resolved."""
        assert get_service_code({"service_code": "Ground"}) == "03"
        assert get_service_code({"service_code": "Next Day Air"}) == "01"

    def test_resolves_name_in_service_field(self):
        """Test human name in service field is resolved."""
        assert get_service_code({"service": "2nd Day Air"}) == "02"

    def test_service_code_takes_precedence(self):
        """Test service_code field takes precedence over service field."""
        order = {"service_code": "01", "service": "Ground"}
        assert get_service_code(order) == "01"


# ── Tests for declared value ──


class TestDeclaredValue:
    """Test declared value flows through the pipeline."""

    def test_single_package_declared_value(self):
        """Test declared value on single package."""
        packages = build_packages({"weight": 2.0, "declared_value": 500.00})
        assert packages[0]["declaredValue"] == 500.0

    def test_multi_package_declared_value(self):
        """Test declared value on multi-package."""
        packages = build_packages({
            "packages": [
                {"weight": 1.0, "declared_value": 100},
                {"weight": 2.0},
            ]
        })
        assert packages[0]["declaredValue"] == 100.0
        assert "declaredValue" not in packages[1]

    def test_declared_value_not_set_when_missing(self):
        """Test no declaredValue key when not provided."""
        packages = build_packages({"weight": 1.0})
        assert "declaredValue" not in packages[0]

    def test_declared_value_in_shipment_payload(self):
        """Test declared value appears in UPS API payload."""
        simplified = _minimal_simplified(
            packages=[{"weight": 2.0, "declaredValue": 250.0}]
        )
        result = build_ups_api_payload(simplified, account_number="X")
        pkg = result["ShipmentRequest"]["Shipment"]["Package"][0]
        dv = pkg["PackageServiceOptions"]["DeclaredValue"]
        assert dv["MonetaryValue"] == "250.0"
        assert dv["CurrencyCode"] == "USD"

    def test_declared_value_in_rate_payload(self):
        """Test declared value appears in UPS rate payload."""
        simplified = _minimal_simplified(
            packages=[{"weight": 2.0, "declaredValue": 100.0}]
        )
        result = build_ups_rate_payload(simplified, account_number="X")
        pkg = result["RateRequest"]["Shipment"]["Package"][0]
        dv = pkg["PackageServiceOptions"]["DeclaredValue"]
        assert dv["MonetaryValue"] == "100.0"


# ── Tests for delivery confirmation / signature ──


class TestDeliveryConfirmation:
    """Test delivery confirmation / signature support."""

    def test_signature_required_boolean(self):
        """Test signature_required=True sets DCISType=1."""
        order = {
            "ship_to_name": "J", "ship_to_city": "LA",
            "ship_to_state": "CA", "signature_required": True,
        }
        req = build_shipment_request(order)
        assert req["deliveryConfirmation"] == "1"

    def test_adult_signature_required(self):
        """Test adult_signature_required=True sets DCISType=2."""
        order = {
            "ship_to_name": "J", "ship_to_city": "LA",
            "ship_to_state": "CA", "adult_signature_required": True,
        }
        req = build_shipment_request(order)
        assert req["deliveryConfirmation"] == "2"

    def test_delivery_confirmation_name(self):
        """Test human name 'Signature Required' resolved to '1'."""
        order = {
            "ship_to_name": "J", "ship_to_city": "LA",
            "ship_to_state": "CA",
            "delivery_confirmation": "Signature Required",
        }
        req = build_shipment_request(order)
        assert req["deliveryConfirmation"] == "1"

    def test_delivery_confirmation_code(self):
        """Test explicit code '2' passes through."""
        order = {
            "ship_to_name": "J", "ship_to_city": "LA",
            "ship_to_state": "CA", "delivery_confirmation": "2",
        }
        req = build_shipment_request(order)
        assert req["deliveryConfirmation"] == "2"

    def test_no_delivery_confirmation_when_not_set(self):
        """Test no deliveryConfirmation key when not requested."""
        order = {
            "ship_to_name": "J", "ship_to_city": "LA",
            "ship_to_state": "CA",
        }
        req = build_shipment_request(order)
        assert "deliveryConfirmation" not in req

    def test_delivery_confirmation_in_shipment_payload(self):
        """Test DC appears in UPS ShipmentRequest."""
        simplified = _minimal_simplified(deliveryConfirmation="1")
        result = build_ups_api_payload(simplified, account_number="X")
        opts = result["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"]
        assert opts["DeliveryConfirmation"]["DCISType"] == "1"

    def test_delivery_confirmation_in_rate_payload(self):
        """Test DC appears in UPS RateRequest."""
        simplified = _minimal_simplified(deliveryConfirmation="2")
        result = build_ups_rate_payload(simplified, account_number="X")
        opts = result["RateRequest"]["Shipment"]["ShipmentServiceOptions"]
        assert opts["DeliveryConfirmation"]["DCISType"] == "2"

    def test_string_yes_for_signature(self):
        """Test string 'yes' treated as truthy for signature_required."""
        order = {
            "ship_to_name": "J", "ship_to_city": "LA",
            "ship_to_state": "CA", "signature_required": "yes",
        }
        req = build_shipment_request(order)
        assert req["deliveryConfirmation"] == "1"


# ── Tests for residential indicator ──


class TestResidentialIndicator:
    """Test residential address indicator."""

    def test_residential_from_ship_to_residential(self):
        """Test ship_to_residential=True sets residential flag."""
        order = {
            "ship_to_name": "J", "ship_to_city": "LA",
            "ship_to_state": "CA", "ship_to_residential": True,
        }
        req = build_shipment_request(order)
        assert req["residential"] is True

    def test_residential_from_residential_field(self):
        """Test residential=True sets residential flag."""
        order = {
            "ship_to_name": "J", "ship_to_city": "LA",
            "ship_to_state": "CA", "residential": "yes",
        }
        req = build_shipment_request(order)
        assert req["residential"] is True

    def test_no_residential_when_not_set(self):
        """Test no residential key when not set."""
        order = {
            "ship_to_name": "J", "ship_to_city": "LA",
            "ship_to_state": "CA",
        }
        req = build_shipment_request(order)
        assert "residential" not in req

    def test_residential_in_shipment_payload(self):
        """Test ResidentialAddressIndicator in ShipTo address."""
        simplified = _minimal_simplified(residential=True)
        result = build_ups_api_payload(simplified, account_number="X")
        addr = result["ShipmentRequest"]["Shipment"]["ShipTo"]["Address"]
        assert "ResidentialAddressIndicator" in addr

    def test_residential_in_rate_payload(self):
        """Test ResidentialAddressIndicator in rate ShipTo address."""
        simplified = _minimal_simplified(residential=True)
        result = build_ups_rate_payload(simplified, account_number="X")
        addr = result["RateRequest"]["Shipment"]["ShipTo"]["Address"]
        assert "ResidentialAddressIndicator" in addr

    def test_no_residential_indicator_when_false(self):
        """Test no indicator when residential not set."""
        simplified = _minimal_simplified()
        result = build_ups_api_payload(simplified, account_number="X")
        addr = result["ShipmentRequest"]["Shipment"]["ShipTo"]["Address"]
        assert "ResidentialAddressIndicator" not in addr


# ── Tests for package-level reference numbers ──


class TestPackageLevelReferences:
    """Test reference numbers at package level."""

    def test_reference_added_to_first_package(self):
        """Test reference number on first package."""
        simplified = _minimal_simplified(reference="ORD-1001")
        result = build_ups_api_payload(simplified, account_number="X")
        pkg = result["ShipmentRequest"]["Shipment"]["Package"][0]
        assert "ReferenceNumber" in pkg
        assert pkg["ReferenceNumber"][0]["Value"] == "ORD-1001"

    def test_two_references_on_package(self):
        """Test both reference and reference2 on first package."""
        simplified = _minimal_simplified(
            reference="ORD-1001", reference2="PO-555"
        )
        result = build_ups_api_payload(simplified, account_number="X")
        pkg = result["ShipmentRequest"]["Shipment"]["Package"][0]
        refs = pkg["ReferenceNumber"]
        assert len(refs) == 2
        assert refs[0]["Value"] == "ORD-1001"
        assert refs[1]["Value"] == "PO-555"

    def test_no_reference_when_not_provided(self):
        """Test no ReferenceNumber when reference is None."""
        simplified = _minimal_simplified()
        result = build_ups_api_payload(simplified, account_number="X")
        pkg = result["ShipmentRequest"]["Shipment"]["Package"][0]
        assert "ReferenceNumber" not in pkg

    def test_reference_truncated_to_35_chars(self):
        """Test long reference truncated to UPS max 35 chars."""
        long_ref = "A" * 50
        simplified = _minimal_simplified(reference=long_ref)
        result = build_ups_api_payload(simplified, account_number="X")
        pkg = result["ShipmentRequest"]["Shipment"]["Package"][0]
        assert len(pkg["ReferenceNumber"][0]["Value"]) == 35

    def test_shipment_level_still_excluded(self):
        """Test shipment level still has no ReferenceNumber."""
        simplified = _minimal_simplified(reference="ORD-1001")
        result = build_ups_api_payload(simplified, account_number="X")
        shipment = result["ShipmentRequest"]["Shipment"]
        assert "ReferenceNumber" not in shipment


# ── Tests for Saturday delivery ──


class TestSaturdayDelivery:
    """Test Saturday delivery option."""

    def test_saturday_delivery_from_order_data(self):
        """Test saturday_delivery=True flows to simplified payload."""
        order = {
            "ship_to_name": "J", "ship_to_city": "LA",
            "ship_to_state": "CA", "saturday_delivery": True,
        }
        req = build_shipment_request(order)
        assert req["saturdayDelivery"] is True

    def test_saturday_delivery_string_yes(self):
        """Test saturday_delivery='yes' treated as truthy."""
        order = {
            "ship_to_name": "J", "ship_to_city": "LA",
            "ship_to_state": "CA", "saturday_delivery": "yes",
        }
        req = build_shipment_request(order)
        assert req["saturdayDelivery"] is True

    def test_no_saturday_when_not_set(self):
        """Test no saturdayDelivery when not requested."""
        order = {
            "ship_to_name": "J", "ship_to_city": "LA",
            "ship_to_state": "CA",
        }
        req = build_shipment_request(order)
        assert "saturdayDelivery" not in req

    def test_saturday_in_shipment_payload(self):
        """Test SaturdayDeliveryIndicator in ShipmentServiceOptions."""
        simplified = _minimal_simplified(saturdayDelivery=True)
        result = build_ups_api_payload(simplified, account_number="X")
        opts = result["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"]
        assert "SaturdayDeliveryIndicator" in opts

    def test_saturday_in_rate_payload(self):
        """Test SaturdayDeliveryIndicator in rate ShipmentServiceOptions."""
        simplified = _minimal_simplified(saturdayDelivery=True)
        result = build_ups_rate_payload(simplified, account_number="X")
        opts = result["RateRequest"]["Shipment"]["ShipmentServiceOptions"]
        assert "SaturdayDeliveryIndicator" in opts

    def test_no_saturday_in_rate_payload_when_not_set(self):
        """Test no SaturdayDeliveryIndicator when not requested."""
        simplified = _minimal_simplified()
        result = build_ups_rate_payload(simplified, account_number="X")
        shipment = result["RateRequest"]["Shipment"]
        assert "ShipmentServiceOptions" not in shipment or \
            "SaturdayDeliveryIndicator" not in shipment.get("ShipmentServiceOptions", {})


# ── Tests for rate/shipping payload parity ──


class TestRatePayloadParity:
    """Test rate payload includes billing context for accurate quotes."""

    def test_rate_payload_includes_payment_information(self):
        """Test rate payload has PaymentInformation matching shipping payload."""
        simplified = _minimal_simplified()
        result = build_ups_rate_payload(simplified, account_number="ABC123")
        payment = result["RateRequest"]["Shipment"]["PaymentInformation"]
        assert isinstance(payment["ShipmentCharge"], list)
        assert len(payment["ShipmentCharge"]) == 1
        assert payment["ShipmentCharge"][0]["Type"] == "01"
        assert payment["ShipmentCharge"][0]["BillShipper"]["AccountNumber"] == "ABC123"

    def test_rate_payload_includes_negotiated_rates_indicator(self):
        """Test rate payload has ShipmentRatingOptions.NegotiatedRatesIndicator."""
        simplified = _minimal_simplified()
        result = build_ups_rate_payload(simplified, account_number="X")
        opts = result["RateRequest"]["Shipment"]["ShipmentRatingOptions"]
        assert "NegotiatedRatesIndicator" in opts

    def test_shipping_payload_includes_negotiated_rates_indicator(self):
        """Test shipping payload has ShipmentRatingOptions.NegotiatedRatesIndicator."""
        simplified = _minimal_simplified()
        result = build_ups_api_payload(simplified, account_number="X")
        opts = result["ShipmentRequest"]["Shipment"]["ShipmentRatingOptions"]
        assert "NegotiatedRatesIndicator" in opts

    def test_rate_and_shipping_payment_info_match(self):
        """Test PaymentInformation structure is identical between rate and shipping."""
        simplified = _minimal_simplified()
        acct = "TESTACCT"
        rate_result = build_ups_rate_payload(simplified, account_number=acct)
        ship_result = build_ups_api_payload(simplified, account_number=acct)
        rate_payment = rate_result["RateRequest"]["Shipment"]["PaymentInformation"]
        ship_payment = ship_result["ShipmentRequest"]["Shipment"]["PaymentInformation"]
        assert rate_payment == ship_payment

    def test_rate_payload_includes_contact_fields_when_provided(self):
        """Rate payload should preserve explicit contact fields."""
        simplified = _minimal_simplified(
            shipper={
                "name": "S",
                "attentionName": "Shipping Desk",
                "phone": "18005551234",
                "addressLine1": "A",
                "city": "C",
                "stateProvinceCode": "CA",
                "postalCode": "90001",
                "countryCode": "US",
            },
            shipTo={
                "name": "R",
                "attentionName": "Maria Garcia",
                "phone": "15145551234",
                "addressLine1": "B",
                "city": "Montreal",
                "stateProvinceCode": "QC",
                "postalCode": "H3A 1E8",
                "countryCode": "CA",
            },
            serviceCode="11",
        )

        rate_result = build_ups_rate_payload(simplified, account_number="ABC123")
        shipment = rate_result["RateRequest"]["Shipment"]
        assert shipment["Shipper"]["AttentionName"] == "Shipping Desk"
        assert shipment["Shipper"]["Phone"]["Number"] == "18005551234"
        assert shipment["ShipTo"]["AttentionName"] == "Maria Garcia"
        assert shipment["ShipTo"]["Phone"]["Number"] == "15145551234"


# ── Tests for Shopify weight conversion ──


class TestShopifyWeightConversion:
    """Test build_packages handles Shopify total_weight_grams."""

    def test_converts_grams_to_lbs(self):
        """Test total_weight_grams is converted to lbs."""
        order_data = {"total_weight_grams": 453.592}  # ~1 lb
        packages = build_packages(order_data)
        assert len(packages) == 1
        assert abs(packages[0]["weight"] - 1.0) < 0.01

    def test_grams_conversion_heavier_package(self):
        """Test heavier package grams conversion."""
        order_data = {"total_weight_grams": 2267.96}  # ~5 lbs
        packages = build_packages(order_data)
        assert abs(packages[0]["weight"] - 5.0) < 0.01

    def test_weight_field_takes_precedence_over_grams(self):
        """Test weight field is preferred over total_weight_grams."""
        order_data = {"weight": 3.0, "total_weight_grams": 453.592}
        packages = build_packages(order_data)
        assert packages[0]["weight"] == 3.0

    def test_total_weight_takes_precedence_over_grams(self):
        """Test total_weight is preferred over total_weight_grams."""
        order_data = {"total_weight": 4.0, "total_weight_grams": 453.592}
        packages = build_packages(order_data)
        assert packages[0]["weight"] == 4.0

    def test_defaults_to_1_with_no_weight_keys(self):
        """Test defaults to 1.0 when no weight fields present."""
        order_data = {"ship_to_name": "John"}
        packages = build_packages(order_data)
        assert packages[0]["weight"] == 1.0


# ── Tests for InternationalForms Contacts.SoldTo ──


class TestInternationalFormsSoldToContacts:
    """Test Contacts.SoldTo injection in InternationalForms."""

    @pytest.fixture()
    def sample_commodities(self) -> list[dict]:
        """Return a minimal commodity list for tests."""
        return [{
            "description": "T-Shirt",
            "commodity_code": "6109100010",
            "origin_country": "US",
            "quantity": 2,
            "unit_value": "25.00",
        }]

    @pytest.fixture()
    def sample_sold_to(self) -> dict[str, str]:
        """Return a sample sold_to (recipient) dict."""
        return {
            "name": "Jane Smith",
            "attentionName": "Acme Corp",
            "phone": "4165551234",
            "addressLine1": "100 Queen St W",
            "addressLine2": "Suite 400",
            "city": "Toronto",
            "stateProvinceCode": "ON",
            "postalCode": "M5H 2N2",
            "countryCode": "CA",
        }

    def test_sold_to_included_when_provided(
        self, sample_commodities: list[dict], sample_sold_to: dict[str, str]
    ):
        """Test Contacts.SoldTo is present when sold_to is passed."""
        forms = build_international_forms(
            commodities=sample_commodities, sold_to=sample_sold_to
        )
        assert "Contacts" in forms
        assert "SoldTo" in forms["Contacts"]

    def test_sold_to_name_and_attention(
        self, sample_commodities: list[dict], sample_sold_to: dict[str, str]
    ):
        """Test SoldTo Name and AttentionName populated correctly."""
        forms = build_international_forms(
            commodities=sample_commodities, sold_to=sample_sold_to
        )
        sold = forms["Contacts"]["SoldTo"]
        assert sold["Name"] == "Jane Smith"
        assert sold["AttentionName"] == "Acme Corp"

    def test_sold_to_address_structure(
        self, sample_commodities: list[dict], sample_sold_to: dict[str, str]
    ):
        """Test SoldTo Address has required UPS fields."""
        forms = build_international_forms(
            commodities=sample_commodities, sold_to=sample_sold_to
        )
        addr = forms["Contacts"]["SoldTo"]["Address"]
        assert addr["AddressLine"] == ["100 Queen St W", "Suite 400"]
        assert addr["City"] == "Toronto"
        assert addr["StateProvinceCode"] == "ON"
        assert addr["PostalCode"] == "M5H 2N2"
        assert addr["CountryCode"] == "CA"

    def test_sold_to_phone_included(
        self, sample_commodities: list[dict], sample_sold_to: dict[str, str]
    ):
        """Test SoldTo Phone is included when provided."""
        forms = build_international_forms(
            commodities=sample_commodities, sold_to=sample_sold_to
        )
        assert forms["Contacts"]["SoldTo"]["Phone"]["Number"] == "4165551234"

    def test_sold_to_phone_omitted_when_empty(
        self, sample_commodities: list[dict], sample_sold_to: dict[str, str]
    ):
        """Test SoldTo Phone is omitted when phone is empty."""
        sample_sold_to.pop("phone")
        forms = build_international_forms(
            commodities=sample_commodities, sold_to=sample_sold_to
        )
        assert "Phone" not in forms["Contacts"]["SoldTo"]

    def test_attention_name_defaults_to_name(
        self, sample_commodities: list[dict]
    ):
        """Test AttentionName falls back to Name when not provided."""
        sold_to = {
            "name": "Bob Jones",
            "addressLine1": "1 Main St",
            "city": "Vancouver",
            "stateProvinceCode": "BC",
            "postalCode": "V6B 1A1",
            "countryCode": "CA",
        }
        forms = build_international_forms(
            commodities=sample_commodities, sold_to=sold_to
        )
        sold = forms["Contacts"]["SoldTo"]
        assert sold["AttentionName"] == "Bob Jones"

    def test_no_contacts_when_sold_to_is_none(
        self, sample_commodities: list[dict]
    ):
        """Test no Contacts section when sold_to is not provided."""
        forms = build_international_forms(commodities=sample_commodities)
        assert "Contacts" not in forms

    def test_sold_to_name_truncated_to_35(
        self, sample_commodities: list[dict]
    ):
        """Test SoldTo Name is truncated to 35 chars (UPS limit)."""
        sold_to = {
            "name": "A" * 50,
            "addressLine1": "1 Main St",
            "city": "Toronto",
            "stateProvinceCode": "ON",
            "postalCode": "M5H 2N2",
            "countryCode": "CA",
        }
        forms = build_international_forms(
            commodities=sample_commodities, sold_to=sold_to
        )
        assert len(forms["Contacts"]["SoldTo"]["Name"]) == 35

    def test_address_line2_omitted_when_empty(
        self, sample_commodities: list[dict]
    ):
        """Test AddressLine only has non-empty entries."""
        sold_to = {
            "name": "Test",
            "addressLine1": "1 Main St",
            "city": "Toronto",
            "stateProvinceCode": "ON",
            "postalCode": "M5H 2N2",
            "countryCode": "CA",
        }
        forms = build_international_forms(
            commodities=sample_commodities, sold_to=sold_to
        )
        assert forms["Contacts"]["SoldTo"]["Address"]["AddressLine"] == ["1 Main St"]


class TestBuildShipmentRequestSoldTo:
    """Test build_shipment_request passes ship_to as sold_to for international."""

    @pytest.fixture(autouse=True)
    def _enable_us_ca_lane(self, monkeypatch: pytest.MonkeyPatch):
        """Enable US-CA international lane for all tests in this class."""
        monkeypatch.setenv("INTERNATIONAL_ENABLED_LANES", "US-CA")

    def test_international_shipment_has_sold_to(self):
        """Test US→CA shipment includes Contacts.SoldTo in internationalForms."""
        order_data = {
            "ship_to_name": "Marie Tremblay",
            "ship_to_phone": "514-555-1234",
            "ship_to_address1": "200 Rue Sainte-Catherine",
            "ship_to_city": "Montreal",
            "ship_to_state": "QC",
            "ship_to_postal_code": "H2X 1L4",
            "ship_to_country": "CA",
            "weight": 2.0,
            "service_code": "11",
            "commodities": [{
                "description": "Cotton T-Shirt",
                "commodity_code": "6109100010",
                "origin_country": "US",
                "quantity": 3,
                "unit_value": "20.00",
            }],
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

        assert "internationalForms" in request
        forms = request["internationalForms"]
        assert "Contacts" in forms
        sold = forms["Contacts"]["SoldTo"]
        assert sold["Name"] == "Marie Tremblay"
        assert sold["Address"]["City"] == "Montreal"
        assert sold["Address"]["CountryCode"] == "CA"

    def test_domestic_shipment_has_no_international_forms(self):
        """Test US→US shipment does NOT include internationalForms."""
        order_data = {
            "ship_to_name": "John Doe",
            "ship_to_address1": "123 Main St",
            "ship_to_city": "Los Angeles",
            "ship_to_state": "CA",
            "ship_to_postal_code": "90001",
            "ship_to_country": "US",
            "weight": 2.0,
        }
        shipper = {
            "name": "Test Store",
            "addressLine1": "456 Oak Ave",
            "city": "San Francisco",
            "stateProvinceCode": "CA",
            "postalCode": "94102",
            "countryCode": "US",
        }

        request = build_shipment_request(order_data, shipper)

        assert "internationalForms" not in request

    def test_sold_to_phone_matches_ship_to(self):
        """Test SoldTo phone comes from the ship_to (recipient) data."""
        order_data = {
            "ship_to_name": "Test Recipient",
            "ship_to_phone": "416-555-9999",
            "ship_to_address1": "100 King St",
            "ship_to_city": "Toronto",
            "ship_to_state": "ON",
            "ship_to_postal_code": "M5H 1A1",
            "ship_to_country": "CA",
            "weight": 1.0,
            "service_code": "11",
            "commodities": [{
                "description": "Widget",
                "commodity_code": "8471300000",
                "origin_country": "US",
                "quantity": 1,
                "unit_value": "50.00",
            }],
        }
        shipper = {
            "name": "Shipper",
            "phone": "5551110000",
            "addressLine1": "1 Elm St",
            "city": "New York",
            "stateProvinceCode": "NY",
            "postalCode": "10001",
            "countryCode": "US",
        }

        request = build_shipment_request(order_data, shipper)

        sold = request["internationalForms"]["Contacts"]["SoldTo"]
        assert sold["Phone"]["Number"] == "4165559999"


# ── Tests for consolidated build_shipper ──


class TestBuildShipper:
    """Test unified build_shipper function."""

    def test_no_env_vars_returns_empty_fields(self):
        """Test no dummy addresses when env vars are missing."""
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {}, clear=True):
            shipper = build_shipper()

        assert shipper["name"] == ""
        assert shipper["addressLine1"] == ""
        assert shipper["city"] == ""
        assert shipper["stateProvinceCode"] == ""
        assert shipper["postalCode"] == ""
        assert shipper["countryCode"] == "US"  # Only country has a default

    def test_env_vars_populate_shipper(self):
        """Test env vars are read correctly."""
        import os
        from unittest.mock import patch

        env_vars = {
            "SHIPPER_NAME": "Test Store",
            "SHIPPER_PHONE": "555-888-7777",
            "SHIPPER_ADDRESS1": "100 Oak Ave",
            "SHIPPER_CITY": "Denver",
            "SHIPPER_STATE": "CO",
            "SHIPPER_ZIP": "80202",
            "SHIPPER_COUNTRY": "US",
        }

        with patch.dict(os.environ, env_vars):
            shipper = build_shipper()

        assert shipper["name"] == "Test Store"
        assert shipper["phone"] == "5558887777"
        assert shipper["addressLine1"] == "100 Oak Ave"
        assert shipper["city"] == "Denver"
        assert shipper["stateProvinceCode"] == "CO"
        assert shipper["postalCode"] == "80202"

    def test_shop_info_overlays_env_vars(self):
        """Test Shopify values override env vars."""
        import os
        from unittest.mock import patch

        env_vars = {
            "SHIPPER_NAME": "Env Store",
            "SHIPPER_CITY": "San Francisco",
        }
        shop_info = {
            "name": "Shopify Store",
            "city": "Portland",
            "province_code": "OR",
            "zip": "97201",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            shipper = build_shipper(shop_info)

        assert shipper["name"] == "Shopify Store"  # Shop overrides env
        assert shipper["city"] == "Portland"  # Shop overrides env
        assert shipper["stateProvinceCode"] == "OR"
        assert shipper["postalCode"] == "97201"

    def test_shop_info_does_not_override_with_empty(self):
        """Test empty shop values don't override env vars."""
        import os
        from unittest.mock import patch

        env_vars = {
            "SHIPPER_NAME": "Env Store",
            "SHIPPER_CITY": "San Francisco",
        }
        shop_info = {
            "name": "",  # Empty — should NOT override
            "city": "Portland",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            shipper = build_shipper(shop_info)

        assert shipper["name"] == "Env Store"  # Empty shop value doesn't override
        assert shipper["city"] == "Portland"  # Non-empty shop value does override

    def test_shop_name_truncated(self):
        """Test shop name is truncated to UPS max length."""
        shop_info = {
            "name": "A" * 50,
        }
        shipper = build_shipper(shop_info)
        assert len(shipper["name"]) <= 35

    def test_shop_phone_normalized(self):
        """Test shop phone is normalized to digits."""
        shop_info = {
            "phone": "(555) 123-4567",
        }
        shipper = build_shipper(shop_info)
        assert shipper["phone"] == "5551234567"

    def test_shop_zip_normalized(self):
        """Test shop zip is normalized."""
        shop_info = {
            "zip": "902101234",
        }
        shipper = build_shipper(shop_info)
        assert shipper["postalCode"] == "90210-1234"
