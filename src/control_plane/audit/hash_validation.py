"""Reuse canonical IDs and hashes; validation errors never echo supplied data."""

from src.control_plane.audit.service import ControlPlaneAuditService
from src.registry.identifiers import ShipAgentIdFamily, parse_shipagent_id


def require_sha256_hex(value: str) -> str:
    return ControlPlaneAuditService._validate_hash_value(value)


def require_account_id(value: str) -> str:
    return ControlPlaneAuditService._validate_id_value(
        value, key="account_id", max_length=36
    )


def require_connection_id(value: str) -> str:
    return ControlPlaneAuditService._validate_id_value(
        value, key="provider_connection_id", max_length=36
    )


def require_reference(value: str, family: ShipAgentIdFamily) -> str:
    try:
        parse_shipagent_id(value, expected_family=family)
    except (TypeError, ValueError):
        raise ValueError("invalid canonical reference") from None
    return value
