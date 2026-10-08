"""Committed hashed evidence and publication coordination for dormant grants."""

import hashlib
from contextlib import asynccontextmanager
from dataclasses import fields

from sqlalchemy import select, text

from src.control_plane.audit.authorization_ledger import (
    AuthorizationLedgerService,
    AuthorizationMetadata,
)
from src.control_plane.audit.models import ControlPlaneAuthorizationLedgerEvent
from src.control_plane.models import ProviderConnection
from src.control_plane.retention.legal_hold import lock_account


class GrantLedger:
    """Use Plan 4 ledger/schema; never load SQL history to recreate authority."""

    def __init__(self, session_factory):
        self.sessions = session_factory

    @asynccontextmanager
    async def active_owner(self, context):
        async with self.sessions() as session, session.begin():
            await session.execute(text("SET LOCAL lock_timeout = '1500ms'"))
            await session.execute(text("SET LOCAL statement_timeout = '1500ms'"))
            account = await lock_account(session, context.account_id)
            connection = await session.scalar(
                select(ProviderConnection)
                .where(
                    ProviderConnection.id == context.provider_connection_id,
                    ProviderConnection.account_id == context.account_id,
                )
                .with_for_update()
            )
            if (
                account.suspended
                or account.auth0_subject != context.subject
                or connection is None
                or connection.status != "active"
                or connection.client_id != context.client_id
                or connection.surface != context.provider_surface
            ):
                raise ValueError("authorization owner unavailable")
            yield session

    async def _record(self, session, metadata, transition):
        if type(metadata) is not AuthorizationMetadata:
            raise ValueError("authorization evidence unavailable")
        metadata.__post_init__()
        # Account locking serializes exactly-once accepted evidence across
        # recovery processes, without adding a parallel ledger or SQL authority.
        await lock_account(session, metadata.account_id)
        if transition == "consumed":
            recorded = await session.scalar(
                select(ControlPlaneAuthorizationLedgerEvent.id)
                .where(
                    ControlPlaneAuthorizationLedgerEvent.account_id
                    == metadata.account_id,
                    ControlPlaneAuthorizationLedgerEvent.provider_connection_id
                    == metadata.provider_connection_id,
                    ControlPlaneAuthorizationLedgerEvent.approval_request_id
                    == metadata.approval_request_id,
                    ControlPlaneAuthorizationLedgerEvent.purchase_scope_hash
                    == metadata.purchase_scope_hash,
                    ControlPlaneAuthorizationLedgerEvent.idempotency_key_hash
                    == metadata.idempotency_key_hash,
                    ControlPlaneAuthorizationLedgerEvent.grant_transition == "consumed",
                )
                .limit(1)
            )
            if recorded is not None:
                return
        await AuthorizationLedgerService.record(
            session=session,
            metadata=metadata,
            event_type="execution_grant_transition",
            grant_transition=transition,
        )

    async def record(self, metadata, transition, *, context=None):
        if context is not None:
            async with self.active_owner(context) as session:
                await self._record(session, metadata, transition)
        else:
            async with self.sessions() as session, session.begin():
                await session.execute(text("SET LOCAL lock_timeout = '1500ms'"))
                await session.execute(text("SET LOCAL statement_timeout = '1500ms'"))
                await self._record(session, metadata, transition)

    async def enable(self, *, context, metadata, transition, operation):
        # Commit required evidence before a state change could allow use. Fresh
        # locks then serialize publication with account deletion. Only existing
        # Redis keys may be changed: late CAS after cleanup cannot resurrect one.
        await self.record(metadata, transition, context=context)
        async with self.active_owner(context):
            return await operation()

    async def recovery_metadata(self, identity, *, context):
        """Evidence-only lookup. This API never returns or rebuilds a grant."""
        if (
            identity.account_id != context.account_id
            or identity.provider_connection_id != context.provider_connection_id
            or identity.purchase_scope_hash is None
            or identity.preview_hash is None
            or identity.execution_target_fingerprint_hash is None
        ):
            raise ValueError("authorization evidence unavailable")
        async with self.active_owner(context) as session:
            event = await session.scalar(
                select(ControlPlaneAuthorizationLedgerEvent)
                .where(
                    ControlPlaneAuthorizationLedgerEvent.account_id
                    == identity.account_id,
                    ControlPlaneAuthorizationLedgerEvent.provider_connection_id
                    == identity.provider_connection_id,
                    ControlPlaneAuthorizationLedgerEvent.approval_request_id
                    == identity.approval_request_id,
                    ControlPlaneAuthorizationLedgerEvent.idempotency_key_hash
                    == hashlib.sha256(identity.idempotency_key.encode()).hexdigest(),
                    ControlPlaneAuthorizationLedgerEvent.execution_target_fingerprint_hash
                    == identity.execution_target_fingerprint_hash.removeprefix(
                        "sha256:"
                    ),
                    ControlPlaneAuthorizationLedgerEvent.purchase_scope_hash
                    == identity.purchase_scope_hash.removeprefix("sha256:"),
                    ControlPlaneAuthorizationLedgerEvent.preview_hash
                    == identity.preview_hash.removeprefix("sha256:"),
                    ControlPlaneAuthorizationLedgerEvent.grant_transition.in_(
                        ("reserved", "consumed")
                    ),
                )
                .order_by(ControlPlaneAuthorizationLedgerEvent.created_at.desc())
                .limit(1)
            )
            if event is None:
                raise ValueError("authorization evidence unavailable")
            return AuthorizationMetadata(
                **{
                    field.name: getattr(event, field.name)
                    for field in fields(AuthorizationMetadata)
                }
            )
