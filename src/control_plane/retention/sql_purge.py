"""Daily bounded SQL retention; account locks serialize explicit hold placement."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select

from src.control_plane.audit.models import (
    ControlPlaneAuditEvent,
    ControlPlaneAuthorizationLedgerEvent,
    ControlPlaneLegalHold,
    utc_now,
)
from src.control_plane.models import CloudAccount


@dataclass(frozen=True)
class SqlPurgeResult:
    audit_events_deleted: int
    authorization_ledger_events_deleted: int
    released_legal_holds_deleted: int


async def purge_expired_authorization_audit(
    *, session, retention_days: int = 90, now: datetime | None = None
) -> SqlPurgeResult:
    if type(retention_days) is not int or not 30 <= retention_days <= 365:
        raise ValueError("retention must be between 30 and 365 days")
    now = now or utc_now()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("retention time must be timezone aware")
    cutoff = now - timedelta(days=retention_days)
    # All writers that can establish legal holds use these same account row locks.
    await session.execute(
        select(CloudAccount.id).order_by(CloudAccount.id).with_for_update()
    )
    active_accounts = select(ControlPlaneLegalHold.account_id).where(
        ControlPlaneLegalHold.released_at.is_(None)
    )
    counts = []
    for model in (ControlPlaneAuditEvent, ControlPlaneAuthorizationLedgerEvent):
        result = await session.execute(
            delete(model).where(
                model.created_at < cutoff,
                or_(
                    model.account_id.is_(None), model.account_id.not_in(active_accounts)
                ),
            )
        )
        counts.append(result.rowcount or 0)
    released = await session.execute(
        delete(ControlPlaneLegalHold).where(
            ControlPlaneLegalHold.released_at < cutoff,
            ControlPlaneLegalHold.account_id.not_in(active_accounts),
        )
    )
    return SqlPurgeResult(*counts, released_legal_holds_deleted=released.rowcount or 0)
