from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.control_plane.models import ControlPlaneBase


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class ControlPlaneAuditEvent(ControlPlaneBase):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(96), index=True)
    account_id: Mapped[str | None] = mapped_column(String(36), index=True)
    provider_connection_id: Mapped[str | None] = mapped_column(String(36))
    device_id: Mapped[str | None] = mapped_column(String(36))
    actor_id_hash: Mapped[str] = mapped_column(String(64))
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )


class ControlPlaneAuthorizationLedgerEvent(ControlPlaneBase):
    """Thin evidence; deliberately no serialized payload or executable grant."""

    __tablename__ = "authorization_ledger_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(96), index=True)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    provider_connection_id: Mapped[str] = mapped_column(String(36), index=True)
    approval_request_id: Mapped[str] = mapped_column(String(128), index=True)
    preview_hash: Mapped[str] = mapped_column(String(64))
    purchase_scope_hash: Mapped[str] = mapped_column(String(64))
    authorized_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    approving_subject_hash: Mapped[str | None] = mapped_column(String(64))
    execution_target_fingerprint_hash: Mapped[str | None] = mapped_column(String(64))
    grant_transition: Mapped[str | None] = mapped_column(String(64))
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64))
    result_category: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    __table_args__ = (
        CheckConstraint(
            "authorized_amount_minor >= 0", name="ck_ledger_nonnegative_amount"
        ),
        CheckConstraint(
            "(authorized_amount_minor IS NULL AND currency IS NULL) OR (authorized_amount_minor IS NOT NULL AND currency IS NOT NULL)",
            name="ck_ledger_amount_currency_pair",
        ),
    )


class ControlPlaneLegalHold(ControlPlaneBase):
    """Explicit exception; released holds are purged with the audit retention window."""

    __tablename__ = "legal_holds"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    reason_hash: Mapped[str] = mapped_column(String(64))
    created_by_actor_hash: Mapped[str] = mapped_column(String(64))
    released_by_actor_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
