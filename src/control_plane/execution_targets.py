from __future__ import annotations

from typing import Any, Protocol

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.relay.invocations import (
    NoLiveRelaySession,
    RelayInvocationBroker,
    RelayInvocationTimeout,
)
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
    async def status(
        self,
        context: AuthorizationContext,
        arguments: dict[str, Any] | None = None,
    ) -> ShipAgentStatus: ...


class LoopbackExecutionTarget:
    def __init__(
        self,
        *,
        capabilities: list[str] | None = None,
        execution_target_id: str = "loopback",
    ) -> None:
        self._capabilities = list(capabilities or [])
        self._execution_target_id = execution_target_id

    async def status(
        self,
        context: AuthorizationContext,
        arguments: dict[str, Any] | None = None,
    ) -> ShipAgentStatus:
        return ShipAgentStatus(
            status=RelayTargetState.READY,
            execution_target=ExecutionTargetStatus(
                state=RelayTargetState.READY,
                target_id=self._execution_target_id,
                capabilities=list(self._capabilities),
                message=None,
            ),
        )


class RelayExecutionTarget:
    def __init__(
        self,
        registry: RelayDeviceRegistry,
        invocation_broker: RelayInvocationBroker | None = None,
    ) -> None:
        self._registry = registry
        self._invocation_broker = invocation_broker or RelayInvocationBroker()

    async def status(
        self,
        context: AuthorizationContext,
        arguments: dict[str, Any] | None = None,
    ) -> ShipAgentStatus:
        heartbeat = await self._registry.get_active_heartbeat(context.account_id)
        if heartbeat is not None:
            correlation_id = str(
                (arguments or {}).get("correlation_id") or "get_shipagent_status"
            )
            try:
                result = await self._invocation_broker.invoke(
                    relay_session_id=heartbeat.relay_session_id,
                    tool_name="get_shipagent_status",
                    arguments=arguments or {},
                    audit_correlation_id=correlation_id,
                    timeout_seconds=2,
                )
            except (NoLiveRelaySession, RelayInvocationTimeout):
                return _offline_status()
            if result.status != "ok" or result.result is None:
                return _offline_status()
            try:
                desktop_status = ShipAgentStatus.model_validate(result.result)
            except ValueError:
                return _offline_status()
            desktop_status.execution_target.capabilities = [
                capability
                for capability in desktop_status.execution_target.capabilities
                if capability in PUBLIC_STATUS_CAPABILITIES
            ]
            return desktop_status
        return _offline_status()


def _offline_status() -> ShipAgentStatus:
    return ShipAgentStatus(
        status=RelayTargetState.OFFLINE,
        execution_target=ExecutionTargetStatus(
            state=RelayTargetState.OFFLINE,
            target_id=None,
            capabilities=[],
            message="No active execution target connected.",
        ),
    )
