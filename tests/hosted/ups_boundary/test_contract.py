"""Tests for hosted UPS MCP boundary contract evaluation."""

from src.hosted.ups_boundary.contract import (
    DECLARATION_ONLY_CAPABILITIES,
    REQUIRED_CAPABILITIES,
    REQUIRED_CONTRACT_VERSION,
    REQUIRED_RESPONSE_FORMATS,
    REQUIRED_TOOLS,
    evaluate_boundary_contract,
)
from src.hosted.ups_boundary.models import (
    UpsBoundaryCapability,
    UpsBoundarySeverity,
)


def _required_payload(**overrides):
    payload = {
        "contract_version": "hosted-v1",
        "server_version": "2026.6.4",
        "capabilities": [capability.value for capability in REQUIRED_CAPABILITIES],
        "response_formats": ["shipagent_v1"],
    }
    payload.update(overrides)
    return payload


def _required_tools() -> set[str]:
    return set(REQUIRED_TOOLS)


def test_required_contract_constants():
    """Contract constants describe the hosted UPS boundary requirements."""
    assert REQUIRED_CONTRACT_VERSION == "hosted-v1"
    assert REQUIRED_TOOLS == frozenset(
        {
            "rate_shipment",
            "validate_address",
            "create_shipment",
            "shipagent_capabilities",
        },
    )
    assert {
        UpsBoundaryCapability.RATE_SHOP,
        UpsBoundaryCapability.IDEMPOTENCY_METADATA_PASSTHROUGH,
        UpsBoundaryCapability.INTERNATIONAL_CHARGES,
    } <= REQUIRED_CAPABILITIES
    assert REQUIRED_RESPONSE_FORMATS == frozenset({"shipagent_v1"})


def test_evaluate_boundary_contract_ready_with_required_boundary_declarations():
    """A boundary with required tools and declarations is ready."""
    report = evaluate_boundary_contract(
        available_tools=_required_tools(),
        declared_payload=_required_payload(),
    )

    assert report.ready is True
    assert report.contract_version == "hosted-v1"
    assert report.server_version == "2026.6.4"
    assert report.available_tools == REQUIRED_TOOLS
    assert REQUIRED_CAPABILITIES <= report.declared_capabilities
    assert "shipagent_v1" in report.response_formats
    assert [check.name for check in report.checks] == ["boundary_contract"]
    assert report.checks[0].severity == UpsBoundarySeverity.OK


def test_evaluate_boundary_contract_wrong_contract_version_fails():
    """A non-hosted-v1 contract version fails readiness."""
    report = evaluate_boundary_contract(
        available_tools=_required_tools(),
        declared_payload=_required_payload(contract_version="hosted-v0"),
    )

    assert report.ready is False
    assert report.contract_version == "hosted-v0"
    assert any(
        check.name == "contract_version" and check.severity == UpsBoundarySeverity.ERROR
        for check in report.checks
    )


def test_evaluate_boundary_contract_missing_contract_version_fails():
    """The hosted boundary must explicitly declare the contract version."""
    payload = _required_payload()
    del payload["contract_version"]

    report = evaluate_boundary_contract(
        available_tools=_required_tools(),
        declared_payload=payload,
    )

    assert report.ready is False
    assert any(
        check.name == "contract_version" and check.severity == UpsBoundarySeverity.ERROR
        for check in report.checks
    )


def test_evaluate_boundary_contract_non_string_contract_version_fails():
    """A non-string contract version is not accepted as hosted-v1."""
    report = evaluate_boundary_contract(
        available_tools=_required_tools(),
        declared_payload=_required_payload(contract_version=1),
    )

    assert report.ready is False
    assert any(
        check.name == "contract_version" and check.severity == UpsBoundarySeverity.ERROR
        for check in report.checks
    )


def test_evaluate_boundary_contract_missing_create_shipment_tool_fails():
    """Missing required operation tools are reported in sorted order."""
    report = evaluate_boundary_contract(
        available_tools=REQUIRED_TOOLS - {"create_shipment"},
        declared_payload=_required_payload(),
    )

    assert report.ready is False
    assert report.missing_tools == ["create_shipment"]
    assert any(
        check.name == "required_tools" and check.severity == UpsBoundarySeverity.ERROR
        for check in report.checks
    )


def test_evaluate_boundary_contract_absent_payload_fails_closed():
    """Absent capability metadata fails closed without raw payload exposure."""
    report = evaluate_boundary_contract(
        available_tools=_required_tools(),
        declared_payload=None,
    )

    assert report.ready is False
    assert UpsBoundaryCapability.IDEMPOTENCY_METADATA_PASSTHROUGH in (
        report.missing_capabilities
    )
    assert report.missing_response_formats == ["shipagent_v1"]
    assert any(
        check.name == "shipagent_capabilities"
        and check.severity == UpsBoundarySeverity.ERROR
        for check in report.checks
    )
    assert all("None" not in check.message for check in report.checks)


def test_evaluate_boundary_contract_missing_shipagent_v1_format_fails():
    """The normalized ShipAgent response format is mandatory."""
    report = evaluate_boundary_contract(
        available_tools=_required_tools(),
        declared_payload=_required_payload(response_formats=["legacy_v1"]),
    )

    assert report.ready is False
    assert report.response_formats == {"legacy_v1"}
    assert report.missing_response_formats == ["shipagent_v1"]
    assert any(
        check.name == "required_response_formats"
        and check.severity == UpsBoundarySeverity.ERROR
        for check in report.checks
    )


def test_evaluate_boundary_contract_ignores_unknown_capabilities_and_preserves_formats():
    """Unknown extension declarations do not make an otherwise ready report fail."""
    report = evaluate_boundary_contract(
        available_tools=_required_tools(),
        declared_payload=_required_payload(
            capabilities=[
                *(capability.value for capability in REQUIRED_CAPABILITIES),
                "future_capability",
            ],
            response_formats=["shipagent_v1", "future_format"],
        ),
    )

    assert report.ready is True
    assert "future_capability" not in report.declared_capabilities
    assert report.response_formats == {"shipagent_v1", "future_format"}


def test_evaluate_boundary_contract_reports_only_declared_capabilities():
    """Inferred tool capabilities may satisfy readiness without being reported as declared."""
    report = evaluate_boundary_contract(
        available_tools=_required_tools(),
        declared_payload=_required_payload(
            capabilities=[
                capability.value for capability in DECLARATION_ONLY_CAPABILITIES
            ],
        ),
    )

    assert report.ready is True
    assert report.missing_capabilities == []
    assert report.declared_capabilities == DECLARATION_ONLY_CAPABILITIES
    assert UpsBoundaryCapability.RATE_QUOTE not in report.declared_capabilities
    assert UpsBoundaryCapability.RATE_SHOP not in report.declared_capabilities
