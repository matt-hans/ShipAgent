"""Unit tests for src/orchestrator/agent/hooks.py.

Tests verify:
- Pre-tool hooks validate inputs and can deny operations
- Post-tool hooks log executions
- Hook matchers are correctly configured
"""

import pytest

from src.orchestrator.agent.hooks import (
    validate_pre_tool,
    validate_shipping_input,
    validate_void_shipment,
    validate_data_query,
    log_post_tool,
    detect_error_response,
    create_hook_matchers,
)


class TestValidateShippingInput:
    """Tests for UPS shipping input validation hook.

    Business-field checks are now delegated to UPS MCP preflight.
    The hook only guards structural integrity (tool_input must be a dict).
    """

    @pytest.mark.asyncio
    async def test_allows_partial_payload_missing_shipper(self):
        """Should allow create_shipment without shipper (MCP preflight handles it)."""
        result = await validate_shipping_input(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {"shipTo": {"name": "Test", "addressLine1": "123 Main St"}}
            },
            "test-id",
            None
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_allows_partial_payload_missing_shipto(self):
        """Should allow create_shipment without shipTo (MCP preflight handles it)."""
        result = await validate_shipping_input(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {"shipper": {"name": "Test", "addressLine1": "123 Main St"}}
            },
            "test-id",
            None
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_allows_partial_payload_missing_shipper_name(self):
        """Should allow create_shipment without shipper name (MCP preflight handles it)."""
        result = await validate_shipping_input(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {
                    "shipper": {"addressLine1": "123 Main St"},
                    "shipTo": {"name": "Receiver", "addressLine1": "456 Oak Ave"}
                }
            },
            "test-id",
            None
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_allows_partial_payload_missing_shipper_address(self):
        """Should allow create_shipment without shipper address."""
        result = await validate_shipping_input(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {
                    "shipper": {"name": "Sender"},
                    "shipTo": {"name": "Receiver", "addressLine1": "456 Oak Ave"}
                }
            },
            "test-id",
            None
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_allows_partial_payload_missing_shipto_name(self):
        """Should allow create_shipment without shipTo name."""
        result = await validate_shipping_input(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {
                    "shipper": {"name": "Sender", "addressLine1": "123 Main St"},
                    "shipTo": {"addressLine1": "456 Oak Ave"}
                }
            },
            "test-id",
            None
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_allows_partial_payload_missing_shipto_address(self):
        """Should allow create_shipment without shipTo address."""
        result = await validate_shipping_input(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {
                    "shipper": {"name": "Sender", "addressLine1": "123 Main St"},
                    "shipTo": {"name": "Receiver"}
                }
            },
            "test-id",
            None
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_allows_valid_shipping_input(self):
        """Should allow shipping_create with all required fields."""
        result = await validate_shipping_input(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {
                    "shipper": {"name": "Sender", "addressLine1": "123 Main St"},
                    "shipTo": {"name": "Receiver", "addressLine1": "456 Oak Ave"}
                }
            },
            "test-id",
            None
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_allows_empty_dict(self):
        """Should allow create_shipment with empty dict (MCP preflight handles it)."""
        result = await validate_shipping_input(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {}
            },
            "test-id",
            None
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_allows_partial_shipment_request(self):
        """Should allow create_shipment with partial ShipmentRequest structure."""
        result = await validate_shipping_input(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {"ShipmentRequest": {}}
            },
            "test-id",
            None
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_denies_none_tool_input(self):
        """Should deny create_shipment when tool_input is None."""
        result = await validate_shipping_input(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": None
            },
            "test-id",
            None
        )
        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"

    @pytest.mark.asyncio
    async def test_denies_string_tool_input(self):
        """Should deny create_shipment when tool_input is a string."""
        result = await validate_shipping_input(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": "not a dict"
            },
            "test-id",
            None
        )
        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"

    @pytest.mark.asyncio
    async def test_denies_list_tool_input(self):
        """Should deny create_shipment when tool_input is a list."""
        result = await validate_shipping_input(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": [1, 2, 3]
            },
            "test-id",
            None
        )
        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"

    @pytest.mark.asyncio
    async def test_allows_non_shipping_tools(self):
        """Should allow tools that aren't create_shipment."""
        result = await validate_shipping_input(
            {
                "tool_name": "mcp__ups__rate_shipment",
                "tool_input": {}
            },
            "test-id",
            None
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_allows_data_tools(self):
        """Should allow data MCP tools."""
        result = await validate_shipping_input(
            {
                "tool_name": "mcp__data__import_csv",
                "tool_input": {"path": "orders.csv"}
            },
            "test-id",
            None
        )
        assert result == {}


class TestValidateVoidShipment:
    """Tests for UPS void_shipment input validation hook."""

    @pytest.mark.asyncio
    async def test_denies_missing_tracking_number(self):
        """Should deny void_shipment without tracking number."""
        result = await validate_void_shipment(
            {
                "tool_name": "mcp__ups__void_shipment",
                "tool_input": {}
            },
            "test-id",
            None
        )

        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "shipment" in result["hookSpecificOutput"]["permissionDecisionReason"].lower()

    @pytest.mark.asyncio
    async def test_allows_with_tracking_number(self):
        """Should allow void_shipment with trackingNumber."""
        result = await validate_void_shipment(
            {
                "tool_name": "mcp__ups__void_shipment",
                "tool_input": {"trackingNumber": "1Z999AA10123456784"}
            },
            "test-id",
            None
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_allows_with_shipment_id(self):
        """Should allow void_shipment with ShipmentIdentificationNumber."""
        result = await validate_void_shipment(
            {
                "tool_name": "mcp__ups__void_shipment",
                "tool_input": {"ShipmentIdentificationNumber": "1Z999AA10123456784"}
            },
            "test-id",
            None
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_allows_non_void_tools(self):
        """Should allow tools that aren't void_shipment."""
        result = await validate_void_shipment(
            {
                "tool_name": "mcp__ups__rate_shipment",
                "tool_input": {}
            },
            "test-id",
            None
        )

        assert result == {}


class TestValidateDataQuery:
    """Tests for data query validation hook."""

    @pytest.mark.asyncio
    async def test_allows_query_with_where(self):
        """Should allow queries with WHERE clause."""
        result = await validate_data_query(
            {
                "tool_name": "mcp__data__query_data",
                "tool_input": {"query": "SELECT * FROM orders WHERE state = 'CA'"}
            },
            "test-id",
            None
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_allows_query_without_where(self):
        """Should allow queries without WHERE (just warns)."""
        result = await validate_data_query(
            {
                "tool_name": "mcp__data__query_data",
                "tool_input": {"query": "SELECT * FROM orders"}
            },
            "test-id",
            None
        )

        # Hook is informational only - returns empty dict
        assert result == {}

    @pytest.mark.asyncio
    async def test_allows_non_query_tools(self):
        """Should allow non-query data tools."""
        result = await validate_data_query(
            {
                "tool_name": "mcp__data__import_csv",
                "tool_input": {"path": "test.csv"}
            },
            "test-id",
            None
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_warns_on_dangerous_keywords(self, capsys):
        """Should warn about dangerous SQL keywords."""
        result = await validate_data_query(
            {
                "tool_name": "mcp__data__query_data",
                "tool_input": {"query": "DELETE FROM orders"}
            },
            "test-id",
            None
        )

        # Returns empty dict (informational warning only)
        assert result == {}


class TestValidatePreTool:
    """Tests for generic pre-tool validation."""

    @pytest.mark.asyncio
    async def test_routes_to_shipping_validator(self):
        """Should route shipping_create to validate_shipping_input.

        Partial payloads (e.g. missing shipper) are allowed because
        business-field validation is delegated to UPS MCP preflight.
        """
        result = await validate_pre_tool(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {"shipTo": {"name": "Test"}}
            },
            "test-id",
            None
        )

        # Should allow — MCP preflight handles missing-field validation
        assert result == {}

    @pytest.mark.asyncio
    async def test_routes_to_void_shipment_validator(self):
        """Should route void_shipment to validate_void_shipment."""
        result = await validate_pre_tool(
            {
                "tool_name": "mcp__ups__void_shipment",
                "tool_input": {}
            },
            "test-id",
            None
        )

        # Should deny (missing tracking number)
        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"

    @pytest.mark.asyncio
    async def test_routes_to_data_query_validator(self):
        """Should route query_data to validate_data_query."""
        result = await validate_pre_tool(
            {
                "tool_name": "mcp__data__query_data",
                "tool_input": {"query": "SELECT * FROM orders"}
            },
            "test-id",
            None
        )

        # Should allow (data query validator is informational)
        assert result == {}

    @pytest.mark.asyncio
    async def test_allows_other_tools(self):
        """Should allow tools that don't match specific validators."""
        result = await validate_pre_tool(
            {"tool_name": "mcp__data__get_schema", "tool_input": {}},
            "test-id",
            None
        )

        assert result == {}


class TestLogPostTool:
    """Tests for post-tool logging hook."""

    @pytest.mark.asyncio
    async def test_returns_empty_dict(self):
        """Post-hook should return empty dict (no flow modification)."""
        result = await log_post_tool(
            {
                "tool_name": "mcp__data__get_schema",
                "tool_response": {"columns": ["id", "name"]}
            },
            "test-id",
            None
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_handles_error_response(self):
        """Should handle error responses without crashing."""
        result = await log_post_tool(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_response": {"error": "API error"}
            },
            "test-id",
            None
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_handles_none_response(self):
        """Should handle None responses."""
        result = await log_post_tool(
            {
                "tool_name": "mcp__data__import_csv",
                "tool_response": None
            },
            "test-id",
            None
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_handles_successful_response(self):
        """Should handle successful responses."""
        result = await log_post_tool(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_response": {
                    "trackingNumber": "1Z999AA10123456784",
                    "status": "success"
                }
            },
            "test-id",
            None
        )

        assert result == {}


class TestDetectErrorResponse:
    """Tests for error detection hook."""

    @pytest.mark.asyncio
    async def test_detects_error_key(self):
        """Should detect responses with error key."""
        result = await detect_error_response(
            {
                "tool_name": "test_tool",
                "tool_response": {"error": "Something went wrong"}
            },
            "test-id",
            None
        )

        # Hook should return empty dict but log warning
        assert result == {}

    @pytest.mark.asyncio
    async def test_detects_is_error_flag(self):
        """Should detect responses with isError=True."""
        result = await detect_error_response(
            {
                "tool_name": "test_tool",
                "tool_response": {"isError": True, "message": "Failed"}
            },
            "test-id",
            None
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_detects_http_error_status(self):
        """Should detect HTTP error status codes."""
        result = await detect_error_response(
            {
                "tool_name": "test_tool",
                "tool_response": {"status": 500, "message": "Internal error"}
            },
            "test-id",
            None
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_detects_status_code_400(self):
        """Should detect statusCode 400 error."""
        result = await detect_error_response(
            {
                "tool_name": "test_tool",
                "tool_response": {"statusCode": 400, "message": "Bad request"}
            },
            "test-id",
            None
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_handles_success_response(self):
        """Should handle successful responses."""
        result = await detect_error_response(
            {
                "tool_name": "test_tool",
                "tool_response": {"data": [1, 2, 3]}
            },
            "test-id",
            None
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_handles_none_response(self):
        """Should handle None responses."""
        result = await detect_error_response(
            {
                "tool_name": "test_tool",
                "tool_response": None
            },
            "test-id",
            None
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_handles_string_response_with_error(self):
        """Should detect error in string response."""
        result = await detect_error_response(
            {
                "tool_name": "test_tool",
                "tool_response": 'Error: Connection failed'
            },
            "test-id",
            None
        )

        assert result == {}


class TestCreateHookMatchers:
    """Tests for hook matcher configuration factory."""

    def test_returns_pretooluse_hooks(self):
        """Should include PreToolUse hook configuration."""
        matchers = create_hook_matchers()
        assert "PreToolUse" in matchers
        assert len(matchers["PreToolUse"]) >= 1

    def test_returns_posttooluse_hooks(self):
        """Should include PostToolUse hook configuration."""
        matchers = create_hook_matchers()
        assert "PostToolUse" in matchers
        assert len(matchers["PostToolUse"]) >= 1

    def test_pretooluse_has_create_shipment_matcher(self):
        """PreToolUse should have matcher for UPS create_shipment tool."""
        matchers = create_hook_matchers()
        shipment_matchers = [
            m for m in matchers["PreToolUse"]
            if m.matcher and "create_shipment" in m.matcher
        ]
        assert len(shipment_matchers) >= 1

    def test_pretooluse_has_void_shipment_matcher(self):
        """PreToolUse should have matcher for UPS void_shipment tool."""
        matchers = create_hook_matchers()
        void_matchers = [
            m for m in matchers["PreToolUse"]
            if m.matcher and "void_shipment" in m.matcher
        ]
        assert len(void_matchers) >= 1

    def test_pretooluse_has_query_matcher(self):
        """PreToolUse should have matcher for data query tools."""
        matchers = create_hook_matchers()
        query_matchers = [
            m for m in matchers["PreToolUse"]
            if m.matcher and "query" in m.matcher
        ]
        assert len(query_matchers) >= 1

    def test_posttooluse_applies_to_all(self):
        """PostToolUse should have matcher for all tools (None)."""
        matchers = create_hook_matchers()
        all_tool_matchers = [
            m for m in matchers["PostToolUse"]
            if m.matcher is None
        ]
        assert len(all_tool_matchers) >= 1

    def test_pretooluse_has_fallback(self):
        """PreToolUse should have fallback matcher (None) for all tools."""
        matchers = create_hook_matchers()
        fallback_matchers = [
            m for m in matchers["PreToolUse"]
            if m.matcher is None
        ]
        assert len(fallback_matchers) >= 1

    def test_each_matcher_has_hooks(self):
        """Each matcher should have hooks list."""
        matchers = create_hook_matchers()
        for event_type in ["PreToolUse", "PostToolUse"]:
            for matcher in matchers[event_type]:
                assert isinstance(matcher.hooks, list)
                assert len(matcher.hooks) >= 1

    def test_hooks_are_callable(self):
        """All hooks should be callable functions."""
        matchers = create_hook_matchers()
        for event_type in ["PreToolUse", "PostToolUse"]:
            for matcher in matchers[event_type]:
                for hook in matcher.hooks:
                    assert callable(hook)

    def test_accepts_interactive_shipping_parameter(self):
        """create_hook_matchers accepts interactive_shipping kwarg."""
        matchers = create_hook_matchers(interactive_shipping=True)
        assert "PreToolUse" in matchers
        assert "PostToolUse" in matchers

    def test_default_interactive_shipping_is_false(self):
        """create_hook_matchers defaults interactive_shipping to False."""
        # Should work without args (backward compatible)
        matchers = create_hook_matchers()
        assert "PreToolUse" in matchers


class TestInteractiveShippingHookEnforcement:
    """Tests for deterministic create_shipment gating by interactive_shipping."""

    @pytest.mark.asyncio
    async def test_create_shipment_denied_when_interactive_off(self):
        """create_shipment is deterministically blocked when interactive=False."""
        from src.orchestrator.agent.hooks import create_shipping_hook

        hook = create_shipping_hook(interactive_shipping=False)
        result = await hook(
            {"tool_name": "mcp__ups__create_shipment", "tool_input": {"request_body": {}}},
            "test-id",
            None,
        )
        assert "deny" in str(result)
        assert "Interactive shipping is disabled" in str(result)

    @pytest.mark.asyncio
    async def test_create_shipment_allowed_when_interactive_on(self):
        """create_shipment allowed (structural guard only) when interactive=True."""
        from src.orchestrator.agent.hooks import create_shipping_hook

        hook = create_shipping_hook(interactive_shipping=True)
        result = await hook(
            {"tool_name": "mcp__ups__create_shipment", "tool_input": {"request_body": {}}},
            "test-id",
            None,
        )
        assert result == {}  # Allowed

    @pytest.mark.asyncio
    async def test_structural_guard_still_applies_when_interactive_on(self):
        """Non-dict tool_input denied even when interactive=True."""
        from src.orchestrator.agent.hooks import create_shipping_hook

        hook = create_shipping_hook(interactive_shipping=True)
        result = await hook(
            {"tool_name": "mcp__ups__create_shipment", "tool_input": "not a dict"},
            "test-id",
            None,
        )
        assert "deny" in str(result)

    @pytest.mark.asyncio
    async def test_non_shipping_tools_unaffected(self):
        """Other tools pass through regardless of interactive flag."""
        from src.orchestrator.agent.hooks import create_shipping_hook

        hook = create_shipping_hook(interactive_shipping=False)
        result = await hook(
            {"tool_name": "mcp__ups__rate_shipment", "tool_input": {}},
            "test-id",
            None,
        )
        assert result == {}  # Allowed — only create_shipment is gated

    @pytest.mark.asyncio
    async def test_empty_dict_allowed_when_interactive_on(self):
        """Empty dict tool_input allowed when interactive=True (MCP preflight handles)."""
        from src.orchestrator.agent.hooks import create_shipping_hook

        hook = create_shipping_hook(interactive_shipping=True)
        result = await hook(
            {"tool_name": "mcp__ups__create_shipment", "tool_input": {}},
            "test-id",
            None,
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_none_input_denied_when_interactive_on(self):
        """None tool_input denied even when interactive=True."""
        from src.orchestrator.agent.hooks import create_shipping_hook

        hook = create_shipping_hook(interactive_shipping=True)
        result = await hook(
            {"tool_name": "mcp__ups__create_shipment", "tool_input": None},
            "test-id",
            None,
        )
        assert "deny" in str(result)

    @pytest.mark.asyncio
    async def test_list_input_denied_when_interactive_on(self):
        """List tool_input denied even when interactive=True."""
        from src.orchestrator.agent.hooks import create_shipping_hook

        hook = create_shipping_hook(interactive_shipping=True)
        result = await hook(
            {"tool_name": "mcp__ups__create_shipment", "tool_input": [1, 2, 3]},
            "test-id",
            None,
        )
        assert "deny" in str(result)

    @pytest.mark.asyncio
    async def test_create_hook_matchers_uses_factory(self):
        """create_hook_matchers(interactive_shipping=False) produces denial hook."""
        matchers = create_hook_matchers(interactive_shipping=False)
        shipment_matchers = [
            m for m in matchers["PreToolUse"]
            if m.matcher and "create_shipment" in m.matcher
        ]
        assert len(shipment_matchers) >= 1
        # The hook should deny create_shipment when interactive=False
        hook = shipment_matchers[0].hooks[0]
        result = await hook(
            {"tool_name": "mcp__ups__create_shipment", "tool_input": {"request_body": {}}},
            "test-id",
            None,
        )
        assert "deny" in str(result)

    @pytest.mark.asyncio
    async def test_create_hook_matchers_allows_when_interactive(self):
        """create_hook_matchers(interactive_shipping=True) produces allow hook."""
        matchers = create_hook_matchers(interactive_shipping=True)
        shipment_matchers = [
            m for m in matchers["PreToolUse"]
            if m.matcher and "create_shipment" in m.matcher
        ]
        assert len(shipment_matchers) >= 1
        hook = shipment_matchers[0].hooks[0]
        result = await hook(
            {"tool_name": "mcp__ups__create_shipment", "tool_input": {"request_body": {}}},
            "test-id",
            None,
        )
        assert result == {}  # Allowed
