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

ALL_PROVIDERS = [
    ProviderExport.openai,
    ProviderExport.anthropic,
    ProviderExport.microsoft,
    ProviderExport.gemini,
    ProviderExport.generic_mcp,
]


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
) -> ToolContract:
    return ToolContract(
        name=name,
        title=title,
        description=description,
        contract_version="1.0.0",
        visibility=ToolVisibility.public,
        availability=[Availability.hosted, Availability.local],
        implementation_status="implemented",
        hosted_readiness="ready",
        tenant_safe=True,
        provider_export_enabled=True,
        side_effect=side_effect,
        requires_confirmation=requires_confirmation,
        auth_scopes=auth_scopes,
        provider_exports=ALL_PROVIDERS,
        audit_level=AuditLevel.full if requires_confirmation else AuditLevel.basic,
        result_sensitivity=ResultSensitivity.business,
        input_schema=input_schema,
        output_schema=output_schema,
        confirmation_policy="standard_side_effect" if requires_confirmation else None,
        ui_resource=ui_resource,
    )


PUBLIC_TOOLS = [
    public_tool(
        "connect_carrier_account",
        "Connect carrier account",
        "Start or check carrier account linking for shipment creation.",
        SideEffectClass.write,
        ["accounts:connect"],
        object_schema(
            {
                "carrier": {
                    "type": "string",
                    "enum": ["ups"],
                    "description": "Carrier account to connect.",
                }
            },
            ["carrier"],
        ),
        object_schema(
            {"link_url": {"type": "string"}, "status": {"type": "string"}},
            ["status"],
        ),
        requires_confirmation=True,
    ),
    public_tool(
        "connect_store",
        "Connect store",
        "Start or check commerce store account linking for order import and tracking write-back.",
        SideEffectClass.write,
        ["stores:connect"],
        object_schema(
            {
                "platform": {
                    "type": "string",
                    "description": "Commerce platform to connect.",
                }
            },
            ["platform"],
        ),
        object_schema(
            {"link_url": {"type": "string"}, "status": {"type": "string"}},
            ["status"],
        ),
        requires_confirmation=True,
    ),
    public_tool(
        "upload_or_import_orders",
        "Upload or import orders",
        "Import order data from an uploaded file or connected cloud store into a hosted order batch.",
        SideEffectClass.write,
        ["orders:write"],
        object_schema(
            {
                "source": {
                    "type": "string",
                    "description": "Order source type, such as uploaded file or connected store.",
                },
                "source_ref": {
                    "type": "string",
                    "description": "Opaque reference for the uploaded file or import source.",
                },
            },
            ["source"],
        ),
        object_schema(
            {"order_batch_id": {"type": "string"}, "row_count": {"type": "integer"}},
            ["order_batch_id", "row_count"],
        ),
        requires_confirmation=True,
    ),
    public_tool(
        "preview_shipments",
        "Preview shipments",
        "Preview shipment destinations, service choices, costs, and write-back effects before purchase.",
        SideEffectClass.estimate,
        ["orders:read", "shipments:preview"],
        object_schema(
            {
                "order_batch_id": {
                    "type": "string",
                    "description": "Hosted order batch to preview.",
                }
            },
            ["order_batch_id"],
        ),
        object_schema(
            {"preview_id": {"type": "string"}, "summary": {"type": "object"}},
            ["preview_id", "summary"],
        ),
        ui_resource="ui://shipagent/preview.html",
    ),
    public_tool(
        "compare_rates",
        "Compare rates",
        "Compare available rates for one shipment or a shipment batch preview.",
        SideEffectClass.estimate,
        ["shipments:rate"],
        object_schema(
            {
                "preview_id": {
                    "type": "string",
                    "description": "Shipment preview to rate.",
                }
            },
            ["preview_id"],
        ),
        object_schema(
            {"rates": {"type": "array", "items": {"type": "object"}}},
            ["rates"],
        ),
        ui_resource="ui://shipagent/rates.html",
    ),
    public_tool(
        "create_shipments",
        "Create shipments",
        "Create shipping labels after a confirmed preview and return job status.",
        SideEffectClass.purchase,
        ["shipments:create"],
        object_schema(
            {
                "confirmation_token": {
                    "type": "string",
                    "description": "Confirmation token for the approved shipment preview.",
                }
            },
            ["confirmation_token"],
        ),
        object_schema(
            {"job_id": {"type": "string"}, "status": {"type": "string"}},
            ["job_id", "status"],
        ),
        requires_confirmation=True,
        ui_resource="ui://shipagent/confirmation.html",
    ),
    public_tool(
        "track_package",
        "Track package",
        "Track a package by tracking number.",
        SideEffectClass.read,
        ["tracking:read"],
        object_schema(
            {
                "tracking_number": {
                    "type": "string",
                    "description": "Carrier tracking number to look up.",
                }
            },
            ["tracking_number"],
        ),
        object_schema(
            {
                "status": {"type": "string"},
                "events": {"type": "array", "items": {"type": "object"}},
            },
            ["status"],
        ),
        ui_resource="ui://shipagent/tracking.html",
    ),
    public_tool(
        "schedule_pickup",
        "Schedule pickup",
        "Schedule a carrier pickup after confirmed pickup details.",
        SideEffectClass.external_mutation,
        ["pickups:create"],
        object_schema(
            {
                "confirmation_token": {
                    "type": "string",
                    "description": "Confirmation token for the approved pickup request.",
                }
            },
            ["confirmation_token"],
        ),
        object_schema(
            {"pickup_id": {"type": "string"}, "status": {"type": "string"}},
            ["pickup_id", "status"],
        ),
        requires_confirmation=True,
        ui_resource="ui://shipagent/pickup.html",
    ),
    public_tool(
        "void_shipment",
        "Void shipment",
        "Void a created shipment after confirmation.",
        SideEffectClass.destructive,
        ["shipments:void"],
        object_schema(
            {
                "confirmation_token": {
                    "type": "string",
                    "description": "Confirmation token for the shipment void request.",
                }
            },
            ["confirmation_token"],
        ),
        object_schema(
            {"shipment_id": {"type": "string"}, "status": {"type": "string"}},
            ["shipment_id", "status"],
        ),
        requires_confirmation=True,
    ),
    public_tool(
        "write_back_tracking",
        "Write back tracking",
        "Write tracking numbers back to a connected cloud system after confirmation.",
        SideEffectClass.external_mutation,
        ["tracking:write"],
        object_schema(
            {
                "confirmation_token": {
                    "type": "string",
                    "description": "Confirmation token for the tracking write-back job.",
                }
            },
            ["confirmation_token"],
        ),
        object_schema(
            {"job_id": {"type": "string"}, "status": {"type": "string"}},
            ["job_id", "status"],
        ),
        requires_confirmation=True,
    ),
    public_tool(
        "get_job_status",
        "Get job status",
        "Get the status and progress summary for a ShipAgent job.",
        SideEffectClass.read,
        ["jobs:read"],
        object_schema(
            {
                "job_id": {
                    "type": "string",
                    "description": "ShipAgent job identifier.",
                }
            },
            ["job_id"],
        ),
        object_schema(
            {"job_id": {"type": "string"}, "status": {"type": "string"}},
            ["job_id", "status"],
        ),
    ),
    public_tool(
        "get_label_links",
        "Get label links",
        "Return tenant-scoped expiring links or opaque handles for generated labels.",
        SideEffectClass.read,
        ["labels:read"],
        object_schema(
            {
                "job_id": {
                    "type": "string",
                    "description": "ShipAgent label creation job identifier.",
                }
            },
            ["job_id"],
        ),
        object_schema(
            {"links": {"type": "array", "items": {"type": "object"}}},
            ["links"],
        ),
    ),
    public_tool(
        "get_audit_summary",
        "Get audit summary",
        "Return a provider-safe summary of ShipAgent decisions and side effects for a job.",
        SideEffectClass.read,
        ["audit:read"],
        object_schema(
            {
                "job_id": {
                    "type": "string",
                    "description": "ShipAgent job identifier to summarize.",
                }
            },
            ["job_id"],
        ),
        object_schema({"summary": {"type": "object"}}, ["summary"]),
    ),
]
