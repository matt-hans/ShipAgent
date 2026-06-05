"""Tests for hosted UPS MCP normalized response validators."""

import pytest

from src.hosted.ups_boundary.fixtures import (
    HOSTED_V1_ADDRESS_VALIDATION_SUCCESS,
    HOSTED_V1_CREATE_SHIPMENT_SUCCESS,
    HOSTED_V1_RATE_QUOTE_SUCCESS,
    HOSTED_V1_RATE_SHOP_SUCCESS,
    HOSTED_V1_SAFE_ERROR,
)
from src.hosted.ups_boundary.validators import (
    validate_address_validation_result,
    validate_create_shipment_result,
    validate_rate_quote_result,
    validate_rate_shop_result,
    validate_safe_error_result,
)


def test_validate_rate_quote_result_accepts_hosted_v1_success():
    result = validate_rate_quote_result(HOSTED_V1_RATE_QUOTE_SUCCESS)

    assert result.valid is True
    assert result.error_code is None


def test_validate_rate_quote_result_accepts_extra_success_fields():
    payload = {
        **HOSTED_V1_RATE_QUOTE_SUCCESS,
        "transitDays": "3",
    }

    result = validate_rate_quote_result(payload)

    assert result.valid is True


@pytest.mark.parametrize(
    ("validator", "payload", "error_code"),
    [
        (
            validate_rate_quote_result,
            {
                **HOSTED_V1_RATE_QUOTE_SUCCESS,
                "rawResponse": {"provider": "unsafe"},
            },
            "E-3004",
        ),
        (
            validate_rate_shop_result,
            {
                **HOSTED_V1_RATE_SHOP_SUCCESS,
                "ratedShipments": [
                    {
                        **HOSTED_V1_RATE_SHOP_SUCCESS["ratedShipments"][0],
                        "accessToken": "unsafe",
                    },
                ],
            },
            "E-3004",
        ),
        (
            validate_address_validation_result,
            {
                **HOSTED_V1_ADDRESS_VALIDATION_SUCCESS,
                "candidates": [
                    {
                        **HOSTED_V1_ADDRESS_VALIDATION_SUCCESS["candidates"][0],
                        "local_path": "/tmp/unsafe",
                    },
                ],
            },
            "E-3007",
        ),
        (
            validate_create_shipment_result,
            {
                **HOSTED_V1_CREATE_SHIPMENT_SUCCESS,
                "requestBody": {"provider": "unsafe"},
            },
            "E-3006",
        ),
        (
            validate_create_shipment_result,
            {
                **HOSTED_V1_CREATE_SHIPMENT_SUCCESS,
                "labelData": [
                    {
                        **HOSTED_V1_CREATE_SHIPMENT_SUCCESS["labelData"][0],
                        "credentials": {"provider": "unsafe"},
                    },
                ],
            },
            "E-3006",
        ),
    ],
)
def test_success_validators_reject_unsafe_fields(validator, payload, error_code):
    result = validator(payload)

    assert result.valid is False
    assert result.error_code == error_code


def test_validate_rate_quote_result_rejects_missing_currency():
    payload = {
        **HOSTED_V1_RATE_QUOTE_SUCCESS,
        "totalCharges": {"monetaryValue": "12.34"},
    }

    result = validate_rate_quote_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3004"


def test_validate_rate_quote_result_rejects_empty_currency():
    payload = {
        **HOSTED_V1_RATE_QUOTE_SUCCESS,
        "totalCharges": {"monetaryValue": "12.34", "currencyCode": ""},
    }

    result = validate_rate_quote_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3004"


def test_validate_rate_quote_result_rejects_whitespace_monetary_value():
    payload = {
        **HOSTED_V1_RATE_QUOTE_SUCCESS,
        "totalCharges": {"monetaryValue": "   ", "currencyCode": "USD"},
    }

    result = validate_rate_quote_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3004"


def test_validate_rate_shop_result_rejects_empty_rated_shipments():
    result = validate_rate_shop_result({"success": True, "ratedShipments": []})

    assert result.valid is False
    assert result.error_code == "E-3004"


def test_validate_rate_shop_result_accepts_hosted_v1_success():
    result = validate_rate_shop_result(HOSTED_V1_RATE_SHOP_SUCCESS)

    assert result.valid is True
    assert result.error_code is None


def test_validate_rate_shop_result_rejects_empty_monetary_value():
    payload = {
        **HOSTED_V1_RATE_SHOP_SUCCESS,
        "ratedShipments": [
            {
                **HOSTED_V1_RATE_SHOP_SUCCESS["ratedShipments"][0],
                "totalCharges": {"monetaryValue": "", "currencyCode": "USD"},
            },
        ],
    }

    result = validate_rate_shop_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3004"


def test_validate_address_validation_result_accepts_hosted_v1_success():
    result = validate_address_validation_result(HOSTED_V1_ADDRESS_VALIDATION_SUCCESS)

    assert result.valid is True
    assert result.error_code is None


def test_validate_address_validation_result_accepts_extra_success_fields():
    payload = {
        **HOSTED_V1_ADDRESS_VALIDATION_SUCCESS,
        "confidence": "medium",
    }

    result = validate_address_validation_result(payload)

    assert result.valid is True


def test_validate_address_validation_result_rejects_unknown_status():
    result = validate_address_validation_result({"status": "maybe"})

    assert result.valid is False
    assert result.error_code == "E-3007"


def test_validate_create_shipment_result_accepts_hosted_v1_success():
    result = validate_create_shipment_result(HOSTED_V1_CREATE_SHIPMENT_SUCCESS)

    assert result.valid is True
    assert result.error_code is None


def test_validate_create_shipment_result_rejects_missing_tracking():
    payload = {
        **HOSTED_V1_CREATE_SHIPMENT_SUCCESS,
        "trackingNumbers": [],
    }

    result = validate_create_shipment_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3006"


def test_validate_create_shipment_result_rejects_empty_shipment_id():
    payload = {
        **HOSTED_V1_CREATE_SHIPMENT_SUCCESS,
        "shipmentIdentificationNumber": "",
    }

    result = validate_create_shipment_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3006"


def test_validate_create_shipment_result_rejects_whitespace_shipment_id():
    payload = {
        **HOSTED_V1_CREATE_SHIPMENT_SUCCESS,
        "shipmentIdentificationNumber": "   ",
    }

    result = validate_create_shipment_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3006"


def test_validate_create_shipment_result_rejects_empty_tracking_number():
    payload = {
        **HOSTED_V1_CREATE_SHIPMENT_SUCCESS,
        "trackingNumbers": [""],
    }

    result = validate_create_shipment_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3006"


def test_validate_create_shipment_result_rejects_whitespace_tracking_number():
    payload = {
        **HOSTED_V1_CREATE_SHIPMENT_SUCCESS,
        "trackingNumbers": ["   "],
    }

    result = validate_create_shipment_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3006"


def test_validate_create_shipment_result_rejects_non_string_tracking_number():
    payload = {
        **HOSTED_V1_CREATE_SHIPMENT_SUCCESS,
        "trackingNumbers": [123],
    }

    result = validate_create_shipment_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3006"


def test_validate_create_shipment_result_rejects_empty_total_charges_currency():
    payload = {
        **HOSTED_V1_CREATE_SHIPMENT_SUCCESS,
        "totalCharges": {"monetaryValue": "12.34", "currencyCode": ""},
    }

    result = validate_create_shipment_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3006"


def test_validate_safe_error_result_accepts_hosted_v1_safe_error():
    result = validate_safe_error_result(HOSTED_V1_SAFE_ERROR)

    assert result.valid is True
    assert result.error_code is None


def test_validate_safe_error_result_rejects_raw_details_nested_payloads():
    payload = {
        **HOSTED_V1_SAFE_ERROR,
        "error": {
            **HOSTED_V1_SAFE_ERROR["error"],
            "details": {"raw": {"provider": "unsafe"}},
        },
    }

    result = validate_safe_error_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3008"


def test_validate_safe_error_result_rejects_nested_secrets_key():
    payload = {
        **HOSTED_V1_SAFE_ERROR,
        "error": {
            **HOSTED_V1_SAFE_ERROR["error"],
            "details": {"secrets": "SUPER_SECRET_RAW_VALUE"},
        },
    }

    result = validate_safe_error_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3008"
    assert "SUPER_SECRET_RAW_VALUE" not in result.message


def test_validate_safe_error_result_rejects_unlisted_top_level_keys():
    payload = {
        **HOSTED_V1_SAFE_ERROR,
        "provider_status": 500,
    }

    result = validate_safe_error_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3008"


def test_validate_safe_error_result_rejects_unlisted_error_keys():
    payload = {
        **HOSTED_V1_SAFE_ERROR,
        "error": {
            **HOSTED_V1_SAFE_ERROR["error"],
            "provider_status": 500,
        },
    }

    result = validate_safe_error_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3008"


def test_validate_safe_error_result_does_not_echo_raw_sentinel():
    payload = {
        **HOSTED_V1_SAFE_ERROR,
        "error": {
            **HOSTED_V1_SAFE_ERROR["error"],
            "raw": "SUPER_SECRET_RAW_VALUE",
        },
    }

    result = validate_safe_error_result(payload)

    assert result.valid is False
    assert result.error_code == "E-3008"
    assert "SUPER_SECRET_RAW_VALUE" not in result.message
