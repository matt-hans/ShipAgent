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
