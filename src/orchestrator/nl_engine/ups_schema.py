"""UPS JSON Schema definitions for template validation.

These schemas are Python translations of the Zod schemas defined in
packages/ups-mcp/src/generated/shipping.ts, converted to JSON Schema
format for use with the jsonschema library.

Reference: UPS OpenAPI Specification (shipping.yaml)
"""

from typing import Any

# ============================================================================
# Common Schemas
# ============================================================================

UPS_PHONE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "Number": {"type": "string", "minLength": 1, "maxLength": 15},
        "Extension": {"type": "string", "maxLength": 4},
    },
    "required": ["Number"],
    "additionalProperties": True,
}

UPS_ADDRESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "AddressLine": {
            "type": "array",
            "items": {"type": "string", "maxLength": 35},
            "minItems": 1,
            "maxItems": 3,
        },
        "City": {"type": "string", "minLength": 1, "maxLength": 30},
        "StateProvinceCode": {"type": "string", "maxLength": 5},
        "PostalCode": {"type": "string", "maxLength": 9},
        "CountryCode": {"type": "string", "minLength": 2, "maxLength": 2},
        "ResidentialAddressIndicator": {"type": "string"},
    },
    "required": ["AddressLine", "City", "CountryCode"],
    "additionalProperties": True,
}

# ============================================================================
# Entity Schemas (Shipper, ShipTo, ShipFrom)
# ============================================================================

UPS_SHIPPER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "Name": {"type": "string", "minLength": 1, "maxLength": 35},
        "AttentionName": {"type": "string", "maxLength": 35},
        "CompanyDisplayableName": {"type": "string", "maxLength": 35},
        "TaxIdentificationNumber": {"type": "string", "maxLength": 15},
        "Phone": UPS_PHONE_SCHEMA,
        "ShipperNumber": {"type": "string", "minLength": 6, "maxLength": 6},
        "FaxNumber": {"type": "string", "maxLength": 14},
        "EMailAddress": {"type": "string", "maxLength": 50},
        "Address": UPS_ADDRESS_SCHEMA,
    },
    "required": ["Name", "ShipperNumber", "Address"],
    "additionalProperties": True,
}

UPS_SHIPTO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "Name": {"type": "string", "minLength": 1, "maxLength": 35},
        "AttentionName": {"type": "string", "maxLength": 35},
        "CompanyDisplayableName": {"type": "string", "maxLength": 35},
        "TaxIdentificationNumber": {"type": "string", "maxLength": 15},
        "Phone": UPS_PHONE_SCHEMA,
        "FaxNumber": {"type": "string", "maxLength": 15},
        "EMailAddress": {"type": "string", "maxLength": 50},
        "Address": UPS_ADDRESS_SCHEMA,
        "LocationID": {"type": "string", "maxLength": 10},
    },
    "required": ["Name", "Address"],
    "additionalProperties": True,
}

UPS_SHIPFROM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "Name": {"type": "string", "minLength": 1, "maxLength": 35},
        "AttentionName": {"type": "string", "maxLength": 35},
        "CompanyDisplayableName": {"type": "string", "maxLength": 35},
        "TaxIdentificationNumber": {"type": "string", "maxLength": 15},
        "Phone": UPS_PHONE_SCHEMA,
        "FaxNumber": {"type": "string", "maxLength": 15},
        "Address": UPS_ADDRESS_SCHEMA,
    },
    "required": ["Name", "Address"],
    "additionalProperties": True,
}

# ============================================================================
# Payment Schemas
# ============================================================================

UPS_BILL_SHIPPER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "AccountNumber": {"type": "string", "minLength": 6, "maxLength": 6},
    },
    "required": ["AccountNumber"],
    "additionalProperties": True,
}

UPS_SHIPMENT_CHARGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "Type": {"type": "string", "minLength": 1, "maxLength": 2},
        "BillShipper": UPS_BILL_SHIPPER_SCHEMA,
    },
    "required": ["Type"],
    "additionalProperties": True,
}

UPS_PAYMENT_INFORMATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ShipmentCharge": {
            "oneOf": [
                UPS_SHIPMENT_CHARGE_SCHEMA,
                {"type": "array", "items": UPS_SHIPMENT_CHARGE_SCHEMA},
            ]
        },
    },
    "required": ["ShipmentCharge"],
    "additionalProperties": True,
}

# ============================================================================
# Service and Package Schemas
# ============================================================================

# Common UPS service codes
UPS_SERVICE_CODES = ["01", "02", "03", "12", "13", "14", "59", "65", "93"]

UPS_SERVICE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "Code": {"type": "string", "minLength": 1, "maxLength": 2},
        "Description": {"type": "string", "maxLength": 35},
    },
    "required": ["Code"],
    "additionalProperties": True,
}

UPS_UNIT_OF_MEASUREMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "Code": {"type": "string", "minLength": 1, "maxLength": 3},
        "Description": {"type": "string", "maxLength": 35},
    },
    "required": ["Code"],
    "additionalProperties": True,
}

UPS_DIMENSIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "UnitOfMeasurement": UPS_UNIT_OF_MEASUREMENT_SCHEMA,
        "Length": {"type": "string", "minLength": 1, "maxLength": 8},
        "Width": {"type": "string", "minLength": 1, "maxLength": 8},
        "Height": {"type": "string", "minLength": 1, "maxLength": 8},
    },
    "required": ["UnitOfMeasurement", "Length", "Width", "Height"],
    "additionalProperties": True,
}

UPS_PACKAGE_WEIGHT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "UnitOfMeasurement": UPS_UNIT_OF_MEASUREMENT_SCHEMA,
        "Weight": {
            "type": "string",
            "minLength": 1,
            "maxLength": 8,
            "pattern": "^[0-9]+(\\.[0-9]+)?$",
        },
    },
    "required": ["UnitOfMeasurement", "Weight"],
    "additionalProperties": True,
}

UPS_PACKAGING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "Code": {"type": "string", "minLength": 1, "maxLength": 2},
        "Description": {"type": "string", "maxLength": 35},
    },
    "required": ["Code"],
    "additionalProperties": True,
}

UPS_PACKAGE_SERVICE_OPTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "DeliveryConfirmation": {
            "type": "object",
            "properties": {
                "DCISType": {"type": "string", "minLength": 1, "maxLength": 1},
            },
            "required": ["DCISType"],
            "additionalProperties": True,
        },
        "DeclaredValue": {
            "type": "object",
            "properties": {
                "CurrencyCode": {"type": "string", "minLength": 3, "maxLength": 3},
                "MonetaryValue": {"type": "string", "minLength": 1, "maxLength": 15},
            },
            "required": ["CurrencyCode", "MonetaryValue"],
            "additionalProperties": True,
        },
    },
    "additionalProperties": True,
}

UPS_PACKAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "Description": {"type": "string", "maxLength": 35},
        "Packaging": UPS_PACKAGING_SCHEMA,
        "Dimensions": UPS_DIMENSIONS_SCHEMA,
        "PackageWeight": UPS_PACKAGE_WEIGHT_SCHEMA,
        "PackageServiceOptions": UPS_PACKAGE_SERVICE_OPTIONS_SCHEMA,
        "NumOfPieces": {"type": "string", "maxLength": 5},
    },
    "required": ["Packaging", "PackageWeight"],
    "additionalProperties": True,
}

# ============================================================================
# Label Specification Schema
# ============================================================================

UPS_LABEL_IMAGE_FORMAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "Code": {"type": "string", "minLength": 1, "maxLength": 3},
        "Description": {"type": "string", "maxLength": 35},
    },
    "required": ["Code"],
    "additionalProperties": True,
}

UPS_LABEL_SPECIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "LabelImageFormat": UPS_LABEL_IMAGE_FORMAT_SCHEMA,
        "HTTPUserAgent": {"type": "string", "maxLength": 64},
        "LabelStockSize": {
            "type": "object",
            "properties": {
                "Height": {"type": "string", "minLength": 1, "maxLength": 4},
                "Width": {"type": "string", "minLength": 1, "maxLength": 4},
            },
            "required": ["Height", "Width"],
            "additionalProperties": True,
        },
    },
    "required": ["LabelImageFormat"],
    "additionalProperties": True,
}

# ============================================================================
# Full Shipment Schema
# ============================================================================

UPS_SHIPMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "Description": {"type": "string", "maxLength": 35},
        "Shipper": UPS_SHIPPER_SCHEMA,
        "ShipTo": UPS_SHIPTO_SCHEMA,
        "ShipFrom": UPS_SHIPFROM_SCHEMA,
        "PaymentInformation": UPS_PAYMENT_INFORMATION_SCHEMA,
        "Service": UPS_SERVICE_SCHEMA,
        "Package": {
            "oneOf": [
                UPS_PACKAGE_SCHEMA,
                {"type": "array", "items": UPS_PACKAGE_SCHEMA},
            ]
        },
        "ShipmentRatingOptions": {
            "type": "object",
            "properties": {
                "NegotiatedRatesIndicator": {"type": "string"},
            },
            "additionalProperties": True,
        },
    },
    "required": ["Shipper", "ShipTo", "PaymentInformation", "Service", "Package"],
    "additionalProperties": True,
}

UPS_SHIPMENT_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "Request": {
            "type": "object",
            "properties": {
                "RequestOption": {"type": "string", "maxLength": 15},
                "SubVersion": {"type": "string", "minLength": 4, "maxLength": 4},
                "TransactionReference": {
                    "type": "object",
                    "properties": {
                        "CustomerContext": {"type": "string", "maxLength": 512},
                    },
                    "additionalProperties": True,
                },
            },
            "additionalProperties": True,
        },
        "Shipment": UPS_SHIPMENT_SCHEMA,
        "LabelSpecification": UPS_LABEL_SPECIFICATION_SCHEMA,
    },
    "required": ["Shipment", "LabelSpecification"],
    "additionalProperties": True,
}

# ============================================================================
# Schema Registry for Path-Based Lookup
# ============================================================================

SCHEMA_REGISTRY: dict[str, dict[str, Any]] = {
    "Phone": UPS_PHONE_SCHEMA,
    "Address": UPS_ADDRESS_SCHEMA,
    "Shipper": UPS_SHIPPER_SCHEMA,
    "ShipTo": UPS_SHIPTO_SCHEMA,
    "ShipFrom": UPS_SHIPFROM_SCHEMA,
    "BillShipper": UPS_BILL_SHIPPER_SCHEMA,
    "ShipmentCharge": UPS_SHIPMENT_CHARGE_SCHEMA,
    "PaymentInformation": UPS_PAYMENT_INFORMATION_SCHEMA,
    "Service": UPS_SERVICE_SCHEMA,
    "UnitOfMeasurement": UPS_UNIT_OF_MEASUREMENT_SCHEMA,
    "Dimensions": UPS_DIMENSIONS_SCHEMA,
    "PackageWeight": UPS_PACKAGE_WEIGHT_SCHEMA,
    "Packaging": UPS_PACKAGING_SCHEMA,
    "PackageServiceOptions": UPS_PACKAGE_SERVICE_OPTIONS_SCHEMA,
    "Package": UPS_PACKAGE_SCHEMA,
    "LabelImageFormat": UPS_LABEL_IMAGE_FORMAT_SCHEMA,
    "LabelSpecification": UPS_LABEL_SPECIFICATION_SCHEMA,
    "Shipment": UPS_SHIPMENT_SCHEMA,
    "ShipmentRequest": UPS_SHIPMENT_REQUEST_SCHEMA,
}


def get_schema_for_path(path: str) -> dict[str, Any]:
    """Get the JSON Schema for a given target path.

    Supports both simple paths (e.g., "ShipTo") and nested paths
    (e.g., "ShipTo.Address", "Shipment.Package.PackageWeight").

    Args:
        path: Dot-separated path to the schema element.

    Returns:
        The JSON Schema for the specified path.

    Raises:
        ValueError: If the path is not found in the schema registry.

    Examples:
        >>> schema = get_schema_for_path("ShipTo")
        >>> "Name" in schema["properties"]
        True

        >>> schema = get_schema_for_path("ShipTo.Address")
        >>> "City" in schema["properties"]
        True
    """
    if not path:
        raise ValueError("Path cannot be empty")

    parts = path.split(".")

    # Check for direct match first
    if path in SCHEMA_REGISTRY:
        return SCHEMA_REGISTRY[path]

    # For single-part paths, try direct lookup
    if len(parts) == 1:
        if parts[0] in SCHEMA_REGISTRY:
            return SCHEMA_REGISTRY[parts[0]]
        raise ValueError(f"Schema not found for path: {path}")

    # For multi-part paths, navigate through the schema
    current_schema = None

    # Start from the first part
    if parts[0] in SCHEMA_REGISTRY:
        current_schema = SCHEMA_REGISTRY[parts[0]]
    else:
        raise ValueError(f"Schema not found for path: {path}")

    # Navigate through remaining parts
    for part in parts[1:]:
        if current_schema is None:
            raise ValueError(f"Schema not found for path: {path}")

        # Look for the property in current schema
        if "properties" in current_schema and part in current_schema["properties"]:
            prop_schema = current_schema["properties"][part]

            # Handle oneOf/anyOf by taking the first option
            if "oneOf" in prop_schema:
                prop_schema = prop_schema["oneOf"][0]
            elif "anyOf" in prop_schema:
                prop_schema = prop_schema["anyOf"][0]

            # Handle array items
            if prop_schema.get("type") == "array" and "items" in prop_schema:
                current_schema = prop_schema["items"]
            else:
                current_schema = prop_schema
        elif part in SCHEMA_REGISTRY:
            # Fall back to direct registry lookup
            current_schema = SCHEMA_REGISTRY[part]
        else:
            raise ValueError(f"Schema not found for path: {path}")

    return current_schema


__all__ = [
    # Individual schemas
    "UPS_PHONE_SCHEMA",
    "UPS_ADDRESS_SCHEMA",
    "UPS_SHIPPER_SCHEMA",
    "UPS_SHIPTO_SCHEMA",
    "UPS_SHIPFROM_SCHEMA",
    "UPS_BILL_SHIPPER_SCHEMA",
    "UPS_SHIPMENT_CHARGE_SCHEMA",
    "UPS_PAYMENT_INFORMATION_SCHEMA",
    "UPS_SERVICE_SCHEMA",
    "UPS_UNIT_OF_MEASUREMENT_SCHEMA",
    "UPS_DIMENSIONS_SCHEMA",
    "UPS_PACKAGE_WEIGHT_SCHEMA",
    "UPS_PACKAGING_SCHEMA",
    "UPS_PACKAGE_SERVICE_OPTIONS_SCHEMA",
    "UPS_PACKAGE_SCHEMA",
    "UPS_LABEL_IMAGE_FORMAT_SCHEMA",
    "UPS_LABEL_SPECIFICATION_SCHEMA",
    "UPS_SHIPMENT_SCHEMA",
    "UPS_SHIPMENT_REQUEST_SCHEMA",
    # Registry and lookup
    "SCHEMA_REGISTRY",
    "get_schema_for_path",
    # Constants
    "UPS_SERVICE_CODES",
]
