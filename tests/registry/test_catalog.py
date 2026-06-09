from src.registry.catalog import load_registry, public_tools
from src.registry.models import ProviderExport, SideEffectClass, ToolVisibility

EXPECTED_PUBLIC = {
    "get_shipagent_status",
    "submit_one_off_shipment",
    "validate_shipment_address",
    "get_shipment_rates",
    "prepare_shipments",
    "execute_shipments",
    "get_job_status",
    "create_label_download",
}


def test_public_catalog_has_expected_tools():
    assert {tool.name for tool in public_tools()} == EXPECTED_PUBLIC


def test_public_tools_are_tenant_safe_and_provider_exportable():
    for tool in public_tools():
        assert tool.visibility == ToolVisibility.public
        assert tool.tenant_safe is True
        assert tool.implementation_status == "implemented"
        assert tool.hosted_readiness == "ready"
        assert tool.provider_export_enabled is False
        assert ProviderExport.openai_apps_public in tool.provider_exports
        assert ProviderExport.claude_remote_mcp_public in tool.provider_exports
        assert ProviderExport.generic_mcp in tool.provider_exports
        assert ProviderExport.anthropic not in tool.provider_exports


def test_side_effecting_public_tools_require_confirmation():
    for tool in public_tools():
        if tool.side_effect in {
            SideEffectClass.write,
            SideEffectClass.purchase,
            SideEffectClass.external_mutation,
            SideEffectClass.destructive,
        }:
            assert tool.requires_confirmation is True


def test_execute_shipments_declares_prepare_tool_and_execution_gate():
    tool = next(tool for tool in public_tools() if tool.name == "execute_shipments")

    assert tool.prepare_tool == "prepare_shipments"
    assert tool.execution_target_required is True
    assert tool.confirmation_policy == "provider_and_shipagent"


def test_public_input_schemas_are_closed():
    for tool in public_tools():
        assert tool.input_schema["additionalProperties"] is False


def test_prepare_tool_schema_is_strict():
    tool = next(tool for tool in public_tools() if tool.name == "prepare_shipments")

    assert set(tool.input_schema["properties"]) == {"input_reference"}
    assert "tenant_id" not in tool.input_schema["properties"]


def test_submit_one_off_shipment_is_non_confirming_input_reference_entrypoint():
    tool = next(
        tool for tool in public_tools() if tool.name == "submit_one_off_shipment"
    )

    assert tool.requires_confirmation is False
    assert tool.side_effect == "estimate"
    assert tool.prepare_tool is None


def test_registry_loads_all_tools():
    registry = load_registry()
    tools_by_name = {tool.name: tool for tool in registry.tools}
    raw_ups_tool = tools_by_name["raw_ups_tool"]

    assert set(tools_by_name) == EXPECTED_PUBLIC | {"raw_ups_tool"}
    assert raw_ups_tool.visibility == ToolVisibility.private
    assert raw_ups_tool.provider_export_enabled is False
    assert raw_ups_tool.tenant_safe is False
