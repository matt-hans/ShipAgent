"""Synthetic hosted UPS MCP boundary fixtures for validator tests."""

from typing import Any

HOSTED_V1_RATE_QUOTE_SUCCESS: dict[str, Any] = {
    "success": True,
    "serviceCode": "03",
    "totalCharges": {
        "monetaryValue": "12.34",
        "currencyCode": "USD",
    },
}

HOSTED_V1_RATE_SHOP_SUCCESS: dict[str, Any] = {
    "success": True,
    "ratedShipments": [
        {
            "serviceCode": "03",
            "serviceDescription": "Synthetic Ground",
            "totalCharges": {
                "monetaryValue": "12.34",
                "currencyCode": "USD",
            },
        },
    ],
}

HOSTED_V1_ADDRESS_VALIDATION_SUCCESS: dict[str, Any] = {
    "status": "ambiguous",
    "candidates": [
        {
            "addressLine1": "100 Example Way",
            "city": "Testville",
            "state": "NY",
            "postalCode": "10001",
            "countryCode": "US",
        },
    ],
}

HOSTED_V1_CREATE_SHIPMENT_SUCCESS: dict[str, Any] = {
    "success": True,
    "idempotencyKey": "idem_synthetic_001",
    "shipmentIdentificationNumber": "SHIP-SYNTHETIC-001",
    "trackingNumbers": ["TRACK-SYNTHETIC-001"],
    "totalCharges": {
        "monetaryValue": "12.34",
        "currencyCode": "USD",
    },
    "labelData": [
        {
            "format": "PDF",
            "encoding": "base64",
            "contentBase64": "JVBERi0xLjQKc3ludGhldGljLWxhYmVsCg==",
        },
    ],
}

HOSTED_V1_SAFE_ERROR: dict[str, Any] = {
    "success": False,
    "error": {
        "code": "E-SYNTHETIC",
        "category": "validation",
        "message": "Synthetic validation error.",
        "retryable": False,
        "correlation_id": "corr_synthetic_001",
    },
}
