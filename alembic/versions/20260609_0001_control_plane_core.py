"""Create control-plane persistence tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260609_0001"
down_revision = None
branch_labels = None
depends_on = None


def _schema() -> str:
    from alembic import context

    return context.config.get_section("alembic:runtime").get(
        "shipagent_control_plane_schema",
        "shipagent_private",
    )


def upgrade() -> None:
    schema = _schema()

    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    op.create_table(
        "cloud_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("auth0_subject", sa.String(length=255), nullable=False),
        sa.Column("suspended", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("auth0_subject"),
        schema=schema,
    )

    op.create_table(
        "provider_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("surface", sa.String(length=64), nullable=False),
        sa.Column("scopes_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            [f"{schema}.cloud_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("account_id", "client_id", "surface"),
        schema=schema,
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=96), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=True),
        sa.Column("provider_connection_id", sa.String(length=36), nullable=True),
        sa.Column("device_id", sa.String(length=36), nullable=True),
        sa.Column("actor_id_hash", sa.String(length=64), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_audit_events_event_type", "event_type"),
        sa.Index("ix_audit_events_account_id", "account_id"),
        sa.Index("ix_audit_events_created_at", "created_at"),
        schema=schema,
    )


def downgrade() -> None:
    schema = _schema()
    op.drop_table("audit_events", schema=schema)
    op.drop_table("provider_connections", schema=schema)
    op.drop_table("cloud_accounts", schema=schema)

