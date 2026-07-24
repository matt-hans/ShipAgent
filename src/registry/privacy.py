"""Provider-visible registry privacy invariants."""

import re
from collections.abc import Iterator
from typing import Any

_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def _field_tokens(value: str) -> set[str]:
    snake_case = _CAMEL_CASE_BOUNDARY.sub("_", value).lower()
    return {token for token in _NON_ALPHANUMERIC.split(snake_case) if token}


def _property_paths(
    schema: object,
    prefix: tuple[str, ...] = (),
) -> Iterator[tuple[str, ...]]:
    if not isinstance(schema, dict):
        return
    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        for name, child in properties.items():
            path = (*prefix, str(name))
            yield path
            yield from _property_paths(child, path)
    yield from _property_paths(schema.get("items"), prefix)


def provider_schema_privacy_violations(
    tool_name: str,
    schema: dict[str, Any],
) -> list[str]:
    """Return provider-visible property paths that can carry sensitive content."""
    tool_tokens = _field_tokens(tool_name)
    violations: list[str] = []

    for path in _property_paths(schema):
        field_name = path[-1]
        tokens = _field_tokens(field_name)
        is_row_count = "row" in tokens and "count" in tokens
        raw_customer_content = bool(tokens & {"address", "payload"}) or (
            "row" in tokens and not is_row_count
        )
        credential_or_token = bool(
            tokens & {"credential", "credentials", "password", "secret", "token"}
        )
        label_or_document_transfer = bool(
            (tokens | tool_tokens) & {"label", "document"}
        ) and bool(
            tokens
            & {
                "base64",
                "bytes",
                "content",
                "data",
                "download",
                "uri",
                "url",
            }
        )
        raw_carrier_exchange = bool(tokens & {"request", "response"}) and bool(
            tokens & {"body", "carrier", "data", "payload", "raw"}
        )
        if (
            raw_customer_content
            or credential_or_token
            or label_or_document_transfer
            or raw_carrier_exchange
        ):
            violations.append(".".join(path))

    return violations
