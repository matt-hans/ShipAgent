"""Orchestrator-native tools for the SDK MCP server.

These tools run in-process within the orchestration agent, providing:
- Natural language command processing (process_command)
- Job state queries (get_job_status)
- Tool discovery (list_tools)
- Batch preview (batch_preview)
- Batch execution (batch_execute)
- Mode switching (batch_set_mode)
- Crash recovery (batch_resume)

Per CONTEXT.md Decision 2: The orchestrator exposes its own tools beyond
MCP passthrough for operations that need access to orchestrator state.
"""

import json
from dataclasses import asdict
from typing import Any

from src.orchestrator.nl_engine.engine import NLMappingEngine
from src.orchestrator.models.filter import ColumnInfo
from src.orchestrator.batch import (
    ExecutionMode,
    SessionModeManager,
    PreviewGenerator,
    BatchExecutor,
    BatchPreview,
    BatchResult,
)


# Singleton engine instance (created on first use)
_engine: NLMappingEngine | None = None

# Singleton mode manager for session-level execution mode
_mode_manager: SessionModeManager | None = None


def _get_engine() -> NLMappingEngine:
    """Get or create the NLMappingEngine singleton."""
    global _engine
    if _engine is None:
        _engine = NLMappingEngine(max_correction_attempts=3)
    return _engine


def _get_mode_manager() -> SessionModeManager:
    """Get or create the SessionModeManager singleton."""
    global _mode_manager
    if _mode_manager is None:
        _mode_manager = SessionModeManager()
    return _mode_manager


def reset_mode_manager() -> None:
    """Reset the mode manager singleton (for testing)."""
    global _mode_manager
    if _mode_manager is not None:
        _mode_manager.reset()
    _mode_manager = None


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
            {"name": "batch_preview", "description": "Generate batch preview with cost estimates"},
            {"name": "batch_execute", "description": "Execute batch shipments"},
            {"name": "batch_set_mode", "description": "Set execution mode (confirm/auto)"},
            {"name": "batch_resume", "description": "Handle interrupted job recovery"},
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


# =============================================================================
# Batch Tools (BATCH-02 through BATCH-06)
# =============================================================================


async def batch_preview_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Generate batch preview with cost estimates.

    Creates a preview of the batch job showing the first 20 rows with
    individual rate quotes, and aggregate statistics for remaining rows.
    Per CONTEXT.md Decision 1.

    Args:
        args: Dict with:
            - job_id (str): UUID of the job
            - filter_clause (str): SQL WHERE clause for row selection
            - mapping_template (str): Jinja2 template for UPS payload
            - shipper_info (dict): Shipper address and account info
            - data_mcp_call (callable, optional): Function to call Data MCP tools
            - ups_mcp_call (callable, optional): Function to call UPS MCP tools

    Returns:
        MCP response with BatchPreview as JSON.
    """
    job_id = args.get("job_id")
    filter_clause = args.get("filter_clause", "")
    mapping_template = args.get("mapping_template", "")
    shipper_info = args.get("shipper_info", {})

    # MCP call functions are injected for testing; in production they come from agent
    data_mcp_call = args.get("data_mcp_call")
    ups_mcp_call = args.get("ups_mcp_call")

    if not job_id:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": "job_id is required"})}],
            "isError": True,
        }

    if not mapping_template:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": "mapping_template is required"})}],
            "isError": True,
        }

    if data_mcp_call is None or ups_mcp_call is None:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": "MCP call functions not provided"})}],
            "isError": True,
        }

    try:
        generator = PreviewGenerator(
            data_mcp_call=data_mcp_call,
            ups_mcp_call=ups_mcp_call,
        )

        preview = await generator.generate_preview(
            job_id=job_id,
            filter_clause=filter_clause,
            mapping_template=mapping_template,
            shipper_info=shipper_info,
        )

        # Convert dataclass to dict for JSON serialization
        preview_dict = asdict(preview)

        return {
            "content": [{"type": "text", "text": json.dumps(preview_dict, indent=2)}]
        }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
            "isError": True,
        }


BATCH_PREVIEW_SCHEMA = {
    "job_id": {"type": "string", "description": "UUID of the job"},
    "filter_clause": {"type": "string", "description": "SQL WHERE clause for row selection"},
    "mapping_template": {"type": "string", "description": "Jinja2 template for UPS payload"},
    "shipper_info": {"type": "object", "description": "Shipper address and account info"},
}


# Import AuditService for batch_execute_tool
from src.services.audit_service import AuditService


async def batch_execute_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Execute batch shipments.

    Runs the batch executor with fail-fast behavior and per-row state
    checkpoints for crash recovery. In CONFIRM mode, requires prior
    preview approval. In AUTO mode, executes immediately.

    Args:
        args: Dict with:
            - job_id (str): UUID of the job
            - mapping_template (str): Jinja2 template for UPS payload
            - shipper_info (dict): Shipper address and account info
            - approved (bool, optional): True if preview was approved (required for CONFIRM mode)
            - source_name (str, optional): Data source name (default "default")
            - data_mcp_call (callable, optional): Function to call Data MCP tools
            - ups_mcp_call (callable, optional): Function to call UPS MCP tools

    Returns:
        MCP response with BatchResult as JSON.
    """
    job_id = args.get("job_id")
    mapping_template = args.get("mapping_template", "")
    shipper_info = args.get("shipper_info", {})
    approved = args.get("approved", False)
    source_name = args.get("source_name", "default")

    # MCP call functions are injected for testing; in production they come from agent
    data_mcp_call = args.get("data_mcp_call")
    ups_mcp_call = args.get("ups_mcp_call")

    if not job_id:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": "job_id is required"})}],
            "isError": True,
        }

    if not mapping_template:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": "mapping_template is required"})}],
            "isError": True,
        }

    if data_mcp_call is None or ups_mcp_call is None:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": "MCP call functions not provided"})}],
            "isError": True,
        }

    # Check execution mode
    mode_manager = _get_mode_manager()

    # In CONFIRM mode, require approval
    if mode_manager.mode == ExecutionMode.CONFIRM and not approved:
        return {
            "content": [{"type": "text", "text": json.dumps({
                "error": "Preview approval required in CONFIRM mode. Set approved=True or switch to AUTO mode."
            })}],
            "isError": True,
        }

    try:
        # Lock mode during execution
        mode_manager.lock()

        with get_db_context() as session:
            job_service = JobService(session)
            audit_service = AuditService(session)

            executor = BatchExecutor(
                job_service=job_service,
                audit_service=audit_service,
                data_mcp_call=data_mcp_call,
                ups_mcp_call=ups_mcp_call,
            )

            result = await executor.execute(
                job_id=job_id,
                mapping_template=mapping_template,
                shipper_info=shipper_info,
                source_name=source_name,
            )

        # Convert dataclass to dict for JSON serialization
        result_dict = asdict(result)

        return {
            "content": [{"type": "text", "text": json.dumps(result_dict, indent=2)}]
        }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
            "isError": True,
        }
    finally:
        # Always unlock mode after execution
        mode_manager.unlock()


BATCH_EXECUTE_SCHEMA = {
    "job_id": {"type": "string", "description": "UUID of the job"},
    "mapping_template": {"type": "string", "description": "Jinja2 template for UPS payload"},
    "shipper_info": {"type": "object", "description": "Shipper address and account info"},
    "approved": {"type": "boolean", "description": "True if preview was approved (required for CONFIRM mode)"},
    "source_name": {"type": "string", "description": "Data source name (default 'default')"},
}


async def batch_set_mode_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Set execution mode for this session.

    Changes the batch execution mode between CONFIRM (preview before execute)
    and AUTO (immediate execution). Cannot change mode while a batch is executing.

    Args:
        args: Dict with:
            - mode (str): "confirm" or "auto"

    Returns:
        MCP response with new mode.
    """
    mode_str = args.get("mode", "").lower()

    if mode_str not in ("confirm", "auto"):
        return {
            "content": [{"type": "text", "text": json.dumps({
                "error": f"Invalid mode: {mode_str}. Must be 'confirm' or 'auto'."
            })}],
            "isError": True,
        }

    try:
        mode = ExecutionMode.CONFIRM if mode_str == "confirm" else ExecutionMode.AUTO
        mode_manager = _get_mode_manager()
        mode_manager.set_mode(mode)

        return {
            "content": [{"type": "text", "text": json.dumps({
                "mode": mode.value,
                "message": f"Execution mode set to {mode.value.upper()}"
            }, indent=2)}]
        }

    except ValueError as e:
        # Mode locked during execution
        return {
            "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
            "isError": True,
        }


BATCH_SET_MODE_SCHEMA = {
    "mode": {"type": "string", "description": "Execution mode: 'confirm' or 'auto'"},
}


async def batch_resume_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Check for and handle interrupted jobs.

    On startup or when called without a choice, checks for jobs in 'running'
    state that may have been interrupted by a crash. If found, presents
    recovery options (resume, restart, cancel).

    When called with a choice, performs the selected recovery action.

    Args:
        args: Dict with:
            - choice (str, optional): "resume", "restart", or "cancel"
            - job_id (str, optional): Job ID if handling specific job

    Returns:
        MCP response with recovery info or action result.
    """
    choice = args.get("choice")
    job_id = args.get("job_id")

    try:
        with get_db_context() as session:
            job_service = JobService(session)

            if choice is None:
                # Check for interrupted jobs
                from src.db.models import JobStatus
                # Query for jobs in running state (potentially interrupted)
                from sqlalchemy import select
                from src.db.models import Job

                stmt = select(Job).where(Job.status == JobStatus.running.value)
                result = session.execute(stmt)
                interrupted_jobs = result.scalars().all()

                if not interrupted_jobs:
                    return {
                        "content": [{"type": "text", "text": json.dumps({
                            "interrupted_jobs": [],
                            "message": "No interrupted jobs found."
                        }, indent=2)}]
                    }

                # Build recovery info for each job
                job_infos = []
                for job in interrupted_jobs:
                    summary = job_service.get_job_summary(str(job.id))
                    job_infos.append({
                        "job_id": str(job.id),
                        "name": job.name,
                        "completed_rows": summary["successful_rows"],
                        "total_rows": summary["total_rows"],
                        "remaining_rows": summary["total_rows"] - summary["successful_rows"],
                        "prompt": f"Job '{job.name}' was interrupted at row {summary['successful_rows'] + 1}/{summary['total_rows']}. Resume, restart, or cancel?"
                    })

                return {
                    "content": [{"type": "text", "text": json.dumps({
                        "interrupted_jobs": job_infos,
                        "options": ["resume", "restart", "cancel"],
                        "message": "Interrupted jobs found. Provide 'choice' to handle."
                    }, indent=2)}]
                }

            else:
                # Handle recovery choice
                if not job_id:
                    return {
                        "content": [{"type": "text", "text": json.dumps({
                            "error": "job_id required when providing a choice"
                        })}],
                        "isError": True,
                    }

                choice = choice.lower()
                if choice not in ("resume", "restart", "cancel"):
                    return {
                        "content": [{"type": "text", "text": json.dumps({
                            "error": f"Invalid choice: {choice}. Must be 'resume', 'restart', or 'cancel'."
                        })}],
                        "isError": True,
                    }

                job = job_service.get_job(job_id)
                if job is None:
                    return {
                        "content": [{"type": "text", "text": json.dumps({
                            "error": f"Job {job_id} not found"
                        })}],
                        "isError": True,
                    }

                from src.db.models import JobStatus

                if choice == "resume":
                    # Keep job in running state, return info for executor to continue
                    pending_rows = job_service.get_pending_rows(job_id)
                    return {
                        "content": [{"type": "text", "text": json.dumps({
                            "action": "resume",
                            "job_id": job_id,
                            "pending_rows": len(pending_rows),
                            "message": f"Ready to resume job '{job.name}' with {len(pending_rows)} remaining rows."
                        }, indent=2)}]
                    }

                elif choice == "restart":
                    # Reset all rows to pending and reset job counts
                    job_service.reset_job_for_restart(job_id)
                    return {
                        "content": [{"type": "text", "text": json.dumps({
                            "action": "restart",
                            "job_id": job_id,
                            "message": f"Job '{job.name}' reset for restart. All rows set to pending."
                        }, indent=2)}]
                    }

                elif choice == "cancel":
                    # Mark job as cancelled
                    job_service.update_status(job_id, JobStatus.cancelled)
                    return {
                        "content": [{"type": "text", "text": json.dumps({
                            "action": "cancel",
                            "job_id": job_id,
                            "message": f"Job '{job.name}' cancelled."
                        }, indent=2)}]
                    }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
            "isError": True,
        }

    # Should not reach here, but return error for safety
    return {
        "content": [{"type": "text", "text": json.dumps({"error": "Unexpected state"})}],
        "isError": True,
    }


BATCH_RESUME_SCHEMA = {
    "choice": {"type": "string", "description": "Recovery choice: 'resume', 'restart', or 'cancel'"},
    "job_id": {"type": "string", "description": "Job ID for recovery action"},
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
        {
            "name": "batch_preview",
            "description": "Generate batch preview with cost estimates before execution",
            "schema": BATCH_PREVIEW_SCHEMA,
            "function": batch_preview_tool,
        },
        {
            "name": "batch_execute",
            "description": "Execute batch shipments with fail-fast and crash recovery",
            "schema": BATCH_EXECUTE_SCHEMA,
            "function": batch_execute_tool,
        },
        {
            "name": "batch_set_mode",
            "description": "Set execution mode (confirm or auto) for this session",
            "schema": BATCH_SET_MODE_SCHEMA,
            "function": batch_set_mode_tool,
        },
        {
            "name": "batch_resume",
            "description": "Check for and handle interrupted jobs after crash",
            "schema": BATCH_RESUME_SCHEMA,
            "function": batch_resume_tool,
        },
    ]


__all__ = [
    # Existing exports
    "process_command_tool",
    "get_job_status_tool",
    "list_tools_tool",
    "get_orchestrator_tools",
    "PROCESS_COMMAND_SCHEMA",
    "GET_JOB_STATUS_SCHEMA",
    "LIST_TOOLS_SCHEMA",
    # New batch exports
    "batch_preview_tool",
    "batch_execute_tool",
    "batch_set_mode_tool",
    "batch_resume_tool",
    "BATCH_PREVIEW_SCHEMA",
    "BATCH_EXECUTE_SCHEMA",
    "BATCH_SET_MODE_SCHEMA",
    "BATCH_RESUME_SCHEMA",
    # Testing utilities
    "reset_mode_manager",
]
