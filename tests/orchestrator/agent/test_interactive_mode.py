"""Behavior-level test for interactive shipping mode.

Asserts observed runtime behavior: policy + mode routing + error translation
working together. Does NOT test prompt text — that's covered by unit tests.
"""

import json

import pytest

from src.services.conversation_runtime.models import ProviderToolCall
from src.services.conversation_runtime.policy import RuntimePolicyEngine
from src.services.mcp_client import MCPToolError
from src.services.ups_mcp_client import UPSMCPClient


async def _check(policy, data, call_id):
    return await policy.check_pre_tool(ProviderToolCall(
        call_id=call_id, tool_name=data["tool_name"], parsed_input=data["tool_input"]
    ))


class TestInteractiveModeEndToEnd:
    """Behavior tests for interactive shipping mode flow."""

    @pytest.mark.asyncio
    async def test_interactive_on_denies_create_shipment_via_policy(self):
        """With interactive=True: policy denies create_shipment — must use preview tool."""
        hook = RuntimePolicyEngine(interactive_shipping=True)
        hook_result = await _check(hook,
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {"request_body": {"Shipment": {}}},
            },
            "test-tool-id",
        )
        assert hook_result.allowed is False
        assert "preview_interactive_shipment" in hook_result.reason

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
        """With interactive=False: policy denies before error translation runs."""
        hook = RuntimePolicyEngine(interactive_shipping=False)
        hook_result = await _check(hook,
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {"request_body": {"Shipment": {}}},
            },
            "test-tool-id",
        )
        assert hook_result.allowed is False
        assert "Interactive shipping is disabled" in hook_result.reason

    @pytest.mark.asyncio
    async def test_batch_tools_unaffected_by_mode(self):
        """Batch tools (ship_command_pipeline etc.) work regardless of mode."""
        hook = RuntimePolicyEngine(interactive_shipping=False)

        # rate_shipment is not gated
        result = await _check(hook,
            {"tool_name": "rate_shipment", "tool_input": {}},
            "test-id",
        )
        assert result.allowed is True

        # track_package is not gated
        result = await _check(hook,
            {"tool_name": "track_package", "tool_input": {}},
            "test-id",
        )
        assert result.allowed is True
