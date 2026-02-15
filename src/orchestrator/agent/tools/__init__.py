"""Agent tool registration — canonical entrypoint.

Imports handler functions from submodules and assembles tool definition
lists for the orchestration agent.
"""

from typing import Any

from src.orchestrator.agent.tools.core import EventEmitterBridge, _bind_bridge
from src.orchestrator.agent.tools.data import (
    connect_shopify_tool,
    fetch_rows_tool,
    get_platform_status_tool,
    get_schema_tool,
    get_source_info_tool,
    validate_filter_syntax_tool,
)
from src.orchestrator.agent.tools.interactive import (
    preview_interactive_shipment_tool,
)
from src.orchestrator.agent.tools.pipeline import (
    add_rows_to_job_tool,
    batch_execute_tool,
    batch_preview_tool,
    create_job_tool,
    get_job_status_tool,
    ship_command_pipeline_tool,
)


def get_all_tool_definitions(
    event_bridge: EventEmitterBridge | None = None,
    interactive_shipping: bool = False,
) -> list[dict[str, Any]]:
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
                    "where_clause": {
                        "type": "string",
                        "description": (
                            "Optional SQL WHERE clause without the 'WHERE' keyword. "
                            "Omit to ship all rows."
                        ),
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
                "Fetch rows from the data source and return a compact fetch_id "
                "reference for downstream tools. Avoid sending full row arrays "
                "through model context unless explicitly needed."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "where_clause": {
                        "type": "string",
                        "description": "SQL WHERE clause without the 'WHERE' keyword. Omit for all rows.",
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
            "name": "validate_filter_syntax",
            "description": "Validate a SQL WHERE clause for syntax correctness before using it.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "where_clause": {
                        "type": "string",
                        "description": "SQL WHERE clause to validate.",
                    },
                },
                "required": ["where_clause"],
            },
            "handler": validate_filter_syntax_tool,
        },
        {
            "name": "create_job",
            "description": "Create a new shipping job in the state database.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Human-readable job name.",
                    },
                    "command": {
                        "type": "string",
                        "description": "The original user command.",
                    },
                },
                "required": ["name", "command"],
            },
            "handler": create_job_tool,
        },
        {
            "name": "add_rows_to_job",
            "description": (
                "Add fetched rows to a job. Call this AFTER create_job and "
                "BEFORE batch_preview. Prefer passing fetch_id from fetch_rows "
                "instead of full rows for faster execution."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job UUID from create_job.",
                    },
                    "rows": {
                        "type": "array",
                        "description": (
                            "Optional full row array from fetch_rows. Prefer fetch_id."
                        ),
                        "items": {"type": "object"},
                    },
                    "fetch_id": {
                        "type": "string",
                        "description": (
                            "Preferred compact reference returned by fetch_rows."
                        ),
                    },
                },
                "required": ["job_id"],
            },
            "handler": _bind_bridge(add_rows_to_job_tool, bridge),
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
            "name": "batch_preview",
            "description": "Run batch preview (rate all rows) for a job. Shows estimated costs before execution.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job UUID to preview.",
                    },
                },
                "required": ["job_id"],
            },
            "handler": _bind_bridge(batch_preview_tool, bridge),
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
    ]

    if not interactive_shipping:
        return definitions

    # In interactive mode, expose only status tools + interactive preview
    interactive_allowed = {"get_job_status", "get_platform_status", "preview_interactive_shipment"}
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
                        "description": "Recipient state/province code (e.g. CA, NY).",
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
                        "description": "Recipient attention name (required for international).",
                    },
                    "shipment_description": {
                        "type": "string",
                        "description": "Description of goods, max 35 chars (required for international).",
                    },
                    "service": {
                        "type": "string",
                        "description": (
                            "UPS service name or code. ALWAYS extract and pass the user's "
                            "service preference (e.g. 'Ground', 'Next Day Air', '2nd Day Air', "
                            "'3 Day Select', 'UPS Standard'). Only use 'Ground' when the user "
                            "explicitly says Ground or does not mention any service."
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
