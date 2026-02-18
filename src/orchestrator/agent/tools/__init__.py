"""Agent tool registration — canonical entrypoint.

Imports handler functions from submodules and assembles tool definition
lists for the orchestration agent.
"""

from collections.abc import Awaitable, Callable
from typing import Any, TypedDict


class ToolDefinition(TypedDict):
    """Type-safe tool definition for the orchestration agent."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Awaitable[Any]]

from src.orchestrator.agent.tools.core import EventEmitterBridge, _bind_bridge
from src.orchestrator.agent.tools.data import (
    confirm_filter_interpretation_tool,
    connect_shopify_tool,
    fetch_rows_tool,
    get_platform_status_tool,
    get_schema_tool,
    get_source_info_tool,
    resolve_filter_intent_tool,
)
from src.orchestrator.agent.tools.documents import (
    delete_paperless_document_tool,
    push_document_to_shipment_tool,
    request_document_upload_tool,
    upload_paperless_document_tool,
)
from src.orchestrator.agent.tools.interactive import (
    preview_interactive_shipment_tool,
)
from src.orchestrator.agent.tools.pickup import (
    cancel_pickup_tool,
    find_locations_tool,
    get_pickup_status_tool,
    get_service_center_facilities_tool,
    rate_pickup_tool,
    schedule_pickup_tool,
)
from src.orchestrator.agent.tools.pipeline import (
    batch_execute_tool,
    get_job_status_tool,
    get_landed_cost_tool,
    ship_command_pipeline_tool,
)
from src.orchestrator.agent.tools.tracking import track_package_tool


def get_all_tool_definitions(
    event_bridge: EventEmitterBridge | None = None,
    interactive_shipping: bool = False,
) -> list[ToolDefinition]:
    """Return all tool definitions for the orchestration agent.

    Each definition includes name, description, input_schema, and handler.

    Returns:
        List of tool definition dicts.
    """
    bridge = event_bridge or EventEmitterBridge()
    definitions = [
        {
            "name": "get_source_info",
            "description": "Get metadata about the currently connected data source (type, path, row count).",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
            "handler": get_source_info_tool,
        },
        {
            "name": "get_schema",
            "description": "Get the column schema (names, types) of the connected data source.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
            "handler": get_schema_tool,
        },
        {
            "name": "ship_command_pipeline",
            "description": (
                "Fast shipping pipeline for straightforward commands. "
                "This tool fetches rows, creates a job, stores rows, and "
                "generates the preview in one call."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "filter_spec": {
                        "type": "object",
                        "description": (
                            "Resolved FilterSpec from resolve_filter_intent. "
                            "Provide this OR all_rows=true, not both."
                        ),
                    },
                    "all_rows": {
                        "type": "boolean",
                        "description": (
                            "Set true to ship all rows without filtering. "
                            "Provide this OR filter_spec, not both."
                        ),
                        "default": False,
                    },
                    "command": {
                        "type": "string",
                        "description": "Original user shipping command.",
                    },
                    "job_name": {
                        "type": "string",
                        "description": "Optional human-readable job name.",
                    },
                    "service_code": {
                        "type": "string",
                        "description": "Optional UPS service code (e.g., 03 for Ground).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows to fetch (default 250).",
                        "default": 250,
                    },
                },
                "required": ["command"],
            },
            "handler": _bind_bridge(ship_command_pipeline_tool, bridge),
        },
        {
            "name": "fetch_rows",
            "description": (
                "Fetch rows from the data source using a compiled FilterSpec. "
                "Returns row samples and counts for exploratory analysis. "
                "Response includes total_count (authoritative matches) and "
                "returned_count (current page size). "
                "Provide filter_spec OR all_rows=true, not both."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "filter_spec": {
                        "type": "object",
                        "description": (
                            "Resolved FilterSpec from resolve_filter_intent. "
                            "Provide this OR all_rows=true, not both."
                        ),
                    },
                    "all_rows": {
                        "type": "boolean",
                        "description": (
                            "Set true to fetch all rows without filtering. "
                            "Provide this OR filter_spec, not both."
                        ),
                        "default": False,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows to return (default 250).",
                        "default": 250,
                    },
                    "include_rows": {
                        "type": "boolean",
                        "description": (
                            "Set true only when full row objects are strictly "
                            "needed in the response. Default false for speed."
                        ),
                        "default": False,
                    },
                },
            },
            "handler": _bind_bridge(fetch_rows_tool, bridge),
        },
        {
            "name": "resolve_filter_intent",
            "description": (
                "Resolve a structured FilterIntent into a concrete FilterSpec. "
                "Takes a FilterIntent JSON, resolves semantic references "
                "(regions, business predicates) against the active data source, "
                "and returns a ResolvedFilterSpec with status and explanation."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "object",
                        "description": (
                            "FilterIntent JSON with root FilterGroup containing "
                            "conditions and/or semantic references."
                        ),
                    },
                },
                "required": ["intent"],
            },
            "handler": _bind_bridge(resolve_filter_intent_tool, bridge),
        },
        {
            "name": "confirm_filter_interpretation",
            "description": (
                "Confirm a Tier-B filter interpretation after user approval. "
                "Call this after resolve_filter_intent returns NEEDS_CONFIRMATION "
                "and the user has confirmed the pending interpretations. "
                "Pass the resolution_token and the original intent to get a "
                "RESOLVED spec with a valid execution token."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "resolution_token": {
                        "type": "string",
                        "description": (
                            "The resolution_token from the NEEDS_CONFIRMATION response."
                        ),
                    },
                    "intent": {
                        "type": "object",
                        "description": (
                            "The same FilterIntent JSON originally passed to "
                            "resolve_filter_intent."
                        ),
                    },
                },
                "required": ["resolution_token", "intent"],
            },
            "handler": _bind_bridge(confirm_filter_interpretation_tool, bridge),
        },
        {
            "name": "get_job_status",
            "description": "Get the summary and progress of a job.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job UUID.",
                    },
                },
                "required": ["job_id"],
            },
            "handler": get_job_status_tool,
        },
        {
            "name": "batch_execute",
            "description": "Execute a confirmed batch job (create shipments). Requires user approval.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job UUID to execute.",
                    },
                    "approved": {
                        "type": "boolean",
                        "description": "Must be True — set only after user confirms the preview.",
                    },
                },
                "required": ["job_id", "approved"],
            },
            "handler": batch_execute_tool,
        },
        {
            "name": "get_platform_status",
            "description": "Check which external platforms (Shopify, etc.) are connected.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
            "handler": get_platform_status_tool,
        },
        {
            "name": "connect_shopify",
            "description": (
                "Connect to Shopify using env credentials, fetch orders, "
                "and import them as the active data source. Call this when "
                "no data source is active and Shopify env vars are configured."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
            },
            "handler": _bind_bridge(connect_shopify_tool, bridge),
        },
        # ---------------------------------------------------------------
        # UPS MCP v2 — Pickup tools
        # ---------------------------------------------------------------
        {
            "name": "schedule_pickup",
            "description": (
                "Schedule a UPS carrier pickup. This is a financial commitment — "
                "always confirm with the user first, then set confirmed=true."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pickup_date": {
                        "type": "string",
                        "description": "Pickup date in YYYYMMDD format.",
                    },
                    "ready_time": {
                        "type": "string",
                        "description": "Ready time in HHMM 24-hour format.",
                    },
                    "close_time": {
                        "type": "string",
                        "description": "Close time in HHMM 24-hour format.",
                    },
                    "address_line": {
                        "type": "string",
                        "description": "Pickup street address.",
                    },
                    "city": {"type": "string", "description": "City."},
                    "state": {"type": "string", "description": "State/province code."},
                    "postal_code": {"type": "string", "description": "Postal/ZIP code."},
                    "country_code": {"type": "string", "description": "Country code."},
                    "contact_name": {"type": "string", "description": "Contact name."},
                    "phone_number": {"type": "string", "description": "Contact phone."},
                    "confirmed": {
                        "type": "boolean",
                        "description": "Must be true. Set only after the user explicitly confirms.",
                    },
                },
                "required": [
                    "pickup_date", "ready_time", "close_time",
                    "address_line", "city", "state", "postal_code",
                    "country_code", "contact_name", "phone_number",
                    "confirmed",
                ],
            },
            "handler": _bind_bridge(schedule_pickup_tool, bridge),
        },
        {
            "name": "cancel_pickup",
            "description": (
                "Cancel a previously scheduled UPS pickup. This is irreversible — "
                "confirm with the user first, then set confirmed=true."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "cancel_by": {
                        "type": "string",
                        "description": "'prn' to cancel by PRN, 'account' for most recent.",
                        "enum": ["prn", "account"],
                    },
                    "prn": {
                        "type": "string",
                        "description": "Pickup Request Number (required when cancel_by='prn').",
                    },
                    "confirmed": {
                        "type": "boolean",
                        "description": "Must be true. Set only after the user explicitly confirms.",
                    },
                },
                "required": ["cancel_by", "confirmed"],
            },
            "handler": _bind_bridge(cancel_pickup_tool, bridge),
        },
        {
            "name": "rate_pickup",
            "description": (
                "Rate a UPS pickup and display the preview card. ALWAYS call this BEFORE "
                "schedule_pickup. Collects address, contact, and schedule details, gets "
                "the rate estimate, and displays a preview card to the user with Confirm/"
                "Cancel buttons. Pickup type is always on-call and set automatically. "
                "Include contact_name and phone_number in the args so they appear in "
                "the preview."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "address_line": {"type": "string", "description": "Pickup address."},
                    "city": {"type": "string", "description": "City."},
                    "state": {"type": "string", "description": "State/province code."},
                    "postal_code": {"type": "string", "description": "Postal/ZIP code."},
                    "country_code": {"type": "string", "description": "Country code."},
                    "pickup_date": {"type": "string", "description": "Date YYYYMMDD."},
                    "ready_time": {"type": "string", "description": "Ready time HHMM."},
                    "close_time": {"type": "string", "description": "Close time HHMM."},
                    "contact_name": {"type": "string", "description": "Contact name for the pickup."},
                    "phone_number": {"type": "string", "description": "Contact phone number."},
                },
                "required": [
                    "address_line", "city", "state", "postal_code", "country_code", "pickup_date",
                    "ready_time", "close_time",
                ],
            },
            "handler": _bind_bridge(rate_pickup_tool, bridge),
        },
        {
            "name": "get_pickup_status",
            "description": "Get pending on-call pickup status for the UPS account.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "account_number": {
                        "type": "string",
                        "description": "UPS account number (optional, uses env fallback).",
                    },
                },
            },
            "handler": _bind_bridge(get_pickup_status_tool, bridge),
        },
        # ---------------------------------------------------------------
        # UPS MCP v2 — Location tools
        # ---------------------------------------------------------------
        {
            "name": "find_locations",
            "description": (
                "Find nearby UPS Access Points, retail stores, and service locations."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "location_type": {
                        "type": "string",
                        "description": "Type of location to search.",
                        "enum": ["access_point", "retail", "general"],
                    },
                    "address_line": {"type": "string", "description": "Street address."},
                    "city": {"type": "string", "description": "City."},
                    "state": {"type": "string", "description": "State/province code."},
                    "postal_code": {"type": "string", "description": "Postal/ZIP code."},
                    "country_code": {"type": "string", "description": "Country code."},
                    "radius": {
                        "type": "number",
                        "description": "Search radius (default 15 miles).",
                        "default": 15.0,
                    },
                    "unit_of_measure": {
                        "type": "string",
                        "description": "Distance unit.",
                        "enum": ["MI", "KM"],
                        "default": "MI",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum locations to return (1-50, default 10).",
                        "default": 10,
                    },
                },
                "required": [
                    "location_type", "address_line", "city",
                    "state", "postal_code", "country_code",
                ],
            },
            "handler": _bind_bridge(find_locations_tool, bridge),
        },
        {
            "name": "get_service_center_facilities",
            "description": "Find UPS service center drop-off locations.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City."},
                    "state": {"type": "string", "description": "State/province code."},
                    "postal_code": {"type": "string", "description": "Postal/ZIP code."},
                    "country_code": {"type": "string", "description": "Country code."},
                },
                "required": ["city", "state", "postal_code", "country_code"],
            },
            "handler": _bind_bridge(get_service_center_facilities_tool, bridge),
        },
        # ---------------------------------------------------------------
        # UPS MCP v2 — Paperless document tools
        # ---------------------------------------------------------------
        {
            "name": "request_document_upload",
            "description": (
                "Show an upload form in the chat for the user to attach a customs/trade document. "
                "Use this instead of asking for file paths. After the user attaches a file, "
                "you will receive a [DOCUMENT_ATTACHED] message — then call upload_paperless_document."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Message displayed above the upload form.",
                    },
                    "suggested_document_type": {
                        "type": "string",
                        "description": "Pre-select a document type code (e.g. '002' for Commercial Invoice).",
                    },
                },
                "required": [],
            },
            "handler": _bind_bridge(request_document_upload_tool, bridge),
        },
        {
            "name": "upload_paperless_document",
            "description": (
                "Upload a customs/trade document to UPS Forms History "
                "for paperless customs clearance. If the user attached a file "
                "via the upload form, file data is automatically available — "
                "only document_type is required."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_content_base64": {
                        "type": "string",
                        "description": "Base64-encoded file content. Auto-loaded from upload form when available.",
                    },
                    "file_name": {
                        "type": "string",
                        "description": "File name (e.g., 'invoice.pdf'). Auto-loaded from upload form when available.",
                    },
                    "file_format": {
                        "type": "string",
                        "description": "File format (pdf, doc, xls, etc.). Auto-loaded from upload form when available.",
                    },
                    "document_type": {
                        "type": "string",
                        "description": "UPS document type code ('002'=invoice, '003'=CO, etc.).",
                    },
                },
                "required": ["document_type"],
            },
            "handler": _bind_bridge(upload_paperless_document_tool, bridge),
        },
        {
            "name": "push_document_to_shipment",
            "description": "Attach a previously uploaded document to a shipment.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "Document ID from upload_paperless_document.",
                    },
                    "shipment_identifier": {
                        "type": "string",
                        "description": "1Z tracking number from create_shipment.",
                    },
                },
                "required": ["document_id", "shipment_identifier"],
            },
            "handler": _bind_bridge(push_document_to_shipment_tool, bridge),
        },
        {
            "name": "delete_paperless_document",
            "description": "Delete a document from UPS Forms History.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "Document ID from upload_paperless_document.",
                    },
                },
                "required": ["document_id"],
            },
            "handler": _bind_bridge(delete_paperless_document_tool, bridge),
        },
        # ---------------------------------------------------------------
        # UPS MCP v2 — Tracking tool
        # ---------------------------------------------------------------
        {
            "name": "track_package",
            "description": (
                "Track a UPS package by tracking number. Returns current status "
                "and activity history. Detects sandbox tracking number mismatches."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "tracking_number": {
                        "type": "string",
                        "description": "UPS tracking number (e.g., 1Z999AA10123456784).",
                    },
                },
                "required": ["tracking_number"],
            },
            "handler": _bind_bridge(track_package_tool, bridge),
        },
        # ---------------------------------------------------------------
        # UPS MCP v2 — Landed cost tool
        # ---------------------------------------------------------------

        {
            "name": "get_landed_cost",
            "description": (
                "Estimate duties, taxes, and fees for an international shipment. "
                "Useful for pre-flight cost estimation before shipping."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "currency_code": {
                        "type": "string",
                        "description": "ISO currency code (e.g., 'USD', 'EUR').",
                    },
                    "export_country_code": {
                        "type": "string",
                        "description": "Origin country code (e.g., 'US').",
                    },
                    "import_country_code": {
                        "type": "string",
                        "description": "Destination country code (e.g., 'GB').",
                    },
                    "commodities": {
                        "type": "array",
                        "description": "Commodity items with price, quantity, and optional hs_code.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "price": {"type": "number"},
                                "quantity": {"type": "integer"},
                                "hs_code": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["price", "quantity"],
                        },
                    },
                },
                "required": [
                    "currency_code", "export_country_code",
                    "import_country_code", "commodities",
                ],
            },
            "handler": _bind_bridge(get_landed_cost_tool, bridge),
        },
    ]

    if not interactive_shipping:
        return definitions

    # In interactive mode, expose status tools + interactive preview + v2 tools.
    # v2 tools work independently of data sources and are useful in both modes.
    interactive_allowed = {
        "get_job_status", "get_platform_status", "preview_interactive_shipment",
        # v2 tools — work independently of data source
        "schedule_pickup", "cancel_pickup", "rate_pickup", "get_pickup_status",
        "find_locations", "get_service_center_facilities",
        "request_document_upload", "upload_paperless_document",
        "push_document_to_shipment", "delete_paperless_document",
        "get_landed_cost",
        "track_package",
    }
    interactive_defs = [d for d in definitions if d["name"] in interactive_allowed]

    # Add the preview_interactive_shipment tool definition
    interactive_defs.append(
        {
            "name": "preview_interactive_shipment",
            "description": (
                "Preview a single interactive shipment. Auto-populates shipper from "
                "config, rates the shipment, creates a Job record, and displays "
                "the InteractivePreviewCard for user confirmation."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "ship_to_name": {
                        "type": "string",
                        "description": "Recipient full name.",
                    },
                    "ship_to_address1": {
                        "type": "string",
                        "description": "Recipient street address line 1.",
                    },
                    "ship_to_address2": {
                        "type": "string",
                        "description": "Recipient street address line 2 (optional).",
                    },
                    "ship_to_city": {
                        "type": "string",
                        "description": "Recipient city.",
                    },
                    "ship_to_state": {
                        "type": "string",
                        "description": (
                            "Recipient state/province code (e.g. CA, NY). "
                            "Required for some international destinations (e.g. GB)."
                        ),
                    },
                    "ship_to_zip": {
                        "type": "string",
                        "description": "Recipient postal/ZIP code.",
                    },
                    "ship_to_phone": {
                        "type": "string",
                        "description": "Recipient phone number (optional).",
                    },
                    "ship_to_country": {
                        "type": "string",
                        "description": "Recipient country code (default US).",
                        "default": "US",
                    },
                    "ship_to_attention_name": {
                        "type": "string",
                        "description": (
                            "Recipient attention/contact name override. "
                            "Optional override only: defaults to ship_to_name when omitted. "
                            "Do not ask user to confirm equality with recipient name."
                        ),
                    },
                    "shipment_description": {
                        "type": "string",
                        "description": "Description of goods, max 35 chars (required for international). Also accepts 'description' as alias.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Alias for shipment_description — description of goods for customs.",
                    },
                    "service": {
                        "type": "string",
                        "description": (
                            "UPS service name or code. ALWAYS extract and pass the user's "
                            "service preference (e.g. 'Ground', 'Next Day Air', '2nd Day Air', "
                            "'3 Day Select', 'UPS Standard'). If the user does not provide a "
                            "service, you may omit this field and the system will discover route-"
                            "available services via UPS Shop and pick a default for preview."
                        ),
                    },
                    "weight": {
                        "type": "number",
                        "description": "Package weight in lbs (default 1.0).",
                        "default": 1.0,
                    },
                    "packaging_type": {
                        "type": "string",
                        "description": "UPS packaging type name or code (optional).",
                    },
                    "command": {
                        "type": "string",
                        "description": "Original user command text.",
                    },
                    "ship_from": {
                        "type": "object",
                        "description": (
                            "Optional shipper address overrides. Accepts keys: "
                            "name, phone, address1, city, state, zip, country. "
                            "Overrides are merged on top of env-configured defaults."
                        ),
                    },
                    "commodities": {
                        "type": "array",
                        "description": (
                            "Commodity lines for international customs (required for "
                            "US->CA and US->MX)."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {
                                    "type": "string",
                                    "description": "Commodity description (max 35 chars).",
                                },
                                "commodity_code": {
                                    "type": "string",
                                    "description": "HS tariff/commodity code.",
                                },
                                "origin_country": {
                                    "type": "string",
                                    "description": "Country of origin (ISO 2-letter code).",
                                },
                                "quantity": {
                                    "type": "integer",
                                    "description": "Item quantity for this commodity line.",
                                },
                                "unit_value": {
                                    "type": "string",
                                    "description": "Monetary value per unit.",
                                },
                            },
                            "required": [
                                "description",
                                "commodity_code",
                                "origin_country",
                                "quantity",
                                "unit_value",
                            ],
                        },
                    },
                    "invoice_currency_code": {
                        "type": "string",
                        "description": "Invoice currency code (ISO 4217, e.g. USD, CAD).",
                    },
                    "invoice_monetary_value": {
                        "type": "string",
                        "description": "Invoice total monetary value.",
                    },
                    "reason_for_export": {
                        "type": "string",
                        "description": "Reason for export.",
                        "enum": [
                            "SALE",
                            "GIFT",
                            "SAMPLE",
                            "REPAIR",
                            "RETURN",
                            "INTERCOMPANY",
                        ],
                    },
                },
                "required": [
                    "ship_to_name",
                    "ship_to_address1",
                    "ship_to_city",
                    "ship_to_zip",
                    "command",
                ],
            },
            "handler": _bind_bridge(preview_interactive_shipment_tool, bridge),
        },
    )

    return interactive_defs


__all__ = ["get_all_tool_definitions"]
