from __future__ import annotations

from typing import Protocol

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.relay.protocol import (
    ExecutionTargetStatus,
    RelayTargetState,
    ShipAgentStatus,
)
from src.control_plane.relay.registry import RelayDeviceRegistry

PUBLIC_STATUS_CAPABILITIES = frozenset(
    {
        "get_shipagent_status",
        "rate_shipment",
    }
)


class ExecutionTarget(Protocol):
    async def status(self, context: AuthorizationContext) -> ShipAgentStatus: ...


class LoopbackExecutionTarget:
    def __init__(
        self,
        *,
        capabilities: list[str] | None = None,
        execution_target_id: str = "loopback",
    ) -> None:
        self._capabilities = list(capabilities or [])
        self._execution_target_id = execution_target_id

    async def status(self, context: AuthorizationContext) -> ShipAgentStatus:
        return ShipAgentStatus(
            status="ok",
            execution_target=ExecutionTargetStatus(
                state=RelayTargetState.READY,
                execution_target_id=self._execution_target_id,
                device_id=None,
                capabilities=list(self._capabilities),
                message=None,
            ),
        )


class RelayExecutionTarget:
    def __init__(self, registry: RelayDeviceRegistry) -> None:
        self._registry = registry

    async def status(self, context: AuthorizationContext) -> ShipAgentStatus:
        heartbeat = await self._registry.get_active_heartbeat(context.account_id)
        if heartbeat is not None:
            return ShipAgentStatus(
                status="ok",
                execution_target=ExecutionTargetStatus(
                    state=heartbeat.state,
                    execution_target_id=heartbeat.execution_target_id,
                    device_id=heartbeat.device_id,
                    capabilities=[
                        capability
                        for capability in heartbeat.version.capabilities
                        if capability in PUBLIC_STATUS_CAPABILITIES
                    ],
                    message=None,
                ),
            )
        return ShipAgentStatus(
            status="unavailable",
            execution_target=ExecutionTargetStatus(
                state=RelayTargetState.OFFLINE,
                execution_target_id=None,
                device_id=None,
                capabilities=[],
                message="No active execution target connected.",
            ),
        )
