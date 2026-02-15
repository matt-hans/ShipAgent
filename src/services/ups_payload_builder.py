"""UPS payload builder for shipment requests.

Transforms order data from JobRow.order_data (JSON) into UPS MCP
shipping_create input format. Also handles shipper information
from Shopify shop details.

Example:
    from src.services.ups_payload_builder import build_shipment_request

    order_data = json.loads(job_row.order_data)
    request = build_shipment_request(
        order_data=order_data,
        shipper=shipper_info,
        service_code="03"
    )
    result = await ups_client.create_shipment(request)
"""

import re
from typing import Any

from src.services.ups_service_codes import resolve_service_code


def normalize_phone(phone: str | None) -> str:
    """Normalize phone number to digits only.

    UPS requires 7-15 digit phone numbers. Handles both domestic
    and international formats (strips formatting, preserves country code).

    Args:
        phone: Raw phone number string (may contain dashes, spaces, parens, +)

    Returns:
        Digits-only phone number, or empty string if invalid/missing.
    """
    if not phone:
        return ""

    # Strip all non-digit characters
    digits = re.sub(r"\D", "", phone)

    # Accept 7-15 digits (international range)
    if len(digits) < 7:
        return ""

    # Truncate to 15 digits (UPS max)
    return digits[:15]


def normalize_zip(postal_code: str | None) -> str:
    """Normalize postal code.

    For US codes: handles 5-digit and ZIP+4 formats.
    For international codes: passes through with whitespace trimmed.

    Args:
        postal_code: Raw postal code string.

    Returns:
        Normalized postal code.
    """
    if not postal_code:
        return ""

    postal_code = postal_code.strip()

    # Extract digits to check if this is a US ZIP
    digits = re.sub(r"\D", "", postal_code)

    # If all digits and 5+ chars, treat as US ZIP
    if postal_code.isdigit() or (len(digits) >= 5 and digits == postal_code.replace("-", "")):
        if len(digits) >= 9:
            return f"{digits[:5]}-{digits[5:9]}"
        elif len(digits) >= 5:
            return digits[:5]

    # International postal codes: return as-is (trimmed)
    return postal_code


def truncate_address(address: str | None, max_length: int = 35) -> str:
    """Truncate address without cutting words.

    UPS limits address lines to 35 characters. This function
    truncates at word boundaries for cleaner results.

    Args:
        address: Raw address string
        max_length: Maximum length (default 35 for UPS)

    Returns:
        Truncated address string
    """
    if not address:
        return ""

    address = address.strip()

    if len(address) <= max_length:
        return address

    # Truncate at word boundary
    truncated = address[:max_length].rsplit(" ", 1)[0]

    # Fallback to hard truncate if no word boundary
    if not truncated:
        truncated = address[:max_length]

    return truncated


def build_shipper_from_shop(shop_info: dict[str, Any]) -> dict[str, str]:
    """Build UPS shipper from Shopify shop.json response.

    Transforms Shopify shop details into UPS-compatible shipper format.
    Falls back to environment variables for any missing required fields
    (addressLine1, city, stateProvinceCode, postalCode) since Shopify
    stores may not always have complete address information.

    Args:
        shop_info: Shopify shop data containing:
            - name: Store name
            - phone: Store phone
            - address1: Street address
            - city: City
            - province_code: State/province code (e.g., "CA")
            - zip: Postal code
            - country_code: Country code (e.g., "US")

    Returns:
        Dict matching UPS shipper schema with all required fields populated
    """
    import os

    # Get env var fallbacks for required address fields
    env_fallbacks = {
        "addressLine1": os.environ.get("SHIPPER_ADDRESS1", "123 Main St"),
        "city": os.environ.get("SHIPPER_CITY", "Los Angeles"),
        "stateProvinceCode": os.environ.get("SHIPPER_STATE", "CA"),
        "postalCode": normalize_zip(os.environ.get("SHIPPER_ZIP", "90001")),
    }

    return {
        "name": truncate_address(shop_info.get("name", ""), 35) or "ShipAgent",
        "phone": normalize_phone(shop_info.get("phone")),
        "addressLine1": truncate_address(shop_info.get("address1", ""))
        or env_fallbacks["addressLine1"],
        "addressLine2": truncate_address(shop_info.get("address2")),
        "city": shop_info.get("city") or env_fallbacks["city"],
        "stateProvinceCode": shop_info.get("province_code")
        or env_fallbacks["stateProvinceCode"],
        "postalCode": normalize_zip(shop_info.get("zip"))
        or env_fallbacks["postalCode"],
        "countryCode": shop_info.get("country_code") or "US",
    }


def build_shipper_from_env() -> dict[str, str]:
    """Build shipper from environment variables.

    Fallback when shop info is not available. Uses SHIPPER_* env vars.

    Returns:
        Dict matching UPS shipper schema
    """
    import os

    return {
        "name": os.environ.get("SHIPPER_NAME", "ShipAgent Default"),
        "phone": normalize_phone(os.environ.get("SHIPPER_PHONE")),
        "addressLine1": os.environ.get("SHIPPER_ADDRESS1", "123 Main St"),
        "city": os.environ.get("SHIPPER_CITY", "Los Angeles"),
        "stateProvinceCode": os.environ.get("SHIPPER_STATE", "CA"),
        "postalCode": normalize_zip(os.environ.get("SHIPPER_ZIP", "90001")),
        "countryCode": os.environ.get("SHIPPER_COUNTRY", "US"),
    }


def build_ship_to(order_data: dict[str, Any]) -> dict[str, str]:
    """Build UPS shipTo from order data.

    Transforms order shipping address into UPS-compatible format.

    Args:
        order_data: Order data containing ship_to_* fields

    Returns:
        Dict matching UPS shipTo schema
    """
    # Build recipient name
    name = order_data.get("ship_to_name", "")
    if not name:
        # Try combining first/last if available
        first = order_data.get("ship_to_first_name", "")
        last = order_data.get("ship_to_last_name", "")
        name = f"{first} {last}".strip()

    return {
        "name": truncate_address(name, 35) or "Recipient",
        "attentionName": truncate_address(order_data.get("ship_to_company"), 35),
        "phone": normalize_phone(order_data.get("ship_to_phone")),
        "addressLine1": truncate_address(order_data.get("ship_to_address1", "")),
        "addressLine2": truncate_address(order_data.get("ship_to_address2")),
        "city": order_data.get("ship_to_city", ""),
        "stateProvinceCode": order_data.get("ship_to_state", ""),
        "postalCode": normalize_zip(order_data.get("ship_to_postal_code")),
        "countryCode": order_data.get("ship_to_country", ""),
    }


def resolve_packaging_code(raw_value: str | None) -> str:
    """Resolve a packaging type value to a UPS numeric code.

    Accepts either a numeric code directly (e.g. "02") or a
    human-readable name (e.g. "Customer Supplied", "PAK").

    Args:
        raw_value: Packaging type string from order data.

    Returns:
        UPS packaging type code string. Defaults to "02" (Customer Supplied Package).
    """
    if not raw_value:
        return "02"

    # Coerce non-string values (e.g. int 2 from LLM/tool args)
    stripped = str(raw_value).strip()
    if not stripped:
        return "02"

    # Known alphanumeric UPS codes — pass through as-is
    _ALPHANUMERIC_CODES = {"2a", "2b", "2c"}
    if stripped.lower() in _ALPHANUMERIC_CODES:
        return stripped.lower()

    # Already a valid numeric code — return as-is
    if stripped.isdigit() and len(stripped) <= 3:
        return stripped.zfill(2)

    # Map human-readable names to UPS codes (case-insensitive)
    packaging_name_map: dict[str, str] = {
        "ups letter": "01",
        "letter": "01",
        "customer supplied package": "02",
        "customer supplied": "02",
        "custom": "02",
        "tube": "03",
        "ups tube": "03",
        "pak": "04",
        "ups pak": "04",
        "ups express box": "21",
        "express box": "21",
        "25kg box": "24",
        "ups 25kg box": "24",
        "10kg box": "25",
        "ups 10kg box": "25",
        "pallet": "30",
        "small express box": "2a",
        "ups small express box": "2a",
        "medium express box": "2b",
        "ups medium express box": "2b",
        "large express box": "2c",
        "ups large express box": "2c",
        "flats": "56",
        "parcels": "57",
        "bpm": "58",
        "first class": "59",
        "priority": "60",
        "machineables": "61",
        "irregulars": "62",
        "parcel post": "63",
        "bpm parcel": "64",
        "media mail": "65",
        "bpm flat": "66",
        "standard flat": "67",
    }

    return packaging_name_map.get(stripped.lower(), "02")


def build_packages(order_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Build UPS packages from order data.

    Creates package list for shipment. Supports single or multi-package.

    Args:
        order_data: Order data containing package info

    Returns:
        List of package dicts matching UPS package schema
    """
    # Check for explicit packages array
    packages = order_data.get("packages", [])
    if packages:
        result = []
        for pkg in packages:
            p: dict[str, Any] = {
                "weight": float(pkg.get("weight", 1.0)),
                "length": pkg.get("length"),
                "width": pkg.get("width"),
                "height": pkg.get("height"),
                "packagingType": resolve_packaging_code(
                    pkg.get("packaging_type")
                ),
                "description": pkg.get("description"),
            }
            dv = pkg.get("declared_value")
            if dv is not None:
                p["declaredValue"] = float(dv)
            result.append(p)
        return result

    # Single package from order-level fields
    # Check weight keys in priority order, including Shopify's grams field
    weight = order_data.get("weight") or order_data.get("total_weight")
    if not weight:
        weight_grams = order_data.get("total_weight_grams")
        if weight_grams:
            weight = float(weight_grams) / 453.592  # Convert grams to lbs
        else:
            weight = 1.0

    package: dict[str, Any] = {
        "weight": float(weight),
        "packagingType": resolve_packaging_code(
            order_data.get("packaging_type")
        ),
    }

    # Add dimensions if present
    length = order_data.get("length")
    width = order_data.get("width")
    height = order_data.get("height")

    if length and width and height:
        package["length"] = float(length)
        package["width"] = float(width)
        package["height"] = float(height)

    # Add declared value if present
    declared_value = order_data.get("declared_value")
    if declared_value is not None:
        package["declaredValue"] = float(declared_value)

    return [package]


def get_service_code(order_data: dict[str, Any], default: str = "03") -> str:
    """Get UPS service code from order data.

    Checks service_code first, then falls back to service name.
    Both values are resolved through the name-to-code map.

    Args:
        order_data: Order data containing service info
        default: Default service code ("03" = Ground)

    Returns:
        UPS service code string
    """
    # Check for explicit service code (may be a name or a code)
    service_code = order_data.get("service_code")
    if service_code:
        return resolve_service_code(str(service_code), default)

    # Fall back to service name field
    service_name = order_data.get("service")
    if service_name:
        return resolve_service_code(str(service_name), default)

    return default


def build_international_forms(
    commodities: list[dict],
    currency_code: str = "USD",
    form_type: str = "01",
    reason_for_export: str = "SALE",
    invoice_date: str | None = None,
) -> dict:
    """Build UPS InternationalForms section for customs documentation.

    Args:
        commodities: List of commodity dicts with description, commodity_code,
            origin_country, quantity, unit_value, and optional unit_of_measure.
        currency_code: ISO 4217 currency code (default USD).
        form_type: InternationalForms type (01 = commercial invoice).
        reason_for_export: Export reason code (SALE, GIFT, SAMPLE, etc.).
        invoice_date: Invoice date in YYYYMMDD format. Defaults to today.

    Returns:
        Dict ready to embed as InternationalForms in UPS payload.
    """
    from datetime import date as date_type

    if invoice_date is None:
        invoice_date = date_type.today().strftime("%Y%m%d")

    products = []
    for comm in commodities:
        uom_code = str(comm.get("unit_of_measure", "PCS")).upper()
        products.append({
            "Description": str(comm["description"])[:35],
            "CommodityCode": str(comm["commodity_code"]),
            "OriginCountryCode": str(comm["origin_country"]).upper(),
            "Unit": {
                "Number": str(int(comm["quantity"])),
                "UnitOfMeasurement": {
                    "Code": uom_code,
                    "Description": uom_code,
                },
                "Value": str(comm["unit_value"]),
            },
        })

    return {
        "FormType": form_type,
        "InvoiceDate": invoice_date,
        "ReasonForExport": reason_for_export,
        "CurrencyCode": currency_code,
        "Product": products,
    }


def build_shipment_request(
    order_data: dict[str, Any],
    shipper: dict[str, str] | None = None,
    service_code: str | None = None,
) -> dict[str, Any]:
    """Build complete UPS shipping_create request.

    Transforms order data into the full payload required by UPS MCP.

    Args:
        order_data: Order data from JobRow.order_data JSON
        shipper: Optional shipper info (from shop or env vars)
        service_code: Optional service code override

    Returns:
        Complete dict for shipping_create tool
    """
    # Use provided shipper or fall back to env vars
    if shipper is None:
        shipper = build_shipper_from_env()

    # Remove None values from shipper
    shipper = {k: v for k, v in shipper.items() if v}

    # Build shipTo
    ship_to = build_ship_to(order_data)
    # Remove None/empty values
    ship_to = {k: v for k, v in ship_to.items() if v}

    # Build packages
    packages = build_packages(order_data)

    # Get service code
    if service_code is None:
        service_code = get_service_code(order_data)

    # Build reference from order ID/number
    reference = order_data.get("order_number") or order_data.get("order_id") or ""

    # Build description
    description = order_data.get("description")
    if not description and reference:
        description = f"Order #{reference}"

    # Build simplified payload
    result: dict[str, Any] = {
        "shipper": shipper,
        "shipTo": ship_to,
        "packages": packages,
        "serviceCode": service_code,
        "description": description or "Shipment",
        "reference": str(reference) if reference else None,
        "reference2": order_data.get("reference2"),
    }

    # Delivery confirmation: 1=Signature Required, 2=Adult Signature Required
    dc = _resolve_delivery_confirmation(order_data)
    if dc:
        result["deliveryConfirmation"] = dc

    # Residential indicator
    if _is_residential(order_data):
        result["residential"] = True

    # Saturday delivery
    if _is_truthy(order_data.get("saturday_delivery")):
        result["saturdayDelivery"] = True

    # --- International enrichment ---
    from src.services.international_rules import get_requirements

    origin_country = shipper.get("countryCode", "US")
    dest_country = order_data.get("ship_to_country", "") or origin_country
    requirements = get_requirements(origin_country, dest_country, service_code)

    if requirements.not_shippable_reason:
        raise ValueError(f"Cannot ship: {requirements.not_shippable_reason}")

    # Enrich simplified dict with international data for downstream consumption
    result["destinationCountry"] = dest_country

    # Contact fields — inject into existing shipper/shipTo sub-dicts
    if requirements.requires_shipper_contact:
        if order_data.get("shipper_attention_name"):
            result["shipper"]["attentionName"] = order_data["shipper_attention_name"]
        if order_data.get("shipper_phone"):
            result["shipper"]["phone"] = normalize_phone(order_data["shipper_phone"])

    if requirements.requires_recipient_contact:
        if order_data.get("ship_to_attention_name"):
            result["shipTo"]["attentionName"] = order_data["ship_to_attention_name"]
        if order_data.get("ship_to_phone"):
            result["shipTo"]["phone"] = normalize_phone(order_data["ship_to_phone"])

    # InvoiceLineTotal — add as top-level key in simplified
    if requirements.requires_invoice_line_total:
        result["invoiceLineTotal"] = {
            "currencyCode": order_data.get("invoice_currency_code", "USD"),
            "monetaryValue": order_data.get("invoice_monetary_value", "0"),
        }

    # Description — add as top-level key in simplified
    if requirements.requires_description:
        desc = order_data.get("shipment_description", "")
        if desc:
            result["description"] = desc[:35]

    # InternationalForms — build from commodities and add to simplified
    if requirements.requires_international_forms:
        commodities = order_data.get("commodities", [])
        if commodities:
            result["internationalForms"] = build_international_forms(
                commodities=commodities,
                currency_code=requirements.currency_code,
                form_type=requirements.form_type,
            )

    return result


def _resolve_delivery_confirmation(order_data: dict[str, Any]) -> str | None:
    """Resolve delivery confirmation type from order data.

    Checks both 'delivery_confirmation' and 'signature_required' fields.

    Args:
        order_data: Order data dict.

    Returns:
        DCISType string ("1" or "2") or None if not requested.
    """
    # Explicit delivery_confirmation code
    dc = order_data.get("delivery_confirmation")
    if dc is not None:
        val = str(dc).strip().lower()
        if val in ("1", "2"):
            return val
        dc_map = {
            "signature": "1",
            "signature required": "1",
            "sig": "1",
            "adult": "2",
            "adult signature": "2",
            "adult signature required": "2",
        }
        return dc_map.get(val)

    # Boolean signature_required field
    if _is_truthy(order_data.get("signature_required")):
        return "1"

    # Boolean adult_signature_required field
    if _is_truthy(order_data.get("adult_signature_required")):
        return "2"

    return None


def _is_residential(order_data: dict[str, Any]) -> bool:
    """Check if destination is residential from order data.

    Args:
        order_data: Order data dict.

    Returns:
        True if residential indicator is set.
    """
    return _is_truthy(order_data.get("ship_to_residential")) or _is_truthy(
        order_data.get("residential")
    )


def _is_truthy(value: Any) -> bool:
    """Check if a value is truthy, handling string representations.

    Args:
        value: Value to check.

    Returns:
        True if value represents a truthy/affirmative value.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    return s in ("true", "yes", "1", "y", "x")


def build_ups_api_payload(
    simplified: dict[str, Any],
    account_number: str,
) -> dict[str, Any]:
    """Transform simplified format to full UPS ShipmentRequest.

    Args:
        simplified: Simplified payload from build_shipment_request().
            Keys: shipper, shipTo, packages, serviceCode, description,
            reference, reference2, saturdayDelivery, signatureRequired.
        account_number: UPS account number for billing.

    Returns:
        Full UPS API ShipmentRequest wrapper.

    Raises:
        ValueError: If account_number is empty.
    """
    if not account_number:
        raise ValueError("account_number is required for UPS shipment creation")

    shipper = simplified.get("shipper", {})
    ship_to = simplified.get("shipTo", {})
    packages = simplified.get("packages", [])
    service_code = simplified.get("serviceCode", "03")

    # Build Shipper
    ups_shipper: dict[str, Any] = {
        "Name": shipper.get("name", ""),
        "ShipperNumber": account_number,
        "Address": {
            "AddressLine": _build_address_lines(shipper),
            "City": shipper.get("city", ""),
            "StateProvinceCode": shipper.get("stateProvinceCode", ""),
            "PostalCode": shipper.get("postalCode", ""),
            "CountryCode": shipper.get("countryCode", "US"),
        },
    }
    if shipper.get("phone"):
        ups_shipper["Phone"] = {"Number": shipper["phone"]}

    # Build ShipTo
    ups_ship_to: dict[str, Any] = {
        "Name": ship_to.get("name", ""),
        "Address": {
            "AddressLine": _build_address_lines(ship_to),
            "City": ship_to.get("city", ""),
            "StateProvinceCode": ship_to.get("stateProvinceCode", ""),
            "PostalCode": ship_to.get("postalCode", ""),
            "CountryCode": ship_to.get("countryCode", "US"),
        },
    }
    if ship_to.get("attentionName"):
        ups_ship_to["AttentionName"] = ship_to["attentionName"]
    if ship_to.get("phone"):
        ups_ship_to["Phone"] = {"Number": ship_to["phone"]}

    # Build Packages
    ups_packages = []
    for pkg in packages:
        ups_pkg: dict[str, Any] = {
            "Packaging": {
                "Code": pkg.get("packagingType", "02"),
            },
            "PackageWeight": {
                "UnitOfMeasurement": {"Code": "LBS"},
                "Weight": str(float(pkg.get("weight", 1.0))),
            },
        }
        # Dimensions (all three required if any present)
        if all(pkg.get(d) for d in ("length", "width", "height")):
            ups_pkg["Dimensions"] = {
                "UnitOfMeasurement": {"Code": "IN"},
                "Length": str(pkg["length"]),
                "Width": str(pkg["width"]),
                "Height": str(pkg["height"]),
            }
        if pkg.get("description"):
            ups_pkg["Description"] = pkg["description"]
        # Declared value (insurance)
        if pkg.get("declaredValue"):
            ups_pkg.setdefault("PackageServiceOptions", {})[
                "DeclaredValue"
            ] = {
                "Type": {"Code": "01"},  # EVS (Enhanced Value Shipment)
                "CurrencyCode": "USD",
                "MonetaryValue": str(pkg["declaredValue"]),
            }
        ups_packages.append(ups_pkg)

    # Build Shipment
    shipment: dict[str, Any] = {
        "Shipper": ups_shipper,
        "ShipTo": ups_ship_to,
        "ShipFrom": ups_shipper,  # ShipFrom = Shipper for standard shipments
        "Service": {"Code": service_code},
        "Package": ups_packages,
        "PaymentInformation": {
            "ShipmentCharge": [
                {
                    "Type": "01",
                    "BillShipper": {"AccountNumber": account_number},
                }
            ]
        },
        "ShipmentRatingOptions": {
            "NegotiatedRatesIndicator": "",
        },
    }

    # Optional fields
    if simplified.get("description"):
        shipment["Description"] = simplified["description"]

    # Reference numbers at package level (shipment-level rejected by Ground).
    # Add to first package only; UPS allows up to 2 per package.
    reference = simplified.get("reference")
    if reference and ups_packages:
        refs = []
        refs.append({
            "Value": str(reference)[:35],  # UPS max 35 chars
        })
        ref2 = simplified.get("reference2")
        if ref2:
            refs.append({
                "Value": str(ref2)[:35],
            })
        ups_packages[0]["ReferenceNumber"] = refs

    # Residential indicator on ShipTo address
    if simplified.get("residential"):
        ups_ship_to["Address"]["ResidentialAddressIndicator"] = ""

    # Shipment-level options
    options: dict[str, Any] = shipment.get("ShipmentServiceOptions", {})
    if simplified.get("saturdayDelivery"):
        options["SaturdayDeliveryIndicator"] = ""
    # Delivery confirmation (signature required)
    dc = simplified.get("deliveryConfirmation")
    if dc:
        options["DeliveryConfirmation"] = {"DCISType": str(dc)}

    # --- International enrichment (reads from simplified, set by build_shipment_request) ---

    # InvoiceLineTotal
    invoice_lt = simplified.get("invoiceLineTotal")
    if invoice_lt:
        shipment["InvoiceLineTotal"] = {
            "CurrencyCode": invoice_lt["currencyCode"],
            "MonetaryValue": invoice_lt["monetaryValue"],
        }

    # Shipper contact (attentionName already handled above; add phone if enriched)
    shipper_data = simplified.get("shipper", {})
    if shipper_data.get("attentionName"):
        ups_shipper["AttentionName"] = shipper_data["attentionName"]
    if shipper_data.get("phone"):
        ups_shipper["Phone"] = {"Number": shipper_data["phone"]}

    # ShipTo contact (attentionName/phone already handled above in base build)

    # InternationalForms
    intl_forms = simplified.get("internationalForms")
    if intl_forms:
        options["InternationalForms"] = intl_forms

    if options:
        shipment["ShipmentServiceOptions"] = options

    return {
        "ShipmentRequest": {
            "Request": {"RequestOption": "nonvalidate"},
            "Shipment": shipment,
            "LabelSpecification": {
                "LabelImageFormat": {"Code": "PDF"},
                "LabelStockSize": {"Height": "6", "Width": "4"},
            },
        }
    }


def build_ups_rate_payload(
    simplified: dict[str, Any],
    account_number: str,
) -> dict[str, Any]:
    """Transform simplified format to full UPS RateRequest.

    Args:
        simplified: Simplified payload from build_shipment_request().
        account_number: UPS account number.

    Returns:
        Full UPS API RateRequest wrapper.

    Raises:
        ValueError: If account_number is empty.
    """
    if not account_number:
        raise ValueError("account_number is required for UPS rate quotes")

    shipper = simplified.get("shipper", {})
    ship_to = simplified.get("shipTo", {})
    packages = simplified.get("packages", [])
    service_code = simplified.get("serviceCode", "03")

    ups_shipper: dict[str, Any] = {
        "Name": shipper.get("name", ""),
        "ShipperNumber": account_number,
        "Address": {
            "AddressLine": _build_address_lines(shipper),
            "City": shipper.get("city", ""),
            "StateProvinceCode": shipper.get("stateProvinceCode", ""),
            "PostalCode": shipper.get("postalCode", ""),
            "CountryCode": shipper.get("countryCode", "US"),
        },
    }

    ups_ship_to_addr: dict[str, Any] = {
        "AddressLine": _build_address_lines(ship_to),
        "City": ship_to.get("city", ""),
        "StateProvinceCode": ship_to.get("stateProvinceCode", ""),
        "PostalCode": ship_to.get("postalCode", ""),
        "CountryCode": ship_to.get("countryCode", "US"),
    }
    # Residential indicator affects rate (residential surcharge)
    if simplified.get("residential"):
        ups_ship_to_addr["ResidentialAddressIndicator"] = ""

    ups_ship_to: dict[str, Any] = {
        "Name": ship_to.get("name", ""),
        "Address": ups_ship_to_addr,
    }

    ups_packages = []
    for pkg in packages:
        ups_pkg: dict[str, Any] = {
            "PackagingType": {"Code": pkg.get("packagingType", "02")},
            "PackageWeight": {
                "UnitOfMeasurement": {"Code": "LBS"},
                "Weight": str(float(pkg.get("weight", 1.0))),
            },
        }
        if all(pkg.get(d) for d in ("length", "width", "height")):
            ups_pkg["Dimensions"] = {
                "UnitOfMeasurement": {"Code": "IN"},
                "Length": str(pkg["length"]),
                "Width": str(pkg["width"]),
                "Height": str(pkg["height"]),
            }
        # Declared value affects insurance cost in rate quote
        if pkg.get("declaredValue"):
            ups_pkg.setdefault("PackageServiceOptions", {})[
                "DeclaredValue"
            ] = {
                "Type": {"Code": "01"},
                "CurrencyCode": "USD",
                "MonetaryValue": str(pkg["declaredValue"]),
            }
        ups_packages.append(ups_pkg)

    shipment: dict[str, Any] = {
        "Shipper": ups_shipper,
        "ShipTo": ups_ship_to,
        "ShipFrom": ups_shipper,
        "Package": ups_packages,
        # Payment + negotiated rates — ensures rate quote matches actual billing
        "PaymentInformation": {
            "ShipmentCharge": [
                {
                    "Type": "01",
                    "BillShipper": {"AccountNumber": account_number},
                }
            ]
        },
        "ShipmentRatingOptions": {
            "NegotiatedRatesIndicator": "",
        },
    }

    if service_code:
        shipment["Service"] = {"Code": service_code}

    # Delivery confirmation affects rate
    dc = simplified.get("deliveryConfirmation")
    if dc:
        shipment.setdefault("ShipmentServiceOptions", {})[
            "DeliveryConfirmation"
        ] = {"DCISType": str(dc)}

    # Saturday delivery affects rate
    if simplified.get("saturdayDelivery"):
        shipment.setdefault("ShipmentServiceOptions", {})[
            "SaturdayDeliveryIndicator"
        ] = ""

    # --- International enrichment for rate accuracy ---

    # InvoiceLineTotal required for accurate US→CA rate quotes
    invoice_lt = simplified.get("invoiceLineTotal")
    if invoice_lt:
        shipment["InvoiceLineTotal"] = {
            "CurrencyCode": invoice_lt["currencyCode"],
            "MonetaryValue": invoice_lt["monetaryValue"],
        }

    # Description
    desc = simplified.get("description")
    if desc:
        shipment["Description"] = desc

    return {
        "RateRequest": {
            "Request": {"RequestOption": "Rate"},
            "Shipment": shipment,
        }
    }


def _build_address_lines(addr: dict[str, str]) -> list[str]:
    """Build UPS AddressLine array from simplified address dict.

    Args:
        addr: Dict with addressLine1, addressLine2, addressLine3 keys.

    Returns:
        List of non-empty address lines.
    """
    lines = []
    for key in ("addressLine1", "addressLine2", "addressLine3"):
        value = addr.get(key, "")
        if value:
            lines.append(value)
    return lines or [""]
