"""Provider-visible registry privacy invariants."""

import re
from collections.abc import Iterator
from typing import Any

_ACRONYM_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")

_COMMON_SCHEMA_KEYWORDS = frozenset({"type", "description", "enum"})
_SCHEMA_KEYWORDS_BY_TYPE = {
    "object": _COMMON_SCHEMA_KEYWORDS
    | {"properties", "required", "additionalProperties"},
    "array": _COMMON_SCHEMA_KEYWORDS | {"items", "minItems", "maxItems", "uniqueItems"},
    "string": _COMMON_SCHEMA_KEYWORDS | {"pattern", "minLength", "maxLength"},
    "integer": _COMMON_SCHEMA_KEYWORDS | {"minimum", "maximum"},
    "number": _COMMON_SCHEMA_KEYWORDS | {"minimum", "maximum"},
    "boolean": _COMMON_SCHEMA_KEYWORDS,
    "null": _COMMON_SCHEMA_KEYWORDS,
}


def _field_tokens(value: str) -> set[str]:
    acronym_split = _ACRONYM_BOUNDARY.sub("_", value)
    snake_case = _CAMEL_CASE_BOUNDARY.sub("_", acronym_split).lower()
    return {token for token in _NON_ALPHANUMERIC.split(snake_case) if token}


def _path_text(path: tuple[str, ...]) -> str:
    return ".".join(path) if path else "schema"


def _schema_dialect_violations(
    schema: object,
    prefix: tuple[str, ...] = (),
) -> Iterator[str]:
    if not isinstance(schema, dict):
        yield _path_text(prefix)
        return

    schema_type = schema.get("type")
    allowed_keywords = (
        _SCHEMA_KEYWORDS_BY_TYPE.get(schema_type)
        if isinstance(schema_type, str)
        else None
    )
    if allowed_keywords is None:
        yield _path_text((*prefix, "type"))
        allowed_keywords = _COMMON_SCHEMA_KEYWORDS

    for keyword in schema:
        if not isinstance(keyword, str) or keyword not in allowed_keywords:
            yield _path_text((*prefix, str(keyword)))

    if schema_type == "object":
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            yield _path_text((*prefix, "properties"))
        else:
            for name, child in properties.items():
                property_path = (*prefix, str(name))
                if not isinstance(name, str) or not isinstance(child, dict):
                    yield _path_text(property_path)
                else:
                    yield from _schema_dialect_violations(child, property_path)

        required = schema.get("required")
        if not isinstance(required, list) or any(
            not isinstance(name, str) for name in required
        ):
            yield _path_text((*prefix, "required"))

        if schema.get("additionalProperties") is not False:
            yield _path_text((*prefix, "additionalProperties"))
    elif schema_type == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            yield _path_text((*prefix, "items"))
        else:
            yield from _schema_dialect_violations(items, (*prefix, "items"))


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
    """Return unsafe dialect or content paths in a provider-visible schema."""
    tool_tokens = _field_tokens(tool_name)
    violations = list(_schema_dialect_violations(schema))

    for path in _property_paths(schema):
        field_name = path[-1]
        tokens = _field_tokens(field_name)
        is_row_count = "row" in tokens and "count" in tokens
        raw_customer_content = bool(tokens & {"address", "payload"}) or (
            "row" in tokens and not is_row_count
        )
        credential_or_token = (
            bool(
                tokens
                & {
                    "bearer",
                    "credential",
                    "credentials",
                    "password",
                    "secret",
                    "token",
                }
            )
            or {"api", "key"} <= tokens
            or {"access", "key"} <= tokens
            or (
                "header" in tokens
                and bool(
                    tokens
                    & {
                        "auth",
                        "authentication",
                        "authorization",
                        "authorisation",
                    }
                )
            )
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
                "href",
                "link",
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

    return list(dict.fromkeys(violations))
