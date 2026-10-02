import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from jsonschema import validate

from src.registry.models import ToolContract
from src.registry.privacy import (
    ALWAYS_FORBIDDEN_RESULT_KEYS,
    EXPIRES_IN_FIELD,
    LOCAL_DATA_RESULT_KEYS,
    DataOrigin,
)

FORBIDDEN_AGGREGATE_KEYS = ALWAYS_FORBIDDEN_RESULT_KEYS | LOCAL_DATA_RESULT_KEYS

_SCHEMA_ENFORCED_PROFILES = {"aggregate", "provider_ingress_echo", "artifact_action"}


def _forbidden_paths(
    value: object,
    path: tuple[str, ...] = (),
    forbidden_keys: frozenset[str] = FORBIDDEN_AGGREGATE_KEYS,
) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_path = (*path, str(key))
            if key in forbidden_keys:
                found.append(".".join(nested_path))
            found.extend(_forbidden_paths(nested, nested_path, forbidden_keys))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_forbidden_paths(nested, (*path, str(index)), forbidden_keys))
    return found


def _assert_closed_profile_schema_allowed(
    value: Any,
    schema: Mapping[str, Any],
    profile: str,
    path: tuple[str, ...] = (),
) -> bool:
    if profile not in _SCHEMA_ENFORCED_PROFILES:
        return True

    if isinstance(value, dict):
        additional_properties = schema.get("additionalProperties")
        if additional_properties is not False:
            location = "root" if not path else ".".join(path)
            raise ValueError(
                f"aggregate profile schema at {location} requires additionalProperties=False"
            )

        properties = schema.get("properties") or {}
        for key, nested in value.items():
            if key not in properties:
                raise ValueError(f"aggregate result contains unexpected key: {key}")

            nested_schema = properties[key]
            if isinstance(nested, (dict, list)) and not isinstance(
                nested_schema, Mapping
            ):
                location = ".".join((*path, key))
                raise ValueError(
                    f"aggregate result container requires a schema object at {location}"
                )
            if not isinstance(nested_schema, Mapping):
                continue
            _assert_closed_profile_schema_allowed(
                nested,
                nested_schema,
                profile,
                path + (key,),
            )

    elif isinstance(value, list):
        items = schema.get("items")
        for index, item in enumerate(value):
            if not isinstance(item, (dict, list, str, int, float, bool, type(None))):
                raise ValueError(
                    f"aggregate result contains unsupported list item at index {index}"
                )
            if isinstance(item, (dict, list)):
                if not isinstance(items, Mapping):
                    location = ".".join((*path, str(index)))
                    raise ValueError(
                        "aggregate result container requires a schema object "
                        f"at {location}"
                    )
                _assert_closed_profile_schema_allowed(
                    item,
                    items,
                    profile,
                    path + (str(index),),
                )

    return True


def _result_value(result: Mapping[str, Any], dotted_path: str) -> Any:
    node: Any = result
    for part in dotted_path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def _has_control_chars(text: str, *, allow_space: bool) -> bool:
    """Report control characters (and whitespace unless allowed) in text."""
    return any(
        ord(ch) < 0x20
        or ord(ch) == 0x7F
        or (not allow_space and (ch.isspace() or ch in "\u0085\u2028\u2029"))
        for ch in text
    )


def _assert_provider_origins(
    contract: ToolContract,
    result: dict,
    field_origins: Mapping[str, DataOrigin] | None,
) -> None:
    """Fail closed unless every present echo field is provider-supplied."""
    for path in contract.provider_originated_fields:
        if _result_value(result, path) is None:
            continue
        origin = (field_origins or {}).get(path)
        # Identity check: a plain string equal to the enum value is not trusted
        # service metadata and must not unlock echo.
        if (
            not isinstance(origin, DataOrigin)
            or origin is not DataOrigin.provider_supplied
        ):
            raise ValueError(f"provider-originated field {path} lacks provider origin")
        value = _result_value(result, path)
        if isinstance(value, str) and _has_control_chars(value, allow_space=True):
            raise ValueError(f"provider-originated field {path} has control characters")


def _assert_signed_download_urls(contract: ToolContract, result: dict) -> None:
    """Allow only plain https signed URLs that carry a short expiry and ready status.

    Shape checks only: signature verification, single-use and account binding
    are deferred trusted-minting obligations (ADR 0007), not enforced here.
    """
    for path in contract.signed_download_fields:
        url = _result_value(result, path)
        if url is None:
            continue
        parent, _, _ = path.rpartition(".")
        prefix = f"{parent}." if parent else ""
        if _result_value(result, f"{prefix}{EXPIRES_IN_FIELD}") is None:
            raise ValueError(
                f"signed download URL at {path} requires {EXPIRES_IN_FIELD}"
            )
        if _result_value(result, f"{prefix}status") != "ready":
            raise ValueError(f"signed download URL at {path} requires ready status")
        if isinstance(url, str) and _has_control_chars(url, allow_space=False):
            raise ValueError(f"signed download URL at {path} is not allowed")
        try:
            parsed = urlsplit(url) if isinstance(url, str) else None
            valid = (
                parsed is not None
                and parsed.scheme == "https"
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and not parsed.fragment
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(f"signed download URL at {path} is not allowed")


def project_result(
    contract: ToolContract,
    result: dict,
    *,
    field_origins: Mapping[str, DataOrigin] | None = None,
) -> dict:
    """Validate a provider-bound result; origins gate ADR 0007 echo fields."""
    if not isinstance(result, dict):
        raise ValueError("provider result must be a JSON object")

    if contract.result_profile in _SCHEMA_ENFORCED_PROFILES:
        forbidden_keys = (
            FORBIDDEN_AGGREGATE_KEYS
            if contract.result_profile == "aggregate"
            else ALWAYS_FORBIDDEN_RESULT_KEYS
        )
        forbidden = _forbidden_paths(result, forbidden_keys=forbidden_keys)
        if forbidden:
            raise ValueError(
                f"{contract.result_profile} result contains forbidden keys: "
                f"{sorted(forbidden)}"
            )

        _assert_closed_profile_schema_allowed(
            result,
            contract.output_schema,
            contract.result_profile,
        )

    validate(instance=result, schema=contract.output_schema)
    _assert_provider_origins(contract, result, field_origins)
    _assert_signed_download_urls(contract, result)
    encoded = json.dumps(result, separators=(",", ":")).encode()
    if len(encoded) > contract.max_result_bytes:
        raise ValueError("provider result exceeds contract size")
    return result
