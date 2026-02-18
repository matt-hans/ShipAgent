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

import re
from typing import Any

from src.services.ups_service_codes import SERVICE_NAME_TO_CODE, translate_service_name

NORMALIZER_VERSION = "column_mapping_v2"


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
    "deliveryConfirmation": "delivery_confirmation",
    "signatureRequired": "signature_required",
    "adultSignatureRequired": "adult_signature_required",
    "shipTo.residential": "ship_to_residential",
    "saturdayDelivery": "saturday_delivery",
    "shipper.name": "shipper_name",
    "shipper.addressLine1": "shipper_address1",
    "shipper.city": "shipper_city",
    "shipper.stateProvinceCode": "shipper_state",
    "shipper.postalCode": "shipper_postal_code",
    "shipper.countryCode": "shipper_country",
    "shipper.phone": "shipper_phone",
    # International shipping fields
    "shipper.attentionName": "shipper_attention_name",
    "shipTo.attentionName": "ship_to_attention_name",
    "invoiceLineTotal.currencyCode": "invoice_currency_code",
    "invoiceLineTotal.monetaryValue": "invoice_monetary_value",
    "shipmentDescription": "shipment_description",
}


def validate_mapping(
    mapping: dict[str, str],
    destination_country: str | None = None,
) -> list[str]:
    """Validate that all required fields have mapping entries.

    Args:
        mapping: Dict of {simplified_path: source_column_name}.
        destination_country: If provided, adjusts required fields.
            For non-US destinations, stateProvinceCode is optional.

    Returns:
        List of error messages (empty if valid).
    """
    errors = []
    is_international = destination_country and destination_country.upper() not in ("US", "PR")
    for field in REQUIRED_FIELDS:
        if field == "shipTo.stateProvinceCode" and is_international:
            continue  # State/province optional for international
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
    # Explicit ship_to patterns must come first so customer_name can't steal the slot.
    (["recipient", "name"], [], "shipTo.name"),
    (["ship_to_name"], [], "shipTo.name"),
    (["ship", "name"], [], "shipTo.name"),
    # Company / attention name
    (["company"], [], "shipTo.attentionName"),
    (["organization"], [], "shipTo.attentionName"),
    (["attention"], [], "shipTo.attentionName"),
    # Generic name — exclude "customer" so customer_name doesn't steal shipTo.name.
    (["name"], ["company", "organization", "file", "sheet", "customer"], "shipTo.name"),
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
    # Package dimensions — exclude "grams" to avoid mapping total_weight_grams
    # directly (the value is in grams, not lbs; conversion happens downstream).
    (["weight"], ["grams"], "packages[0].weight"),
    (["length"], [], "packages[0].length"),
    (["width"], [], "packages[0].width"),
    (["height"], [], "packages[0].height"),
    (["packaging"], [], "packages[0].packagingType"),
    # Value
    (["declared", "value"], [], "packages[0].declaredValue"),
    (["insured", "value"], [], "packages[0].declaredValue"),
    # Description
    (["description"], ["package"], "description"),
    # Reference / order — prefer order_number over order_id for human-readable refs.
    # Columns are iterated alphabetically, so order_id comes before order_number.
    # Exclude "_id" from the first rule to prevent order_id from claiming the slot.
    (["order_number"], [], "reference"),
    (["order", "number"], [], "reference"),
    (["order"], ["_id", "status"], "reference"),
    (["reference"], ["2"], "reference"),
    # Service
    (["service"], [], "serviceCode"),
    # Delivery confirmation / signature
    (["signature", "required"], [], "signatureRequired"),
    (["adult", "signature"], [], "adultSignatureRequired"),
    (["delivery", "confirmation"], [], "deliveryConfirmation"),
    # Residential indicator
    (["residential"], [], "shipTo.residential"),
    # Saturday delivery
    (["saturday"], [], "saturdayDelivery"),
]


def _canonicalize_header(value: str) -> str:
    """Normalize a header for deterministic matching and ordering."""
    lowered = value.strip().lower()
    lowered = re.sub(r"\s+", "_", lowered)
    lowered = re.sub(r"[^a-z0-9_]+", "_", lowered)
    lowered = re.sub(r"_+", "_", lowered)
    return lowered.strip("_")


def _token_set(canonical_header: str) -> set[str]:
    """Split canonical header into deterministic token set."""
    return {t for t in canonical_header.split("_") if t}


def _match_quality(
    token: str,
    canonical_header: str,
    tokens: set[str],
) -> int:
    """Return token match quality (2 exact, 1 substring, 0 no match)."""
    normalized = _canonicalize_header(token)
    if not normalized:
        return 0
    if normalized == canonical_header or normalized in tokens:
        return 2
    if normalized in canonical_header:
        return 1
    return 0


def auto_map_columns(source_columns: list[str]) -> dict[str, str]:
    """Auto-map source column names to UPS field paths using naming heuristics.

    Examines each source column name against a table of pattern rules.
    Returns a mapping of {simplified_path: source_column_name}.

    Args:
        source_columns: List of column names from the data source.

    Returns:
        Dict mapping simplified UPS field paths to source column names.
    """
    mapping, _ = auto_map_columns_with_trace(source_columns)
    return mapping


def auto_map_columns_with_trace(
    source_columns: list[str],
) -> tuple[dict[str, str], dict[str, Any]]:
    """Auto-map source column names and return trace metadata.

    Trace includes the selected source column and candidate ranking basis
    for each mapped target path.
    """
    # Deterministic candidate pool per target path, independent of source order.
    by_path: dict[str, list[tuple[int, int, int, int, str, str]]] = {}
    canonical_columns = sorted(
        (
            (
                _canonicalize_header(col_name),
                col_name,
            )
            for col_name in source_columns
            if isinstance(col_name, str) and col_name.strip()
        ),
        key=lambda item: (item[0], item[1].lower()),
    )

    for canonical_header, original_header in canonical_columns:
        tokens = _token_set(canonical_header)
        for rule_index, (must_have, must_not, path) in enumerate(_AUTO_MAP_RULES):
            required_scores = [
                _match_quality(token, canonical_header, tokens) for token in must_have
            ]
            if any(score == 0 for score in required_scores):
                continue
            blocked = any(
                _match_quality(token, canonical_header, tokens) > 0
                for token in must_not
            )
            if blocked:
                continue

            exact_matches = sum(1 for score in required_scores if score == 2)
            substring_matches = sum(1 for score in required_scores if score == 1)
            by_path.setdefault(path, []).append(
                (
                    exact_matches,
                    substring_matches,
                    -rule_index,              # earlier rules win
                    -len(canonical_header),   # shorter headers win
                    canonical_header,         # stable lexical tie-break
                    original_header,
                )
            )

    mapping: dict[str, str] = {}
    trace: dict[str, Any] = {}
    seen_paths: set[str] = set()
    for _, _, path in _AUTO_MAP_RULES:
        if path in seen_paths:
            continue
        seen_paths.add(path)
        candidates = by_path.get(path, [])
        if not candidates:
            continue
        # Rank: exact > substring > rule order > shorter header > lexical.
        ranked = sorted(
            candidates,
            key=lambda c: (-c[0], -c[1], -c[2], -c[3], c[4], c[5].lower()),
        )
        best = ranked[0]
        mapping[path] = best[5]
        trace[path] = {
            "selected_source_column": best[5],
            "selected_score": {
                "exact_matches": best[0],
                "substring_matches": best[1],
                "rule_priority": -best[2],
                "header_length_penalty": -best[3],
            },
            "candidates": [
                {
                    "source_column": candidate[5],
                    "exact_matches": candidate[0],
                    "substring_matches": candidate[1],
                    "rule_priority": -candidate[2],
                    "header_length_penalty": -candidate[3],
                }
                for candidate in ranked[:10]
            ],
        }

    return mapping, trace


# Re-exported from src.services.ups_service_codes for backward compatibility:
# SERVICE_NAME_TO_CODE, translate_service_name
