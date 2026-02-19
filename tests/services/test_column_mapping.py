"""Tests for column mapping service."""

from src.services.column_mapping import (
    _FIELD_TO_ORDER_DATA,
    apply_mapping,
    auto_map_columns,
    validate_mapping,
)


class TestValidateMapping:
    """Test mapping validation."""

    def test_valid_mapping_passes(self):
        """Test valid mapping with all required fields."""
        mapping = {
            "shipTo.name": "recipient_name",
            "shipTo.addressLine1": "address",
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
        }

        errors = validate_mapping(mapping)
        assert errors == []

    def test_missing_required_field(self):
        """Test missing required field is reported."""
        mapping = {
            "shipTo.name": "recipient_name",
            # Missing addressLine1
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
        }

        errors = validate_mapping(mapping)
        assert len(errors) == 1
        assert "shipTo.addressLine1" in errors[0]

    def test_extra_optional_fields_allowed(self):
        """Test optional fields don't cause errors."""
        mapping = {
            "shipTo.name": "name",
            "shipTo.addressLine1": "addr1",
            "shipTo.addressLine2": "addr2",
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
            "shipTo.phone": "phone",
            "description": "notes",
        }

        errors = validate_mapping(mapping)
        assert errors == []


class TestApplyMapping:
    """Test mapping application to row data."""

    def test_extracts_fields(self):
        """Test fields are extracted from row using mapping."""
        mapping = {
            "shipTo.name": "recipient",
            "shipTo.addressLine1": "address",
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight_lbs",
        }

        row = {
            "recipient": "John Doe",
            "address": "123 Main St",
            "city": "Los Angeles",
            "state": "CA",
            "zip": "90001",
            "country": "US",
            "weight_lbs": 2.5,
        }

        order_data = apply_mapping(mapping, row)

        assert order_data["ship_to_name"] == "John Doe"
        assert order_data["ship_to_address1"] == "123 Main St"
        assert order_data["ship_to_city"] == "Los Angeles"
        assert order_data["ship_to_state"] == "CA"
        assert order_data["ship_to_postal_code"] == "90001"
        assert order_data["ship_to_country"] == "US"
        assert order_data["weight"] == 2.5

    def test_handles_missing_optional_fields(self):
        """Test missing optional fields are not included."""
        mapping = {
            "shipTo.name": "name",
            "shipTo.addressLine1": "addr",
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
        }

        row = {
            "name": "Jane",
            "addr": "456 Oak",
            "city": "SF",
            "state": "CA",
            "zip": "94102",
            "country": "US",
            "weight": 1.0,
        }

        order_data = apply_mapping(mapping, row)

        assert "ship_to_phone" not in order_data
        assert "ship_to_address2" not in order_data

    def test_includes_service_code(self):
        """Test serviceCode is mapped."""
        mapping = {
            "shipTo.name": "name",
            "shipTo.addressLine1": "addr",
            "shipTo.city": "city",
            "shipTo.stateProvinceCode": "state",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
            "serviceCode": "service",
        }

        row = {
            "name": "Jane",
            "addr": "456 Oak",
            "city": "SF",
            "state": "CA",
            "zip": "94102",
            "country": "US",
            "weight": 1.0,
            "service": "01",
        }

        order_data = apply_mapping(mapping, row)

        assert order_data["service_code"] == "01"


class TestAutoMapColumns:
    """Test auto column mapping heuristics."""

    # Shopify ExternalOrder columns (minus items/raw_data)
    SHOPIFY_COLUMNS = sorted([
        "platform", "order_id", "order_number", "status", "created_at",
        "customer_name", "customer_email",
        "ship_to_name", "ship_to_company", "ship_to_address1", "ship_to_address2",
        "ship_to_city", "ship_to_state", "ship_to_postal_code",
        "ship_to_country", "ship_to_phone",
        "total_price", "financial_status", "fulfillment_status", "tags",
        "total_weight_grams", "shipping_method", "item_count",
    ])

    def test_ship_to_name_over_customer_name(self):
        """ship_to_name must map to shipTo.name, not customer_name."""
        mapping = auto_map_columns(self.SHOPIFY_COLUMNS)
        assert mapping.get("shipTo.name") == "ship_to_name"

    def test_customer_name_excluded_from_shipto(self):
        """customer_name must NOT capture the shipTo.name slot."""
        mapping = auto_map_columns(self.SHOPIFY_COLUMNS)
        for path, col in mapping.items():
            assert col != "customer_name", (
                f"customer_name should not be mapped; found at {path}"
            )

    def test_order_number_preferred_over_order_id(self):
        """order_number should map to reference, not order_id."""
        mapping = auto_map_columns(self.SHOPIFY_COLUMNS)
        assert mapping.get("reference") == "order_number"

    def test_total_weight_grams_not_mapped_to_weight(self):
        """total_weight_grams (grams) must not auto-map to packages[0].weight."""
        mapping = auto_map_columns(self.SHOPIFY_COLUMNS)
        weight_col = mapping.get("packages[0].weight")
        assert weight_col is None or "grams" not in weight_col.lower()

    def test_shopify_address_fields_mapped(self):
        """Shopify address columns should map correctly."""
        mapping = auto_map_columns(self.SHOPIFY_COLUMNS)
        assert mapping.get("shipTo.addressLine1") == "ship_to_address1"
        assert mapping.get("shipTo.addressLine2") == "ship_to_address2"
        assert mapping.get("shipTo.city") == "ship_to_city"
        assert mapping.get("shipTo.stateProvinceCode") == "ship_to_state"
        assert mapping.get("shipTo.postalCode") == "ship_to_postal_code"
        assert mapping.get("shipTo.countryCode") == "ship_to_country"
        assert mapping.get("shipTo.phone") == "ship_to_phone"

    def test_csv_generic_name_still_maps(self):
        """A plain 'Name' column should still map to shipTo.name for CSV data."""
        csv_cols = sorted(["Name", "Address", "City", "State", "Zip", "Weight"])
        mapping = auto_map_columns(csv_cols)
        assert mapping.get("shipTo.name") == "Name"

    def test_csv_recipient_name_maps(self):
        """A 'Recipient Name' column should map to shipTo.name."""
        cols = sorted(["Recipient Name", "Address", "City", "State", "Zip", "Weight"])
        mapping = auto_map_columns(cols)
        assert mapping.get("shipTo.name") == "Recipient Name"

    def test_weight_lbs_maps_correctly(self):
        """A 'Weight' column (no 'grams') should map to packages[0].weight."""
        cols = sorted(["Name", "Address", "City", "State", "Zip", "Weight"])
        mapping = auto_map_columns(cols)
        assert mapping.get("packages[0].weight") == "Weight"

    def test_mapping_is_permutation_invariant(self):
        """Column order should not change deterministic auto-mapping output."""
        cols = [
            "Recipient Name",
            "Customer Name",
            "Address Line 1",
            "City",
            "State",
            "Zip",
            "Country",
            "Weight",
            "Order Number",
        ]
        expected = auto_map_columns(cols)
        for variant in (
            list(reversed(cols)),
            cols[2:] + cols[:2],
            cols[1:] + cols[:1],
        ):
            assert auto_map_columns(variant) == expected

    def test_tie_break_prefers_more_specific_header(self):
        """When multiple headers match, deterministic ranking picks the best one."""
        cols = [
            "Name",
            "Recipient Name",
            "Address",
            "City",
            "State",
            "Zip",
            "Country",
            "Weight",
        ]
        mapping = auto_map_columns(cols)
        assert mapping.get("shipTo.name") == "Recipient Name"

    def test_header_normalization_is_deterministic(self):
        """Whitespace/casing variants map identically after normalization."""
        cols_a = [
            "  Recipient   Name  ",
            "Address Line 1",
            "City",
            "State",
            "Zip",
            "Country",
            "Weight",
        ]
        cols_b = [
            "recipient_name",
            "address-line-1",
            "CITY",
            "state",
            "ZIP",
            "country",
            "weight",
        ]
        mapping_a = auto_map_columns(cols_a)
        mapping_b = auto_map_columns(cols_b)
        assert mapping_a.get("shipTo.name") == "  Recipient   Name  "
        assert mapping_b.get("shipTo.name") == "recipient_name"
        assert set(mapping_a.keys()) == set(mapping_b.keys())


class TestNormalizeRowsEndToEnd:
    """End-to-end test of auto_map + apply_mapping with data from all sources.

    Mirrors what _normalize_rows_for_shipping does in tools/core.py without
    importing the SDK-dependent module.
    """

    def _normalize_row(self, row: dict) -> dict:
        """Replicate _normalize_rows_for_shipping logic for a single row."""
        source_columns = sorted({str(k) for k in row.keys()})
        mapping = auto_map_columns(source_columns)
        out = dict(row)
        mapped = apply_mapping(mapping, row)
        for key, value in mapped.items():
            if value is not None and value != "":
                out[key] = value
        # Fallback name fields
        if not out.get("ship_to_name"):
            for key in ("recipient_name", "customer_name", "name"):
                value = row.get(key)
                if value:
                    out["ship_to_name"] = value
                    break
        # Default country
        if not out.get("ship_to_country"):
            out["ship_to_country"] = "US"
        return out

    def test_shopify_row_preserves_ship_to_name(self):
        """Normalization must not overwrite ship_to_name with customer_name."""
        row = {
            "customer_name": "Alice Buyer",
            "ship_to_name": "Bob Recipient",
            "ship_to_address1": "123 Main St",
            "ship_to_city": "Springfield",
            "ship_to_state": "IL",
            "ship_to_postal_code": "62701",
            "ship_to_country": "US",
            "order_number": "1001",
            "total_weight_grams": "453.592",
        }

        out = self._normalize_row(row)

        # ship_to_name must remain the original recipient, not the buyer
        assert out["ship_to_name"] == "Bob Recipient"
        # customer_name must still be preserved in the row
        assert out["customer_name"] == "Alice Buyer"

    def test_normalization_does_not_inject_grams_as_weight(self):
        """total_weight_grams must not become the canonical weight value."""
        row = {
            "ship_to_name": "Bob Recipient",
            "ship_to_address1": "123 Main St",
            "ship_to_city": "Springfield",
            "ship_to_state": "IL",
            "ship_to_postal_code": "62701",
            "ship_to_country": "US",
            "total_weight_grams": "453.592",
        }

        out = self._normalize_row(row)

        # The "weight" key (canonical lbs) should not contain the grams value
        assert out.get("weight") != "453.592"

    def test_csv_row_normalizes_to_canonical_keys(self):
        """CSV row with generic headers must produce all canonical keys."""
        row = {
            "recipient_name": "Jane Doe",
            "address_line_1": "456 Oak Ave",
            "address_line_2": "",
            "city": "Portland",
            "state": "OR",
            "zip_code": "97201",
            "country": "US",
            "weight_lbs": "3.5",
            "phone": "503-555-1234",
            "order_number": "ORD-100",
        }

        out = self._normalize_row(row)

        assert out["ship_to_name"] == "Jane Doe"
        assert out["ship_to_address1"] == "456 Oak Ave"
        assert out["ship_to_city"] == "Portland"
        assert out["ship_to_state"] == "OR"
        assert out["ship_to_postal_code"] == "97201"
        assert out["ship_to_country"] == "US"
        assert out["weight"] == "3.5"

    def test_csv_row_builds_valid_shipment_request(self):
        """Normalized CSV data must produce a valid UPS shipment request."""
        from src.services.ups_payload_builder import (
            build_shipment_request,
            build_ups_rate_payload,
        )

        row = {
            "recipient_name": "Jane Doe",
            "address_line_1": "456 Oak Ave",
            "city": "Portland",
            "state": "OR",
            "zip_code": "97201",
            "country": "US",
            "weight_lbs": "3.5",
        }

        out = self._normalize_row(row)
        shipper = {
            "name": "Test Shipper",
            "addressLine1": "100 Test St",
            "city": "Test City",
            "stateProvinceCode": "CA",
            "postalCode": "90001",
            "countryCode": "US",
        }

        simplified = build_shipment_request(
            order_data=out, shipper=shipper, service_code="03",
        )
        assert simplified["shipTo"]["name"] == "Jane Doe"
        assert simplified["shipTo"]["city"] == "Portland"
        assert simplified["packages"][0]["weight"] == 3.5

        rate_payload = build_ups_rate_payload(
            simplified, account_number="TEST123",
        )
        pkg = rate_payload["RateRequest"]["Shipment"]["Package"][0]
        assert pkg["PackageWeight"]["Weight"] == "3.5"

    def test_csv_row_with_dimensions_builds_valid_payload(self):
        """CSV row with length/width/height must include Dimensions."""
        from src.services.ups_payload_builder import build_shipment_request

        row = {
            "recipient_name": "Bob Smith",
            "address_line_1": "789 Pine Rd",
            "city": "Denver",
            "state": "CO",
            "zip_code": "80201",
            "weight_lbs": 4.2,
            "length_in": 16,
            "width_in": 12,
            "height_in": 8,
            "declared_value": 275.0,
        }

        out = self._normalize_row(row)
        simplified = build_shipment_request(
            order_data=out, service_code="03",
        )
        pkg = simplified["packages"][0]
        assert pkg["weight"] == 4.2
        assert pkg.get("length") == 16.0
        assert pkg.get("declaredValue") == 275.0


class TestNewFieldMappings:
    """New field mapping entries for P0+P1 UPS fields."""

    def test_shipment_date_in_field_map(self):
        """shipmentDate is a recognized field path."""
        assert "shipmentDate" in _FIELD_TO_ORDER_DATA

    def test_ship_from_fields_in_field_map(self):
        """ShipFrom address fields are recognized."""
        assert "shipFrom.name" in _FIELD_TO_ORDER_DATA
        assert "shipFrom.addressLine1" in _FIELD_TO_ORDER_DATA
        assert "shipFrom.city" in _FIELD_TO_ORDER_DATA
        assert "shipFrom.postalCode" in _FIELD_TO_ORDER_DATA

    def test_service_options_in_field_map(self):
        """Service option fields are recognized."""
        for key in ["costCenter", "holdForPickup", "liftGatePickup",
                     "liftGateDelivery", "carbonNeutral", "notification.email"]:
            assert key in _FIELD_TO_ORDER_DATA, f"{key} missing from _FIELD_TO_ORDER_DATA"

    def test_international_forms_in_field_map(self):
        """International forms fields are recognized."""
        for key in ["termsOfShipment", "purchaseOrderNumber", "invoiceComments"]:
            assert key in _FIELD_TO_ORDER_DATA, f"{key} missing from _FIELD_TO_ORDER_DATA"

    def test_package_indicators_in_field_map(self):
        """Package-level indicators are recognized."""
        assert "largePackage" in _FIELD_TO_ORDER_DATA
        assert "additionalHandling" in _FIELD_TO_ORDER_DATA

    def test_auto_map_detects_ship_date_column(self):
        """A column named 'ship_date' auto-maps to shipmentDate."""
        mapping = auto_map_columns(["ship_date", "name", "address", "city", "state", "zip"])
        assert mapping.get("shipmentDate") == "ship_date"

    def test_auto_map_detects_cost_center_column(self):
        """A column named 'cost_center' auto-maps to costCenter."""
        mapping = auto_map_columns(["cost_center", "name", "address", "city", "state", "zip"])
        assert mapping.get("costCenter") == "cost_center"

    def test_auto_map_detects_ship_from_name(self):
        """A column named 'ship_from_name' auto-maps to shipFrom.name."""
        mapping = auto_map_columns(["ship_from_name", "name", "address", "city", "state", "zip"])
        assert mapping.get("shipFrom.name") == "ship_from_name"
