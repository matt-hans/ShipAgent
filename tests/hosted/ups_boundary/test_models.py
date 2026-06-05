"""Tests for hosted UPS MCP boundary DTOs."""

from datetime import datetime

from src.hosted.ups_boundary.models import (
    UpsBoundaryCapabilityReport,
    UpsBoundaryCheck,
    UpsBoundarySeverity,
    UpsBoundaryValidationResult,
)


def test_capability_report_ready_when_no_missing_requirements_or_error_checks():
    """Reports are ready when all requirements are present and checks are non-error."""
    report = UpsBoundaryCapabilityReport()

    assert report.ready is True
    assert isinstance(report.checked_at, datetime)


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
