"""Explicit, transactionally audited legal holds, serialized with account cleanup."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.control_plane.audit.hash_validation import (
    require_account_id,
    require_sha256_hex,
)
from src.control_plane.audit.models import ControlPlaneLegalHold, utc_now
from src.control_plane.audit.service import ControlPlaneAuditService
from src.control_plane.models import CloudAccount


async def lock_account(
    session: AsyncSession, account_id: str, *, required: bool = True
) -> CloudAccount | None:
    require_account_id(account_id)
    account = await session.scalar(
        select(CloudAccount).where(CloudAccount.id == account_id).with_for_update()
    )
    if required and account is None:
        raise ValueError("account unavailable")
    return account


class LegalHoldService:
    @classmethod
    async def has_active_hold(cls, *, session: AsyncSession, account_id: str) -> bool:
        require_account_id(account_id)
        return (
            await session.scalar(
                select(ControlPlaneLegalHold.id)
                .where(
                    ControlPlaneLegalHold.account_id == account_id,
                    ControlPlaneLegalHold.released_at.is_(None),
                )
                .limit(1)
            )
            is not None
        )

    @classmethod
    async def place(
        cls,
        *,
        session: AsyncSession,
        account_id: str,
        reason_hash: str,
        actor_id_hash: str,
    ) -> ControlPlaneLegalHold:
        require_sha256_hex(reason_hash)
        require_sha256_hex(actor_id_hash)
        await lock_account(session, account_id)
        hold = ControlPlaneLegalHold(
            account_id=account_id,
            reason_hash=reason_hash,
            created_by_actor_hash=actor_id_hash,
        )
        session.add(hold)
        await ControlPlaneAuditService.record(
            session=session,
            event_type="legal_hold_placed",
            actor_id_hash=actor_id_hash,
            account_id=account_id,
            hashes={"request_hash": reason_hash},
            safe_fields={"status": "active"},
        )
        await session.flush()
        return hold

    @classmethod
    async def release(
        cls, *, session: AsyncSession, hold_id: str, actor_id_hash: str
    ) -> ControlPlaneLegalHold:
        require_account_id(hold_id)
        require_sha256_hex(actor_id_hash)
        hold = await session.get(ControlPlaneLegalHold, hold_id)
        if hold is None:
            raise LookupError("legal hold unavailable")
        await lock_account(session, hold.account_id)
        # Refresh after waiting on the account lock; concurrent release is idempotent.
        await session.refresh(hold)
        if hold.released_at is None:
            hold.released_at = utc_now()
            hold.released_by_actor_hash = actor_id_hash
            await ControlPlaneAuditService.record(
                session=session,
                event_type="legal_hold_released",
                actor_id_hash=actor_id_hash,
                account_id=hold.account_id,
                hashes={"request_hash": hold.reason_hash},
                safe_fields={"status": "inactive"},
            )
            await session.flush()
        return hold
