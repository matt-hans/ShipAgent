"""Provider-visible registry privacy invariants."""

import re
from collections.abc import Iterator
from typing import Any

from src.registry.identifiers import provider_schema_identifier_violations

_ACRONYM_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")

_CUSTOMER_CONTENT_TOKENS = frozenset({"address", "payload"})
_CUSTOMER_ROW_TOKENS = frozenset({"row", "rows"})
_CREDENTIAL_TOKENS = frozenset(
    {"bearer", "credential", "credentials", "password", "secret", "token"}
)
_KEY_QUALIFIER_TOKENS = frozenset({"access", "api"})
_AUTH_HEADER_TOKENS = frozenset(
    {"auth", "authentication", "authorization", "authorisation"}
)
_TRANSFER_CONTENT_KINDS = frozenset({"document", "label"})
_TRANSFER_TOKENS = frozenset(
    {
        "base64",
        "bytes",
        "content",
        "data",
        "download",
        "href",
        "link",
        "payload",
        "uri",
        "url",
    }
)
_CARRIER_DIRECTIONS = frozenset({"request", "response"})
_CARRIER_CONTENT_TOKENS = frozenset({"body", "carrier", "data", "payload", "raw"})

# Compact aliases cannot be tokenized reliably (for example, XAPIKEY). Derive
# their fragments from the same privacy families used by the tokenized checks so
# new spellings do not need a hand-maintained alias allow/block list.
_FORBIDDEN_COMPACT_SINGLE_TOKEN_FRAGMENTS = (
    _CUSTOMER_CONTENT_TOKENS | _CREDENTIAL_TOKENS
)


def _bidirectional_compact_compounds(
    first_tokens: frozenset[str],
    second_tokens: frozenset[str],
) -> frozenset[str]:
    return frozenset(
        {
            compound
            for first in first_tokens
            for second in second_tokens
            for compound in (f"{first}{second}", f"{second}{first}")
        }
    )


_FORBIDDEN_COMPACT_COMPOUND_FRAGMENTS = frozenset().union(
    _bidirectional_compact_compounds(_KEY_QUALIFIER_TOKENS, frozenset({"key"})),
    _bidirectional_compact_compounds(_AUTH_HEADER_TOKENS, frozenset({"header"})),
    _bidirectional_compact_compounds(frozenset({"bearer"}), frozenset({"value"})),
    _bidirectional_compact_compounds(_TRANSFER_CONTENT_KINDS, _TRANSFER_TOKENS),
    _bidirectional_compact_compounds(_CARRIER_DIRECTIONS, _CARRIER_CONTENT_TOKENS),
    _bidirectional_compact_compounds(
        frozenset({"customer"}),
        _CUSTOMER_CONTENT_TOKENS | _CUSTOMER_ROW_TOKENS,
    ),
    _bidirectional_compact_compounds(
        frozenset({"confirmation"}), frozenset({"artifact", "token"})
    ),
    _bidirectional_compact_compounds(
        _CREDENTIAL_TOKENS & frozenset({"secret", "token"}),
        frozenset({"value"}),
    ),
)

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


def _compact_field_name(value: str) -> str:
    return _NON_ALPHANUMERIC.sub("", value.lower())


def _path_text(path: tuple[str, ...]) -> str:
    return ".".join(path) if path else "schema"


def _has_forbidden_compact_fragment(compact_name: str) -> bool:
    if compact_name == "confirmationartifactid":
        return False

    has_customer_row = compact_name.endswith(tuple(_CUSTOMER_ROW_TOKENS))
    return (
        has_customer_row
        or any(
            fragment in compact_name
            for fragment in _FORBIDDEN_COMPACT_SINGLE_TOKEN_FRAGMENTS
        )
        or any(
            fragment in compact_name
            for fragment in _FORBIDDEN_COMPACT_COMPOUND_FRAGMENTS
        )
    )


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
        if "maxItems" not in schema:
            yield _path_text(prefix)
        items = schema.get("items")
        if not isinstance(items, dict):
            yield _path_text((*prefix, "items"))
        else:
            yield from _schema_dialect_violations(items, (*prefix, "items"))
    elif schema_type == "string" and "enum" not in schema:
        if not {"pattern", "minLength", "maxLength"} <= schema.keys():
            yield _path_text(prefix)
    elif isinstance(schema_type, str) and schema_type in {"integer", "number"}:
        if not {"minimum", "maximum"} <= schema.keys():
            yield _path_text(prefix)


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
    violations = [
        *list(_schema_dialect_violations(schema)),
        *provider_schema_identifier_violations(schema),
    ]

    for path in _property_paths(schema):
        field_name = path[-1]
        tokens = _field_tokens(field_name)
        compact_name = _compact_field_name(field_name)
        is_row_count = "row" in tokens and "count" in tokens
        raw_customer_content = bool(tokens & _CUSTOMER_CONTENT_TOKENS) or (
            bool(tokens & _CUSTOMER_ROW_TOKENS) and not is_row_count
        )
        credential_or_token = (
            bool(tokens & _CREDENTIAL_TOKENS)
            or any({qualifier, "key"} <= tokens for qualifier in _KEY_QUALIFIER_TOKENS)
            or ("header" in tokens and bool(tokens & _AUTH_HEADER_TOKENS))
        )
        label_or_document_transfer = bool(
            (tokens | tool_tokens) & _TRANSFER_CONTENT_KINDS
        ) and bool(tokens & _TRANSFER_TOKENS)
        raw_carrier_exchange = bool(tokens & _CARRIER_DIRECTIONS) and bool(
            tokens & _CARRIER_CONTENT_TOKENS
        )
        if (
            raw_customer_content
            or credential_or_token
            or label_or_document_transfer
            or raw_carrier_exchange
            or _has_forbidden_compact_fragment(compact_name)
        ):
            violations.append(".".join(path))

    return list(dict.fromkeys(violations))
