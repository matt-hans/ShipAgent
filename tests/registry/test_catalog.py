from src.registry.catalog import load_registry, public_tools
from src.registry.models import ProviderExport, SideEffectClass, ToolVisibility
from src.workflows.models import PreviewShipmentsRequest, PreviewShipmentsResult

EXPECTED_PUBLIC = {
    "connect_carrier_account",
    "connect_store",
    "upload_or_import_orders",
    "preview_shipments",
    "compare_rates",
    "create_shipments",
    "track_package",
    "schedule_pickup",
    "void_shipment",
    "write_back_tracking",
    "get_job_status",
    "get_label_links",
    "get_audit_summary",
}


def test_public_catalog_has_expected_tools():
    assert {tool.name for tool in public_tools()} == EXPECTED_PUBLIC


def test_public_tools_are_tenant_safe_but_not_provider_exported_without_bindings():
    for tool in public_tools():
        assert tool.visibility == ToolVisibility.public
        assert tool.tenant_safe is True
        assert tool.implementation_status == "planned"
        assert tool.hosted_readiness == "not_ready"
        assert tool.provider_export_enabled is False
        assert ProviderExport.openai in tool.provider_exports
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


def test_connect_tools_start_linking_with_confirmation():
    tools_by_name = {tool.name: tool for tool in public_tools()}

    for name in {"connect_carrier_account", "connect_store"}:
        tool = tools_by_name[name]
        assert tool.side_effect == SideEffectClass.write
        assert tool.requires_confirmation is True
        assert tool.confirmation_policy == "standard_side_effect"


def test_public_input_schemas_are_closed():
    for tool in public_tools():
        assert tool.input_schema["additionalProperties"] is False


def test_track_package_schema_matches_description():
    tool = next(tool for tool in public_tools() if tool.name == "track_package")

    assert set(tool.input_schema["properties"]) == {"tracking_number"}
    assert "shipment id" not in tool.description.lower()


def test_preview_shipments_schema_matches_workflow_request_contract():
    tool = next(tool for tool in public_tools() if tool.name == "preview_shipments")
    workflow_schema = PreviewShipmentsRequest.model_json_schema()
    workflow_result_schema = PreviewShipmentsResult.model_json_schema()

    assert set(tool.input_schema["required"]) == set(workflow_schema["required"])
    assert set(tool.input_schema["properties"]) == set(workflow_schema["properties"])
    assert tool.input_schema["properties"]["shipments"]["minItems"] == 1
    assert set(tool.output_schema["required"]) == set(workflow_result_schema["required"])
    assert set(tool.output_schema["properties"]) == set(
        workflow_result_schema["properties"]
    )


def test_registry_loads_all_tools():
    registry = load_registry()
    tools_by_name = {tool.name: tool for tool in registry.tools}
    raw_ups_tool = tools_by_name["raw_ups_tool"]

    assert set(tools_by_name) == EXPECTED_PUBLIC | {"raw_ups_tool"}
    assert raw_ups_tool.visibility == ToolVisibility.private
    assert raw_ups_tool.provider_export_enabled is False
    assert raw_ups_tool.tenant_safe is False
