from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import String, Text
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
    created_at: Mapped[datetime] = mapped_column(default=utc_now, index=True)

