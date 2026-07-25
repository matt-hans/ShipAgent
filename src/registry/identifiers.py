"""Canonical server-minted identifiers used in provider-visible contracts."""

import re
import secrets
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum

SHIPAGENT_ID_HEX_LENGTH = 32


class ShipAgentIdFamily(StrEnum):
    CORRELATION = "correlation"
    DEVICE = "device"
    INGRESS = "ingress"
    INPUT = "input"
    VALIDATION = "validation"
    PREVIEW = "preview"
    CONFIRMATION = "confirmation"
    JOB = "job"
    LABEL = "label"


PROVIDER_VISIBLE_ID_FAMILIES = tuple(ShipAgentIdFamily)

PROVIDER_VISIBLE_FIELD_FAMILIES = {
    "correlation_id": ShipAgentIdFamily.CORRELATION,
    "active_device_id": ShipAgentIdFamily.DEVICE,
    "ingress_reference": ShipAgentIdFamily.INGRESS,
    "input_reference": ShipAgentIdFamily.INPUT,
    "validation_artifact_id": ShipAgentIdFamily.VALIDATION,
    "preview_id": ShipAgentIdFamily.PREVIEW,
    "confirmation_artifact_id": ShipAgentIdFamily.CONFIRMATION,
    "job_id": ShipAgentIdFamily.JOB,
    "label_artifact_id": ShipAgentIdFamily.LABEL,
}
_COMPACT_FIELD_FAMILIES = {
    re.sub(r"[^a-z0-9]+", "", field_name.lower()): family
    for field_name, family in PROVIDER_VISIBLE_FIELD_FAMILIES.items()
}


@dataclass(frozen=True)
class ParsedShipAgentId:
    family: ShipAgentIdFamily
    hex_body: str


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
                    looks_like_identifier = (
                        name.lower().endswith(("_id", "_reference"))
                        or compact_name in _COMPACT_FIELD_FAMILIES
                    )
                    if looks_like_identifier:
                        family = _COMPACT_FIELD_FAMILIES.get(compact_name)
                        if family is None or not _uses_exact_id_schema(child, family):
                            yield ".".join(child_path)
                    yield from visit(child, child_path)
        elif value.get("type") == "array":
            yield from visit(value.get("items"), path)

    return list(visit(schema, prefix))


def _uses_exact_id_schema(
    schema: object,
    family: ShipAgentIdFamily,
) -> bool:
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
