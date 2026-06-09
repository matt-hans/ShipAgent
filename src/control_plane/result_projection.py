import json
from collections.abc import Mapping
from typing import Any

from jsonschema import validate

from src.registry.models import ToolContract

FORBIDDEN_AGGREGATE_KEYS = frozenset(
    {
        "rows",
        "preview_rows",
        "sample_rows",
        "address_line_1",
        "recipient_name",
        "account_number",
        "credentials",
        "label_bytes",
        "raw_response",
        "request_body",
        "local_path",
    }
)


_SCHEMA_ENFORCED_PROFILES = {"aggregate", "provider_ingress_echo", "artifact_action"}


def _forbidden_paths(value: object, path: tuple[str, ...] = ()) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_path = (*path, str(key))
            if key in FORBIDDEN_AGGREGATE_KEYS:
                found.append(".".join(nested_path))
            found.extend(_forbidden_paths(nested, nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_forbidden_paths(nested, (*path, str(index))))
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
        properties = schema.get("properties")
        additional_properties = schema.get("additionalProperties")
        if properties is None:
            return True

        if additional_properties is not False:
            location = "root" if not path else ".".join(path)
            raise ValueError(
                f"aggregate profile schema at {location} requires additionalProperties=False"
            )

        for key, nested in value.items():
            if key not in properties:
                raise ValueError(f"aggregate result contains unexpected key: {key}")

            nested_schema = properties[key]
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
        if items is None:
            return True
        if not isinstance(items, Mapping):
            return True

        for index, item in enumerate(value):
            if not isinstance(item, (dict, list, str, int, float, bool, type(None))):
                raise ValueError(
                    f"aggregate result contains unsupported list item at index {index}"
                )
            if isinstance(item, (dict, list)):
                _assert_closed_profile_schema_allowed(
                    item,
                    items,
                    profile,
                    path + (str(index),),
                )

    return True


def project_result(contract: ToolContract, result: dict) -> dict:
    if not isinstance(result, dict):
        raise ValueError("provider result must be a JSON object")

    if contract.result_profile in _SCHEMA_ENFORCED_PROFILES:
        if contract.result_profile == "aggregate":
            forbidden = _forbidden_paths(result)
            if forbidden:
                raise ValueError(
                    f"aggregate result contains forbidden keys: {sorted(forbidden)}"
                )

        _assert_closed_profile_schema_allowed(
            result,
            contract.output_schema,
            contract.result_profile,
        )

    validate(instance=result, schema=contract.output_schema)
    encoded = json.dumps(result, separators=(",", ":")).encode()
    if len(encoded) > contract.max_result_bytes:
        raise ValueError("provider result exceeds contract size")
    return result
