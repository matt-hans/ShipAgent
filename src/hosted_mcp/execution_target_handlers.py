from __future__ import annotations

from typing import Any

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.execution_targets import ExecutionTarget, TargetToolRequest
from src.hosted_mcp.server import ToolHandler


def project_status_for_provider(status: dict[str, Any]) -> dict[str, Any]:
    """Reduce a target status to provider-visible fields (no target id or free text)."""
    target = status["executionTarget"]
    return {
        "status": status["status"],
        "executionTarget": {
            "state": target["state"],
            "capabilities": list(target["capabilities"]),
        },
    }


def build_execution_target_tool_handlers(
    execution_target: ExecutionTarget,
) -> dict[str, ToolHandler]:
    async def get_shipagent_status(
        context: AuthorizationContext,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        status = await execution_target.invoke(
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
        return project_status_for_provider(status)

    def run_handler(tool_name: str) -> ToolHandler:
        async def invoke(
            context: AuthorizationContext, arguments: dict[str, Any]
        ) -> dict[str, Any]:
            return await execution_target.invoke(
                TargetToolRequest(
                    account_id=context.account_id,
                    provider_connection_id=context.provider_connection_id,
                    provider_surface=context.provider_surface,
                    tool_name=tool_name,
                    arguments=arguments,
                    correlation_id=tool_name,
                )
            )

        return invoke

    return {
        "get_shipagent_status": get_shipagent_status,
        "submit_shipagent_task": run_handler("submit_shipagent_task"),
        "read_shipagent_run": run_handler("read_shipagent_run"),
    }
