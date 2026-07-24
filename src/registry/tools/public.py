from typing import Literal

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

FIRST_SLICE_TOOL_NAMES = (
    "get_shipagent_status",
    "submit_one_off_shipment",
    "validate_shipment_address",
    "get_shipment_rates",
    "prepare_shipments",
    "execute_shipments",
    "get_job_status",
    "create_label_download",
)

PUBLIC_RELAY_PROVIDERS = [
    ProviderExport.openai_apps_public,
    ProviderExport.claude_remote_mcp_public,
    ProviderExport.generic_mcp,
]

ADDRESS_VALIDATION_GUIDANCE_CODES = [
    "no_action_required",
    "postal_code_review_required",
    "locality_review_required",
    "region_review_required",
    "recipient_review_required",
    "destination_not_recognized",
    "multiple_candidates",
    "carrier_validation_unavailable",
]


def shipagent_reference_schema(description: str) -> dict[str, object]:
    return {
        "type": "string",
        "description": description,
        "pattern": r"^sa_[A-Za-z0-9_-]{20,124}$",
        "minLength": 23,
        "maxLength": 127,
    }


def public_tool(
    name: str,
    title: str,
    description: str,
    side_effect: SideEffectClass,
    auth_scopes: list[str],
    input_schema: dict[str, object],
    output_schema: dict[str, object],
    requires_confirmation: bool = False,
    ui_resource: str | None = None,
    implementation_status: Literal["planned", "implemented"] = "implemented",
    hosted_readiness: Literal["not_ready", "ready"] = "ready",
    provider_export_enabled: bool = False,
    confirmation_policy: str | None = None,
    result_profile: str | None = None,
    prepare_tool: str | None = None,
    execution_target_required: bool = False,
) -> ToolContract:
    confirmation = confirmation_policy if requires_confirmation else None
    return ToolContract(
        name=name,
        title=title,
        description=description,
        contract_version="1.0.0",
        visibility=ToolVisibility.public,
        availability=[Availability.hosted, Availability.local],
        implementation_status=implementation_status,
        hosted_readiness=hosted_readiness,
        tenant_safe=True,
        provider_export_enabled=provider_export_enabled,
        side_effect=side_effect,
        requires_confirmation=requires_confirmation,
        auth_scopes=auth_scopes,
        provider_exports=PUBLIC_RELAY_PROVIDERS,
        audit_level=AuditLevel.full if requires_confirmation else AuditLevel.basic,
        result_sensitivity=ResultSensitivity.business,
        input_schema=input_schema,
        output_schema=output_schema,
        confirmation_policy=confirmation,
        ui_resource=ui_resource,
        result_profile=result_profile or "aggregate",
        prepare_tool=prepare_tool,
        execution_target_required=execution_target_required,
    )


PUBLIC_TOOLS = [
    public_tool(
        "get_shipagent_status",
        "Get shipagent status",
        "Return operational status for the active account and device.",
        SideEffectClass.read,
        ["account:read", "device:read"],
        object_schema(
            {
                "correlation_id": {
                    "type": "string",
                    "description": "Opaque client correlation identifier.",
                }
            },
            ["correlation_id"],
        ),
        object_schema(
            {
                "status": {"type": "string"},
                "active_device_id": {"type": "string"},
                "capabilities": {"type": "array", "items": {"type": "string"}},
            },
            ["status", "active_device_id", "capabilities"],
        ),
        provider_export_enabled=True,
    ),
    public_tool(
        "submit_one_off_shipment",
        "Submit one off shipment",
        "Register a ShipAgent-owned ingress artifact for one-off shipment workflows.",
        SideEffectClass.estimate,
        ["shipments:create"],
        object_schema(
            {
                "ingress_reference": shipagent_reference_schema(
                    "Opaque reference minted by the authenticated ShipAgent ingress channel."
                ),
            },
            ["ingress_reference"],
        ),
        object_schema(
            {
                "input_reference": shipagent_reference_schema(
                    "Opaque ShipAgent shipment input reference."
                )
            },
            ["input_reference"],
        ),
        provider_export_enabled=True,
    ),
    public_tool(
        "validate_shipment_address",
        "Validate shipment address",
        "Validate a destination and return canonical address guidance.",
        SideEffectClass.estimate,
        ["address:validate"],
        object_schema(
            {
                "input_reference": shipagent_reference_schema(
                    "Opaque ShipAgent shipment input reference."
                ),
            },
            ["input_reference"],
        ),
        object_schema(
            {
                "validation_artifact_id": shipagent_reference_schema(
                    "Opaque ShipAgent validation artifact reference."
                ),
                "valid": {"type": "boolean"},
                "guidance_codes": {
                    "type": "array",
                    "description": "Bounded redacted remediation categories.",
                    "items": {
                        "type": "string",
                        "enum": ADDRESS_VALIDATION_GUIDANCE_CODES,
                    },
                    "maxItems": len(ADDRESS_VALIDATION_GUIDANCE_CODES),
                    "uniqueItems": True,
                },
            },
            ["validation_artifact_id", "valid", "guidance_codes"],
        ),
        provider_export_enabled=True,
    ),
    public_tool(
        "get_shipment_rates",
        "Get shipment rates",
        "Generate rate options for a validated shipment request.",
        SideEffectClass.estimate,
        ["shipments:rate"],
        object_schema(
            {
                "input_reference": shipagent_reference_schema(
                    "Opaque ShipAgent shipment input reference."
                )
            },
            ["input_reference"],
        ),
        object_schema(
            {
                "rates": {
                    "type": "array",
                    "items": object_schema(
                        {
                            "service_code": {"type": "string"},
                            "service_name": {"type": "string"},
                            "total_charge": {"type": "string"},
                            "currency_code": {"type": "string"},
                            "estimated_delivery_date": {"type": "string"},
                        },
                        [
                            "service_code",
                            "service_name",
                            "total_charge",
                            "currency_code",
                        ],
                    ),
                },
                "selected": {"type": "string"},
            },
            ["rates", "selected"],
        ),
        ui_resource="ui://shipagent/rates.html",
        execution_target_required=True,
        provider_export_enabled=True,
    ),
    public_tool(
        "prepare_shipments",
        "Prepare shipments",
        "Create immutable preview artifacts for a shipment batch.",
        SideEffectClass.estimate,
        ["shipments:preview"],
        object_schema(
            {
                "input_reference": shipagent_reference_schema(
                    "Opaque ShipAgent shipment input reference."
                )
            },
            ["input_reference"],
        ),
        object_schema(
            {
                "preview_id": {"type": "string"},
                "summary": {
                    "type": "object",
                    "properties": {
                        "shipment_count": {"type": "integer"},
                    },
                    "required": ["shipment_count"],
                    "additionalProperties": False,
                },
            },
            ["preview_id", "summary"],
        ),
        ui_resource="ui://shipagent/preview.html",
        execution_target_required=True,
        provider_export_enabled=True,
    ),
    public_tool(
        "execute_shipments",
        "Execute shipments",
        "Execute a prepared preview and return immutable execution artifacts.",
        SideEffectClass.purchase,
        ["shipments:execute"],
        object_schema(
            {
                "preview_id": {"type": "string"},
                "confirmation_token": {"type": "string"},
            },
            ["preview_id", "confirmation_token"],
        ),
        object_schema(
            {"job_id": {"type": "string"}, "status": {"type": "string"}},
            ["job_id", "status"],
        ),
        requires_confirmation=True,
        confirmation_policy="provider_and_shipagent",
        prepare_tool="prepare_shipments",
        ui_resource="ui://shipagent/confirmation.html",
        execution_target_required=True,
        provider_export_enabled=True,
    ),
    public_tool(
        "get_job_status",
        "Get job status",
        "Get the status and progress summary for a ShipAgent job.",
        SideEffectClass.read,
        ["jobs:read"],
        object_schema(
            {"job_id": {"type": "string", "description": "ShipAgent job identifier."}},
            ["job_id"],
        ),
        object_schema(
            {"job_id": {"type": "string"}, "status": {"type": "string"}},
            ["job_id", "status"],
        ),
        provider_export_enabled=True,
    ),
    public_tool(
        "create_label_download",
        "Create label download",
        "Create downloadable label artifacts for a completed shipment job.",
        SideEffectClass.read,
        ["labels:read"],
        object_schema(
            {"job_id": {"type": "string"}},
            ["job_id"],
        ),
        object_schema(
            {"download_url": {"type": "string"}, "status": {"type": "string"}},
            ["download_url", "status"],
        ),
        provider_export_enabled=True,
    ),
]
