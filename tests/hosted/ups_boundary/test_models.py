"""Tests for hosted UPS MCP boundary DTOs."""

from datetime import datetime

from src.hosted.ups_boundary.models import (
    UpsBoundaryCapability,
    UpsBoundaryCapabilityReport,
    UpsBoundaryCheck,
    UpsBoundarySeverity,
    UpsBoundaryValidationResult,
)


def test_capability_report_default_fails_closed():
    """Empty reports are not ready without positive contract evidence."""
    report = UpsBoundaryCapabilityReport()

    assert report.ready is False
    assert isinstance(report.checked_at, datetime)


def test_capability_report_ready_with_positive_contract_evidence():
    """Reports are ready when required evidence exists and checks are non-error."""
    report = UpsBoundaryCapabilityReport(
        available_tools={"rate_shipment"},
        declared_capabilities={UpsBoundaryCapability.RATE_QUOTE},
        response_formats={"shipagent_v1"},
        checks=[
            UpsBoundaryCheck(
                name="boundary_contract",
                severity=UpsBoundarySeverity.OK,
                message="Hosted UPS boundary contract is ready.",
            ),
        ],
    )

    assert report.ready is True


def test_capability_report_not_ready_with_missing_tools():
    """Missing required tools make the report not ready."""
    report = UpsBoundaryCapabilityReport(missing_tools=["rate_shipment"])

    assert report.ready is False


def test_capability_report_not_ready_with_missing_response_formats():
    """Missing required response formats make the report not ready."""
    report = UpsBoundaryCapabilityReport(
        missing_response_formats=["shipment_response_normalization"],
    )

    assert report.ready is False


def test_capability_report_not_ready_with_error_check():
    """Any error-severity check makes the report not ready."""
    report = UpsBoundaryCapabilityReport(
        checks=[
            UpsBoundaryCheck(
                name="response_normalization",
                severity=UpsBoundarySeverity.ERROR,
                message="Missing normalized shipment response.",
            ),
        ],
    )

    assert report.ready is False


def test_validation_result_serializes_without_raw_payload_fields():
    """Validation result serialization exposes only the public contract."""
    result = UpsBoundaryValidationResult(
        name="shipagent_capabilities",
        valid=False,
        error_code="missing_tool",
        message="Tool is not exposed.",
    )

    assert result.model_dump() == {
        "name": "shipagent_capabilities",
        "valid": False,
        "error_code": "missing_tool",
        "message": "Tool is not exposed.",
    }
