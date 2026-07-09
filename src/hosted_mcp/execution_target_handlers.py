from __future__ import annotations

from typing import Any

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.execution_targets import ExecutionTarget
from src.hosted_mcp.server import ToolHandler


def build_execution_target_tool_handlers(
    execution_target: ExecutionTarget,
) -> dict[str, ToolHandler]:
    async def get_shipagent_status(
        context: AuthorizationContext,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        status = await execution_target.status(context, arguments)
        return status.model_dump(mode="json", by_alias=True)

    return {"get_shipagent_status": get_shipagent_status}
