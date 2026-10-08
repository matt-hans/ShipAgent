from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from src.control_plane.relay.invocations import (
    NoLiveRelaySession,
    RelayInvocationBroker,
    RelayInvocationBusy,
    RelayInvocationTimeout,
)
from src.control_plane.relay.protocol import (
    ExecutionTargetStatus,
    InvocationIdentity,
    RelayTargetState,
    ShipAgentStatus,
    TargetAcceptanceEvidence,
)
from src.control_plane.relay.registry import RelayDeviceRegistry
from src.registry.vocabulary import PUBLIC_STATUS_CAPABILITIES


@dataclass(frozen=True)
class TargetToolRequest:
    account_id: str
    provider_connection_id: str
    provider_surface: str
    tool_name: str
    arguments: dict[str, Any]
    correlation_id: str


class ExecutionTarget(Protocol):
    async def invoke(self, request: TargetToolRequest) -> dict[str, Any]:
        """Invoke a provider-neutral workflow tool on the active target."""


class LoopbackExecutionTarget:
    def __init__(
        self,
        *,
        capabilities: list[str] | None = None,
        execution_target_id: str = "loopback",
    ) -> None:
        self._capabilities = list(capabilities or [])
        self._execution_target_id = execution_target_id

    async def invoke(self, request: TargetToolRequest) -> dict[str, Any]:
        if request.tool_name != "get_shipagent_status":
            return {
                "code": "unsupported_tool",
                "message": "Target tool is not supported.",
            }
        return ShipAgentStatus(
            status=RelayTargetState.READY,
            execution_target=ExecutionTargetStatus(
                state=RelayTargetState.READY,
                target_id=self._execution_target_id,
                capabilities=list(self._capabilities),
                message=None,
            ),
        ).model_dump(mode="json", by_alias=True)


class RelayExecutionTarget:
    def __init__(
        self,
        registry: RelayDeviceRegistry,
        invocation_broker: RelayInvocationBroker | None = None,
    ) -> None:
        self._registry = registry
        self._invocation_broker = invocation_broker or RelayInvocationBroker()

    async def invoke(self, request: TargetToolRequest) -> dict[str, Any]:
        heartbeat = await self._registry.get_active_heartbeat(request.account_id)
        if heartbeat is None:
            if request.tool_name == "get_shipagent_status":
                return _offline_status().model_dump(mode="json", by_alias=True)
            raise NoLiveRelaySession("no active execution target connected")

        try:
            result = await self._invocation_broker.invoke(
                relay_session_id=heartbeat.relay_session_id,
                tool_name=request.tool_name,
                arguments=request.arguments,
                audit_correlation_id=request.correlation_id,
                timeout_seconds=2,
            )
        except (NoLiveRelaySession, RelayInvocationTimeout, RelayInvocationBusy):
            if request.tool_name == "get_shipagent_status":
                return _offline_status().model_dump(mode="json", by_alias=True)
            raise

        if request.tool_name != "get_shipagent_status":
            return (
                (result.result or {}) if result.status == "ok" else (result.error or {})
            )
        if result.status != "ok" or result.result is None:
            return _offline_status().model_dump(mode="json", by_alias=True)
        try:
            desktop_status = ShipAgentStatus.model_validate(result.result)
        except ValueError:
            return _offline_status().model_dump(mode="json", by_alias=True)
        public_capabilities = [
            capability
            for capability in desktop_status.execution_target.capabilities
            if capability in PUBLIC_STATUS_CAPABILITIES
        ]
        return desktop_status.model_copy(
            update={
                "execution_target": desktop_status.execution_target.model_copy(
                    update={"capabilities": public_capabilities}
                )
            }
        ).model_dump(mode="json", by_alias=True)


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


class DurableExecutionTarget(Protocol):
    """Optional acceptance/recovery capability; invoke-only targets do not qualify.

    The adapter owns the authenticated exact-target session and increasing
    transport sequence. It must use the existing RelayInvocationEnvelope fields
    (datetime deadline_at, canonical input hash), preserve the supplied server
    invocation/idempotency identity, and never retry a dispatch automatically.
    No current production relay or desktop target opts into this protocol.
    Adapters authenticate attempt_generation in dispatch, lookup and evidence.
    Durable nonacceptance fences are permanent per generation; a later generation
    requires positive prior rejection, while idempotent acceptance is unique
    across every generation of the original purchase key.

    """

    execution_target_id: str

    async def dispatch_invocation(
        self,
        *,
        identity: InvocationIdentity,
        arguments: dict[str, object],
        deadline_at: datetime,
    ) -> None:
        """Send once. Return is transport delivery, never durable acceptance."""

    async def get_acceptance(
        self, identity: InvocationIdentity
    ) -> TargetAcceptanceEvidence:
        """Read exact-key durable evidence. Missing/unreachable means unknown.

        A negative answer requires an existing durable rejection fence that also
        prevents delayed original sends from accepting. This operation must not
        invoke/purchase, select a replacement target, or mint a new key.
        """
