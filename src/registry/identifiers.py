"""Canonical server-minted identifiers used in provider-visible contracts."""

import re
import secrets
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum

SHIPAGENT_ID_HEX_LENGTH = 32


class ShipAgentIdFamily(StrEnum):
    CORRELATION = "correlation"
    CONVERSATION = "conversation"
    AGENT_RUN = "agent_run"
    DEVICE = "device"
    INGRESS = "ingress"
    INPUT = "input"
    VALIDATION = "validation"
    PREVIEW = "preview"
    CONFIRMATION = "confirmation"
    APPROVAL_REQUEST = "approval_request"
    JOB = "job"
    LABEL = "label"


PROVIDER_VISIBLE_ID_FAMILIES = tuple(ShipAgentIdFamily)

PREVIEW_ID_FIELD = "preview_id"
APPROVAL_REQUEST_ID_FIELD = "approval_request_id"

PROVIDER_VISIBLE_FIELD_FAMILIES = {
    "correlation_id": ShipAgentIdFamily.CORRELATION,
    "conversation_reference": ShipAgentIdFamily.CONVERSATION,
    "run_reference": ShipAgentIdFamily.AGENT_RUN,
    "active_device_id": ShipAgentIdFamily.DEVICE,
    "ingress_reference": ShipAgentIdFamily.INGRESS,
    "input_reference": ShipAgentIdFamily.INPUT,
    "validation_artifact_id": ShipAgentIdFamily.VALIDATION,
    PREVIEW_ID_FIELD: ShipAgentIdFamily.PREVIEW,
    "confirmation_artifact_id": ShipAgentIdFamily.CONFIRMATION,
    APPROVAL_REQUEST_ID_FIELD: ShipAgentIdFamily.APPROVAL_REQUEST,
    "job_id": ShipAgentIdFamily.JOB,
    "label_artifact_id": ShipAgentIdFamily.LABEL,
}
_ACRONYM_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
_IDENTIFIER_SUFFIXES = {
    "id": ("id", False),
    "ids": ("id", True),
    "reference": ("reference", False),
    "references": ("reference", True),
}
# Compact names are intentionally fail-closed; list only established words whose
# spelling happens to end in an identifier suffix.
_NON_IDENTIFIER_COMPACT_FIELDS = frozenset({"valid"})
_COMPACT_FIELD_FAMILIES = {
    re.sub(r"[^a-z0-9]+", "", field_name.lower()): family
    for field_name, family in PROVIDER_VISIBLE_FIELD_FAMILIES.items()
}


@dataclass(frozen=True)
class ParsedShipAgentId:
    family: ShipAgentIdFamily
    hex_body: str


def _field_tokens(value: str) -> list[str]:
    acronym_split = _ACRONYM_BOUNDARY.sub("_", value)
    snake_case = _CAMEL_CASE_BOUNDARY.sub("_", acronym_split).lower()
    return [token for token in _NON_ALPHANUMERIC.split(snake_case) if token]


def _identifier_field_shape(value: str) -> tuple[str, bool] | None:
    tokens = _field_tokens(value)
    if not tokens:
        return None
    suffix = _IDENTIFIER_SUFFIXES.get(tokens[-1])
    if (
        suffix is None
        and len(tokens) == 1
        and tokens[0] not in _NON_IDENTIFIER_COMPACT_FIELDS
    ):
        compact_name = tokens[0]
        for compact_suffix in sorted(_IDENTIFIER_SUFFIXES, key=len, reverse=True):
            if compact_name.endswith(compact_suffix) and compact_name != compact_suffix:
                suffix = _IDENTIFIER_SUFFIXES[compact_suffix]
                tokens = [compact_name.removesuffix(compact_suffix), compact_suffix]
                break
    if suffix is None:
        return None
    singular_suffix, plural = suffix
    return ("".join((*tokens[:-1], singular_suffix)), plural)


def shipagent_id_prefix(family: ShipAgentIdFamily) -> str:
    return f"sa_{family.value}_"


def shipagent_id_pattern(family: ShipAgentIdFamily) -> str:
    return (
        rf"^{re.escape(shipagent_id_prefix(family))}"
        rf"[0-9a-f]{{{SHIPAGENT_ID_HEX_LENGTH}}}$"
    )


def shipagent_id_schema(
    family: ShipAgentIdFamily,
    description: str,
) -> dict[str, object]:
    """Return the exact JSON Schema for one provider-visible ID family."""
    exact_length = len(shipagent_id_prefix(family)) + SHIPAGENT_ID_HEX_LENGTH
    return {
        "type": "string",
        "description": description,
        "pattern": shipagent_id_pattern(family),
        "minLength": exact_length,
        "maxLength": exact_length,
    }


def provider_schema_identifier_violations(
    schema: object,
    prefix: tuple[str, ...] = (),
) -> list[str]:
    """Return provider ID/reference paths that do not use a registered schema."""

    def visit(value: object, path: tuple[str, ...]) -> Iterator[str]:
        if not isinstance(value, Mapping):
            return
        if value.get("type") == "object":
            properties = value.get("properties")
            if isinstance(properties, Mapping):
                for raw_name, child in properties.items():
                    name = str(raw_name)
                    child_path = (*path, name)
                    compact_name = re.sub(r"[^a-z0-9]+", "", name.lower())
                    identifier_shape = _identifier_field_shape(name)
                    if (
                        identifier_shape is not None
                        or compact_name in _COMPACT_FIELD_FAMILIES
                    ):
                        normalized_name, plural = identifier_shape or (
                            compact_name,
                            False,
                        )
                        family = _COMPACT_FIELD_FAMILIES.get(normalized_name)
                        if family is None or not _uses_exact_id_schema(
                            child,
                            family,
                            plural=plural,
                        ):
                            yield ".".join(child_path)
                    yield from visit(child, child_path)
        elif value.get("type") == "array":
            yield from visit(value.get("items"), path)

    return list(visit(schema, prefix))


def _uses_exact_id_schema(
    schema: object,
    family: ShipAgentIdFamily,
    *,
    plural: bool = False,
) -> bool:
    if not isinstance(schema, Mapping):
        return False
    if plural:
        if schema.get("type") != "array":
            return False
        schema = schema.get("items")
        if not isinstance(schema, Mapping):
            return False
    prefix = shipagent_id_prefix(family)
    exact_length = len(prefix) + SHIPAGENT_ID_HEX_LENGTH
    return (
        schema.get("type") == "string"
        and schema.get("pattern") == shipagent_id_pattern(family)
        and schema.get("minLength") == exact_length
        and schema.get("maxLength") == exact_length
    )


def mint_shipagent_id(family: ShipAgentIdFamily) -> str:
    """Mint a cryptographically random canonical identifier for ``family``."""
    return f"{shipagent_id_prefix(family)}{secrets.token_hex(16)}"


def parse_shipagent_id(
    identifier: str,
    *,
    expected_family: ShipAgentIdFamily | None = None,
) -> ParsedShipAgentId:
    """Parse an exact canonical ShipAgent identifier or raise ``ValueError``."""
    families = (
        (expected_family,)
        if expected_family is not None
        else PROVIDER_VISIBLE_ID_FAMILIES
    )
    for family in families:
        if re.fullmatch(shipagent_id_pattern(family), identifier):
            return ParsedShipAgentId(
                family=family,
                hex_body=identifier.removeprefix(shipagent_id_prefix(family)),
            )
    raise ValueError("identifier is not a canonical provider-visible ShipAgent ID")
