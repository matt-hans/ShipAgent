"""Fresh control-plane admission for a pinned source-free execution target.

This is not a target-side authority cache or an enrollment/dispatch protocol.
A resolved binding never by itself authorizes later worker activity.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.control_plane.auth.provider_clients import ProviderClientRegistry
from src.control_plane.execution_targets import TargetToolRequest
from src.control_plane.models import CloudAccount, ProviderConnection
from src.control_plane.relay.protocol import (
    AgentRunAuthorityBinding,
    RelayTargetState,
    RelayVersionMetadata,
)
from src.control_plane.relay.registry import RelayDeviceRegistry
from src.registry.tools.agent_runs import AGENT_RUN_TOOL_NAMES


class AgentRunAuthorityResolver:
    """Resolve current identity and exact live target, never select a replacement.

    Instances use independent SQL sessions so a prior request's ORM identity map
    cannot hide revocation. Version requirements come from a trusted qualified
    profile, never provider arguments. No production lifecycle tool opts in yet.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clients: ProviderClientRegistry,
        registry: RelayDeviceRegistry,
        account_id: str,
        execution_target_id: str,
        required_version: RelayVersionMetadata,
    ) -> None:
        self._sessions = session_factory
        self._clients = clients
        self._registry = registry
        self._account_id = account_id
        self._target_id = execution_target_id
        self._required_version = required_version.model_copy(deep=True)

    async def resolve(
        self,
        request: TargetToolRequest,
        *,
        expected: AgentRunAuthorityBinding | None = None,
    ) -> AgentRunAuthorityBinding:
        try:
            async with asyncio.timeout(1):
                return await self._resolve(request, expected=expected)
        except Exception:
            # SQL/Redis/configuration details and task input are never public.
            raise PermissionError("Agent Run authority is unavailable.") from None

    async def _resolve(
        self, request: TargetToolRequest, *, expected: AgentRunAuthorityBinding | None
    ) -> AgentRunAuthorityBinding:
        if (
            request.account_id != self._account_id
            or request.tool_name not in AGENT_RUN_TOOL_NAMES
        ):
            raise PermissionError
        async with self._sessions() as db:
            row = (
                await db.execute(
                    select(ProviderConnection, CloudAccount)
                    .join(
                        CloudAccount, CloudAccount.id == ProviderConnection.account_id
                    )
                    .where(
                        ProviderConnection.id == request.provider_connection_id,
                        ProviderConnection.account_id == self._account_id,
                        ProviderConnection.surface == request.provider_surface,
                        ProviderConnection.status == "active",
                        CloudAccount.suspended.is_(False),
                    )
                )
            ).one_or_none()
            if row is None:
                raise PermissionError
            connection, _account = row
            if self._clients.surface_for(connection.client_id) != connection.surface:
                raise PermissionError
        heartbeat = await self._registry.get_active_heartbeat(self._account_id)
        if (
            heartbeat is None
            or heartbeat.account_id != self._account_id
            or heartbeat.execution_target_id != self._target_id
            or heartbeat.state != RelayTargetState.READY
            or request.tool_name not in heartbeat.version.capabilities
            or heartbeat.version.shipagent_core_version
            != self._required_version.shipagent_core_version
            or heartbeat.version.registry_contract_version
            != self._required_version.registry_contract_version
            or heartbeat.version.ups_boundary_contract_version
            != self._required_version.ups_boundary_contract_version
        ):
            raise PermissionError
        binding = AgentRunAuthorityBinding(
            account_id=self._account_id,
            provider_connection_id=connection.id,
            provider_surface=connection.surface,
            link_generation=connection.link_generation,
            execution_target_id=self._target_id,
            device_id=heartbeat.device_id,
            relay_session_id=heartbeat.relay_session_id,
        )
        if expected is not None and binding != expected:
            raise PermissionError
        return binding
