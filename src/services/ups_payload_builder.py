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
    result = await ups_service.create_shipment(request)
"""

import re
from typing import Any


def normalize_phone(phone: str | None) -> str:
    """Normalize phone number to digits only.

    UPS requires 10-15 digit phone numbers without formatting.

    Args:
        phone: Raw phone number string (may contain dashes, spaces, parens)

    Returns:
        Digits-only phone number, or default if invalid
    """
    if not phone:
        return "5555555555"  # Default placeholder

    # Strip all non-digit characters
    digits = re.sub(r"\D", "", phone)

    # Ensure minimum 10 digits
    if len(digits) < 10:
        return "5555555555"

    # Truncate to 15 digits (UPS max)
    return digits[:15]


def normalize_zip(postal_code: str | None) -> str:
    """Normalize US postal code.

    Handles both 5-digit and ZIP+4 formats.

    Args:
        postal_code: Raw postal code string

    Returns:
        Normalized 5-digit or ZIP+4 format
    """
    if not postal_code:
        return ""

    # Strip whitespace
    postal_code = postal_code.strip()

    # Extract digits
    digits = re.sub(r"\D", "", postal_code)

    if len(digits) >= 9:
        # ZIP+4 format
        return f"{digits[:5]}-{digits[5:9]}"
    elif len(digits) >= 5:
        # 5-digit ZIP
        return digits[:5]
    else:
        # Return as-is for international codes
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
        "countryCode": order_data.get("ship_to_country", "US"),
    }


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
        return [
            {
                "weight": float(pkg.get("weight", 1.0)),
                "length": pkg.get("length"),
                "width": pkg.get("width"),
                "height": pkg.get("height"),
                "packagingType": pkg.get("packaging_type", "02"),
                "description": pkg.get("description"),
            }
            for pkg in packages
        ]

    # Single package from order-level fields
    weight = order_data.get("weight") or order_data.get("total_weight") or 1.0

    package: dict[str, Any] = {
        "weight": float(weight),
        "packagingType": order_data.get("packaging_type", "02"),
    }

    # Add dimensions if present
    length = order_data.get("length")
    width = order_data.get("width")
    height = order_data.get("height")

    if length and width and height:
        package["length"] = float(length)
        package["width"] = float(width)
        package["height"] = float(height)

    return [package]


def get_service_code(order_data: dict[str, Any], default: str = "03") -> str:
    """Get UPS service code from order data.

    Maps service names to UPS codes if needed.

    Args:
        order_data: Order data containing service info
        default: Default service code ("03" = Ground)

    Returns:
        UPS service code string
    """
    # Check for explicit service code
    service_code = order_data.get("service_code")
    if service_code:
        return str(service_code)

    # Map service names to codes
    service_name_map = {
        "ground": "03",
        "ups ground": "03",
        "ground saver": "13",
        "2nd day air": "02",
        "2 day": "02",
        "next day air": "01",
        "next day": "01",
        "overnight": "01",
        "3 day select": "12",
        "3 day": "12",
    }

    service_name = order_data.get("service", "").lower().strip()
    return service_name_map.get(service_name, default)


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

    return {
        "shipper": shipper,
        "shipTo": ship_to,
        "packages": packages,
        "serviceCode": service_code,
        "description": description or "Shipment",
        "reference": str(reference) if reference else None,
    }


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
            "PackagingType": {
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
        ups_packages.append(ups_pkg)

    # Build Shipment
    shipment: dict[str, Any] = {
        "Shipper": ups_shipper,
        "ShipTo": ups_ship_to,
        "ShipFrom": ups_shipper,  # ShipFrom = Shipper for standard shipments
        "Service": {"Code": service_code},
        "Package": ups_packages,
        "PaymentInformation": {
            "ShipmentCharge": {
                "Type": "01",
                "BillShipper": {"AccountNumber": account_number},
            }
        },
    }

    # Optional fields
    if simplified.get("description"):
        shipment["Description"] = simplified["description"]
    if simplified.get("reference"):
        shipment["ReferenceNumber"] = {
            "Code": "00",
            "Value": simplified["reference"],
        }
    if simplified.get("reference2"):
        shipment["ReferenceNumber2"] = {
            "Code": "00",
            "Value": simplified["reference2"],
        }

    # Shipment-level options
    options = {}
    if simplified.get("saturdayDelivery"):
        options["SaturdayDeliveryIndicator"] = ""
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
        ups_packages.append(ups_pkg)

    shipment: dict[str, Any] = {
        "Shipper": ups_shipper,
        "ShipTo": ups_ship_to,
        "ShipFrom": ups_shipper,
        "Package": ups_packages,
    }

    if service_code:
        shipment["Service"] = {"Code": service_code}

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
