from __future__ import annotations

from typing import Any

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.execution_targets import ExecutionTarget, TargetToolRequest
from src.hosted_mcp.server import ToolHandler


def build_execution_target_tool_handlers(
    execution_target: ExecutionTarget,
) -> dict[str, ToolHandler]:
    async def get_shipagent_status(
        context: AuthorizationContext,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return await execution_target.invoke(
            TargetToolRequest(
                account_id=context.account_id,
                provider_connection_id=context.provider_connection_id,
                provider_surface=context.provider_surface,
                tool_name="get_shipagent_status",
                arguments=arguments,
                correlation_id=str(
                    arguments.get("correlation_id") or "get_shipagent_status"
                ),
            )
        )

    return {"get_shipagent_status": get_shipagent_status}
