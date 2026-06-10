import json

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


def _forbidden_paths(
    value: object, path: tuple[str, ...] = ()
) -> list[str]:
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


def project_result(contract: ToolContract, result: dict) -> dict:
    if contract.result_profile == "aggregate":
        forbidden = _forbidden_paths(result)
        if forbidden:
            raise ValueError(
                f"aggregate result contains forbidden keys: {sorted(forbidden)}"
            )
    validate(instance=result, schema=contract.output_schema)
    encoded = json.dumps(result, separators=(",", ":")).encode()
    if len(encoded) > contract.max_result_bytes:
        raise ValueError("provider result exceeds contract size")
    return result
