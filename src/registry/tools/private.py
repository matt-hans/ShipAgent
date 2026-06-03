from src.registry.models import (
    AuditLevel,
    Availability,
    ProviderExport,
    ResultSensitivity,
    SideEffectClass,
    ToolContract,
    ToolVisibility,
)
from src.registry.tools.schema import object_schema

PRIVATE_TOOLS = [
    ToolContract(
        name="raw_ups_tool",
        title="Raw UPS tool",
        description="Private diagnostic access to raw UPS MCP primitives for trusted deployments.",
        contract_version="1.0.0",
        visibility=ToolVisibility.private,
        availability=[Availability.local],
        implementation_status="implemented",
        hosted_readiness="not_ready",
        tenant_safe=False,
        provider_export_enabled=False,
        side_effect=SideEffectClass.external_mutation,
        requires_confirmation=True,
        auth_scopes=["debug:carrier"],
        provider_exports=[ProviderExport.generic_mcp],
        audit_level=AuditLevel.full,
        result_sensitivity=ResultSensitivity.confidential,
        input_schema=object_schema(
            {"tool_name": {"type": "string"}, "args": {"type": "object"}},
            ["tool_name", "args"],
        ),
        output_schema=object_schema({"result": {"type": "object"}}, ["result"]),
        confirmation_policy="private_debug",
    )
]
