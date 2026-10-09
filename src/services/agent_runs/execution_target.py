"""Account-bound ExecutionTarget adapter for the synthetic source-free tracer."""

from src.control_plane.execution_targets import TargetToolRequest
from src.services.agent_runs.service import AgentRunService


class AgentRunExecutionTarget:
    def __init__(self, service: AgentRunService) -> None:
        self._service = service

    async def invoke(self, request: TargetToolRequest) -> dict[str, object]:
        if request.account_id != self._service.store.account_id:
            raise PermissionError("Execution Target is unavailable.")
        if request.tool_name == "submit_shipagent_task":
            return self._service.submit(
                connection_id=request.provider_connection_id,
                arguments=request.arguments,
            )
        if request.tool_name == "continue_shipagent_task":
            return self._service.continue_turn(
                connection_id=request.provider_connection_id,
                arguments=request.arguments,
            )
        if request.tool_name == "read_shipagent_run":
            return self._service.read(
                connection_id=request.provider_connection_id,
                run_reference=request.arguments["run_reference"],
            )
        if request.tool_name == "cancel_shipagent_run":
            return self._service.cancel(
                connection_id=request.provider_connection_id,
                run_reference=request.arguments["run_reference"],
            )
        raise PermissionError("Target tool is unavailable.")
