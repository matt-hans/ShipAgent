import pytest

from src.provider_adapters.export_filter import exportable_tools
from src.provider_adapters.gemini_projection import to_gemini_function
from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.provider_adapters.microsoft_projection import to_openapi_operation
from src.provider_adapters.openai_projection import to_openai_app_tool
from src.registry.catalog import public_tools
from src.registry.models import ProviderExport, ToolVisibility


def tool(name: str):
    return next(item for item in public_tools() if item.name == name)


def test_mcp_descriptor_includes_annotations():
    descriptor = to_mcp_tool_descriptor(tool("execute_shipments"))

    assert descriptor["name"] == "execute_shipments"
    assert descriptor["annotations"]["destructiveHint"] is False
    assert descriptor["annotations"]["readOnlyHint"] is False


def test_openai_app_tool_includes_ui_meta_when_present():
    descriptor = to_openai_app_tool(tool("prepare_shipments"))

    assert descriptor["title"] == "Prepare shipments"
    assert descriptor["_meta"]["ui"]["resourceUri"] == "ui://shipagent/preview.html"


def test_openai_app_tool_omits_ui_meta_when_absent():
    descriptor = to_openai_app_tool(tool("create_label_download"))

    assert "_meta" not in descriptor


def test_microsoft_openapi_marks_consequential_operations():
    operation = to_openapi_operation(tool("execute_shipments"))

    assert operation["x-openai-isConsequential"] is True


def test_gemini_function_declaration_has_parameters():
    declaration = to_gemini_function(tool("prepare_shipments"))

    assert declaration["name"] == "prepare_shipments"
    assert declaration["parameters"]["type"] == "object"


@pytest.mark.parametrize(
    ("tool_name", "read_only", "destructive", "open_world", "consequential"),
    [
        ("get_shipagent_status", True, False, False, False),
        ("submit_one_off_shipment", False, False, True, True),
        ("validate_shipment_address", True, False, False, False),
        ("get_shipment_rates", True, False, True, False),
        ("prepare_shipments", True, False, True, False),
        ("execute_shipments", False, False, True, True),
        ("get_job_status", True, False, False, False),
        ("create_label_download", True, False, True, False),
    ],
)
def test_side_effect_safety_metadata(
    tool_name: str,
    read_only: bool,
    destructive: bool,
    open_world: bool,
    consequential: bool,
):
    contract = tool(tool_name)
    mcp_descriptor = to_mcp_tool_descriptor(contract)
    microsoft_operation = to_openapi_operation(contract)

    assert mcp_descriptor["annotations"]["readOnlyHint"] is read_only
    assert mcp_descriptor["annotations"]["destructiveHint"] is destructive
    assert mcp_descriptor["annotations"]["openWorldHint"] is open_world
    assert microsoft_operation["x-openai-isConsequential"] is consequential


def test_exportable_tools_filters_by_provider_and_export_safety_gates():
    base_tool = tool("get_job_status")
    exportable_update = {
        "implementation_status": "implemented",
        "hosted_readiness": "ready",
        "provider_export_enabled": True,
    }
    included = base_tool.model_copy(
        update={
            **exportable_update,
            "name": "included",
            "provider_exports": [ProviderExport.gemini],
        }
    )
    provider_excluded = base_tool.model_copy(
        update={
            **exportable_update,
            "name": "provider_excluded",
            "provider_exports": [ProviderExport.openai],
        }
    )
    disabled = base_tool.model_copy(
        update={**exportable_update, "name": "disabled", "provider_export_enabled": False}
    )
    planned = base_tool.model_copy(
        update={**exportable_update, "name": "planned", "implementation_status": "planned"}
    )
    not_ready = base_tool.model_copy(
        update={**exportable_update, "name": "not_ready", "hosted_readiness": "not_ready"}
    )
    unsafe = base_tool.model_copy(
        update={**exportable_update, "name": "unsafe", "tenant_safe": False}
    )
    private = base_tool.model_copy(
        update={**exportable_update, "name": "private", "visibility": ToolVisibility.private}
    )

    exported = exportable_tools(
        ProviderExport.gemini,
        [included, provider_excluded, disabled, planned, not_ready, unsafe, private],
    )

    assert [contract.name for contract in exported] == ["included"]


def test_public_tools_do_not_claim_anthropic_export_without_artifact_path():
    for contract in public_tools():
        assert ProviderExport.anthropic not in contract.provider_exports


def schema_at(payload: dict, path: tuple[str, ...]) -> dict:
    schema = payload
    for key in path:
        schema = schema[key]
    return schema


@pytest.mark.parametrize(
    ("projection", "schema_path"),
    [
        (to_mcp_tool_descriptor, ("inputSchema",)),
        (to_openai_app_tool, ("inputSchema",)),
        (
            to_openapi_operation,
            ("requestBody", "content", "application/json", "schema"),
        ),
        (to_gemini_function, ("parameters",)),
    ],
)
def test_projection_input_schemas_do_not_alias_registry_schemas(
    projection,
    schema_path: tuple[str, ...],
):
    contract = tool("prepare_shipments")
    descriptor = projection(contract)
    schema = schema_at(descriptor, schema_path)

    schema["properties"]["order_batch_id"]["type"] = "integer"

    assert contract.input_schema["properties"]["order_batch_id"]["type"] == "string"


@pytest.mark.parametrize(
    ("projection", "schema_path"),
    [
        (to_mcp_tool_descriptor, ("outputSchema",)),
        (
            to_openapi_operation,
            ("responses", "200", "content", "application/json", "schema"),
        ),
    ],
)
def test_projection_output_schemas_do_not_alias_registry_schemas(
    projection,
    schema_path: tuple[str, ...],
):
    contract = tool("prepare_shipments")
    descriptor = projection(contract)
    schema = schema_at(descriptor, schema_path)

    schema["properties"]["preview_id"]["type"] = "integer"

    assert contract.output_schema["properties"]["preview_id"]["type"] == "string"
