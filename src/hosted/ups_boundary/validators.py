"""Validators for normalized hosted UPS MCP boundary responses."""

from collections.abc import Mapping
from typing import Any

from src.hosted.ups_boundary.models import UpsBoundaryValidationResult

_ADDRESS_STATUSES = {
    "valid",
    "corrected",
    "ambiguous",
    "invalid",
    "unsupported",
    "unknown",
}
_SAFE_ERROR_KEYS = {"code", "category", "message", "retryable", "correlation_id"}
_SAFE_ERROR_TOP_LEVEL_KEYS = {"success", "error"}
_SAFE_ERROR_CATEGORIES = {
    "auth",
    "rate_limit",
    "validation",
    "service_unavailable",
    "address",
    "customs",
    "transport",
    "unknown",
}
_UNSAFE_KEYS = {
    "details",
    "raw",
    "raw_response",
    "request",
    "request_body",
    "payload",
    "stack",
    "stack_trace",
    "traceback",
    "local_path",
    "path",
    "credentials",
    "secrets",
    "client_secret",
    "access_token",
}


def validate_rate_quote_result(
    result: Mapping[str, Any],
) -> UpsBoundaryValidationResult:
    """Validate a normalized hosted-v1 UPS rate quote result."""
    name = "rate_quote_result"
    unsafe_result = _reject_unsafe_result(
        result,
        name,
        "E-3004",
        "Rate quote result contains unsafe fields.",
    )
    if unsafe_result is not None:
        return unsafe_result

    if result.get("success") is True and _has_money_shape(result.get("totalCharges")):
        return _valid(name)
    return _invalid(name, "E-3004", "Rate quote result is not normalized.")


def validate_rate_shop_result(
    result: Mapping[str, Any],
) -> UpsBoundaryValidationResult:
    """Validate a normalized hosted-v1 UPS rate shop result."""
    name = "rate_shop_result"
    unsafe_result = _reject_unsafe_result(
        result,
        name,
        "E-3004",
        "Rate shop result contains unsafe fields.",
    )
    if unsafe_result is not None:
        return unsafe_result

    rated_shipments = result.get("ratedShipments")
    if result.get("success") is not True or not _non_empty_list(rated_shipments):
        return _invalid(name, "E-3004", "Rate shop result is not normalized.")

    for rated_shipment in rated_shipments:
        if not isinstance(rated_shipment, Mapping):
            return _invalid(name, "E-3004", "Rate shop result is not normalized.")
        if not _non_empty_string(rated_shipment.get("serviceCode")):
            return _invalid(name, "E-3004", "Rate shop result is not normalized.")
        if not _has_money_shape(rated_shipment.get("totalCharges")):
            return _invalid(name, "E-3004", "Rate shop result is not normalized.")

    return _valid(name)


def validate_address_validation_result(
    result: Mapping[str, Any],
) -> UpsBoundaryValidationResult:
    """Validate a normalized hosted-v1 UPS address validation result."""
    name = "address_validation_result"
    unsafe_result = _reject_unsafe_result(
        result,
        name,
        "E-3007",
        "Address validation result contains unsafe fields.",
    )
    if unsafe_result is not None:
        return unsafe_result

    if result.get("status") not in _ADDRESS_STATUSES:
        return _invalid(name, "E-3007", "Address validation result is not normalized.")

    candidates = result.get("candidates")
    if candidates is not None and not isinstance(candidates, list):
        return _invalid(name, "E-3007", "Address validation result is not normalized.")

    return _valid(name)


def validate_create_shipment_result(
    result: Mapping[str, Any],
) -> UpsBoundaryValidationResult:
    """Validate a normalized hosted-v1 UPS create shipment result."""
    name = "create_shipment_result"
    unsafe_result = _reject_unsafe_result(
        result,
        name,
        "E-3006",
        "Create shipment result contains unsafe fields.",
    )
    if unsafe_result is not None:
        return unsafe_result

    if result.get("success") is not True:
        return _invalid(name, "E-3006", "Create shipment result is not normalized.")
    if not _non_empty_string(result.get("idempotencyKey")):
        return _invalid(name, "E-3006", "Create shipment result is not normalized.")
    if not _non_empty_string(result.get("shipmentIdentificationNumber")):
        return _invalid(name, "E-3006", "Create shipment result is not normalized.")
    tracking_numbers = result.get("trackingNumbers")
    if not _non_empty_list(tracking_numbers):
        return _invalid(name, "E-3006", "Create shipment result is not normalized.")
    if not all(_non_empty_string(tracking) for tracking in tracking_numbers):
        return _invalid(name, "E-3006", "Create shipment result is not normalized.")
    if not _has_money_shape(result.get("totalCharges")):
        return _invalid(name, "E-3006", "Create shipment result is not normalized.")

    label_data = result.get("labelData")
    if not _non_empty_list(label_data):
        return _invalid(name, "E-3006", "Create shipment result is not normalized.")

    for label in label_data:
        if not isinstance(label, Mapping):
            return _invalid(name, "E-3006", "Create shipment result is not normalized.")
        if not _non_empty_string(label.get("format")):
            return _invalid(name, "E-3006", "Create shipment result is not normalized.")
        if label.get("encoding") != "base64":
            return _invalid(name, "E-3006", "Create shipment result is not normalized.")
        if not _non_empty_string(label.get("contentBase64")):
            return _invalid(name, "E-3006", "Create shipment result is not normalized.")

    return _valid(name)


def validate_safe_error_result(
    result: Mapping[str, Any],
) -> UpsBoundaryValidationResult:
    """Validate a sanitized hosted-v1 UPS safe error envelope."""
    name = "safe_error_result"
    if _contains_unsafe_key(result):
        return _invalid(name, "E-3008", "Safe error result contains unsafe fields.")
    if set(result) != _SAFE_ERROR_TOP_LEVEL_KEYS:
        return _invalid(name, "E-3008", "Safe error result is not normalized.")

    error = result.get("error")
    if result.get("success") is not False or not isinstance(error, Mapping):
        return _invalid(name, "E-3008", "Safe error result is not normalized.")

    if set(error) != _SAFE_ERROR_KEYS:
        return _invalid(name, "E-3008", "Safe error result is not normalized.")
    if not _non_empty_string(error.get("code")):
        return _invalid(name, "E-3008", "Safe error result is not normalized.")
    if error.get("category") not in _SAFE_ERROR_CATEGORIES:
        return _invalid(name, "E-3008", "Safe error result is not normalized.")
    if not _non_empty_string(error.get("message")):
        return _invalid(name, "E-3008", "Safe error result is not normalized.")
    if not isinstance(error.get("retryable"), bool):
        return _invalid(name, "E-3008", "Safe error result is not normalized.")
    if not _non_empty_string(error.get("correlation_id")):
        return _invalid(name, "E-3008", "Safe error result is not normalized.")

    return _valid(name)


def _has_money_shape(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and _non_empty_string(value.get("monetaryValue"))
        and _non_empty_string(value.get("currencyCode"))
    )


def _non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _reject_unsafe_result(
    result: Mapping[str, Any],
    name: str,
    error_code: str,
    message: str,
) -> UpsBoundaryValidationResult | None:
    if _contains_unsafe_key(result):
        return _invalid(name, error_code, message)
    return None


def _contains_unsafe_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _is_unsafe_key(key) or _contains_unsafe_key(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_unsafe_key(child) for child in value)
    return False


def _is_unsafe_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    return _to_snake_key(key) in _UNSAFE_KEYS


def _to_snake_key(key: str) -> str:
    chars: list[str] = []
    for char in key.replace("-", "_"):
        if char.isupper():
            if chars and chars[-1] != "_":
                chars.append("_")
            chars.append(char.lower())
        else:
            chars.append(char.lower())
    return "".join(chars)


def _valid(name: str) -> UpsBoundaryValidationResult:
    return UpsBoundaryValidationResult(name=name, valid=True)


def _invalid(
    name: str,
    error_code: str,
    message: str,
) -> UpsBoundaryValidationResult:
    return UpsBoundaryValidationResult(
        name=name,
        valid=False,
        error_code=error_code,
        message=message,
    )
