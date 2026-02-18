"""UPS payload builder for shipment requests.

Transforms order data from JobRow.order_data (JSON) into UPS MCP
shipping_create input format. Also handles shipper information
from environment variables and Shopify shop details.

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

from src.services.ups_constants import (
    DEFAULT_CURRENCY_CODE,
    DEFAULT_FORM_TYPE,
    DEFAULT_LABEL_FORMAT,
    DEFAULT_LABEL_HEIGHT,
    DEFAULT_LABEL_WIDTH,
    DEFAULT_ORIGIN_COUNTRY,
    DEFAULT_PACKAGE_WEIGHT_LBS,
    DEFAULT_PACKAGING_CODE,
    DEFAULT_REASON_FOR_EXPORT,
    GRAMS_PER_LB,
    PACKAGING_ALIASES,
    UPS_ADDRESS_MAX_LEN,
    UPS_DIMENSION_UNIT,
    UPS_PHONE_MAX_DIGITS,
    UPS_PHONE_MIN_DIGITS,
    UPS_REFERENCE_MAX_LEN,
    UPS_WEIGHT_UNIT,
)
from src.services.ups_service_codes import (
    SUPPORTED_INTERNATIONAL_SERVICES,
    ServiceCode,
    resolve_service_code,
    upgrade_to_international,
)


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
    if len(digits) < UPS_PHONE_MIN_DIGITS:
        return ""

    # Truncate to 15 digits (UPS max)
    return digits[:UPS_PHONE_MAX_DIGITS]


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


def truncate_address(address: str | None, max_length: int = UPS_ADDRESS_MAX_LEN) -> str:
    """Truncate address without cutting words.

    UPS limits address lines to 35 characters. This function
    truncates at word boundaries for cleaner results.

    Args:
        address: Raw address string
        max_length: Maximum length (default UPS_ADDRESS_MAX_LEN)

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


def build_shipper(shop_info: dict[str, Any] | None = None) -> dict[str, str]:
    """Build UPS shipper from env vars, optionally overlaid with Shopify shop data.

    Reads SHIPPER_* environment variables as the base. If shop_info is provided,
    non-empty Shopify values override the env var values.

    Missing required fields default to empty strings (no dummy addresses).
    The UPS API will reject empty shipper addresses with a clear error,
    which is safer than silently shipping from a fake address.

    Args:
        shop_info: Optional Shopify shop data dict with keys:
            name, phone, address1, address2, city, province_code, zip, country_code.

    Returns:
        Dict matching UPS shipper schema.
    """
    import os

    shipper = {
        "name": truncate_address(os.environ.get("SHIPPER_NAME", ""), UPS_ADDRESS_MAX_LEN),
        "phone": normalize_phone(os.environ.get("SHIPPER_PHONE")),
        "addressLine1": truncate_address(os.environ.get("SHIPPER_ADDRESS1", ""), UPS_ADDRESS_MAX_LEN),
        "addressLine2": "",
        "city": os.environ.get("SHIPPER_CITY", ""),
        "stateProvinceCode": os.environ.get("SHIPPER_STATE", ""),
        "postalCode": normalize_zip(os.environ.get("SHIPPER_ZIP", "")),
        "countryCode": os.environ.get("SHIPPER_COUNTRY", DEFAULT_ORIGIN_COUNTRY),
    }

    if shop_info:
        _SHOP_KEY_MAP = {
            "name": "name",
            "phone": "phone",
            "address1": "addressLine1",
            "address2": "addressLine2",
            "city": "city",
            "province_code": "stateProvinceCode",
            "zip": "postalCode",
            "country_code": "countryCode",
        }
        for shop_key, shipper_key in _SHOP_KEY_MAP.items():
            val = shop_info.get(shop_key)
            if val:
                val = str(val)
                if shipper_key == "phone":
                    val = normalize_phone(val)
                elif shipper_key == "postalCode":
                    val = normalize_zip(val)
                elif shipper_key in ("name", "addressLine1", "addressLine2"):
                    val = truncate_address(val, UPS_ADDRESS_MAX_LEN)
                shipper[shipper_key] = val

    return shipper


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

    normalized_name = truncate_address(name, UPS_ADDRESS_MAX_LEN) or "Recipient"
    attention_name = (
        order_data.get("ship_to_attention_name")
        or order_data.get("ship_to_company")
        or normalized_name
    )

    return {
        "name": normalized_name,
        "attentionName": truncate_address(attention_name, UPS_ADDRESS_MAX_LEN),
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
        return DEFAULT_PACKAGING_CODE.value

    # Coerce non-string values (e.g. int 2 from LLM/tool args)
    stripped = str(raw_value).strip()
    if not stripped:
        return DEFAULT_PACKAGING_CODE.value

    # Known alphanumeric UPS codes — pass through as-is
    _ALPHANUMERIC_CODES = {"2a", "2b", "2c"}
    if stripped.lower() in _ALPHANUMERIC_CODES:
        return stripped.lower()

    # Already a valid numeric code — return as-is
    if stripped.isdigit() and len(stripped) <= 3:
        return stripped.zfill(2)

    # Map human-readable names to UPS codes (case-insensitive) via PACKAGING_ALIASES
    matched = PACKAGING_ALIASES.get(stripped.lower())
    if matched is not None:
        return matched.value

    return DEFAULT_PACKAGING_CODE.value


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
                "weight": float(pkg.get("weight", DEFAULT_PACKAGE_WEIGHT_LBS)),
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
            weight = float(weight_grams) / GRAMS_PER_LB
        else:
            weight = DEFAULT_PACKAGE_WEIGHT_LBS

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


def get_service_code(order_data: dict[str, Any], default: str = ServiceCode.GROUND.value) -> str:
    """Get UPS service code from order data.

    Checks service_code first, then falls back to service name.
    Both values are resolved through the name-to-code map.

    Args:
        order_data: Order data containing service info
        default: Default service code (Ground)

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
    currency_code: str = DEFAULT_CURRENCY_CODE,
    form_type: str = DEFAULT_FORM_TYPE,
    reason_for_export: str = DEFAULT_REASON_FOR_EXPORT,
    invoice_date: str | None = None,
    sold_to: dict[str, str] | None = None,
) -> dict:
    """Build UPS InternationalForms section for customs documentation.

    Args:
        commodities: List of commodity dicts with description, commodity_code,
            origin_country, quantity, unit_value, and optional unit_of_measure.
        currency_code: ISO 4217 currency code (default USD).
        form_type: InternationalForms type (01 = commercial invoice).
        reason_for_export: Export reason code (SALE, GIFT, SAMPLE, etc.).
        invoice_date: Invoice date in YYYYMMDD format. Defaults to today.
        sold_to: Recipient address dict for Contacts.SoldTo (required by UPS
            when FormType=01). Keys: name, attentionName, phone, addressLine1,
            addressLine2, city, stateProvinceCode, postalCode, countryCode.

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
            "Description": str(comm["description"])[:UPS_ADDRESS_MAX_LEN],
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

    forms: dict[str, Any] = {
        "FormType": form_type,
        "InvoiceDate": invoice_date,
        "ReasonForExport": reason_for_export,
        "CurrencyCode": currency_code,
        "Product": products,
    }

    if sold_to:
        address_lines = [
            line for line in [
                sold_to.get("addressLine1", ""),
                sold_to.get("addressLine2", ""),
            ] if line
        ]
        contacts_sold_to: dict[str, Any] = {
            "Name": sold_to.get("name", "")[:UPS_ADDRESS_MAX_LEN],
            "AttentionName": sold_to.get(
                "attentionName", sold_to.get("name", "")
            )[:UPS_ADDRESS_MAX_LEN],
            "Address": {
                "AddressLine": address_lines or [""],
                "City": sold_to.get("city", ""),
                "StateProvinceCode": sold_to.get("stateProvinceCode", ""),
                "PostalCode": sold_to.get("postalCode", ""),
                "CountryCode": sold_to.get("countryCode", ""),
            },
        }
        if sold_to.get("phone"):
            contacts_sold_to["Phone"] = {"Number": sold_to["phone"]}
        forms["Contacts"] = {"SoldTo": contacts_sold_to}

    return forms


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
        shipper = build_shipper()

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

    # Safety net: auto-upgrade domestic service codes for international destinations.
    # Callers should already upgrade via batch_engine / interactive tool, but this
    # guarantees correctness regardless of call path.
    origin_country = shipper.get("countryCode", DEFAULT_ORIGIN_COUNTRY)
    dest_country = order_data.get("ship_to_country", "") or origin_country
    service_code = upgrade_to_international(service_code, origin_country, dest_country)

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
            "currencyCode": order_data.get("invoice_currency_code", DEFAULT_CURRENCY_CODE),
            "monetaryValue": order_data.get("invoice_monetary_value", "0"),
        }

    # Description — add as top-level key in simplified
    if requirements.requires_description:
        desc = order_data.get("shipment_description", "")
        if desc:
            result["description"] = desc[:UPS_ADDRESS_MAX_LEN]

    # InternationalForms — build from commodities and add to simplified
    if requirements.requires_international_forms:
        commodities = order_data.get("commodities", [])
        if commodities:
            reason_for_export = str(
                order_data.get("reason_for_export", DEFAULT_REASON_FOR_EXPORT)
            ).upper()
            result["internationalForms"] = build_international_forms(
                commodities=commodities,
                currency_code=requirements.currency_code,
                form_type=requirements.form_type,
                reason_for_export=reason_for_export,
                sold_to=ship_to,
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
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Transform simplified format to full UPS ShipmentRequest.

    Args:
        simplified: Simplified payload from build_shipment_request().
            Keys: shipper, shipTo, packages, serviceCode, description,
            reference, reference2, saturdayDelivery, signatureRequired.
        account_number: UPS account number for billing.
        idempotency_key: Optional idempotency key for TransactionReference.
            When provided, included as CustomerContext for exactly-once
            shipment creation and crash recovery audit.

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
    service_code = simplified.get("serviceCode", ServiceCode.GROUND.value)

    # Build Shipper
    ups_shipper: dict[str, Any] = {
        "Name": shipper.get("name", ""),
        "ShipperNumber": account_number,
        "Address": {
            "AddressLine": _build_address_lines(shipper),
            "City": shipper.get("city", ""),
            "StateProvinceCode": shipper.get("stateProvinceCode", ""),
            "PostalCode": shipper.get("postalCode", ""),
            "CountryCode": shipper.get("countryCode", DEFAULT_ORIGIN_COUNTRY),
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
            "CountryCode": ship_to.get("countryCode", DEFAULT_ORIGIN_COUNTRY),
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
                "Code": pkg.get("packagingType", DEFAULT_PACKAGING_CODE.value),
            },
            "PackageWeight": {
                "UnitOfMeasurement": {"Code": UPS_WEIGHT_UNIT},
                "Weight": str(float(pkg.get("weight", DEFAULT_PACKAGE_WEIGHT_LBS))),
            },
        }
        # Dimensions (all three required if any present)
        if all(pkg.get(d) for d in ("length", "width", "height")):
            ups_pkg["Dimensions"] = {
                "UnitOfMeasurement": {"Code": UPS_DIMENSION_UNIT},
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
                "CurrencyCode": DEFAULT_CURRENCY_CODE,
                "MonetaryValue": str(pkg["declaredValue"]),
            }
        ups_packages.append(ups_pkg)

    # MerchandiseDescription — required by UPS for certain international
    # destinations (e.g., Mexico). Populate from shipment description on
    # every package so the payload is universally valid.
    merch_desc = simplified.get("description", "")
    if merch_desc and service_code in SUPPORTED_INTERNATIONAL_SERVICES:
        for ups_pkg in ups_packages:
            ups_pkg["Description"] = str(merch_desc)[:UPS_ADDRESS_MAX_LEN]

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
            "Value": str(reference)[:UPS_REFERENCE_MAX_LEN],
        })
        ref2 = simplified.get("reference2")
        if ref2:
            refs.append({
                "Value": str(ref2)[:UPS_REFERENCE_MAX_LEN],
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

    request: dict[str, Any] = {"RequestOption": "nonvalidate"}
    if idempotency_key:
        request["TransactionReference"] = {"CustomerContext": idempotency_key}

    return {
        "ShipmentRequest": {
            "Request": request,
            "Shipment": shipment,
            "LabelSpecification": {
                "LabelImageFormat": {"Code": DEFAULT_LABEL_FORMAT},
                "LabelStockSize": {
                    "Height": DEFAULT_LABEL_HEIGHT,
                    "Width": DEFAULT_LABEL_WIDTH,
                },
            },
        }
    }


def build_ups_rate_payload(
    simplified: dict[str, Any],
    account_number: str,
    request_option: str = "Rate",
    include_service: bool = True,
) -> dict[str, Any]:
    """Transform simplified format to full UPS RateRequest.

    Args:
        simplified: Simplified payload from build_shipment_request().
        account_number: UPS account number.
        request_option: UPS rating request option ("Rate", "Shop",
            or "Shoptimeintransit").
        include_service: Whether to include Shipment.Service in payload.
            Use False with Shop requests to discover all available services.

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
    service_code = simplified.get("serviceCode", ServiceCode.GROUND.value)

    ups_shipper: dict[str, Any] = {
        "Name": shipper.get("name", ""),
        "ShipperNumber": account_number,
        "Address": {
            "AddressLine": _build_address_lines(shipper),
            "City": shipper.get("city", ""),
            "StateProvinceCode": shipper.get("stateProvinceCode", ""),
            "PostalCode": shipper.get("postalCode", ""),
            "CountryCode": shipper.get("countryCode", DEFAULT_ORIGIN_COUNTRY),
        },
    }

    ups_ship_to_addr: dict[str, Any] = {
        "AddressLine": _build_address_lines(ship_to),
        "City": ship_to.get("city", ""),
        "StateProvinceCode": ship_to.get("stateProvinceCode", ""),
        "PostalCode": ship_to.get("postalCode", ""),
        "CountryCode": ship_to.get("countryCode", DEFAULT_ORIGIN_COUNTRY),
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
            "Packaging": {"Code": pkg.get("packagingType", DEFAULT_PACKAGING_CODE.value)},
            "PackageWeight": {
                "UnitOfMeasurement": {"Code": UPS_WEIGHT_UNIT},
                "Weight": str(float(pkg.get("weight", DEFAULT_PACKAGE_WEIGHT_LBS))),
            },
        }
        if all(pkg.get(d) for d in ("length", "width", "height")):
            ups_pkg["Dimensions"] = {
                "UnitOfMeasurement": {"Code": UPS_DIMENSION_UNIT},
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
                "CurrencyCode": DEFAULT_CURRENCY_CODE,
                "MonetaryValue": str(pkg["declaredValue"]),
            }
        ups_packages.append(ups_pkg)

    # Package-level description for international (required by some destinations)
    merch_desc = simplified.get("description", "")
    if merch_desc and service_code in SUPPORTED_INTERNATIONAL_SERVICES:
        for ups_pkg in ups_packages:
            ups_pkg["Description"] = str(merch_desc)[:UPS_ADDRESS_MAX_LEN]

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

    if include_service and service_code:
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
            "Request": {"RequestOption": request_option},
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
