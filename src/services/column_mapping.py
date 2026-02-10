"""Column mapping for CSV/Excel data sources.

Replaces the Jinja2 template generation pipeline (~1100 lines).
The LLM produces a simple lookup table mapping shipment field paths
to source column names. Deterministic code uses this mapping to
extract values from each row.

Example:
    mapping = {"shipTo.name": "recipient_name", "packages[0].weight": "weight_lbs"}
    errors = validate_mapping(mapping)
    order_data = apply_mapping(mapping, row)
"""

from typing import Any


# Fields that must have a mapping entry for valid shipments
REQUIRED_FIELDS = [
    "shipTo.name",
    "shipTo.addressLine1",
    "shipTo.city",
    "shipTo.stateProvinceCode",
    "shipTo.postalCode",
    "shipTo.countryCode",
    "packages[0].weight",
]

# Mapping from simplified path → order_data key used by build_shipment_request
_FIELD_TO_ORDER_DATA: dict[str, str] = {
    "shipTo.name": "ship_to_name",
    "shipTo.attentionName": "ship_to_company",
    "shipTo.addressLine1": "ship_to_address1",
    "shipTo.addressLine2": "ship_to_address2",
    "shipTo.addressLine3": "ship_to_address3",
    "shipTo.city": "ship_to_city",
    "shipTo.stateProvinceCode": "ship_to_state",
    "shipTo.postalCode": "ship_to_postal_code",
    "shipTo.countryCode": "ship_to_country",
    "shipTo.phone": "ship_to_phone",
    "packages[0].weight": "weight",
    "packages[0].length": "length",
    "packages[0].width": "width",
    "packages[0].height": "height",
    "packages[0].packagingType": "packaging_type",
    "packages[0].declaredValue": "declared_value",
    "packages[0].description": "package_description",
    "serviceCode": "service_code",
    "description": "description",
    "reference": "order_number",
    "reference2": "reference2",
    "shipper.name": "shipper_name",
    "shipper.addressLine1": "shipper_address1",
    "shipper.city": "shipper_city",
    "shipper.stateProvinceCode": "shipper_state",
    "shipper.postalCode": "shipper_postal_code",
    "shipper.countryCode": "shipper_country",
    "shipper.phone": "shipper_phone",
}


def validate_mapping(mapping: dict[str, str]) -> list[str]:
    """Validate that all required fields have mapping entries.

    Args:
        mapping: Dict of {simplified_path: source_column_name}.

    Returns:
        List of error messages (empty if valid).
    """
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in mapping:
            errors.append(f"Missing required field mapping: '{field}'")
    return errors


def apply_mapping(mapping: dict[str, str], row: dict[str, Any]) -> dict[str, Any]:
    """Extract order data from a source row using the column mapping.

    Transforms source row data into the order_data format expected by
    build_shipment_request().

    Args:
        mapping: Dict of {simplified_path: source_column_name}.
        row: Source row data with arbitrary column names.

    Returns:
        Dict in order_data format for build_shipment_request().
    """
    order_data: dict[str, Any] = {}

    for simplified_path, source_column in mapping.items():
        order_data_key = _FIELD_TO_ORDER_DATA.get(simplified_path)
        if order_data_key is None:
            continue

        value = row.get(source_column)
        if value is not None:
            order_data[order_data_key] = value

    return order_data
