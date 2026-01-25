"""Orchestrator-native tools for the SDK MCP server.

These tools run in-process within the orchestration agent, providing:
- Natural language command processing (process_command)
- Job state queries (get_job_status)
- Tool discovery (list_tools)

Per CONTEXT.md Decision 2: The orchestrator exposes its own tools beyond
MCP passthrough for operations that need access to orchestrator state.
"""

import json
from typing import Any

from src.orchestrator.nl_engine.engine import NLMappingEngine
from src.orchestrator.models.filter import ColumnInfo


# Singleton engine instance (created on first use)
_engine: NLMappingEngine | None = None


def _get_engine() -> NLMappingEngine:
    """Get or create the NLMappingEngine singleton."""
    global _engine
    if _engine is None:
        _engine = NLMappingEngine(max_correction_attempts=3)
    return _engine


async def process_command_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Process a natural language shipping command.

    This tool wraps the Phase 4 NLMappingEngine to parse user commands
    and generate structured outputs (intent, filters, templates).

    Args:
        args: Dict with:
            - command (str): Natural language command like "Ship California orders via Ground"
            - source_schema (list): List of column info dicts with 'name' and 'type' keys
            - example_row (dict, optional): Example row data for template validation
            - user_mappings (list, optional): User-confirmed field mappings

    Returns:
        MCP tool response with command processing results.
    """
    command = args.get("command", "")
    schema_dicts = args.get("source_schema", [])
    example_row = args.get("example_row")
    user_mappings = args.get("user_mappings")

    # Convert schema dicts to ColumnInfo objects
    source_schema = [
        ColumnInfo(name=col["name"], type=col.get("type", "string"))
        for col in schema_dicts
    ]

    engine = _get_engine()
    result = await engine.process_command(
        command=command,
        source_schema=source_schema,
        example_row=example_row,
        user_mappings=user_mappings,
    )

    # Convert to MCP response format
    return {
        "content": [{
            "type": "text",
            "text": json.dumps(result.model_dump(mode="json"), indent=2, default=str)
        }]
    }


PROCESS_COMMAND_SCHEMA = {
    "command": {"type": "string", "description": "Natural language shipping command"},
    "source_schema": {"type": "array", "description": "List of column info dicts with 'name' and 'type'"},
    "example_row": {"type": "object", "description": "Optional example row for validation"},
    "user_mappings": {"type": "array", "description": "Optional user-confirmed field mappings"},
}


# Import JobService dependencies for get_job_status
from src.services.job_service import JobService
from src.db.connection import get_db_context


async def get_job_status_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Get the status of a shipping job.

    Queries the state database for job information including
    status, row counts, and error details.

    Args:
        args: Dict with:
            - job_id (str): UUID of the job to query

    Returns:
        MCP tool response with job status details.
    """
    job_id = args.get("job_id")

    if not job_id:
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({"error": "job_id is required"})
            }],
            "isError": True
        }

    try:
        # Use sync context manager - JobService uses sync Session
        with get_db_context() as session:
            job_service = JobService(session)
            job = job_service.get_job(job_id)

            if job is None:
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({"error": f"Job {job_id} not found"})
                    }],
                    "isError": True
                }

            # Build status response
            status = {
                "job_id": str(job.id),
                "status": job.status,
                "name": job.name,
                "original_command": job.original_command,
                "total_rows": job.total_rows,
                "processed_rows": job.processed_rows,
                "successful_rows": job.successful_rows,
                "failed_rows": job.failed_rows,
                "error_code": job.error_code,
                "error_message": job.error_message,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
                "started_at": job.started_at,
                "completed_at": job.completed_at,
            }

            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps(status, indent=2, default=str)
                }]
            }

    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({"error": str(e)})
            }],
            "isError": True
        }


GET_JOB_STATUS_SCHEMA = {
    "job_id": {"type": "string", "description": "UUID of the job to query"},
}


async def list_tools_tool(args: dict[str, Any]) -> dict[str, Any]:
    """List all available tools across MCPs and orchestrator.

    Returns a summary of available tools organized by namespace.
    For detailed tool schemas, Claude can inspect individual tools.

    Args:
        args: Dict with:
            - namespace (str, optional): Filter to specific namespace ("data", "ups", "orchestrator")

    Returns:
        MCP tool response listing available tools.
    """
    namespace = args.get("namespace")

    # Orchestrator tools (always available)
    tools = {
        "orchestrator": [
            {"name": "process_command", "description": "Process natural language shipping command"},
            {"name": "get_job_status", "description": "Get shipping job status"},
            {"name": "list_tools", "description": "List available tools"},
        ],
        "data": [
            {"name": "import_csv", "description": "Import CSV file"},
            {"name": "import_excel", "description": "Import Excel file"},
            {"name": "import_database", "description": "Import from database"},
            {"name": "list_sheets", "description": "List Excel sheets"},
            {"name": "list_tables", "description": "List database tables"},
            {"name": "get_schema", "description": "Get data schema"},
            {"name": "override_column_type", "description": "Override column type"},
            {"name": "get_row", "description": "Get single row"},
            {"name": "get_rows_by_filter", "description": "Get filtered rows"},
            {"name": "query_data", "description": "Execute SQL query"},
            {"name": "compute_checksums", "description": "Compute row checksums"},
            {"name": "verify_checksum", "description": "Verify row checksum"},
        ],
        "ups": [
            {"name": "rating_quote", "description": "Get shipping rate quote"},
            {"name": "rating_shop", "description": "Compare shipping rates"},
            {"name": "shipping_create", "description": "Create shipment"},
            {"name": "shipping_void", "description": "Void shipment"},
            {"name": "shipping_get_label", "description": "Get shipping label"},
            {"name": "address_validate", "description": "Validate address"},
        ],
    }

    if namespace:
        if namespace not in tools:
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "error": f"Unknown namespace: {namespace}",
                        "available": list(tools.keys())
                    })
                }],
                "isError": True
            }
        tools = {namespace: tools[namespace]}

    return {
        "content": [{
            "type": "text",
            "text": json.dumps(tools, indent=2)
        }]
    }


LIST_TOOLS_SCHEMA = {
    "namespace": {"type": "string", "description": "Optional filter by namespace (data, ups, orchestrator)"},
}


def get_orchestrator_tools() -> list[dict[str, Any]]:
    """Get list of orchestrator tool definitions for SDK MCP server registration.

    Returns list of dicts with:
    - name: Tool name
    - description: Tool description
    - schema: Parameter schema
    - function: Async function to execute

    Used by create_sdk_mcp_server() in Plan 04.
    """
    return [
        {
            "name": "process_command",
            "description": "Process a natural language shipping command into structured intent and templates",
            "schema": PROCESS_COMMAND_SCHEMA,
            "function": process_command_tool,
        },
        {
            "name": "get_job_status",
            "description": "Get the status of a shipping job by ID",
            "schema": GET_JOB_STATUS_SCHEMA,
            "function": get_job_status_tool,
        },
        {
            "name": "list_tools",
            "description": "List all available tools across MCPs and orchestrator",
            "schema": LIST_TOOLS_SCHEMA,
            "function": list_tools_tool,
        },
    ]


__all__ = [
    "process_command_tool",
    "get_job_status_tool",
    "list_tools_tool",
    "get_orchestrator_tools",
    "PROCESS_COMMAND_SCHEMA",
    "GET_JOB_STATUS_SCHEMA",
    "LIST_TOOLS_SCHEMA",
]
