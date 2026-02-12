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


# === Auto column mapping ===

# Heuristic table: maps lowercase source column patterns to simplified paths.
# Patterns are checked in order; first match wins.
_AUTO_MAP_RULES: list[tuple[list[str], list[str], str]] = [
    # (must_contain_all, must_not_contain, simplified_path)
    # Address fields (check multi-word patterns before single-word)
    (["address", "2"], [], "shipTo.addressLine2"),
    (["address", "3"], [], "shipTo.addressLine3"),
    (["address", "1"], [], "shipTo.addressLine1"),
    (["address_line_2"], [], "shipTo.addressLine2"),
    (["address_line_3"], [], "shipTo.addressLine3"),
    (["address_line_1"], [], "shipTo.addressLine1"),
    (["address"], ["2", "3"], "shipTo.addressLine1"),
    # Recipient name (before generic "name")
    (["recipient", "name"], [], "shipTo.name"),
    (["ship_to_name"], [], "shipTo.name"),
    (["ship", "name"], [], "shipTo.name"),
    # Company / attention name
    (["company"], [], "shipTo.attentionName"),
    (["organization"], [], "shipTo.attentionName"),
    (["attention"], [], "shipTo.attentionName"),
    # Generic name (if not matched above)
    (["name"], ["company", "organization", "file", "sheet"], "shipTo.name"),
    # Contact info
    (["phone"], [], "shipTo.phone"),
    (["tel"], ["hotel"], "shipTo.phone"),
    # Location
    (["city"], [], "shipTo.city"),
    (["state"], ["status"], "shipTo.stateProvinceCode"),
    (["province"], [], "shipTo.stateProvinceCode"),
    (["zip"], [], "shipTo.postalCode"),
    (["postal"], [], "shipTo.postalCode"),
    (["country"], [], "shipTo.countryCode"),
    # Package dimensions
    (["weight"], [], "packages[0].weight"),
    (["length"], [], "packages[0].length"),
    (["width"], [], "packages[0].width"),
    (["height"], [], "packages[0].height"),
    (["packaging"], [], "packages[0].packagingType"),
    # Value
    (["declared", "value"], [], "packages[0].declaredValue"),
    (["insured", "value"], [], "packages[0].declaredValue"),
    # Description
    (["description"], ["package"], "description"),
    # Reference / order
    (["order_number"], [], "reference"),
    (["order_id"], [], "reference"),
    (["order", "number"], [], "reference"),
    (["reference"], [], "reference"),
    # Service
    (["service"], [], "serviceCode"),
]


def auto_map_columns(source_columns: list[str]) -> dict[str, str]:
    """Auto-map source column names to UPS field paths using naming heuristics.

    Examines each source column name against a table of pattern rules.
    Returns a mapping of {simplified_path: source_column_name}.

    Args:
        source_columns: List of column names from the data source.

    Returns:
        Dict mapping simplified UPS field paths to source column names.
    """
    mapping: dict[str, str] = {}
    used_paths: set[str] = set()

    for col_name in source_columns:
        col_lower = col_name.lower()

        for must_have, must_not, path in _AUTO_MAP_RULES:
            if path in used_paths:
                continue

            # Check all required tokens present
            if all(token in col_lower for token in must_have):
                # Check no excluded tokens present
                if not any(token in col_lower for token in must_not):
                    mapping[path] = col_name
                    used_paths.add(path)
                    break

    return mapping


# === Service name translation ===

SERVICE_NAME_TO_CODE: dict[str, str] = {
    "ground": "03",
    "ups ground": "03",
    "2nd day air": "02",
    "ups 2nd day air": "02",
    "next day air": "01",
    "ups next day air": "01",
    "3 day select": "12",
    "ups 3 day select": "12",
    "next day air saver": "13",
    "ups next day air saver": "13",
    "next day air early": "14",
    "ups next day air early": "14",
    "2nd day air am": "59",
    "ups 2nd day air am": "59",
    "standard": "11",
    "ups standard": "11",
    "express": "01",
    "overnight": "01",
}


def translate_service_name(name: str) -> str:
    """Translate a human-readable service name to a UPS service code.

    Case-insensitive lookup. Returns the original value if already a
    numeric code or if no match is found.

    Args:
        name: Service name string (e.g., "Ground", "Next Day Air").

    Returns:
        UPS service code string (e.g., "03", "01").
    """
    if not name:
        return "03"  # Default to Ground

    stripped = name.strip()

    # Already a code (numeric string)?
    if stripped.isdigit():
        return stripped

    # Lookup by lowercase
    code = SERVICE_NAME_TO_CODE.get(stripped.lower())
    if code:
        return code

    # Default to Ground if unrecognized
    return "03"
