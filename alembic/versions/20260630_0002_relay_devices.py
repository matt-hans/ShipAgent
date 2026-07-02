"""Create relay device persistence table."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260630_0002"
down_revision = "20260609_0001"
branch_labels = None
depends_on = None


def _schema() -> str | None:
    from alembic import context
    from src.control_plane.db import resolve_control_plane_schema

    if "shipagent_control_plane_schema" in context.config.attributes:
        return context.config.attributes["shipagent_control_plane_schema"]
    runtime_section = context.config.get_section("alembic:runtime") or {}
    return resolve_control_plane_schema(
        dialect_name=op.get_context().dialect.name,
        configured_schema=runtime_section.get("shipagent_control_plane_schema"),
    )


def upgrade() -> None:
    schema = _schema()

    op.create_table(
        "relay_devices",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("device_name", sa.String(length=255), nullable=False),
        sa.Column("public_key_pem", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=96), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            [f"{schema}.cloud_accounts.id" if schema else "cloud_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "account_id",
            "fingerprint",
            name="uq_relay_devices_account_fingerprint",
        ),
        schema=schema,
    )
    op.create_index(
        "uq_relay_devices_one_active_per_account",
        "relay_devices",
        ["account_id"],
        unique=True,
        schema=schema,
        sqlite_where=sa.text("active = 1 AND revoked = 0"),
        postgresql_where=sa.text("active IS TRUE AND revoked IS FALSE"),
    )


def downgrade() -> None:
    schema = _schema()
    op.drop_index(
        "uq_relay_devices_one_active_per_account",
        table_name="relay_devices",
        schema=schema,
    )
    op.drop_table("relay_devices", schema=schema)
