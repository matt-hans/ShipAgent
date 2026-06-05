"""Readiness adapter for hosted UPS MCP boundaries."""

from collections.abc import Mapping
from typing import Any, Protocol

from src.hosted.ups_boundary.contract import evaluate_boundary_contract
from src.hosted.ups_boundary.models import UpsBoundaryCapabilityReport


class UpsBoundaryClient(Protocol):
    """Read-only hosted UPS MCP boundary client used for readiness inspection."""

    async def list_tool_names(self) -> set[str]:
        """Return tool names exposed by the hosted UPS MCP server."""

    async def get_shipagent_capabilities(self) -> Mapping[str, Any] | None:
        """Return ShipAgent capability metadata exposed by the boundary."""


class HostedUpsBoundaryAdapter:
    """Readiness-only hosted UPS MCP boundary adapter."""

    def __init__(self, ups_client: UpsBoundaryClient) -> None:
        self._ups_client = ups_client

    async def inspect_capabilities(self) -> UpsBoundaryCapabilityReport:
        """Inspect hosted UPS MCP boundary readiness without calling operation tools."""
        available_tools = await self._ups_client.list_tool_names()
        declared_payload = await self._ups_client.get_shipagent_capabilities()
        return evaluate_boundary_contract(
            available_tools=available_tools,
            declared_payload=declared_payload,
        )
