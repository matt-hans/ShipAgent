"""Tests for hosted UPS MCP boundary adapter readiness inspection."""

from src.hosted.ups_boundary.adapter import HostedUpsBoundaryAdapter
from src.hosted.ups_boundary.contract import REQUIRED_CAPABILITIES, REQUIRED_TOOLS
from src.hosted.ups_boundary.models import UpsBoundaryCapability


class FakeUpsBoundaryClient:
    def __init__(self, payload):
        self.payload = payload
        self.list_tool_names_called = False
        self.get_shipagent_capabilities_called = False

    async def list_tool_names(self) -> set[str]:
        self.list_tool_names_called = True
        return set(REQUIRED_TOOLS)

    async def get_shipagent_capabilities(self):
        self.get_shipagent_capabilities_called = True
        return self.payload


def _required_payload():
    return {
        "contract_version": "hosted-v1",
        "server_version": "2026.6.4",
        "capabilities": [capability.value for capability in REQUIRED_CAPABILITIES],
        "response_formats": ["shipagent_v1"],
    }


async def test_adapter_inspects_tool_names_and_declared_capabilities():
    """The adapter evaluates an injected UPS boundary client for readiness."""
    client = FakeUpsBoundaryClient(_required_payload())
    adapter = HostedUpsBoundaryAdapter(client)

    report = await adapter.inspect_capabilities()

    assert client.list_tool_names_called is True
    assert client.get_shipagent_capabilities_called is True
    assert report.ready is True
    assert report.server_version == "2026.6.4"
    assert REQUIRED_CAPABILITIES <= report.declared_capabilities


async def test_adapter_fails_closed_when_capability_metadata_absent():
    """Tool presence alone is not enough without declaration-only metadata."""
    client = FakeUpsBoundaryClient(None)
    adapter = HostedUpsBoundaryAdapter(client)

    report = await adapter.inspect_capabilities()

    assert report.ready is False
    assert report.server_version is None
    assert report.missing_tools == []
    assert UpsBoundaryCapability.IDEMPOTENCY_METADATA_PASSTHROUGH in (
        report.missing_capabilities
    )
