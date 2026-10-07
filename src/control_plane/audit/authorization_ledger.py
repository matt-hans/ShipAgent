"""Allowlisted evidence only; SQL records are never executable authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from src.control_plane.audit.models import ControlPlaneAuthorizationLedgerEvent

from src.control_plane.audit.hash_validation import (
    require_account_id,
    require_connection_id,
    require_reference,
    require_sha256_hex,
)
from src.registry.identifiers import ShipAgentIdFamily
from src.registry.tools.public import RATE_CURRENCY_CODES


@dataclass(frozen=True, repr=False)
class AuthorizationMetadata:
    """Safe hashes and opaque references shared by ephemeral state and SQL audit."""

    account_id: str
    provider_connection_id: str
    approval_request_id: str
    preview_hash: str
    purchase_scope_hash: str
    authorized_amount_minor: int | None = None
    currency: str | None = None
    approving_subject_hash: str | None = None
    execution_target_fingerprint_hash: str | None = None
    idempotency_key_hash: str | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        require_account_id(self.account_id)
        require_connection_id(self.provider_connection_id)
        require_reference(self.approval_request_id, ShipAgentIdFamily.APPROVAL_REQUEST)
        require_sha256_hex(self.preview_hash)
        require_sha256_hex(self.purchase_scope_hash)
        for value in (
            self.approving_subject_hash,
            self.execution_target_fingerprint_hash,
            self.idempotency_key_hash,
        ):
            if value is not None:
                require_sha256_hex(value)
        if self.correlation_id is not None:
            require_reference(self.correlation_id, ShipAgentIdFamily.CORRELATION)
        amount = self.authorized_amount_minor
        if amount is not None and (type(amount) is not int or not 0 <= amount < 2**63):
            raise ValueError("invalid authorized amount")
        if (amount is None) != (self.currency is None):
            raise ValueError("amount and currency must be supplied together")
        if self.currency is not None and self.currency not in RATE_CURRENCY_CODES:
            raise ValueError("unsupported canonical currency")


class AuthorizationLedgerError(Exception):
    def __init__(self):
        super().__init__("authorization_ledger_unavailable")


class AuthorizationLedgerService:
    """Caller owns the SQL transaction and MUST commit before enabling Redis state."""

    EVENT_TYPES = frozenset(
        {
            "approval_request_created",
            "approval_decision_recorded",
            "execution_grant_transition",
            "provider_tool_result",
        }
    )
    GRANT_TRANSITIONS = frozenset(
        {
            "requested",
            "approved",
            "rejected",
            "reserved",
            "consumed",
            "expired",
            "revoked",
            "replay_rejected",
            "released",
            "reconciliation_pending",
        }
    )
    RESULT_CATEGORIES = frozenset(
        {
            "success",
            "blocked",
            "unavailable",
            "processing_unknown",
            "validation",
            "authorization",
            "provider",
            "policy",
            "rate_limit",
            "error",
        }
    )

    @classmethod
    async def record(
        cls,
        *,
        session: AsyncSession,
        metadata: AuthorizationMetadata,
        event_type: str,
        grant_transition: str | None = None,
        result_category: str | None = None,
    ) -> ControlPlaneAuthorizationLedgerEvent:
        from dataclasses import asdict

        from sqlalchemy import select
        from sqlalchemy.exc import SQLAlchemyError

        from src.control_plane.audit.models import ControlPlaneAuthorizationLedgerEvent
        from src.control_plane.models import ProviderConnection
        from src.control_plane.retention.legal_hold import lock_account

        if type(metadata) is not AuthorizationMetadata:
            raise ValueError("invalid authorization metadata")
        metadata.__post_init__()
        for value, permitted in (
            (event_type, cls.EVENT_TYPES),
            (grant_transition, cls.GRANT_TRANSITIONS | {None}),
            (result_category, cls.RESULT_CATEGORIES | {None}),
        ):
            if not isinstance(value, (str, type(None))) or value not in permitted:
                raise ValueError("unsupported authorization ledger code")
        if event_type is None:
            raise ValueError("unsupported authorization ledger code")
        try:
            await lock_account(session, metadata.account_id)
            connection = await session.scalar(
                select(ProviderConnection.id)
                .where(
                    ProviderConnection.id == metadata.provider_connection_id,
                    ProviderConnection.account_id == metadata.account_id,
                )
                .with_for_update()
            )
            if connection is None:
                raise ValueError("provider connection does not belong to account")
            event = ControlPlaneAuthorizationLedgerEvent(
                **asdict(metadata),
                event_type=event_type,
                grant_transition=grant_transition,
                result_category=result_category,
            )
            session.add(event)
            await session.flush()
            return event
        except SQLAlchemyError:
            raise AuthorizationLedgerError() from None

    @classmethod
    async def cleanup_for_account(
        cls, *, session: AsyncSession, account_id: str
    ) -> int:
        from sqlalchemy import delete

        from src.control_plane.audit.models import ControlPlaneAuthorizationLedgerEvent
        from src.control_plane.retention.legal_hold import (
            LegalHoldService,
            lock_account,
        )

        require_account_id(account_id)
        await lock_account(session, account_id, required=False)
        if await LegalHoldService.has_active_hold(
            session=session, account_id=account_id
        ):
            raise PermissionError("active legal hold")
        result = await session.execute(
            delete(ControlPlaneAuthorizationLedgerEvent).where(
                ControlPlaneAuthorizationLedgerEvent.account_id == account_id
            )
        )
        return result.rowcount or 0
