"""Production readiness classification for hosted UPS MCP boundaries."""

from typing import Protocol

from src.hosted.ups_boundary.models import (
    UpsBoundaryCapabilityReport,
    UpsBoundaryReadiness,
    UpsBoundarySeverity,
)


class UpsBoundaryInspectable(Protocol):
    """Read-only adapter that can inspect hosted UPS boundary capabilities."""

    async def inspect_capabilities(self) -> UpsBoundaryCapabilityReport:
        """Return the hosted UPS boundary capability report."""


async def check_ups_mcp_boundary_readiness(
    adapter: UpsBoundaryInspectable,
) -> UpsBoundaryReadiness:
    """Classify hosted UPS MCP boundary readiness from an inspected report."""
    report = await adapter.inspect_capabilities()

    if not report.ready:
        status = "not_ready"
    elif any(check.severity == UpsBoundarySeverity.WARN for check in report.checks):
        status = "degraded"
    else:
        status = "ready"

    return UpsBoundaryReadiness(status=status, report=report)
