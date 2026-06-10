from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class ControlPlaneBase(DeclarativeBase):
    pass


class CloudAccount(ControlPlaneBase):
    __tablename__ = "cloud_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    auth0_subject: Mapped[str] = mapped_column(String(255), unique=True)
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class ProviderConnection(ControlPlaneBase):
    __tablename__ = "provider_connections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("cloud_accounts.id", ondelete="CASCADE"),
    )
    client_id: Mapped[str] = mapped_column(String(255))
    surface: Mapped[str] = mapped_column(String(64))
    scopes_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    __table_args__ = (
        UniqueConstraint("account_id", "client_id", "surface"),
    )
