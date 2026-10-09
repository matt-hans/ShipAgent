from typing import Literal

from src.job_status import PROVIDER_JOB_STATUS_CODES
from src.registry.identifiers import ShipAgentIdFamily, shipagent_id_schema
from src.registry.models import (
    AuditLevel,
    Availability,
    ProviderExport,
    ResultSensitivity,
    SideEffectClass,
    ToolContract,
    ToolVisibility,
)
from src.registry.privacy import (
    EXPIRES_IN_FIELD,
    MAX_SIGNED_DOWNLOAD_TTL_SECONDS,
    MAX_SIGNED_DOWNLOAD_URL_LENGTH,
)
from src.registry.tools.schema import object_schema
from src.registry.vocabulary import SHIPAGENT_CAPABILITY_CODES
from src.services.ups_constants import DEFAULT_CURRENCY_CODE
from src.services.ups_service_codes import SERVICE_CODE_NAMES, ServiceCode

FIRST_SLICE_TOOL_NAMES = (
    "get_shipagent_status",
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

# Relay execution target states; mirrors RelayTargetState in the control plane.
EXECUTION_TARGET_STATE_CODES = ["ready", "offline", "update_required"]
LABEL_STATUS_CODES = ["pending", "ready", "unavailable"]
UPS_SERVICE_CODES = [code.value for code in ServiceCode]
UPS_SERVICE_NAMES = list(SERVICE_CODE_NAMES.values())
RATE_CURRENCY_CODES = [DEFAULT_CURRENCY_CODE]

PROVIDER_ECHO_TEXT_PATTERN = r"^[^\x00-\x1f\x7f]{1,500}$"
PROVIDER_ECHO_TEXT_MAX_LENGTH = 500
SIGNED_LABEL_URL_PATTERN = r"^https://[^\s\x00-\x1f\x7f]{1,2040}$"
MONEY_PATTERN = r"^(0|[1-9][0-9]{0,9})\.[0-9]{2}$"
_ISO_DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"


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
    provider_originated_fields: list[str] | None = None,
    signed_download_fields: list[str] | None = None,
    notes: str = "",
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
        provider_originated_fields=provider_originated_fields or [],
        signed_download_fields=signed_download_fields or [],
        notes=notes,
    )


PUBLIC_TOOLS = [
    public_tool(
        "get_shipagent_status",
        "Get shipagent status",
        "Return operational status for the active account execution target.",
        SideEffectClass.read,
        ["shipagent.status"],
        object_schema(
            {
                "correlation_id": shipagent_id_schema(
                    ShipAgentIdFamily.CORRELATION,
                    "Opaque ShipAgent correlation identifier.",
                )
            },
            ["correlation_id"],
        ),
        object_schema(
            {
                "status": {"type": "string", "enum": EXECUTION_TARGET_STATE_CODES},
                "executionTarget": object_schema(
                    {
                        "state": {
                            "type": "string",
                            "enum": EXECUTION_TARGET_STATE_CODES,
                        },
                        "capabilities": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": list(SHIPAGENT_CAPABILITY_CODES),
                            },
                            "maxItems": len(SHIPAGENT_CAPABILITY_CODES),
                            "uniqueItems": True,
                        },
                    },
                    ["state", "capabilities"],
                ),
            },
            ["status", "executionTarget"],
        ),
        provider_export_enabled=True,
    ).model_copy(update={"rate_limit_class": "read", "call_repetition": "poll"}),
    public_tool(
        "validate_shipment_address",
        "Validate shipment address",
        "Validate a destination and return canonical address guidance.",
        SideEffectClass.estimate,
        ["address:validate"],
        object_schema(
            {
                "input_reference": shipagent_id_schema(
                    ShipAgentIdFamily.INPUT,
                    "Opaque ShipAgent shipment input reference.",
                ),
            },
            ["input_reference"],
        ),
        object_schema(
            {
                "validation_artifact_id": shipagent_id_schema(
                    ShipAgentIdFamily.VALIDATION,
                    "Opaque ShipAgent validation artifact reference.",
                ),
                "valid": {"type": "boolean"},
                "address_text": {
                    "type": "string",
                    "description": (
                        "Echo of address text the user supplied through the "
                        "provider conversation; never imported-source data."
                    ),
                    "pattern": PROVIDER_ECHO_TEXT_PATTERN,
                    "minLength": 1,
                    "maxLength": PROVIDER_ECHO_TEXT_MAX_LENGTH,
                },
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
        result_profile="provider_ingress_echo",
        provider_originated_fields=["address_text"],
        notes=(
            "ADR 0007: address_text may only be set when the validated input "
            "originated in the provider conversation. Imported-source inputs "
            "must omit it; project_result fails closed without provider_supplied "
            "origin metadata."
        ),
    ),
    public_tool(
        "get_shipment_rates",
        "Get shipment rates",
        "Generate rate options for a validated shipment request.",
        SideEffectClass.estimate,
        ["shipments:rate"],
        object_schema(
            {
                "input_reference": shipagent_id_schema(
                    ShipAgentIdFamily.INPUT,
                    "Opaque ShipAgent shipment input reference.",
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
                            "service_code": {
                                "type": "string",
                                "enum": UPS_SERVICE_CODES,
                            },
                            "service_name": {
                                "type": "string",
                                "enum": UPS_SERVICE_NAMES,
                            },
                            "total_charge": {
                                "type": "string",
                                "pattern": MONEY_PATTERN,
                                "minLength": 4,
                                "maxLength": 13,
                            },
                            "currency_code": {
                                "type": "string",
                                "enum": RATE_CURRENCY_CODES,
                            },
                            "estimated_delivery_date": {
                                "type": "string",
                                "pattern": _ISO_DATE_PATTERN,
                                "minLength": 10,
                                "maxLength": 10,
                            },
                        },
                        [
                            "service_code",
                            "service_name",
                            "total_charge",
                            "currency_code",
                        ],
                    ),
                    "maxItems": len(UPS_SERVICE_CODES),
                },
                "selected": {
                    "type": "string",
                    "enum": UPS_SERVICE_CODES,
                },
            },
            ["rates", "selected"],
        ),
        ui_resource="ui://shipagent/rates.html",
        execution_target_required=True,
    ),
    public_tool(
        "prepare_shipments",
        "Prepare shipments",
        "Create immutable preview artifacts for a shipment batch.",
        SideEffectClass.estimate,
        ["shipments:preview"],
        object_schema(
            {
                "input_reference": shipagent_id_schema(
                    ShipAgentIdFamily.INPUT,
                    "Opaque ShipAgent shipment input reference.",
                )
            },
            ["input_reference"],
        ),
        object_schema(
            {
                "preview_id": shipagent_id_schema(
                    ShipAgentIdFamily.PREVIEW,
                    "Opaque ShipAgent shipment preview identifier.",
                ),
                "approval_request_id": shipagent_id_schema(
                    ShipAgentIdFamily.APPROVAL_REQUEST,
                    "Opaque Approval Request reference; carries no execution authority.",
                ),
                "summary": {
                    "type": "object",
                    "properties": {
                        "shipment_count": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 1_000_000,
                        },
                    },
                    "required": ["shipment_count"],
                    "additionalProperties": False,
                },
            },
            ["preview_id", "summary"],
        ),
        ui_resource="ui://shipagent/preview.html",
        execution_target_required=True,
    ),
    public_tool(
        "execute_shipments",
        "Execute shipments",
        "Execute a prepared preview and return immutable execution artifacts.",
        SideEffectClass.purchase,
        ["shipments:execute"],
        object_schema(
            {
                "preview_id": shipagent_id_schema(
                    ShipAgentIdFamily.PREVIEW,
                    "Opaque ShipAgent shipment preview identifier.",
                ),
                "approval_request_id": shipagent_id_schema(
                    ShipAgentIdFamily.APPROVAL_REQUEST,
                    "Opaque Approval Request reference returned by prepare_shipments.",
                ),
            },
            ["preview_id", "approval_request_id"],
        ),
        object_schema(
            {
                "job_id": shipagent_id_schema(
                    ShipAgentIdFamily.JOB,
                    "Opaque ShipAgent shipment job identifier.",
                ),
                "status": {
                    "type": "string",
                    "enum": list(PROVIDER_JOB_STATUS_CODES),
                },
            },
            ["job_id", "status"],
        ),
        requires_confirmation=True,
        confirmation_policy="provider_and_shipagent",
        prepare_tool="prepare_shipments",
        ui_resource="ui://shipagent/confirmation.html",
        execution_target_required=True,
    ),
    public_tool(
        "get_job_status",
        "Get job status",
        "Get the status and progress summary for a ShipAgent job.",
        SideEffectClass.read,
        ["jobs:read"],
        object_schema(
            {
                "job_id": shipagent_id_schema(
                    ShipAgentIdFamily.JOB,
                    "Opaque ShipAgent shipment job identifier.",
                )
            },
            ["job_id"],
        ),
        object_schema(
            {
                "job_id": shipagent_id_schema(
                    ShipAgentIdFamily.JOB,
                    "Opaque ShipAgent shipment job identifier.",
                ),
                "status": {
                    "type": "string",
                    "enum": list(PROVIDER_JOB_STATUS_CODES),
                },
            },
            ["job_id", "status"],
        ),
    ),
    public_tool(
        "create_label_download",
        "Create label download",
        "Create a short-lived signed label download reference for the account.",
        SideEffectClass.read,
        ["labels:read"],
        object_schema(
            {
                "job_id": shipagent_id_schema(
                    ShipAgentIdFamily.JOB,
                    "Opaque ShipAgent shipment job identifier.",
                )
            },
            ["job_id"],
        ),
        object_schema(
            {
                "label_artifact_id": shipagent_id_schema(
                    ShipAgentIdFamily.LABEL,
                    "Opaque label artifact resolved only by an authenticated ShipAgent channel.",
                ),
                "status": {"type": "string", "enum": LABEL_STATUS_CODES},
                "download_url": {
                    "type": "string",
                    "description": (
                        "Short-lived signed download URL; label bytes never "
                        "pass through the provider."
                    ),
                    "pattern": SIGNED_LABEL_URL_PATTERN,
                    "minLength": 9,
                    "maxLength": MAX_SIGNED_DOWNLOAD_URL_LENGTH,
                },
                EXPIRES_IN_FIELD: {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_SIGNED_DOWNLOAD_TTL_SECONDS,
                },
            },
            ["label_artifact_id", "status"],
        ),
        result_profile="artifact_action",
        signed_download_fields=["download_url"],
        notes=(
            "ADR 0007 obligations for any future implementation: the URL is "
            "minted by the Execution Target flow, single-use, and bound to an "
            "Auth0 browser session of the same Cloud Account; possession alone "
            "is not authorization. Bytes stream desktop-to-browser with no "
            "cloud persistence. Projection enforces only shape: https, no "
            "whitespace/credentials/fragment, ready status, and "
            "expires_in_seconds <= 300 accompanying the URL. Signature "
            "verification, single-use and account binding are deferred "
            "trusted-minting obligations and are NOT enforced here."
        ),
    ),
]
