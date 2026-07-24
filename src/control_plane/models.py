from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
    __table_args__ = (UniqueConstraint("account_id", "client_id", "surface"),)


class RelayDevice(ControlPlaneBase):
    __tablename__ = "relay_devices"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("cloud_accounts.id", ondelete="CASCADE"),
    )
    device_name: Mapped[str] = mapped_column(String(255))
    public_key_pem: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(96))
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "fingerprint",
            name="uq_relay_devices_account_fingerprint",
        ),
        Index(
            "uq_relay_devices_one_active_per_account",
            "account_id",
            unique=True,
            sqlite_where=text("active = 1 AND revoked = 0"),
            postgresql_where=text("active IS TRUE AND revoked IS FALSE"),
        ),
    )
