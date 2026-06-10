import pytest
from pydantic import ValidationError

from src.registry.models import (
    AuditLevel,
    Availability,
    ProviderExport,
    RegistrySchema,
    ResultSensitivity,
    SideEffectClass,
    ToolContract,
    ToolVisibility,
)


def minimal_tool(**overrides):
    data = {
        "name": "preview_shipments",
        "title": "Preview shipments",
        "description": "Preview shipment costs and effects before confirmation.",
        "contract_version": "1.0.0",
        "visibility": ToolVisibility.public,
        "availability": [Availability.hosted, Availability.local],
        "implementation_status": "implemented",
        "hosted_readiness": "ready",
        "tenant_safe": True,
        "provider_export_enabled": True,
        "side_effect": SideEffectClass.estimate,
        "requires_confirmation": False,
        "auth_scopes": ["orders:read", "shipments:preview"],
        "provider_exports": [ProviderExport.openai, ProviderExport.generic_mcp],
        "audit_level": AuditLevel.basic,
        "result_sensitivity": ResultSensitivity.business,
        "input_schema": {
            "type": "object",
            "properties": {"order_batch_id": {"type": "string"}},
            "required": ["order_batch_id"],
        },
        "output_schema": {
            "type": "object",
            "properties": {"preview_id": {"type": "string"}},
            "required": ["preview_id"],
        },
    }
    data.update(overrides)
    return ToolContract.model_validate(data)


def test_public_export_requires_tenant_safety():
    with pytest.raises(ValidationError):
        minimal_tool(tenant_safe=False)


def test_public_export_requires_implemented_status():
    with pytest.raises(ValidationError):
        minimal_tool(implementation_status="planned")


def test_public_export_requires_hosted_readiness():
    with pytest.raises(ValidationError):
        minimal_tool(hosted_readiness="not_ready")


def test_tool_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        minimal_tool(visibilityy=ToolVisibility.public)


def test_registry_rejects_unknown_fields():
    tool = minimal_tool()
    with pytest.raises(ValidationError):
        RegistrySchema(schema_version="1.0.0", tools=[tool], unexpected=True)


@pytest.mark.parametrize("field_name", ["availability", "provider_exports"])
def test_tool_rejects_empty_required_lists(field_name):
    with pytest.raises(ValidationError):
        minimal_tool(**{field_name: []})


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("availability", [Availability.hosted, Availability.hosted]),
        ("provider_exports", [ProviderExport.openai, ProviderExport.openai]),
    ],
)
def test_tool_rejects_duplicate_required_lists(field_name, value):
    with pytest.raises(ValidationError):
        minimal_tool(**{field_name: value})


@pytest.mark.parametrize("field_name", ["input_schema", "output_schema"])
def test_tool_rejects_non_object_schemas(field_name):
    with pytest.raises(ValidationError):
        minimal_tool(**{field_name: {"type": "array", "items": {"type": "string"}}})


@pytest.mark.parametrize("field_name", ["input_schema", "output_schema"])
def test_tool_rejects_invalid_json_schema_shapes(field_name):
    with pytest.raises(ValidationError):
        minimal_tool(**{field_name: {"type": "object", "properties": []}})


def test_side_effecting_public_tool_requires_confirmation():
    tool = minimal_tool(
        name="create_shipments",
        title="Create shipments",
        side_effect=SideEffectClass.purchase,
        requires_confirmation=True,
        prepare_tool="prepare_shipments",
        auth_scopes=["shipments:create"],
    )

    assert tool.requires_confirmation is True


@pytest.mark.parametrize(
    "side_effect",
    [
        SideEffectClass.write,
        SideEffectClass.purchase,
        SideEffectClass.external_mutation,
        SideEffectClass.destructive,
    ],
)
def test_side_effecting_public_tool_rejects_missing_confirmation(side_effect):
    with pytest.raises(ValidationError):
        minimal_tool(
            name=f"{side_effect.value}_shipments",
            title=f"{side_effect.value} shipments",
            side_effect=side_effect,
            requires_confirmation=False,
        )


def test_publicly_confirmed_tool_requires_prepare_tool():
    with pytest.raises(ValidationError):
        minimal_tool(
            name="execute_shipments",
            title="Execute shipments",
            side_effect=SideEffectClass.write,
            requires_confirmation=True,
            prepare_tool="create_preview",
        )


def test_registry_rejects_duplicate_tool_names():
    tool = minimal_tool()
    with pytest.raises(ValidationError):
        RegistrySchema(schema_version="1.0.0", tools=[tool, tool])
