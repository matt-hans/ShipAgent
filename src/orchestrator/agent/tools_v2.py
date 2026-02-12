"""Deterministic SDK tools for the orchestration agent.

Each tool wraps an existing service with a thin interface returning
MCP-compatible response dicts. No tool calls the LLM internally —
all operations are deterministic.

Tool response format:
    {"isError": False, "content": [{"type": "text", "text": "..."}]}
    {"isError": True,  "content": [{"type": "text", "text": "error msg"}]}

Example:
    result = await get_source_info_tool({})
    defs = get_all_tool_definitions()
"""

import json
import logging
from typing import Any

import sqlglot

from src.db.connection import get_db_context
from src.services.data_source_service import DataSourceService
from src.services.job_service import JobService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(data: Any) -> dict[str, Any]:
    """Build a successful tool response.

    Args:
        data: Serializable data to return.

    Returns:
        MCP tool response dict with isError=False.
    """
    return {
        "isError": False,
        "content": [{"type": "text", "text": json.dumps(data, default=str)}],
    }


def _err(message: str) -> dict[str, Any]:
    """Build an error tool response.

    Args:
        message: Human-readable error message.

    Returns:
        MCP tool response dict with isError=True.
    """
    return {
        "isError": True,
        "content": [{"type": "text", "text": message}],
    }


def _get_data_source_service() -> DataSourceService:
    """Get the singleton DataSourceService instance.

    Returns:
        The active DataSourceService.
    """
    return DataSourceService.get_instance()


# ---------------------------------------------------------------------------
# Data Source Tools
# ---------------------------------------------------------------------------


async def get_source_info_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Get metadata about the currently connected data source.

    Args:
        args: Empty dict (no arguments needed).

    Returns:
        Tool response with source_type, file_path, row_count, column count.
    """
    svc = _get_data_source_service()
    info = svc.get_source_info()
    if info is None:
        return _err("No data source connected. Ask the user to connect a CSV, Excel, or database source.")

    return _ok({
        "source_type": info.source_type,
        "file_path": info.file_path,
        "row_count": info.row_count,
        "column_count": len(info.columns),
    })


async def get_schema_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Get the column schema of the currently connected data source.

    Args:
        args: Empty dict (no arguments needed).

    Returns:
        Tool response with list of column definitions.
    """
    svc = _get_data_source_service()
    info = svc.get_source_info()
    if info is None:
        return _err("No data source connected.")

    columns = [
        {"name": col.name, "type": col.type, "nullable": col.nullable}
        for col in info.columns
    ]
    return _ok({"columns": columns})


async def fetch_rows_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Fetch rows from the connected data source with optional SQL filter.

    Args:
        args: Dict with optional 'where_clause' (str) and 'limit' (int).

    Returns:
        Tool response with matched rows and count.
    """
    svc = _get_data_source_service()
    where_clause = args.get("where_clause")
    limit = args.get("limit", 250)

    try:
        rows = await svc.get_rows_by_filter(where_clause=where_clause, limit=limit)
        return _ok({"row_count": len(rows), "rows": rows})
    except Exception as e:
        logger.error("fetch_rows_tool failed: %s", e)
        return _err(f"Failed to fetch rows: {e}")


# ---------------------------------------------------------------------------
# Filter Validation Tool
# ---------------------------------------------------------------------------


async def validate_filter_syntax_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Validate SQL WHERE clause syntax using sqlglot.

    Args:
        args: Dict with 'where_clause' (str).

    Returns:
        Tool response with valid=True/False and optional error message.
    """
    where_clause = args.get("where_clause", "")
    try:
        sqlglot.parse(f"SELECT * FROM t WHERE {where_clause}")
        return _ok({"valid": True, "where_clause": where_clause})
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError) as e:
        return _ok({"valid": False, "error": str(e), "where_clause": where_clause})


# ---------------------------------------------------------------------------
# Job Management Tools
# ---------------------------------------------------------------------------


async def create_job_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Create a new job in the state database.

    Args:
        args: Dict with 'name' (str) and 'command' (str).

    Returns:
        Tool response with job_id and status.
    """
    name = args.get("name", "Untitled Job")
    command = args.get("command", "")

    try:
        with get_db_context() as db:
            svc = JobService(db)
            job = svc.create_job(name=name, original_command=command)
            return _ok({"job_id": job.id, "status": job.status})
    except Exception as e:
        logger.error("create_job_tool failed: %s", e)
        return _err(f"Failed to create job: {e}")


async def get_job_status_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Get the summary/status of a job.

    Args:
        args: Dict with 'job_id' (str).

    Returns:
        Tool response with job summary metrics.
    """
    job_id = args.get("job_id", "")
    if not job_id:
        return _err("job_id is required")

    try:
        with get_db_context() as db:
            svc = JobService(db)
            summary = svc.get_job_summary(job_id)
            return _ok(summary)
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        logger.error("get_job_status_tool failed: %s", e)
        return _err(f"Failed to get job status: {e}")


# ---------------------------------------------------------------------------
# Batch Processing Tools
# ---------------------------------------------------------------------------


async def _run_batch_preview(job_id: str) -> dict[str, Any]:
    """Internal helper — run batch preview via BatchEngine.

    Separated for testability. In production this creates a BatchEngine
    and calls preview(). The caller (batch_preview_tool) can be tested
    by patching this function.

    Args:
        job_id: Job UUID.

    Returns:
        Preview result dict from BatchEngine.
    """
    # Import here to avoid circular imports and heavy setup in tests
    import os

    from src.services.batch_engine import BatchEngine
    from src.services.ups_payload_builder import build_shipper_from_env
    from src.services.ups_service import UPSService

    account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "")
    ups = UPSService()
    shipper = build_shipper_from_env()

    with get_db_context() as db:
        engine = BatchEngine(
            ups_service=ups,
            db_session=db,
            account_number=account_number,
        )
        svc = JobService(db)
        rows = svc.get_rows(job_id)
        result = await engine.preview(
            job_id=job_id,
            rows=rows,
            shipper=shipper,
        )
    return result


async def batch_preview_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Run batch preview (rate all rows) for a job.

    Args:
        args: Dict with 'job_id' (str).

    Returns:
        Tool response with preview data (row count, estimated cost, etc.).
    """
    job_id = args.get("job_id", "")
    if not job_id:
        return _err("job_id is required")

    try:
        result = await _run_batch_preview(job_id)
        return _ok(result)
    except Exception as e:
        logger.error("batch_preview_tool failed: %s", e)
        return _err(f"Batch preview failed: {e}")


async def batch_execute_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Execute a confirmed batch job (create shipments).

    Requires explicit approval. Returns error if approved is not True.

    Args:
        args: Dict with 'job_id' (str) and 'approved' (bool).

    Returns:
        Tool response with execution status, or error if not approved.
    """
    job_id = args.get("job_id", "")
    approved = args.get("approved", False)

    if not approved:
        return _err(
            "Batch execution requires user approval. "
            "Set approved=True only after the user has confirmed the preview."
        )

    if not job_id:
        return _err("job_id is required")

    try:
        import os

        from src.services.batch_engine import BatchEngine
        from src.services.ups_payload_builder import build_shipper_from_env
        from src.services.ups_service import UPSService

        account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "")
        ups = UPSService()
        shipper = build_shipper_from_env()

        with get_db_context() as db:
            engine = BatchEngine(
                ups_service=ups,
                db_session=db,
                account_number=account_number,
            )
            svc = JobService(db)
            rows = svc.get_rows(job_id)
            result = await engine.execute(
                job_id=job_id,
                rows=rows,
                shipper=shipper,
            )
        return _ok(result)
    except Exception as e:
        logger.error("batch_execute_tool failed: %s", e)
        return _err(f"Batch execution failed: {e}")


# ---------------------------------------------------------------------------
# Platform Tools
# ---------------------------------------------------------------------------


async def get_platform_status_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Check which external platforms are connected.

    Args:
        args: Empty dict (no arguments needed).

    Returns:
        Tool response with platform connection statuses.
    """
    platforms: dict[str, Any] = {}

    # Check Shopify
    try:
        from src.mcp.external_sources.clients.shopify import ShopifyClient

        client = ShopifyClient()
        platforms["shopify"] = {
            "connected": client.is_configured(),
            "shop_name": getattr(client, "shop_name", None),
        }
    except Exception:
        platforms["shopify"] = {"connected": False}

    return _ok({"platforms": platforms})


# ---------------------------------------------------------------------------
# Tool Definitions Registry
# ---------------------------------------------------------------------------


def get_all_tool_definitions() -> list[dict[str, Any]]:
    """Return all tool definitions for the orchestration agent.

    Each definition includes name, description, input_schema, and handler.

    Returns:
        List of tool definition dicts.
    """
    return [
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
            "name": "fetch_rows",
            "description": "Fetch rows from the data source, optionally filtered by a SQL WHERE clause.",
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
                },
            },
            "handler": fetch_rows_tool,
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
            "handler": batch_preview_tool,
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
    ]
