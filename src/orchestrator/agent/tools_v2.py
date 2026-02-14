"""TEMPORARY BARREL — removal target: 2026-03-14

All new imports should use individual tool submodules directly:
    from src.orchestrator.agent.tools import get_all_tool_definitions
    from src.orchestrator.agent.tools.core import EventEmitterBridge
    from src.orchestrator.agent.tools.pipeline import batch_preview_tool
    etc.

After the removal date, update all consumers and delete this file.
"""

# Re-export the tool registry entrypoint
from src.orchestrator.agent.tools import get_all_tool_definitions

# Re-export core utilities (used by client.py, main.py, tests)
from src.orchestrator.agent.tools.core import (
    EventEmitterBridge,
    _bind_bridge,
    _emit_event,
    _emit_preview_ready,
    _enrich_preview_rows,
    _get_ups_client,
    _reset_ups_client,
    shutdown_cached_ups_client,
)

# Re-export data tool handlers (used by tests)
from src.orchestrator.agent.tools.data import (
    connect_shopify_tool,
    fetch_rows_tool,
    get_platform_status_tool,
    get_schema_tool,
    get_source_info_tool,
    validate_filter_syntax_tool,
)

# Re-export pipeline tool handlers (used by tests)
from src.orchestrator.agent.tools.pipeline import (
    add_rows_to_job_tool,
    batch_execute_tool,
    batch_preview_tool,
    create_job_tool,
    get_job_status_tool,
    ship_command_pipeline_tool,
)

# Re-export interactive tool handlers (used by tests)
from src.orchestrator.agent.tools.interactive import (
    _mask_account,
    _normalize_ship_from,
    preview_interactive_shipment_tool,
)

__all__ = [
    "get_all_tool_definitions",
    "EventEmitterBridge",
    "shutdown_cached_ups_client",
    "_bind_bridge",
]
