"""Behavior-level test for interactive shipping mode.

Asserts observed runtime behavior: hook + mode routing + error translation
working together. Does NOT test prompt text — that's covered by unit tests.
"""

import json

import pytest

from src.orchestrator.agent.hooks import create_shipping_hook
from src.services.mcp_client import MCPToolError
from src.services.ups_mcp_client import UPSMCPClient


class TestInteractiveModeEndToEnd:
    """Behavior tests for interactive shipping mode flow."""

    @pytest.mark.asyncio
    async def test_interactive_on_denies_create_shipment_via_hook(self):
        """With interactive=True: hook denies create_shipment — must use preview tool."""
        hook = create_shipping_hook(interactive_shipping=True)
        hook_result = await hook(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {"request_body": {"Shipment": {}}},
            },
            "test-tool-id",
            None,
        )
        assert "deny" in str(hook_result)
        assert "preview_interactive_shipment" in str(hook_result)

    @pytest.mark.asyncio
    async def test_translate_error_still_produces_e2010_for_missing(self):
        """_translate_error converts missing[] ToolError to E-2010."""
        client = UPSMCPClient.__new__(UPSMCPClient)
        error = MCPToolError(tool_name="create_shipment", error_text=json.dumps({
            "code": "ELICITATION_UNSUPPORTED",
            "message": "Missing required shipment fields",
            "missing": [
                {"dot_path": "Shipment.Shipper.Name", "flat_key": "shipper_name", "prompt": "Shipper name"},
                {"dot_path": "Shipment.ShipTo.Name", "flat_key": "ship_to_name", "prompt": "Recipient name"},
            ],
        }))
        ups_error = client._translate_error(error)

        assert ups_error.code == "E-2010"
        assert "Shipper name" in ups_error.message
        assert "Recipient name" in ups_error.message
        assert "2" in ups_error.message  # count

    @pytest.mark.asyncio
    async def test_interactive_off_denies_create_shipment(self):
        """With interactive=False: hook denies before error translation runs."""
        hook = create_shipping_hook(interactive_shipping=False)
        hook_result = await hook(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {"request_body": {"Shipment": {}}},
            },
            "test-tool-id",
            None,
        )
        assert "deny" in str(hook_result)
        assert "Interactive shipping is disabled" in str(hook_result)

    @pytest.mark.asyncio
    async def test_batch_tools_unaffected_by_mode(self):
        """Batch tools (ship_command_pipeline etc.) work regardless of mode."""
        hook = create_shipping_hook(interactive_shipping=False)

        # rate_shipment is not gated
        result = await hook(
            {"tool_name": "mcp__ups__rate_shipment", "tool_input": {}},
            "test-id",
            None,
        )
        assert result == {}

        # track_package is not gated
        result = await hook(
            {"tool_name": "mcp__ups__track_package", "tool_input": {}},
            "test-id",
            None,
        )
        assert result == {}
