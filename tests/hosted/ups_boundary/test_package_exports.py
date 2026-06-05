"""Smoke tests for hosted UPS MCP boundary package imports."""

from src.hosted.ups_boundary.adapter import HostedUpsBoundaryAdapter
from src.hosted.ups_boundary.contract import evaluate_boundary_contract
from src.hosted.ups_boundary.fixtures import HOSTED_V1_SAFE_ERROR
from src.hosted.ups_boundary.readiness import check_ups_mcp_boundary_readiness
from src.hosted.ups_boundary.validators import validate_create_shipment_result


def test_boundary_package_imports_public_entrypoints() -> None:
    assert HostedUpsBoundaryAdapter is not None
    assert evaluate_boundary_contract is not None
    assert HOSTED_V1_SAFE_ERROR["success"] is False
    assert check_ups_mcp_boundary_readiness is not None
    assert validate_create_shipment_result is not None
