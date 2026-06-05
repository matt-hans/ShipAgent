"""Tests for hosted UPS MCP boundary readiness classification."""

from src.hosted.ups_boundary.models import (
    UpsBoundaryCapability,
    UpsBoundaryCapabilityReport,
    UpsBoundaryCheck,
    UpsBoundarySeverity,
)
from src.hosted.ups_boundary.readiness import check_ups_mcp_boundary_readiness


class FakeInspectableAdapter:
    def __init__(self, report: UpsBoundaryCapabilityReport) -> None:
        self.report = report

    async def inspect_capabilities(self) -> UpsBoundaryCapabilityReport:
        return self.report


def _report_with_positive_evidence(
    checks: list[UpsBoundaryCheck],
) -> UpsBoundaryCapabilityReport:
    return UpsBoundaryCapabilityReport(
        available_tools={"rate_shipment"},
        declared_capabilities={UpsBoundaryCapability.RATE_QUOTE},
        response_formats={"shipagent_v1"},
        checks=checks,
    )


async def test_check_ups_mcp_boundary_readiness_returns_ready_for_ready_report():
    adapter = FakeInspectableAdapter(
        _report_with_positive_evidence(
            checks=[
                UpsBoundaryCheck(
                    name="boundary_contract",
                    severity=UpsBoundarySeverity.OK,
                    message="Hosted UPS boundary contract is ready.",
                ),
            ],
        ),
    )

    readiness = await check_ups_mcp_boundary_readiness(adapter)

    assert readiness.status == "ready"
    assert readiness.production_ready is True
    assert readiness.report.ready is True


async def test_check_ups_mcp_boundary_readiness_returns_not_ready_when_missing_requirements():
    adapter = FakeInspectableAdapter(
        UpsBoundaryCapabilityReport(
            missing_tools=["create_shipment"],
            checks=[
                UpsBoundaryCheck(
                    name="required_tools",
                    severity=UpsBoundarySeverity.ERROR,
                    message="Hosted UPS boundary is missing required tools.",
                ),
            ],
        ),
    )

    readiness = await check_ups_mcp_boundary_readiness(adapter)

    assert readiness.status == "not_ready"
    assert readiness.production_ready is False


async def test_check_ups_mcp_boundary_readiness_returns_degraded_for_warn_only_checks():
    adapter = FakeInspectableAdapter(
        _report_with_positive_evidence(
            checks=[
                UpsBoundaryCheck(
                    name="boundary_contract",
                    severity=UpsBoundarySeverity.OK,
                    message="Hosted UPS boundary contract is ready.",
                ),
                UpsBoundaryCheck(
                    name="fixture_age",
                    severity=UpsBoundarySeverity.WARN,
                    message="Static fixture is older than expected.",
                ),
            ],
        ),
    )

    readiness = await check_ups_mcp_boundary_readiness(adapter)

    assert readiness.report.ready is True
    assert readiness.status == "degraded"
    assert readiness.production_ready is False
