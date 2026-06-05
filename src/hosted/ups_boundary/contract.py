"""Hosted UPS MCP boundary contract evaluation."""

from collections.abc import Mapping
from typing import Any

from src.hosted.ups_boundary.models import (
    UpsBoundaryCapability,
    UpsBoundaryCapabilityReport,
    UpsBoundaryCheck,
    UpsBoundarySeverity,
)

REQUIRED_CONTRACT_VERSION = "hosted-v1"
REQUIRED_TOOLS = frozenset(
    {
        "rate_shipment",
        "validate_address",
        "create_shipment",
        "shipagent_capabilities",
    },
)
REQUIRED_RESPONSE_FORMATS = frozenset({"shipagent_v1"})

TOOL_CAPABILITY_HINTS = {
    "rate_shipment": frozenset(
        {
            UpsBoundaryCapability.RATE_QUOTE,
            UpsBoundaryCapability.RATE_SHOP,
        },
    ),
    "validate_address": frozenset({UpsBoundaryCapability.ADDRESS_VALIDATION}),
    "create_shipment": frozenset({UpsBoundaryCapability.CREATE_SHIPMENT}),
}

DECLARATION_ONLY_CAPABILITIES = frozenset(
    {
        UpsBoundaryCapability.IDEMPOTENCY_METADATA_PASSTHROUGH,
        UpsBoundaryCapability.SHIPMENT_RESPONSE_NORMALIZATION,
        UpsBoundaryCapability.INTERNATIONAL_CHARGES,
        UpsBoundaryCapability.SAFE_ERROR_MAPPING,
        UpsBoundaryCapability.MUTATING_RETRY_POLICY,
    },
)

REQUIRED_CAPABILITIES = (
    frozenset().union(*TOOL_CAPABILITY_HINTS.values()) | DECLARATION_ONLY_CAPABILITIES
)


def evaluate_boundary_contract(
    *,
    available_tools: set[str],
    declared_payload: Mapping[str, Any] | None,
) -> UpsBoundaryCapabilityReport:
    """Evaluate whether a hosted UPS MCP server satisfies ShipAgent requirements."""
    inferred_capabilities = _infer_tool_capabilities(available_tools)
    declared_capabilities = _parse_declared_capabilities(declared_payload)
    effective_capabilities = inferred_capabilities | declared_capabilities
    response_formats = _parse_response_formats(declared_payload)
    contract_version = _parse_contract_version(declared_payload)
    server_version = _parse_server_version(declared_payload)

    missing_tools = sorted(REQUIRED_TOOLS - available_tools)
    missing_capabilities = sorted(
        REQUIRED_CAPABILITIES - effective_capabilities,
        key=lambda capability: capability.value,
    )
    missing_response_formats = sorted(REQUIRED_RESPONSE_FORMATS - response_formats)

    checks = _build_checks(
        declared_payload=declared_payload,
        contract_version=contract_version,
        missing_tools=missing_tools,
        missing_capabilities=missing_capabilities,
        missing_response_formats=missing_response_formats,
    )

    return UpsBoundaryCapabilityReport(
        contract_version=contract_version,
        server_version=server_version,
        available_tools=set(available_tools),
        declared_capabilities=declared_capabilities,
        response_formats=response_formats,
        missing_tools=missing_tools,
        missing_capabilities=missing_capabilities,
        missing_response_formats=missing_response_formats,
        checks=checks,
    )


def _infer_tool_capabilities(available_tools: set[str]) -> set[UpsBoundaryCapability]:
    capabilities: set[UpsBoundaryCapability] = set()
    for tool_name in available_tools:
        capabilities.update(TOOL_CAPABILITY_HINTS.get(tool_name, frozenset()))
    return capabilities


def _parse_declared_capabilities(
    declared_payload: Mapping[str, Any] | None,
) -> set[UpsBoundaryCapability]:
    if declared_payload is None:
        return set()

    raw_capabilities = declared_payload.get("capabilities", [])
    if not isinstance(raw_capabilities, list):
        return set()

    capabilities: set[UpsBoundaryCapability] = set()
    for raw_capability in raw_capabilities:
        if not isinstance(raw_capability, str):
            continue
        try:
            capabilities.add(UpsBoundaryCapability(raw_capability))
        except ValueError:
            continue
    return capabilities


def _parse_response_formats(declared_payload: Mapping[str, Any] | None) -> set[str]:
    if declared_payload is None:
        return set()

    raw_formats = declared_payload.get("response_formats", [])
    if not isinstance(raw_formats, list):
        return set()

    return {raw_format for raw_format in raw_formats if isinstance(raw_format, str)}


def _parse_contract_version(declared_payload: Mapping[str, Any] | None) -> str:
    if declared_payload is None:
        return ""

    contract_version = declared_payload.get("contract_version")
    if isinstance(contract_version, str):
        return contract_version
    return ""


def _parse_server_version(declared_payload: Mapping[str, Any] | None) -> str | None:
    if declared_payload is None:
        return None

    server_version = declared_payload.get("server_version")
    if isinstance(server_version, str):
        return server_version
    return None


def _build_checks(
    *,
    declared_payload: Mapping[str, Any] | None,
    contract_version: str,
    missing_tools: list[str],
    missing_capabilities: list[UpsBoundaryCapability],
    missing_response_formats: list[str],
) -> list[UpsBoundaryCheck]:
    checks: list[UpsBoundaryCheck] = []

    if declared_payload is None:
        checks.append(
            UpsBoundaryCheck(
                name="shipagent_capabilities",
                severity=UpsBoundarySeverity.ERROR,
                message="Hosted UPS boundary did not provide ShipAgent capability metadata.",
            ),
        )

    if contract_version != REQUIRED_CONTRACT_VERSION:
        checks.append(
            UpsBoundaryCheck(
                name="contract_version",
                severity=UpsBoundarySeverity.ERROR,
                message="Hosted UPS boundary declared an unsupported contract version.",
            ),
        )

    if missing_tools:
        checks.append(
            UpsBoundaryCheck(
                name="required_tools",
                severity=UpsBoundarySeverity.ERROR,
                message="Hosted UPS boundary is missing required tools.",
            ),
        )

    if missing_capabilities:
        checks.append(
            UpsBoundaryCheck(
                name="required_capabilities",
                severity=UpsBoundarySeverity.ERROR,
                message="Hosted UPS boundary is missing required capabilities.",
            ),
        )

    if missing_response_formats:
        checks.append(
            UpsBoundaryCheck(
                name="required_response_formats",
                severity=UpsBoundarySeverity.ERROR,
                message="Hosted UPS boundary is missing required response formats.",
            ),
        )

    if not checks:
        checks.append(
            UpsBoundaryCheck(
                name="boundary_contract",
                severity=UpsBoundarySeverity.OK,
                message="Hosted UPS boundary contract is ready.",
            ),
        )

    return checks
